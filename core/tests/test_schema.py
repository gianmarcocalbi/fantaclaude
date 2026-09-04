import duckdb
import pytest
from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.db.schema import (
    ADVANCED_SNAPSHOTS_DDL,
    SCHEMA_VERSION,
    SchemaVersionMismatch,
    apply_schema,
    schema_report,
)

V2_OBJECTS = {"voti_files", "player_match", "advanced_snapshots", "advanced_stats", "fixture_snapshots",
              "fixtures", "v_voti_files_current", "v_player_match_current", "v_player_season",
              "v_player_form", "v_advanced_current", "v_advanced_unmatched", "v_fixtures_current",
              "v_european_ties"}
V3_OBJECTS = {"valuation_runs", "valuations", "valuation_prices",
              "v_valuation_runs", "v_valuations_current", "v_valuation_prices_current"}
V4_OBJECTS = {"probabili_files", "probabili", "roster_snapshots", "rosters", "lineup_runs", "predictions",
              "v_probabili_files_current", "v_probabili_current", "v_rosters_current", "v_rosters_first",
              "v_market_prices", "v_lineup_runs_current"}

# advanced_snapshots exactly as Phase 0b created it: the shape a live version-2 file carries.
V2_ADVANCED_SNAPSHOTS = """
CREATE TABLE advanced_snapshots (
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
)"""


def _columns(con, table):
    return [r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()]


def test_apply_schema_is_idempotent(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    assert apply_schema(con) == SCHEMA_VERSION == 4
    assert apply_schema(con) == SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
    con.close()


def test_schema_report_lists_tables_and_views(db):
    report = schema_report(db)
    kinds = {t.name: t.kind for t in report.tables}
    assert kinds["players"] == "table" and kinds["v_players_current"] == "view"
    assert {"league_settings", "listone_snapshots", "teams", "player_aliases",
            "v_league_settings_current", "v_teams_current"} <= set(kinds)
    assert V2_OBJECTS <= set(kinds) and V3_OBJECTS <= set(kinds)
    assert kinds["valuations"] == "table" and kinds["v_valuation_runs"] == "view"
    players = next(t for t in report.tables if t.name == "players")
    assert [c.name for c in players.columns][:3] == ["snapshot_id", "player_id", "name"]
    assert players.rows == 0
    assert report.version == SCHEMA_VERSION
    assert report.to_dict()["version"] == SCHEMA_VERSION


def test_advanced_snapshots_carries_the_full_dedupe_key(db):
    cols = _columns(db, "advanced_snapshots")
    assert cols == ["snapshot_id", "season_id", "fetched_at", "source", "raw_path", "sha256",
                    "aliases_sha256", "listone_snapshot_id", "row_count", "matched", "ambiguous", "unmatched"]
    row = ["x", "raw", "abc", "al1", 1, 0, 0, 0, 0]
    db.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
               "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (20, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(duckdb.Error):                      # the same three inputs twice is a constraint violation
        db.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
                   "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (20, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    row[3] = "al2"                                          # a changed aliases file is a new derivation
    db.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
               "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (20, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert db.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 2


def test_a_version_1_file_is_migrated_forward_in_place(tmp_path):
    """The Phase 0a database must not be rebuilt with more live-API calls:
    the DDL is additive, so apply_schema upgrades it and keeps its rows."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    for view in sorted(v for v in V2_OBJECTS | V3_OBJECTS if v.startswith("v_")):
        con.execute(f"DROP VIEW {view}")
    for table in ("player_match", "voti_files", "advanced_stats", "advanced_snapshots", "fixtures", "fixture_snapshots",
                  "valuation_prices", "valuations", "valuation_runs"):
        con.execute(f"DROP TABLE {table}")
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (1)")
    con.execute("INSERT INTO teams VALUES (1, 15, 'Roma', 'ROM')")
    con.close()

    con = connect(path)
    assert apply_schema(con) == 4
    assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 2      # history of versions kept
    assert con.execute("SELECT name FROM teams").fetchone()[0] == "Roma"               # v1 rows survive
    assert con.execute("SELECT count(*) FROM v_player_season").fetchone()[0] == 0
    assert "aliases_sha256" in _columns(con, "advanced_snapshots")
    con.close()


def test_a_version_2_file_gets_its_advanced_snapshots_rebuilt(tmp_path):
    """The live Phase 0b file: advanced_snapshots exists in the old shape with
    rows and UNIQUE(sha256). DuckDB cannot drop a constraint, so the table is
    rebuilt around its rows; the old rows get a NULL key -- which is what
    makes the next `ingest advanced` re-match them under the full key."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    for view in sorted(v for v in V3_OBJECTS if v.startswith("v_")):
        con.execute(f"DROP VIEW {view}")
    for table in ("valuation_prices", "valuations", "valuation_runs", "advanced_snapshots"):
        con.execute(f"DROP TABLE {table}")
    con.execute(V2_ADVANCED_SNAPSHOTS)
    con.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, row_count, matched, "
                "ambiguous, unmatched) VALUES (20, now(), 'understat', 'p', 'deadbeef', 10, 5, 1, 4)")
    con.execute("INSERT INTO advanced_stats VALUES (1, 20, '7006', 'Lautaro', ['Inter'], 2764, 'matched', [2764], "
                "30, 2205, 17, 6, 17.1, 6.3, 14, 14.0, 90, 30, 3, 0, 20.0, 5.0, 'F', '{}')")
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (2)")
    con.close()

    con = connect(path)
    assert apply_schema(con) == 4
    assert _columns(con, "advanced_snapshots")[6:8] == ["aliases_sha256", "listone_snapshot_id"]
    kept = con.execute("SELECT snapshot_id, sha256, aliases_sha256, listone_snapshot_id, matched FROM advanced_snapshots").fetchall()
    assert kept == [(1, "deadbeef", None, None, 5)]
    assert con.execute("SELECT count(*) FROM v_advanced_current").fetchone()[0] == 1
    nxt = con.execute("SELECT nextval('seq_advanced_snapshots')").fetchone()[0]
    assert nxt >= 2                                          # the sequence continues past the kept rows
    assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'advanced_snapshots_v2'").fetchone()[0] == 0
    con.close()


def _seed_v2_advanced_snapshots(con) -> None:
    """The live Phase 0b shape, one snapshot with one dependent advanced_stats row."""
    con.execute(V2_ADVANCED_SNAPSHOTS)
    con.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, row_count, matched, "
                "ambiguous, unmatched) VALUES (20, now(), 'understat', 'p', 'deadbeef', 10, 5, 1, 4)")
    con.execute("INSERT INTO advanced_stats VALUES (1, 20, '7006', 'Lautaro', ['Inter'], 2764, 'matched', [2764], "
                "30, 2205, 17, 6, 17.1, 6.3, 14, 14.0, 90, 30, 3, 0, 20.0, 5.0, 'F', '{}')")


def _drop_v3_advanced_snapshots(con) -> None:
    for view in sorted(v for v in V3_OBJECTS if v.startswith("v_")):
        con.execute(f"DROP VIEW {view}")
    for table in ("valuation_prices", "valuations", "valuation_runs", "advanced_snapshots"):
        con.execute(f"DROP TABLE {table}")


def test_an_interrupted_migration_resumes_from_the_leftover_v2_table(tmp_path):
    """The real failure mode: RENAME committed (autocommit, pre-fix), then the
    process died before CREATE/INSERT/DROP ever ran. advanced_snapshots does
    not exist at all -- only advanced_snapshots_v2, holding the real rows.
    The next apply_schema must treat that leftover table as the resume
    point, not create an empty advanced_snapshots and call it done."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    _drop_v3_advanced_snapshots(con)
    _seed_v2_advanced_snapshots(con)
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (2)")
    con.execute("ALTER TABLE advanced_snapshots RENAME TO advanced_snapshots_v2")   # the crash point
    con.close()

    con = connect(path)
    assert apply_schema(con) == 4
    assert _columns(con, "advanced_snapshots")[6:8] == ["aliases_sha256", "listone_snapshot_id"]
    kept = con.execute("SELECT snapshot_id, sha256, aliases_sha256, listone_snapshot_id, matched "
                       "FROM advanced_snapshots").fetchall()
    assert kept == [(1, "deadbeef", None, None, 5)]
    assert con.execute("SELECT count(*) FROM v_advanced_current").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM information_schema.tables "
                       "WHERE table_name = 'advanced_snapshots_v2'").fetchone()[0] == 0
    con.close()


def test_a_migration_already_corrupted_by_the_old_non_atomic_code_still_recovers(tmp_path):
    """Worse than an interrupted RENAME: an older binary ran the whole
    non-transactional sequence, but something failed right before DROP TABLE
    -- or a previous run of *this exact bug* stamped version 3 over an empty
    advanced_snapshots while advanced_snapshots_v2 sat there orphaned. Gating
    the rebuild on schema_version (`stored < 3`) would never look again once
    version 3 is stamped; gating on the table's actual shape recovers it."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    _drop_v3_advanced_snapshots(con)
    _seed_v2_advanced_snapshots(con)
    con.execute("ALTER TABLE advanced_snapshots RENAME TO advanced_snapshots_v2")
    con.execute(ADVANCED_SNAPSHOTS_DDL)                     # the empty v3-shape shell the DDL loop created
    # schema_version is left at 3, as apply_schema's final INSERT would have stamped it.
    con.close()

    con = connect(path)
    assert apply_schema(con) == 4
    kept = con.execute("SELECT snapshot_id, sha256, aliases_sha256, listone_snapshot_id, matched "
                       "FROM advanced_snapshots").fetchall()
    assert kept == [(1, "deadbeef", None, None, 5)]
    assert con.execute("SELECT count(*) FROM information_schema.tables "
                       "WHERE table_name = 'advanced_snapshots_v2'").fetchone()[0] == 0
    con.close()


def test_an_old_shape_table_with_no_version_row_is_still_migrated(tmp_path):
    """A version row is not proof either way: its absence must not be read
    as "nothing to migrate" when the table itself is still the old shape."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    _drop_v3_advanced_snapshots(con)
    _seed_v2_advanced_snapshots(con)
    con.execute("DELETE FROM schema_version")               # no version row at all
    con.close()

    con = connect(path)
    assert apply_schema(con) == 4
    assert "aliases_sha256" in _columns(con, "advanced_snapshots")
    assert con.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 1
    con.close()


def test_a_failure_mid_migration_rolls_back_atomically(tmp_path, monkeypatch):
    """RENAME, CREATE, INSERT and DROP must commit together or not at all --
    otherwise a crash between them stamps advanced_snapshots renamed away
    with nothing standing in its place, which is exactly finding 1."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    _drop_v3_advanced_snapshots(con)
    _seed_v2_advanced_snapshots(con)
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (2)")
    con.close()

    con = connect(path)
    real_execute = duckdb.DuckDBPyConnection.execute

    def flaky(self, sql, *a, **kw):
        if isinstance(sql, str) and sql.strip().startswith("DROP TABLE advanced_snapshots_v2"):
            raise RuntimeError("simulated crash")
        return real_execute(self, sql, *a, **kw)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", flaky)
    with pytest.raises(RuntimeError, match="simulated crash"):
        apply_schema(con)
    monkeypatch.undo()

    # Rolled back: the original table, under its original name, unharmed --
    # not left renamed away with a half-built replacement standing in.
    assert con.execute("SELECT count(*) FROM information_schema.tables "
                       "WHERE table_name = 'advanced_snapshots_v2'").fetchone()[0] == 0
    assert "sha256" in _columns(con, "advanced_snapshots") and "aliases_sha256" not in _columns(con, "advanced_snapshots")
    assert con.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 1
    con.close()

    # A later, unobstructed apply_schema still finishes the job.
    con = connect(path)
    assert apply_schema(con) == 4
    kept = con.execute("SELECT snapshot_id, sha256, aliases_sha256, listone_snapshot_id, matched "
                       "FROM advanced_snapshots").fetchall()
    assert kept == [(1, "deadbeef", None, None, 5)]
    con.close()


def test_a_newer_file_is_refused(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    apply_schema(con)
    con.execute("INSERT INTO schema_version (version) VALUES (99)")
    with pytest.raises(SchemaVersionMismatch):
        apply_schema(con)
    con.close()


def test_read_only_connection_requires_an_existing_file(tmp_path):
    with pytest.raises(DatabaseMissing):
        connect(tmp_path / "missing.duckdb", read_only=True)


def test_read_only_connection_rejects_writes(tmp_path):
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    con.close()
    ro = connect(path, read_only=True)
    with pytest.raises(duckdb.Error):
        ro.execute("INSERT INTO teams VALUES (1, 1, 'x', 'X')")
    ro.close()


def test_write_connection_creates_the_parent_directory(tmp_path):
    con = connect(tmp_path / "nested" / "x.duckdb")
    con.close()
    assert (tmp_path / "nested" / "x.duckdb").is_file()


def test_views_over_empty_history_are_queryable(db):
    for view in sorted(v for v in V2_OBJECTS | V3_OBJECTS if v.startswith("v_")):
        assert db.execute(f"SELECT count(*) FROM {view}").fetchone()[0] == 0, view


def test_valuation_views_pick_the_newest_run_under_the_rules_in_force(db, mcp_fixture_json):
    from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads

    snap = snapshot_from_payloads(profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
                                  rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
                                  calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams"))
    record_snapshot(db, snap)
    for run_id, rules, created in (("r1", snap.rules_hash, "2026-08-29 10:00:00"), ("r2", "0000000000000000", "2026-08-29 11:00:00"),
                                   ("r3", snap.rules_hash, "2026-08-29 09:00:00")):
        db.execute("INSERT INTO valuation_runs VALUES (?, ?, ?, 'm', 'i', 1, 1, 21, 2, ['balanced'], '{}', '{}')",
                   [run_id, created, rules])
        db.execute("INSERT INTO valuations VALUES (?, 2764, 'Martinez L.', 'INT', 'A', 'Pc', ['Pc'], 33.0, 7.1, 6.4, "
                   "200.0, 234.0, 260.0, 90.0, 144.0, 1, 35, 230.0, 4.0, '{}')", [run_id])
        db.execute("INSERT INTO valuation_prices VALUES (?, 'balanced', 2764, 'Pc', 42, 60, 68, 75, 1500.0, true, '{}')", [run_id])
    superseded = dict(db.execute("SELECT run_id, superseded FROM v_valuation_runs").fetchall())
    assert superseded == {"r1": False, "r2": True, "r3": False}
    assert db.execute("SELECT run_id FROM v_valuations_current").fetchall() == [("r1",)]      # newest, not superseded
    assert db.execute("SELECT run_id FROM v_valuation_prices_current").fetchall() == [("r1",)]


def test_version_4_adds_the_forecast_and_roster_layer(tmp_path):
    con = connect(tmp_path / "v4.duckdb")
    assert apply_schema(con) == 4 and SCHEMA_VERSION == 4
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
    assert V4_OBJECTS <= names
    assert _columns(con, "predictions") == ["lineup_run_id", "season_id", "giornata", "player_id", "p_start_published",
                                            "p_start", "fv_if_plays", "fv_sd", "expected_points", "source"]
    assert _columns(con, "lineup_runs")[:6] == ["lineup_run_id", "season_id", "giornata", "run_id", "model_hash",
                                                "probabili_file_id"]
    assert _columns(con, "rosters") == ["snapshot_id", "team_id", "team_name", "owner", "player_id", "cost", "position"]
    # a version-3 file upgrades in place: apply twice, version row once per level
    assert apply_schema(con) == 4
    assert con.execute("SELECT count(*) FROM schema_version WHERE version = 4").fetchone()[0] == 1
    con.close()
