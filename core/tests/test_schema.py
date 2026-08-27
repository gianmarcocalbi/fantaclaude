import duckdb
import pytest
from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.db.schema import SCHEMA_VERSION, apply_schema, schema_report


def test_apply_schema_is_idempotent(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    assert apply_schema(con) == SCHEMA_VERSION
    assert apply_schema(con) == SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
    con.close()


def test_schema_report_lists_tables_and_views(db):
    report = schema_report(db)
    kinds = {t.name: t.kind for t in report.tables}
    assert kinds["players"] == "table" and kinds["v_players_current"] == "view"
    assert {"league_settings", "listone_snapshots", "teams", "player_aliases",
            "v_league_settings_current", "v_teams_current"} <= set(kinds)
    players = next(t for t in report.tables if t.name == "players")
    assert [c.name for c in players.columns][:3] == ["snapshot_id", "player_id", "name"]
    assert players.rows == 0
    assert report.version == SCHEMA_VERSION
    assert report.to_dict()["version"] == SCHEMA_VERSION


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
