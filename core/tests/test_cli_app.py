import json

import pytest
import typer
from fantaclaude import __version__
from fantaclaude.cli.app import ExitCode, app, emit
from typer.testing import CliRunner

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == ExitCode.OK
    assert __version__ in result.stdout


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert "Usage" in result.stdout


def test_exit_codes_are_the_documented_contract():
    assert [c.value for c in ExitCode] == [0, 1, 2, 3, 4]
    assert ExitCode.NOT_READY == 3 and ExitCode.CONFLICT == 4


def test_emit_prints_json_or_rendered_text(capsys):
    emit({"a": 1}, json_=True, render=lambda p: "never")
    assert json.loads(capsys.readouterr().out) == {"a": 1}
    emit({"a": 1}, json_=False, render=lambda p: f"a is {p['a']}")
    assert capsys.readouterr().out.strip() == "a is 1"


@pytest.mark.parametrize("args", [
    ["ingest", "all"],
    ["ingest", "advanced"],
    ["ingest", "calendar"],
    ["ingest", "stats-web"],
], ids=["all", "advanced", "calendar", "stats-web"])
def test_ensure_schema_precedes_the_seasons_pre_read(monkeypatch, tmp_path, args):
    """Finding F6: `ensure_schema()` must run before `_seasons_or_exit`'s
    pre-read (`current_season_id`, a plain read-only query against whatever
    schema version happens to be on disk) at every one of the four call
    sites -- exactly what `ensure_schema`'s own docstring promises ("before
    any pre-read") and what the comment on that very line already claimed.
    The old code ran the two in the opposite order at all four sites,
    harmless today only because `current_season_id` happens to read
    `v_league_settings_current`, a schema-1 view -- the docstring says
    Phase 1 will add reads of `player_match`/`advanced_stats`/`fixtures`,
    which a schema-1 database does not have, and would crash again exactly
    the way Ruling R7 fixed."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.setenv("FANTACALCIO_WEB_COOKIE", "session=synthetic-value-for-tests")
    order: list[str] = []

    def fake_ensure_schema(*a, **k):
        order.append("ensure_schema")

    def fake_seasons_or_exit(season):
        order.append("seasons_or_exit")
        raise typer.Exit(code=ExitCode.NOT_READY)

    monkeypatch.setattr("fantaclaude.commands.ingest.ensure_schema", fake_ensure_schema)
    monkeypatch.setattr("fantaclaude.cli.app._seasons_or_exit", fake_seasons_or_exit)

    result = runner.invoke(app, args)
    assert result.exit_code == ExitCode.NOT_READY, result.output
    assert order == ["ensure_schema", "seasons_or_exit"]
