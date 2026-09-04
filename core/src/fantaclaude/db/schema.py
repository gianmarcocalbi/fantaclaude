"""The analytical spine's DDL, applied idempotently.

Snapshot tables, never overwrites: league_settings appends one row per
observed rule change, listone_snapshots/players append one snapshot per
ingest, and the v_*_current views pick the latest. Raw payloads travel in a
JSON column so a field the models do not name is still there to query.
Version 2 (Phase 0b) added the observed history -- player_match from the
voti workbooks, advanced_stats from Understat, fixtures from the Serie A
calendar and UEFA -- and the views over them. Version 3 (Phase 1) adds the
derived layer -- valuation_runs, valuations and valuation_prices, every row
immutable, supersession a view -- and rebuilds advanced_snapshots around a
dedupe key that covers every input of the match: the raw bytes, the aliases
file and the listone snapshot, so a changed alias re-matches on its own.
Version 4 (Phase 3a) adds the observed roster and probabili layers and the
forecast layer -- lineup_runs/predictions, immutable, refused after the first
kickoff by the writer, never by the schema.
The DDL is additive: apply_schema upgrades an older file in place and
refuses only a newer one; the one table whose constraint changed (version 2
to 3) is rebuilt around its rows, because DuckDB cannot drop a constraint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import duckdb

SCHEMA_VERSION = 4

ADVANCED_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS advanced_snapshots (
    snapshot_id         INTEGER PRIMARY KEY DEFAULT nextval('seq_advanced_snapshots'),
    season_id           INTEGER NOT NULL,
    fetched_at          TIMESTAMP NOT NULL,
    source              VARCHAR NOT NULL,
    raw_path            VARCHAR NOT NULL,
    sha256              VARCHAR NOT NULL,
    aliases_sha256      VARCHAR,
    listone_snapshot_id INTEGER,
    row_count           INTEGER NOT NULL,
    matched             INTEGER NOT NULL,
    ambiguous           INTEGER NOT NULL,
    unmatched           INTEGER NOT NULL,
    UNIQUE (sha256, aliases_sha256, listone_snapshot_id)
)"""

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
""" + ADVANCED_SNAPSHOTS_DDL + """;
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
CREATE TABLE IF NOT EXISTS valuation_runs (
    run_id               VARCHAR PRIMARY KEY,
    created_at           TIMESTAMP NOT NULL,
    rules_hash           VARCHAR NOT NULL,
    model_hash           VARCHAR NOT NULL,
    inputs_hash          VARCHAR NOT NULL,
    settings_snapshot_id INTEGER NOT NULL,
    listone_snapshot_id  INTEGER NOT NULL,
    season_id            INTEGER NOT NULL,
    giornata             INTEGER NOT NULL,
    scenarios            VARCHAR[] NOT NULL,
    config               JSON NOT NULL,
    summary              JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS valuations (
    run_id         VARCHAR NOT NULL,
    player_id      INTEGER NOT NULL,
    name           VARCHAR NOT NULL,
    team_short     VARCHAR,
    classic_role   VARCHAR NOT NULL,
    role_class     VARCHAR NOT NULL,
    roles          VARCHAR[] NOT NULL,
    exp_presenze   DOUBLE NOT NULL,
    exp_fantamedia DOUBLE NOT NULL,
    exp_voto       DOUBLE NOT NULL,
    value_p25      DOUBLE NOT NULL,
    value_p50      DOUBLE NOT NULL,
    value_p75      DOUBLE NOT NULL,
    replacement    DOUBLE NOT NULL,
    vor            DOUBLE NOT NULL,
    tier           INTEGER NOT NULL,
    quot_mantra    INTEGER,
    implied_value  DOUBLE,
    divergence     DOUBLE,
    explain        JSON NOT NULL,
    PRIMARY KEY (run_id, player_id)
);
CREATE TABLE IF NOT EXISTS valuation_prices (
    run_id         VARCHAR NOT NULL,
    scenario       VARCHAR NOT NULL,
    player_id      INTEGER NOT NULL,
    role_class     VARCHAR NOT NULL,
    expected_price INTEGER NOT NULL,
    max_p25        INTEGER NOT NULL,
    max_p50        INTEGER NOT NULL,
    max_p75        INTEGER NOT NULL,
    walk_value     DOUBLE NOT NULL,
    exact          BOOLEAN NOT NULL,
    explain        JSON NOT NULL,
    PRIMARY KEY (run_id, scenario, player_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_probabili_files START 1;
CREATE TABLE IF NOT EXISTS probabili_files (
    file_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_probabili_files'),
    season_id   INTEGER NOT NULL,
    giornata    INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_path    VARCHAR NOT NULL,
    sha256      VARCHAR NOT NULL,
    row_count   INTEGER NOT NULL,
    matches     INTEGER NOT NULL,
    uncompiled  INTEGER NOT NULL,
    UNIQUE (season_id, giornata, sha256)
);
CREATE TABLE IF NOT EXISTS probabili (
    file_id     INTEGER NOT NULL,
    season_id   INTEGER NOT NULL,
    giornata    INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    name        VARCHAR NOT NULL,
    club_slug   VARCHAR NOT NULL,
    team_short  VARCHAR,
    formation   VARCHAR,
    p_start     INTEGER NOT NULL,
    bench       BOOLEAN NOT NULL,
    updated_at  TIMESTAMP,
    raw         JSON NOT NULL,
    PRIMARY KEY (file_id, player_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_roster_snapshots START 1;
CREATE TABLE IF NOT EXISTS roster_snapshots (
    snapshot_id    INTEGER PRIMARY KEY DEFAULT nextval('seq_roster_snapshots'),
    league_id      INTEGER NOT NULL,
    season_id      INTEGER,
    fetched_at     TIMESTAMP NOT NULL,
    source         VARCHAR NOT NULL,
    raw_path       VARCHAR NOT NULL,
    sha256         VARCHAR NOT NULL,
    matchday       INTEGER,
    matchday_start TIMESTAMP,
    team_count     INTEGER NOT NULL,
    teams          JSON NOT NULL,
    row_count      INTEGER NOT NULL,
    UNIQUE (league_id, sha256)
);
CREATE TABLE IF NOT EXISTS rosters (
    snapshot_id INTEGER NOT NULL,
    team_id     INTEGER NOT NULL,
    team_name   VARCHAR NOT NULL,
    owner       VARCHAR,
    player_id   INTEGER NOT NULL,
    cost        INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, team_id, player_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_lineup_runs START 1;
CREATE TABLE IF NOT EXISTS lineup_runs (
    lineup_run_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_lineup_runs'),
    season_id         INTEGER NOT NULL,
    giornata          INTEGER NOT NULL,
    run_id            VARCHAR NOT NULL,
    model_hash        VARCHAR NOT NULL,
    probabili_file_id INTEGER NOT NULL,
    deadline          TIMESTAMP NOT NULL,
    written_at        TIMESTAMP NOT NULL,
    late              BOOLEAN NOT NULL,
    my_team           INTEGER,
    module            VARCHAR,
    xi                JSON,
    module_scores     JSON,
    predictions       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS predictions (
    lineup_run_id     INTEGER NOT NULL,
    season_id         INTEGER NOT NULL,
    giornata          INTEGER NOT NULL,
    player_id         INTEGER NOT NULL,
    p_start_published INTEGER,
    p_start           DOUBLE NOT NULL,
    fv_if_plays       DOUBLE NOT NULL,
    fv_sd             DOUBLE,
    expected_points   DOUBLE NOT NULL,
    source            VARCHAR NOT NULL,
    PRIMARY KEY (lineup_run_id, player_id)
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
CREATE OR REPLACE VIEW v_valuation_runs AS
    SELECT r.*, coalesce(r.rules_hash <> (SELECT rules_hash FROM v_league_settings_current), true) AS superseded
    FROM valuation_runs r;
CREATE OR REPLACE VIEW v_valuations_current AS
    SELECT v.* FROM valuations v
    WHERE v.run_id = (SELECT run_id FROM v_valuation_runs WHERE NOT superseded
                      ORDER BY created_at DESC, run_id DESC LIMIT 1);
CREATE OR REPLACE VIEW v_valuation_prices_current AS
    SELECT p.* FROM valuation_prices p
    WHERE p.run_id = (SELECT run_id FROM v_valuation_runs WHERE NOT superseded
                      ORDER BY created_at DESC, run_id DESC LIMIT 1);
CREATE OR REPLACE VIEW v_probabili_files_current AS
    SELECT f.* FROM probabili_files f
    WHERE f.file_id = (SELECT max(g.file_id) FROM probabili_files g
                       WHERE g.season_id = f.season_id AND g.giornata = f.giornata);
CREATE OR REPLACE VIEW v_probabili_current AS
    SELECT p.* FROM probabili p
    WHERE p.file_id IN (SELECT file_id FROM v_probabili_files_current);
CREATE OR REPLACE VIEW v_rosters_current AS
    SELECT r.*, s.league_id, s.season_id, s.fetched_at, s.matchday, s.matchday_start
    FROM rosters r JOIN roster_snapshots s USING (snapshot_id)
    WHERE r.snapshot_id = (SELECT max(snapshot_id) FROM roster_snapshots);
CREATE OR REPLACE VIEW v_rosters_first AS
    SELECT r.*, s.league_id, s.season_id, s.fetched_at
    FROM rosters r JOIN roster_snapshots s USING (snapshot_id)
    WHERE r.snapshot_id IN (SELECT min(snapshot_id) FROM roster_snapshots
                            WHERE row_count > 0 GROUP BY league_id, season_id);
CREATE OR REPLACE VIEW v_market_prices AS
    SELECT f.league_id, f.season_id, f.snapshot_id, f.team_id, f.team_name, f.player_id, f.cost AS paid,
           p.run_id, p.scenario, p.role_class, p.expected_price, p.max_p50,
           v.name, v.classic_role, v.quot_mantra
    FROM v_rosters_first f
    JOIN valuation_runs vr ON vr.season_id = f.season_id
    JOIN valuation_prices p ON p.run_id = vr.run_id AND p.player_id = f.player_id
    LEFT JOIN valuations v ON v.run_id = p.run_id AND v.player_id = f.player_id;
CREATE OR REPLACE VIEW v_lineup_runs_current AS
    SELECT l.* FROM lineup_runs l
    WHERE NOT l.late AND l.lineup_run_id = (SELECT max(m.lineup_run_id) FROM lineup_runs m
                                            WHERE m.season_id = l.season_id AND m.giornata = l.giornata
                                              AND NOT m.late);
"""


class SchemaVersionMismatch(RuntimeError):
    """The file was written by a different schema version; migrate before use."""


def _stored_version(con: duckdb.DuckDBPyConnection) -> int | None:
    try:
        return con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    except duckdb.CatalogException:
        return None


def _has_column(con: duckdb.DuckDBPyConnection, table: str, column: str) -> bool | None:
    """None when the table does not exist."""
    exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'main' "
                         "AND table_name = ?", [table]).fetchone()[0]
    if not exists:
        return None
    return column in {r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()}


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'main' "
                       "AND table_name = ?", [table]).fetchone()[0] > 0


def _migrate_advanced_snapshots_to_v3(con: duckdb.DuckDBPyConnection) -> None:
    """Version 2 keyed advanced_snapshots on sha256 alone (UNIQUE), so a
    changed alias or listone could never re-match an already-recorded file.
    DuckDB cannot drop a UNIQUE constraint, so the table is rebuilt around
    its rows: the old rows keep their snapshot_id (advanced_stats points at
    it) and get a NULL aliases_sha256/listone_snapshot_id, which no new row
    ever has -- the next ingest re-matches them under the full key and
    appends. The sequence is untouched, so new ids continue past the old.

    Gated on the table's actual shape, never on schema_version: a stored
    version is not proof the rebuild happened (an interrupted run, or an
    older binary that hit the bug this docstring used to describe, can
    stamp version 3 without ever finishing it) and its absence is not proof
    the rebuild is unneeded (an old-shape table can carry no version row at
    all). RENAME, CREATE, INSERT and DROP all run inside one transaction --
    they commit together or none of them do, so a crash mid-migration never
    leaves advanced_snapshots renamed away with nothing standing in its
    place. A leftover advanced_snapshots_v2 table -- from exactly that kind
    of crash, or from a full run of the old, non-transactional version of
    this function -- is the resume point: the rows still missing from
    advanced_snapshots (there may be none, if only the final DROP was lost)
    are pulled from it by snapshot_id, and it is then dropped."""
    has_v2 = _table_exists(con, "advanced_snapshots_v2")
    wrong_shape = _has_column(con, "advanced_snapshots", "aliases_sha256") is False
    if not has_v2 and not wrong_shape:
        return
    con.begin()
    try:
        if wrong_shape:
            con.execute("ALTER TABLE advanced_snapshots RENAME TO advanced_snapshots_v2")
            has_v2 = True
        if has_v2:
            con.execute(ADVANCED_SNAPSHOTS_DDL)
            con.execute(
                "INSERT INTO advanced_snapshots SELECT snapshot_id, season_id, fetched_at, source, raw_path, "
                "sha256, NULL, NULL, row_count, matched, ambiguous, unmatched FROM advanced_snapshots_v2 "
                "WHERE snapshot_id NOT IN (SELECT snapshot_id FROM advanced_snapshots)")
            con.execute("DROP TABLE advanced_snapshots_v2")
    except Exception:
        con.rollback()
        raise
    con.commit()


def apply_schema(con: duckdb.DuckDBPyConnection) -> int:
    """Create what is missing, then reconcile the version row.

    The DDL is additive (CREATE ... IF NOT EXISTS, CREATE OR REPLACE VIEW),
    so running it against an older file upgrades it in place -- the live
    database keeps its rows instead of being rebuilt with more live-API
    calls. A table whose *constraint* changed is rebuilt first, around its
    rows. A stored version *newer* than the code is the one case that is
    refused: the code cannot know what that file holds.
    """
    stored = _stored_version(con)
    if stored is not None and stored > SCHEMA_VERSION:
        raise SchemaVersionMismatch(f"database is at schema {stored}, code expects {SCHEMA_VERSION}")
    _migrate_advanced_snapshots_to_v3(con)
    for statement in DDL.split(";"):
        if statement.strip():
            con.execute(statement)
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
