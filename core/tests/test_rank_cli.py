import json
from datetime import UTC, datetime

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.rank import provisional_note
from fantaclaude.db.connection import connect
from fantaclaude.league.league_yml import load_league_yml
from test_valuation import seeded
from typer.testing import CliRunner

runner = CliRunner()


def _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    (tmp_path / "pricing.yml").write_text("bench_weight: 0.12\n")
    (tmp_path / "preferences.yml").write_text(
        "risk_appetite: balanced\nmax_budget_share_per_role: {}\nexcluded_clubs: []\ntarget_composition: {Por: 2}\n"
        "scenarios:\n  aggressive-attack: {target_composition: {A: 2, Pc: 2}, risk_appetite: aggressive}\n"
        "  value-hunting: {risk_appetite: cautious}\n")
    (tmp_path / "league.yml").write_text(
        "budget: {value: 500, source: admin, verified_on: 2026-08-24}\n"
        "auction: {date: {value: 2026-09-05, source: admin, verified_on: 2026-08-22, note: approximate}}\n")


def test_rank_offline_writes_a_run_renders_and_records(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["rank", "--offline", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["players"] == 17 and payload["scenarios"] == ["balanced", "aggressive-attack", "value-hunting"]
    assert payload["run_id"].endswith(payload["model_hash"][:4] + payload["rules_hash"][:4])
    assert sorted(p.rsplit("/", 1)[-1] for p in payload["exports"]) == ["asta-plan.md", "rankings.csv", "rankings.md"]
    assert len(payload["records"]) == 4 and all(p.endswith(".parquet") for p in payload["records"])
    assert payload["provisional"].startswith("provisional")
    assert (tmp_path / "data" / "exports" / "rankings.md").is_file()
    assert (tmp_path / "records" / "valuations" / f"{payload['run_id']}.parquet").is_file()
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM valuation_prices").fetchone()[0] == 17 * 3
    assert con.execute("SELECT run_id FROM v_valuations_current LIMIT 1").fetchone()[0] == payload["run_id"]
    con.close()

    plain = runner.invoke(app, ["rank", "--offline"])
    assert plain.exit_code == ExitCode.OK, plain.output
    assert "run " in plain.stdout and "balanced" in plain.stdout and "provisional" in plain.stdout
    assert "Martinez L." in plain.stdout

    one = runner.invoke(app, ["rank", "--offline", "--scenario", "value-hunting", "--json"])
    assert one.exit_code == ExitCode.OK and json.loads(one.stdout)["scenarios"] == ["value-hunting"]
    bad = runner.invoke(app, ["rank", "--offline", "--scenario", "nope"])
    assert bad.exit_code == ExitCode.USAGE and "nope" in bad.stderr


def test_rank_re_syncs_first_unless_offline(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    calls = []

    def fake_run_with_api(fn):
        import asyncio

        calls.append("sync")
        return asyncio.run(fn(fake_api()))

    monkeypatch.setattr("fantaclaude.api_client.run_with_api", fake_run_with_api)
    result = runner.invoke(app, ["rank", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    assert calls == ["sync"] and json.loads(result.stdout)["players"] == 17

    calls.clear()
    assert runner.invoke(app, ["rank", "--offline", "--json"]).exit_code == ExitCode.OK and calls == []

    # a league.yml that disagrees with the API refuses the whole command, before any run is written
    (tmp_path / "league.yml").write_text("budget: {value: 999, source: admin, verified_on: 2026-08-24}\n")
    conflict = runner.invoke(app, ["rank"])
    assert conflict.exit_code == ExitCode.CONFLICT and "CONFLICT budget" in conflict.stdout
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0] == 2
    con.close()


def test_rank_refuses_when_not_ready(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    assert runner.invoke(app, ["rank", "--offline"]).exit_code == ExitCode.NOT_READY

    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    (tmp_path / "pricing.yml").write_text("bench_weight: heavy\n")
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY and "pricing.yml" in result.stderr

    (tmp_path / "pricing.yml").write_text("bench_weight: 0.12\n")
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["smodf"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY and "smodf" in result.stderr


def test_provisional_note_reads_the_auction_date(tmp_path):
    (tmp_path / "league.yml").write_text(
        "auction: {date: {value: 2026-09-05, source: admin, verified_on: 2026-08-22}}\n")
    entries = load_league_yml(tmp_path / "league.yml")
    early = provisional_note(entries, datetime(2026, 8, 30, tzinfo=UTC), 8)
    assert early.startswith("provisional") and "8 teams" in early and "6 days" in early
    late = provisional_note(entries, datetime(2026, 9, 4, 12, tzinfo=UTC), 10)
    assert late.startswith("final window") and "10 teams" in late
    assert provisional_note(None, datetime(2026, 8, 30, tzinfo=UTC), 8).startswith("provisional")


def test_a_bare_value_error_from_run_valuation_is_not_mistaken_for_not_ready(
        monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """PricingConfigError subclasses ValueError, and price_board itself raises a bare
    ValueError for an ordinary modelling error (an unknown role class) -- that is not
    "not ready" (exit 3) and must not be caught by a broad `except ValueError`. Stand
    in for price_board's bare ValueError with a monkeypatched run_valuation, since
    reproducing the real "unknown role class" branch would need a broken weights table."""
    import fantaclaude.commands.rank as rank_module

    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)

    def boom(*args, **kwargs):
        raise ValueError("player 1 has role class 'Xy', which the weights do not know")

    monkeypatch.setattr(rank_module, "run_valuation", boom)
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code != ExitCode.NOT_READY, result.output
    assert result.exit_code == ExitCode.ERROR
