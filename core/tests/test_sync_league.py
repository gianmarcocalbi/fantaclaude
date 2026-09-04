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

    # a league.yml leaf without provenance is not-ready (3), the same code rank gives it,
    # and it is refused before the network is touched
    (tmp_path / "league.yml").write_text("budget: 1000\n")
    calls_before = len(api.calls)
    result = runner.invoke(app, ["sync-league"])
    assert result.exit_code == ExitCode.NOT_READY and "league.yml" in result.stderr
    assert len(api.calls) == calls_before


def test_a_rule_change_reports_the_runs_it_supersedes(db, mcp_fixture_json, fake_api):
    import asyncio

    from fantaclaude.commands.sync_league import sync_league

    first = asyncio.run(sync_league(fake_api(), db, None))
    assert first.changed and first.superseded_runs == 0
    db.execute("INSERT INTO valuation_runs VALUES ('r1', now(), ?, 'm', 'i', 1, 1, 21, 2, ['balanced'], '{}', '{}')",
               [first.rules_hash])
    unchanged = asyncio.run(sync_league(fake_api(), db, None))
    assert not unchanged.changed and unchanged.superseded_runs == 0
    rosters = mcp_fixture_json("roster_settings")
    rosters["budg"] = 600
    changed = asyncio.run(sync_league(fake_api({"roster_settings": rosters}), db, None))
    assert changed.changed and changed.superseded_runs == 1 and changed.to_dict()["superseded_runs"] == 1
    assert db.execute("SELECT superseded FROM v_valuation_runs WHERE run_id = 'r1'").fetchone()[0] is True

    # Finding 8. The count was every run whose rules_hash is not the new one --
    # every run ever superseded, not the ones *this* change supersedes. With a
    # single rules change the two are the same number, which is why one change
    # was never enough to see it. Rank again under the new rules, change the
    # rules a second time, and only the run that was current may be reported.
    db.execute("INSERT INTO valuation_runs VALUES ('r2', now(), ?, 'm', 'i', 2, 1, 21, 2, ['balanced'], '{}', '{}')",
               [changed.rules_hash])
    rosters["budg"] = 700
    again = asyncio.run(sync_league(fake_api({"roster_settings": rosters}), db, None))
    assert again.changed and again.superseded_runs == 1, "r1 was already superseded by the first change"
    assert again.previous_hash == changed.rules_hash
    superseded = dict(db.execute("SELECT run_id, superseded FROM v_valuation_runs ORDER BY run_id").fetchall())
    assert superseded == {"r1": True, "r2": True}                # both stale now; only one became stale here


def test_a_failed_fetch_leaves_no_database_behind(monkeypatch, tmp_path):
    """The database must not exist until there is something to record. A file
    created before the first network call survives the failure and then answers
    "schema v1, 0 rows" -- so a skill can no longer tell "nothing ingested yet"
    from "ingested and empty"."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))

    def boom(fn):
        raise RuntimeError("no credentials")

    monkeypatch.setattr("fantaclaude.api_client.run_with_api", boom)
    result = CliRunner().invoke(app, ["sync-league", "--json"])
    assert result.exit_code != ExitCode.OK
    assert not (tmp_path / "data" / "fanta.duckdb").exists(), "phantom database created"


def test_a_league_yml_conflict_leaves_no_database_behind(monkeypatch, tmp_path, fake_api):
    """Exit 4 records nothing -- including the file itself."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    (tmp_path / "league.yml").write_text(
        "budget: {value: 1000, source: admin, verified_on: 2026-08-24}\n")
    api = fake_api()
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    result = CliRunner().invoke(app, ["sync-league"])
    assert result.exit_code == ExitCode.CONFLICT
    assert not (tmp_path / "data" / "fanta.duckdb").exists(), "phantom database created"


async def test_the_team_list_is_paged_until_exhausted_and_checked_against_the_division_count(db, fake_api, mcp_fixture_json):
    """Spec open question 12 (found 2026-09-02): the endpoint pages by ten,
    and `fetch_snapshot` read page 1 only, so the eleventh team -- the one
    who just joined, before an auction -- fell off silently. Every page is
    read, and a total that disagrees with `divisions[].count` is a warning
    the report carries rather than a snapshot that quietly lies."""
    teams = mcp_fixture_json("teams")
    rows = teams["data"]
    extra = [{**rows[0], "id": 900 + i, "idu": 700 + i, "n": f"Team {i}", "nu": f"nick{i}"} for i in range(4)]
    page1 = {**teams, "nextPage": True, "pages": 2, "item": 12, "data": rows + extra[:2],
             "divisions": [{"division": "A", "count": 12}]}
    page2 = {**teams, "nextPage": False, "prevPage": True, "page": 2, "pages": 2, "item": 12, "data": extra[2:],
             "divisions": [{"division": "A", "count": 12}]}
    pages = {1: page1, 2: page2}
    api = fake_api()

    async def teams_by_page(page=1, league=None):
        api.calls.append(f"teams:{page}")
        return json.loads(json.dumps(pages[page]))

    api.teams = teams_by_page
    report = await sync_league(api, db, None)
    assert api.calls.count("teams:1") == 1 and api.calls.count("teams:2") == 1
    stored = json.loads(db.execute("SELECT payload FROM league_settings WHERE snapshot_id = ?", [report.snapshot_id]).fetchone()[0])
    assert len(stored["teams"]["data"]) == 12 and report.warnings == []
    # a division count the pages do not add up to is said, not hidden
    short = {1: {**page1, "nextPage": False, "pages": 1, "divisions": [{"division": "A", "count": 12}]}}

    async def one_short_page(page=1, league=None):
        return json.loads(json.dumps(short[page]))

    api.teams = one_short_page
    again = await sync_league(api, db, None)
    assert len(again.warnings) == 1 and "10" in again.warnings[0] and "12" in again.warnings[0]
    assert again.to_dict()["warnings"] == again.warnings
