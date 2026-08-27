import asyncio
import json

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.sync_league import sync_league
from fantaclaude.league.league_yml import load_league_yml
from typer.testing import CliRunner


async def test_sync_records_a_snapshot_and_reports_no_change_on_rerun(db, fake_api):
    api = fake_api()
    first = await sync_league(api, db, None)
    assert first.changed and first.snapshot_id == 1 and first.league_id == 2578630
    assert first.team_count == 8 and first.season_id == 21
    second = await sync_league(api, db, None)
    assert not second.changed and second.snapshot_id == 1
    assert api.calls.count("league_profile") == 2


async def test_sync_reports_what_changed(db, fake_api, mcp_fixture_json):
    await sync_league(fake_api(), db, None)
    richer = fake_api(overrides={"roster_settings": dict(mcp_fixture_json("roster_settings"), budg=1000)})
    report = await sync_league(richer, db, None)
    assert report.changed and [c.path for c in report.diff] == ["rosters.budg"]
    assert report.to_dict()["diff"] == [{"path": "rosters.budg", "before": 500, "after": 1000}]


async def test_conflict_with_league_yml_records_nothing(db, fake_api, tmp_path):
    path = tmp_path / "league.yml"
    path.write_text("budget: {value: 1000, source: admin, verified_on: 2026-08-24}\n")
    report = await sync_league(fake_api(), db, load_league_yml(path))
    assert report.conflicts and report.conflicts[0].key == "budget"
    assert report.snapshot_id is None and not report.changed
    assert db.execute("SELECT count(*) FROM league_settings").fetchone()[0] == 0


def test_cli_sync_league_json_and_exit_codes(monkeypatch, tmp_path, fake_api):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    api = fake_api()
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    runner = CliRunner()
    result = runner.invoke(app, ["sync-league", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["changed"] is True and payload["snapshot_id"] == 1 and payload["conflicts"] == []
    assert (tmp_path / "data" / "fanta.duckdb").is_file()

    (tmp_path / "league.yml").write_text("budget: {value: 1000, source: admin, verified_on: 2026-08-24}\n")
    result = runner.invoke(app, ["sync-league"])
    assert result.exit_code == ExitCode.CONFLICT
    assert "budget" in result.stdout and "1000" in result.stdout and "500" in result.stdout
