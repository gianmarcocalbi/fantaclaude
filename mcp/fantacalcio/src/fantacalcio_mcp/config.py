"""Paths, .env parsing and credential resolution."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_API_BASE_URL = "https://apileague.fantacalcio.it"
KEYCHAIN_SERVICE = "fantacalcio-mcp"


class ConfigurationError(Exception):
    """Raised when the server is misconfigured. Never retried."""


def workspace_root() -> Path:
    """Repo root. Never the cwd: Claude Code spawns stdio servers anywhere."""
    override = os.environ.get("FANTACALCIO_HOME")
    if override:
        return Path(override).expanduser().resolve()
    # .../mcp/fantacalcio/src/fantacalcio_mcp/config.py -> parents[4] is the repo root
    return Path(__file__).resolve().parents[4]


def env_path() -> Path:
    return workspace_root() / ".env"


def token_cache_path() -> Path:
    return workspace_root() / ".auth" / "tokens.json"


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            env[key] = value
    return env


@dataclass(frozen=True)
class Credentials:
    username: str | None = None
    # repr=False: these must never show up in a traceback rendered with
    # frame locals (pytest --showlocals, rich tracebacks, etc).
    password: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)

    @property
    def can_login(self) -> bool:
        """True when we can call POST /login and therefore self-heal."""
        return bool(self.username and self.password)


def _keychain_password(account: str) -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_credentials(env: dict[str, str]) -> Credentials:
    """Keychain password wins over .env; token-only mode is the last resort."""
    username = env.get("FANTACALCIO_USERNAME") or None
    password = env.get("FANTACALCIO_PASSWORD") or None
    token = env.get("FANTACALCIO_LEAGUE_TOKEN") or None

    if username:
        password = _keychain_password(username) or password

    if (username and password) or token:
        return Credentials(username=username, password=password, token=token)

    raise ConfigurationError(
        "No credentials found. Set FANTACALCIO_USERNAME and FANTACALCIO_PASSWORD "
        "in .env (or store the password in the macOS keychain under service "
        f"'{KEYCHAIN_SERVICE}'), or set FANTACALCIO_LEAGUE_TOKEN for token-only mode."
    )


@dataclass(frozen=True)
class Settings:
    app_key: str
    base_url: str
    credentials: Credentials


def load_settings() -> Settings:
    env = {**load_dotenv(env_path()), **os.environ}
    app_key = (env.get("FANTACALCIO_APP_KEY") or "").strip()
    if not app_key:
        raise ConfigurationError("FANTACALCIO_APP_KEY is required; set it in .env")
    return Settings(
        app_key=app_key,
        base_url=(env.get("FANTACALCIO_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/"),
        credentials=resolve_credentials(env),
    )
