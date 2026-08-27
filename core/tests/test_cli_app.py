import json

from typer.testing import CliRunner

from fantaclaude import __version__
from fantaclaude.cli.app import ExitCode, app, emit

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
