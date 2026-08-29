import duckdb
import pytest
from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.db.schema import (
    SCHEMA_VERSION,
    SchemaVersionMismatch,
    apply_schema,
    schema_report,
)

V2_OBJECTS = {"voti_files", "player_match", "advanced_snapshots", "advanced_stats", "fixture_snapshots",
              "fixtures", "v_voti_files_current", "v_player_match_current", "v_player_season",
              "v_player_form", "v_advanced_current", "v_advanced_unmatched", "v_fixtures_current",
              "v_european_ties"}


def test_apply_schema_is_idempotent(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    assert apply_schema(con) == SCHEMA_VERSION == 2
    assert apply_schema(con) == SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
    con.close()


def test_schema_report_lists_tables_and_views(db):
    report = schema_report(db)
    kinds = {t.name: t.kind for t in report.tables}
    assert kinds["players"] == "table" and kinds["v_players_current"] == "view"
    assert {"league_settings", "listone_snapshots", "teams", "player_aliases",
            "v_league_settings_current", "v_teams_current"} <= set(kinds)
    assert V2_OBJECTS <= set(kinds)
    assert kinds["player_match"] == "table" and kinds["v_player_season"] == "view"
    players = next(t for t in report.tables if t.name == "players")
    assert [c.name for c in players.columns][:3] == ["snapshot_id", "player_id", "name"]
    assert players.rows == 0
    assert report.version == SCHEMA_VERSION
    assert report.to_dict()["version"] == SCHEMA_VERSION


def test_a_version_1_file_is_migrated_forward_in_place(tmp_path):
    """The Phase 0a database must not be rebuilt with more live-API calls:
    the v2 DDL is additive, so apply_schema upgrades it and keeps its rows."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    # Turn the file back into a Phase 0a one: drop everything v2 added, stamp version 1.
    for view in sorted(v for v in V2_OBJECTS if v.startswith("v_")):
        con.execute(f"DROP VIEW {view}")
    for table in ("player_match", "voti_files", "advanced_stats", "advanced_snapshots", "fixtures", "fixture_snapshots"):
        con.execute(f"DROP TABLE {table}")
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (1)")
    con.execute("INSERT INTO teams VALUES (1, 15, 'Roma', 'ROM')")
    con.close()

    con = connect(path)
    assert apply_schema(con) == 2
    assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 2      # history of versions kept
    assert con.execute("SELECT name FROM teams").fetchone()[0] == "Roma"               # v1 rows survive
    assert con.execute("SELECT count(*) FROM v_player_season").fetchone()[0] == 0
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
    con.close()                      # one mode per process: close before reopening read-only
    ro = connect(path, read_only=True)
    with pytest.raises(duckdb.Error):
        ro.execute("INSERT INTO teams VALUES (1, 1, 'x', 'X')")
    ro.close()


def test_write_connection_creates_the_parent_directory(tmp_path):
    con = connect(tmp_path / "nested" / "x.duckdb")
    con.close()
    assert (tmp_path / "nested" / "x.duckdb").is_file()


def test_views_over_empty_history_are_queryable(db):
    for view in sorted(v for v in V2_OBJECTS if v.startswith("v_")):
        assert db.execute(f"SELECT count(*) FROM {view}").fetchone()[0] == 0, view
