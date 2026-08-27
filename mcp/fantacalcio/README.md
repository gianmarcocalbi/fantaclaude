# fantacalcio-mcp

An MCP server exposing **read-only** access to a private Leghe Fantacalcio.it
league, for personal use with Claude Code (or any MCP client).

It talks to Fantacalcio.it's own non-public app API (the same one the
official mobile/web app uses), not any documented public API. It is built
for one person to read their own league's data — there is no write surface
anywhere in this codebase, and none should be added.

## Requirements

- **Python 3.14.7 (final)** — not 3.14.0rc2. An rc2 interpreter hits a
  `TypeError: _eval_type() ... prefer_fwd_module` failure mode during
  Pydantic model evaluation that final 3.14.7 does not; if `uv python list
  --all-versions` shows an rc2 build in play, run `uv python install 3.14.7`
  to get the final release and re-sync (`uv sync`) before doing anything
  else.
- [`uv`](https://docs.astral.sh/uv/) as the project/dependency manager.
- `fastmcp` — `pyproject.toml` declares `fastmcp>=3.4.7` (an open lower bound, not a pin); the version actually installed is whatever `uv.lock` resolved, currently `3.4.7`. That exact version is what the `show_banner=False` stdio option (see `__main__.py`) was verified against via `inspect.signature`; running `uv lock --upgrade-package fastmcp` can move the resolved version forward, so re-check that signature if you do.

## Configuration

All configuration lives in a `.env` file at the **workspace root**
(`/Users/grimid3v/Workspace/fantaclaudio/.env`), not inside `mcp/fantacalcio/`.
The server locates it independent of the process's working directory, since
an MCP client may launch the server from anywhere.

The same file, the token cache in `.auth/` and the lock/stamp sidecars
beside it are shared with the `fantaclaude` CLI (`core/`), which imports
this package as a library — one login machinery for both.

| Variable | Required | Meaning |
| --- | --- | --- |
| `FANTACALCIO_APP_KEY` | yes | The app key the Fantacalcio.it API expects on every request. |
| `FANTACALCIO_USERNAME` | for login mode | Account username/email. |
| `FANTACALCIO_PASSWORD` | for login mode | Account password. Prefer the keychain (below) over putting this in `.env`. |
| `FANTACALCIO_LEAGUE_TOKEN` | for token-only mode | A previously captured JWT, used directly with no ability to self-refresh on expiry. |
| `FANTACALCIO_API_BASE_URL` | no | Overrides the default API base URL. |

You need either `FANTACALCIO_USERNAME` + `FANTACALCIO_PASSWORD` ("login
mode" — the server can log in again on its own when a token expires), or
`FANTACALCIO_LEAGUE_TOKEN` alone ("token-only mode" — no self-healing; once
the pasted token expires, tool calls fail until you paste a fresh one).

**Precedence when both are set:** if `FANTACALCIO_USERNAME` +
`FANTACALCIO_PASSWORD` *and* `FANTACALCIO_LEAGUE_TOKEN` are all present,
login mode wins outright (`Credentials.can_login` is `True`) and the
pasted `FANTACALCIO_LEAGUE_TOKEN` is silently never used — there is no
"force this specific token" behavior. If you need a specific pasted
token to actually take effect, remove `FANTACALCIO_USERNAME`/
`FANTACALCIO_PASSWORD` (and the keychain entry, if any) so the server
falls into token-only mode.

### Storing the password in the keychain (recommended)

Rather than put a plaintext password in `.env`, store it in the macOS
keychain under the service the server already looks for:

```bash
security add-generic-password -s fantacalcio-mcp -a <your-username> -w
```

You'll be prompted for the password interactively (it isn't an argument, so
it never ends up in shell history). When `FANTACALCIO_USERNAME` is set, the
server checks the keychain first and only falls back to
`FANTACALCIO_PASSWORD` in `.env` if nothing is found there.

### Which auth mode actually gets exercised

The two modes are not equally battle-tested against the live service.
**Token-only mode never calls `POST /login` at all** —
`Auth.token_for()` short-circuits and hands back the pasted
`FANTACALCIO_LEAGUE_TOKEN` directly, so the account's password-based
self-healing path (401 recovery, cooldown, single-flight login — the
logic Tasks 4 and 5 hardened over five fix rounds) is never touched in
that mode, live or otherwise. Only **login mode** (`FANTACALCIO_USERNAME`
+ `FANTACALCIO_PASSWORD` set) exercises that code path against the real
server. `scripts/smoke.py` prints which mode is active (see below) so a
clean run's endpoint `OK`s are never mistaken for having verified both
paths. To switch from token-only to login mode, set `FANTACALCIO_USERNAME`
and either `FANTACALCIO_PASSWORD` or a keychain entry (see below), and
drop `FANTACALCIO_LEAGUE_TOKEN` if you want token-only mode instead (see
the precedence note above for what happens if you leave both set).

## Tools

The server exposes exactly seven read-only tools, all scoped to the
signed-in account's league (pass `league`, the league alias, only if the
account belongs to more than one league):

- **`get_account`** — the signed-in account's id, username, and every
  league it belongs to.
- **`get_league`** — one league's identity (name, id, alias, founding year,
  president, admins, team count) plus its live status (season, matchday,
  kickoff time). Never returns the league's join password.
- **`get_league_settings`** — roster budget/size limits, lineup rules
  (bench size, allowed formations), substitutions allowed, and the
  bonus/malus point table.
- **`get_my_team`** — the signed-in user's own team: name, division,
  credits, roster composition, co-managers.
- **`list_teams`** — every team in the league with managers, credits and
  division (optionally including pending, unaccepted invitations); manager
  email addresses are always stripped.
- **`list_competitions`** — the competitions configured in the league.
- **`get_server_time`** — Fantacalcio's own server clock, for reasoning
  about deadlines relative to a matchday's kickoff time.

## Running the smoke test

`scripts/smoke.py` is a standalone script — deliberately **not** part of the
pytest suite — that exercises the real, live API with your real
credentials. It first prints which credential mode is active (`mode:
token-only (no login path exercised)` or `mode: login (username/
password)` — see "Which auth mode actually gets exercised" above), then
calls six read-only endpoints and prints one `OK`/`FAIL` line per
endpoint:

```bash
cd mcp/fantacalcio
uv run python scripts/smoke.py
```

This performs real network calls against your live account. Run it
sparingly — not in a loop, not repeatedly "to confirm" — since each run
that needs to log in hits the same authentication endpoint a real account
can be rate-limited or locked on. A `FAIL` mentioning `ATH018` means the
configured credentials are wrong; do not retry blindly, fix the credentials
first.

## Registering with Claude Code

The workspace root's `.mcp.json` already registers this server:

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

Claude Code launches it over stdio from the workspace root's environment; run
`uv sync` at the root once so the `.venv` exists.

## Running the tests

From the workspace root, `uv run poe test-mcp` (or `uv run poe test` for both
packages). The suite is fixture-driven and performs no network I/O at all.
Running `uv run pytest` from inside `mcp/fantacalcio/` still works: uv
resolves the workspace root automatically.
