"""The analytical spine's DDL, applied idempotently.

Snapshot tables, never overwrites: league_settings appends one row per
observed rule change, listone_snapshots/players append one snapshot per
ingest, and the v_*_current views pick the latest. Raw payloads travel in a
JSON column so a field the models do not name is still there to query.
Later phases add their tables here and bump SCHEMA_VERSION.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import duckdb

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE SEQUENCE IF NOT EXISTS seq_league_settings START 1;
CREATE TABLE IF NOT EXISTS league_settings (
    snapshot_id   INTEGER PRIMARY KEY DEFAULT nextval('seq_league_settings'),
    fetched_at    TIMESTAMP NOT NULL,
    league_id     INTEGER NOT NULL,
    season_id     INTEGER,
    matchday      INTEGER,
    rules_hash    VARCHAR NOT NULL,
    team_count    INTEGER,
    budget        INTEGER,
    roster_min    INTEGER,
    roster_max    INTEGER,
    modules       VARCHAR[],
    bench_size    INTEGER,
    substitutions INTEGER,
    payload       JSON NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS seq_listone_snapshots START 1;
CREATE TABLE IF NOT EXISTS listone_snapshots (
    snapshot_id  INTEGER PRIMARY KEY DEFAULT nextval('seq_listone_snapshots'),
    fetched_at   TIMESTAMP NOT NULL,
    source       VARCHAR NOT NULL,
    raw_path     VARCHAR NOT NULL,
    sha256       VARCHAR NOT NULL UNIQUE,
    player_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    snapshot_id          INTEGER NOT NULL,
    player_id            INTEGER NOT NULL,
    name                 VARCHAR NOT NULL,
    team_id              INTEGER,
    team_name            VARCHAR,
    team_short           VARCHAR,
    classic_role         VARCHAR NOT NULL,
    mantra_roles         VARCHAR[] NOT NULL,
    mantra_role_codes    INTEGER[] NOT NULL,
    quot_initial_classic INTEGER,
    quot_current_classic INTEGER,
    quot_initial_mantra  INTEGER,
    quot_current_mantra  INTEGER,
    fvm_classic          INTEGER,
    fvm_mantra           INTEGER,
    age                  INTEGER,
    nationality          VARCHAR,
    transfer_flag        BOOLEAN NOT NULL,
    raw                  JSON NOT NULL,
    PRIMARY KEY (snapshot_id, player_id)
);
CREATE TABLE IF NOT EXISTS teams (
    snapshot_id INTEGER NOT NULL,
    team_id     INTEGER NOT NULL,
    name        VARCHAR NOT NULL,
    short       VARCHAR,
    PRIMARY KEY (snapshot_id, team_id)
);
CREATE TABLE IF NOT EXISTS player_aliases (
    alias     VARCHAR NOT NULL,
    source    VARCHAR NOT NULL,
    player_id INTEGER NOT NULL,
    PRIMARY KEY (alias, source)
);
CREATE OR REPLACE VIEW v_league_settings_current AS
    SELECT * FROM league_settings ORDER BY snapshot_id DESC LIMIT 1;
CREATE OR REPLACE VIEW v_players_current AS
    SELECT p.* FROM players p
    WHERE p.snapshot_id = (SELECT max(snapshot_id) FROM listone_snapshots);
CREATE OR REPLACE VIEW v_teams_current AS
    SELECT t.* FROM teams t
    WHERE t.snapshot_id = (SELECT max(snapshot_id) FROM listone_snapshots);
"""


class SchemaVersionMismatch(RuntimeError):
    """The file was written by a different schema version; migrate before use."""


def apply_schema(con: duckdb.DuckDBPyConnection) -> int:
    for statement in DDL.split(";"):
        if statement.strip():
            con.execute(statement)
    stored = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    if stored is None:
        con.execute("INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION])
    elif stored != SCHEMA_VERSION:
        raise SchemaVersionMismatch(f"database is at schema {stored}, code expects {SCHEMA_VERSION}")
    return SCHEMA_VERSION


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    kind: str                       # "table" | "view"
    columns: list[ColumnInfo]
    rows: int | None


@dataclass(frozen=True)
class SchemaReport:
    version: int | None
    tables: list[TableInfo]

    def to_dict(self) -> dict:
        return {"version": self.version, "tables": [asdict(t) for t in self.tables]}


def schema_report(con: duckdb.DuckDBPyConnection) -> SchemaReport:
    try:
        version = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    except duckdb.Error:
        version = None
    names = con.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name").fetchall()
    tables: list[TableInfo] = []
    for name, table_type in names:
        columns = [ColumnInfo(row[0], row[1]) for row in con.execute(f'DESCRIBE "{name}"').fetchall()]
        rows = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        tables.append(TableInfo(name, "view" if table_type == "VIEW" else "table", columns, rows))
    return SchemaReport(version, tables)
