"""fantaclaude ingest: every source, through the same fetch/load/record shape."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.advanced import (
    AdvancedIngestResult,
    fetch_advanced,
    load_advanced,
    record_advanced,
)
from fantaclaude.ingest.calendar import (
    COMPETITIONS,
    FixtureIngestResult,
    fetch_serie_a,
    fetch_uefa,
    load_serie_a,
    load_uefa,
    record_fixtures,
)
from fantaclaude.ingest.http import WebSessionExpired, polite_pause
from fantaclaude.ingest.listone_api import (
    IngestResult,
    fetch_listone,
    load_listone,
    record_listone,
)
from fantaclaude.ingest.names import load_aliases, load_candidates, load_teams
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.ingest.stats_web import (
    VotiFetch,
    VotiIngestResult,
    VotiShapeError,
    fetch_voti_range,
    is_not_yet_rated_workbook,
    parse_voti,
    record_voti,
)
from fantaclaude.model.seasons import SERIE_A_GIORNATE, back_seasons


async def ingest_listone(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection, store: RawStore, *,
                         league: str | None = None) -> IngestResult:
    raw = await fetch_listone(api, store, league=league)
    return record_listone(con, load_listone(raw.path), raw)


class NotReady(RuntimeError):
    """No database, or no league_settings snapshot: the season is unknown."""


def current_season_id(path: Path | None = None) -> int:
    """The season the league is in, from the latest league_settings snapshot.

    Read-only and closed before returning: the caller fetches from the network
    next and opens read-write only to record, so no lock spans a request.
    """
    try:
        con = connect(path, read_only=True)
    except DatabaseMissing:
        raise NotReady("no database -- run `fantaclaude sync-league` first") from None
    try:
        row = con.execute("SELECT season_id FROM v_league_settings_current").fetchone()
    finally:
        con.close()
    if row is None or row[0] is None:
        raise NotReady("no league_settings snapshot -- run `fantaclaude sync-league` first")
    return int(row[0])


def default_seasons(*, back: int = 3, path: Path | None = None) -> list[int]:
    """The current season and the `back` before it, oldest first."""
    current = current_season_id(path)
    return [*back_seasons(current, back), current]


def ensure_schema(path: Path | None = None) -> int | None:
    """Migrate the database forward, read-write, before any read-only
    pre-read that needs a table an older schema version does not have.

    `apply_schema` normally runs only on the write connection each ingest
    command opens after its fetch, to record. But several commands read the
    database read-only first -- `current_season_id`/`default_seasons` (via
    `_seasons_or_exit`) -- and a database left at an older schema version
    (this phase's live one included: schema 1, no
    `voti_files`/`advanced_stats`/`fixtures` yet) would make a read-only
    pre-read that touches a v2-only table crash on one that does not exist.
    `existing_giornate` no longer is such a read (Ruling R8b: it reads the
    raw store, not the database), so nothing currently in this file crashes
    without this call -- but Phase 1 is expected to add read-only reads of
    `player_match`/`advanced_stats`, and Task 9 adds a doctor check, so this
    is kept as a defensive migration ahead of those, not removed as
    currently-redundant. Call this once, before any pre-read. The write
    handle closes before the pre-read opens its own read-only one: DuckDB
    does not allow both open in the same process.

    A no-op, returning None, when the database file does not exist yet
    (Finding F2): `_seasons_or_exit` only proves a database exists when it
    falls through to `default_seasons`, not when `--season` is passed
    explicitly (it then short-circuits to `list(season)` without touching
    the database at all). `connect(path)` read-write creates the file, so
    calling it unconditionally would create a fully-schema'd, empty database
    ahead of the network call and leave it behind if the fetch then fails --
    exactly what every ingest command's "fetch first, open read-write only
    to record" ordering exists to prevent (`test_a_failed_ingest_leaves_no_database_behind`).
    """
    try:
        probe = connect(path, read_only=True)
    except DatabaseMissing:
        return None
    probe.close()
    con = connect(path)
    try:
        return apply_schema(con)
    finally:
        con.close()


async def fetch_advanced_seasons(http: httpx.AsyncClient, store: RawStore,
                                 seasons: list[int]) -> dict[int, RawFile]:
    raws: dict[int, RawFile] = {}
    for index, season_id in enumerate(seasons):
        if index:
            await polite_pause()
        raws[season_id] = await fetch_advanced(http, store, season_id=season_id)
    return raws


def record_advanced_seasons(con: duckdb.DuckDBPyConnection, raws: dict[int, RawFile],
                            aliases_path: Path) -> list[AdvancedIngestResult]:
    aliases = load_aliases(aliases_path)
    candidates, teams = load_candidates(con), load_teams(con)
    results = []
    for season_id in sorted(raws):
        loaded_season, rows = load_advanced(raws[season_id].path)
        results.append(record_advanced(con, loaded_season, rows, raws[season_id],
                                       candidates=candidates, teams=teams, aliases=aliases))
    return results


def rematch_advanced_seasons(con: duckdb.DuckDBPyConnection, store: RawStore, seasons: list[int],
                             aliases_path: Path) -> list[AdvancedIngestResult]:
    """Re-record each requested season's most recent on-disk raw file,
    forcing record_advanced past its sha256 short-circuit (Ruling R11) --
    zero network. This is `ingest advanced --rematch`'s whole point: an
    alias added to kb/rules/aliases.yml or a listone move never gets a
    chance to re-match an Understat payload already recorded once, and
    never will on its own for a back season, whose content stops changing
    once the season is over."""
    aliases = load_aliases(aliases_path)
    candidates, teams = load_candidates(con), load_teams(con)
    results = []
    for season_id in sorted(seasons):
        paths = store.list("advanced", ext="json", label=str(season_id))
        if not paths:
            raise NotReady(f"no advanced/{season_id} raw file on disk yet -- run `fantaclaude ingest advanced` first")
        path = paths[-1]                       # the most recent fetch for this season
        raw = _raw_file_from_disk(path, "advanced")
        loaded_season, rows = load_advanced(path)
        results.append(record_advanced(con, loaded_season, rows, raw, candidates=candidates, teams=teams,
                                       aliases=aliases, force=True))
    return results


async def fetch_calendar(http: httpx.AsyncClient, store: RawStore, season_id: int,
                         competitions: list[str]) -> dict[str, list[RawFile]]:
    """Every requested competition, in the order given, one host at a time."""
    raws: dict[str, list[RawFile]] = {}
    for index, competition in enumerate(competitions):
        if index:
            await polite_pause()
        if competition == "SA":
            raws[competition] = await fetch_serie_a(http, store, season_id=season_id,
                                                    giornate=range(1, SERIE_A_GIORNATE + 1))
        else:
            raws[competition] = await fetch_uefa(http, store, season_id=season_id, competition=competition)
    return raws


def record_calendar(con: duckdb.DuckDBPyConnection, season_id: int, raws: dict[str, list[RawFile]],
                    aliases_path: Path) -> list[FixtureIngestResult]:
    aliases = load_aliases(aliases_path)
    teams = load_teams(con)
    results = []
    for competition, files in raws.items():
        paths = [f.path for f in files]
        if competition == "SA":
            rows, team_aliases = load_serie_a(paths, season_id=season_id), aliases.teams_for("fantacalcio")
        else:
            rows, team_aliases = load_uefa(paths), aliases.teams_for("uefa")
        results.append(record_fixtures(con, competition, season_id, rows, files,
                                       teams=teams, team_aliases=team_aliases))
    return results


_VOTI_LABEL = re.compile(r"-voti-(?P<season>\d+)-(?P<giornata>\d+)\.xlsx$")


def _voti_on_disk(store: RawStore, season_id: int) -> dict[int, Path]:
    """Every giornata of `season_id` with a workbook already in data/raw/voti/,
    by the file's own label -- not by what the database has recorded, which
    can disagree with disk exactly when a run fetched but failed to record."""
    found: dict[int, Path] = {}
    for path in store.list("voti", ext="xlsx"):
        match = _VOTI_LABEL.search(path.name)
        if match and int(match.group("season")) == season_id:
            found[int(match.group("giornata"))] = path
    return found


def _raw_file_from_disk(path: Path, kind: str) -> RawFile:
    """Reconstruct the RawFile a prior run's write() returned, for a file
    RawStore already wrote: the fetch stamp is the name's own prefix, and the
    hash is cheap to recompute -- nothing about a raw file is ever mutable."""
    stamp, _, _ = path.name.partition("-")
    fetched_at = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
    return RawFile(path, RawStore.sha256_of(path), fetched_at, kind)


def existing_giornate(store: RawStore, seasons: list[int]) -> dict[int, set[int]]:
    """Which giornate of each season already have a workbook on disk (data/raw/voti/),
    so fetch_voti_seasons does not re-download a file already sitting there --
    that decision must be made from the raw store, not the database: a run
    that fetched successfully and then failed to record leaves disk and
    database disagreeing, and re-downloading everything already on disk is
    exactly the hazard this function exists to avoid (Ruling R8b).

    A not-yet-rated shell (Ruling R9) is excluded even though its file is on
    disk (Finding F3): counting it as "already fetched" would permanently
    suppress that giornata once the site actually rates it, since nothing
    would ever ask for it again. record_voti_files still sees the shell --
    it reads _voti_on_disk directly, unfiltered -- and keeps reporting it as
    not-yet-rated on every run until a real workbook replaces it on disk."""
    found: dict[int, set[int]] = {}
    for season in seasons:
        on_disk = _voti_on_disk(store, season)
        found[season] = {giornata for giornata, path in on_disk.items() if not is_not_yet_rated_workbook(path)}
    return found


async def fetch_voti_seasons(http: httpx.AsyncClient, store: RawStore, *, cookie: str, seasons: list[int],
                             giornate: list[int], existing: dict[int, set[int]],
                             refetch: bool) -> dict[int, VotiFetch]:
    fetched: dict[int, VotiFetch] = {}
    for index, season_id in enumerate(seasons):
        if index:
            await polite_pause()
        fetched[season_id] = await fetch_voti_range(http, store, cookie=cookie, season_id=season_id,
                                                    giornate=giornate, existing=existing.get(season_id, set()),
                                                    refetch=refetch)
    return fetched


def record_voti_files(con: duckdb.DuckDBPyConnection, store: RawStore, fetched: dict[int, VotiFetch],
                      giornate: list[int]) -> tuple[list[VotiIngestResult], dict[int, list[int]]]:
    """Record every on-disk workbook for the fetched seasons and the
    requested giornate range, not only what this run downloaded (Ruling
    R8b): a giornata skipped at fetch time because it was already on disk
    must still be recorded, or a fetch-succeeded-record-failed run never
    finishes recovering. record_voti's sha256 dedupe makes an
    already-recorded file a cheap no-op either way.

    A file that turns out to be the not-yet-rated shell (Ruling R9) is
    counted and returned in the second element, never recorded and never
    raised: a giornata already on disk from before this ruling existed, or
    fetched again and found to still be unrated, is exactly the same fact
    `fetch_voti` now refuses to store in the first place -- nothing is
    silently dropped, but it is not a VotiIngestResult either, since nothing
    was recorded."""
    known = {int(r[0]) for r in con.execute("SELECT player_id FROM v_players_current").fetchall()}
    wanted = set(giornate)
    results: list[VotiIngestResult] = []
    not_yet_rated: dict[int, list[int]] = {}
    for season_id in sorted(fetched):
        on_disk = _voti_on_disk(store, season_id)
        for giornata in sorted(g for g in on_disk if g in wanted):
            path = on_disk[giornata]
            if is_not_yet_rated_workbook(path):
                not_yet_rated.setdefault(season_id, []).append(giornata)
                continue
            raw = fetched[season_id].raws.get(giornata) or _raw_file_from_disk(path, "voti")
            results.append(record_voti(con, season_id, giornata, parse_voti(raw.path), raw, known_ids=known))
    return results, not_yet_rated


@dataclass(frozen=True)
class AllFetched:
    season_id: int                              # the season the league is in; the calendar's season
    listone: RawFile
    advanced: dict[int, RawFile]
    calendar: dict[str, list[RawFile]]
    stats_web: dict[int, VotiFetch] | None      # None when skipped
    skipped: list[str]


async def fetch_everything(api: FantacalcioAPI, http: httpx.AsyncClient, store: RawStore, *,
                           seasons: list[int], cookie: str | None, existing_voti: dict[int, set[int]],
                           league: str | None = None) -> AllFetched:
    """The network half of `ingest all`: one league-API call, then the web sources.

    A source whose prerequisite is missing (no cookie) is skipped and named.
    A source whose cookie is rejected mid-run (Finding F1, the task-review
    dispatch) is also caught here and named the same way, so `record_everything` still
    runs for whatever *did* fetch: the listone, advanced and calendar have
    no on-disk recovery path of their own, unlike voti's raw store (Ruling
    R8b), so losing them to an aborted run is exactly what "after the other
    sources are already recorded" (the brief's own words) rules out. The
    listone goes first because every other source is matched against it at
    record time.

    A malformed voti workbook (`VotiShapeError` -- an appended column, a
    missing club row, or any other layout surprise `fetch_voti` detects) is
    carried the same way: it is a genuine error, not a missing prerequisite,
    but by the time stats_web is attempted the listone, advanced and
    calendar have already been fetched, so letting it escape and abort the
    run before `record_everything` runs would throw all three away for
    exactly the reason the cookie-rejection handling above exists.
    """
    skipped: list[str] = []
    listone = await fetch_listone(api, store, league=league)
    advanced = await fetch_advanced_seasons(http, store, seasons)
    await polite_pause()
    calendar = await fetch_calendar(http, store, seasons[-1], list(COMPETITIONS))
    stats_web: dict[int, VotiFetch] | None = None
    if cookie is None:
        skipped.append("stats_web: FANTACALCIO_WEB_COOKIE is not set")
    else:
        await polite_pause()
        try:
            stats_web = await fetch_voti_seasons(http, store, cookie=cookie, seasons=seasons,
                                                 giornate=list(range(1, SERIE_A_GIORNATE + 1)),
                                                 existing=existing_voti, refetch=False)
        except WebSessionExpired as exc:
            # A rejected cookie is an error, not a missing prerequisite -- but
            # the listone, advanced and calendar have already been fetched by
            # this point and have no on-disk recovery path of their own
            # (unlike voti's raw store, Ruling R8b), so the run must still
            # record them: caught here, carried as a skip reason, instead of
            # left to propagate out of fetch_everything and abort before
            # record_everything ever runs.
            skipped.append(f"stats_web: website session rejected: {exc} -- re-capture "
                           f"FANTACALCIO_WEB_COOKIE (core/README.md, 'The website session')")
        except VotiShapeError as exc:
            # See the docstring above: carried the same way as a rejected
            # cookie, so record_everything still runs for the listone,
            # advanced and calendar payloads already fetched.
            skipped.append(f"stats_web: voti workbook shape error: {exc}")
    return AllFetched(seasons[-1], listone, advanced, calendar, stats_web, skipped)


def record_everything(con: duckdb.DuckDBPyConnection, store: RawStore, fetched: AllFetched,
                      aliases_path: Path) -> dict[str, Any]:
    """The database half: listone first (the identity every join needs), then the rest."""
    listone = record_listone(con, load_listone(fetched.listone.path), fetched.listone)
    advanced = record_advanced_seasons(con, fetched.advanced, aliases_path)
    calendar = record_calendar(con, fetched.season_id, fetched.calendar, aliases_path)
    stats_web = None
    if fetched.stats_web is not None:
        files, not_yet_rated = record_voti_files(con, store, fetched.stats_web, list(range(1, SERIE_A_GIORNATE + 1)))
        stats_web = {"files": [r.to_dict() for r in files],
                     "skipped": {str(s): sorted(f.skipped) for s, f in fetched.stats_web.items()},
                     "not_published_from": {str(s): f.not_published_from for s, f in fetched.stats_web.items()
                                            if f.not_published_from is not None},
                     "not_yet_rated": {str(s): sorted(g) for s, g in not_yet_rated.items()}}
    return {"listone": listone.to_dict(), "advanced": [r.to_dict() for r in advanced],
            "calendar": [r.to_dict() for r in calendar], "stats_web": stats_web, "skipped": list(fetched.skipped)}
