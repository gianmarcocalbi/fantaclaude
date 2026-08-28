"""One place that opens fanta.duckdb.

DuckDB is single-process for writes, and inside one process every connection
to a file must share its configuration -- a read-only and a read-write handle
cannot coexist. So `query` opens read-only, `sync-league` and `ingest` open
read-write, and they are different processes: the spec's concurrency model.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from fantaclaude.paths import db_path


class DatabaseMissing(FileNotFoundError):
    """Nothing has been ingested yet: the database file does not exist."""


def connect(path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = path or db_path()
    if read_only:
        if not path.is_file():
            raise DatabaseMissing(str(path))
        return duckdb.connect(str(path), read_only=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))
