"""The probabili formazioni page: every player's published probability of
playing, keyed by the listone id in his link (spec, "The news adapter").

Captured 2026-09-04 (`captured/probabili-2026-27-giornata-3.html`, one
anonymous request; the golden fixture `probabili_sample.html` is the
Genoa-Como and Fiorentina-Torino cards trimmed from it -- the fixture's two
cards, not the capture's ten). The page carries all ten matches of the next
giornata twice over: a `<nav id="match-menu">` strip lists every match as a
bare score/date teaser (no lineup), and the `<ul class="match-list">` below
it holds the actual match cards. On this capture all ten of those cards were
already compiled with a lineup (`matches=10, uncompiled=0`); no placeholder
card has been observed on this page, in any capture or fixture. Only the
`match-list` cards carry player data, so club/formation events are
recognised only once the parser has entered that list -- the nav strip
repeats every club's bare team link and would otherwise inflate
`uncompiled` with matches this page never meant to report on.

Each player is an `li.player-item` whose `aria-valuenow` is the percentage
(0-100, starters and bench alike); his link is an absolute
`https://www.fantacalcio.it/serie-a/squadre/<club>/<slug>/<id>` and `<id>`
is the listone id. The panchina list is `ul.player-list.reserves` (not
"riserve" -- that spelling never appears). Each club's predicted module
rides on a separate `ul.team-lineup[data-formation]` pitch-diagram widget
that fires *before* any player in that match: both clubs' headers are seen,
then both clubs' formations, in the same home/away order, so a formation
is bound to the earliest club header, in the same card, not yet bound to
one (a FIFO queue scoped to the match card it opens in, reset at the next
card's own `li.match-item` -- a page-global queue would let a card with
headers but no formation widget shift every later club's formation onto
the previous match). Each match's own `Ultimo aggiornamento dd/mm/yyyy -
HH:MM` (Rome time) is one `<div class="last-update">` emitted *after* both
clubs' starters+reserves lists, with the date itself in a child `<span>` --
so it arrives as a separate text node from the label, joined by a rolling
text buffer. The giornata is not declared as such in this layout's visible
text; it is only in `<meta itemprop="name" content="... N° giornata
...">`, once per match card (nav and real alike). A fallback regex over the
visible text collected *inside* `match-list` (never the nav strip, never a
script/style body) stands in if that microdata is ever absent or reworded
-- deliberately scoped, since the cards' own prose can otherwise carry an
unrelated giornata mention (an injury note's "rientro dalla 4a giornata"
appears on this very capture) that must not be read as the page's own round.

The constants below pin what the capture showed; a page that no longer
matches fails loud (`ProbabiliShapeError`), never silently.

A match card that is not yet compiled -- headers for both clubs but no
player list, no `data-formation` widget -- is skipped and counted, not
fatal: Tuesday's page is legitimately half empty, before the paper's
midweek updates land. That shape is *inferred*, not observed: this
adapter has never seen one on the real site. `test_probabili.py`
synthesises it by stripping a real card's players and both formation
widgets, which is evidence about this parser's behaviour on that input,
not an observation of the live page -- treat it as such until an
early-week capture confirms the real shape.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.timeutil import to_db

SOURCE = "fantacalcio.it:/probabili-formazioni-serie-a"
URL = "https://www.fantacalcio.it/probabili-formazioni-serie-a"
ROME = ZoneInfo("Europe/Rome")
ORIGIN = "https://www.fantacalcio.it"

# Pinned against captured/probabili-2026-27-giornata-3.html (Task 1) and
# verified against core/tests/fixtures/probabili_sample.html (Task 3).
# Change them only with a new capture and a regenerated fixture, never by guess.
PLAYER_CLASS = "player-item"                                   # the li that carries aria-valuenow
MATCH_LIST_CLASS = "match-list"                                 # the real cards; excludes the match-menu nav strip
BENCH_CLASS_RE = re.compile(r"reserv|bench|panch", re.IGNORECASE)        # the container of the panchina list ("reserves")
STAMP_BEFORE_LISTS = False                                      # "Ultimo aggiornamento" follows both clubs' lists
_ORIGIN_RE = re.escape(ORIGIN)
PLAYER_HREF = re.compile(rf"^(?:{_ORIGIN_RE})?/serie-a/squadre/(?P<club>[^/]+)/(?P<slug>[^/]+)/(?P<id>\d+)/?$")
CLUB_HREF = re.compile(rf"^(?:{_ORIGIN_RE})?/serie-a/squadre/(?P<club>[^/]+)/?$")
STAMP_RE = re.compile(r"Ultimo aggiornamento\s*:?\s*(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{1,2}):(\d{2})")
GIORNATA_RE = re.compile(r"(\d{1,2})\s*[ªa°]\s*giornata", re.IGNORECASE)
VOID_TAGS = frozenset({"meta", "img", "br", "input", "link", "hr", "source"})


class ProbabiliShapeError(ValueError):
    """The page is not the probabili page this adapter was written against."""


@dataclass(frozen=True)
class ProbabiliRow:
    player_id: int
    name: str
    club_slug: str
    formation: str | None
    p_start: int
    bench: bool
    updated_at: datetime | None          # aware UTC
    raw: dict[str, Any]


@dataclass(frozen=True)
class ProbabiliPage:
    rows: list[ProbabiliRow]
    matches: int                         # compiled: at least one player listed
    uncompiled: int
    giornata: int | None                 # when the page names it (visible text, or match microdata)
    duplicates: int                      # a player listed twice: the first stands


class _Parser(HTMLParser):
    """A flat event stream in document order: formation, club header, player, stamp.
    Grouping into matches is done afterwards, on the stream, not in the parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, Any]] = []
        self.text: list[str] = []
        self.meta_names: list[str] = []                    # <meta itemprop="name" content="..."> in document order
        self._in_cards = False                              # inside <ul class="match-list">, not the nav strip
        self._stack: list[tuple[str, bool, bool, bool]] = []  # (tag, marks_bench, is_player, is_name_anchor)
        self._player: dict[str, Any] | None = None
        self._name_depth = 0                                 # >0 while inside the player's own name anchor
        self._buffer = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=True)

    def _open(self, tag: str, a: dict[str, str | None], *, void: bool) -> None:
        classes = str(a.get("class") or "").split()
        if not self._in_cards and MATCH_LIST_CLASS in classes:
            self._in_cards = True
        if tag == "meta" and a.get("itemprop") == "name":
            content = a.get("content")
            if content:
                self.meta_names.append(str(content))
        formation = a.get("data-formation") if self._in_cards else None
        if formation:
            self.events.append(("formation", str(formation)))
        href = str(a.get("href") or "")
        club = CLUB_HREF.match(href) if self._in_cards else None
        if club and self._player is None:
            self.events.append(("club", club.group("club")))
        if self._in_cards and tag == "li" and "match-item" in classes:
            self.events.append(("card", None))       # a new match card: formations bind only within it
        is_player = self._in_cards and PLAYER_CLASS in classes
        marks_bench = any(BENCH_CLASS_RE.search(c) for c in classes)
        is_name_anchor = False
        if is_player:
            self._player = {"p": a.get("aria-valuenow"), "href": None, "name": "",
                            "bench": marks_bench or any(b for _, b, _, _ in self._stack)}
        elif self._player is not None:
            if self._player["p"] is None and a.get("aria-valuenow") is not None:
                self._player["p"] = a.get("aria-valuenow")
            if tag == "a" and self._player["href"] is None and PLAYER_HREF.match(href):
                self._player["href"] = href
                is_name_anchor = True
                self._name_depth += 1
        if not void:
            self._stack.append((tag, marks_bench, is_player, is_name_anchor))

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, *_ in self._stack):
            return  # html.parser is lenient; a stray end tag with nothing to close is left alone,
                    # never drained -- popping past it would forget every tag still legitimately open
        while self._stack:
            open_tag, _, was_player, was_name_anchor = self._stack.pop()
            if was_name_anchor:
                self._name_depth -= 1
            if was_player and self._player is not None:
                self.events.append(("player", self._player))
                self._player = None
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        # kept only for the giornata fallback, and only from inside the real cards: the nav
        # strip, ad copy and inline JSON elsewhere on the page must never be read as the page's
        # own round, and script/style bodies (CDATA, reported here whole) are never prose either.
        if self._in_cards and not any(t in ("script", "style") for t, *_ in self._stack):
            self.text.append(data)
        if self._player is not None and self._name_depth > 0:
            self._player["name"] += data
        self._buffer = (self._buffer + " " + data)[-160:]
        found = STAMP_RE.search(self._buffer)
        if found:
            day, month, year, hour, minute = (int(x) for x in found.groups())
            self.events.append(("stamp", datetime(year, month, day, hour, minute, tzinfo=ROME).astimezone(UTC)))
            self._buffer = ""


def parse_probabili_page(html_text: str) -> ProbabiliPage:
    parser = _Parser()
    parser.feed(html_text)
    if not any(kind == "player" for kind, _ in parser.events):
        raise ProbabiliShapeError(f"no li.{PLAYER_CLASS} on the page -- the probabili layout changed")
    header_clubs = {slug for kind, slug in parser.events if kind == "club"}
    matches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    formations: dict[str, str] = {}
    club_queue: list[str] = []          # club headers not yet bound to a formation, FIFO per match

    def new_match(stamp: datetime | None) -> dict[str, Any]:
        match = {"stamp": stamp, "clubs": [], "players": []}
        matches.append(match)
        return match

    for kind, payload in parser.events:
        if kind == "card":
            club_queue = []          # a match boundary: no club is still owed a formation from the last one
        elif kind == "club":
            club_queue.append(payload)
        elif kind == "formation":
            if club_queue:
                formations.setdefault(club_queue.pop(0), payload)
        elif kind == "stamp":
            if STAMP_BEFORE_LISTS:
                if current is None or current["players"]:
                    current = new_match(payload)
                else:
                    current["stamp"] = payload
            else:
                if current is None:
                    current = new_match(payload)
                else:
                    current["stamp"] = payload
                    current = None
        elif kind == "player":
            href = payload["href"]
            if not href:
                raise ProbabiliShapeError(f"a {PLAYER_CLASS} without a player link ({payload['name'].strip()[:40]!r})")
            link = PLAYER_HREF.match(href)
            club = link.group("club")
            if current is None or (club not in current["clubs"] and len(current["clubs"]) == 2):
                current = new_match(None)
            if club not in current["clubs"]:
                current["clubs"].append(club)
            if payload["p"] is None:
                raise ProbabiliShapeError(f"player {href} carries no aria-valuenow")
            try:
                p_start = int(str(payload["p"]))
            except ValueError:
                raise ProbabiliShapeError(f"aria-valuenow {payload['p']!r} on {href} is not an integer") from None
            if not 0 <= p_start <= 100:
                raise ProbabiliShapeError(f"aria-valuenow {p_start} on {href} is not a percentage")
            current["players"].append((club, int(link.group("id")), " ".join(payload["name"].split()), p_start,
                                       bool(payload["bench"]), href))
    rows: list[ProbabiliRow] = []
    seen: set[int] = set()
    duplicates = 0
    for match in matches:
        stamp = match["stamp"]
        for club, player_id, name, p_start, bench, href in match["players"]:
            if player_id in seen:
                duplicates += 1
                continue
            seen.add(player_id)
            rows.append(ProbabiliRow(player_id, name, club, formations.get(club), p_start, bench, stamp,
                                     {"href": href, "clubs": list(match["clubs"]),
                                      "stamp": stamp.isoformat() if stamp else None}))
    compiled = sum(1 for m in matches if m["players"])
    total = max(len(header_clubs) // 2, compiled)
    named = GIORNATA_RE.search(" ".join(parser.meta_names)) or GIORNATA_RE.search(" ".join(parser.text))
    return ProbabiliPage(rows, compiled, total - compiled, int(named.group(1)) if named else None, duplicates)


async def fetch_probabili(http: httpx.AsyncClient, store: RawStore, *, label: str) -> RawFile:
    data = await fetch_bytes(http, URL)
    return store.write_bytes("probabili", data, ext="html", label=label)


@dataclass(frozen=True)
class ProbabiliIngestResult:
    file_id: int
    season_id: int
    giornata: int
    inserted: int
    skipped_duplicate: bool
    matches: int
    uncompiled: int
    unknown_players: int
    duplicates: int
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"file_id": self.file_id, "season_id": self.season_id, "giornata": self.giornata,
                "inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate, "matches": self.matches,
                "uncompiled": self.uncompiled, "unknown_players": self.unknown_players,
                "duplicates": self.duplicates, "sha256": self.sha256, "raw_path": self.raw_path}


def record_probabili(con: duckdb.DuckDBPyConnection, season_id: int, giornata: int, page: ProbabiliPage,
                     raw: RawFile) -> ProbabiliIngestResult:
    """Append one file row and its player rows; the same bytes for the same
    giornata is a no-op. A later fetch is a later file: v_probabili_current
    picks the newest, and nothing is overwritten."""
    existing = con.execute("SELECT file_id FROM probabili_files WHERE season_id = ? AND giornata = ? AND sha256 = ?",
                           [season_id, giornata, raw.sha256]).fetchone()
    if existing is not None:
        return ProbabiliIngestResult(existing[0], season_id, giornata, 0, True, page.matches, page.uncompiled, 0,
                                     page.duplicates, raw.sha256, str(raw.path))
    known = {int(pid): short for pid, short in con.execute(
        "SELECT player_id, team_short FROM v_players_current").fetchall()}
    unknown = sum(1 for r in page.rows if r.player_id not in known)
    con.begin()
    try:
        file_id = con.execute(
            "INSERT INTO probabili_files (season_id, giornata, fetched_at, source, raw_path, sha256, row_count, matches, "
            "uncompiled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
            [season_id, giornata, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, len(page.rows),
             page.matches, page.uncompiled]).fetchone()[0]
        con.executemany(
            "INSERT INTO probabili VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[file_id, season_id, giornata, r.player_id, r.name, r.club_slug, known.get(r.player_id), r.formation,
              r.p_start, r.bench, to_db(r.updated_at) if r.updated_at else None, json.dumps(r.raw, ensure_ascii=False)]
             for r in page.rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return ProbabiliIngestResult(file_id, season_id, giornata, len(page.rows), False, page.matches, page.uncompiled,
                                 unknown, page.duplicates, raw.sha256, str(raw.path))
