# Fantacalcio MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local MCP server that lets Claude read a Leghe Fantacalcio.it league through the site's private API, authenticating with a password and no browser.

**Architecture:** Layered — `auth.py` owns credentials and JWTs, `api.py` owns HTTP, `models.py` owns payload decoding, `server.py` exposes seven FastMCP tools and contains no HTTP logic. `api.py` never imports FastMCP, so the entire client is testable against recorded fixtures with zero network access.

**Tech Stack:** Python 3.14.7, uv, FastMCP 3.4.7, httpx 0.28.1, pydantic 2.13.4, respx 0.23.1, pytest 9.1.1, pytest-asyncio 1.4.0.

**Spec:** `docs/superpowers/specs/2026-08-22-fantacalcio-mcp-design.md`

## Global Constraints

- **Python must be 3.14.7 (final), never 3.14.0rc2.** Verified failure: pydantic 2.13.4 calls `typing._eval_type(..., prefer_fwd_module=True)`, which rc2 does not accept, so `import fastmcp` dies with `TypeError: _eval_type() got an unexpected keyword argument 'prefer_fwd_module'`. This is an interpreter problem, not a dependency-version problem — do not "fix" it by downgrading pydantic.
- **uv must be >= 0.12.5.** uv 0.8.11's Python manifest stops at 3.14.0rc2, so it physically cannot install a working interpreter.
- Project root for the MCP is `mcp/fantacalcio/`. Workspace root is `/Users/grimid3v/Workspace/fantaclaudio`.
- `api.py` must never import `fastmcp`. `server.py` must never import `httpx`.
- **No test may perform network I/O.** All HTTP is mocked with `respx` against fixtures.
- **Field naming rule:** a payload field gets a friendly model name only if its meaning is confirmed by observed data. Everything else stays in `raw`. Never invent a name for `bm`, `st`, `c`, `pl`, `cal`, `cs`, `mplys`, `hdslt`, `fsltc`, `tcap`, `cmod`, `sroles`, `minrl`, `maxrl`, `hlnp`, `rlnp`, `fbench`, `assu`, `lcap`, `lswi`, `elnp`, `brdrs`, `bseq`, `stbdf`, `smod*`, `skodm`.
- Secrets never enter fixtures, tests, or git: no JWTs, no `app_key`, no emails, no `lega.parola`.
- API base URL: `https://apileague.fantacalcio.it`. Auth headers: `app_key: <key>` and `Authorization: Bearer <jwt>`.
- Transport is `stdio` by default. Writes are out of scope for this plan (phase 3).

---

## File Structure

| file | responsibility |
| --- | --- |
| `mcp/fantacalcio/pyproject.toml` | uv project, pinned deps, `requires-python = ">=3.14"` |
| `mcp/fantacalcio/.python-version` | `3.14.7` |
| `src/fantacalcio_mcp/config.py` | path resolution, `.env` parsing, credential resolution |
| `src/fantacalcio_mcp/auth.py` | login, JWT claims, token cache, expiry, 401 recovery |
| `src/fantacalcio_mcp/api.py` | httpx transport, one method per endpoint, error mapping |
| `src/fantacalcio_mcp/models.py` | pydantic models, decoded fields + `raw` |
| `src/fantacalcio_mcp/server.py` | seven FastMCP tools |
| `src/fantacalcio_mcp/__main__.py` | entrypoint, `--transport` flag |
| `tests/fixtures/*.json` | scrubbed recorded payloads |
| `tests/test_*.py` | one test module per source module |

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `mcp/fantacalcio/pyproject.toml`, `mcp/fantacalcio/.python-version`
- Create: `mcp/fantacalcio/src/fantacalcio_mcp/__init__.py`
- Create: `mcp/fantacalcio/src/fantacalcio_mcp/config.py`
- Test: `mcp/fantacalcio/tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `workspace_root() -> Path`, `env_path() -> Path`, `token_cache_path() -> Path`, `load_dotenv(path: Path) -> dict[str, str]`, `Credentials(username: str | None, password: str | None, token: str | None)`, `resolve_credentials(env: dict[str,str]) -> Credentials`, `Settings(app_key: str, base_url: str, credentials: Credentials)`, `load_settings() -> Settings`, `ConfigurationError`.

- [ ] **Step 1: Verify and prepare the toolchain**

The installed uv cannot build this project. Upgrade it and install the interpreter:

```bash
uv self update
uv --version          # must print >= 0.12.5
uv python install 3.14.7
uv python list --all-versions | grep 'cpython-3.14.7'   # must show it installed
```

If `uv self update` reports uv was installed by a package manager, reinstall it standalone instead:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- [ ] **Step 2: Initialise the git repository (workspace root)**

The workspace is not yet a git repo, so nothing is recoverable until this runs.

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git init
git add .gitignore docs/
git commit -m "chore: init repo with design spec and plan"
```

- [ ] **Step 3: Scaffold the uv project**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
mkdir -p mcp/fantacalcio
cd mcp/fantacalcio
uv init --python 3.14.7 --lib --no-workspace .
rm -rf src/fantacalcio        # uv names the package after the directory; we want fantacalcio_mcp
mkdir -p src/fantacalcio_mcp tests/fixtures
uv add fastmcp httpx pydantic
uv add --dev pytest pytest-asyncio respx
uv run python -c "import fastmcp, sys; print(sys.version.split()[0], fastmcp.__version__)"
```

Expected output: `3.14.7 3.4.7`. If it raises `TypeError: _eval_type() ... prefer_fwd_module`, the venv is on rc2 — delete `.venv` and `.python-version`, re-run `uv python pin 3.14.7`, then `uv sync`.

- [ ] **Step 4: Configure pytest**

Append to `mcp/fantacalcio/pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.uv]
package = true
```

- [ ] **Step 5: Write the failing test**

Create `mcp/fantacalcio/tests/test_config.py`:

```python
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
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantacalcio_mcp.config'`

- [ ] **Step 7: Write the implementation**

Create `mcp/fantacalcio/src/fantacalcio_mcp/__init__.py` (empty file), then `mcp/fantacalcio/src/fantacalcio_mcp/config.py`:

```python
"""Paths, .env parsing and credential resolution."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
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
    password: str | None = None
    token: str | None = None

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
```

Note the merge order in `load_settings`: `os.environ` wins over `.env`, matching the convention already used in this workspace.

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_config.py -v`
Expected: PASS, 7 passed

- [ ] **Step 9: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio
git commit -m "feat(mcp): scaffold uv project and configuration layer"
```

---

### Task 2: Test fixtures extracted from recorded payloads

**Files:**
- Create: `mcp/fantacalcio/tests/fixtures/{profile,league_profile,league_status,competitions,my_team,teams,roster_settings,lineup_settings,calculation_settings,participants,invitees,server_time,login}.json`
- Create: `mcp/fantacalcio/tests/conftest.py`
- Test: `mcp/fantacalcio/tests/test_fixtures.py`

**Interfaces:**
- Consumes: `captured/api-dump.json` at the workspace root.
- Produces: pytest fixture `fixture_json(name: str) -> dict | list` available to every later test module.

> **This task must complete before Task 8.** `captured/` is the only recorded copy of real API responses; deleting it first destroys the ground truth these fixtures come from.

- [ ] **Step 1: Write the failing test**

Create `mcp/fantacalcio/tests/test_fixtures.py`:

```python
import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

EXPECTED = {
    "profile", "league_profile", "league_status", "competitions", "my_team",
    "teams", "roster_settings", "lineup_settings", "calculation_settings",
    "participants", "invitees", "server_time", "login",
}


def test_every_expected_fixture_exists():
    actual = {p.stem for p in FIXTURE_DIR.glob("*.json")}
    assert EXPECTED <= actual


def test_fixtures_contain_no_secrets():
    """A JWT, app_key, email or league password must never reach the repo."""
    for path in FIXTURE_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "eyJhbGci" not in text, f"{path.name} contains a JWT"
        assert "@" not in text.replace("\\u0040", ""), f"{path.name} contains an email"
        payload = json.loads(text)
        # The league join password is checked by KEY, never by value: a
        # substring match would have to hardcode the password itself, so the
        # scanner would ship the very secret it exists to keep out of the
        # repo. `keys_at_any_depth` (tests/conftest.py) asserts no key named
        # "parola" exists at ANY depth, which also catches the password
        # wherever it is nested rather than only under a top-level "lega".
        assert "parola" not in keys_at_any_depth(payload), f"{path.name} leaks parola"


def test_league_profile_shape_survived_scrubbing(fixture_json):
    lega = fixture_json("league_profile")["lega"]
    assert lega["nome"]
    assert lega["id"]
    assert "admins" in lega


def test_teams_fixture_is_paginated_envelope(fixture_json):
    teams = fixture_json("teams")
    assert set(teams) >= {"page", "pages", "data", "divisions"}
    assert isinstance(teams["data"], list) and teams["data"]


def test_login_fixture_carries_league_tokens(fixture_json):
    data = fixture_json("login")["data"]
    assert data["leghe"], "login fixture must contain at least one league"
    assert {"alias", "jwt", "id", "id_squadra"} <= set(data["leghe"][0])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_fixtures.py -v`
Expected: FAIL — `fixture 'fixture_json' not found` and missing fixture files.

- [ ] **Step 3: Write the conftest**

Create `mcp/fantacalcio/tests/conftest.py`:

```python
import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_json():
    def _load(name: str):
        return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load
```

- [ ] **Step 4: Write the extraction script and run it once**

Create `mcp/fantacalcio/tests/fixtures/_extract.py` (kept as provenance — it documents how fixtures were produced):

```python
"""One-shot extraction of test fixtures from captured/api-dump.json.

Run from the workspace root:  uv run python mcp/fantacalcio/tests/fixtures/_extract.py
Scrubs every secret: JWTs, app_key, emails, and the league join password.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DUMP = ROOT / "captured" / "api-dump.json"
OUT = Path(__file__).parent

KEY_MAP = {
    "profile": "profile",
    "leagueProfile": "league_profile",
    "leagueStatus": "league_status",
    "competitions": "competitions",
    "myTeam": "my_team",
    "teams": "teams",
    "rosterSettings": "roster_settings",
    "lineupSettings": "lineup_settings",
    "calculationSettings": "calculation_settings",
    "participants": "participants",
    "invitees": "invitees",
    "serverTime": "server_time",
}

SECRET_KEYS = {"jwt", "token", "token_auth", "utente_token", "sendbird_token",
               "email", "parola", "app_key"}
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def scrub(node, key=""):
    if isinstance(node, dict):
        return {k: ("<scrubbed>" if k in SECRET_KEYS else scrub(v, k))
                for k, v in node.items() if k != "parola"}
    if isinstance(node, list):
        return [scrub(v, key) for v in node]
    if isinstance(node, str):
        node = JWT_RE.sub("<scrubbed>", node)
        if "@" in node:
            return "<scrubbed>"
    return node


def main() -> None:
    dump = json.loads(DUMP.read_text(encoding="utf-8"))
    for src, dest in KEY_MAP.items():
        if src not in dump:
            raise SystemExit(f"missing {src} in {DUMP}")
        (OUT / f"{dest}.json").write_text(
            json.dumps(scrub(dump[src]), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("wrote", dest)

    # The login response was never dumped wholesale; synthesise it from the
    # observed shape so auth tests have a realistic envelope.
    login = {
        "state": 1787414858653,
        "success": True,
        "update": True,
        "data": {
            "state_auth": 1724789741307,
            "token_auth": "<scrubbed>",
            "utente": {"id": 10426252, "username": "grimid3v", "confermato": 1},
            "leghe": [{
                "visibile": True, "ordine": 1, "admin": -1,
                "id": 2578630, "id_squadra": 11560832,
                "tipo_lega": 0, "tipo_gioco": 2,
                "nome": "Fantabalotelli3", "alias": "fantabalotelli3",
                "link": "https://leghe.fantacalcio.it/fantabalotelli3",
                "jwt": "<scrubbed>", "token": "<scrubbed>",
            }],
            "jwt": "<scrubbed>",
        },
        "error_msgs": None,
    }
    (OUT / "login.json").write_text(
        json.dumps(login, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote login")


if __name__ == "__main__":
    main()
```

Run it:

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
uv run --project mcp/fantacalcio python mcp/fantacalcio/tests/fixtures/_extract.py
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_fixtures.py -v`
Expected: PASS, 5 passed

If `test_fixtures_contain_no_secrets` fails, fix `_extract.py` and re-run it — never hand-edit a fixture, or the next extraction silently reintroduces the secret.

- [ ] **Step 6: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio/tests
git commit -m "test(mcp): extract scrubbed fixtures from recorded payloads"
```

---

### Task 3: Payload models

**Files:**
- Create: `mcp/fantacalcio/src/fantacalcio_mcp/models.py`
- Test: `mcp/fantacalcio/tests/test_models.py`

**Interfaces:**
- Consumes: `fixture_json` from Task 2.
- Produces: `Coach`, `Admin`, `Team`, `League`, `LeagueStatus`, `LeagueSettings` (merges all three settings endpoints — there is deliberately no separate `RosterSettings`/`LineupSettings`/`CalculationSettings`), `Participant`, `ServerTime`, `AccountLeague`, `Account`. Every model exposes `.raw: dict` and a `from_api(payload) -> Self` classmethod.

- [ ] **Step 1: Write the failing test**

Create `mcp/fantacalcio/tests/test_models.py`:

```python
from fantacalcio_mcp.models import (
    Account, League, LeagueSettings, LeagueStatus, ServerTime, Team,
)


def test_team_decodes_confirmed_fields_only(fixture_json):
    team = Team.from_api(fixture_json("my_team"))
    assert team.name == "Sanzimippi FC"
    assert team.team_id == 11560832
    assert team.owner_username == "Edo"
    assert team.credits_initial == 500
    assert team.credits_spent == 0
    assert team.credits_remaining == 500
    assert team.division == "A"
    assert team.roster_counts == {"p": 0, "d": 0, "c": 0, "a": 0}
    assert [c.name for c in team.coaches] == ["Edo", "Himmy"]


def test_team_keeps_unknown_fields_in_raw(fixture_json):
    payload = fixture_json("my_team")
    team = Team.from_api(payload)
    # bm/st/pl are unconfirmed and must never be given a friendly name
    assert team.raw["bm"] == payload["bm"]
    assert team.raw["st"] == payload["st"]
    assert set(payload) <= set(team.raw), "raw must preserve every input key"


def test_league_omits_the_join_password(fixture_json):
    league = League.from_api(fixture_json("league_profile"))
    assert league.name == "Fantabalotelli3"
    assert league.league_id == 2578630
    assert league.founded == "2023"
    assert [a.name for a in league.admins] == ["KingNazzario", "Chuck"]
    assert "parola" not in league.raw
    assert not hasattr(league, "parola")


def test_league_status_decodes(fixture_json):
    status = LeagueStatus.from_api(fixture_json("league_status"))
    assert status.season_id == 21
    assert status.matchday == 1
    assert status.matchday_start == "2026-08-22T16:30:00"
    assert status.active is True


def test_league_settings_merges_three_endpoints(fixture_json):
    settings = LeagueSettings.from_api(
        rosters=fixture_json("roster_settings"),
        lineup=fixture_json("lineup_settings"),
        calculate=fixture_json("calculation_settings"),
    )
    assert settings.budget == 500
    assert settings.roster_min == 23
    assert settings.roster_max == 40
    assert settings.bench_size == 12
    assert "442" in settings.modules
    assert settings.substitutions == 5
    assert settings.bonus_malus["goal_scored"] == [3, 3]
    assert settings.bonus_malus["yellow_card"] == [-0.5, -0.5]
    assert settings.bonus_malus["own_goal"] == [-1, -1]
    # unconfirmed knobs stay raw
    assert "lswi" in settings.raw["lineup"]
    assert "smodg" in settings.raw["calculate"]


def test_server_time_decodes(fixture_json):
    assert ServerTime.from_api(fixture_json("server_time")).seconds == "20260822160844"


def test_account_lists_leagues_without_tokens(fixture_json):
    account = Account.from_api(fixture_json("profile"))
    assert account.username == "grimid3v"
    assert account.user_id == 10426252
    serialised = account.model_dump_json()
    assert "jwt" not in serialised and "eyJhbGci" not in serialised
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantacalcio_mcp.models'`

- [ ] **Step 3: Write the implementation**

Create `mcp/fantacalcio/src/fantacalcio_mcp/models.py`:

```python
"""Pydantic views over the API's abbreviated payloads.

Naming rule: a field is renamed only where observed data confirms its meaning.
Everything else survives untouched in `raw`, because a misnamed field is worse
than an absent one -- the caller cannot tell it is wrong.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field

# Confirmed bonus/malus keys from settings/calculate.
BONUS_MALUS_NAMES = {
    "bmgs": "goal_scored",
    "bmgc": "goal_conceded",
    "bmpsc": "penalty_scored",
    "bmpns": "penalty_missed",
    "bmpsa": "penalty_saved",
    "bmyc": "yellow_card",
    "bmrc": "red_card",
    "bmog": "own_goal",
    "bmasf": "assist_first",
    "bmass": "assist_second",
    "bmasg": "assist_generic",
    "motm": "man_of_the_match",
}


class Coach(BaseModel):
    coach_id: int
    name: str


class Team(BaseModel):
    team_id: int
    name: str
    owner_username: str | None = None
    owner_user_id: int | None = None
    division: str | None = None
    credits_initial: int | None = None
    credits_spent: int | None = None
    credits_remaining: int | None = None
    roster_counts: dict[str, int] = Field(default_factory=dict)
    coaches: list[Coach] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        return cls(
            team_id=payload["id"],
            name=payload.get("n", ""),
            owner_username=payload.get("nu"),
            owner_user_id=payload.get("idu"),
            division=payload.get("d"),
            credits_initial=payload.get("cri"),
            credits_spent=payload.get("crs"),
            credits_remaining=payload.get("cr"),
            roster_counts=payload.get("r") or {},
            coaches=[Coach(coach_id=c["id"], name=c.get("n", ""))
                     for c in payload.get("all") or []],
            raw=payload,
        )


class Admin(BaseModel):
    admin_id: int
    name: str


class League(BaseModel):
    league_id: int
    name: str
    alias: str | None = None
    founded: str | None = None
    president: str | None = None
    team_count: int | None = None
    admins: list[Admin] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        lega = dict(payload.get("lega") or payload)
        lega.pop("parola", None)          # never surface the join password
        lega.pop("parola_ordine", None)
        return cls(
            league_id=lega["id"],
            name=lega.get("nome", ""),
            alias=lega.get("alias"),
            founded=lega.get("anno_fondazione"),
            president=lega.get("presidente"),
            team_count=lega.get("n_s"),
            admins=[Admin(admin_id=a["id"], name=a.get("nome", ""))
                    for a in lega.get("admins") or []],
            raw=lega,
        )


class LeagueStatus(BaseModel):
    season_id: int | None = None
    matchday: int | None = None
    matchday_start: str | None = None
    active: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        return cls(
            season_id=payload.get("sId"),
            matchday=payload.get("mday"),
            matchday_start=payload.get("mstr"),
            active=payload.get("activ"),
            raw=payload,
        )


class LeagueSettings(BaseModel):
    budget: int | None = None
    roster_min: int | None = None
    roster_max: int | None = None
    bench_size: int | None = None
    modules: list[str] = Field(default_factory=list)
    substitutions: int | None = None
    bonus_malus: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, rosters: dict[str, Any], lineup: dict[str, Any],
                 calculate: dict[str, Any]) -> Self:
        bn = calculate.get("bnMls") or {}
        return cls(
            budget=rosters.get("budg"),
            roster_min=rosters.get("msltc"),
            roster_max=rosters.get("xsltc"),
            bench_size=lineup.get("tbench"),
            modules=list(lineup.get("mods") or []),
            substitutions=(calculate.get("subst") or {}).get("ssnum"),
            bonus_malus={friendly: bn[key]
                         for key, friendly in BONUS_MALUS_NAMES.items() if key in bn},
            raw={"rosters": rosters, "lineup": lineup, "calculate": calculate},
        )


class Participant(BaseModel):
    team_id: int
    team_name: str
    managers: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        scrubbed = dict(payload)
        scrubbed["coaches"] = [{k: v for k, v in c.items() if k != "email"}
                               for c in payload.get("coaches") or []]
        return cls(
            team_id=payload["teamId"],
            team_name=payload.get("teamName", ""),
            managers=[c.get("name", "") for c in payload.get("coaches") or []],
            raw=scrubbed,
        )


class ServerTime(BaseModel):
    seconds: str | None = None
    minutes: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        return cls(seconds=payload.get("secs"), minutes=payload.get("mins"), raw=payload)


class AccountLeague(BaseModel):
    league_id: int
    name: str
    alias: str
    team_id: int | None = None


class Account(BaseModel):
    user_id: int
    username: str
    leagues: list[AccountLeague] = Field(default_factory=list)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        data = payload.get("data", payload)
        utente = data.get("utente") or {}
        return cls(
            user_id=utente.get("id"),
            username=utente.get("username", ""),
            leagues=[
                AccountLeague(
                    league_id=lg["id"], name=lg.get("nome", ""),
                    alias=lg.get("alias", ""), team_id=lg.get("id_squadra"),
                )
                for lg in data.get("leghe") or []
            ],
        )
```

`Account` deliberately has no `raw`: the profile payload embeds JWTs and an
email, and the model's job is to be the one place those cannot leak.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_models.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio
git commit -m "feat(mcp): add payload models with raw passthrough"
```

---

### Task 4: Authentication and token lifecycle

**Files:**
- Create: `mcp/fantacalcio/src/fantacalcio_mcp/auth.py`
- Test: `mcp/fantacalcio/tests/test_auth.py`

**Interfaces:**
- Consumes: `Credentials`, `ConfigurationError` from `config.py`; `login.json` fixture.
- Produces: `AuthError`, `decode_claims(jwt: str) -> dict`, `is_expired(jwt: str, *, now: float | None = None, skew: int = 60) -> bool`, `LeagueToken(alias, league_id, team_id, name, jwt)`, and `Auth` with `async login() -> dict`, `async token_for(alias: str | None = None) -> str`, `async account_token() -> str`, `invalidate() -> None`, `list_leagues() -> list[LeagueToken]`.

- [ ] **Step 1: Write the failing test**

Create `mcp/fantacalcio/tests/test_auth.py`:

```python
import base64
import json
import time

import httpx
import pytest
import respx

from fantacalcio_mcp.auth import Auth, AuthError, decode_claims, is_expired
from fantacalcio_mcp.config import ConfigurationError, Credentials

BASE = "https://apileague.fantacalcio.it"


def make_jwt(**claims) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.signature"


def league_jwt(exp_offset=31_536_000):
    return make_jwt(user_id="10426252", l_id="2578630", t_id="11560832",
                    role="user_league", exp=int(time.time()) + exp_offset)


@pytest.fixture
def login_response(fixture_json):
    payload = fixture_json("login")
    payload["data"]["jwt"] = make_jwt(user_id="10426252", role="user",
                                      exp=int(time.time()) + 31_536_000)
    payload["data"]["leghe"][0]["jwt"] = league_jwt()
    return payload


def test_decode_claims_reads_league_context():
    claims = decode_claims(league_jwt())
    assert claims["l_id"] == "2578630"
    assert claims["t_id"] == "11560832"
    assert claims["role"] == "user_league"


def test_is_expired_uses_skew():
    nearly = make_jwt(exp=int(time.time()) + 30)
    assert is_expired(nearly, skew=60) is True
    assert is_expired(nearly, skew=0) is False


async def test_login_caches_league_tokens(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "APPKEY", BASE)
            token = await auth.token_for()
    assert route.called
    assert decode_claims(token)["l_id"] == "2578630"
    saved = json.loads(cache.read_text())
    assert "fantabalotelli3" in saved["leagues"]
    assert cache.stat().st_mode & 0o777 == 0o600


async def test_login_sends_app_key_and_credentials(tmp_path, login_response):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), tmp_path / "t.json",
                       http, "APPKEY", BASE).token_for()
    request = route.calls[0].request
    assert request.headers["app_key"] == "APPKEY"
    assert json.loads(request.content) == {"username": "u", "password": "p"}


async def test_cached_token_avoids_second_login(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
            await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
    assert route.call_count == 1


async def test_expired_cached_token_triggers_relogin(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    cache.write_text(json.dumps({
        "account": None,
        "leagues": {"fantabalotelli3": {
            "alias": "fantabalotelli3", "league_id": "2578630",
            "team_id": "11560832", "name": "Fantabalotelli3",
            "jwt": make_jwt(exp=int(time.time()) - 10),
        }},
    }))
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
    assert route.called


async def test_bad_credentials_raise_configuration_error(tmp_path):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(
            400, json={"code": "ATH018", "message": "Invalid username or password"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "bad"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.token_for()


async def test_token_only_mode_never_logs_in(tmp_path):
    token = league_jwt()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials(token=token), tmp_path / "t.json", http, "K", BASE)
            assert await auth.token_for() == token
    assert not route.called


async def test_token_only_mode_cannot_recover(tmp_path):
    async with httpx.AsyncClient(base_url=BASE) as http:
        auth = Auth(Credentials(token=make_jwt(exp=int(time.time()) - 1)),
                    tmp_path / "t.json", http, "K", BASE)
        with pytest.raises(AuthError, match="expired"):
            await auth.token_for()


async def test_unknown_alias_lists_available(tmp_path, login_response):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(AuthError, match="fantabalotelli3"):
                await auth.token_for("nonexistent")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantacalcio_mcp.auth'`

- [ ] **Step 3: Write the implementation**

Create `mcp/fantacalcio/src/fantacalcio_mcp/auth.py`:

```python
"""Credentials in, valid league JWT out.

League context lives inside the token (claims l_id / t_id), so switching
leagues means switching tokens. This module is the only place that knows that.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import ConfigurationError, Credentials

LOGIN_PATH = "/onboarding/v1/login"


class AuthError(Exception):
    """Authentication failed in a way retrying will not fix."""


def decode_claims(jwt: str) -> dict[str, Any]:
    try:
        payload = jwt.split(".")[1]
        padding = "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload + padding))
    except (IndexError, ValueError) as exc:
        raise AuthError("token is not a readable JWT") from exc


def is_expired(jwt: str, *, now: float | None = None, skew: int = 60) -> bool:
    exp = decode_claims(jwt).get("exp")
    if exp is None:
        return False
    return (now if now is not None else time.time()) + skew >= float(exp)


@dataclass
class LeagueToken:
    alias: str
    league_id: str
    team_id: str
    name: str
    jwt: str


class Auth:
    def __init__(self, credentials: Credentials, cache_path: Path,
                 http: httpx.AsyncClient, app_key: str, base_url: str) -> None:
        self._credentials = credentials
        self._cache_path = cache_path
        self._http = http
        self._app_key = app_key
        self._base_url = base_url.rstrip("/")
        self._account_jwt: str | None = None
        self._leagues: dict[str, LeagueToken] = {}
        self._load_cache()

    # ---- cache ---------------------------------------------------------
    def _load_cache(self) -> None:
        if not self._cache_path.is_file():
            return
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._account_jwt = data.get("account")
        self._leagues = {alias: LeagueToken(**entry)
                         for alias, entry in (data.get("leagues") or {}).items()}

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps({
            "account": self._account_jwt,
            "leagues": {alias: asdict(tok) for alias, tok in self._leagues.items()},
        }, indent=2), encoding="utf-8")
        self._cache_path.chmod(0o600)

    def invalidate(self) -> None:
        """Drop cached tokens so the next call re-logs in."""
        self._account_jwt = None
        self._leagues = {}
        self._cache_path.unlink(missing_ok=True)

    def list_leagues(self) -> list[LeagueToken]:
        return list(self._leagues.values())

    # ---- login ---------------------------------------------------------
    async def login(self) -> dict[str, Any]:
        if not self._credentials.can_login:
            raise AuthError(
                "Cached token is expired or missing and no username/password is "
                "configured. Set FANTACALCIO_USERNAME and FANTACALCIO_PASSWORD, "
                "or refresh FANTACALCIO_LEAGUE_TOKEN."
            )
        response = await self._http.post(
            f"{self._base_url}{LOGIN_PATH}",
            headers={"app_key": self._app_key, "Accept": "application/json"},
            json={"username": self._credentials.username,
                  "password": self._credentials.password},
        )
        if response.status_code >= 400:
            body = _safe_json(response)
            code = body.get("code", "")
            message = body.get("message", response.text[:200])
            if code in {"ATH006", "ATH018", "ATH000", "ATH007"}:
                raise ConfigurationError(f"{code}: {message}")
            raise AuthError(f"login failed (HTTP {response.status_code}): {message}")

        data = (response.json() or {}).get("data") or {}
        self._account_jwt = data.get("jwt")
        self._leagues = {
            lg["alias"]: LeagueToken(
                alias=lg["alias"], league_id=str(lg.get("id", "")),
                team_id=str(lg.get("id_squadra", "")), name=lg.get("nome", ""),
                jwt=lg["jwt"],
            )
            for lg in data.get("leghe") or [] if lg.get("alias") and lg.get("jwt")
        }
        self._save_cache()
        return data

    # ---- token access --------------------------------------------------
    async def account_token(self) -> str:
        if not self._account_jwt or is_expired(self._account_jwt):
            await self.login()
        if not self._account_jwt:
            raise AuthError("login did not return an account token")
        return self._account_jwt

    async def token_for(self, alias: str | None = None) -> str:
        if self._credentials.token and not self._credentials.can_login:
            if is_expired(self._credentials.token):
                raise AuthError(
                    "FANTACALCIO_LEAGUE_TOKEN is expired and token-only mode "
                    "cannot refresh it. Add FANTACALCIO_USERNAME/PASSWORD or "
                    "paste a fresh token."
                )
            return self._credentials.token

        token = self._pick(alias)
        if token is None or is_expired(token.jwt):
            await self.login()
            token = self._pick(alias)
        if token is None:
            raise AuthError(
                f"league {alias!r} not found. Available: "
                f"{', '.join(sorted(self._leagues)) or 'none'}"
            )
        return token.jwt

    def _pick(self, alias: str | None) -> LeagueToken | None:
        if alias:
            return self._leagues.get(alias)
        if len(self._leagues) == 1:
            return next(iter(self._leagues.values()))
        return None


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_auth.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio
git commit -m "feat(mcp): add auth with token cache and expiry handling"
```

---

### Task 5: API client

**Files:**
- Create: `mcp/fantacalcio/src/fantacalcio_mcp/api.py`
- Test: `mcp/fantacalcio/tests/test_api.py`

**Interfaces:**
- Consumes: `Auth` from Task 4.
- Produces: `ApiError(message, *, status: int | None, code: str | None)` and `FantacalcioAPI(http, auth, base_url, app_key)` with async methods `profile(user_id=None)` (resolves the id from the account token's `user_id` claim when omitted), `league_profile(league=None)`, `league_status(league=None)`, `competitions(league=None)`, `my_team(league=None)`, `teams(page=1, league=None)`, `roster_settings(league=None)`, `lineup_settings(league=None)`, `calculation_settings(league=None)`, `participants(page_number=1, page_size=1000, league=None)`, `invitees(page_number=1, page_size=1000, league=None)`, `server_time(league=None)`.

> `api.py` MUST NOT import `fastmcp`. Task 7's test asserts this.

- [ ] **Step 1: Write the failing test**

Create `mcp/fantacalcio/tests/test_api.py`:

```python
import base64
import json
import time

import httpx
import pytest
import respx

from fantacalcio_mcp.api import ApiError, FantacalcioAPI
from fantacalcio_mcp.auth import Auth
from fantacalcio_mcp.config import Credentials

BASE = "https://apileague.fantacalcio.it"


def make_jwt(**claims):
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.sig"


@pytest.fixture
def valid_token():
    return make_jwt(l_id="2578630", t_id="11560832", role="user_league",
                    exp=int(time.time()) + 31_536_000)


@pytest.fixture
async def api(tmp_path, valid_token):
    async with httpx.AsyncClient(base_url=BASE) as http:
        auth = Auth(Credentials(token=valid_token), tmp_path / "t.json",
                    http, "APPKEY", BASE)
        yield FantacalcioAPI(http, auth, BASE, "APPKEY")


async def test_get_sends_both_auth_headers(api, fixture_json, valid_token):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/league/profile").mock(
            return_value=httpx.Response(200, json=fixture_json("league_profile")))
        await api.league_profile()
    request = route.calls[0].request
    assert request.headers["app_key"] == "APPKEY"
    assert request.headers["Authorization"] == f"Bearer {valid_token}"


async def test_teams_passes_page_parameter(api, fixture_json):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/league/teams").mock(
            return_value=httpx.Response(200, json=fixture_json("teams")))
        await api.teams(page=3)
    assert route.calls[0].request.url.params["page"] == "3"


async def test_participants_passes_pagination(api, fixture_json):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/invitation/participants").mock(
            return_value=httpx.Response(200, json=fixture_json("participants")))
        await api.participants(page_number=2, page_size=50)
    params = route.calls[0].request.url.params
    assert params["pageNumber"] == "2" and params["pageSize"] == "50"


async def test_known_error_code_is_mapped(api):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/market/v1/time").mock(return_value=httpx.Response(
            401, json={"code": "ATH000", "message": "No Appkey authorized"}))
        with pytest.raises(ApiError) as excinfo:
            await api.server_time()
    assert excinfo.value.code == "ATH000"
    assert "app_key" in str(excinfo.value)


async def test_unknown_error_passes_through_verbatim(api):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/market/v1/time").mock(return_value=httpx.Response(
            500, json={"code": "ZZZ999", "message": "boom"}))
        with pytest.raises(ApiError, match="boom") as excinfo:
            await api.server_time()
    assert excinfo.value.status == 500


async def test_401_retries_once_after_relogin(tmp_path, fixture_json, valid_token):
    login = fixture_json("login")
    login["data"]["jwt"] = make_jwt(role="user", exp=int(time.time()) + 3600)
    login["data"]["leghe"][0]["jwt"] = valid_token

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login))
        time_route = mock.get("/market/v1/time").mock(side_effect=[
            httpx.Response(401, json={"code": "ATH001", "message": "expired"}),
            httpx.Response(200, json={"secs": "1", "mins": "1"}),
        ])
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            result = await FantacalcioAPI(http, auth, BASE, "K").server_time()

    assert result == {"secs": "1", "mins": "1"}
    assert time_route.call_count == 2
    assert login_route.call_count == 2   # initial token fetch + recovery


async def test_401_does_not_retry_twice(tmp_path, fixture_json, valid_token):
    login = fixture_json("login")
    login["data"]["leghe"][0]["jwt"] = valid_token
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login))
        time_route = mock.get("/market/v1/time").mock(
            return_value=httpx.Response(401, json={"code": "ATH001", "message": "nope"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(ApiError):
                await FantacalcioAPI(http, auth, BASE, "K").server_time()
    assert time_route.call_count == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantacalcio_mcp.api'`

- [ ] **Step 3: Write the implementation**

Create `mcp/fantacalcio/src/fantacalcio_mcp/api.py`:

```python
"""HTTP transport for the private Leghe Fantacalcio.it API.

Must never import fastmcp: keeping this module framework-free is what makes
the client testable against fixtures.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .auth import Auth, decode_claims

ERROR_HINTS = {
    "ATH000": "app_key rejected -- it may have rotated; re-capture it",
    "ATH006": "credentials missing -- set FANTACALCIO_USERNAME and FANTACALCIO_PASSWORD",
    "ATH007": "app_key missing -- set FANTACALCIO_APP_KEY",
    "ATH018": "invalid username or password",
}


class ApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None,
                 code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class FantacalcioAPI:
    def __init__(self, http: httpx.AsyncClient, auth: Auth,
                 base_url: str, app_key: str) -> None:
        self._http = http
        self._auth = auth
        self._base_url = base_url.rstrip("/")
        self._app_key = app_key

    async def _get(self, path: str, *, params: dict[str, Any] | None = None,
                   league: str | None = None, token: str | None = None) -> Any:
        bearer = token or await self._auth.token_for(league)
        response = await self._request(path, params, bearer)

        if response.status_code in (401, 403) and token is None:
            self._auth.invalidate()
            bearer = await self._auth.token_for(league)
            response = await self._request(path, params, bearer)

        if response.status_code >= 400:
            body = _safe_json(response)
            code = body.get("code")
            message = ERROR_HINTS.get(code or "", body.get("message") or response.text[:200])
            raise ApiError(f"{path} -> HTTP {response.status_code}: {message}",
                           status=response.status_code, code=code)
        return response.json()

    async def _request(self, path: str, params: dict[str, Any] | None,
                       bearer: str) -> httpx.Response:
        return await self._http.get(
            f"{self._base_url}{path}",
            params=params,
            headers={"Accept": "application/json", "app_key": self._app_key,
                     "Authorization": f"Bearer {bearer}"},
        )

    # ---- endpoints -----------------------------------------------------
    async def profile(self, user_id: str | None = None) -> Any:
        """Read the account profile.

        The endpoint was only ever observed with a numeric id, so the id is
        read from the account token's `user_id` claim rather than guessed.
        """
        token = await self._auth.account_token()
        if user_id is None:
            user_id = decode_claims(token).get("user_id")
            if not user_id:
                raise ApiError("account token carries no user_id claim", code=None)
        return await self._get(f"/onboarding/v2/profile/{quote(str(user_id))}", token=token)

    async def league_profile(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/profile", league=league)

    async def league_status(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/status", league=league)

    async def competitions(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/competitions", league=league)

    async def my_team(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/teams/my", league=league)

    async def teams(self, page: int = 1, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/teams",
                               params={"page": max(1, page)}, league=league)

    async def roster_settings(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/settings/rosters", league=league)

    async def lineup_settings(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/settings/lineup", league=league)

    async def calculation_settings(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/settings/calculate", league=league)

    async def participants(self, page_number: int = 1, page_size: int = 1000,
                           league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/invitation/participants", league=league,
                               params=_pagination(page_number, page_size))

    async def invitees(self, page_number: int = 1, page_size: int = 1000,
                       league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/invitation/invitees", league=league,
                               params=_pagination(page_number, page_size))

    async def server_time(self, league: str | None = None) -> Any:
        return await self._get("/market/v1/time", league=league)


def _pagination(page_number: int, page_size: int) -> dict[str, int]:
    return {"pageNumber": max(1, page_number), "pageSize": min(max(1, page_size), 1000)}


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_api.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio
git commit -m "feat(mcp): add API client with error mapping and 401 recovery"
```

---

### Task 6: MCP tool surface

**Files:**
- Create: `mcp/fantacalcio/src/fantacalcio_mcp/server.py`
- Create: `mcp/fantacalcio/src/fantacalcio_mcp/__main__.py`
- Test: `mcp/fantacalcio/tests/test_server.py`

**Interfaces:**
- Consumes: `FantacalcioAPI` (Task 5), every model (Task 3).
- Produces: `build_server(api: FantacalcioAPI) -> FastMCP` registering exactly seven tools: `get_account`, `get_league`, `get_league_settings`, `get_my_team`, `list_teams`, `list_competitions`, `get_server_time`.

- [ ] **Step 1: Write the failing test**

Create `mcp/fantacalcio/tests/test_server.py`:

```python
import json
from pathlib import Path

import pytest
from fastmcp import Client

from fantacalcio_mcp.server import build_server

SRC = Path(__file__).resolve().parents[1] / "src" / "fantacalcio_mcp"

EXPECTED_TOOLS = {
    "get_account", "get_league", "get_league_settings", "get_my_team",
    "list_teams", "list_competitions", "get_server_time",
}


class FakeAPI:
    """Stands in for FantacalcioAPI; returns fixtures, records calls."""

    def __init__(self, fixture_json):
        self._f = fixture_json
        self.calls: list[tuple[str, dict]] = []

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))

    async def profile(self, user_id=None):
        self._record("profile", user_id=user_id); return self._f("profile")

    async def league_profile(self, league=None):
        self._record("league_profile", league=league); return self._f("league_profile")

    async def league_status(self, league=None):
        self._record("league_status", league=league); return self._f("league_status")

    async def competitions(self, league=None):
        self._record("competitions", league=league); return self._f("competitions")

    async def my_team(self, league=None):
        self._record("my_team", league=league); return self._f("my_team")

    async def teams(self, page=1, league=None):
        self._record("teams", page=page, league=league); return self._f("teams")

    async def roster_settings(self, league=None):
        return self._f("roster_settings")

    async def lineup_settings(self, league=None):
        return self._f("lineup_settings")

    async def calculation_settings(self, league=None):
        return self._f("calculation_settings")

    async def participants(self, page_number=1, page_size=1000, league=None):
        self._record("participants", league=league); return self._f("participants")

    async def invitees(self, page_number=1, page_size=1000, league=None):
        self._record("invitees", league=league); return self._f("invitees")

    async def server_time(self, league=None):
        return self._f("server_time")


@pytest.fixture
def fake_api(fixture_json):
    return FakeAPI(fixture_json)


def test_api_module_never_imports_fastmcp():
    assert "fastmcp" not in (SRC / "api.py").read_text(encoding="utf-8")


def test_server_module_never_imports_httpx():
    assert "import httpx" not in (SRC / "server.py").read_text(encoding="utf-8")


async def test_exactly_seven_tools_are_registered(fake_api):
    async with Client(build_server(fake_api)) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_every_tool_has_a_description(fake_api):
    async with Client(build_server(fake_api)) as client:
        for tool in await client.list_tools():
            assert tool.description and len(tool.description) > 20, tool.name


async def test_get_league_merges_profile_and_status(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("get_league", {})
    payload = json.loads(result.content[0].text)
    assert payload["name"] == "Fantabalotelli3"
    assert payload["status"]["matchday"] == 1
    assert "parola" not in json.dumps(payload)


async def test_get_league_settings_merges_three_endpoints(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("get_league_settings", {})
    payload = json.loads(result.content[0].text)
    assert payload["budget"] == 500
    assert payload["substitutions"] == 5
    assert "442" in payload["modules"]


async def test_list_teams_merges_managers_into_teams(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("list_teams", {})
    payload = json.loads(result.content[0].text)
    by_name = {t["name"]: t for t in payload["teams"]}
    assert by_name["KingKlavan FC"]["managers"] == ["KingNazzario"]
    assert "@" not in json.dumps(payload), "manager emails must never be returned"


async def test_list_teams_can_include_pending_invites(fake_api):
    async with Client(build_server(fake_api)) as client:
        await client.call_tool("list_teams", {"include_pending": True})
    assert any(name == "invitees" for name, _ in fake_api.calls)


async def test_league_argument_is_forwarded(fake_api):
    async with Client(build_server(fake_api)) as client:
        await client.call_tool("get_my_team", {"league": "fantabalotelli3"})
    assert ("my_team", {"league": "fantabalotelli3"}) in fake_api.calls


async def test_get_account_never_returns_tokens(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("get_account", {})
    text = result.content[0].text
    assert "eyJhbGci" not in text and "jwt" not in text.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantacalcio_mcp.server'`

- [ ] **Step 3: Write the implementation**

Create `mcp/fantacalcio/src/fantacalcio_mcp/server.py`:

```python
"""FastMCP tool surface. No HTTP here -- only api calls and model decoding."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .models import (
    Account, League, LeagueSettings, LeagueStatus, Participant, ServerTime, Team,
)

INSTRUCTIONS = (
    "Read-only access to a Leghe Fantacalcio.it league. League context comes "
    "from the configured account; pass `league` (the alias) only when the "
    "account belongs to more than one league."
)


def build_server(api: Any) -> FastMCP:
    mcp = FastMCP(name="fantacalcio", instructions=INSTRUCTIONS)

    @mcp.tool
    async def get_account() -> dict[str, Any]:
        """Read the signed-in Fantacalcio account and every league it belongs to.

        Use this first when you need a league alias to pass to other tools.
        Never returns tokens or email addresses.
        """
        account = Account.from_api(await api.profile())
        return account.model_dump()

    @mcp.tool
    async def get_league(league: str | None = None) -> dict[str, Any]:
        """Read the league's identity and current state: name, id, founding year,
        president, admins, team count, season, matchday and kickoff time.
        """
        profile = League.from_api(await api.league_profile(league=league))
        status = LeagueStatus.from_api(await api.league_status(league=league))
        payload = profile.model_dump()
        payload["status"] = status.model_dump()
        return payload

    @mcp.tool
    async def get_league_settings(league: str | None = None) -> dict[str, Any]:
        """Read the league's rules: budget, roster size, allowed formations, bench
        size, substitutions, and the full bonus/malus table.

        Fields whose meaning is not confirmed are preserved untouched under `raw`.
        """
        settings = LeagueSettings.from_api(
            rosters=await api.roster_settings(league=league),
            lineup=await api.lineup_settings(league=league),
            calculate=await api.calculation_settings(league=league),
        )
        return settings.model_dump()

    @mcp.tool
    async def get_my_team(league: str | None = None) -> dict[str, Any]:
        """Read the signed-in user's own team: name, credits spent and remaining,
        roster composition by role, division and co-managers.
        """
        return Team.from_api(await api.my_team(league=league)).model_dump()

    @mcp.tool
    async def list_teams(include_pending: bool = False,
                         league: str | None = None) -> dict[str, Any]:
        """List every team in the league with its managers, credits and division.

        Set include_pending to also list invitations that have not been accepted.
        """
        envelope = await api.teams(page=1, league=league)
        rows = envelope.get("data") if isinstance(envelope, dict) else envelope
        teams = [Team.from_api(row) for row in rows or []]

        roster = await api.participants(league=league)
        managers = {p.team_id: p.managers
                    for p in (Participant.from_api(r) for r in roster or [])}

        payload: dict[str, Any] = {
            "teams": [{**team.model_dump(), "managers": managers.get(team.team_id, [])}
                      for team in teams],
            "divisions": envelope.get("divisions") if isinstance(envelope, dict) else None,
        }
        if include_pending:
            pending = await api.invitees(league=league)
            payload["pending_invites"] = [
                {k: v for k, v in row.items() if k != "email"} for row in pending or []
            ]
        return payload

    @mcp.tool
    async def list_competitions(league: str | None = None) -> dict[str, Any]:
        """List the competitions configured in the league (campionato, coppa, ...).

        An empty list means the league has not created any competition yet.
        """
        return {"competitions": await api.competitions(league=league) or []}

    @mcp.tool
    async def get_server_time(league: str | None = None) -> dict[str, Any]:
        """Read Fantacalcio's own server clock, for reasoning about deadlines.

        Returned as `YYYYMMDDHHMMSS` strings, which is the API's native format.
        """
        return ServerTime.from_api(await api.server_time(league=league)).model_dump()

    return mcp
```

Create `mcp/fantacalcio/src/fantacalcio_mcp/__main__.py`:

```python
"""Entrypoint. stdio by default; HTTP binds loopback unless told otherwise."""

from __future__ import annotations

import argparse
import asyncio

import httpx

from .api import FantacalcioAPI
from .auth import Auth
from .config import load_settings, token_cache_path
from .server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(prog="fantacalcio-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    settings = load_settings()
    http = httpx.AsyncClient(timeout=20.0)
    auth = Auth(settings.credentials, token_cache_path(), http,
                settings.app_key, settings.base_url)
    api = FantacalcioAPI(http, auth, settings.base_url, settings.app_key)
    server = build_server(api)

    try:
        if args.transport == "http":
            server.run(transport="http", host=args.host, port=args.port)
        else:
            server.run(transport="stdio")
    finally:
        asyncio.run(http.aclose())


if __name__ == "__main__":
    main()
```

Add the entrypoint to `mcp/fantacalcio/pyproject.toml`:

```toml
[project.scripts]
fantacalcio-mcp = "fantacalcio_mcp.__main__:main"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp/fantacalcio && uv run pytest tests/test_server.py -v`
Expected: all tests in the module pass

- [ ] **Step 5: Run the whole suite**

Run: `cd mcp/fantacalcio && uv run pytest -v`
Expected: all tests pass with zero failures (count is indicative, not a gate)

- [ ] **Step 6: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio
git commit -m "feat(mcp): expose seven read-only tools over stdio"
```

---

### Task 7: Live smoke test and Claude Code registration

**Files:**
- Create: `mcp/fantacalcio/scripts/smoke.py`
- Create: `mcp/fantacalcio/README.md`
- Modify: `/Users/grimid3v/Workspace/fantaclaudio/.mcp.json`

**Interfaces:**
- Consumes: everything above, plus the real `.env` at the workspace root.
- Produces: a verified end-to-end run against the live league.

- [ ] **Step 1: Write the smoke script**

Create `mcp/fantacalcio/scripts/smoke.py`:

```python
"""Live read-only check against the real league. Not part of the test suite."""

import asyncio

import httpx

from fantacalcio_mcp.api import FantacalcioAPI
from fantacalcio_mcp.auth import Auth
from fantacalcio_mcp.config import load_settings, token_cache_path


async def main() -> None:
    settings = load_settings()
    async with httpx.AsyncClient(timeout=20.0) as http:
        auth = Auth(settings.credentials, token_cache_path(), http,
                    settings.app_key, settings.base_url)
        api = FantacalcioAPI(http, auth, settings.base_url, settings.app_key)
        for name, call in [
            ("league_profile", api.league_profile()),
            ("league_status", api.league_status()),
            ("my_team", api.my_team()),
            ("teams", api.teams()),
            ("participants", api.participants()),
            ("server_time", api.server_time()),
        ]:
            try:
                result = await call
                size = len(result.get("data", result)) if isinstance(result, dict) else len(result)
                print(f"OK   {name:<16} ({size} keys/rows)")
            except Exception as exc:  # noqa: BLE001 - smoke script reports everything
                print(f"FAIL {name:<16} {exc}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the smoke test**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio/mcp/fantacalcio
uv run python scripts/smoke.py
```

Expected: six `OK` lines. A `FAIL ... ATH018` means the credentials in `.env` are
wrong; a `FAIL ... ATH000` means the `app_key` rotated.

- [ ] **Step 3: Register the server with Claude Code**

Create `/Users/grimid3v/Workspace/fantaclaudio/.mcp.json`:

```json
{
  "mcpServers": {
    "fantacalcio": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/Users/grimid3v/Workspace/fantaclaudio/mcp/fantacalcio",
        "fantacalcio-mcp"
      ]
    }
  }
}
```

- [ ] **Step 4: Verify the server starts over stdio**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio/mcp/fantacalcio
uv run python -c "
import asyncio, json
from fastmcp import Client
from fantacalcio_mcp.__main__ import main  # import check only
print('entrypoint importable')
"
```

Expected: `entrypoint importable`, no traceback.

- [ ] **Step 5: Write the README**

Create `mcp/fantacalcio/README.md` covering: what it is, the Python 3.14.7 requirement and why rc2 breaks, `.env` variables (`FANTACALCIO_APP_KEY`, `FANTACALCIO_USERNAME`, `FANTACALCIO_PASSWORD`, optional `FANTACALCIO_LEAGUE_TOKEN` for token-only mode), how to store the password in the keychain (`security add-generic-password -s fantacalcio-mcp -a <username> -w`), the seven tools, how to run the smoke script, and a note that this uses non-public endpoints for personal read-only use.

- [ ] **Step 6: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio .mcp.json
git commit -m "feat(mcp): add smoke script, README and Claude Code registration"
```

---

### Task 8: Remove the Playwright and Node exploration code

**Files:**
- Delete: `tools/capture-session.mjs`, `tools/probe-api.mjs`, `src/client.mjs`, `package.json`, `package-lock.json`, `node_modules/`, `.auth/chromium-profile/`, `captured/`
- Modify: `/Users/grimid3v/Workspace/fantaclaudio/.gitignore`

> **Blocked on Task 2.** Do not start until fixtures exist and `uv run pytest` passes — `captured/` is the only recorded copy of the real payloads.

- [ ] **Step 1: Verify the fixtures made it in**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio/mcp/fantacalcio
uv run pytest -q
ls tests/fixtures/*.json | wc -l     # must be 13
```

Expected: full suite green and 13 fixture files. **If either check fails, stop** — deleting `captured/` now would lose the ground truth permanently.

- [ ] **Step 2: Confirm nothing still references the Node code**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
grep -rn "client.mjs\|capture-session\|probe-api" --include="*.py" --include="*.toml" --include="*.json" mcp/ || echo "no references"
```

Expected: `no references`

- [ ] **Step 3: Delete the artefacts**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
rm -rf tools src package.json package-lock.json node_modules .auth/chromium-profile captured
ls -a    # .auth must still exist if tokens.json was created
```

- [ ] **Step 4: Update .gitignore**

Replace `/Users/grimid3v/Workspace/fantaclaudio/.gitignore` with:

```gitignore
.env
.auth/
captured/
node_modules/
__pycache__/
.venv/
.pytest_cache/
*.pyc
```

- [ ] **Step 5: Verify the suite still passes without captured/**

Run: `cd mcp/fantacalcio && uv run pytest -q`
Expected: all tests pass with zero failures — proving the tests depend only on committed fixtures.

- [ ] **Step 6: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add -A
git commit -m "chore: remove Playwright/Node exploration code superseded by the MCP"
```

---

## Self-Review

**Spec coverage:** auth model → Task 4; login contract → Task 4; 13 endpoints → Task 5; hybrid models with `raw` → Task 3; 7 consolidated tools → Task 6; stdio default and HTTP loopback → Task 6; error-code mapping → Task 5; fixtures with no network → Tasks 2–6; security (no secrets, emails dropped, `parola` omitted) → Tasks 2, 3, 6; cleanup with the fixtures-first ordering → Tasks 2 and 8. Phases 2 and 3 are deliberately out of scope.

**Type consistency:** `Auth.token_for(alias)` is called with the keyword `league=` nowhere — `api.py` passes it positionally as `self._auth.token_for(league)`. `FantacalcioAPI` methods take `league: str | None` uniformly; `server.py` forwards the same name. `from_api` is the constructor on every model except `LeagueSettings.from_api`, which takes three keyword payloads and is called that way in Task 6.

**Placeholder scan:** clean — no TBDs, and every code step carries runnable code rather than a description of code.

**Resolved during review:** an earlier draft had `get_account` call `api.profile("me")`, guessing at a path segment never observed live. It now reads `user_id` from the account token's claim, which is data we have verified. Guessing was the wrong thing to hand an executor who cannot see the API.
