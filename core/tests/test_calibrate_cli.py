import asyncio
import json
from datetime import UTC, datetime

from conftest import seed_fixtures, seed_lineup_run, seed_voti_matching
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.db.connection import connect
from test_lineup_cli import (
    LINEUP_CALCULATED,
    LINEUP_CALENDAR,
    _ingest_lineup_workspace,
    _ranked,
)
from typer.testing import CliRunner

runner = CliRunner()


def _scored_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api):
    _ingest_lineup_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    api = fake_api(overrides={"competition_calendar": LINEUP_CALENDAR, "lineup": LINEUP_CALCULATED})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    assert runner.invoke(app, ["ingest", "lineup", "--giornata", "3"]).exit_code == ExitCode.OK
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_voti_matching(con, 21, LINEUP_CALCULATED)
    seed_fixtures(con, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    seed_lineup_run(con, 21, 3, [(632, 90, 0.9, 6.5, 1.0), (7017, 85, 0.85, 6.0, 1.0)])
    con.close()


def test_calibrate_reports_the_week_the_page_and_the_platform_check(monkeypatch, tmp_path, fixture_json,
                                                                      mcp_fixture_json, fake_api):
    _scored_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api)
    result = runner.invoke(app, ["calibrate", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["giornate"] == [3] and payload["weeks"][0]["result"] == "1-4"
    assert payload["p_start"]["n"] == 2 and payload["scoring"]["checked"] == 46 and payload["scoring"]["ok"]
    plain = runner.invoke(app, ["calibrate"])
    assert plain.exit_code == ExitCode.OK, plain.output
    for phrase in ("giornata 3: 67 – 82.5", "lost 1-4", "best possible", "no forecast named an XI",
                   "p_start (published, 2 rows", "46 platform rows agree with the voti"):
        assert phrase in plain.stdout, phrase


def test_calibrate_opens_the_database_read_only(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api):
    from fantaclaude.db import connection

    _scored_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api)
    seen, real = [], connection.connect
    monkeypatch.setattr(connection, "connect", lambda *a, **kw: seen.append(kw.get("read_only", False)) or real(*a, **kw))
    assert runner.invoke(app, ["calibrate", "--json"]).exit_code == ExitCode.OK
    assert seen and all(seen)


def test_calibrate_is_not_ready_with_nothing_to_score(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["calibrate"])
    assert result.exit_code == ExitCode.NOT_READY and "no giornata" in result.stderr
