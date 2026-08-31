import json
from pathlib import Path

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.db.connection import connect
from test_rank_cli import _workspace
from typer.testing import CliRunner

runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "asta_session_sample.jsonl"

DOSSIER = """---
updated: 2026-08-30
ttl: 90d
confidence: medium
source: interview
nick: Marco
budget_style: early
favourite_clubs: [Inter]
overpays: [Pc]
avoids: []
---

# Marco
"""


def _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """The rank CLI test's workspace with one run recorded and one dossier; returns the run id."""
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["rank", "--offline", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    (tmp_path / "kb" / "league" / "participants").mkdir(parents=True)
    (tmp_path / "kb" / "league" / "participants" / "marco.md").write_text(DOSSIER, encoding="utf-8")
    return json.loads(result.stdout)["run_id"]


def test_board_prices_the_run_against_an_empty_auction(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    run_id = _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "board", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == run_id and payload["scenario"] == "balanced" and payload["source"].startswith("an empty auction")
    assert payload["settings"]["source"] == "league" and payload["me"]["credits"] == 500 and len(payload["teams"]) == 8
    assert payload["market_credits"] == 4000 and payload["problems"] == [] and payload["lot"] is None
    # the tier board is the class's own priced players, in price order -- not a slice of some other one
    pc = {r["player_id"]: r["band"]["p50"] for r in payload["prices"].values() if r["role_class"] == "Pc"}
    tier = [r["player_id"] for r in payload["tiers"]["Pc"]]
    assert len(pc) == 3 and set(tier) == set(pc)                          # --top 5 fits the whole class
    assert [pc[pid] for pid in tier] == sorted(pc.values(), reverse=True)
    # --top bounds every class, and 1 < the 3 the default shows for Pc, so it has to bite
    one = json.loads(runner.invoke(app, ["asta", "board", "--top", "1", "--json"]).stdout)
    assert set(one["tiers"]) == set(payload["tiers"]) and all(len(rows) == 1 for rows in one["tiers"].values())
    # the same bands the run committed: one pricing function, read back
    sql = f"SELECT player_id, max_p50 FROM valuation_prices WHERE run_id = '{run_id}' AND scenario = 'balanced'"
    query = runner.invoke(app, ["query", "--sql", sql, "--json"])
    committed = {str(pid): p50 for pid, p50 in json.loads(query.stdout)["rows"]}
    assert payload["prices"] and all(payload["prices"][pid]["band"]["p50"] == committed[pid] for pid in payload["prices"])
    plain = runner.invoke(app, ["asta", "board", "--top", "2"])
    assert plain.exit_code == ExitCode.OK, plain.output
    assert f"run {run_id}" in plain.stdout and "  Pc: " in plain.stdout and "lot: none" in plain.stdout
    assert runner.invoke(app, ["asta", "board", "--scenario", "value-hunting", "--json"]).exit_code == ExitCode.OK
    # exit 2 and exit 3 for the stated reason: a scenario the run did not price is a bad
    # argument, a run id nothing recorded is a workspace that is not ready.
    unknown = runner.invoke(app, ["asta", "board", "--scenario", "nope"])
    assert unknown.exit_code == ExitCode.USAGE and "has no scenario 'nope'" in unknown.stderr
    no_run = runner.invoke(app, ["asta", "board", "--run", "nope"])
    assert no_run.exit_code == ExitCode.NOT_READY and "no valuation run 'nope'" in no_run.stderr


def test_board_refuses_without_a_run_or_a_database(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "board"])
    assert result.exit_code == ExitCode.NOT_READY and "no valuation run" in result.stderr
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path / "empty"))
    result = runner.invoke(app, ["asta", "board"])
    assert result.exit_code == ExitCode.NOT_READY and "no database" in result.stderr


def test_explain_reads_one_players_trace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "explain", "Martinez L.", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["player"]["player_id"] == 2764 and payload["player"]["role_class"] == "Pc" and payload["sold_to"] is None
    board = json.loads(runner.invoke(app, ["asta", "board", "--json"]).stdout)
    assert payload["trace"]["band"] == board["prices"]["2764"]["band"] and payload["trace"]["inflation"] == board["inflation"]
    assert len(payload["pressure"]["bidders"]) == 7 and payload["pressure"]["estimate"] >= payload["pressure"]["expected"]
    assert json.loads(runner.invoke(app, ["asta", "explain", "2764", "--json"]).stdout)["player"]["name"] == "Martinez L."
    plain = runner.invoke(app, ["asta", "explain", "Martinez L."])
    assert plain.exit_code == ExitCode.OK and "band " in plain.stdout and "pressure: est." in plain.stdout
    missing = runner.invoke(app, ["asta", "explain", "Nobody"])
    assert missing.exit_code == ExitCode.USAGE and "Nobody" in missing.stderr


def test_replay_runs_the_captured_session_and_writes_the_state_file(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--map", "host=Marco", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["mapping"] == {"mine": 1, "nicks": {"0": "Marco"}} and len(payload["steps"]) == 8
    assert payload["steps"][1]["events"] == ["+ Martinez L. (Pc) -> host for 120"]
    assert payload["steps"][4]["events"] == ["- Bastoni (Dc) <- Claude (45, undone)"]
    assert payload["steps"][5]["lot"]["name"] == "Svilar" and payload["steps"][6]["events"] == []
    assert payload["steps"][7]["events"][0] == "+ player 999999 (not in the run) -> @bomber for 3"
    assert payload["me"]["credits"] == 500 and payload["teams"][0]["spent"] == 165 and payload["written"] is None
    assert any("999999" in p for p in payload["problems"])
    assert payload["league_conflicts"] == ["teams: 3 in the session, 8 in the league"]
    assert payload["prices"]["5841"]["pressure"]["bidders"][0]["nick"] == "Marco"

    written = runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "1", "--write-state", "--json"])
    assert written.exit_code == ExitCode.OK, written.output
    state_file = tmp_path / "data" / "asta-state.json"
    assert json.loads(written.stdout)["written"] == str(state_file) and state_file.is_file()
    # the board now reads the state file: the mirrored auction, the mapping remembered
    board = runner.invoke(app, ["asta", "board", "--json"])
    assert board.exit_code == ExitCode.OK, board.output
    payload = json.loads(board.stdout)
    assert payload["source"].startswith("state file") and payload["picks"] == 3 and payload["me"]["label"] == "Claude"
    assert payload["mapping"]["mine"] == 1 and payload["teams"][0]["spent"] == 165 and payload["settings"]["source"] == "session"
    fresh = json.loads(runner.invoke(app, ["asta", "board", "--fresh", "--json"]).stdout)
    assert fresh["picks"] == 0 and fresh["settings"]["source"] == "league"
    plain = runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude"])
    assert plain.exit_code == ExitCode.OK, plain.output
    assert "undone" in plain.stdout and "final " in plain.stdout
    # every refusal named: an exit 2 for the wrong reason reads the same as one for the right reason
    for args, needle in ((["--map", "host=Marco"], "which team is mine? --me one of 0 (host), 1 (Claude), 2 (@bomber)"),
                         (["--me", "nobody"], "no team 'nobody'; the session has 0 (host)"),
                         (["--me", "Claude", "--map", "host=Luca"], "no dossier for 'Luca'"),
                         (["--me", "Claude", "--map", "host"], "--map takes team=nick, got 'host'")):
        bad = runner.invoke(app, ["asta", "replay", str(FIXTURE), *args])
        assert bad.exit_code == ExitCode.USAGE and needle in bad.stderr, (args, bad.stderr)
    absent = runner.invoke(app, ["asta", "replay", str(tmp_path / "missing.jsonl"), "--me", "Claude"])
    assert absent.exit_code == ExitCode.USAGE and "missing.jsonl is not a file" in absent.stderr


def test_adjust_appends_and_shows_what_moved(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "adjust", "--type", "exclude", "--player", "Martinez L.", "--reason", "not buying him",
                                 "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["player_id"] == 2764 and payload["count"] == 1
    assert payload["before"]["band"] is not None and payload["after"]["band"] is None
    path = tmp_path / "data" / "adjustments.yml"
    assert "- player: Martinez L.\n  type: exclude\n  reason: not buying him\n" in path.read_text(encoding="utf-8")
    board = json.loads(runner.invoke(app, ["asta", "board", "--json"]).stdout)
    assert "2764" not in board["prices"] and board["adjustments"]["applied"] == 1
    value = runner.invoke(app, ["asta", "adjust", "--type", "value", "--player-id", "6052", "--factor", "0.5", "--reason", "knee",
                                "--json"])
    assert value.exit_code == ExitCode.OK, value.output
    v = json.loads(value.stdout)
    assert v["count"] == 2 and v["after"]["band"]["p50"] < v["before"]["band"]["p50"]
    target = runner.invoke(app, ["asta", "adjust", "--type", "target", "--class", "Por", "--count", "3", "--reason", "keepers"])
    assert target.exit_code == ExitCode.OK and "appended to" in target.stdout
    # a player the run cannot resolve, or a malformed entry, is a bad argument: refused and never written
    for args, needle in ((["--type", "exclude", "--player", "Nobody", "--reason", "r"], "is not in the pinned run"),
                         (["--type", "nope", "--player", "Martinez L.", "--reason", "r"], "type must be one of"),
                         (["--type", "value", "--player", "Bastoni", "--reason", "r"], "factor must be a number"),
                         (["--type", "exclude", "--player", "Bastoni"], "Missing option '--reason'")):
        bad = runner.invoke(app, ["asta", "adjust", *args])
        assert bad.exit_code == ExitCode.USAGE and needle in bad.stderr, (args, bad.output)
    assert path.read_text(encoding="utf-8").count("type:") == 3


def test_close_copies_the_state_file_to_records_and_doctor_sees_it_all(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    nothing = runner.invoke(app, ["asta", "close"])
    assert nothing.exit_code == ExitCode.NOT_READY and "no state file" in nothing.stderr
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--write-state"]).exit_code == ExitCode.OK
    result = runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    copy = Path(json.loads(result.stdout)["records"])
    assert copy.parent == tmp_path / "records" / "asta" and copy.name.startswith("FA-nri-okm-") and copy.is_file()
    assert copy.read_bytes() == (tmp_path / "data" / "asta-state.json").read_bytes()
    doctor = json.loads(runner.invoke(app, ["doctor", "--json"]).stdout)
    by = {c["name"]: c for c in doctor["checks"]}
    assert by["pinned_run"]["ok"] and by["adjustments"]["ok"] and by["asta_state"]["ok"]
    assert "3 picks" in by["asta_state"]["detail"] and "none yet" in by["adjustments"]["detail"]


def test_the_mapping_flags_take_team_numbers_when_there_is_no_session(monkeypatch, tmp_path, fixture_json,
                                                                      mcp_fixture_json):
    """With no state file there is no session, so the league's teams are only
    numbered: --me and --map's key are team numbers, and a label names nothing."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    mapped = runner.invoke(app, ["asta", "board", "--me", "3", "--map", "0=Marco", "--json"])
    assert mapped.exit_code == ExitCode.OK, mapped.output
    payload = json.loads(mapped.stdout)
    assert payload["mapping"] == {"mine": 3, "nicks": {"0": "Marco"}} and payload["me"]["team_id"] == 3
    assert payload["teams"][0]["nick"] == "Marco" and payload["prices"]["2764"]["pressure"]["bidders"][0]["nick"] == "Marco"
    for args, needle in ((["--me", "Claude"], "--me must be a team number when there is no session, got 'Claude'"),
                         (["--map", "host=Marco"], "--map takes team=nick, with a team number when there is no session"),
                         (["--map", "0=Luca"], "no dossier for 'Luca'")):
        bad = runner.invoke(app, ["asta", "board", *args])
        assert bad.exit_code == ExitCode.USAGE and needle in bad.stderr, (args, bad.stderr)


def test_a_flag_adds_to_the_mapping_the_state_file_remembers(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """--me or --map used to rebuild the mapping from the flags alone, so naming
    my team on a mirrored auction silently unbound every rival's dossier and the
    pressure went neutral for all of them with no message at all."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    (tmp_path / "kb" / "league" / "participants" / "luca.md").write_text(DOSSIER.replace("Marco", "Luca"),
                                                                        encoding="utf-8")
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--map", "host=Marco",
                               "--write-state"]).exit_code == ExitCode.OK
    remembered = json.loads(runner.invoke(app, ["asta", "board", "--json"]).stdout)
    assert remembered["mapping"] == {"mine": 1, "nicks": {"0": "Marco"}} and remembered["teams"][0]["nick"] == "Marco"

    moved = json.loads(runner.invoke(app, ["asta", "board", "--me", "2", "--json"]).stdout)
    assert moved["mapping"] == {"mine": 2, "nicks": {"0": "Marco"}}          # --me moves me; it unbinds nobody
    assert moved["teams"][0]["nick"] == "Marco"
    added = json.loads(runner.invoke(app, ["asta", "board", "--map", "@bomber=Luca", "--json"]).stdout)
    assert added["mapping"] == {"mine": 1, "nicks": {"0": "Marco", "2": "Luca"}}      # one more binding, not one instead
    overridden = json.loads(runner.invoke(app, ["asta", "board", "--map", "host=Luca", "--json"]).stdout)
    assert overridden["mapping"] == {"mine": 1, "nicks": {"0": "Luca"}}               # naming a bound team replaces it


def test_a_map_that_names_no_team_is_refused(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """With no session a --map key is only a number, so team 9 of an eight-team
    league used to bind a nick nothing reads: no dossier applied, no problem
    line, exit 0. The exit-code contract calls that a usage error."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    bad = runner.invoke(app, ["asta", "board", "--map", "9=Marco"])
    assert bad.exit_code == ExitCode.USAGE and "--map names team(s) [9]" in bad.stderr and "0 (team 0)" in bad.stderr
    assert runner.invoke(app, ["asta", "board", "--map", "7=Marco", "--json"]).exit_code == ExitCode.OK   # the last real team
    # and nothing was written on the way out
    assert not (tmp_path / "data" / "asta-state.json").exists()


def test_a_malformed_adjustments_file_or_state_file_is_not_ready(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """Both are named in the exit-code contract as 3: a file this code cannot
    read is not a bad argument, and the fix is to fix the file."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    (tmp_path / "data" / "adjustments.yml").write_text("- player: [unbalanced\n", encoding="utf-8")
    broken = runner.invoke(app, ["asta", "board"])
    assert broken.exit_code == ExitCode.NOT_READY and "adjustments.yml" in broken.stderr
    assert runner.invoke(app, ["asta", "explain", "Martinez L."]).exit_code == ExitCode.NOT_READY
    (tmp_path / "data" / "adjustments.yml").write_text("- {player: Nobody, type: exclude, reason: r}\n", encoding="utf-8")
    inert = runner.invoke(app, ["asta", "board", "--json"])          # an entry that resolves to nobody is a problem, not a refusal
    assert inert.exit_code == ExitCode.OK and any("Nobody" in p for p in json.loads(inert.stdout)["problems"])
    (tmp_path / "data" / "adjustments.yml").unlink()

    (tmp_path / "data" / "asta-state.json").write_text("{not json", encoding="utf-8")
    torn = runner.invoke(app, ["asta", "board"])
    assert torn.exit_code == ExitCode.NOT_READY and "asta-state.json" in torn.stderr
    closing = runner.invoke(app, ["asta", "close"])
    assert closing.exit_code == ExitCode.NOT_READY and "asta-state.json" in closing.stderr
    fresh = runner.invoke(app, ["asta", "board", "--fresh", "--json"])       # --fresh never opens it
    assert fresh.exit_code == ExitCode.OK and json.loads(fresh.stdout)["picks"] == 0


def test_a_database_that_cannot_answer_is_not_ready_not_a_crash(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """A duckdb.Error raised *after* connect used to escape every asta command as
    a traceback and exit 1: _open_read_only answers for a failure at connect, and
    open_run only for PinnedRunError, so a workspace at an older schema -- no
    v_valuation_runs -- crashed instead of reporting itself. The contract calls a
    stale or foreign database "not ready" (3); exit 1 tells a caller to retry a bug."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    con.execute("DROP VIEW v_valuation_runs CASCADE")
    con.close()
    for args in (["asta", "board"], ["asta", "explain", "Martinez L."],
                 ["asta", "adjust", "--type", "exclude", "--player", "Martinez L.", "--reason", "r"],
                 ["asta", "replay", str(FIXTURE), "--me", "Claude"]):
        broken = runner.invoke(app, args)
        assert broken.exit_code == ExitCode.NOT_READY, (args, broken.exit_code, broken.output, broken.exception)
        # the code alone is not enough: an exit 3 for a missing run reads the same
        assert "v_valuation_runs" in broken.stderr and "fantaclaude doctor" in broken.stderr, (args, broken.stderr)
    assert not (tmp_path / "data" / "adjustments.yml").exists()      # and the refused adjust wrote nothing


def test_the_board_says_so_when_it_prices_a_scenario_the_state_file_was_not_written_under(
        monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """The state file has always recorded its scenario and nothing read it back,
    so a rehearsal mirrored under value-hunting read back as the run's first
    scenario with no message at all -- a model swap mid-auction, when it is least
    likely to be noticed. Noted, not adopted: the operator picks the model."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    written = runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--scenario", "value-hunting",
                                  "--write-state", "--json"])
    assert written.exit_code == ExitCode.OK, written.output
    state = json.loads((tmp_path / "data" / "asta-state.json").read_text(encoding="utf-8"))
    assert state["scenario"] == "value-hunting"

    default = runner.invoke(app, ["asta", "board", "--json"])
    assert default.exit_code == ExitCode.OK, default.output
    payload = json.loads(default.stdout)
    assert payload["scenario"] == "balanced"
    note = [n for n in payload["notes"] if "scenario" in n]
    assert len(note) == 1 and "value-hunting" in note[0] and "balanced" in note[0], payload["notes"]
    plain = runner.invoke(app, ["asta", "board"])                    # and it reaches the human-readable board too
    assert plain.exit_code == ExitCode.OK and f"note: {note[0]}" in plain.stdout

    matched = json.loads(runner.invoke(app, ["asta", "board", "--scenario", "value-hunting", "--json"]).stdout)
    assert matched["scenario"] == "value-hunting"
    assert not [n for n in matched["notes"] if "scenario" in n]      # agreeing is silent; only the swap is noted


def test_a_state_file_that_does_not_exist_is_a_bad_argument_not_an_empty_board(monkeypatch, tmp_path, fixture_json,
                                                                               mcp_fixture_json):
    """An explicit --state naming nothing used to read exactly like "no state
    file yet": 500 credits, no picks, exit 0 -- mid-auction, with nothing
    saying the file named was never opened. The exit-code contract calls a
    flag naming something that does not exist a usage error, and `replay`
    already refuses a missing session file that way."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--write-state"]).exit_code == ExitCode.OK
    typo = tmp_path / "rehearsal.jsno"
    for args in (["asta", "board", "--state", str(typo)],
                 ["asta", "explain", "Martinez L.", "--state", str(typo)],
                 ["asta", "adjust", "--type", "exclude", "--player", "Martinez L.", "--reason", "r", "--state", str(typo)]):
        bad = runner.invoke(app, args)
        # the message too, not only the code: an exit 2 for an unrelated cause reads the same
        assert bad.exit_code == ExitCode.USAGE, (args, bad.exit_code, bad.output)
        assert f"--state names {typo}, which is not a file" in bad.stderr, (args, bad.stderr)
    assert not (tmp_path / "data" / "adjustments.yml").exists()       # and the refused adjust wrote nothing

    state_file = tmp_path / "data" / "asta-state.json"
    named = runner.invoke(app, ["asta", "board", "--state", str(state_file), "--json"])
    assert named.exit_code == ExitCode.OK and json.loads(named.stdout)["picks"] == 3
    # --fresh asks for an empty board outright and opens no state file at all, so it stands
    with_fresh = runner.invoke(app, ["asta", "board", "--fresh", "--state", str(typo), "--json"])
    assert with_fresh.exit_code == ExitCode.OK and json.loads(with_fresh.stdout)["picks"] == 0
    # the implicit default is the one that may be absent: before the first mirror it always is
    state_file.unlink()
    default = runner.invoke(app, ["asta", "board", "--json"])
    assert default.exit_code == ExitCode.OK and json.loads(default.stdout)["source"].startswith("an empty auction")


def _rewrite_state(path, **fields):
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(fields)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def test_the_records_copy_is_named_by_the_state_file_not_by_the_clock_at_close(monkeypatch, tmp_path, fixture_json,
                                                                               mcp_fixture_json):
    """The copy used to be stamped with the instant of the close, so two
    `asta close` runs more than a second apart wrote two files with different
    names and identical bytes -- and the same-bytes/different-bytes guard
    copy_to_records documents could never fire. records/ is committed and
    never rewritten, so it silently accumulated copies of one auction."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--write-state"]).exit_code == ExitCode.OK
    state_file = tmp_path / "data" / "asta-state.json"
    _rewrite_state(state_file, written_at="2026-09-05T22:30:00+00:00")
    asta = tmp_path / "records" / "asta"

    first = runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm", "--json"])
    assert first.exit_code == ExitCode.OK, first.output
    copy = Path(json.loads(first.stdout)["records"])
    assert copy.name == "FA-nri-okm-20260905T223000Z.json"          # the file's own written_at, not today
    second = runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm", "--json"])
    assert second.exit_code == ExitCode.OK and Path(json.loads(second.stdout)["records"]) == copy
    assert [p.name for p in asta.iterdir()] == [copy.name]          # one record, not two identical ones

    # a state file that genuinely moved on is a different record, which is correct
    _rewrite_state(state_file, written_at="2026-09-05T23:05:00+00:00")
    third = runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm", "--json"])
    assert third.exit_code == ExitCode.OK, third.output
    assert Path(json.loads(third.stdout)["records"]).name == "FA-nri-okm-20260905T230500Z.json"
    assert len(list(asta.iterdir())) == 2

    # and the guard the stable name makes reachable at last: same name, different bytes, refused
    _rewrite_state(state_file, me=2)
    conflict = runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm"])
    assert conflict.exit_code == ExitCode.NOT_READY and "never rewritten" in conflict.stderr
    assert len(list(asta.iterdir())) == 2


def test_a_session_code_with_a_path_separator_is_refused(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """--session goes straight into one path component under records/asta/, so
    a value carrying a separator would write outside records/ altogether. A
    typo guard: the code the league shows is FA-xxx-xxx."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--write-state"]).exit_code == ExitCode.OK
    for code in ("../FA-nri-okm", "nested/FA-nri-okm", "..", r"back\slash"):
        bad = runner.invoke(app, ["asta", "close", "--session", code])
        assert bad.exit_code == ExitCode.USAGE, (code, bad.exit_code, bad.output)
        assert "is a path, not a session code" in bad.stderr, (code, bad.stderr)
    assert not (tmp_path / "records" / "asta").exists()             # and nothing was written on the way out
    assert runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm"]).exit_code == ExitCode.OK


def test_a_session_code_out_of_the_state_file_is_refused_too(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """The guard used to sit on the flag alone, but `close` falls back to the
    state file's own `session.code` when no --session is given, and that
    value reaches the same path component under records/asta/ unvalidated.
    Unreachable while render_state writes None there, and exactly the route
    2b's live mirror will use once the feed supplies the code.

    The two routes are two verdicts: a typed --session is a usage error
    (exit 2), a session code read out of the state file says the file is not
    one this code wrote (exit 3, the way every other torn-file condition
    reports here). The message matters as much as the code -- an exit 2 or 3
    for an unrelated cause looks identical from outside."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--write-state"]).exit_code == ExitCode.OK
    state_file = tmp_path / "data" / "asta-state.json"

    # route 1: the flag, unchanged -- a usage error, with the message it has always had
    flag = runner.invoke(app, ["asta", "close", "--session", "../FA-nri-okm"])
    assert flag.exit_code == ExitCode.USAGE, flag.output
    assert "--session '../FA-nri-okm' is a path, not a session code" in flag.stderr

    # route 2: the state file's own session.code, with no flag at all
    for code in ("../FA-nri-okm", "nested/FA-nri-okm", "..", r"back\slash"):
        _rewrite_state(state_file, session={"code": code})
        stored = runner.invoke(app, ["asta", "close"])
        assert stored.exit_code == ExitCode.NOT_READY, (code, stored.exit_code, stored.output)
        assert f"session code {code!r} is a path, not a session code" in stored.stderr, (code, stored.stderr)
    assert not (tmp_path / "records" / "asta").exists()          # and nothing was written on the way out

    # a sound code in the state file closes, and the flag naming the same one closes to the same record
    _rewrite_state(state_file, session={"code": "FA-nri-okm"})
    stored = runner.invoke(app, ["asta", "close", "--json"])
    assert stored.exit_code == ExitCode.OK, stored.output
    assert Path(json.loads(stored.stdout)["records"]).name.startswith("FA-nri-okm-")
    assert runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm"]).exit_code == ExitCode.OK
