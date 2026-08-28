"""fantaclaude ingest: every source, through the same fetch/load/record shape."""

from __future__ import annotations

import duckdb
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.ingest.listone_api import (
    IngestResult,
    fetch_listone,
    load_listone,
    record_listone,
)
from fantaclaude.ingest.raw import RawFile, RawStore


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
