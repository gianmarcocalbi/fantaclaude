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
    assert one.exit_code == ExitCode.OK
    one_payload = json.loads(one.stdout)
    assert one_payload["scenarios"] == ["value-hunting"]
    # The report payload is only half of it -- record_run persists an immutable row, so
    # the filtered board must be what actually landed: one scenario's worth of prices,
    # never the full three, and the stored config must name only what ran (Trap 2).
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM valuation_prices WHERE run_id = ?",
                       [one_payload["run_id"]]).fetchone()[0] == 17
    stored_config = json.loads(con.execute("SELECT config FROM valuation_runs WHERE run_id = ?",
                                           [one_payload["run_id"]]).fetchone()[0])
    assert stored_config["scenarios"] == ["value-hunting"]
    con.close()

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
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY
    # Finding 2: a missing preferences.yml must be caught before connect() ever
    # creates and schemas the database -- otherwise doctor reports "ok, schema
    # version 3" on a workspace where nothing was ever ingested.
    assert not (tmp_path / "data" / "fanta.duckdb").exists(), "phantom database created"

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


def test_rank_exits_not_ready_for_an_unknown_voto_source_or_a_malformed_note(monkeypatch, tmp_path, fixture_json,
                                                                              mcp_fixture_json):
    """Finding 4. These used to escape run_valuation unwrapped and land as a
    bare traceback at exit 1 -- ScoringError and NoteError are not
    ValuationError -- even though the contract lists "voto source unknown"
    under exit 3."""
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["sourcev"] = 9
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY and "voto source" in result.stderr

    payload["calculate"]["sourcev"] = 1
    con = connect(tmp_path / "data" / "fanta.duckdb")
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    note_dir = tmp_path / "kb" / "serie-a" / "teams" / "inter" / "players"
    note_dir.mkdir(parents=True)
    (note_dir / "bad.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                     "player_id: 2764\nname: Martinez L.\nteam_short: INT\ndepth: titolare\n---\n# n\n")
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY and "depth" in result.stderr


def test_rank_exits_not_ready_when_the_hand_written_d_factor_table_does_not_parse(monkeypatch, tmp_path, fixture_json,
                                                                                   mcp_fixture_json):
    """Finding 7. check_ready caught DFactorTableError only, so a YAML syntax
    error in the one file a human transcribes by hand escaped as a traceback
    at exit 1. A malformed config is exit 3."""
    import fantaclaude.commands.rank as rank_module
    from fantaclaude.model.d_factor import load_d_factor

    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    bad = tmp_path / "d_factor.yml"
    bad.write_text("bands: [ {min: 6.0, points: 1 }\n", encoding="utf-8")
    monkeypatch.setattr(rank_module, "load_d_factor", lambda: load_d_factor(bad))
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY, result.output
    assert "d_factor.yml" in result.stderr


def test_provisional_note_reads_the_auction_date(tmp_path):
    # The plan's requirement (line 30) is seven days, not the two an earlier
    # draft of rank.py mis-copied into FINAL_WINDOW_DAYS.
    (tmp_path / "league.yml").write_text(
        "auction: {date: {value: 2026-09-05, source: admin, verified_on: 2026-08-22}}\n")
    entries = load_league_yml(tmp_path / "league.yml")
    far = provisional_note(entries, datetime(2026, 8, 20, tzinfo=UTC), 8)
    assert far.startswith("provisional") and "8 teams" in far and "16 days" in far
    assert "does not say how many are expected" in far          # league.yml has no team_count leaf today

    # Inside the window: the wording changes, the "provisional" label never does --
    # the freeze makes a run final, not the calendar, and this code cannot see the freeze.
    near = provisional_note(entries, datetime(2026, 9, 4, 12, tzinfo=UTC), 10)
    assert near.startswith("provisional") and "10 teams" in near and "1 days" in near
    assert "final" not in near.split(" -- ", 1)[0]
    assert "pre-freeze window" in near and "still provisional" in near

    assert provisional_note(None, datetime(2026, 8, 30, tzinfo=UTC), 8).startswith("provisional")


def test_provisional_note_flags_a_league_still_forming(tmp_path):
    (tmp_path / "league.yml").write_text(
        "auction: {date: {value: 2026-09-05, source: admin, verified_on: 2026-08-22}}\n"
        "team_count: {value: 10, source: admin, verified_on: 2026-08-22}\n")
    entries = load_league_yml(tmp_path / "league.yml")
    forming = provisional_note(entries, datetime(2026, 8, 20, tzinfo=UTC), 8)
    assert "8 of 10 expected teams" in forming
    full = provisional_note(entries, datetime(2026, 8, 20, tzinfo=UTC), 10)
    assert "8 of 10" not in full and "10 teams (of 10 expected)" in full


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
