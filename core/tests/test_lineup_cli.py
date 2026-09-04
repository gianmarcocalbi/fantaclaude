import json
from datetime import UTC, datetime, timedelta

import httpx
import respx
from conftest import FIXTURE_DIR, seed_fixtures, seed_probabili, seed_rosters
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.db.connection import connect
from test_rank_cli import _workspace
from typer.testing import CliRunner

runner = CliRunner()
SAMPLE = (FIXTURE_DIR / "probabili_sample.html").read_text(encoding="utf-8")
PAGE = [(2764, "Martinez L.", "inter", 90), (5841, "Svilar", "roma", 100), (2640, "Kolasinac", "atalanta", 55),
        (2120, "Bastoni", "inter", 90), (254, "Dimarco", "inter", 75), (2194, "Calhanoglu", "inter", 35)]


def _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["rank", "--offline", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    return json.loads(result.stdout)["run_id"]


def _calendar(tmp_path, *, first: datetime):
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_fixtures(con, 21, {3: [first, first + timedelta(days=3)], 4: [first + timedelta(days=7)]})
    con.close()


def _page(tmp_path):
    con = connect(tmp_path / "data" / "fanta.duckdb")
    file_id = seed_probabili(con, 21, 3, PAGE)
    con.close()
    return file_id


def test_lineup_writes_the_forecast_for_every_listed_priced_player(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    run_id = _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    _page(tmp_path)
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["round"]["giornata"] == 3 and payload["run_id"] == run_id and payload["late"] is False
    assert payload["predictions"] == 6 and payload["xi"] is None and "my_team" in payload["no_xi_reason"]
    assert set(payload["top"]) == {"P", "D", "C", "A"} and payload["top"]["A"][0]["player_id"] == 2764
    assert [p.rsplit("/", 2)[-2] for p in payload["records"]] == ["lineup_runs", "predictions"]
    plain = runner.invoke(app, ["lineup"])
    assert plain.exit_code == ExitCode.OK and "XI: none" in plain.stdout and "6 predictions" in plain.stdout


def test_lineup_is_refused_after_kickoff_and_marked_with_late(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) - timedelta(hours=1))
    _page(tmp_path)
    refused = runner.invoke(app, ["lineup"])
    assert refused.exit_code == ExitCode.CONFLICT and "--late" in refused.stderr
    late = runner.invoke(app, ["lineup", "--late", "--json"])
    assert late.exit_code == ExitCode.OK, late.output
    assert json.loads(late.stdout)["late"] is True


def test_lineup_says_what_is_missing(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    no_calendar = runner.invoke(app, ["lineup"])
    assert no_calendar.exit_code == ExitCode.NOT_READY and "ingest calendar" in no_calendar.stderr
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    no_page = runner.invoke(app, ["lineup"])
    assert no_page.exit_code == ExitCode.NOT_READY and "ingest probabili" in no_page.stderr


@respx.mock
def test_ingest_probabili_fetches_once_and_records_under_the_calendars_giornata(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    route = respx.get("https://www.fantacalcio.it/probabili-formazioni-serie-a").mock(return_value=httpx.Response(200, text=SAMPLE))
    result = runner.invoke(app, ["ingest", "probabili", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert route.call_count == 1 and payload["giornata"] == 3 and payload["matches"] == 2 and not payload["skipped_duplicate"]
    assert list((tmp_path / "data" / "raw" / "probabili").glob("*-probabili-21-03.html"))
    again = runner.invoke(app, ["ingest", "probabili", "--json"])
    assert json.loads(again.stdout)["skipped_duplicate"] is True and route.call_count == 2
    # The sample page names its own giornata (3, Task 3's meta-tag parse) -- asking to
    # record it under 4 must be refused, not silently accepted (the designed cross-check).
    plain = runner.invoke(app, ["ingest", "probabili", "--giornata", "4"])
    assert plain.exit_code == ExitCode.CONFLICT and "giornata 3" in plain.stderr


@respx.mock
def test_ingest_probabili_maps_a_changed_page_to_exit_1(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    respx.get("https://www.fantacalcio.it/probabili-formazioni-serie-a").mock(return_value=httpx.Response(200, text="<html></html>"))
    result = runner.invoke(app, ["ingest", "probabili"])
    assert result.exit_code == ExitCode.ERROR and "player-item" in result.stderr


def test_lineup_names_the_xi_when_league_yml_names_my_team(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]     # the 17 can field 3-4-3
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone])
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone})})
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    xi = payload["xi"]
    assert payload["my_team"] == 4242 and xi["module"] in payload["xi"]["module_scores"] and len(xi["slots"]) == 11
    assert payload["predictions"] == 17
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT my_team, module FROM lineup_runs").fetchone() == (4242, xi["module"])
    con.close()
    plain = runner.invoke(app, ["lineup"])
    assert plain.exit_code == ExitCode.OK and f"XI: {xi['module']}" in plain.stdout


def test_lineup_with_my_team_but_no_roster_still_writes_the_forecast(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    _page(tmp_path)
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["xi"] is None and "ingest rosters" in payload["no_xi_reason"] and payload["predictions"] == 6
