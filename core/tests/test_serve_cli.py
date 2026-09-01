import asyncio
import json
from pathlib import Path

import duckdb
import pytest
from fantaclaude.cli.app import ExitCode, app
from test_asta_cli import _ranked
from typer.testing import CliRunner

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def _con(tmp_path):
    return duckdb.connect(str(tmp_path / "data" / "fanta.duckdb"), read_only=True)


def _paths(tmp_path):
    from fantaclaude.commands.asta import AstaPaths
    return AstaPaths(db=tmp_path / "data" / "fanta.duckdb", adjustments=tmp_path / "data" / "adjustments.yml",
                     state=tmp_path / "data" / "asta-state.json", records=tmp_path / "records",
                     kb=tmp_path / "kb")


def test_prepare_refuses_zero_or_two_sources_and_bad_flags(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.commands.asta import UsageError
    from fantaclaude.commands.serve import ServeOptions, prepare
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = _con(tmp_path)
    try:
        for opts in (ServeOptions(),                                                   # no source
                     ServeOptions(session="FA-a-b", replay=FIXTURES / "asta_session_sample.jsonl"),
                     ServeOptions(session="FA/evil"),                                  # a path, not a code
                     ServeOptions(replay=tmp_path / "missing.jsonl"),
                     ServeOptions(replay=FIXTURES / "asta_session_sample.jsonl", speed=0),
                     ServeOptions(session="FA-a-b", scenario="no-such-scenario")):
            with pytest.raises(UsageError):
                prepare(con, _paths(tmp_path), opts)
    finally:
        con.close()


def test_prepare_replay_with_me_goes_live_without_the_screen(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.commands.serve import ServeOptions, prepare
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = _con(tmp_path)
    try:
        plan = prepare(con, _paths(tmp_path), ServeOptions(replay=FIXTURES / "asta_session_sample.jsonl", me="0"))
        assert plan.mode == "replay" and len(plan.snapshots) >= 2
        assert plan.server.auction is not None and plan.server.hello()["phase"] == "live"
        pending = prepare(con, _paths(tmp_path), ServeOptions(replay=FIXTURES / "asta_session_sample.jsonl"))
        assert pending.server.auction is None                     # the screen will answer it
    finally:
        con.close()


def test_prepare_feed_mode_is_pending_with_a_capture_path(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.commands.serve import ServeOptions, prepare
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = _con(tmp_path)
    try:
        plan = prepare(con, _paths(tmp_path), ServeOptions(session=" FA-nri-okm "))
        assert plan.mode == "feed" and plan.session_code == "FA-nri-okm"
        assert plan.capture_path is not None and plan.capture_path.name.startswith("FA-nri-okm-")
        assert plan.capture_path.parent == tmp_path / "data" / "raw" / "asta_live"
        off = prepare(con, _paths(tmp_path), ServeOptions(session="FA-nri-okm", capture=False))
        assert off.capture_path is None
    finally:
        con.close()


def test_prepare_state_mode_reloads_the_file(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.commands.serve import ServeOptions, prepare
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    r = runner.invoke(app, ["asta", "replay", str(FIXTURES / "asta_session_sample.jsonl"),
                            "--me", "0", "--write-state"])
    assert r.exit_code == ExitCode.OK, r.output
    con = _con(tmp_path)
    try:
        plan = prepare(con, _paths(tmp_path), ServeOptions(state=tmp_path / "data" / "asta-state.json"))
        assert plan.mode == "state" and plan.server.hello()["phase"] == "live"
        assert plan.stored_snapshot is not None
        assert plan.notes == ()                    # the state file's run agrees with the pinned run: nothing to note
    finally:
        con.close()


def test_prepare_state_mode_notes_a_run_id_mismatch(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """A state file written under a different run than the one now pinned must
    surface a note naming both run ids -- never be absorbed silently, which is
    what would tell an operator mid-auction that the board on screen was
    priced under a run other than the one they think is pinned."""
    from fantaclaude.commands.serve import ServeOptions, prepare
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    r = runner.invoke(app, ["asta", "replay", str(FIXTURES / "asta_session_sample.jsonl"),
                            "--me", "0", "--write-state"])
    assert r.exit_code == ExitCode.OK, r.output
    state_path = tmp_path / "data" / "asta-state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    pinned_run_id = payload["run_id"]                 # the state file agrees with the pinned run, before doctoring
    payload["run_id"] = "not-the-pinned-run"
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    con = _con(tmp_path)
    try:
        plan = prepare(con, _paths(tmp_path), ServeOptions(state=state_path))
        assert plan.mode == "state" and plan.server.hello()["phase"] == "live"
        assert plan.stored_snapshot is not None
        assert len(plan.notes) == 1
        assert "not-the-pinned-run" in plan.notes[0] and pinned_run_id in plan.notes[0]
    finally:
        con.close()


def test_serve_cli_validates_flags_then_hands_off_to_run_serve(monkeypatch, tmp_path, fixture_json,
                                                               mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    called = {}

    async def fake_run_serve(plan, opts, paths):
        called["mode"] = plan.mode
        called["port"] = opts.port

    monkeypatch.setattr("fantaclaude.commands.serve.run_serve", fake_run_serve)
    r = runner.invoke(app, ["asta", "serve", "--replay", str(FIXTURES / "asta_session_sample.jsonl"),
                            "--me", "0", "--port", "9000"])
    assert r.exit_code == ExitCode.OK, r.output
    assert called == {"mode": "replay", "port": 9000}
    assert "run " in r.output and "http://127.0.0.1:9000" in r.output
    bad = runner.invoke(app, ["asta", "serve", "--replay", str(tmp_path / "nope.jsonl")])
    assert bad.exit_code == ExitCode.USAGE


class _Recorder:
    """Just enough AstaServer for the source tasks: the two calls they make."""

    def __init__(self, boom):
        self.boom = boom
        self.statuses: list[str] = []

    async def on_snapshot(self, snap):
        raise self.boom

    async def set_feed_status(self, status):
        self.statuses.append(status)


async def test_a_domain_error_out_of_a_snapshot_stops_the_feed_loudly_and_turns_the_dot_red(capsys):
    # The failure this guards: SessionError (an admin changing a league
    # setting mid-auction) is not a FeedError, so catching FeedError alone let
    # it escape _feed_task and die as an unretrieved task exception -- the
    # mirror stopped forever while feed_status stayed LIVE and the dashboard
    # dot stayed green. Same hole for an OSError out of write_state.
    from types import SimpleNamespace

    from fantaclaude.asta.session import SessionError
    from fantaclaude.commands import serve as serve_mod

    for boom in (SessionError("settings.budget is not a number"), OSError("no space left on device")):
        server = _Recorder(boom)

        class _Feed:
            def __init__(self, *a, _server=server, **k):
                self.server = _server

            async def run(self):
                await self.server.on_snapshot(object())

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(serve_mod, "AstaLiveFeed", _Feed)
            await serve_mod._feed_task(server, SimpleNamespace(session_code="FA-aaa-bbb", capture_path=None))
        assert server.statuses == ["offline"]
        assert str(boom) in capsys.readouterr().err


async def test_a_replay_that_blows_up_reports_and_goes_offline_but_cancellation_does_not(capsys):
    from fantaclaude.asta.session import SessionError
    from fantaclaude.commands.serve import _replay_task

    server = _Recorder(SessionError("settings.budget is not a number"))
    await _replay_task(server, (object(),), 1.0)
    assert server.statuses == ["offline"] and "settings.budget" in capsys.readouterr().err

    quiet = _Recorder(None)

    async def on_snapshot(snap):
        raise asyncio.CancelledError

    quiet.on_snapshot = on_snapshot
    with pytest.raises(asyncio.CancelledError):
        await _replay_task(quiet, (object(),), 1.0)
    assert quiet.statuses == []                    # shutdown is not a dead feed
