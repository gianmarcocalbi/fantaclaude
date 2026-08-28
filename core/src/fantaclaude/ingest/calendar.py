"""Fixtures: the Serie A calendar and every European midweek tie of an Italian club.

Serie A comes from fantacalcio.it's public calendario pages, one per
giornata, read as schema.org microdata -- observed 2026-08-28: each match is
a SportsEvent carrying homeTeam/awayTeam names spelled as the listone, an
ISO startDate, the kick-off hour in Europe/Rome, the stadium and a match
link .../calendario/<giornata>/<season label>/<slug>/<id>; every match is
rendered twice (large and compact pill) and deduped on the id; only the
current season is served. Europe comes from UEFA's public match API, paged
by offset and filtered to matches with an ITA side: competition ids 1 (UCL),
14 (UEL), 2019 (UECL); seasonYear is the season's ending year.

Scores are not modelled (`results` is Phase 3): a fixture row is the
schedule, and a snapshot is appended only when the schedule changed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes, polite_pause
from fantaclaude.ingest.names import resolve_team
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.league.settings import canonical_json
from fantaclaude.model.seasons import season_id_from_label, uefa_season_year
from fantaclaude.timeutil import to_db

SOURCE_SERIE_A = "fantacalcio.it:/serie-a/calendario/<giornata>"
SOURCE_UEFA = "uefa:GET match.uefa.com/v5/matches"
SERIE_A_URL = "https://www.fantacalcio.it/serie-a/calendario/{giornata}"
UEFA_URL = "https://match.uefa.com/v5/matches"
UEFA_COMPETITIONS = {"UCL": "1", "UEL": "14", "UECL": "2019"}
COMPETITIONS = ("SA", *UEFA_COMPETITIONS)
UEFA_PAGE = 200
ROME = ZoneInfo("Europe/Rome")
VOID_TAGS = frozenset({"meta", "img", "br", "input", "link", "hr", "source"})
UEFA_REQUIRED = ("id", "homeTeam", "awayTeam", "matchday", "round")
_DROP = frozenset({"playerEvents", "referees", "relatedMatches", "translations"})
_HOURS = re.compile(r"(\d{1,2}):(\d{2})")


class CalendarShapeError(ValueError):
    """A page or payload is not the calendar this adapter was written against."""


@dataclass(frozen=True)
class FixtureRow:
    competition: str
    season_id: int
    source_id: str
    round: str                       # "2" for a giornata; "MD3", "MD1 - PO" for UEFA
    giornata: int | None
    phase: str | None                # UEFA: QUALIFYING | TOURNAMENT
    kickoff: datetime | None         # aware UTC; None when unscheduled
    home: str
    away: str
    home_domestic: bool              # a Serie A club, which must resolve to a listone short code
    away_domestic: bool
    raw: dict[str, Any]

    def canonical(self) -> dict[str, Any]:
        return {"competition": self.competition, "season_id": self.season_id, "source_id": self.source_id,
                "round": self.round, "giornata": self.giornata, "phase": self.phase,
                "kickoff": self.kickoff.isoformat() if self.kickoff else None,
                "home": self.home, "away": self.away}


def kickoff_rome(start_date: str | None, hours: str | None) -> datetime | None:
    """An ISO date and an "HH:MM" in Europe/Rome -> aware UTC; None when either is missing."""
    if not start_date:
        return None
    match = _HOURS.fullmatch((hours or "").strip())
    if not match:
        return None
    day = datetime.fromisoformat(start_date)
    return day.replace(hour=int(match.group(1)), minute=int(match.group(2)), tzinfo=ROME).astimezone(UTC)


class _SerieAPageParser(HTMLParser):
    """Collects every schema.org SportsEvent on a calendario page.

    Team names come from the meta[itemprop=name] inside the homeTeam/awayTeam
    labels, so the parser tracks which label it is inside by element depth.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, Any]] = []
        self._event: dict[str, Any] | None = None
        self._depth = 0
        self._side: str | None = None
        self._side_depth = 0
        self._text_target: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=True)

    def _open(self, tag: str, a: dict[str, str | None], *, void: bool) -> None:
        if str(a.get("itemtype") or "").endswith("SportsEvent"):
            self._event = {"status": a.get("data-match-status"), "matchweek": None, "home": None,
                           "away": None, "url": None, "start_date": None, "hours": None,
                           "stadium": None, "name": None}
            self._depth = 0
            self._side = None
        if self._event is None:
            return
        if not void:
            self._depth += 1
        prop = a.get("itemprop")
        classes = str(a.get("class") or "").split()
        if prop in ("homeTeam", "awayTeam") and not void:
            self._side = "home" if prop == "homeTeam" else "away"
            self._side_depth = self._depth
        elif tag == "meta" and prop == "name":
            if self._side:
                self._event[self._side] = a.get("content")
            elif self._event["name"] is None:
                self._event["name"] = a.get("content")
        elif tag == "meta" and prop == "startDate":
            self._event["start_date"] = a.get("content")
        elif tag == "a" and "match-score" in classes:
            self._event["url"] = a.get("href")
        elif tag == "span" and "hours" in classes:
            self._text_target = "hours"
        elif tag == "span" and prop == "location":
            self._text_target = "stadium"
        elif tag == "div" and "matchweek" in classes:
            self._text_target = "matchweek"

    def handle_endtag(self, tag: str) -> None:
        if self._event is None or tag in VOID_TAGS:
            return
        if self._side and self._depth == self._side_depth:
            self._side = None
        self._text_target = None
        self._depth -= 1
        if self._depth == 0:
            self.events.append(self._event)
            self._event = None

    def handle_data(self, data: str) -> None:
        if self._event is not None and self._text_target:
            key = self._text_target
            self._event[key] = ((self._event[key] or "") + data).strip()


def parse_serie_a_page(html_text: str, *, season_id: int) -> list[FixtureRow]:
    parser = _SerieAPageParser()
    parser.feed(html_text)
    if not parser.events:
        raise CalendarShapeError("no SportsEvent on the page -- the calendario layout changed")
    rows: dict[str, FixtureRow] = {}
    for event in parser.events:
        url = event["url"]
        if not url:
            raise CalendarShapeError("a SportsEvent without a match link")
        parts = url.rstrip("/").split("/")
        if len(parts) < 4 or not parts[-1].isdigit() or not parts[-4].isdigit():
            raise CalendarShapeError(f"unexpected match link {url!r}")
        source_id, label, giornata = parts[-1], parts[-3], parts[-4]
        try:
            page_season = season_id_from_label(label)
        except ValueError:
            raise CalendarShapeError(f"unexpected season label in {url!r}") from None
        if page_season != season_id:
            raise CalendarShapeError(
                f"the page is season {label}, not {season_id} -- fantacalcio.it serves the current season only")
        if event["matchweek"] != giornata:
            raise CalendarShapeError(f"matchweek {event['matchweek']!r} disagrees with the link's giornata {giornata}")
        if not event["home"] or not event["away"]:
            raise CalendarShapeError(f"match {source_id}: missing a team name")
        rows[source_id] = FixtureRow(
            competition="SA", season_id=season_id, source_id=source_id, round=giornata,
            giornata=int(giornata), phase=None, kickoff=kickoff_rome(event["start_date"], event["hours"]),
            home=event["home"], away=event["away"], home_domestic=True, away_domestic=True, raw=dict(event))
    return sorted(rows.values(), key=lambda r: (r.kickoff or datetime.max.replace(tzinfo=UTC), r.source_id))


async def fetch_serie_a(http: httpx.AsyncClient, store: RawStore, *, season_id: int,
                        giornate: Any) -> list[RawFile]:
    raws: list[RawFile] = []
    for index, giornata in enumerate(giornate):
        if index:
            await polite_pause()
        data = await fetch_bytes(http, SERIE_A_URL.format(giornata=giornata))
        raws.append(store.write_bytes("calendar", data, ext="html", label=f"sa-{season_id}-{giornata:02d}"))
    return raws


_SA_LABEL = re.compile(r"-sa-(?P<season>\d+)-(?P<giornata>\d+)\.\w+$")


def load_serie_a(paths: list[Path], *, season_id: int) -> list[FixtureRow]:
    """Filter each page down to the giornata fetch_serie_a fetched it for.

    Observed 2026-08-29: a page whose giornata has already been played also
    advertises the next one (captured/calendario-2026-27-giornata-1.html
    carries ten giornata-1 matches and ten giornata-2 preview pills) -- "one
    page, one giornata" does not hold in general. Only "the giornata the page
    was fetched for is on it" does, and that giornata is the file's own label
    (fetch_serie_a writes "sa-<season>-<giornata>"), not something to infer
    from the page's content. A page missing its own giornata is still a
    genuine layout change and raises loud, same as before.
    """
    rows: list[FixtureRow] = []
    seen: set[int] = set()
    for path in paths:
        match = _SA_LABEL.search(path.name)
        if not match or int(match.group("season")) != season_id:
            raise CalendarShapeError(f"{path}: not a Serie A page written by fetch_serie_a")
        requested = int(match.group("giornata"))
        if requested in seen:
            raise CalendarShapeError(f"{path}: giornata {requested} twice in one load")
        seen.add(requested)
        page = parse_serie_a_page(path.read_text(encoding="utf-8"), season_id=season_id)
        wanted = [row for row in page if row.giornata == requested]
        if not wanted:
            raise CalendarShapeError(
                f"{path}: giornata {requested} is not on its own page -- found {sorted({r.giornata for r in page})}")
        rows.extend(wanted)
    return rows


async def fetch_uefa(http: httpx.AsyncClient, store: RawStore, *, season_id: int,
                     competition: str) -> list[RawFile]:
    raws: list[RawFile] = []
    offset = 0
    while True:
        if raws:
            await polite_pause()
        data = await fetch_bytes(http, UEFA_URL, params={
            "competitionId": UEFA_COMPETITIONS[competition], "seasonYear": str(uefa_season_year(season_id)),
            "offset": str(offset), "limit": str(UEFA_PAGE)})
        try:
            payload = json.loads(data)
        except ValueError:
            raise CalendarShapeError("UEFA answered something that is not JSON") from None
        if not isinstance(payload, list):
            raise CalendarShapeError("UEFA payload is not a list of matches")
        raws.append(store.write("calendar", {"competition": competition, "season_id": season_id,
                                             "offset": offset, "matches": payload},
                                label=f"{competition.lower()}-{season_id}-{len(raws):02d}"))
        if len(payload) < UEFA_PAGE:
            return raws
        offset += UEFA_PAGE


def _slim(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _slim(v) for k, v in value.items() if k not in _DROP and not str(k).endswith("LogoUrl")}
    if isinstance(value, list):
        return [_slim(v) for v in value]
    return value


def load_uefa(paths: list[Path]) -> list[FixtureRow]:
    """Pages as fetch_uefa writes them; a file may also bundle several pages in a list."""
    rows: dict[str, FixtureRow] = {}
    for path in paths:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        for doc in (loaded if isinstance(loaded, list) else [loaded]):
            if not isinstance(doc, dict) or not isinstance(doc.get("matches"), list) \
                    or doc.get("competition") not in UEFA_COMPETITIONS or not isinstance(doc.get("season_id"), int):
                raise CalendarShapeError(f"{path}: not a UEFA page written by fetch_uefa")
            rows.update(_uefa_rows(doc, path))
    return sorted(rows.values(), key=lambda r: (r.kickoff or datetime.max.replace(tzinfo=UTC), r.source_id))


def _uefa_rows(doc: dict[str, Any], path: Path) -> dict[str, FixtureRow]:
    rows: dict[str, FixtureRow] = {}
    for match in doc["matches"]:
        missing = [k for k in UEFA_REQUIRED if k not in match]
        if missing:
            raise CalendarShapeError(f"{path}: match {match.get('id')} lacks {missing}")
        home, away = match["homeTeam"], match["awayTeam"]
        domestic = (home.get("countryCode") == "ITA", away.get("countryCode") == "ITA")
        if not any(domestic):
            continue
        when = (match.get("kickOffTime") or {}).get("dateTime")
        kickoff = datetime.fromisoformat(when).astimezone(UTC) if when else None
        rows[str(match["id"])] = FixtureRow(
            competition=doc["competition"], season_id=doc["season_id"], source_id=str(match["id"]),
            round=str(match["matchday"].get("name") or ""), giornata=None,
            phase=match["round"].get("phase"), kickoff=kickoff,
            home=str(home.get("internationalName") or ""), away=str(away.get("internationalName") or ""),
            home_domestic=domestic[0], away_domestic=domestic[1], raw=_slim(match))
    return rows


def schedule_hash(rows: list[FixtureRow]) -> str:
    payload = canonical_json(sorted((r.canonical() for r in rows), key=lambda c: c["source_id"]))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FixtureIngestResult:
    snapshot_id: int | None
    competition: str
    season_id: int
    inserted: int
    skipped_unchanged: bool
    sha256: str
    raw_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "competition": self.competition, "season_id": self.season_id,
                "inserted": self.inserted, "skipped_unchanged": self.skipped_unchanged,
                "sha256": self.sha256, "raw_paths": self.raw_paths}


def record_fixtures(con: duckdb.DuckDBPyConnection, competition: str, season_id: int,
                    rows: list[FixtureRow], raws: list[RawFile], *, teams: dict[str, str],
                    team_aliases: dict[str, str]) -> FixtureIngestResult:
    """Append a snapshot when the schedule differs from the latest one.

    A Serie A club the listone cannot resolve is an error, not a flag: it is
    a spelling drift (alias it) or a listone that needs re-ingesting, and
    either way every row for that club would silently fall out of
    v_european_ties.
    """
    digest = schedule_hash(rows)
    latest = con.execute(
        "SELECT snapshot_id, sha256 FROM fixture_snapshots WHERE competition = ? AND season_id = ? "
        "ORDER BY snapshot_id DESC LIMIT 1", [competition, season_id]).fetchone()
    paths = [str(r.path) for r in raws]
    if latest is not None and latest[1] == digest:
        return FixtureIngestResult(latest[0], competition, season_id, 0, True, digest, paths)
    section = "fantacalcio_teams" if competition == "SA" else "uefa_teams"
    records: list[list[Any]] = []
    for row in rows:
        shorts: list[str | None] = []
        for name, domestic in ((row.home, row.home_domestic), (row.away, row.away_domestic)):
            short = resolve_team(name, teams, team_aliases) if domestic else None
            if domestic and short is None:
                raise CalendarShapeError(
                    f"{competition} {season_id}: club {name!r} is not in the listone -- if it is a spelling, "
                    f"add `{section}: {{{name}: <listone name>}}` to kb/rules/aliases.yml")
            shorts.append(short)
        records.append([None, competition, season_id, row.source_id, row.round, row.giornata, row.phase,
                        to_db(row.kickoff) if row.kickoff else None, row.home, row.away, shorts[0], shorts[1],
                        json.dumps(row.raw, ensure_ascii=False)])
    fetched_at = max(r.fetched_at for r in raws)
    source = SOURCE_SERIE_A if competition == "SA" else SOURCE_UEFA
    con.begin()
    try:
        snapshot_id = con.execute(
            "INSERT INTO fixture_snapshots (competition, season_id, fetched_at, source, raw_paths, sha256, row_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING snapshot_id",
            [competition, season_id, to_db(fetched_at), source, paths, digest, len(rows)]).fetchone()[0]
        for record in records:
            record[0] = snapshot_id
        if records:
            con.executemany("INSERT INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)", records)
    except Exception:
        con.rollback()
        raise
    con.commit()
    return FixtureIngestResult(snapshot_id, competition, season_id, len(rows), False, digest, paths)
