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
from fantaclaude.ingest.raw import RawStore


async def ingest_listone(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection, store: RawStore, *,
                         league: str | None = None) -> IngestResult:
    raw = await fetch_listone(api, store, league=league)
    return record_listone(con, load_listone(raw.path), raw)


async def ingest_all(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection, store: RawStore, *,
                     league: str | None = None) -> dict[str, IngestResult]:
    # Phase 0b adds stats_web, calendar and advanced here.
    return {"listone": await ingest_listone(api, con, store, league=league)}
