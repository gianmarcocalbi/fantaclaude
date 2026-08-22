import pytest
from fantacalcio_mcp.config import (
    Credentials,
    ConfigurationError,
    load_dotenv,
    resolve_credentials,
    workspace_root,
)


def test_workspace_root_honours_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    assert workspace_root() == tmp_path.resolve()


def test_workspace_root_defaults_to_repo_root(monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    root = workspace_root()
    assert (root / "mcp" / "fantacalcio").is_dir()


def test_load_dotenv_parses_pairs_and_ignores_noise(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "\n"
        "FANTACALCIO_APP_KEY=abc123\n"
        "export FANTACALCIO_USERNAME=someone\n"
        "FANTACALCIO_PASSWORD='quoted secret'\n"
    )
    env = load_dotenv(env_file)
    assert env["FANTACALCIO_APP_KEY"] == "abc123"
    assert env["FANTACALCIO_USERNAME"] == "someone"
    assert env["FANTACALCIO_PASSWORD"] == "quoted secret"


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_resolve_credentials_prefers_username_password():
    creds = resolve_credentials(
        {"FANTACALCIO_USERNAME": "u", "FANTACALCIO_PASSWORD": "p",
         "FANTACALCIO_LEAGUE_TOKEN": "tok"}
    )
    assert creds == Credentials(username="u", password="p", token="tok")
    assert creds.can_login is True


def test_resolve_credentials_token_only_mode():
    creds = resolve_credentials({"FANTACALCIO_LEAGUE_TOKEN": "tok"})
    assert creds.can_login is False
    assert creds.token == "tok"


def test_resolve_credentials_without_anything_raises():
    with pytest.raises(ConfigurationError) as excinfo:
        resolve_credentials({})
    message = str(excinfo.value)
    assert "FANTACALCIO_USERNAME" in message
    assert "FANTACALCIO_LEAGUE_TOKEN" in message


def test_credentials_repr_never_leaks_password_or_token():
    """Password/token must not appear in the dataclass repr: a traceback
    rendered with frame locals (pytest --showlocals, rich tracebacks) would
    otherwise print the real secret. Username stays visible; it isn't one.
    """
    creds = Credentials(username="grimid3v", password="hunter2", token="secret-jwt")
    text = repr(creds)
    assert "grimid3v" in text
    assert "hunter2" not in text
    assert "secret-jwt" not in text
