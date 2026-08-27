import json

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.db.connection import connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from typer.testing import CliRunner


def _seeded_workspace(monkeypatch, tmp_path, fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    raw = RawStore(tmp_path / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    con.close()                      # the CLI reopens read-only, in what would be another process


def test_schema_and_query_need_a_database(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == ExitCode.NOT_READY and "sync-league" in result.stderr
    assert runner.invoke(app, ["query", "--sql", "select 1"]).exit_code == ExitCode.NOT_READY


def test_schema_lists_views_and_row_counts(monkeypatch, tmp_path, fixture_json):
    _seeded_workspace(monkeypatch, tmp_path, fixture_json)
    result = CliRunner().invoke(app, ["schema", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    by = {t["name"]: t for t in payload["tables"]}
    assert by["players"]["rows"] == 17 and by["v_players_current"]["kind"] == "view"
    assert payload["version"] == 1
    plain = CliRunner().invoke(app, ["schema"])
    assert "view v_players_current" in plain.stdout


def test_query_returns_rows_and_refuses_writes(monkeypatch, tmp_path, fixture_json):
    _seeded_workspace(monkeypatch, tmp_path, fixture_json)
    runner = CliRunner()
    result = runner.invoke(app, ["query", "--json", "--sql",
        "SELECT player_id, name FROM v_players_current WHERE list_contains(mantra_roles, 'B') ORDER BY player_id"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["columns"] == ["player_id", "name"] and payload["rows"] == [[5877, "Carlos Augusto"]]
    assert payload["truncated"] is False

    result = runner.invoke(app, ["query", "--sql", "DELETE FROM players"])
    assert result.exit_code == ExitCode.ERROR and "query failed" in result.stderr

    result = runner.invoke(app, ["query", "--json", "--limit", "5", "--sql",
                                 "SELECT player_id FROM v_players_current ORDER BY player_id"])
    payload = json.loads(result.stdout)
    assert len(payload["rows"]) == 5 and payload["truncated"] is True

    plain = runner.invoke(app, ["query", "--sql", "SELECT count(*) AS n FROM v_players_current"])
    assert plain.exit_code == ExitCode.OK and "17" in plain.stdout
