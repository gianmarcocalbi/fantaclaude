"""fantaclaude ingest: every source, through the same fetch/load/record shape."""

from __future__ import annotations

from pathlib import Path

import duckdb
import httpx
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.ingest.advanced import (
    AdvancedIngestResult,
    fetch_advanced,
    load_advanced,
    record_advanced,
)
from fantaclaude.ingest.calendar import (
    FixtureIngestResult,
    fetch_serie_a,
    fetch_uefa,
    load_serie_a,
    load_uefa,
    record_fixtures,
)
from fantaclaude.ingest.http import polite_pause
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
    fetch_voti_range,
    parse_voti,
    record_voti,
)
from fantaclaude.model.seasons import SERIE_A_GIORNATE, back_seasons


async def fetch_all(api: FantacalcioAPI, store: RawStore, *,
                    league: str | None = None) -> dict[str, RawFile]:
    """The network half: every source into data/raw/, no database involved.

    Kept separate so the caller opens DuckDB only for the write -- it is
    single-writer, and a file created before the fetch survives a failure as an
    empty database that looks ingested.
    """
    # Phase 0b adds stats_web, calendar and advanced here.
    return {"listone": await fetch_listone(api, store, league=league)}


def record_all(con: duckdb.DuckDBPyConnection, raws: dict[str, RawFile]) -> dict[str, IngestResult]:
    """The database half: parse each raw file and snapshot it."""
    return {name: record_listone(con, load_listone(raw.path), raw)
            for name, raw in raws.items()}


async def ingest_listone(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection, store: RawStore, *,
                         league: str | None = None) -> IngestResult:
    raw = await fetch_listone(api, store, league=league)
    return record_listone(con, load_listone(raw.path), raw)


async def ingest_all(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection, store: RawStore, *,
                     league: str | None = None) -> dict[str, IngestResult]:
    # Phase 0b adds stats_web, calendar and advanced here.
    return {"listone": await ingest_listone(api, con, store, league=league)}


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


def existing_giornate(path: Path | None, seasons: list[int]) -> dict[int, set[int]]:
    """Which giornate of each season are already on disk (read-only, closed before returning)."""
    try:
        con = connect(path, read_only=True)
    except DatabaseMissing:
        return {season: set() for season in seasons}
    try:
        rows = con.execute("SELECT season_id, giornata FROM voti_files WHERE season_id IN "
                           f"({', '.join('?' for _ in seasons)})", seasons).fetchall() if seasons else []
    finally:
        con.close()
    found: dict[int, set[int]] = {season: set() for season in seasons}
    for season_id, giornata in rows:
        found[int(season_id)].add(int(giornata))
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


def record_voti_files(con: duckdb.DuckDBPyConnection, fetched: dict[int, VotiFetch]) -> list[VotiIngestResult]:
    known = {int(r[0]) for r in con.execute("SELECT player_id FROM v_players_current").fetchall()}
    results: list[VotiIngestResult] = []
    for season_id in sorted(fetched):
        for giornata in sorted(fetched[season_id].raws):
            raw = fetched[season_id].raws[giornata]
            results.append(record_voti(con, season_id, giornata, parse_voti(raw.path), raw, known_ids=known))
    return results
