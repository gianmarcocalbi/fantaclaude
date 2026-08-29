"""The analytical spine's DDL, applied idempotently.

Snapshot tables, never overwrites: league_settings appends one row per
observed rule change, listone_snapshots/players append one snapshot per
ingest, and the v_*_current views pick the latest. Raw payloads travel in a
JSON column so a field the models do not name is still there to query.
Version 2 (Phase 0b) adds the observed history -- player_match from the voti
workbooks, advanced_stats from Understat, fixtures from the Serie A calendar
and UEFA -- and the views over them. The DDL is additive: apply_schema
upgrades an older file in place and refuses only a newer one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import duckdb

SCHEMA_VERSION = 2

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
CREATE SEQUENCE IF NOT EXISTS seq_voti_files START 1;
CREATE TABLE IF NOT EXISTS voti_files (
    file_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_voti_files'),
    season_id   INTEGER NOT NULL,
    giornata    INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_path    VARCHAR NOT NULL,
    sha256      VARCHAR NOT NULL,
    sheets      VARCHAR[] NOT NULL,
    row_count   INTEGER NOT NULL,
    UNIQUE (season_id, giornata, sha256)
);
CREATE TABLE IF NOT EXISTS player_match (
    file_id        INTEGER NOT NULL,
    season_id      INTEGER NOT NULL,
    giornata       INTEGER NOT NULL,
    sheet          VARCHAR NOT NULL,
    player_id      INTEGER NOT NULL,
    name           VARCHAR NOT NULL,
    team           VARCHAR NOT NULL,
    classic_role   VARCHAR NOT NULL,
    voto           DECIMAL(4,2),
    senza_voto     BOOLEAN NOT NULL,
    goals          INTEGER NOT NULL,
    goals_conceded INTEGER NOT NULL,
    pen_saved      INTEGER NOT NULL,
    pen_missed     INTEGER NOT NULL,
    pen_scored     INTEGER NOT NULL,
    own_goals      INTEGER NOT NULL,
    yellow         INTEGER NOT NULL,
    red            INTEGER NOT NULL,
    assists        INTEGER NOT NULL,
    raw            JSON NOT NULL,
    PRIMARY KEY (file_id, sheet, player_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_advanced_snapshots START 1;
CREATE TABLE IF NOT EXISTS advanced_snapshots (
    snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('seq_advanced_snapshots'),
    season_id   INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_path    VARCHAR NOT NULL,
    sha256      VARCHAR NOT NULL UNIQUE,
    row_count   INTEGER NOT NULL,
    matched     INTEGER NOT NULL,
    ambiguous   INTEGER NOT NULL,
    unmatched   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS advanced_stats (
    snapshot_id  INTEGER NOT NULL,
    season_id    INTEGER NOT NULL,
    source_id    VARCHAR NOT NULL,
    player_name  VARCHAR NOT NULL,
    teams        VARCHAR[] NOT NULL,
    player_id    INTEGER,
    match_status VARCHAR NOT NULL,
    candidates   INTEGER[] NOT NULL,
    games        INTEGER NOT NULL,
    minutes      INTEGER NOT NULL,
    goals        INTEGER NOT NULL,
    assists      INTEGER NOT NULL,
    xg           DOUBLE NOT NULL,
    xa           DOUBLE NOT NULL,
    npg          INTEGER NOT NULL,
    npxg         DOUBLE NOT NULL,
    shots        INTEGER NOT NULL,
    key_passes   INTEGER NOT NULL,
    yellow       INTEGER NOT NULL,
    red          INTEGER NOT NULL,
    xg_chain     DOUBLE NOT NULL,
    xg_buildup   DOUBLE NOT NULL,
    position     VARCHAR NOT NULL,
    raw          JSON NOT NULL,
    PRIMARY KEY (snapshot_id, source_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_fixture_snapshots START 1;
CREATE TABLE IF NOT EXISTS fixture_snapshots (
    snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('seq_fixture_snapshots'),
    competition VARCHAR NOT NULL,
    season_id   INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_paths   VARCHAR[] NOT NULL,
    sha256      VARCHAR NOT NULL,
    row_count   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fixtures (
    snapshot_id INTEGER NOT NULL,
    competition VARCHAR NOT NULL,
    season_id   INTEGER NOT NULL,
    source_id   VARCHAR NOT NULL,
    round       VARCHAR NOT NULL,
    giornata    INTEGER,
    phase       VARCHAR,
    kickoff     TIMESTAMP,
    home        VARCHAR NOT NULL,
    away        VARCHAR NOT NULL,
    home_short  VARCHAR,
    away_short  VARCHAR,
    raw         JSON NOT NULL,
    PRIMARY KEY (snapshot_id, source_id)
);
CREATE OR REPLACE VIEW v_voti_files_current AS
    SELECT f.* FROM voti_files f
    WHERE f.file_id = (SELECT max(g.file_id) FROM voti_files g
                       WHERE g.season_id = f.season_id AND g.giornata = f.giornata);
CREATE OR REPLACE VIEW v_player_match_current AS
    SELECT m.* FROM player_match m
    WHERE m.file_id IN (SELECT file_id FROM v_voti_files_current);
CREATE OR REPLACE VIEW v_advanced_current AS
    SELECT a.* FROM advanced_stats a
    WHERE a.snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id);
CREATE OR REPLACE VIEW v_advanced_unmatched AS
    SELECT season_id, source_id, player_name, teams, match_status, candidates
    FROM v_advanced_current WHERE player_id IS NULL;
CREATE OR REPLACE VIEW v_player_season AS
    SELECT m.season_id, m.sheet, m.player_id, any_value(m.name) AS name,
           list(DISTINCT m.team) AS teams,
           count(*) AS appearances,
           count(*) FILTER (WHERE NOT m.senza_voto) AS presenze,
           avg(m.voto) AS media_voto,
           sum(m.goals) AS goals, sum(m.assists) AS assists,
           sum(m.goals_conceded) AS goals_conceded,
           sum(m.pen_scored) AS pen_scored, sum(m.pen_missed) AS pen_missed,
           sum(m.pen_saved) AS pen_saved, sum(m.own_goals) AS own_goals,
           sum(m.yellow) AS yellow, sum(m.red) AS red,
           any_value(a.minutes) AS minutes, any_value(a.games) AS games_understat,
           any_value(a.xg) AS xg, any_value(a.xa) AS xa
    FROM v_player_match_current m
    LEFT JOIN (SELECT season_id, player_id, sum(minutes) AS minutes, sum(games) AS games,
                      sum(xg) AS xg, sum(xa) AS xa
               FROM v_advanced_current WHERE player_id IS NOT NULL
               GROUP BY season_id, player_id) a
           ON a.season_id = m.season_id AND a.player_id = m.player_id
    GROUP BY m.season_id, m.sheet, m.player_id;
CREATE OR REPLACE VIEW v_player_form AS
    SELECT season_id, sheet, player_id, any_value(name) AS name,
           count(*) AS n, avg(voto) AS media_voto, sum(goals) AS goals,
           sum(assists) AS assists, max(giornata) AS last_giornata
    FROM (SELECT season_id, sheet, player_id, name, giornata, voto, goals, assists,
                 dense_rank() OVER (PARTITION BY season_id, sheet, player_id
                                    ORDER BY giornata DESC) AS rn
          FROM v_player_match_current
          WHERE NOT senza_voto AND season_id = (SELECT max(season_id) FROM voti_files))
    WHERE rn <= 5
    GROUP BY season_id, sheet, player_id;
CREATE OR REPLACE VIEW v_fixtures_current AS
    SELECT x.* FROM fixtures x
    WHERE x.snapshot_id IN (SELECT max(snapshot_id) FROM fixture_snapshots
                            GROUP BY competition, season_id);
CREATE OR REPLACE VIEW v_european_ties AS
    SELECT * FROM (
        SELECT competition, season_id, source_id, round, phase, kickoff, home, away,
               unnest([home_short, away_short]) AS team_short
        FROM v_fixtures_current WHERE competition <> 'SA')
    WHERE team_short IS NOT NULL;
"""


class SchemaVersionMismatch(RuntimeError):
    """The file was written by a different schema version; migrate before use."""


def apply_schema(con: duckdb.DuckDBPyConnection) -> int:
    """Create what is missing, then reconcile the version row.

    The DDL is additive (CREATE ... IF NOT EXISTS, CREATE OR REPLACE VIEW),
    so running it against an older file upgrades it in place -- the Phase 0a
    database keeps its league_settings and listone rows instead of being
    rebuilt with more live-API calls. A stored version *newer* than the code
    is the one case that is refused: the code cannot know what that file holds.
    """
    for statement in DDL.split(";"):
        if statement.strip():
            con.execute(statement)
    stored = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    if stored is not None and stored > SCHEMA_VERSION:
        raise SchemaVersionMismatch(f"database is at schema {stored}, code expects {SCHEMA_VERSION}")
    if stored is None or stored < SCHEMA_VERSION:
        con.execute("INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION])
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
