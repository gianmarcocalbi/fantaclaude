# fantaclaude Phase 0a — the spine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the repository into a uv workspace with a `fantaclaude` package that holds the league's rules and the listone in DuckDB, exposes them through a typed CLI, encodes the Mantra role model from the official module table, and hardens the MCP's token cache for two processes.

**Architecture:** `core/` is a workspace member (`fantaclaude`) that imports `fantacalcio_mcp.api` as a library — one HTTP client, one endpoint map. DuckDB `data/fanta.duckdb` is the only database; every ingest appends a dated raw file and a snapshot row, nothing is overwritten. The CLI (`Typer`) is the single interface skills call: every read command has `--json`, real exit codes, and an importable function behind it. The Mantra module table is domain data in `model/modules.yml`, transcribed from the official PDF, never inferred from the API.

**Tech Stack:** Python 3.14.7, uv 0.12.5 (workspace), duckdb 1.5.5, typer 0.27.1, pyyaml 6.0.3, httpx 0.28.1, pydantic 2.13.4, poethepoet 0.48.0, pytest 9.1.1, pytest-asyncio 1.4.0, respx 0.23.1, ruff 0.16.4.

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` (sections "Relationship to `fantacalcio-mcp`", "League configuration is data, not constants", "Repository architecture", "The skill ↔ Python contract", "The Mantra role model", "Concurrency", "Schema", "Ingestion adapters", "Name matching", "Testing", "Phasing" row 0a). The MCP's own spec, `docs/superpowers/specs/2026-08-22-fantacalcio-mcp-design.md`, governs everything under `mcp/fantacalcio/` (sections "The listone", "Mantra role codes", "Auth & token lifecycle").

## Global Constraints

- **Python is 3.14.7 (final)**, never 3.14.0rc2 (pydantic's `_eval_type(prefer_fwd_module=...)` breaks on rc2). **uv ≥ 0.12.5.** Both are installed: `uv --version` → `0.12.5`, `uv python list --only-installed` shows `cpython-3.14.7`.
- **Workspace root** is `/Users/grimid3v/Workspace/fantaclaudio`; `fantacalcio_mcp.config.workspace_root()` resolves it (honouring `FANTACALCIO_HOME`) and `fantaclaude.paths` must reuse that function, never re-derive it.
- **No test performs network I/O.** HTTP is mocked with `respx`; the league API is fixture-backed. **Never run `fantaclaude sync-league`, `fantaclaude ingest`, or `mcp/fantacalcio/scripts/smoke.py` in a loop** — each may authenticate against a real account. The plan names the exactly-once live runs (Task 14, Step 4) and nothing else may call the live API.
- **Secrets never enter fixtures, tests or git**: no JWT (`eyJhbGci`), no `app_key`, no email address (`@`), no `parola`. Secret-scanning tests assert on key names and shapes, never on a literal value. `.env`, `.auth/`, `captured/` and `data/` stay gitignored.
- **Email addresses never reach a tool result or a stored payload.** Team payloads carry usernames, never emails; the `League.from_api` model already pops `parola` — store `raw` from the models, never the bare HTTP body.
- **League rules are never hardcoded.** Budget, team count, modules, roster bounds and bonus/malus come from the `league_settings` snapshot at run time. `league.yml` holds only what the API cannot express; every leaf carries `value`, `source`, `verified_on`.
- **MCP field-naming rule** applies to every payload column: a friendly name only for a field whose meaning the MCP spec confirms (`fcrle`, `marle`, `icsfc/acsfc`, `icsma/acsma`, `fvmfc/fvmma`, `name`, `tname`, `stnme`, `tid`, `age`, `naty`, `trnsf`). Everything else stays inside the `raw` JSON column. `lid` is *not* confirmed as the season id — do not name it.
- **Mantra role codes** (MCP spec, confirmed): `6 Por, 7 Dd, 8 Ds, 9 Dc, 10 E, 11 M, 12 C, 13 W, 14 T, 15 A, 16 Pc, 19 B`. An unknown code is an error that names the player, never a silent drop.
- **DuckDB is single-process for writes**, and inside one process a read-only and a read-write connection to the same file cannot coexist (`Can't open a connection to same database file with a different configuration`). `query` opens read-only; `sync-league`/`ingest` open read-write; tests close one connection before opening the other mode. `json` and `parquet` extensions ship installed — nothing is downloaded.
- **The only MCP files this plan touches** are `mcp/fantacalcio/src/fantacalcio_mcp/auth.py` (Task 3, cross-process locking), `api.py` (Task 2, one new method), their tests and fixtures, `pyproject.toml`/`uv.lock`/`.python-version` (Task 1, workspace membership) and `README.md` (Task 14). `api.py` must never import `fastmcp`; `server.py` is not modified.
- **Commit messages document the change, never the tool.** No `Claude-Session:` trailer, no `Co-Authored-By: Claude`, no "Generated with Claude Code" (CLAUDE.md). One commit per task, as written in each task's last step.
- Exit codes are a contract: `0` ok, `1` unexpected error, `2` usage (Typer's default), `3` not ready (nothing ingested yet / database missing / doctor failed), `4` conflict (`league.yml` disagrees with the API).

---

## File Structure

| file | responsibility |
| --- | --- |
| `pyproject.toml` (root) | uv workspace root, dev dependencies, poe tasks |
| `.python-version` (root) | `3.14.7` |
| `.mcp.json` | registers the MCP from the workspace root (`uv run --directory <root> fantacalcio-mcp`) |
| `league.yml` | provenanced facts the API cannot express |
| `preferences.yml` | the user's computation-affecting choices (scaffold only in this phase) |
| `records/README.md` | committed durable exports live here (filled from Phase 1) |
| `kb/README.md`, `kb/rules/aliases.yml`, `kb/**/.gitkeep` | knowledge-base tree and the front-matter contract |
| `core/pyproject.toml` | package `fantaclaude`, script `fantaclaude` |
| `core/src/fantaclaude/__init__.py` | `__version__` |
| `core/src/fantaclaude/paths.py` | every path the package uses, derived from the MCP's `workspace_root()` |
| `core/src/fantaclaude/model/roles.py` | `Role`, `ClassicRole`, code maps, `decode_mantra`, `decode_classic` |
| `core/src/fantaclaude/model/modules.yml` | the eleven modules and their slots — domain data from the official table |
| `core/src/fantaclaude/model/modules.py` | `Slot`, `Module`, `Fit`, `load_modules`, `assign` (exact bipartite matching) |
| `core/src/fantaclaude/db/connection.py` | `connect(path, read_only)` |
| `core/src/fantaclaude/db/schema.py` | DDL, `apply_schema`, `schema_report` |
| `core/src/fantaclaude/league/settings.py` | `LeagueSnapshot`, `rules_hash`, `record_snapshot`, `diff_payloads` |
| `core/src/fantaclaude/league/league_yml.py` | provenanced `league.yml` loader and the API cross-check |
| `core/src/fantaclaude/ingest/raw.py` | `RawStore`: immutable dated raw files with sha256 |
| `core/src/fantaclaude/ingest/listone_api.py` | fetch / load / record the listone through `fantacalcio_mcp.api` |
| `core/src/fantaclaude/api_client.py` | builds a `FantacalcioAPI` from the MCP's settings; sync bridge |
| `core/src/fantaclaude/commands/sync_league.py` | `sync_league()` — the importable command |
| `core/src/fantaclaude/commands/ingest.py` | `ingest_listone()`, `ingest_all()` |
| `core/src/fantaclaude/commands/doctor.py` | readiness checks |
| `core/src/fantaclaude/kb/audit.py` | front-matter parsing and TTL audit |
| `core/src/fantaclaude/cli/app.py` | the Typer app, `ExitCode`, `emit` |
| `core/tests/conftest.py` | fixture loaders (own + MCP fixtures), `FakeAPI`, temp DB |
| `core/tests/fixtures/listone_sample.json` | 17 scrubbed listone rows covering all 12 role codes |
| `core/tests/test_*.py` | one module per source module, plus `test_fixtures.py` (secret scan) |
| `mcp/fantacalcio/src/fantacalcio_mcp/api.py` | `+ players()` |
| `mcp/fantacalcio/src/fantacalcio_mcp/auth.py` | cross-process lock, cache re-read, shared cooldown stamp |
| `mcp/fantacalcio/tests/fixtures/players.json` | 3-row listone fixture for the API test |

Everything under `core/src/fantaclaude/` is imported as `fantaclaude.<module>`. Tests import the MCP fixtures from `mcp/fantacalcio/tests/fixtures/` through a conftest helper — the payload shapes are the MCP's, so the ground truth stays in one place.

---

### Task 1: uv workspace, `core/` skeleton, `paths.py`, CLI entry point

**Files:**
- Create: `pyproject.toml`, `.python-version`, `records/README.md`
- Create: `core/pyproject.toml`, `core/src/fantaclaude/__init__.py`, `core/src/fantaclaude/paths.py`, `core/src/fantaclaude/cli/__init__.py`, `core/src/fantaclaude/cli/app.py`
- Create: `core/tests/conftest.py`, `core/tests/test_paths.py`, `core/tests/test_cli_app.py`
- Modify: `.mcp.json`, `.gitignore`
- Delete: `mcp/fantacalcio/uv.lock`, `mcp/fantacalcio/.python-version` (tracked), `mcp/fantacalcio/.venv/` (untracked)

**Interfaces:**
- Consumes: `fantacalcio_mcp.config.workspace_root() -> Path`.
- Produces: `fantaclaude.paths.{workspace_root, data_dir, raw_dir, db_path, kb_dir, records_dir, league_yml_path, preferences_yml_path}() -> Path`; `fantaclaude.cli.app.app` (Typer), `fantaclaude.cli.app.main()`, `fantaclaude.cli.app.ExitCode(IntEnum)` with `OK=0, ERROR=1, USAGE=2, NOT_READY=3, CONFLICT=4`; `fantaclaude.cli.app.emit(payload: dict, *, json_: bool, render: Callable[[dict], str]) -> None`; pytest fixtures `fixture_json(name)` (core fixtures) and `mcp_fixture_json(name)` (MCP fixtures).

- [ ] **Step 1: Write the failing tests**

Create `core/tests/conftest.py`:

```python
import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
# The league API payload shapes are the MCP's ground truth; reuse its scrubbed
# fixtures instead of keeping a drifting second copy.
MCP_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "mcp" / "fantacalcio" / "tests" / "fixtures"


@pytest.fixture
def fixture_json():
    def _load(name: str):
        return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def mcp_fixture_json():
    def _load(name: str):
        return json.loads((MCP_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load
```

Create `core/tests/test_paths.py`:

```python
from pathlib import Path

from fantaclaude import paths


def test_paths_follow_fantacalcio_home(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    assert paths.workspace_root() == tmp_path.resolve()
    assert paths.data_dir() == tmp_path.resolve() / "data"
    assert paths.raw_dir() == tmp_path.resolve() / "data" / "raw"
    assert paths.db_path() == tmp_path.resolve() / "data" / "fanta.duckdb"
    assert paths.kb_dir() == tmp_path.resolve() / "kb"
    assert paths.records_dir() == tmp_path.resolve() / "records"
    assert paths.league_yml_path() == tmp_path.resolve() / "league.yml"
    assert paths.preferences_yml_path() == tmp_path.resolve() / "preferences.yml"


def test_default_root_is_the_repository(monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    root = paths.workspace_root()
    assert (root / "mcp" / "fantacalcio").is_dir()
    assert (root / "core" / "src" / "fantaclaude").is_dir()
```

Create `core/tests/test_cli_app.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --directory core pytest -q 2>&1 | tail -3`
Expected: FAIL — `uv` cannot resolve `core` as a project yet (no `core/pyproject.toml`), or `ModuleNotFoundError: fantaclaude`.

- [ ] **Step 3: Create the workspace root**

Create `/Users/grimid3v/Workspace/fantaclaudio/pyproject.toml`:

```toml
[project]
name = "fantaclaudio-workspace"
version = "0.0.0"
description = "uv workspace root: fantaclaude (core) and fantacalcio-mcp"
requires-python = ">=3.14.7"
dependencies = [
    "fantaclaude",
    "fantacalcio-mcp",
]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["core", "mcp/fantacalcio"]

[tool.uv.sources]
fantaclaude = { workspace = true }
fantacalcio-mcp = { workspace = true }

[dependency-groups]
dev = [
    "poethepoet>=0.48.0",
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.0",
    "respx>=0.23.1",
    "ruff>=0.16.4",
]

[tool.poe.tasks]
# Two suites, two rootdirs: each package keeps its own pytest configuration
# and its own conftest.py, so they are run separately rather than merged.
test-mcp = "pytest mcp/fantacalcio/tests -c mcp/fantacalcio/pyproject.toml -q"
test-core = "pytest core/tests -c core/pyproject.toml -q"
test = ["test-mcp", "test-core"]
lint = "ruff check core mcp/fantacalcio"
fmt = "ruff format core mcp/fantacalcio"
```

Create `/Users/grimid3v/Workspace/fantaclaudio/.python-version` containing exactly:

```
3.14.7
```

Create `core/pyproject.toml`:

```toml
[project]
name = "fantaclaude"
version = "0.1.0"
description = "Fantacalcio Mantra assistant: data spine, valuation, auction copilot"
requires-python = ">=3.14.7"
dependencies = [
    "duckdb>=1.5.5",
    "typer>=0.27.1",
    "pyyaml>=6.0.3",
    "httpx>=0.28.1",
    "pydantic>=2.13.4",
    "fantacalcio-mcp",
]

[project.scripts]
fantaclaude = "fantaclaude.cli.app:main"

[build-system]
requires = ["uv_build>=0.12.5,<0.13.0"]
build-backend = "uv_build"

[tool.uv]
package = true

[tool.uv.sources]
fantacalcio-mcp = { workspace = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Create `records/README.md`:

```markdown
# records/

Durable, committed exports: parquet copies of `valuations` and `league_settings`
(from Phase 1), and the auction snapshot between the auction and the confirmed
transfer into the lega. Everything in `data/` is gitignored and rebuildable;
what a journal entry links to by `run_id` must be resolvable from here.
```

Append to `.gitignore` (keep the existing entries):

```
data/
```

Replace `.mcp.json` with:

```json
{
  "mcpServers": {
    "fantacalcio": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/Users/grimid3v/Workspace/fantaclaudio",
        "fantacalcio-mcp"
      ]
    }
  }
}
```

Remove the member's own lock, interpreter pin and venv. `uv_build` needs the package directory to exist before the first sync, so create the package marker now (Step 4 fills in the rest):

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git rm -q mcp/fantacalcio/uv.lock
git rm -q --ignore-unmatch mcp/fantacalcio/.python-version; rm -f mcp/fantacalcio/.python-version
rm -rf mcp/fantacalcio/.venv
mkdir -p core/src/fantaclaude && printf '__version__ = "0.1.0"\n' > core/src/fantaclaude/__init__.py
uv sync
uv run fantacalcio-mcp --help
```

Expected: `uv sync` writes a root `uv.lock` and `.venv/`; `fantacalcio-mcp --help` prints the argparse usage (`--transport`, `--host`, `--port`).

- [ ] **Step 4: Write the package skeleton**

Create `core/src/fantaclaude/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `core/src/fantaclaude/paths.py`:

```python
"""Every filesystem location the package uses, in one place.

The root comes from the MCP so both packages agree on FANTACALCIO_HOME and on
what "the workspace" is; nothing here re-derives it from __file__.
"""

from __future__ import annotations

from pathlib import Path

from fantacalcio_mcp.config import workspace_root as _mcp_workspace_root


def workspace_root() -> Path:
    return _mcp_workspace_root()


def data_dir() -> Path:
    return workspace_root() / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def db_path() -> Path:
    return data_dir() / "fanta.duckdb"


def kb_dir() -> Path:
    return workspace_root() / "kb"


def records_dir() -> Path:
    return workspace_root() / "records"


def league_yml_path() -> Path:
    return workspace_root() / "league.yml"


def preferences_yml_path() -> Path:
    return workspace_root() / "preferences.yml"
```

Create `core/src/fantaclaude/cli/__init__.py` (empty) and `core/src/fantaclaude/cli/app.py`:

```python
"""The `fantaclaude` CLI: the single interface skills call.

Every read command takes --json and prints one JSON document on stdout; the
human rendering is the same payload passed through a small renderer. Exit codes
are part of the contract (see ExitCode) so a caller can tell "nothing ingested
yet" from "this crashed" without parsing a traceback. Commands are thin: each
one calls an importable function under fantaclaude.commands.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import IntEnum

import typer

from fantaclaude import __version__


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1
    USAGE = 2          # Typer/Click's own code for bad arguments
    NOT_READY = 3      # database missing, nothing ingested yet, doctor failed
    CONFLICT = 4       # league.yml disagrees with the API


app = typer.Typer(
    name="fantaclaude",
    help="Fantacalcio Mantra assistant — data spine and auction tooling.",
    no_args_is_help=True,
)


def emit(payload: dict, *, json_: bool, render: Callable[[dict], str]) -> None:
    """Print `payload` as JSON (--json) or through `render` (human)."""
    if json_:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
    else:
        typer.echo(render(payload))


def _version(value: bool) -> None:
    if value:
        typer.echo(f"fantaclaude {__version__}")
        raise typer.Exit(code=ExitCode.OK)


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True,
        help="Print the version and exit."),
) -> None:
    """Fantacalcio Mantra assistant — data spine and auction tooling."""


def main() -> None:
    app()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/grimid3v/Workspace/fantaclaudio && uv sync -q && uv run poe test-core`
Expected: `6 passed`.

- [ ] **Step 6: Verify the MCP suite still passes from the root lock**

Run: `cd /Users/grimid3v/Workspace/fantaclaudio && uv run poe test-mcp`
Expected: `91 passed` — the same count as before the migration. If pytest reports `import file mismatch` or cannot import `conftest`, the `-c` flag was dropped from the poe task; restore it (it is what sets each suite's rootdir).

- [ ] **Step 7: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add pyproject.toml .python-version uv.lock .gitignore .mcp.json records/README.md core/ mcp/fantacalcio/uv.lock mcp/fantacalcio/.python-version
git commit -m "build: uv workspace with core/ (fantaclaude) and the MCP as members"
```

---

### Task 2: `FantacalcioAPI.players()` — the listone endpoint

**Files:**
- Modify: `mcp/fantacalcio/src/fantacalcio_mcp/api.py` (after `server_time`, before `_pagination`)
- Create: `mcp/fantacalcio/tests/fixtures/players.json`
- Modify: `mcp/fantacalcio/tests/test_fixtures.py` (`EXPECTED`), `mcp/fantacalcio/tests/test_api.py`

**Interfaces:**
- Consumes: `FantacalcioAPI._get(path, *, league=...)`.
- Produces: `async def players(self, league: str | None = None) -> Any` returning the raw `{"players": [...], "timestamp": ...}` payload of `GET /onboarding/v1/league/players`.

- [ ] **Step 1: Write the fixture from the capture**

`captured/listone-2026-08-23.json` (gitignored, on disk) is the source of truth for the listone shape. Extract three rows — ids `3` (Radunovic, `Por`), `254` (Dimarco, `E`+`T`) and `5877` (Carlos Augusto, `B`+`Ds`+`E`, the code-19 case) — dropping only `img`, a CDN path with no confirmed meaning:

```bash
python3 -c "
import json
P = {p['id']: p for p in json.load(open('captured/listone-2026-08-23.json'))['players']}
rows = [{k: v for k, v in P[i].items() if k != 'img'} for i in (3, 254, 5877)]
json.dump({'players': rows, 'timestamp': 1787517550778},
          open('mcp/fantacalcio/tests/fixtures/players.json', 'w'), ensure_ascii=False, indent=1)
print(len(rows), 'rows')"
```

Expected: `3 rows`. The first row is, verbatim:

```json
{"lid": 21, "trnsf": 0, "trsfd": 0, "quotd": 1, "tid": 21, "fvmfc": 1, "fvmma": 1, "mspv": 0, "mspvi": 0, "mspva": 0, "wid": 387733, "bmcsh": 0, "id": 3, "fcrle": 1, "icsfc": 1, "icsma": 1, "acsfc": 1, "acsma": 1, "age": 30, "agrd": 0.0, "fagrd": 0.0, "aagr": 0.0, "faagr": 0.0, "agit": 0.0, "fagit": 0.0, "marle": [6], "name": "Radunovic", "tname": "Cagliari", "stnme": "CAG", "leag": "ITA", "naty": "Serbia", "shtnu": "0", "vers": "v=692", "l5sub": [""], "l5rfc": [56.0], "l5frfc": [0.0], "l5rit": [56.0], "l5frit": [0.0], "l5ral": [56.0], "l5fral": [0.0]}
```

and the other two carry `"marle": [10, 14]` (id 254, `icsfc` 32 / `icsma` 30) and `"marle": [19, 8, 10]` (id 5877, `icsfc` 7 / `icsma` 8). The listone holds no secret — player names, clubs and prices are public — but the secret-scan test in this suite still runs over it.

- [ ] **Step 2: Write the failing tests**

In `mcp/fantacalcio/tests/test_fixtures.py`, add `"players"` to `EXPECTED`:

```python
EXPECTED = {
    "profile", "league_profile", "league_status", "competitions", "my_team",
    "teams", "roster_settings", "lineup_settings", "calculation_settings",
    "participants", "invitees", "server_time", "login", "players",
}
```

and append:

```python
def test_players_fixture_carries_confirmed_fields(fixture_json):
    rows = fixture_json("players")["players"]
    assert len(rows) == 3
    for row in rows:
        assert {"id", "name", "tname", "tid", "fcrle", "marle", "icsma", "acsma"} <= set(row)
    assert any(19 in row["marle"] for row in rows), "the B (code 19) case must be represented"
```

Append to `mcp/fantacalcio/tests/test_api.py`:

```python
async def test_players_hits_the_listone_endpoint_with_league_token(api, fixture_json, valid_token):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/league/players").mock(
            return_value=httpx.Response(200, json=fixture_json("players")))
        payload = await api.players()
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {valid_token}"
    assert [p["id"] for p in payload["players"]] == [3, 254, 5877]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/grimid3v/Workspace/fantaclaudio && uv run poe test-mcp 2>&1 | tail -5`
Expected: FAIL — `AttributeError: 'FantacalcioAPI' object has no attribute 'players'`.

- [ ] **Step 4: Add the endpoint method**

In `mcp/fantacalcio/src/fantacalcio_mcp/api.py`, after `server_time` and before `def _pagination`:

```python
    async def players(self, league: str | None = None) -> Any:
        """The listone: every Serie A player with Classic role, Mantra role
        codes and both quotazioni. ~515 KB, 539 rows — a library call for
        ingestion, deliberately not exposed as a tool. See the spec, "The
        listone".
        """
        return await self._get("/onboarding/v1/league/players", league=league)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/grimid3v/Workspace/fantaclaudio && uv run poe test-mcp`
Expected: `93 passed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio/src/fantacalcio_mcp/api.py mcp/fantacalcio/tests/test_api.py mcp/fantacalcio/tests/test_fixtures.py mcp/fantacalcio/tests/fixtures/players.json
git commit -m "feat(mcp): players() reads the listone endpoint"
```

---

### Task 3: Cross-process token-cache coordination in `auth.py`

**Files:**
- Modify: `mcp/fantacalcio/src/fantacalcio_mcp/auth.py`
- Modify: `mcp/fantacalcio/tests/test_auth.py`

**Interfaces:**
- Consumes: the existing `Auth` (`_login_lock`, `_load_cache`, `_save_cache`, `_login_and_record`, `_begin_recovery_login`, `_maybe_login`, `refresh_if_stale`, `refresh_account_if_stale`, `invalidate`).
- Produces: no public API change. Two sidecar files next to the cache: `tokens.json.lock` (flock, held around every login-and-write) and `login-attempt.json` (`{"at": <epoch>, "kind": "login"|"recovery", "error_type": str|null, "message": str|null}`, the last attempt any process made). Behaviour: the loser of a cross-process race re-reads the cache under the lock and uses the winner's token; a failed attempt within the cooldown is re-raised, with its original type, in every process; a recovery within the cooldown of another process's recovery is refused. `invalidate()` removes the stamp along with the cache.

Why the stamp carries a `kind`: in-process, `_last_login_at` and `_last_recovery_login_at` are two clocks on purpose — the first recovery after an ordinary login must be allowed, while sequential recoveries are bounded (`test_sequential_401s_do_not_relogin_once_per_tool_call` pins both). The shared stamp mirrors that split: `_maybe_login` honours any recent attempt; `_begin_recovery_login` honours only recent *recovery* attempts.

- [ ] **Step 1: Write the failing tests**

Append to `mcp/fantacalcio/tests/test_auth.py`:

```python
# ---- cross-process coordination ------------------------------------------
# Two Auth instances on one cache path stand in for two processes: flock is
# per open file description, so two opens of the same sidecar contend exactly
# as two processes would (verified on this platform before writing these).


def _cache_with(jwt: str) -> str:
    return json.dumps({"account": None, "user_id": None, "username": "u", "leagues": {
        "fantabalotelli3": {"alias": "fantabalotelli3", "league_id": "2578630",
                            "team_id": "11560832", "name": "Fantabalotelli3", "jwt": jwt}}})


async def test_two_cold_instances_share_one_login(tmp_path, login_response):
    cache = tmp_path / "tokens.json"

    async def slow_login(request):
        await asyncio.sleep(0.01)   # long enough for the second instance to reach the lock
        return httpx.Response(200, json=login_response)

    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(side_effect=slow_login)
        async with httpx.AsyncClient(base_url=BASE) as http:
            first = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            second = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            tokens = await asyncio.gather(first.token_for(), second.token_for())
    assert route.call_count == 1
    assert len(set(tokens)) == 1
    assert (tmp_path / "tokens.json.lock").stat().st_mode & 0o777 == 0o600


async def test_failed_login_in_one_instance_holds_the_cooldown_for_another(tmp_path):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(
            400, json={"code": "ATH018", "message": "Invalid username or password"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            first = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await first.token_for()
            second = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await second.token_for()
    assert route.call_count == 1
    stamp_path = tmp_path / "login-attempt.json"
    stamp = json.loads(stamp_path.read_text())
    assert set(stamp) == {"at", "kind", "error_type", "message"}
    assert stamp["kind"] == "login" and stamp["error_type"] == "ConfigurationError"
    assert "eyJhbGci" not in stamp_path.read_text()
    assert stamp_path.stat().st_mode & 0o777 == 0o600


async def test_shared_cooldown_expires(tmp_path):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(
            400, json={"code": "ATH018", "message": "Invalid username or password"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            first = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError):
                await first.token_for()
            stamp_path = tmp_path / "login-attempt.json"
            stamp = json.loads(stamp_path.read_text())
            stamp["at"] = time.time() - 120          # older than the 60 s cooldown
            stamp_path.write_text(json.dumps(stamp))
            second = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError):
                await second.token_for()
    assert route.call_count == 2


@pytest.mark.parametrize("garbage", ["null", "[]", '{"at": "soon"}', "{not json"])
async def test_corrupt_stamp_is_ignored(tmp_path, login_response, garbage):
    (tmp_path / "login-attempt.json").write_text(garbage)
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), tmp_path / "tokens.json", http, "K", BASE).token_for()
    assert route.call_count == 1


async def test_recovery_adopts_a_token_another_process_already_refreshed(tmp_path):
    cache = tmp_path / "tokens.json"
    stale = league_jwt(exp_offset=3_600)
    fresh = league_jwt(exp_offset=7_200)      # a different string, still valid
    cache.write_text(_cache_with(stale))
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            assert await auth.token_for() == stale
            cache.write_text(_cache_with(fresh))    # "another process" recovered meanwhile
            assert await auth.refresh_if_stale(stale) == fresh
    assert not route.called


async def test_recovery_honours_a_failed_recovery_from_another_process(tmp_path):
    cache = tmp_path / "tokens.json"
    stale = league_jwt(exp_offset=3_600)
    cache.write_text(_cache_with(stale))
    (tmp_path / "login-attempt.json").write_text(json.dumps({
        "at": time.time(), "kind": "recovery", "error_type": "ConfigurationError",
        "message": "ATH018: Invalid username or password"}))
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            assert await auth.token_for() == stale
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.refresh_if_stale(stale)
            assert cache.exists(), "a refusal must leave the cache intact"
    assert not route.called


async def test_ordinary_login_is_not_blocked_by_a_recent_recovery_stamp(tmp_path, login_response):
    """A recovery elsewhere must not stop a cold process from logging in when
    the cache it re-reads has nothing usable -- only an ordinary attempt or a
    failure holds an ordinary login back."""
    (tmp_path / "login-attempt.json").write_text(json.dumps({
        "at": time.time(), "kind": "recovery", "error_type": None, "message": None}))
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), tmp_path / "tokens.json", http, "K", BASE).token_for()
    assert route.call_count == 1
```

In the existing `test_cache_directory_and_file_are_owner_only`, replace the last two lines

```python
    # No leftover temp files from the atomic-write dance.
    assert list(cache.parent.iterdir()) == [cache]
```

with

```python
    # No leftover temp files from the atomic-write dance -- only the cache and
    # the two cross-process sidecars, every one of them owner-only.
    assert sorted(p.name for p in cache.parent.iterdir()) == [
        "login-attempt.json", "tokens.json", "tokens.json.lock"]
    for entry in cache.parent.iterdir():
        assert entry.stat().st_mode & 0o777 == 0o600, entry.name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-mcp 2>&1 | tail -12`
Expected: the seven new tests FAIL (`route.call_count == 2` where 1 is expected; `FileNotFoundError: login-attempt.json`; the directory listing test sees only `tokens.json`). Every pre-existing test still passes.

- [ ] **Step 3: Add the sidecar paths and helpers to `auth.py`**

Add two imports at the top of `mcp/fantacalcio/src/fantacalcio_mcp/auth.py`, keeping the alphabetical order:

```python
import contextlib
import fcntl
```

In `Auth.__init__`, immediately after `self._cache_path = cache_path`:

```python
        # Cross-process coordination lives beside the cache: a flock sidecar
        # serialises login-and-write across processes (fantaclaude sync-league
        # and the MCP server both drive this class), and a stamp records the
        # last attempt so the cooldown holds for a process that was not the
        # one to try. See _cross_process_lock and _recent_shared_attempt.
        self._lock_path = cache_path.with_name(cache_path.name + ".lock")
        self._stamp_path = cache_path.with_name("login-attempt.json")
```

After `_discard_cache_file`, add:

```python
    def _discard_stamp_file(self) -> None:
        try:
            self._stamp_path.unlink(missing_ok=True)
        except OSError:
            pass

    @contextlib.asynccontextmanager
    async def _cross_process_lock(self):
        """Hold the flock sidecar for the duration of a login-and-write.

        `_login_lock` serialises coroutines inside one process and nothing
        else; two processes racing a login is how a real account gets
        locked. flock is taken on a sidecar rather than on the cache file,
        because the cache is replaced atomically (os.replace) and a lock on
        it would end up attached to an unlinked inode. The blocking acquire
        runs in a thread so the event loop stays free. Best-effort like
        every other filesystem step here: if the sidecar cannot be opened
        the login proceeds unlocked rather than not at all.
        """
        fd: int | None = None
        try:
            self._secure_cache_dir()
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX)
        except OSError:
            if fd is not None:
                os.close(fd)
            fd = None
        try:
            yield
        finally:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _recent_shared_attempt(self) -> tuple[str, BaseException | None] | None:
        """The last login attempt any process recorded, if it is still inside
        the cooldown window: (kind, exception-or-None). A missing, stale or
        unreadable stamp is None -- fail open to "no recent attempt", the
        same way a corrupt cache is treated as a cold start. Unknown error
        types come back as AuthError so a transient failure elsewhere is not
        mistaken for a success.
        """
        try:
            data = json.loads(self._stamp_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("at"), (int, float)):
            return None
        if time.time() - float(data["at"]) >= self._login_cooldown_seconds:
            return None
        kind = data.get("kind") if data.get("kind") in ("login", "recovery") else "login"
        message = str(data.get("message") or "")
        error_type = data.get("error_type")
        if error_type is None:
            return kind, None
        if error_type == "ConfigurationError":
            return kind, ConfigurationError(message)
        return kind, AuthError(message)

    def _write_stamp(self, at: float, kind: str, error: BaseException | None) -> None:
        """Record an attempt for other processes -- the same atomic, owner-only,
        best-effort write as the cache. The message is the exception text (an
        error code and a hint), never a token or a credential.
        """
        payload = json.dumps({
            "at": at,
            "kind": kind,
            "error_type": type(error).__name__ if error is not None else None,
            "message": str(error)[:500] if error is not None else None,
        }).encode("utf-8")
        try:
            self._secure_cache_dir()
            fd, tmp_name = tempfile.mkstemp(dir=self._stamp_path.parent,
                                            prefix=".stamp-", suffix=".tmp")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self._stamp_path)
            except OSError:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError:
            pass
```

- [ ] **Step 4: Wire the stamp into the attempt bookkeeping**

In `invalidate()`, after `self._discard_cache_file()` add `self._discard_stamp_file()`, and append this sentence to its docstring: `The shared attempt stamp goes with the cache file: invalidate() means the next login is wanted, in this process or another.`

Replace the body of `_login_and_record` (keep its docstring) so it takes a `kind` and records the attempt:

```python
    async def _login_and_record(self, *, kind: str = "login") -> None:
        """(existing docstring unchanged)"""
        self._last_login_at = time.time()
        try:
            await self.login()
        except Exception as exc:
            self._last_login_error = exc
            self._write_stamp(self._last_login_at, kind, exc)
            raise
        else:
            self._last_login_error = None
            self._write_stamp(self._last_login_at, kind, None)
```

Replace the body of `_begin_recovery_login` (keep its docstring, and append: `The attempt stamp extends this clock across processes: another process's recovery inside the window is refused the same way, and its failure is re-raised with its own type.`):

```python
        now = time.time()
        recent = self._recent_shared_attempt()
        if recent is not None and recent[0] == "recovery" and recent[1] is not None:
            raise recent[1]
        if ((self._last_recovery_login_at is not None
                and now - self._last_recovery_login_at < self._login_cooldown_seconds)
                or (recent is not None and recent[0] == "recovery")):
            raise AuthError(
                "token rejected immediately after a fresh login -- refusing to "
                "log in again inside the cooldown window. The server is "
                "rejecting a token it just issued (revoked session, a WAF, or a "
                "league state change); try again in a minute."
            )
        self._last_recovery_login_at = now
```

Replace the body of `_maybe_login` (keep its docstring, and append: `Across processes the same two guards are the flock sidecar and the attempt stamp: once the lock is held the cache is re-read, so the loser of a race uses the winner's token instead of logging in again, and a recent attempt recorded by any process answers the way an in-process one does -- a failure re-raised with its original type, a success taken as already done.`):

```python
        async with self._login_lock:
            if not still_needed():
                return
            now = time.time()
            if (self._last_login_at is not None
                    and now - self._last_login_at < self._login_cooldown_seconds):
                if self._last_login_error is not None:
                    raise self._last_login_error
                return
            async with self._cross_process_lock():
                self._load_cache()          # adopt what another process wrote meanwhile
                if not still_needed():
                    return
                recent = self._recent_shared_attempt()
                if recent is not None and recent[0] == "login":
                    if recent[1] is not None:
                        raise recent[1]
                    return
                await self._login_and_record()
```

In `refresh_account_if_stale`, replace everything from `async with self._login_lock:` to the end of the method with:

```python
        async with self._login_lock:
            if (self._account_jwt is not None and self._account_jwt != failed_token
                    and not _cache_token_expired(self._account_jwt)):
                return self._account_jwt

            async with self._cross_process_lock():
                self._load_cache()
                if (self._account_jwt is not None and self._account_jwt != failed_token
                        and not _cache_token_expired(self._account_jwt)):
                    return self._account_jwt     # another process already recovered

                if self._recovery_attempted_for != failed_token:
                    # Before invalidate(), so a refusal leaves the cache intact.
                    self._begin_recovery_login()
                    self.invalidate()
                    self._recovery_attempted_for = failed_token
                    try:
                        await self._login_and_record(kind="recovery")
                    except Exception:
                        pass  # outcome is read from _last_login_error below,
                              # the same way for us and every piggybacking waiter

                if self._last_login_error is not None:
                    raise self._last_login_error
                if self._account_jwt is None or _cache_token_expired(self._account_jwt):
                    raise AuthError("login did not return a valid account token")
                return self._account_jwt
```

In `refresh_if_stale`, replace everything from `async with self._login_lock:` to the end of the method with:

```python
        async with self._login_lock:
            current = self._pick(alias)
            if (current is not None and current.jwt != failed_token
                    and not _cache_token_expired(current.jwt)):
                return current.jwt

            async with self._cross_process_lock():
                self._load_cache()
                current = self._pick(alias)
                if (current is not None and current.jwt != failed_token
                        and not _cache_token_expired(current.jwt)):
                    return current.jwt           # another process already recovered

                if self._recovery_attempted_for != failed_token:
                    # Before invalidate(), so a refusal leaves the cache intact.
                    self._begin_recovery_login()
                    self.invalidate()
                    self._recovery_attempted_for = failed_token
                    try:
                        await self._login_and_record(kind="recovery")
                    except Exception:
                        pass  # outcome is read from _last_login_error below,
                              # the same way for us and every piggybacking waiter

                if self._last_login_error is not None:
                    raise self._last_login_error
                current = self._pick(alias)
                if current is None or _cache_token_expired(current.jwt):
                    raise AuthError(
                        f"league {alias!r} not found after recovery login. Available: "
                        f"{', '.join(sorted(self._leagues)) or 'none'}"
                    )
                return current.jwt
```

(The comment block that explained the "distinct token per login" assumption above the fast path stays where it is.)

- [ ] **Step 5: Run the whole MCP suite**

Run: `cd /Users/grimid3v/Workspace/fantaclaudio && uv run poe test-mcp`
Expected: `100 passed` (93 + 7 new). Three existing tests are the ones most likely to regress and are the ones that prove the design is right: `test_sequential_401s_do_not_relogin_once_per_tool_call` (2 logins), `test_recovery_cooldown_expires_and_allows_a_later_recovery` (3 logins; the stamp expires with `login_cooldown=0.05` because it reads `_login_cooldown_seconds`), `test_invalidate_forces_fresh_login_and_removes_cache_file` (invalidate removed the stamp, so the second login is allowed).

- [ ] **Step 6: Update the MCP spec's auth section**

In `docs/superpowers/specs/2026-08-22-fantacalcio-mcp-design.md`, section "Auth & token lifecycle", after the "**Token cache:**" paragraph add:

```markdown
**Cross-process:** the cache is shared by every process that imports this
module (the MCP server and the `fantaclaude` CLI). A `flock` sidecar
(`tokens.json.lock`) is held around every login-and-write, the cache is
re-read once the lock is held so the loser of a race uses the winner's token,
and `login-attempt.json` records the last attempt (kind, time, error type) so
the cooldown and the never-retry rule for `ATH018` hold across processes, not
per instance.
```

- [ ] **Step 7: Commit**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
git add mcp/fantacalcio/src/fantacalcio_mcp/auth.py mcp/fantacalcio/tests/test_auth.py docs/superpowers/specs/2026-08-22-fantacalcio-mcp-design.md
git commit -m "fix(mcp): hold a file lock and a shared attempt stamp around login"
```

---

### Task 4: Mantra roles and the listone's role codes

**Files:**
- Create: `core/src/fantaclaude/model/__init__.py`, `core/src/fantaclaude/model/roles.py`
- Test: `core/tests/test_roles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Role(StrEnum)` with the twelve members `Por Dd Ds Dc B E M C T W A Pc` (in that declaration order); `ClassicRole(StrEnum)` `P D C A`; `MANTRA_CODES: dict[int, Role]`; `CLASSIC_CODES: dict[int, ClassicRole]`; `DEFENSIVE`, `OFFENSIVE: frozenset[Role]`; `ROLE_ORDER: tuple[Role, ...]`; `UnknownRoleCode(ValueError)` with `.codes`; `decode_mantra(codes: Iterable[int], *, context: str = "") -> frozenset[Role]`; `decode_classic(code: int, *, context: str = "") -> ClassicRole`; `sort_roles(roles: Iterable[Role]) -> list[Role]`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_roles.py`:

```python
import pytest

from fantaclaude.model.roles import (
    CLASSIC_CODES, DEFENSIVE, MANTRA_CODES, OFFENSIVE, ROLE_ORDER, ClassicRole, Role,
    UnknownRoleCode, decode_classic, decode_mantra, sort_roles,
)


def test_twelve_mantra_roles_and_their_listone_codes():
    assert len(Role) == 12
    assert MANTRA_CODES == {
        6: Role.Por, 7: Role.Dd, 8: Role.Ds, 9: Role.Dc, 10: Role.E, 11: Role.M,
        12: Role.C, 13: Role.W, 14: Role.T, 15: Role.A, 16: Role.Pc, 19: Role.B,
    }
    assert set(MANTRA_CODES.values()) == set(Role)
    assert CLASSIC_CODES == {1: ClassicRole.P, 2: ClassicRole.D, 3: ClassicRole.C, 4: ClassicRole.A}


def test_code_19_is_braccetto():
    assert decode_mantra([19, 8, 10]) == frozenset({Role.B, Role.Ds, Role.E})


def test_defensive_and_offensive_partition_the_outfield_roles():
    assert DEFENSIVE | OFFENSIVE == set(Role) - {Role.Por}
    assert not DEFENSIVE & OFFENSIVE


def test_unknown_code_fails_loud_and_names_the_player():
    with pytest.raises(UnknownRoleCode, match=r"\[20\].*Rossi") as excinfo:
        decode_mantra([9, 20], context="Rossi (id 42)")
    assert excinfo.value.codes == [20]


def test_empty_role_list_is_an_error():
    with pytest.raises(ValueError, match="no Mantra role"):
        decode_mantra([])


def test_classic_decoding():
    assert [decode_classic(c) for c in (1, 2, 3, 4)] == list(ClassicRole)
    with pytest.raises(UnknownRoleCode):
        decode_classic(5)


def test_sort_roles_uses_the_canonical_order():
    assert ROLE_ORDER == tuple(Role)
    assert sort_roles({Role.E, Role.B, Role.Ds}) == [Role.Ds, Role.B, Role.E]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.model'`.

- [ ] **Step 3: Write the module**

Create `core/src/fantaclaude/model/__init__.py` (empty) and `core/src/fantaclaude/model/roles.py`:

```python
"""Mantra and Classic roles, and the listone's numeric codes for them.

Twelve Mantra roles. The codes are the listone's `marle` values, confirmed in
the MCP spec ("Mantra role codes"); 19 is B, confirmed against a player's
public role badges on 2026-08-24. A code outside this table is an error that
names the player -- never a silent drop, because a striker quietly missing
from the pool is exactly the failure this system exists to avoid.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    Por = "Por"
    Dd = "Dd"
    Ds = "Ds"
    Dc = "Dc"
    B = "B"
    E = "E"
    M = "M"
    C = "C"
    T = "T"
    W = "W"
    A = "A"
    Pc = "Pc"


class ClassicRole(StrEnum):
    P = "P"
    D = "D"
    C = "C"
    A = "A"


MANTRA_CODES: dict[int, Role] = {
    6: Role.Por, 7: Role.Dd, 8: Role.Ds, 9: Role.Dc, 10: Role.E, 11: Role.M,
    12: Role.C, 13: Role.W, 14: Role.T, 15: Role.A, 16: Role.Pc, 19: Role.B,
}
CLASSIC_CODES: dict[int, ClassicRole] = {
    1: ClassicRole.P, 2: ClassicRole.D, 3: ClassicRole.C, 4: ClassicRole.A,
}

# The regolamento's split: every scheme fields five players from the first
# group and five from the second among its ten outfield players.
DEFENSIVE: frozenset[Role] = frozenset({Role.Dd, Role.Ds, Role.Dc, Role.B, Role.E, Role.M})
OFFENSIVE: frozenset[Role] = frozenset({Role.C, Role.T, Role.W, Role.A, Role.Pc})

ROLE_ORDER: tuple[Role, ...] = tuple(Role)


class UnknownRoleCode(ValueError):
    def __init__(self, codes: Iterable[int], *, context: str = "") -> None:
        self.codes = sorted(set(codes))
        where = f" for {context}" if context else ""
        super().__init__(
            f"unknown role code(s) {self.codes}{where}; known Mantra codes: "
            f"{sorted(MANTRA_CODES)}, Classic codes: {sorted(CLASSIC_CODES)}"
        )


def decode_mantra(codes: Iterable[int], *, context: str = "") -> frozenset[Role]:
    codes = list(codes)
    unknown = [c for c in codes if c not in MANTRA_CODES]
    if unknown:
        raise UnknownRoleCode(unknown, context=context)
    if not codes:
        where = f" for {context}" if context else ""
        raise ValueError(f"no Mantra role{where}: every player carries at least one")
    return frozenset(MANTRA_CODES[c] for c in codes)


def decode_classic(code: int, *, context: str = "") -> ClassicRole:
    try:
        return CLASSIC_CODES[code]
    except KeyError:
        raise UnknownRoleCode([code], context=context) from None


def sort_roles(roles: Iterable[Role]) -> list[Role]:
    return sorted(roles, key=ROLE_ORDER.index)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/model core/tests/test_roles.py
git commit -m "feat(model): Mantra roles and the listone role codes, B included"
```

---

### Task 5: The module table and exact feasibility matching

**Files:**
- Create: `core/src/fantaclaude/model/modules.yml`, `core/src/fantaclaude/model/modules.py`
- Test: `core/tests/test_modules.py`

**Interfaces:**
- Consumes: `Role` (Task 4); the MCP fixture `lineup_settings.json` (`mods`).
- Produces: `Fit(Enum)` `NATURAL | ADAPTED | FORCED_ONLY | NO`; `Slot(label: str, natural: frozenset[Role], adapted: frozenset[Role], forced_only: frozenset[Role])` with `fit(roles: frozenset[Role]) -> Fit`; `Module(code: str, label: str, slots: tuple[Slot, ...])` with `slot_counts() -> dict[str, int]`; `ModuleTableError(ValueError)`; `MODULES_YML: Path`; `load_modules(path: Path = MODULES_YML) -> dict[str, Module]` (keyed by code such as `"343"`, cached); `assign(module: Module, roster: Sequence[frozenset[Role]], *, allow_adapted: bool = False) -> list[int] | None`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_modules.py`:

```python
from fantaclaude.model.modules import MODULES_YML, Fit, assign, load_modules
from fantaclaude.model.roles import Role

R = frozenset


def test_the_eleven_modules_are_exactly_the_league_api_list(mcp_fixture_json):
    modules = load_modules()
    assert set(modules) == set(mcp_fixture_json("lineup_settings")["mods"])
    for module in modules.values():
        assert len(module.slots) == 11
        assert sum(1 for s in module.slots if s.natural == {Role.Por}) == 1


def test_table_header_records_source_and_date():
    text = MODULES_YML.read_text(encoding="utf-8")
    assert "Tabella-sostituzioni-per-schema-2024-2025.pdf" in text
    assert "verified_on: 2026-08-24" in text


def test_slots_transcribed_from_the_official_table():
    m = load_modules()
    labels = lambda code: [s.label for s in m[code].slots]  # noqa: E731
    assert labels("343") == ["Por", "Dc", "Dc", "Dc/B", "E", "M/C", "C", "E", "W/A", "A/Pc", "W/A"]
    assert labels("4141") == ["Por", "Ds", "Dc", "Dc", "Dd", "M", "C/T", "T", "E/W", "W", "A/Pc"]
    assert labels("4312")[9] == "T/A/Pc"
    assert m["343"].slot_counts() == {"Por": 1, "Dc": 2, "Dc/B": 1, "E": 2, "M/C": 1, "C": 1, "W/A": 2, "A/Pc": 1}


def test_adaptation_matrix_spot_checks():
    m = load_modules()
    e_slot = m["343"].slots[4]                              # the first "E"
    assert e_slot.fit(R({Role.Dd})) is Fit.ADAPTED          # "-1" in the table
    assert e_slot.fit(R({Role.M})) is Fit.FORCED_ONLY       # "-1*"
    assert e_slot.fit(R({Role.W})) is Fit.NO
    t_slot = m["4141"].slots[7]                             # the rule the regolamento singles out:
    assert t_slot.fit(R({Role.W})) is Fit.NO                # in 4-1-4-1 W cannot cover T ...
    assert m["4141"].slots[8].fit(R({Role.T})) is Fit.NO    # ... nor T cover E/W
    dcb = m["352"].slots[3]
    assert dcb.fit(R({Role.B})) is Fit.NATURAL and dcb.fit(R({Role.Dd})) is Fit.FORCED_ONLY


def test_back_three_schemes_use_b_and_back_four_schemes_do_not():
    for code, module in load_modules().items():
        if code.startswith("3"):
            assert module.slots[3].label == "Dc/B"
        else:
            assert not any(Role.B in s.natural for s in module.slots)


def test_a_multi_role_player_takes_the_best_fit_across_his_roles():
    slot = load_modules()["4231"].slots[7]                  # "W/T"
    assert slot.fit(R({Role.E, Role.T})) is Fit.NATURAL     # T natural, even though E alone is only adapted


def test_assign_fields_a_legal_eleven_and_rejects_an_illegal_one():
    m = load_modules()["343"]
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}),
              R({Role.C}), R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A})]
    result = assign(m, roster)
    assert result is not None and sorted(result) == list(range(11))
    roster[7] = R({Role.W})                                  # second E gone: no natural E left
    assert assign(m, roster) is None
    assert assign(m, roster, allow_adapted=True) is None     # W is "no" for E even adapted
    roster[7] = R({Role.Dd})                                 # Dd is adapted for E
    assert assign(m, roster) is None
    assert assign(m, roster, allow_adapted=True) is not None


def test_assign_counts_a_three_role_player_once():
    m = load_modules()["343"]
    flex = R({Role.B, Role.Ds, Role.E})
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), flex, R({Role.M}), R({Role.C}),
              R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A})]
    assert assign(m, roster) is None                         # ten players cannot fill eleven slots
    roster.append(R({Role.E}))
    result = assign(m, roster)
    assert result is not None and len(set(result)) == 11


def test_assign_finds_the_matching_a_greedy_pass_misses():
    """Hand-solved: in 3-4-1-2 the E/T player must go to T so the E-only
    players can take both E slots; a first-come assignment would park him at E."""
    m = load_modules()["3412"]
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.Dc}), R({Role.E, Role.T}),
              R({Role.E}), R({Role.M}), R({Role.C}), R({Role.Pc}), R({Role.A})]
    assert assign(m, roster) is None                         # two E slots + T from {E/T, E}: one short
    roster.append(R({Role.E}))
    result = assign(m, roster)
    assert result is not None
    t_index = next(i for i, s in enumerate(m.slots) if s.label == "T")
    assert roster[result[t_index]] == R({Role.E, Role.T})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.model.modules'`.

- [ ] **Step 3: Write the module table**

Create `core/src/fantaclaude/model/modules.yml` with exactly this content (transcribed from the official PDF; `natural` is the table's `ok`, `adapted` its `-1`, `forced_only` its `-1*`; a role absent from all three is `no`):

```yaml
# Mantra module table -- DOMAIN DATA, not API data. The league API names the
# eleven modules (settings/lineup.mods) and defines none of them.
# Source: "Tabella sostituzioni per schema 2024-2025",
#   https://content.fantacalcio.it/web/risorse/Tabella-sostituzioni-per-schema-2024-2025.pdf
#   linked from https://www.fantacalcio.it/regolamenti/sistema-mantra
# Transcribed 2026-08-24: 11 modules x 11 slots, checked by hand against the PDF.
# Per slot: natural = "ok" (no malus); adapted = "-1" (out of position, with
# the malus); forced_only = "-1*" (not allowed at lineup insertion, reachable
# only through a forced substitution, with the malus). Anything else is "no".
source: https://content.fantacalcio.it/web/risorse/Tabella-sostituzioni-per-schema-2024-2025.pdf
verified_on: 2026-08-24
modules:
  '343':
    label: 3-4-3
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc/B", natural: [Dc, B], forced_only: [Dd, Ds]}
      - {slot: "E", natural: [E], adapted: [Dd, Ds, Dc, B], forced_only: [M]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "E", natural: [E], adapted: [Dd, Ds, Dc, B], forced_only: [M]}
      - {slot: "W/A", natural: [W, A], adapted: [Dd, Ds, Dc, B, E, M, C, T]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
      - {slot: "W/A", natural: [W, A], adapted: [Dd, Ds, Dc, B, E, M, C, T]}
  '3412':
    label: 3-4-1-2
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc/B", natural: [Dc, B], forced_only: [Dd, Ds]}
      - {slot: "E", natural: [E], adapted: [Dd, Ds, Dc, B], forced_only: [M]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "E", natural: [E], adapted: [Dd, Ds, Dc, B], forced_only: [M]}
      - {slot: "T", natural: [T], adapted: [Dd, Ds, Dc, B, E, M, C], forced_only: [W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '3421':
    label: 3-4-2-1
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc/B", natural: [Dc, B], forced_only: [Dd, Ds]}
      - {slot: "E", natural: [E], adapted: [Dd, Ds, Dc, B], forced_only: [M]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C, T]}
      - {slot: "T", natural: [T], adapted: [Dd, Ds, Dc, B, E, M, C], forced_only: [W]}
      - {slot: "T/A", natural: [T, A], adapted: [Dd, Ds, Dc, B, E, M, C, W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '352':
    label: 3-5-2
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc/B", natural: [Dc, B], forced_only: [Dd, Ds]}
      - {slot: "E", natural: [E], adapted: [Dd, Ds, Dc, B], forced_only: [M]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C, T]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '3511':
    label: 3-5-1-1
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc/B", natural: [Dc, B], forced_only: [Dd, Ds]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C, T]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C, T]}
      - {slot: "T/A", natural: [T, A], adapted: [Dd, Ds, Dc, B, E, M, C, W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '433':
    label: 4-3-3
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Ds", natural: [Ds], adapted: [Dc], forced_only: [Dd, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dd", natural: [Dd], adapted: [Dc], forced_only: [Ds, B]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "W/A", natural: [W, A], adapted: [Dd, Ds, Dc, B, E, M, C, T]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
      - {slot: "W/A", natural: [W, A], adapted: [Dd, Ds, Dc, B, E, M, C, T]}
  '4312':
    label: 4-3-1-2
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Ds", natural: [Ds], adapted: [Dc], forced_only: [Dd, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dd", natural: [Dd], adapted: [Dc], forced_only: [Ds, B]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "T", natural: [T], adapted: [Dd, Ds, Dc, B, E, M, C], forced_only: [W]}
      - {slot: "T/A/Pc", natural: [T, A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '442':
    label: 4-4-2
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Ds", natural: [Ds], adapted: [Dc], forced_only: [Dd, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dd", natural: [Dd], adapted: [Dc], forced_only: [Ds, B]}
      - {slot: "E", natural: [E], adapted: [Dd, Ds, Dc, B], forced_only: [M]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C, T]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '4411':
    label: 4-4-1-1
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Ds", natural: [Ds], adapted: [Dc], forced_only: [Dd, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dd", natural: [Dd], adapted: [Dc], forced_only: [Ds, B]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C, T]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "C", natural: [C], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C, T]}
      - {slot: "T/A", natural: [T, A], adapted: [Dd, Ds, Dc, B, E, M, C, W]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '4231':
    label: 4-2-3-1
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Ds", natural: [Ds], adapted: [Dc], forced_only: [Dd, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dd", natural: [Dd], adapted: [Dc], forced_only: [Ds, B]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "M/C", natural: [M, C], adapted: [Dd, Ds, Dc, B, E]}
      - {slot: "W/T", natural: [T, W], adapted: [Dd, Ds, Dc, B, E, M, C]}
      - {slot: "T", natural: [T], adapted: [Dd, Ds, Dc, B, E, M, C], forced_only: [W]}
      - {slot: "W/A", natural: [W, A], adapted: [Dd, Ds, Dc, B, E, M, C, T]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
  '4141':
    label: 4-1-4-1
    slots:
      - {slot: "Por", natural: [Por]}
      - {slot: "Ds", natural: [Ds], adapted: [Dc], forced_only: [Dd, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dc", natural: [Dc], forced_only: [Dd, Ds, B]}
      - {slot: "Dd", natural: [Dd], adapted: [Dc], forced_only: [Ds, B]}
      - {slot: "M", natural: [M], adapted: [Dd, Ds, Dc, B], forced_only: [E]}
      - {slot: "C/T", natural: [C, T], adapted: [Dd, Ds, Dc, B, E, M]}
      - {slot: "T", natural: [T], adapted: [Dd, Ds, Dc, B, E, M, C]}
      - {slot: "E/W", natural: [E, W], adapted: [Dd, Ds, Dc, B, M, C]}
      - {slot: "W", natural: [W], adapted: [Dd, Ds, Dc, B, E, M, C]}
      - {slot: "A/Pc", natural: [A, Pc], adapted: [Dd, Ds, Dc, B, E, M, C, T, W]}
```

- [ ] **Step 4: Write the loader and the matcher**

Create `core/src/fantaclaude/model/modules.py`:

```python
"""The eleven Mantra modules as slot lists, and exact feasibility matching.

modules.yml is domain data transcribed from the official table (see its
header); nothing here infers a slot from the API. `assign` answers "can this
roster field this module?" exactly, by bipartite matching -- the question the
valuation and the auction advisor ask, and one that eyeballing gets wrong for
multi-role players.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

import yaml

from .roles import Role

MODULES_YML = Path(__file__).with_name("modules.yml")


class Fit(Enum):
    NATURAL = "natural"        # "ok" in the table: no malus
    ADAPTED = "adapted"        # "-1": out of position, with the malus
    FORCED_ONLY = "forced"     # "-1*": only through a forced substitution
    NO = "no"


@dataclass(frozen=True)
class Slot:
    label: str
    natural: frozenset[Role]
    adapted: frozenset[Role]
    forced_only: frozenset[Role]

    def fit(self, roles: frozenset[Role]) -> Fit:
        """The best fit any of a player's roles gives for this slot."""
        if roles & self.natural:
            return Fit.NATURAL
        if roles & self.adapted:
            return Fit.ADAPTED
        if roles & self.forced_only:
            return Fit.FORCED_ONLY
        return Fit.NO


@dataclass(frozen=True)
class Module:
    code: str            # "343" -- the key settings/lineup.mods uses
    label: str           # "3-4-3"
    slots: tuple[Slot, ...]

    def slot_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for slot in self.slots:
            counts[slot.label] = counts.get(slot.label, 0) + 1
        return counts


class ModuleTableError(ValueError):
    """modules.yml does not describe a legal Mantra module table."""


def _roles(names: list[str] | None) -> frozenset[Role]:
    return frozenset(Role(n) for n in (names or []))


@cache
def load_modules(path: Path = MODULES_YML) -> dict[str, Module]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_modules = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(raw_modules, dict):
        raise ModuleTableError(f"{path}: expected a top-level 'modules' mapping")
    modules: dict[str, Module] = {}
    for code, entry in raw_modules.items():
        slots = tuple(
            Slot(label=str(s["slot"]), natural=_roles(s.get("natural")),
                 adapted=_roles(s.get("adapted")), forced_only=_roles(s.get("forced_only")))
            for s in entry["slots"]
        )
        module = Module(code=str(code), label=str(entry["label"]), slots=slots)
        _validate(module)
        modules[module.code] = module
    if len(modules) != 11:
        raise ModuleTableError(f"{path}: expected 11 modules, found {len(modules)}")
    return modules


def _validate(module: Module) -> None:
    if len(module.slots) != 11:
        raise ModuleTableError(f"{module.label}: {len(module.slots)} slots, expected 11")
    if sum(1 for s in module.slots if s.natural == {Role.Por}) != 1:
        raise ModuleTableError(f"{module.label}: exactly one Por slot expected")
    for slot in module.slots:
        if set(slot.label.split("/")) != {r.value for r in slot.natural}:
            raise ModuleTableError(
                f"{module.label}: slot {slot.label!r} natural roles do not match its label")
        if (slot.natural & slot.adapted or slot.natural & slot.forced_only
                or slot.adapted & slot.forced_only):
            raise ModuleTableError(f"{module.label}: slot {slot.label!r} lists a role under two fits")


def assign(module: Module, roster: Sequence[frozenset[Role]], *,
           allow_adapted: bool = False) -> list[int] | None:
    """Match players to slots: per slot, the index into `roster` of the
    player fielded there, or None if the roster cannot field the module.

    Natural fits only, unless `allow_adapted`, which also accepts ADAPTED --
    never FORCED_ONLY, which is not legal at lineup insertion. Exact:
    augmenting-path bipartite matching over eleven slots, so a roster of
    forty multi-role players is answered in microseconds and never by
    guesswork.
    """
    accepted = {Fit.NATURAL, Fit.ADAPTED} if allow_adapted else {Fit.NATURAL}
    candidates = [[i for i, roles in enumerate(roster) if slot.fit(roles) in accepted]
                  for slot in module.slots]
    owner: dict[int, int] = {}          # player index -> slot index

    def try_slot(slot_index: int, seen: set[int]) -> bool:
        for player in candidates[slot_index]:
            if player in seen:
                continue
            seen.add(player)
            if player not in owner or try_slot(owner[player], seen):
                owner[player] = slot_index
                return True
        return False

    for slot_index in range(len(module.slots)):
        if not try_slot(slot_index, set()):
            return None
    result = [-1] * len(module.slots)
    for player, slot_index in owner.items():
        result[slot_index] = player
    return result
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `22 passed`.

- [ ] **Step 6: Hand-check the transcription against the PDF**

Download the table and compare three modules by eye — this is domain data and the test can only check what the transcriber also typed:

```bash
curl -sL -o /tmp/schemi.pdf 'https://content.fantacalcio.it/web/risorse/Tabella-sostituzioni-per-schema-2024-2025.pdf'
uv run --with pdfplumber python -c "
import pdfplumber
with pdfplumber.open('/tmp/schemi.pdf') as pdf:
    for page in pdf.pages: print(page.extract_text())" | grep -A11 -E '^(3-4-2-1|4-1-4-1|4-2-3-1) '
```

Expected: for each of the three modules the eleven row labels and their `ok`/`-1`/`-1*`/`no` cells agree with the corresponding `modules.yml` entries (`3421`, `4141`, `4231`). If any cell disagrees, fix `modules.yml`, not the test.

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/model/modules.yml core/src/fantaclaude/model/modules.py core/tests/test_modules.py
git commit -m "feat(model): official Mantra module table and exact slot matching"
```

---

### Task 6: DuckDB connection and the Phase 0a schema

**Files:**
- Create: `core/src/fantaclaude/db/__init__.py`, `core/src/fantaclaude/db/connection.py`, `core/src/fantaclaude/db/schema.py`, `core/src/fantaclaude/timeutil.py`
- Modify: `core/tests/conftest.py` (add the `db` fixture)
- Test: `core/tests/test_schema.py`, `core/tests/test_timeutil.py`

**Interfaces:**
- Consumes: `fantaclaude.paths.db_path()`.
- Produces: `DatabaseMissing(FileNotFoundError)`; `connect(path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection`; `SCHEMA_VERSION = 1`; `SchemaVersionMismatch(RuntimeError)`; `apply_schema(con) -> int`; `ColumnInfo(name, type)`, `TableInfo(name, kind, columns, rows)`, `SchemaReport(version, tables)` with `to_dict()`; `schema_report(con) -> SchemaReport`; pytest fixture `db` (a temp read-write connection with the schema applied); `fantaclaude.timeutil.utc_now() -> datetime` (aware) and `to_db(dt: datetime) -> datetime` (naive UTC — DuckDB converts an aware datetime to *local* time before storing it, so every TIMESTAMP insert goes through `to_db`). Tables: `schema_version`, `league_settings`, `listone_snapshots`, `players`, `teams`, `player_aliases`; views: `v_league_settings_current`, `v_players_current`, `v_teams_current`.

- [ ] **Step 1: Write the failing tests**

Append to `core/tests/conftest.py`:

```python
@pytest.fixture
def db(tmp_path):
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "test.duckdb")
    apply_schema(con)
    yield con
    con.close()
```

Create `core/tests/test_schema.py`:

```python
import duckdb
import pytest

from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.db.schema import SCHEMA_VERSION, apply_schema, schema_report


def test_apply_schema_is_idempotent(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    assert apply_schema(con) == SCHEMA_VERSION
    assert apply_schema(con) == SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
    con.close()


def test_schema_report_lists_tables_and_views(db):
    report = schema_report(db)
    kinds = {t.name: t.kind for t in report.tables}
    assert kinds["players"] == "table" and kinds["v_players_current"] == "view"
    assert {"league_settings", "listone_snapshots", "teams", "player_aliases",
            "v_league_settings_current", "v_teams_current"} <= set(kinds)
    players = next(t for t in report.tables if t.name == "players")
    assert [c.name for c in players.columns][:3] == ["snapshot_id", "player_id", "name"]
    assert players.rows == 0
    assert report.version == SCHEMA_VERSION
    assert report.to_dict()["version"] == SCHEMA_VERSION


def test_read_only_connection_requires_an_existing_file(tmp_path):
    with pytest.raises(DatabaseMissing):
        connect(tmp_path / "missing.duckdb", read_only=True)


def test_read_only_connection_rejects_writes(tmp_path):
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    con.close()                      # one mode per process: close before reopening read-only
    ro = connect(path, read_only=True)
    with pytest.raises(duckdb.Error):
        ro.execute("INSERT INTO teams VALUES (1, 1, 'x', 'X')")
    ro.close()


def test_write_connection_creates_the_parent_directory(tmp_path):
    con = connect(tmp_path / "nested" / "x.duckdb")
    con.close()
    assert (tmp_path / "nested" / "x.duckdb").is_file()
```

Create `core/tests/test_timeutil.py`:

```python
from datetime import UTC, datetime, timedelta, timezone

from fantaclaude.timeutil import to_db, utc_now


def test_to_db_normalises_to_naive_utc():
    rome = timezone(timedelta(hours=2))
    assert to_db(datetime(2026, 8, 24, 12, 0, tzinfo=rome)) == datetime(2026, 8, 24, 10, 0)
    assert to_db(datetime(2026, 8, 24, 10, 0, tzinfo=UTC)) == datetime(2026, 8, 24, 10, 0)
    assert to_db(datetime(2026, 8, 24, 10, 0)) == datetime(2026, 8, 24, 10, 0)   # naive is taken as UTC


def test_utc_now_is_aware():
    assert utc_now().tzinfo is UTC
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.db'` (and `fantaclaude.timeutil`).

- [ ] **Step 3: Write the connection module**

Create `core/src/fantaclaude/db/__init__.py` (empty) and `core/src/fantaclaude/db/connection.py`:

```python
"""One place that opens fanta.duckdb.

DuckDB is single-process for writes, and inside one process every connection
to a file must share its configuration -- a read-only and a read-write handle
cannot coexist. So `query` opens read-only, `sync-league` and `ingest` open
read-write, and they are different processes: the spec's concurrency model.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from fantaclaude.paths import db_path


class DatabaseMissing(FileNotFoundError):
    """Nothing has been ingested yet: the database file does not exist."""


def connect(path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = path or db_path()
    if read_only:
        if not path.is_file():
            raise DatabaseMissing(str(path))
        return duckdb.connect(str(path), read_only=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))
```

- [ ] **Step 4: Write the time helper and the schema module**

Create `core/src/fantaclaude/timeutil.py`:

```python
"""Timestamps: aware UTC in Python, naive UTC in DuckDB.

DuckDB's TIMESTAMP has no zone, and binding an aware datetime converts it to
the machine's local time first -- an auction-night laptop in Rome would store
10:00Z as 12:00. Everything that lands in a TIMESTAMP column passes through
to_db() so the stored value is always UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_db(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)
```

Create `core/src/fantaclaude/db/schema.py`:

```python
"""The analytical spine's DDL, applied idempotently.

Snapshot tables, never overwrites: league_settings appends one row per
observed rule change, listone_snapshots/players append one snapshot per
ingest, and the v_*_current views pick the latest. Raw payloads travel in a
JSON column so a field the models do not name is still there to query.
Later phases add their tables here and bump SCHEMA_VERSION.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import duckdb

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE SEQUENCE IF NOT EXISTS seq_league_settings START 1;
CREATE TABLE IF NOT EXISTS league_settings (
    snapshot_id   INTEGER PRIMARY KEY DEFAULT nextval('seq_league_settings'),
    fetched_at    TIMESTAMP NOT NULL,
    league_id     INTEGER NOT NULL,
    season_id     INTEGER,
    matchday      INTEGER,
    rules_hash    VARCHAR NOT NULL,
    team_count    INTEGER,
    budget        INTEGER,
    roster_min    INTEGER,
    roster_max    INTEGER,
    modules       VARCHAR[],
    bench_size    INTEGER,
    substitutions INTEGER,
    payload       JSON NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS seq_listone_snapshots START 1;
CREATE TABLE IF NOT EXISTS listone_snapshots (
    snapshot_id  INTEGER PRIMARY KEY DEFAULT nextval('seq_listone_snapshots'),
    fetched_at   TIMESTAMP NOT NULL,
    source       VARCHAR NOT NULL,
    raw_path     VARCHAR NOT NULL,
    sha256       VARCHAR NOT NULL UNIQUE,
    player_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    snapshot_id          INTEGER NOT NULL,
    player_id            INTEGER NOT NULL,
    name                 VARCHAR NOT NULL,
    team_id              INTEGER,
    team_name            VARCHAR,
    team_short           VARCHAR,
    classic_role         VARCHAR NOT NULL,
    mantra_roles         VARCHAR[] NOT NULL,
    mantra_role_codes    INTEGER[] NOT NULL,
    quot_initial_classic INTEGER,
    quot_current_classic INTEGER,
    quot_initial_mantra  INTEGER,
    quot_current_mantra  INTEGER,
    fvm_classic          INTEGER,
    fvm_mantra           INTEGER,
    age                  INTEGER,
    nationality          VARCHAR,
    transfer_flag        BOOLEAN NOT NULL,
    raw                  JSON NOT NULL,
    PRIMARY KEY (snapshot_id, player_id)
);
CREATE TABLE IF NOT EXISTS teams (
    snapshot_id INTEGER NOT NULL,
    team_id     INTEGER NOT NULL,
    name        VARCHAR NOT NULL,
    short       VARCHAR,
    PRIMARY KEY (snapshot_id, team_id)
);
CREATE TABLE IF NOT EXISTS player_aliases (
    alias     VARCHAR NOT NULL,
    source    VARCHAR NOT NULL,
    player_id INTEGER NOT NULL,
    PRIMARY KEY (alias, source)
);
CREATE OR REPLACE VIEW v_league_settings_current AS
    SELECT * FROM league_settings ORDER BY snapshot_id DESC LIMIT 1;
CREATE OR REPLACE VIEW v_players_current AS
    SELECT p.* FROM players p
    WHERE p.snapshot_id = (SELECT max(snapshot_id) FROM listone_snapshots);
CREATE OR REPLACE VIEW v_teams_current AS
    SELECT t.* FROM teams t
    WHERE t.snapshot_id = (SELECT max(snapshot_id) FROM listone_snapshots);
"""


class SchemaVersionMismatch(RuntimeError):
    """The file was written by a different schema version; migrate before use."""


def apply_schema(con: duckdb.DuckDBPyConnection) -> int:
    for statement in DDL.split(";"):
        if statement.strip():
            con.execute(statement)
    stored = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    if stored is None:
        con.execute("INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION])
    elif stored != SCHEMA_VERSION:
        raise SchemaVersionMismatch(f"database is at schema {stored}, code expects {SCHEMA_VERSION}")
    return SCHEMA_VERSION


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    kind: str                       # "table" | "view"
    columns: list[ColumnInfo]
    rows: int | None


@dataclass(frozen=True)
class SchemaReport:
    version: int | None
    tables: list[TableInfo]

    def to_dict(self) -> dict:
        return {"version": self.version, "tables": [asdict(t) for t in self.tables]}


def schema_report(con: duckdb.DuckDBPyConnection) -> SchemaReport:
    try:
        version = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    except duckdb.Error:
        version = None
    names = con.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name").fetchall()
    tables: list[TableInfo] = []
    for name, table_type in names:
        columns = [ColumnInfo(row[0], row[1]) for row in con.execute(f'DESCRIBE "{name}"').fetchall()]
        rows = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        tables.append(TableInfo(name, "view" if table_type == "VIEW" else "table", columns, rows))
    return SchemaReport(version, tables)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `29 passed`.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/db core/src/fantaclaude/timeutil.py core/tests/conftest.py core/tests/test_schema.py core/tests/test_timeutil.py
git commit -m "feat(db): DuckDB connection and the snapshot schema"
```

---

### Task 7: `league_settings` snapshots with a rules hash

**Files:**
- Create: `core/src/fantaclaude/league/__init__.py`, `core/src/fantaclaude/league/settings.py`
- Test: `core/tests/test_league_settings.py`

**Interfaces:**
- Consumes: `fantacalcio_mcp.models.{League, LeagueStatus, LeagueSettings}`; the `db` fixture; MCP fixtures `league_profile`, `league_status`, `roster_settings`, `lineup_settings`, `calculation_settings`, `teams`.
- Produces: `LeagueSnapshot` (frozen dataclass: `league_id, season_id, matchday, team_count, budget, roster_min, roster_max, modules: tuple[str, ...], bench_size, substitutions, rules_hash: str, payload: dict`); `rules_hash(rosters, lineup, calculate, team_count) -> str` (16 hex chars); `snapshot_from_payloads(*, profile, status, rosters, lineup, calculate, teams) -> LeagueSnapshot`; `Change(path, before, after)`; `diff_rules(old_payload, old_team_count, new: LeagueSnapshot) -> list[Change]`; `StoredSnapshot(snapshot_id, fetched_at, rules_hash, team_count, payload)`; `latest_snapshot(con) -> StoredSnapshot | None`; `SyncResult(changed, snapshot_id, rules_hash, previous_hash, diff)`; `record_snapshot(con, snap, *, fetched_at=None) -> SyncResult`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_league_settings.py`:

```python
import json
from datetime import UTC, datetime

import pytest

from fantaclaude.league.settings import (
    Change, latest_snapshot, record_snapshot, rules_hash, snapshot_from_payloads,
)


@pytest.fixture
def payloads(mcp_fixture_json):
    return dict(
        profile=mcp_fixture_json("league_profile"),
        status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"),
        lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"),
        teams=mcp_fixture_json("teams"),
    )


def test_snapshot_decodes_the_confirmed_fields(payloads):
    snap = snapshot_from_payloads(**payloads)
    assert snap.league_id == 2578630 and snap.budget == 500
    assert (snap.roster_min, snap.roster_max) == (23, 40)
    assert len(snap.modules) == 11 and snap.bench_size == 12 and snap.substitutions == 5
    assert snap.team_count == 8
    assert len(snap.rules_hash) == 16
    assert "parola" not in snap.payload["profile"]
    assert set(snap.payload) == {"profile", "status", "rosters", "lineup", "calculate", "teams"}


def test_rules_hash_ignores_volatile_fields_and_sees_rule_changes(payloads):
    base = rules_hash(payloads["rosters"], payloads["lineup"], payloads["calculate"], 8)
    bumped = dict(payloads["rosters"], count=99, version="v3")
    assert rules_hash(bumped, payloads["lineup"], payloads["calculate"], 8) == base
    richer = dict(payloads["rosters"], budg=1000)
    assert rules_hash(richer, payloads["lineup"], payloads["calculate"], 8) != base
    assert rules_hash(payloads["rosters"], payloads["lineup"], payloads["calculate"], 10) != base


def test_record_snapshot_appends_only_on_change(db, payloads):
    snap = snapshot_from_payloads(**payloads)
    first = record_snapshot(db, snap, fetched_at=datetime(2026, 8, 24, tzinfo=UTC))
    assert first.changed and first.snapshot_id == 1 and first.previous_hash is None
    again = record_snapshot(db, snap)
    assert not again.changed and again.snapshot_id == 1 and again.diff == []
    changed = snapshot_from_payloads(**{**payloads, "rosters": dict(payloads["rosters"], budg=1000)})
    second = record_snapshot(db, changed)
    assert second.changed and second.snapshot_id == 2 and second.previous_hash == first.rules_hash
    assert Change("rosters.budg", 500, 1000) in second.diff
    assert db.execute("SELECT count(*) FROM league_settings").fetchone()[0] == 2
    assert latest_snapshot(db).snapshot_id == 2
    assert db.execute("SELECT budget FROM v_league_settings_current").fetchone()[0] == 1000
    stored = db.execute("SELECT fetched_at FROM league_settings WHERE snapshot_id = 1").fetchone()[0]
    assert stored == datetime(2026, 8, 24)          # naive UTC, whatever the machine's zone


def test_team_count_change_is_a_rule_change(db, payloads):
    record_snapshot(db, snapshot_from_payloads(**payloads))
    profile = json.loads(json.dumps(payloads["profile"]))
    profile["lega"]["n_s"] = 10
    result = record_snapshot(db, snapshot_from_payloads(**{**payloads, "profile": profile}))
    assert result.changed and Change("team_count", 8, 10) in result.diff


def test_team_payload_never_carries_an_email(payloads):
    teams = {"data": [{"id": 1, "n": "x", "all": [{"id": 2, "n": "y", "email": "someone@example.it"}]}],
             "divisions": []}
    snap = snapshot_from_payloads(**{**payloads, "teams": teams})
    assert "@" not in json.dumps(snap.payload["teams"])
    assert snap.payload["teams"]["data"][0]["all"][0] == {"id": 2, "n": "y"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.league'`.

- [ ] **Step 3: Write the module**

Create `core/src/fantaclaude/league/__init__.py` (empty) and `core/src/fantaclaude/league/settings.py`:

```python
"""league_settings: an append-only snapshot of the rules in force.

Every valuation depends on the rules -- money supply, roster bounds, scoring
-- so a rule change is history, not a lost fact. One row per observed change,
keyed by rules_hash; the full payloads travel in a JSON column, decoded by the
MCP's own models so nothing is renamed twice.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb
from fantacalcio_mcp.models import League, LeagueSettings, LeagueStatus

from fantaclaude.timeutil import to_db, utc_now

# Server-side bookkeeping that changes without any rule changing.
VOLATILE_KEYS = frozenset({"count", "version"})


@dataclass(frozen=True)
class LeagueSnapshot:
    league_id: int
    season_id: int | None
    matchday: int | None
    team_count: int | None
    budget: int | None
    roster_min: int | None
    roster_max: int | None
    modules: tuple[str, ...]
    bench_size: int | None
    substitutions: int | None
    rules_hash: str
    payload: dict[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _rules_view(rosters: dict, lineup: dict, calculate: dict, team_count: int | None) -> dict:
    strip = lambda d: {k: v for k, v in d.items() if k not in VOLATILE_KEYS}  # noqa: E731
    return {"rosters": strip(rosters), "lineup": strip(lineup),
            "calculate": strip(calculate), "team_count": team_count}


def rules_hash(rosters: dict, lineup: dict, calculate: dict, team_count: int | None) -> str:
    """Sixteen hex characters over everything a valuation depends on: the
    three settings payloads (minus volatile bookkeeping) and the team count,
    which sets the money supply."""
    view = _rules_view(rosters, lineup, calculate, team_count)
    return hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()[:16]


def _is_email_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalised = "".join(ch for ch in key.lower() if ch.isalnum())
    return "email" in normalised or normalised in {"mail", "mails"}


def _without_emails(value: Any) -> Any:
    """Drop every email-bearing key at any depth -- the MCP's rule, applied
    before a team payload is stored."""
    if isinstance(value, dict):
        return {k: _without_emails(v) for k, v in value.items() if not _is_email_key(k)}
    if isinstance(value, list):
        return [_without_emails(item) for item in value]
    return value


def snapshot_from_payloads(*, profile: dict, status: dict, rosters: dict, lineup: dict,
                           calculate: dict, teams: Any) -> LeagueSnapshot:
    league = League.from_api(profile)            # pops the join password
    league_status = LeagueStatus.from_api(status)
    settings = LeagueSettings.from_api(rosters=rosters, lineup=lineup, calculate=calculate)
    team_rows = teams.get("data") if isinstance(teams, dict) else teams
    team_count = league.team_count
    if team_count is None and team_rows is not None:
        team_count = len(team_rows)
    return LeagueSnapshot(
        league_id=league.league_id,
        season_id=league_status.season_id,
        matchday=league_status.matchday,
        team_count=team_count,
        budget=settings.budget,
        roster_min=settings.roster_min,
        roster_max=settings.roster_max,
        modules=tuple(settings.modules),
        bench_size=settings.bench_size,
        substitutions=settings.substitutions,
        rules_hash=rules_hash(rosters, lineup, calculate, team_count),
        payload={"profile": league.raw, "status": league_status.raw, "rosters": rosters,
                 "lineup": lineup, "calculate": calculate, "teams": _without_emails(teams)},
    )


@dataclass(frozen=True)
class Change:
    path: str
    before: Any
    after: Any


def diff_payloads(old: Any, new: Any, prefix: str = "") -> list[Change]:
    """Recursive over mappings; lists and scalars compare as a whole. Paths
    are dotted, keys in sorted order, so a report is stable run to run."""
    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[Change] = []
        for key in sorted(set(old) | set(new), key=str):
            path = f"{prefix}.{key}" if prefix else str(key)
            changes.extend(diff_payloads(old.get(key), new.get(key), path))
        return changes
    return [] if old == new else [Change(prefix, old, new)]


def diff_rules(old_payload: dict, old_team_count: int | None, new: LeagueSnapshot) -> list[Change]:
    before = _rules_view(old_payload["rosters"], old_payload["lineup"], old_payload["calculate"], old_team_count)
    after = _rules_view(new.payload["rosters"], new.payload["lineup"], new.payload["calculate"], new.team_count)
    return diff_payloads(before, after)


@dataclass(frozen=True)
class StoredSnapshot:
    snapshot_id: int
    fetched_at: datetime
    rules_hash: str
    team_count: int | None
    payload: dict[str, Any]


def latest_snapshot(con: duckdb.DuckDBPyConnection) -> StoredSnapshot | None:
    row = con.execute(
        "SELECT snapshot_id, fetched_at, rules_hash, team_count, payload "
        "FROM league_settings ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    payload = row[4] if isinstance(row[4], dict) else json.loads(row[4])
    return StoredSnapshot(row[0], row[1], row[2], row[3], payload)


@dataclass(frozen=True)
class SyncResult:
    changed: bool
    snapshot_id: int | None
    rules_hash: str
    previous_hash: str | None
    diff: list[Change] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"changed": self.changed, "snapshot_id": self.snapshot_id,
                "rules_hash": self.rules_hash, "previous_hash": self.previous_hash,
                "diff": [{"path": c.path, "before": c.before, "after": c.after} for c in self.diff]}


def record_snapshot(con: duckdb.DuckDBPyConnection, snap: LeagueSnapshot, *,
                    fetched_at: datetime | None = None) -> SyncResult:
    """Append a row only when the rules hash moved. The first row is always
    a change; an identical hash is reported, not stored."""
    previous = latest_snapshot(con)
    if previous is not None and previous.rules_hash == snap.rules_hash:
        return SyncResult(False, previous.snapshot_id, snap.rules_hash, previous.rules_hash)
    diff = diff_rules(previous.payload, previous.team_count, snap) if previous is not None else []
    row = con.execute(
        "INSERT INTO league_settings (fetched_at, league_id, season_id, matchday, rules_hash, "
        "team_count, budget, roster_min, roster_max, modules, bench_size, substitutions, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON) RETURNING snapshot_id",
        [to_db(fetched_at or utc_now()), snap.league_id, snap.season_id, snap.matchday,
         snap.rules_hash, snap.team_count, snap.budget, snap.roster_min, snap.roster_max,
         list(snap.modules), snap.bench_size, snap.substitutions, canonical_json(snap.payload)],
    ).fetchone()
    return SyncResult(True, row[0], snap.rules_hash,
                      previous.rules_hash if previous is not None else None, diff)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `34 passed`. If DuckDB rejects the `payload` parameter, it is because the JSON column was handed a `dict` rather than the canonical string — `canonical_json(snap.payload)` is what the insert must receive.

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/league core/tests/test_league_settings.py
git commit -m "feat(league): append-only league_settings snapshots keyed by rules hash"
```

---

### Task 8: `league.yml`, `preferences.yml`, and the provenance cross-check

**Files:**
- Create: `league.yml`, `preferences.yml` (workspace root)
- Create: `core/src/fantaclaude/league/league_yml.py`
- Test: `core/tests/test_league_yml.py`

**Interfaces:**
- Consumes: `LeagueSnapshot` (Task 7); `fantaclaude.paths.{league_yml_path, preferences_yml_path}`.
- Produces: `LeagueYmlError(ValueError)`; `Provenanced(key, value, source, verified_on: date, note=None)`; `load_league_yml(path: Path) -> dict[str, Provenanced]` (dotted keys); `COMPARABLE: dict[str, Callable[[LeagueSnapshot], Any]]`; `Conflict(key, league_yml, api)`; `cross_check(entries, snapshot) -> list[Conflict]`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_league_yml.py`:

```python
from datetime import date

import pytest
import yaml

from fantaclaude.league.league_yml import (
    Conflict, LeagueYmlError, Provenanced, cross_check, load_league_yml,
)
from fantaclaude.league.settings import snapshot_from_payloads
from fantaclaude.paths import league_yml_path, preferences_yml_path

GOOD = """
auction:
  platform: {value: FantaAstaLive, source: admin, verified_on: 2026-08-23}
roster:
  min_goalkeepers: {value: 2, source: admin, verified_on: 2026-08-24, note: "verbal"}
participants: {}
"""


def test_loads_provenanced_leaves_with_dotted_keys(tmp_path):
    path = tmp_path / "league.yml"
    path.write_text(GOOD)
    entries = load_league_yml(path)
    assert entries["auction.platform"] == Provenanced(
        "auction.platform", "FantaAstaLive", "admin", date(2026, 8, 23))
    assert entries["roster.min_goalkeepers"].note == "verbal"
    assert "participants" not in entries          # an empty mapping is allowed, it holds nothing


@pytest.mark.parametrize("bad", [
    "auction: {platform: FantaAstaLive}",                                   # bare value
    "x: {value: 1, source: admin}",                                          # no verified_on
    "x: {value: 1, source: admin, verified_on: soon}",                       # not a date
    "x: {value: 1, source: '', verified_on: 2026-08-24}",                    # empty source
    "x: {value: 1, source: admin, verified_on: 2026-08-24, extra: 1}",       # unknown key
    "- just\n- a list",                                                      # not a mapping
])
def test_missing_or_malformed_provenance_fails_loud(tmp_path, bad):
    path = tmp_path / "league.yml"
    path.write_text(bad)
    with pytest.raises(LeagueYmlError):
        load_league_yml(path)


def test_cross_check_flags_only_disagreements(mcp_fixture_json, tmp_path):
    snap = snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams"))
    path = tmp_path / "league.yml"
    path.write_text(
        "budget: {value: 500, source: admin, verified_on: 2026-08-24}\n"
        "roster:\n  min_goalkeepers: {value: 3, source: admin, verified_on: 2026-08-24}\n"
        "auction:\n  mode: {value: draft, source: admin, verified_on: 2026-08-24}\n")
    assert cross_check(load_league_yml(path), snap) == [Conflict("roster.min_goalkeepers", 3, 2)]


def test_the_committed_files_load():
    entries = load_league_yml(league_yml_path())
    assert entries["auction.platform"].value == "FantaAstaLive"
    assert entries["roster.min_goalkeepers"].value == 2
    assert all(e.source and e.verified_on for e in entries.values())
    prefs = yaml.safe_load(preferences_yml_path().read_text(encoding="utf-8"))
    assert isinstance(prefs, dict) and "target_composition" in prefs
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.league.league_yml'`.

- [ ] **Step 3: Write the two root files**

Create `league.yml`:

```yaml
# league.yml -- only what the league API cannot express. Never override what
# it can: a key that duplicates an API value must agree with it, or
# `fantaclaude sync-league` fails loud (exit 4). Every leaf carries
# value / source / verified_on (an ISO date); `note` is optional.
auction:
  platform:
    value: FantaAstaLive
    source: admin
    verified_on: 2026-08-23
  mode:
    value: unknown        # draft | rilanci -- ask the admin when asking for the session code
    source: admin
    verified_on: 2026-08-24
    note: FantaAstaLive offers DRAFT and A RILANCI; the admin has not said which
  date:
    value: 2026-09-05
    source: admin
    verified_on: 2026-08-22
    note: approximate
roster:
  min_goalkeepers:
    value: 2
    source: admin
    verified_on: 2026-08-24
    note: stated verbally; equals the API's minrl[0], and the cross-check keeps it that way
# nick -> participant dossier, filled by `fanta-kb interview` (Phase 1)
participants: {}
```

Create `preferences.yml`:

```yaml
# preferences.yml -- the user's computation-affecting choices. Versioned in
# git because they feed model_hash: a preference that changes a number cannot
# live somewhere unversioned. Read by Phase 1 (valuation); Phase 0a only
# checks that it parses.
risk_appetite: balanced              # cautious | balanced | aggressive
max_budget_share_per_role: {}        # e.g. {Pc: 0.35}
excluded_clubs: []
target_composition:                  # a starting point the optimiser may depart from
  Por: 2
```

- [ ] **Step 4: Write the loader and the cross-check**

Create `core/src/fantaclaude/league/league_yml.py`:

```python
"""league.yml: what the API cannot express, with provenance on every leaf.

A leaf is a mapping {value, source, verified_on[, note]}; keys flatten with
dots ("auction.mode"). Where a key duplicates something the API reports, the
two must agree -- sync-league fails loud rather than picking a winner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .settings import LeagueSnapshot

LEAF_KEYS = frozenset({"value", "source", "verified_on"})
OPTIONAL_KEYS = frozenset({"note"})


class LeagueYmlError(ValueError):
    """league.yml is malformed or a leaf lacks provenance."""


@dataclass(frozen=True)
class Provenanced:
    key: str
    value: Any
    source: str
    verified_on: date
    note: str | None = None


def load_league_yml(path: Path) -> dict[str, Provenanced]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise LeagueYmlError(f"{path}: the top level must be a mapping")
    entries: dict[str, Provenanced] = {}

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict) and LEAF_KEYS <= set(node):
            extra = set(node) - LEAF_KEYS - OPTIONAL_KEYS
            if extra:
                raise LeagueYmlError(f"{path}: {prefix}: unexpected keys {sorted(extra)}")
            if not isinstance(node["verified_on"], date):
                raise LeagueYmlError(f"{path}: {prefix}: verified_on must be an ISO date")
            if not node["source"]:
                raise LeagueYmlError(f"{path}: {prefix}: source must not be empty")
            entries[prefix] = Provenanced(prefix, node["value"], str(node["source"]),
                                          node["verified_on"], node.get("note"))
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{prefix}.{key}" if prefix else str(key))
        else:
            raise LeagueYmlError(f"{path}: {prefix}: every leaf needs value/source/verified_on")

    walk(data, "")
    return entries


# league.yml key -> the value the API reports for it. `minrl`/`maxrl` are read
# as [goalkeepers, outfield]: the design spec's reading of `sroles: 2`
# (2+21 = msltc, 6+34 = xsltc). This cross-check is what would catch that
# reading being wrong.
COMPARABLE: dict[str, Callable[[LeagueSnapshot], Any]] = {
    "budget": lambda s: s.budget,
    "team_count": lambda s: s.team_count,
    "roster.min_size": lambda s: s.roster_min,
    "roster.max_size": lambda s: s.roster_max,
    "roster.min_goalkeepers": lambda s: (s.payload["rosters"].get("minrl") or [None])[0],
    "roster.max_goalkeepers": lambda s: (s.payload["rosters"].get("maxrl") or [None])[0],
}


@dataclass(frozen=True)
class Conflict:
    key: str
    league_yml: Any
    api: Any


def cross_check(entries: dict[str, Provenanced], snapshot: LeagueSnapshot) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for key in sorted(entries):
        reader = COMPARABLE.get(key)
        if reader is None:
            continue
        api_value = reader(snapshot)
        if api_value is not None and entries[key].value != api_value:
            conflicts.append(Conflict(key, entries[key].value, api_value))
    return conflicts
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `43 passed`.

- [ ] **Step 6: Commit**

```bash
git add league.yml preferences.yml core/src/fantaclaude/league/league_yml.py core/tests/test_league_yml.py
git commit -m "feat(league): provenanced league.yml with an API cross-check; preferences scaffold"
```

---

### Task 9: The API client bridge and `fantaclaude sync-league`

**Files:**
- Create: `core/src/fantaclaude/api_client.py`, `core/src/fantaclaude/commands/__init__.py`, `core/src/fantaclaude/commands/sync_league.py`
- Modify: `core/src/fantaclaude/cli/app.py` (the `sync-league` command), `core/tests/conftest.py` (`make_jwt`, `FakeAPI`, `fake_api`)
- Test: `core/tests/test_api_client.py`, `core/tests/test_sync_league.py`

**Interfaces:**
- Consumes: `fantacalcio_mcp.config.{load_settings, token_cache_path}`, `fantacalcio_mcp.auth.Auth`, `fantacalcio_mcp.api.FantacalcioAPI`; Tasks 6–8.
- Produces: `ApiHandle(api, http)` with `aclose()`; `build_api(*, timeout=20.0) -> ApiHandle`; `run_with_api(fn: Callable[[FantacalcioAPI], Awaitable[T]]) -> T`; `SyncReport` (frozen: `league_id, season_id, team_count, rules_hash, changed, snapshot_id, previous_hash, diff: list[Change], conflicts: list[Conflict]`, `to_dict()`); `async fetch_snapshot(api, *, league=None) -> LeagueSnapshot`; `async sync_league(api, con, league_yml: dict[str, Provenanced] | None, *, league=None, fetched_at=None) -> SyncReport`; CLI `fantaclaude sync-league [--json] [--league ALIAS]` (exit `4` on a conflict, nothing recorded); conftest `make_jwt(**claims) -> str`, `FakeAPI`, fixture `fake_api(overrides: dict | None = None) -> FakeAPI`.

- [ ] **Step 1: Write the failing tests**

Append to `core/tests/conftest.py`:

```python
import base64
import time


def make_jwt(**claims) -> str:
    """An unsigned RS256-shaped JWT with the given claims (test helper, mirrors the MCP suite)."""
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.signature"


class FakeAPI:
    """The subset of FantacalcioAPI the commands call, answered from fixtures.

    `overrides` replaces a named payload; `calls` records every method name
    so a test can assert how many round-trips a command made.
    """

    def __init__(self, load, overrides=None):
        self._load = load
        self._overrides = dict(overrides or {})
        self.calls: list[str] = []

    async def _answer(self, name: str):
        self.calls.append(name)
        if name in self._overrides:
            return json.loads(json.dumps(self._overrides[name]))
        return self._load(name)

    async def league_profile(self, league=None):
        return await self._answer("league_profile")

    async def league_status(self, league=None):
        return await self._answer("league_status")

    async def roster_settings(self, league=None):
        return await self._answer("roster_settings")

    async def lineup_settings(self, league=None):
        return await self._answer("lineup_settings")

    async def calculation_settings(self, league=None):
        return await self._answer("calculation_settings")

    async def teams(self, page=1, league=None):
        return await self._answer("teams")

    async def players(self, league=None):
        return await self._answer("players")


@pytest.fixture
def fake_api(mcp_fixture_json):
    def _make(overrides=None):
        return FakeAPI(mcp_fixture_json, overrides)
    return _make
```

Create `core/tests/test_api_client.py`:

```python
import time

import httpx
import respx

from conftest import make_jwt
from fantaclaude.api_client import run_with_api

BASE = "https://apileague.fantacalcio.it"


def test_run_with_api_builds_a_client_from_the_workspace_env(monkeypatch, tmp_path, mcp_fixture_json):
    for var in ("FANTACALCIO_USERNAME", "FANTACALCIO_PASSWORD", "FANTACALCIO_LEAGUE_TOKEN",
                "FANTACALCIO_APP_KEY", "FANTACALCIO_API_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    token = make_jwt(user_id="10426252", l_id="2578630", t_id="11560832", role="user_league",
                     exp=int(time.time()) + 31_536_000)
    (tmp_path / ".env").write_text(f"FANTACALCIO_APP_KEY=K\nFANTACALCIO_LEAGUE_TOKEN={token}\n")
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/market/v1/time").mock(
            return_value=httpx.Response(200, json=mcp_fixture_json("server_time")))
        payload = run_with_api(lambda api: api.server_time())
    assert route.called
    assert route.calls[0].request.headers["app_key"] == "K"
    assert payload == mcp_fixture_json("server_time")
```

Create `core/tests/test_sync_league.py`:

```python
import asyncio
import json

from typer.testing import CliRunner

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.sync_league import sync_league
from fantaclaude.league.league_yml import load_league_yml


async def test_sync_records_a_snapshot_and_reports_no_change_on_rerun(db, fake_api):
    api = fake_api()
    first = await sync_league(api, db, None)
    assert first.changed and first.snapshot_id == 1 and first.league_id == 2578630
    assert first.team_count == 8 and first.season_id == 21
    second = await sync_league(api, db, None)
    assert not second.changed and second.snapshot_id == 1
    assert api.calls.count("league_profile") == 2


async def test_sync_reports_what_changed(db, fake_api, mcp_fixture_json):
    await sync_league(fake_api(), db, None)
    richer = fake_api(overrides={"roster_settings": dict(mcp_fixture_json("roster_settings"), budg=1000)})
    report = await sync_league(richer, db, None)
    assert report.changed and [c.path for c in report.diff] == ["rosters.budg"]
    assert report.to_dict()["diff"] == [{"path": "rosters.budg", "before": 500, "after": 1000}]


async def test_conflict_with_league_yml_records_nothing(db, fake_api, tmp_path):
    path = tmp_path / "league.yml"
    path.write_text("budget: {value: 1000, source: admin, verified_on: 2026-08-24}\n")
    report = await sync_league(fake_api(), db, load_league_yml(path))
    assert report.conflicts and report.conflicts[0].key == "budget"
    assert report.snapshot_id is None and not report.changed
    assert db.execute("SELECT count(*) FROM league_settings").fetchone()[0] == 0


def test_cli_sync_league_json_and_exit_codes(monkeypatch, tmp_path, fake_api):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    api = fake_api()
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    runner = CliRunner()
    result = runner.invoke(app, ["sync-league", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["changed"] is True and payload["snapshot_id"] == 1 and payload["conflicts"] == []
    assert (tmp_path / "data" / "fanta.duckdb").is_file()

    (tmp_path / "league.yml").write_text("budget: {value: 1000, source: admin, verified_on: 2026-08-24}\n")
    result = runner.invoke(app, ["sync-league"])
    assert result.exit_code == ExitCode.CONFLICT
    assert "budget" in result.stdout and "1000" in result.stdout and "500" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.api_client'`.

- [ ] **Step 3: Write the API bridge**

Create `core/src/fantaclaude/api_client.py`:

```python
"""Build the MCP's API client for the CLI, and run coroutines from sync code.

One client, one endpoint map: the MCP's config, auth and api are imported as a
library, so the credentials, the token cache and its cross-process lock are
the very files the server uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import httpx
from fantacalcio_mcp.api import FantacalcioAPI
from fantacalcio_mcp.auth import Auth
from fantacalcio_mcp.config import load_settings, token_cache_path

T = TypeVar("T")


@dataclass
class ApiHandle:
    api: FantacalcioAPI
    http: httpx.AsyncClient

    async def aclose(self) -> None:
        await self.http.aclose()


def build_api(*, timeout: float = 20.0) -> ApiHandle:
    settings = load_settings()
    http = httpx.AsyncClient(timeout=timeout)
    auth = Auth(settings.credentials, token_cache_path(), http, settings.app_key, settings.base_url)
    return ApiHandle(FantacalcioAPI(http, auth, settings.base_url, settings.app_key), http)


def run_with_api(fn: Callable[[FantacalcioAPI], Awaitable[T]]) -> T:
    """Run `fn(api)` to completion on one event loop and close the client on
    that same loop -- the MCP's __main__ explains why closing on a second
    loop is not safe."""
    async def go() -> T:
        handle = build_api()
        try:
            return await fn(handle.api)
        finally:
            await handle.aclose()
    return asyncio.run(go())
```

- [ ] **Step 4: Write the command**

Create `core/src/fantaclaude/commands/__init__.py` (empty) and `core/src/fantaclaude/commands/sync_league.py`:

```python
"""fantaclaude sync-league: refresh league_settings from the league API.

Importable on purpose -- the CLI and, later, the FastAPI server call this
function; the CLI adds only argument parsing and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.league.league_yml import Conflict, Provenanced, cross_check
from fantaclaude.league.settings import (
    Change, LeagueSnapshot, record_snapshot, snapshot_from_payloads,
)


@dataclass(frozen=True)
class SyncReport:
    league_id: int
    season_id: int | None
    team_count: int | None
    rules_hash: str
    changed: bool
    snapshot_id: int | None
    previous_hash: str | None
    diff: list[Change] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "league_id": self.league_id, "season_id": self.season_id,
            "team_count": self.team_count, "rules_hash": self.rules_hash,
            "changed": self.changed, "snapshot_id": self.snapshot_id,
            "previous_hash": self.previous_hash,
            "diff": [{"path": c.path, "before": c.before, "after": c.after} for c in self.diff],
            "conflicts": [{"key": c.key, "league_yml": c.league_yml, "api": c.api}
                          for c in self.conflicts],
        }


async def fetch_snapshot(api: FantacalcioAPI, *, league: str | None = None) -> LeagueSnapshot:
    # Sequential on purpose: six reads against a real account, one at a time.
    profile = await api.league_profile(league=league)
    status = await api.league_status(league=league)
    rosters = await api.roster_settings(league=league)
    lineup = await api.lineup_settings(league=league)
    calculate = await api.calculation_settings(league=league)
    teams = await api.teams(page=1, league=league)
    return snapshot_from_payloads(profile=profile, status=status, rosters=rosters,
                                  lineup=lineup, calculate=calculate, teams=teams)


async def sync_league(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection,
                      league_yml: dict[str, Provenanced] | None, *,
                      league: str | None = None,
                      fetched_at: datetime | None = None) -> SyncReport:
    """Fetch the rules, refuse loudly if league.yml disagrees with them,
    otherwise append a snapshot when the rules hash moved."""
    snap = await fetch_snapshot(api, league=league)
    conflicts = cross_check(league_yml, snap) if league_yml else []
    if conflicts:
        return SyncReport(snap.league_id, snap.season_id, snap.team_count, snap.rules_hash,
                          changed=False, snapshot_id=None, previous_hash=None,
                          conflicts=conflicts)
    result = record_snapshot(con, snap, fetched_at=fetched_at)
    return SyncReport(snap.league_id, snap.season_id, snap.team_count, snap.rules_hash,
                      changed=result.changed, snapshot_id=result.snapshot_id,
                      previous_hash=result.previous_hash, diff=result.diff)
```

- [ ] **Step 5: Wire the CLI command**

Append to `core/src/fantaclaude/cli/app.py`:

```python
def _render_sync(payload: dict) -> str:
    lines = [f"league {payload['league_id']} · season {payload['season_id']} · "
             f"{payload['team_count']} teams · rules {payload['rules_hash']}"]
    for c in payload["conflicts"]:
        lines.append(f"CONFLICT {c['key']}: league.yml says {c['league_yml']!r}, the API says {c['api']!r}")
    if payload["conflicts"]:
        lines.append("nothing recorded -- fix league.yml (it must never override the API) and re-run")
        return "\n".join(lines)
    if payload["changed"]:
        was = f" (was {payload['previous_hash']})" if payload["previous_hash"] else " (first snapshot)"
        lines.append(f"changed: snapshot {payload['snapshot_id']}{was}")
        for c in payload["diff"]:
            lines.append(f"  {c['path']}: {c['before']!r} -> {c['after']!r}")
    else:
        lines.append(f"unchanged (snapshot {payload['snapshot_id']})")
    return "\n".join(lines)


@app.command("sync-league")
def sync_league_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh league_settings from the league API: profile, status, the three settings payloads and the team list."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.sync_league import sync_league
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.league.league_yml import load_league_yml
    from fantaclaude.paths import league_yml_path

    entries = load_league_yml(league_yml_path()) if league_yml_path().is_file() else None
    con = connect()
    try:
        apply_schema(con)
        report = run_with_api(lambda api: sync_league(api, con, entries, league=league))
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_sync)
    if report.conflicts:
        raise typer.Exit(code=ExitCode.CONFLICT)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `48 passed`. If `test_api_client` fails on a keychain prompt, `FANTACALCIO_USERNAME` leaked from the environment — the `delenv` loop in the test is what prevents `_keychain_password` from being called.

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/api_client.py core/src/fantaclaude/commands core/src/fantaclaude/cli/app.py core/tests/conftest.py core/tests/test_api_client.py core/tests/test_sync_league.py
git commit -m "feat(cli): sync-league appends league_settings and checks league.yml"
```

---

### Task 10: Raw store, listone adapter, `fantaclaude ingest`

**Files:**
- Create: `core/src/fantaclaude/ingest/__init__.py`, `core/src/fantaclaude/ingest/raw.py`, `core/src/fantaclaude/ingest/listone_api.py`, `core/src/fantaclaude/commands/ingest.py`
- Create: `core/tests/fixtures/_extract_listone.py`, `core/tests/fixtures/listone_sample.json`
- Modify: `core/src/fantaclaude/cli/app.py` (the `ingest` sub-app), `core/tests/conftest.py` (`fixture_path`)
- Test: `core/tests/test_fixtures.py`, `core/tests/test_listone.py`

**Interfaces:**
- Consumes: `FantacalcioAPI.players()` (Task 2), `decode_mantra`/`decode_classic`/`sort_roles` (Task 4), the schema (Task 6), `to_db` (Task 6).
- Produces: `RawFile(path, sha256, fetched_at, kind)`; `RawStore(root)` with `write(kind, payload, *, fetched_at=None) -> RawFile`, `list(kind) -> list[Path]`, `sha256_of(path)`; `ListoneShapeError(ValueError)`; `PlayerRow` (frozen dataclass, fields listed in the code); `async fetch_listone(api, store, *, league=None) -> RawFile`; `load_listone(path) -> list[PlayerRow]`; `IngestResult(snapshot_id, inserted, skipped_duplicate, sha256, raw_path)` with `to_dict()`; `record_listone(con, rows, raw) -> IngestResult`; `async ingest_listone(api, con, store, *, league=None) -> IngestResult`; `async ingest_all(api, con, store, *, league=None) -> dict[str, IngestResult]`; CLI `fantaclaude ingest listone [--json]`, `fantaclaude ingest all [--json]`; conftest fixture `fixture_path(name) -> Path`.

- [ ] **Step 1: Build the listone fixture from the capture**

Create `core/tests/fixtures/_extract_listone.py` (kept as provenance, like the MCP's `_extract.py`):

```python
"""One-shot: build listone_sample.json from captured/listone-2026-08-23.json.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_listone.py

Seventeen players chosen to cover every Mantra role code (6-16 and 19), a
transfer-flagged name, a three-role player without B, and a player whose
Classic and Mantra quotazioni differ. `img` (a CDN path) is dropped; nothing
else in the listone is a secret -- names, clubs and prices are public.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "listone-2026-08-23.json"
OUT = Path(__file__).with_name("listone_sample.json")

IDS = [3, 5841, 2120, 254, 5877, 2764, 2194, 2423, 2097, 6052,
       2517, 536, 309, 152, 2297, 791, 2640]


def main() -> None:
    players = {p["id"]: p for p in json.loads(CAPTURE.read_text(encoding="utf-8"))["players"]}
    rows = [{k: v for k, v in players[i].items() if k != "img"} for i in IDS]
    OUT.write_text(json.dumps({"players": rows, "timestamp": 1787517550778},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    codes = sorted({c for r in rows for c in r["marle"]})
    print(f"wrote {len(rows)} players, role codes {codes}")


if __name__ == "__main__":
    main()
```

Run: `uv run python core/tests/fixtures/_extract_listone.py`
Expected: `wrote 17 players, role codes [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19]`.

- [ ] **Step 2: Write the failing tests**

Append to `core/tests/conftest.py`:

```python
@pytest.fixture
def fixture_path():
    def _path(name: str) -> Path:
        return FIXTURE_DIR / f"{name}.json"
    return _path
```

Create `core/tests/test_fixtures.py`:

```python
"""The secret scan for this package's fixtures: key names and shapes, never
a literal value -- a scanner that embeds the secret it scans for ships it."""

import json

from conftest import FIXTURE_DIR

SECRET_KEYS = {"parola", "password", "token", "jwt", "email", "app_key"}


def _keys_at_any_depth(value) -> set[str]:
    found: set[str] = set()
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            found.update(str(k).lower() for k in node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def test_expected_fixtures_exist():
    assert (FIXTURE_DIR / "listone_sample.json").is_file()


def test_fixtures_contain_no_secrets():
    for path in FIXTURE_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "eyJhbGci" not in text, f"{path.name} contains a JWT"
        assert "@" not in text.replace("\\u0040", ""), f"{path.name} contains an email"
        assert not SECRET_KEYS & _keys_at_any_depth(json.loads(text)), f"{path.name} carries a secret key"
```

Create `core/tests/test_listone.py`:

```python
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import ingest_all, ingest_listone
from fantaclaude.ingest.listone_api import ListoneShapeError, load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from fantaclaude.model.roles import ClassicRole, Role, UnknownRoleCode


def test_raw_store_writes_immutable_dated_files(tmp_path):
    store = RawStore(tmp_path)
    when = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    first = store.write("listone", {"x": 1}, fetched_at=when)
    assert first.path.name == "20260824T100000000000Z-listone.json" and first.path.is_file()
    assert first.sha256 == RawStore.sha256_of(first.path) and first.kind == "listone"
    with pytest.raises(FileExistsError):
        store.write("listone", {"x": 2}, fetched_at=when)          # never overwritten
    second = store.write("listone", {"x": 1})
    assert store.list("listone") == sorted([first.path, second.path])
    assert first.sha256 == second.sha256                            # same bytes, same hash
    assert store.list("nothing") == []


def test_load_listone_decodes_every_role_code(fixture_path):
    rows = load_listone(fixture_path("listone_sample"))
    assert len(rows) == 17
    assert {c for r in rows for c in r.mantra_role_codes} == {6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19}
    by = {r.player_id: r for r in rows}
    assert by[5877].mantra_roles == {Role.B, Role.Ds, Role.E} and by[5877].classic_role is ClassicRole.D
    assert by[254].quot_current_mantra == 30 and by[254].quot_current_classic == 32
    assert by[2297].transfer_flag is True and by[2764].transfer_flag is False
    assert by[3].raw["lid"] == 21                                   # unnamed fields survive in raw
    assert by[2764].team_name == "Inter" and by[2764].team_short == "INT"


def test_unknown_role_code_names_the_player(tmp_path, fixture_json):
    payload = fixture_json("listone_sample")
    payload["players"][0]["marle"] = [6, 99]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(UnknownRoleCode, match=r"\[99\].*Radunovic"):
        load_listone(path)


def test_missing_confirmed_field_fails_loud(tmp_path, fixture_json):
    payload = fixture_json("listone_sample")
    del payload["players"][3]["icsma"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ListoneShapeError, match="icsma"):
        load_listone(path)
    path.write_text(json.dumps({"players": []}))
    with pytest.raises(ListoneShapeError):
        load_listone(path)


def test_record_listone_snapshots_and_dedupes(db, tmp_path, fixture_json):
    store = RawStore(tmp_path / "raw")
    raw = store.write("listone", fixture_json("listone_sample"))
    result = record_listone(db, load_listone(raw.path), raw)
    assert result.snapshot_id == 1 and result.inserted == 17 and not result.skipped_duplicate
    assert db.execute("SELECT count(*) FROM v_players_current").fetchone()[0] == 17
    assert db.execute("SELECT mantra_roles FROM v_players_current WHERE player_id = 5877").fetchone()[0] == ["Ds", "B", "E"]
    teams = {p["tid"] for p in fixture_json("listone_sample")["players"]}
    assert db.execute("SELECT count(*) FROM v_teams_current").fetchone()[0] == len(teams)

    again = record_listone(db, load_listone(raw.path), raw)
    assert again.skipped_duplicate and again.snapshot_id == 1 and again.inserted == 0

    changed = fixture_json("listone_sample")
    changed["players"][0]["acsma"] = 2
    raw2 = store.write("listone", changed)
    second = record_listone(db, load_listone(raw2.path), raw2)
    assert second.snapshot_id == 2
    assert db.execute("SELECT count(*) FROM players").fetchone()[0] == 34            # history kept
    assert db.execute("SELECT quot_current_mantra FROM v_players_current WHERE player_id = 3").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM listone_snapshots").fetchone()[0] == 2


async def test_ingest_listone_command_end_to_end(db, tmp_path, fake_api, fixture_json):
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    result = await ingest_listone(api, db, RawStore(tmp_path / "raw"))
    assert result.inserted == 17 and Path(result.raw_path).is_file()
    everything = await ingest_all(api, db, RawStore(tmp_path / "raw"))
    assert set(everything) == {"listone"} and everything["listone"].skipped_duplicate


def test_cli_ingest_listone_json(monkeypatch, tmp_path, fake_api, fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    result = CliRunner().invoke(app, ["ingest", "listone", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["inserted"] == 17 and payload["snapshot_id"] == 1
    assert list((tmp_path / "data" / "raw" / "listone").glob("*-listone.json"))
    result = CliRunner().invoke(app, ["ingest", "all"])
    assert result.exit_code == ExitCode.OK and "listone" in result.stdout and "duplicate" in result.stdout
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.ingest'`.

- [ ] **Step 4: Write the raw store**

Create `core/src/fantaclaude/ingest/__init__.py` (empty) and `core/src/fantaclaude/ingest/raw.py`:

```python
"""Immutable, dated raw files: what every adapter's fetch() writes.

data/raw/<kind>/<UTC stamp>-<kind>.json, created O_EXCL so nothing is ever
overwritten, fsynced, and hashed -- the spine is rebuildable from these.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fantaclaude.timeutil import utc_now


@dataclass(frozen=True)
class RawFile:
    path: Path
    sha256: str
    fetched_at: datetime
    kind: str


class RawStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, kind: str, payload: Any, *, fetched_at: datetime | None = None) -> RawFile:
        fetched_at = fetched_at or utc_now()
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        stamp = fetched_at.strftime("%Y%m%dT%H%M%S%fZ")    # microseconds keep two writes apart
        path = folder / f"{stamp}-{kind}.json"
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        return RawFile(path, hashlib.sha256(data).hexdigest(), fetched_at, kind)

    def list(self, kind: str) -> list[Path]:
        folder = self.root / kind
        return sorted(folder.glob(f"*-{kind}.json")) if folder.is_dir() else []

    @staticmethod
    def sha256_of(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
```

- [ ] **Step 5: Write the listone adapter**

Create `core/src/fantaclaude/ingest/listone_api.py`:

```python
"""The listone through the league API: fetch, parse, snapshot.

Column names follow the MCP spec's confirmed meanings; everything else rides
in `raw`. An unknown role code fails loud with the player's name (roles.py)
and a missing confirmed field fails loud with the field's name -- a red
ingest, never a silently-null quotazione.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.model.roles import ClassicRole, Role, decode_classic, decode_mantra, sort_roles
from fantaclaude.timeutil import to_db

SOURCE = "league_api:/onboarding/v1/league/players"
REQUIRED = ("id", "name", "tname", "stnme", "tid", "fcrle", "marle",
            "icsfc", "acsfc", "icsma", "acsma", "fvmfc", "fvmma")


class ListoneShapeError(ValueError):
    """The payload is not the listone this adapter was written against."""


@dataclass(frozen=True)
class PlayerRow:
    player_id: int
    name: str
    team_id: int
    team_name: str
    team_short: str
    classic_role: ClassicRole
    mantra_roles: frozenset[Role]
    mantra_role_codes: tuple[int, ...]
    quot_initial_classic: int
    quot_current_classic: int
    quot_initial_mantra: int
    quot_current_mantra: int
    fvm_classic: int
    fvm_mantra: int
    age: int | None
    nationality: str | None
    transfer_flag: bool
    raw: dict[str, Any]


async def fetch_listone(api: FantacalcioAPI, store: RawStore, *, league: str | None = None) -> RawFile:
    payload = await api.players(league=league)
    if not isinstance(payload, dict) or not isinstance(payload.get("players"), list):
        raise ListoneShapeError("listone payload is not {players: [...], timestamp}")
    return store.write("listone", payload)


def load_listone(path: Path) -> list[PlayerRow]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    players = payload.get("players") if isinstance(payload, dict) else None
    if not isinstance(players, list) or not players:
        raise ListoneShapeError(f"{path}: no players array")
    rows: list[PlayerRow] = []
    for entry in players:
        missing = [k for k in REQUIRED if k not in entry]
        if missing:
            raise ListoneShapeError(
                f"{path}: player {entry.get('id')} ({entry.get('name')}) lacks {missing}")
        context = f"{entry['name']} (id {entry['id']})"
        rows.append(PlayerRow(
            player_id=int(entry["id"]),
            name=str(entry["name"]),
            team_id=int(entry["tid"]),
            team_name=str(entry["tname"]),
            team_short=str(entry["stnme"]),
            classic_role=decode_classic(int(entry["fcrle"]), context=context),
            mantra_roles=decode_mantra(entry["marle"], context=context),
            mantra_role_codes=tuple(int(c) for c in entry["marle"]),
            quot_initial_classic=int(entry["icsfc"]),
            quot_current_classic=int(entry["acsfc"]),
            quot_initial_mantra=int(entry["icsma"]),
            quot_current_mantra=int(entry["acsma"]),
            fvm_classic=int(entry["fvmfc"]),
            fvm_mantra=int(entry["fvmma"]),
            age=entry.get("age"),
            nationality=entry.get("naty"),
            transfer_flag=bool(entry.get("trnsf")),
            raw=entry,
        ))
    ids = [r.player_id for r in rows]
    if len(set(ids)) != len(ids):
        raise ListoneShapeError(f"{path}: duplicate player ids")
    return rows


@dataclass(frozen=True)
class IngestResult:
    snapshot_id: int | None
    inserted: int
    skipped_duplicate: bool
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "inserted": self.inserted,
                "skipped_duplicate": self.skipped_duplicate, "sha256": self.sha256,
                "raw_path": self.raw_path}


def record_listone(con: duckdb.DuckDBPyConnection, rows: list[PlayerRow], raw: RawFile) -> IngestResult:
    """Append one snapshot per distinct raw file; the same bytes twice is a no-op."""
    existing = con.execute("SELECT snapshot_id FROM listone_snapshots WHERE sha256 = ?",
                           [raw.sha256]).fetchone()
    if existing is not None:
        return IngestResult(existing[0], 0, True, raw.sha256, str(raw.path))
    snapshot_id = con.execute(
        "INSERT INTO listone_snapshots (fetched_at, source, raw_path, sha256, player_count) "
        "VALUES (?, ?, ?, ?, ?) RETURNING snapshot_id",
        [to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, len(rows)]).fetchone()[0]
    con.executemany(
        "INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
        [[snapshot_id, r.player_id, r.name, r.team_id, r.team_name, r.team_short,
          r.classic_role.value, [x.value for x in sort_roles(r.mantra_roles)],
          list(r.mantra_role_codes), r.quot_initial_classic, r.quot_current_classic,
          r.quot_initial_mantra, r.quot_current_mantra, r.fvm_classic, r.fvm_mantra,
          r.age, r.nationality, r.transfer_flag, json.dumps(r.raw, ensure_ascii=False)]
         for r in rows])
    teams = sorted({(r.team_id, r.team_name, r.team_short) for r in rows})
    con.executemany("INSERT INTO teams VALUES (?, ?, ?, ?)",
                    [[snapshot_id, team_id, name, short] for team_id, name, short in teams])
    return IngestResult(snapshot_id, len(rows), False, raw.sha256, str(raw.path))
```

- [ ] **Step 6: Write the command and the CLI sub-app**

Create `core/src/fantaclaude/commands/ingest.py`:

```python
"""fantaclaude ingest: every source, through the same fetch/load/record shape."""

from __future__ import annotations

import duckdb
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.ingest.listone_api import IngestResult, fetch_listone, load_listone, record_listone
from fantaclaude.ingest.raw import RawStore


async def ingest_listone(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection, store: RawStore, *,
                         league: str | None = None) -> IngestResult:
    raw = await fetch_listone(api, store, league=league)
    return record_listone(con, load_listone(raw.path), raw)


async def ingest_all(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection, store: RawStore, *,
                     league: str | None = None) -> dict[str, IngestResult]:
    # Phase 0b adds stats_web, calendar and advanced here.
    return {"listone": await ingest_listone(api, con, store, league=league)}
```

Append to `core/src/fantaclaude/cli/app.py`:

```python
ingest_app = typer.Typer(name="ingest", help="Fetch a source into data/raw/ and snapshot it into DuckDB.",
                         no_args_is_help=True)
app.add_typer(ingest_app)


def _render_ingest(payload: dict) -> str:
    lines = []
    for name, result in payload.items():
        if result["skipped_duplicate"]:
            lines.append(f"{name}: duplicate of snapshot {result['snapshot_id']} -- nothing new ({result['raw_path']})")
        else:
            lines.append(f"{name}: snapshot {result['snapshot_id']}, {result['inserted']} rows ({result['raw_path']})")
    return "\n".join(lines)


def _run_ingest(names: list[str], json_: bool, league: str | None) -> None:
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.ingest import ingest_all, ingest_listone
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir

    store = RawStore(raw_dir())
    con = connect()
    try:
        apply_schema(con)
        if names == ["all"]:
            results = run_with_api(lambda api: ingest_all(api, con, store, league=league))
        else:
            results = {"listone": run_with_api(lambda api: ingest_listone(api, con, store, league=league))}
    finally:
        con.close()
    payload = {name: r.to_dict() for name, r in results.items()}
    if names != ["all"]:
        emit(payload["listone"], json_=json_, render=lambda p: _render_ingest({"listone": p}))
    else:
        emit(payload, json_=json_, render=_render_ingest)


@ingest_app.command("listone")
def ingest_listone_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Fetch the listone (539 players, Mantra roles and quotazioni) and snapshot it."""
    _run_ingest(["listone"], json_, league)


@ingest_app.command("all")
def ingest_all_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh every source (only the listone in Phase 0a)."""
    _run_ingest(["all"], json_, league)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `57 passed`.

- [ ] **Step 8: Commit**

```bash
git add core/src/fantaclaude/ingest core/src/fantaclaude/commands/ingest.py core/src/fantaclaude/cli/app.py core/tests/conftest.py core/tests/fixtures core/tests/test_fixtures.py core/tests/test_listone.py
git commit -m "feat(ingest): listone through the league API into dated raw files and snapshots"
```

---

### Task 11: `fantaclaude schema` and `fantaclaude query --sql`

**Files:**
- Modify: `core/src/fantaclaude/cli/app.py`
- Test: `core/tests/test_query_schema_cli.py`

**Interfaces:**
- Consumes: `connect(read_only=True)`, `DatabaseMissing`, `schema_report` (Task 6); `RawStore`, `load_listone`, `record_listone` (Task 10) for seeding in tests.
- Produces: CLI `fantaclaude schema [--json]` (exit `3` when there is no database); CLI `fantaclaude query --sql SQL [--json] [--limit N]` (read-only; exit `3` no database, exit `1` when DuckDB rejects the statement; JSON shape `{"columns": [...], "rows": [[...]], "truncated": bool}`).

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_query_schema_cli.py`:

```python
import json

from typer.testing import CliRunner

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.db.connection import connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore


def _seeded_workspace(monkeypatch, tmp_path, fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    raw = RawStore(tmp_path / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    con.close()                      # the CLI reopens read-only, in what would be another process


def test_schema_and_query_need_a_database(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == ExitCode.NOT_READY and "sync-league" in result.stderr
    assert runner.invoke(app, ["query", "--sql", "select 1"]).exit_code == ExitCode.NOT_READY


def test_schema_lists_views_and_row_counts(monkeypatch, tmp_path, fixture_json):
    _seeded_workspace(monkeypatch, tmp_path, fixture_json)
    result = CliRunner().invoke(app, ["schema", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    by = {t["name"]: t for t in payload["tables"]}
    assert by["players"]["rows"] == 17 and by["v_players_current"]["kind"] == "view"
    assert payload["version"] == 1
    plain = CliRunner().invoke(app, ["schema"])
    assert "view v_players_current" in plain.stdout


def test_query_returns_rows_and_refuses_writes(monkeypatch, tmp_path, fixture_json):
    _seeded_workspace(monkeypatch, tmp_path, fixture_json)
    runner = CliRunner()
    result = runner.invoke(app, ["query", "--json", "--sql",
        "SELECT player_id, name FROM v_players_current WHERE list_contains(mantra_roles, 'B') ORDER BY player_id"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["columns"] == ["player_id", "name"] and payload["rows"] == [[5877, "Carlos Augusto"]]
    assert payload["truncated"] is False

    result = runner.invoke(app, ["query", "--sql", "DELETE FROM players"])
    assert result.exit_code == ExitCode.ERROR and "query failed" in result.stderr

    result = runner.invoke(app, ["query", "--json", "--limit", "5", "--sql",
                                 "SELECT player_id FROM v_players_current ORDER BY player_id"])
    payload = json.loads(result.stdout)
    assert len(payload["rows"]) == 5 and payload["truncated"] is True

    plain = runner.invoke(app, ["query", "--sql", "SELECT count(*) AS n FROM v_players_current"])
    assert plain.exit_code == ExitCode.OK and "17" in plain.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `No such command 'schema'` (exit code 2 where 3 or 0 is expected).

- [ ] **Step 3: Add the two commands**

Append to `core/src/fantaclaude/cli/app.py`:

```python
def _open_read_only():
    from fantaclaude.db.connection import DatabaseMissing, connect

    try:
        return connect(read_only=True)
    except DatabaseMissing as exc:
        typer.echo(f"no database at {exc} -- run `fantaclaude sync-league` or "
                   f"`fantaclaude ingest listone` first", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY)


def _render_schema(payload: dict) -> str:
    lines = [f"schema version {payload['version']}"]
    for t in payload["tables"]:
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        lines.append(f"{t['kind']} {t['name']} ({t['rows']} rows): {cols}")
    return "\n".join(lines)


@app.command("schema")
def schema_cmd(json_: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """List tables, views and columns -- the names `query --sql` may use. Prefer the v_* views."""
    from fantaclaude.db.schema import schema_report

    con = _open_read_only()
    try:
        report = schema_report(con)
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_schema)


def _render_rows(payload: dict) -> str:
    columns, rows = payload["columns"], payload["rows"]
    if not columns:
        return "(no result set)"
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    line = lambda values: "  ".join(v.ljust(w) for v, w in zip(values, widths))  # noqa: E731
    out = [line(columns), line(["-" * w for w in widths]), *(line(r) for r in cells)]
    if payload["truncated"]:
        out.append(f"... truncated at {len(rows)} rows (raise --limit)")
    return "\n".join(out)


@app.command("query")
def query_cmd(
    sql: str = typer.Option(..., "--sql", help="A read-only SQL statement."),
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    limit: int = typer.Option(200, "--limit", help="Maximum rows returned."),
) -> None:
    """Run ad-hoc read-only SQL against fanta.duckdb. Query the v_* views by name; raw table shapes may change."""
    import duckdb

    con = _open_read_only()
    try:
        try:
            cursor = con.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(limit + 1) if columns else []
        except duckdb.Error as exc:
            typer.echo(f"query failed: {exc}", err=True)
            raise typer.Exit(code=ExitCode.ERROR)
    finally:
        con.close()
    truncated = len(rows) > limit
    payload = {"columns": columns, "rows": [list(r) for r in rows[:limit]], "truncated": truncated}
    emit(payload, json_=json_, render=_render_rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `60 passed`.

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/cli/app.py core/tests/test_query_schema_cli.py
git commit -m "feat(cli): schema and read-only query commands"
```

---

### Task 12: The `kb/` scaffold and `fantaclaude kb audit`

**Files:**
- Create: `kb/README.md`, `kb/rules/aliases.yml`, `kb/serie-a/teams/.gitkeep`, `kb/league/participants/.gitkeep`, `kb/league/history/.gitkeep`, `kb/league/season-2026-27/.gitkeep`
- Create: `core/src/fantaclaude/kb/__init__.py`, `core/src/fantaclaude/kb/audit.py`
- Modify: `core/src/fantaclaude/cli/app.py` (the `kb` sub-app)
- Test: `core/tests/test_kb_audit.py`

**Interfaces:**
- Consumes: `fantaclaude.paths.kb_dir()`.
- Produces: `FrontMatter(updated: date | None, ttl: str | None, confidence: str | None, source: str | None, raw: dict)`; `FrontMatterError(ValueError)`; `parse_front_matter(text) -> FrontMatter | None`; `ttl_days(ttl: str) -> int | None`; `AuditEntry(path: str, status: str, detail: str)` with `status` in `ok | expired | missing_front_matter | invalid`; `audit(kb_dir: Path, today: date) -> list[AuditEntry]`; CLI `fantaclaude kb audit [--json] [--today YYYY-MM-DD]` (always exit `0`: an audit is a notice, never a refusal).

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_kb_audit.py`:

```python
import json
from datetime import date

import pytest
from typer.testing import CliRunner

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.kb.audit import FrontMatterError, audit, parse_front_matter, ttl_days

FM = "---\nupdated: {updated}\nttl: {ttl}\nconfidence: {confidence}\nsource: {source}\n---\n# doc\n"


def test_parse_front_matter_and_ttl():
    fm = parse_front_matter(FM.format(updated="2026-08-20", ttl="7d", confidence="high", source="regolamento"))
    assert fm.updated == date(2026, 8, 20) and fm.ttl == "7d" and fm.source == "regolamento"
    assert fm.raw["confidence"] == "high"
    assert parse_front_matter("# no front matter\n") is None
    assert ttl_days("30d") == 30 and ttl_days("never") is None
    with pytest.raises(FrontMatterError):
        ttl_days("soon")
    with pytest.raises(FrontMatterError):
        parse_front_matter("---\nupdated: 2026-08-20\n")            # unterminated
    with pytest.raises(FrontMatterError):
        parse_front_matter("---\nupdated: soon\n---\n")               # not a date


def test_audit_classifies_documents(tmp_path):
    kb = tmp_path / "kb"
    inter = kb / "serie-a" / "teams" / "inter"
    inter.mkdir(parents=True)
    (kb / "README.md").write_text("# the contract, not a document\n")
    (inter / "profile.md").write_text(FM.format(updated="2026-08-20", ttl="30d", confidence="high", source="web"))
    (inter / "news.md").write_text(FM.format(updated="2026-08-01", ttl="7d", confidence="low", source="web"))
    (inter / "bare.md").write_text("no front matter\n")
    (inter / "broken.md").write_text(FM.format(updated="2026-08-20", ttl="whenever", confidence="low", source="x"))
    (inter / "partial.md").write_text("---\nupdated: 2026-08-20\nttl: 7d\n---\n")
    (inter / "forever.md").write_text(FM.format(updated="2020-01-01", ttl="never", confidence="high", source="regolamento"))
    statuses = {e.path: e.status for e in audit(kb, date(2026, 8, 24))}
    assert statuses == {
        "serie-a/teams/inter/bare.md": "missing_front_matter",
        "serie-a/teams/inter/broken.md": "invalid",
        "serie-a/teams/inter/forever.md": "ok",
        "serie-a/teams/inter/news.md": "expired",
        "serie-a/teams/inter/partial.md": "invalid",
        "serie-a/teams/inter/profile.md": "ok",
    }
    assert audit(tmp_path / "nowhere", date(2026, 8, 24)) == []


def test_committed_tree_and_the_cli(monkeypatch, tmp_path):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import kb_dir

    root = kb_dir()
    assert (root / "README.md").is_file() and (root / "rules" / "aliases.yml").is_file()
    for sub in ("rules", "serie-a/teams", "league/participants", "league/history", "league/season-2026-27"):
        assert (root / sub).is_dir(), sub

    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    rules = tmp_path / "kb" / "rules"
    rules.mkdir(parents=True)
    (rules / "house-rules.md").write_text(FM.format(updated="2026-01-01", ttl="30d", confidence="high", source="admin"))
    result = CliRunner().invoke(app, ["kb", "audit", "--json", "--today", "2026-08-24"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["expired"] == 1 and payload["entries"][0]["path"] == "rules/house-rules.md"
    plain = CliRunner().invoke(app, ["kb", "audit", "--today", "2026-08-24"])
    assert plain.exit_code == ExitCode.OK and "expired" in plain.stdout and "house-rules.md" in plain.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.kb'`.

- [ ] **Step 3: Create the tree**

Create `kb/README.md`:

```markdown
# kb/ — the knowledge base

DuckDB holds neutral numbers; this tree holds opinionated prose with
provenance. **Prose never restates a number** — it links to a query or a
`run_id`. "Lautaro averages 7.2" is a lie waiting to happen; "Lautaro takes
penalties unless Calhanoglu is on the pitch" is durable and no table has it.

```
kb/
├── rules/                     # near-static: mantra.md, house-rules.md, aliases.yml
├── serie-a/teams/<team>/      # profile.md (tactics, module, takers, rotation_factor)
│   └── players/<slug>.md      # sparse: only where prose changes a decision
└── league/
    ├── participants/<name>.md # opponent dossiers (fixed front-matter schema)
    ├── history/<season>.md
    └── season-2026-27/        # the journal, append-only: giornata-00-asta.md, giornata-01.md, …
```

## Front-matter contract

Every `.md` document except this README starts with a YAML block:

```yaml
---
updated: 2026-08-24        # ISO date of the last review
ttl: 30d                   # "<days>d" or "never"
confidence: high           # high | medium | low
source: regolamento        # where this came from
---
```

`fantaclaude kb audit` lists what has expired (`updated + ttl < today`), what
lacks front-matter, and what is malformed. An expired document is a notice for
the skill that would use it — the skill states low confidence or refuses;
the audit itself never refuses.

`fanta-kb bootstrap` (Phase 0b) fills this tree; `fanta-kb refresh` renews it.
```

Create `kb/rules/aliases.yml`:

```yaml
# Human overrides for name matching across sources (fantacalcio.it vs FBref vs
# Transfermarkt), keyed by source: the source's spelling -> listone player id.
# Empty until Phase 0b brings a second source. The listone and FantaAstaLive
# share ids and need no aliases.
fbref: {}
understat: {}
```

Create empty `.gitkeep` files at `kb/serie-a/teams/.gitkeep`, `kb/league/participants/.gitkeep`, `kb/league/history/.gitkeep`, `kb/league/season-2026-27/.gitkeep`.

- [ ] **Step 4: Write the audit**

Create `core/src/fantaclaude/kb/__init__.py` (empty) and `core/src/fantaclaude/kb/audit.py`:

```python
"""fantaclaude kb audit: which documents have expired.

Every kb document carries front-matter: updated (ISO date), ttl ("7d", "30d"
or "never"), confidence, source. Expired means updated + ttl < today. The
audit is a notice, never a refusal -- refusing belongs to the skill that
would otherwise lean on stale prose.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

REQUIRED = ("updated", "ttl", "confidence", "source")
_TTL = re.compile(r"^(\d+)d$")


class FrontMatterError(ValueError):
    """The leading YAML block is malformed."""


@dataclass(frozen=True)
class FrontMatter:
    updated: date | None
    ttl: str | None
    confidence: str | None
    source: str | None
    raw: dict[str, Any]


def parse_front_matter(text: str) -> FrontMatter | None:
    """The leading '---' block as YAML; None when the document has none."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        raise FrontMatterError("unterminated front-matter")
    data = yaml.safe_load(text[4:end]) or {}
    if not isinstance(data, dict):
        raise FrontMatterError("front-matter is not a mapping")
    updated = data.get("updated")
    if updated is not None and not isinstance(updated, date):
        raise FrontMatterError("updated must be an ISO date")
    ttl = data.get("ttl")
    return FrontMatter(updated, None if ttl is None else str(ttl),
                       data.get("confidence"), data.get("source"), data)


def ttl_days(ttl: str) -> int | None:
    if ttl == "never":
        return None
    match = _TTL.match(ttl)
    if not match:
        raise FrontMatterError(f"ttl must look like '7d' or 'never', got {ttl!r}")
    return int(match.group(1))


@dataclass(frozen=True)
class AuditEntry:
    path: str
    status: str            # ok | expired | missing_front_matter | invalid
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def audit(kb_dir: Path, today: date) -> list[AuditEntry]:
    entries: list[AuditEntry] = []
    if not kb_dir.is_dir():
        return entries
    for path in sorted(kb_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        rel = str(path.relative_to(kb_dir))
        try:
            fm = parse_front_matter(path.read_text(encoding="utf-8"))
            if fm is None:
                entries.append(AuditEntry(rel, "missing_front_matter", "no leading --- block"))
                continue
            missing = [k for k in REQUIRED if fm.raw.get(k) in (None, "")]
            if missing:
                entries.append(AuditEntry(rel, "invalid", f"missing {missing}"))
                continue
            days = ttl_days(fm.ttl)
        except FrontMatterError as exc:
            entries.append(AuditEntry(rel, "invalid", str(exc)))
            continue
        detail = f"updated {fm.updated}, ttl {fm.ttl}"
        if days is not None and fm.updated + timedelta(days=days) < today:
            entries.append(AuditEntry(rel, "expired", detail))
        else:
            entries.append(AuditEntry(rel, "ok", detail))
    return entries
```

- [ ] **Step 5: Add the CLI sub-app**

Append to `core/src/fantaclaude/cli/app.py`:

```python
kb_app = typer.Typer(name="kb", help="Knowledge-base maintenance.", no_args_is_help=True)
app.add_typer(kb_app)


def _render_audit(payload: dict) -> str:
    lines = [f"{e['status']:<20} {e['path']}  ({e['detail']})" for e in payload["entries"]]
    lines.append(f"{len(payload['entries'])} documents: {payload['expired']} expired, "
                 f"{payload['invalid']} invalid, {payload['missing_front_matter']} without front-matter")
    return "\n".join(lines)


@kb_app.command("audit")
def kb_audit_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    today: str | None = typer.Option(None, "--today", help="ISO date to audit against (default: today)."),
) -> None:
    """List knowledge-base documents that have expired, lack front-matter, or are malformed."""
    from datetime import date

    from fantaclaude.kb.audit import audit
    from fantaclaude.paths import kb_dir

    entries = audit(kb_dir(), date.fromisoformat(today) if today else date.today())
    payload = {
        "entries": [e.to_dict() for e in entries],
        "expired": sum(e.status == "expired" for e in entries),
        "invalid": sum(e.status == "invalid" for e in entries),
        "missing_front_matter": sum(e.status == "missing_front_matter" for e in entries),
    }
    emit(payload, json_=json_, render=_render_audit)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `63 passed`.

- [ ] **Step 7: Commit**

```bash
git add kb core/src/fantaclaude/kb core/src/fantaclaude/cli/app.py core/tests/test_kb_audit.py
git commit -m "feat(kb): knowledge-base tree with the front-matter contract and kb audit"
```

---

### Task 13: `fantaclaude doctor`

**Files:**
- Create: `core/src/fantaclaude/commands/doctor.py`
- Modify: `core/src/fantaclaude/cli/app.py`
- Test: `core/tests/test_doctor.py`

**Interfaces:**
- Consumes: `fantacalcio_mcp.config.load_dotenv`, `fantacalcio_mcp.auth.is_expired`; Tasks 5–8, 10, 12.
- Produces: `Check(name, ok, detail)` with `to_dict()`; `DoctorPaths(env, token_cache, db, league_yml, preferences, kb)`; `run_doctor(paths: DoctorPaths, *, now: datetime) -> list[Check]` with check names, in order: `env`, `credentials`, `token_cache`, `database`, `extensions`, `league_settings`, `listone`, `league_yml`, `preferences`, `kb`, `modules`; CLI `fantaclaude doctor [--json]` (exit `0` when every check passes, `3` otherwise). Never prints a secret value.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_doctor.py`:

```python
import json
import time
from datetime import UTC, datetime

from typer.testing import CliRunner

from conftest import make_jwt
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.doctor import DoctorPaths, run_doctor
from fantaclaude.db.connection import connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads

NAMES = ["env", "credentials", "token_cache", "database", "extensions", "league_settings",
         "listone", "league_yml", "preferences", "kb", "modules"]


def _paths(root):
    return DoctorPaths(env=root / ".env", token_cache=root / ".auth" / "tokens.json",
                       db=root / "data" / "fanta.duckdb", league_yml=root / "league.yml",
                       preferences=root / "preferences.yml", kb=root / "kb")


def _ready_workspace(root, fixture_json, mcp_fixture_json, *, token_exp_offset=31_536_000):
    token = make_jwt(user_id="1", l_id="2578630", t_id="1", role="user_league",
                     exp=int(time.time()) + token_exp_offset)
    (root / ".env").write_text("FANTACALCIO_APP_KEY=K\nFANTACALCIO_USERNAME=u\n")
    (root / ".auth").mkdir()
    (root / ".auth" / "tokens.json").write_text(json.dumps({
        "account": None, "user_id": None, "username": "u",
        "leagues": {"fantabalotelli3": {"alias": "fantabalotelli3", "league_id": "2578630",
                                        "team_id": "1", "name": "F3", "jwt": token}}}))
    (root / "league.yml").write_text("budget: {value: 500, source: admin, verified_on: 2026-08-24}\n")
    (root / "preferences.yml").write_text("target_composition: {Por: 2}\n")
    (root / "kb" / "rules").mkdir(parents=True)
    (root / "kb" / "README.md").write_text("# kb\n")
    (root / "kb" / "rules" / "aliases.yml").write_text("fbref: {}\n")
    con = connect(root / "data" / "fanta.duckdb")
    apply_schema(con)
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    raw = RawStore(root / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    con.close()


def test_every_check_passes_on_a_ready_workspace(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert "17 players" in next(c.detail for c in checks if c.name == "listone")
    assert "login mode" in next(c.detail for c in checks if c.name == "credentials")
    joined = " ".join(c.detail for c in checks)
    assert "eyJhbGci" not in joined and "K\n" not in joined           # never a secret value


def test_missing_pieces_are_named(tmp_path):
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not checks["env"].ok and not checks["database"].ok and not checks["league_yml"].ok
    assert not checks["kb"].ok and not checks["credentials"].ok
    assert checks["modules"].ok
    assert "sync-league" in checks["database"].detail


def test_expired_token_cache_is_flagged(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json, token_exp_offset=-10)
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not checks["token_cache"].ok and "expired" in checks["token_cache"].detail


def test_doctor_cli_exit_codes(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == ExitCode.NOT_READY
    payload = json.loads(result.stdout)
    assert payload["ok"] is False and [c["name"] for c in payload["checks"]] == NAMES
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == ExitCode.OK, result.output
    assert "ok" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run poe test-core 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.commands.doctor'`.

- [ ] **Step 3: Write the checks**

Create `core/src/fantaclaude/commands/doctor.py`:

```python
"""fantaclaude doctor: is the workspace ready for the night?

Every check reports existence, parseability or age -- never a value. A token
is "present, expires in N days", an app key is "set", and nothing here can
leak into a terminal log.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import yaml
from fantacalcio_mcp.auth import is_expired
from fantacalcio_mcp.config import load_dotenv

from fantaclaude.db.schema import SCHEMA_VERSION
from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
from fantaclaude.model.modules import ModuleTableError, load_modules


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DoctorPaths:
    env: Path
    token_cache: Path
    db: Path
    league_yml: Path
    preferences: Path
    kb: Path


def _age(then: datetime, now: datetime) -> str:
    hours = (now.replace(tzinfo=None) - then.replace(tzinfo=None)).total_seconds() / 3600
    return f"{hours / 24:.1f} days old" if hours >= 48 else f"{hours:.0f} hours old"


def _token_cache(path: Path, now: datetime) -> Check:
    if not path.is_file():
        return Check("token_cache", True, "no cache yet; the first API call logs in")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        leagues = (data.get("leagues") or {}) if isinstance(data, dict) else {}
        jwts = [entry["jwt"] for entry in leagues.values() if isinstance(entry, dict) and entry.get("jwt")]
    except (ValueError, KeyError, AttributeError):
        return Check("token_cache", True, "unreadable cache; it will be treated as cold and rebuilt")
    if not jwts:
        return Check("token_cache", True, "cache holds no league token yet")
    live = sum(1 for jwt in jwts if not is_expired(jwt, now=now.timestamp()))
    if live == 0:
        return Check("token_cache", False, f"{len(jwts)} league token(s), all expired -- the next call must log in")
    return Check("token_cache", True, f"{live}/{len(jwts)} league token(s) valid")


def _database_checks(path: Path, now: datetime) -> list[Check]:
    if not path.is_file():
        missing = Check("database", False, f"no database at {path} -- run `fantaclaude sync-league` and `fantaclaude ingest listone`")
        skipped = "skipped: no database"
        return [missing, Check("extensions", False, skipped), Check("league_settings", False, skipped),
                Check("listone", False, skipped)]
    checks: list[Check] = []
    con = duckdb.connect(str(path), read_only=True)
    try:
        version = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
        checks.append(Check("database", version == SCHEMA_VERSION,
                            f"schema version {version}, code expects {SCHEMA_VERSION}"))
        installed = {r[0] for r in con.execute(
            "SELECT extension_name FROM duckdb_extensions() WHERE installed").fetchall()}
        needed = {"json", "parquet"}
        checks.append(Check("extensions", needed <= installed,
                            f"installed: {', '.join(sorted(needed & installed)) or 'none'}; "
                            f"missing: {', '.join(sorted(needed - installed)) or 'none'}"))
        row = con.execute("SELECT fetched_at, rules_hash, budget, team_count FROM v_league_settings_current").fetchone()
        if row is None:
            checks.append(Check("league_settings", False, "no snapshot -- run `fantaclaude sync-league`"))
        else:
            checks.append(Check("league_settings", True,
                                f"rules {row[1]}, budget {row[2]}, {row[3]} teams, {_age(row[0], now)}"))
        row = con.execute("SELECT fetched_at, player_count FROM listone_snapshots "
                          "ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        if row is None:
            checks.append(Check("listone", False, "no snapshot -- run `fantaclaude ingest listone`"))
        else:
            checks.append(Check("listone", True, f"{row[1]} players, {_age(row[0], now)}"))
    finally:
        con.close()
    return checks


def _yaml_check(name: str, path: Path, required_key: str) -> Check:
    if not path.is_file():
        return Check(name, False, f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return Check(name, False, f"does not parse: {exc}")
    if not isinstance(data, dict) or required_key not in data:
        return Check(name, False, f"no `{required_key}` key")
    return Check(name, True, f"{len(data)} top-level keys")


def run_doctor(paths: DoctorPaths, *, now: datetime) -> list[Check]:
    env = load_dotenv(paths.env) if paths.env.is_file() else {}
    checks = [Check("env", paths.env.is_file() and bool(env.get("FANTACALCIO_APP_KEY")),
                    "FANTACALCIO_APP_KEY set" if env.get("FANTACALCIO_APP_KEY") else f"{paths.env} missing or without FANTACALCIO_APP_KEY")]
    if env.get("FANTACALCIO_USERNAME"):
        checks.append(Check("credentials", True, "login mode (password from the keychain or .env)"))
    elif env.get("FANTACALCIO_LEAGUE_TOKEN"):
        checks.append(Check("credentials", True, "token-only mode (no self-healing on expiry)"))
    else:
        checks.append(Check("credentials", False, "neither FANTACALCIO_USERNAME nor FANTACALCIO_LEAGUE_TOKEN in .env"))
    checks.append(_token_cache(paths.token_cache, now))
    checks.extend(_database_checks(paths.db, now))
    try:
        entries = load_league_yml(paths.league_yml) if paths.league_yml.is_file() else None
        checks.append(Check("league_yml", entries is not None,
                            f"{len(entries)} provenanced keys" if entries is not None else f"{paths.league_yml} is missing"))
    except LeagueYmlError as exc:
        checks.append(Check("league_yml", False, str(exc)))
    checks.append(_yaml_check("preferences", paths.preferences, "target_composition"))
    kb_ok = (paths.kb / "README.md").is_file() and (paths.kb / "rules" / "aliases.yml").is_file()
    checks.append(Check("kb", kb_ok, f"{paths.kb}" + ("" if kb_ok else " lacks README.md or rules/aliases.yml")))
    try:
        checks.append(Check("modules", True, f"{len(load_modules())} modules"))
    except (ModuleTableError, OSError, ValueError) as exc:
        checks.append(Check("modules", False, str(exc)))
    return checks
```

- [ ] **Step 4: Add the CLI command**

Append to `core/src/fantaclaude/cli/app.py`:

```python
def _render_doctor(payload: dict) -> str:
    lines = [f"{'ok ' if c['ok'] else 'FAIL'}  {c['name']:<16} {c['detail']}" for c in payload["checks"]]
    lines.append("ready" if payload["ok"] else "not ready")
    return "\n".join(lines)


@app.command("doctor")
def doctor_cmd(json_: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Readiness check: credentials, token cache, database, snapshots, league.yml, kb, module table."""
    from fantacalcio_mcp.config import env_path, token_cache_path

    from fantaclaude.commands.doctor import DoctorPaths, run_doctor
    from fantaclaude.paths import db_path, kb_dir, league_yml_path, preferences_yml_path
    from fantaclaude.timeutil import utc_now

    paths = DoctorPaths(env=env_path(), token_cache=token_cache_path(), db=db_path(),
                        league_yml=league_yml_path(), preferences=preferences_yml_path(), kb=kb_dir())
    checks = run_doctor(paths, now=utc_now())
    payload = {"ok": all(c.ok for c in checks), "checks": [c.to_dict() for c in checks]}
    emit(payload, json_=json_, render=_render_doctor)
    if not payload["ok"]:
        raise typer.Exit(code=ExitCode.NOT_READY)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run poe test-core`
Expected: `67 passed`.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/commands/doctor.py core/src/fantaclaude/cli/app.py core/tests/test_doctor.py
git commit -m "feat(cli): doctor readiness checks"
```

---

### Task 14: READMEs, CLAUDE.md, and the exactly-once live verification

**Files:**
- Create: `core/README.md`
- Modify: `mcp/fantacalcio/README.md` (sections "Configuration", "Registering with Claude Code", "Running the tests"), `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation only, plus the one live run of `sync-league` and `ingest listone` that seeds `data/`.

- [ ] **Step 1: Write `core/README.md`**

```markdown
# fantaclaude (core)

The data spine and CLI behind the Fantacalcio Mantra assistant. Design:
`docs/superpowers/specs/2026-08-22-fantaclaude-design.md`.

## Commands

Every read command takes `--json`; exit codes are a contract
(`0` ok, `1` error, `2` usage, `3` not ready, `4` league.yml conflicts with the API).

| command | does |
| --- | --- |
| `fantaclaude sync-league` | appends a `league_settings` snapshot when the rules hash moves; refuses (exit 4) if `league.yml` disagrees with the API |
| `fantaclaude ingest listone` / `ingest all` | fetches the listone into `data/raw/listone/` and snapshots it into DuckDB |
| `fantaclaude schema` | tables, views, columns — what `query` may name |
| `fantaclaude query --sql …` | read-only SQL; prefer the `v_*` views |
| `fantaclaude kb audit` | expired or malformed knowledge-base documents |
| `fantaclaude doctor` | readiness: credentials, token cache, database, snapshots, `league.yml`, `kb/`, module table |

`sync-league` and `ingest` call the live league API with the account in `.env`.
**Run them when you need fresh data, once — never in a loop.** Everything else
is local.

## Layout

`data/` (gitignored) holds `fanta.duckdb` and the immutable dated raw files;
`records/` (committed) will hold durable exports from Phase 1; `kb/` is the
knowledge base; `league.yml` carries provenanced facts the API cannot express;
`preferences.yml` the user's computation-affecting choices.

## Development

```bash
uv sync                # once, at the workspace root
uv run poe test        # both suites: mcp/fantacalcio/tests then core/tests
uv run poe lint
```

The `fantacalcio_mcp` package is imported as a library (`fantaclaude.api_client`);
its `.env`, `.auth/tokens.json` and the cross-process lock beside it are shared.
```

- [ ] **Step 2: Update the MCP README**

In `mcp/fantacalcio/README.md`:

- In "Configuration", after the sentence ending `since an MCP client may launch the server from anywhere.`, add the paragraph: `The same file, the token cache in `.auth/` and the lock/stamp sidecars beside it are shared with the `fantaclaude` CLI (`core/`), which imports this package as a library — one login machinery for both.`
- Replace the JSON block in "Registering with Claude Code" with the current `.mcp.json` (the `--directory` form from Task 1) and change the sentence after it to: `Claude Code launches it over stdio from the workspace root's environment; run `uv sync` at the root once so the `.venv` exists.`
- Replace the "Running the tests" section body with: `From the workspace root, `uv run poe test-mcp` (or `uv run poe test` for both packages). The suite is fixture-driven and performs no network I/O at all. Running `uv run pytest` from inside `mcp/fantacalcio/` still works: uv resolves the workspace root automatically.`

- [ ] **Step 3: Extend CLAUDE.md**

Append to `CLAUDE.md`:

```markdown
## Workspace and tests

The repository is a uv workspace: `core/` (package `fantaclaude`) and
`mcp/fantacalcio/` (package `fantacalcio_mcp`) share one `uv.lock` and one
`.venv` at the root. `uv run poe test` runs both suites; neither touches the
network.

`fantaclaude sync-league` and `fantaclaude ingest …` call the live league API
with the real account — the same rule as `smoke.py`: run once when data is
needed, never repeatedly "to check". Everything else in the CLI is local.

`captured/` (gitignored) holds the 2026-08-23 listone and FantaAstaLive
local-state captures the test fixtures were extracted from; regenerate a
fixture with its `_extract*.py` script, never by hand. `data/` is gitignored
and rebuildable from `data/raw/`.
```

- [ ] **Step 4: The exactly-once live verification**

These four commands hit the live API — twice in total (one `sync-league`, one `ingest listone`). Run them once, read the output, and do not repeat them to "confirm". If `sync-league` exits 4, fix `league.yml` (it must never override the API) and run it once more; that is the only case a second run is expected.

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
uv run fantaclaude doctor                # expected: not ready -- "no database"
uv run fantaclaude sync-league           # expected: "changed: snapshot 1 (first snapshot)"
uv run fantaclaude ingest listone        # expected: "listone: snapshot 1, 539 rows (data/raw/listone/…)"
uv run fantaclaude doctor                # expected: every check ok, "ready"
```

Then, all local:

```bash
uv run fantaclaude schema | head -5
uv run fantaclaude query --sql "SELECT count(*) AS b FROM v_players_current WHERE list_contains(mantra_roles, 'B')"
uv run fantaclaude query --sql "SELECT budget, team_count, rules_hash FROM v_league_settings_current" --json
uv run fantaclaude kb audit
uv run fantacalcio-mcp --help
```

Expected: `b = 12`; budget `500`, team count `8` (or whatever the league reports today — that is the point of not hardcoding it); `kb audit` lists `0 documents`; the MCP entry point still starts from the root environment. In Claude Code, `/mcp` must show `fantacalcio` connected after the `.mcp.json` change.

- [ ] **Step 5: Run everything one last time**

Run: `uv run poe test && uv run poe lint`
Expected: `100 passed` (MCP) then `67 passed` (core); ruff reports no errors. Fix any lint finding in place.

- [ ] **Step 6: Commit**

```bash
git add core/README.md mcp/fantacalcio/README.md CLAUDE.md
git commit -m "docs: workspace layout, CLI reference, and the live-call rule"
```

---

## Self-Review

**Spec coverage, Phase 0a row and the sections it draws on:**

| spec requirement | task |
| --- | --- |
| uv workspace, `.mcp.json` resolving via the root lock | 1 |
| MCP token cache: file lock, cache re-read, shared cooldown stamp | 3 |
| MCP `players()` for the listone endpoint (extension, no tool) | 2 |
| DuckDB is the only database; snapshot tables, nothing overwritten; `v_*` views for `query` | 6, 7, 10 |
| `league_settings` append-only with `season_id`, `fetched_at`, `rules_hash`; "a settings change is surfaced, not absorbed" | 7, 9 |
| `league.yml` with `source:`/`verified_on:` on every key; fails loud on disagreement | 8, 9 |
| `preferences.yml` versioned, computation-affecting choices | 8 (scaffold; read by Phase 1) |
| Mantra role model: twelve roles incl. B; module table as domain data; exact matching | 4, 5 |
| listone via `fantacalcio_mcp.api`, dated immutable raw files, idempotent ingest | 10 |
| Skill ↔ Python contract: `--json`, exit codes, `--help`, importable commands | 1, 9–13 |
| `fantaclaude schema`, `query --sql`, `doctor`, `kb audit` | 11, 12, 13 |
| DuckDB extensions verified ahead of time | 13 (`json`, `parquet` are built in) |
| `kb/` tree, front-matter contract, `aliases.yml` | 12 |
| `records/` exists for durable exports | 1 |
| Secrets never in fixtures; scanners assert on shapes | 2, 10 |

**Deliberately not in this plan** (each is named in the spec as a later phase): `fantaclaude rank` and the superseding of `valuations` runs (Phase 1 — the `SyncReport.diff` is what it will consume); the fantavoto scoring function (Phase 1, when event counts exist); the name matcher behind `player_aliases` (Phase 0b, with the first second source); `player_season`/`player_match`, `calendar`, `advanced` adapters (Phase 0b, after the website-login discovery); `fanta-kb` skills and the kb prose bootstrap (Phase 0b); `kb move-player` (there are no player notes to move yet).

**Placeholder scan:** no `TBD`, `TODO`, "implement later", "add validation", "similar to Task N"; every code step carries its code. The one intentional reference to existing text is Task 3's "(existing docstring unchanged)", which names a docstring already in the file.

**Type consistency:** `emit(payload, *, json_, render)`, `ExitCode`, `record_snapshot(con, snap, *, fetched_at=None)`, `snapshot_from_payloads(*, profile, status, rosters, lineup, calculate, teams)`, `RawStore.write(kind, payload, *, fetched_at=None)`, `load_listone(path)`, `record_listone(con, rows, raw)`, `run_doctor(paths, *, now)`, `audit(kb_dir, today)`, `fake_api(overrides=None)`, `to_db`/`utc_now` are used with the same names and signatures in every task that touches them. Test counts per task assume the sequence above: 6 → 13 → 22 → 29 → 34 → 43 → 48 → 57 → 60 → 63 → 67 (core) and 91 → 93 → 100 (MCP).
