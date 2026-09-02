# fantaclaude Phase 2b — Feed, Server, Dashboard, and the Auction MCP: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put transport and surfaces around Phase 2a's one `mutate()` path: the
FantaAstaLive Firebase feed (`ingest/asta_live.py`), the `asta serve` process
(FastAPI + WebSocket, one owner of live state, the state file written on every
change), the Vite/React/shadcn dashboard (`web/`), and the auction MCP
(`fantaclaude-asta`) served over HTTP by `asta serve` itself — so that on
auction night the operating procedure is `fantaclaude asta serve`, open
localhost, answer the mapping screen, and watch the board follow the room.

**Architecture:** Phase 2a built the whole brain — state machine, advisor,
pricing, adjustments, pressure, snapshot — as pure, importable functions with
one mutation path (`asta/auction.py::Auction.mutate`). 2b adds *no* new
domain logic: the feed adapter is transport only (SSE in, parsed `Snapshot`s
out; the set-diff already lives in `asta/state.py`), the server is an async
shell around `Auction` (one `asyncio.Lock`, `mutate` in a worker thread, state
file + WebSocket broadcast as listeners), the dashboard is a renderer of one
JSON payload (`Board.to_dict()`), and the MCP tools read the same in-memory
`Board` the dashboard shows. Everything is testable without a network:
the server runs from a replayed capture or a state file exactly as it runs
from the live feed.

**Tech Stack:** Python 3.14 (FastAPI, uvicorn, httpx, FastMCP 3, duckdb,
Typer, pydantic v2 — all already conventions of this repo except FastAPI/
uvicorn/FastMCP which Task 5/6 add to `core`), Vite + React + TypeScript +
Tailwind (v4) + shadcn/ui in `web/`, openapi-typescript for generated types,
pytest + respx + starlette TestClient for tests.

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` — sections
"A second MCP, for the auction", "The skill ↔ Python contract", "One database,
and the auction is not in it", "Succession, not reconciliation", "Concurrency:
one owner of state, and two classes of query", "Live adjustments",
"`fanta-asta` — live auction copilot" (the live feed, the adapter's rules,
what the model is for, division of surfaces, dossiers loaded not read live),
"Dashboard architecture" (including "Requirements specific to a single-shot
live event" 1–7), "Testing" (the live feed, replay, crash recovery, CLI),
"Phasing" (the 2b row: land **2 September**; freeze + rehearsal 3 September),
open questions 4, 9, 10, and "Non-goals". The Phase 2a plan
(`docs/superpowers/plans/2026-08-30-fantaclaude-phase-2a-asta-core.md`)
defines every interface this plan consumes; the code on `main` at `97fdd92`
is the truth where the two differ.

## Global Constraints

- **Deadline: 2b lands 2 September 2026.** The freeze + full mock rehearsal is
  3 September; the auction ~5 September. Tasks are ordered so a late cut still
  leaves a working serve + dashboard: feed and server first, dashboard next,
  polish last. Per the spec, **the feed is not cuttable** — nothing sits
  behind it but the printed tier board.
- **No test touches the network** (repo rule, both suites). Firebase, uvicorn
  and the browser are exercised through respx, `httpx.MockTransport`,
  starlette's `TestClient`, and replayed captures. The only code that ever
  opens a live connection is `asta serve` at runtime.
- **Live network discipline:** `asta serve` subscribes to the FantaAstaLive
  Firebase session — anonymous sign-in, **exactly one subscriber** (the
  server; no CLI and no MCP tool connects to Firebase), reconnect with
  backoff, token refreshed ahead of expiry. It never calls the league API,
  never re-syncs, never ranks. Do not connect to a live session "to check"
  during development; the replay harness exists so the feed's first real
  exercise is not auction night.
- **Every other `fantaclaude asta` command stays local.** `asta adjust` and
  the new `asta refresh` may additionally talk to a *running local server*
  (`http://127.0.0.1:8765` by default) and fall back to the offline path
  (adjust) or refuse (refresh) when nothing is listening.
- **The mirror is faithful.** No local correction path, no override flag;
  whatever the admin records is what the board shows. Credits derive from
  `picks[]`, never from `teams[].currentBudget`.
- **Session settings are authoritative for the night**; a conflict with the
  league's own bounds is surfaced loudly at connect (before bidding opens) and
  on every settings change, never absorbed.
- **Nothing writes DuckDB during the auction.** The server opens
  `data/fanta.duckdb` read-only, per-query, inside `asyncio.to_thread`;
  analytical MCP queries run there too. In-memory auction state is read
  directly on the event loop.
- **One writer for `data/adjustments.yml`**: the running server. The CLI, the
  MCP tool and the dashboard form all proxy to it; the offline CLI path is the
  single writer when no server runs. Appends stay text-first and atomic
  (`append_adjustment`).
- **`data/asta-state.json` is written atomically on every mutation**
  (`render_state` → `write_state`), and `records/` files are never rewritten.
- **Scrubbing:** an email-shaped nick never reaches a payload, a state file, a
  tool result or the DOM (`scrub_label` at ingestion, `_scrub_nick` at the
  state file — both exist; the server adds no new path around them). The
  session code is refused at ingestion if it is not a name
  (`session_code_is_path`).
- **Secrets:** there are none in this phase — Firebase sign-in is anonymous;
  the client config is public app configuration, not a credential. Nothing
  new enters `.env`. No command prints a token; errors carry response codes,
  never bodies that could echo one.
- **Exit-code contract** (CLI): 0 OK, 1 crash, 2 usage (`UsageError`,
  unknown scenario, bad flag combinations), 3 not ready (`NotReady`: missing
  run, malformed files, no server for `refresh`), 4 conflict. HTTP mapping in
  the server: 409 phase errors ("answer the mapping screen"), 422 bad input,
  503 never used for domain errors.
- **Localhost only by default** (`--host 127.0.0.1`): serving the room is a
  spec non-goal. Port default **8765**.
- **Python ≥ 3.14.7**; uv workspace; `uv run poe test`, `uv run poe lint` and
  `uv run poe docs-build` must pass at every task's end; `poe web-build` must
  pass from Task 9 on.
- **Out of scope, decided 2026-08-31 with the user:** `verify-transfer` and
  the deletion of the state files (blocked on open question 9 — the roster
  endpoint is unmapped and only observable after the admin's transfer;
  becomes its own small post-auction task), the A RILANCI bid ladder (open
  question 10 — the fields are read at the rehearsal if that mode is chosen;
  the state machine already ignores unknown node fields), `market_prices` /
  `calibration` (Phase 3), and the auction journal entry (`fanta-market`
  writes it).
- **Commit discipline:** conventional messages, no Claude session links, no
  co-author trailers (CLAUDE.md). One commit per task as written in each
  task's final step.

## Source facts (verified while planning, 2026-08-31)

Recorded here so no task has to rediscover them.

**FantaAstaLive's Firebase client config** — read from the public web app's
own bundle (`https://fanta-asta-live.fantacalcio.it/` → `main-VJKJAFYQ.js` →
`chunk-E2X65QDE.js`), 2026-08-31. This is the config the app itself ships to
every visitor's browser; sign-in is anonymous (`accounts:signUp`, no email),
so none of it is a credential:

```
apiKey:      AIzaSyAji5aMonqYhjfCnHU6YW4TgwOIh8x302Y
databaseURL: https://leghe-fantagazzetta-app.firebaseio.com
projectId:   leghe-fantagazzetta-app
authDomain:  leghe-fantagazzetta-app.firebaseapp.com
```

The bundle reads and writes `sessions/${id}/...` nodes (`state`, `env`,
`messages`, `peers` observed in the code), matching the spec's live
verification of 2026-08-23 (`/sessions/<code>/state`; observed session code
shape `FA-nri-okm`). If the app re-deploys against a different project,
connect fails loudly at startup and the constants are re-read from the
bundle — a comment in `asta_live.py` says exactly that.

**Firebase REST endpoints** (standard, stable Google APIs):

- Anonymous sign-up: `POST
  https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={apiKey}`
  with JSON `{"returnSecureToken": true}` → `{"idToken", "refreshToken",
  "expiresIn": "3600", "localId"}` (`expiresIn` is a **string** of seconds).
- Refresh: `POST https://securetoken.googleapis.com/v1/token?key={apiKey}`
  with **form** body `grant_type=refresh_token&refresh_token=…` →
  `{"id_token", "refresh_token", "expires_in"}` (snake_case here).
- Streaming read: `GET
  {databaseURL}/sessions/{code}/state.json?auth={idToken}` with header
  `Accept: text/event-stream`. The server answers an SSE stream of
  `event:`/`data:` frames: `put` and `patch` carry
  `{"path": "/…", "data": …}`; `keep-alive` (data `null`) arrives every
  ~30–45 s; `auth_revoked` means the token expired mid-stream (reconnect with
  a fresh one); `cancel` means the security rules deny the read (fatal). The
  endpoint may answer **307** to a same-database follower host — the client
  must follow redirects. A `put` at path `/` with `data: null` means **no
  such session**.

**FastMCP 3.4.7** (already in the workspace lock via `fantacalcio-mcp`):
`FastMCP.http_app(path=None, …, transport="http", stateless_http=None, …) ->
StarletteWithLifespan`. The returned app mounts into FastAPI; its `.lifespan`
must be run by the outer app's lifespan or the transport never starts.
`fastmcp.Client(mcp_instance)` drives tools in-process for tests.

**Toolchain:** node v24.14.0 and npm 11.9.0 are on the machine. `fastapi` is
not yet installed; `uvicorn 0.52.4`, `starlette 1.6.0`, `sse-starlette` are
already in `.venv` as fastmcp dependencies but `core` must declare what it
imports.

**Phase 2a interfaces this plan consumes** (all on `main` at `97fdd92`):

- `asta/state.py`: `Snapshot`, `parse_snapshot(node) -> Snapshot` (raises
  `SnapshotError`), `read_snapshots(path) -> list[Snapshot]` (JSONL),
  `AuctionState`, `apply_snapshot(state, snap) -> (AuctionState,
  tuple[Event, ...])`, event types `SaleAdded/SaleRemoved/CostEdited/
  LotSelected/SettingsChanged/StatusChanged`.
- `asta/auction.py`: `Auction(run, mapping, *, settings=None, layer=EMPTY_LAYER,
  scenario=None, participants=None)`, `.mutate(change: Snapshot | Refresh) ->
  MutationResult(events, board)`, `.subscribe(listener)`, `Refresh(layer=None,
  participants=None)`. `mutate` raises `SessionError` on unreadable session
  settings and `UnknownScenarioError` from the constructor's first derive.
- `asta/advisor.py`: `Board` (`.to_dict()`, `.tiers(n)`, `.me`,
  `.price_of(pid)`, `.problems`, `.league_conflicts`, `.pressure`),
  `TeamMapping(mine, nicks)`, `derive(...)`.
- `asta/pinned.py`: `PinnedRun` (`.players: dict[int, PinnedPlayer]`,
  `.league: SessionSettings`, `.describe()`, `.candidates()`, `.scenario(name)`),
  `load_pinned_run(con, run_id=None)` (raises `PinnedRunError`).
- `asta/session.py`: `SessionSettings`, `session_from_feed(settings, *,
  team_count)` (raises `SessionError`), `compare(session, league) -> list[str]`.
- `asta/adjustments.py`: `Adjustment`, `adjustment_from_entry(raw, where)`,
  `append_adjustment(path, adjustment)`, `load_adjustments(path)`,
  `resolve(adjustments, candidates, *, sha256="")` → `AdjustmentLayer`,
  `file_sha256(path)`, `AdjustmentsError`.
- `asta/snapshot.py`: `render_state(board, *, session_code, written_at)`,
  `write_state(path, payload)`, `read_state(path) -> StoredState(snapshot,
  mapping, session_code, run_id, scenario, written_at, payload)`,
  `session_code_is_path(code)`, `StateFileError`.
- `asta/pricing.py`: `explain(board_pricing, player_id) -> dict`, `Band(p25,
  p50, p75)`, `PlayerPrice`, `BoardPricing`.
- `commands/asta.py`: `AstaPaths(db, adjustments, state, records, kb)`,
  `open_run(con, run_id)`, `load_layer(path, run)`, `load_dossiers(kb_dir)`,
  `resolve_mapping(teams, *, me, maps, participants, remembered=None)`,
  `_settings(snapshot, run)`, `_player(run, key)`, `describe_event(event, run,
  labels)`, `UsageError`; `commands/ingest.py::NotReady`.
- `kb/participants.py`: `Participant` (`.nick`, `.to_dict()`),
  `load_participants(kb_dir)`.
- `cli/app.py`: `ExitCode`, `emit(payload, *, json_, render)`,
  `_asta_errors()`, `_asta_paths()`, `_open_read_only()`, option singletons
  `RUN_OPTION`, `ONE_SCENARIO_OPTION`, `ME_OPTION`, `MAP_OPTION`.
- `atomic.py::write_atomic(path, data: bytes)`; `timeutil.utc_now()`;
  `values.json_safe`; `paths.py` (every location helper).
- Test helpers: `core/tests/test_advisor.py::pinned_run(tmp_path,
  fixture_json, mcp_fixture_json, **kw)` → `(RankResult, PinnedRun)` and
  `node(picks, *, selected=None, teams=(0, 1, 2), settings=SESSION)` →
  `AuctionState`; `SESSION = {"budget": 500, "game": 2, "roles": {"gk": [3,
  3], "mov": [22, 22], "size": [25, 25]}}`; `core/tests/test_asta_cli.py::
  _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)` → run id in
  a full CLI workspace (FANTACALCIO_HOME monkeypatched) with one dossier
  (`marco.md`); `core/tests/fixtures/asta_session_sample.jsonl` (a captured
  session: several snapshots, sales, an undo, a cost edit).

**`Board.to_dict()` — the wire payload.** Keys, exactly as produced today
(everything already `json_safe`; `-inf` → `null`): `run_id: str`,
`scenario: str`, `settings: {budget, goalkeepers: [lo, hi], outfield: [lo,
hi], size: [lo, hi], game, team_count, source}`, `league_conflicts: [str]`,
`problems: [str]`, `status: str|null`, `locked: bool|null`, `picks: int`,
`me: LedgerDict`, `teams: [LedgerDict]` where `LedgerDict = {team_id, label,
nick: str|null, budget, spent, credits, picks: [player_id], goalkeepers,
outfield, unknown, missing_goalkeepers, missing_outfield, open_slots}`,
`market_credits: int`, `inflation: float`, `composition: {class: int}`,
`credits_by_class: {class: int}`, `reserve: int`, `budget: int`,
`slot_price: float`, `targets_departed: [str]`, `completion_value:
float|null`, `selected: int|null`, `lot: {player_id, name, team_short,
role_class, roles: [str], tier, band: {p25, p50, p75}|null, expected_price:
int|null, sold_to: int|null}|null`, `lot_pressure: PressureDict|null`,
`adjustments: {count, applied, value_factor: {pid_str: float}, excluded:
[int], targets: {class: int}, problems: [str], sha256}`, `prices: {pid_str:
{player_id, name, team_short, role_class, roles, tier, band, expected_price,
value_p50, pressure?: PressureDict}}` with `PressureDict = {player_id,
expected, estimate, bidders: [{team_id, label, nick, intent, credits, depth,
overpay, ceiling, reasons: [str]}]}`.

## File structure

```
core/src/fantaclaude/
├── ingest/asta_live.py        # NEW  Task 1+2 — Firebase auth, SSE stream, node → Snapshot, capture
├── api/                       # NEW package (spec tree: "api/  FastAPI: REST + WebSocket, serves the frontend")
│   ├── __init__.py            # NEW  Task 3 — empty
│   ├── models.py              # NEW  Task 3 — pydantic mirrors of the wire payloads (the typed contract)
│   ├── serve.py               # NEW  Task 4 — AstaServer: one owner of live state, async shell around Auction
│   ├── app.py                 # NEW  Task 5 — create_app(): REST + WS + static + /mcp mount
│   └── openapi_dump.py        # NEW  Task 9 — print the OpenAPI document for `poe types`
├── asta/mcp.py                # NEW  Task 6 — build_mcp(): the fantaclaude-asta tool surface
├── commands/serve.py          # NEW  Task 7 — ServeOptions, prepare(), run_serve(): startup orchestration
├── commands/asta.py           # MOD  Task 8 — server_adjust()/server_refresh() proxies
├── commands/doctor.py         # MOD  Task 7 — dashboard-bundle check
├── cli/app.py                 # MOD  Task 7 (serve) + Task 8 (refresh, adjust --server)
└── paths.py                   # MOD  Task 2 (asta_captures_dir) + Task 7 (web_dist_dir)
core/tests/
├── test_asta_live.py          # NEW  Task 1+2
├── test_api_models.py         # NEW  Task 3
├── test_api_serve.py          # NEW  Task 4
├── test_api_app.py            # NEW  Task 5
├── test_asta_mcp.py           # NEW  Task 6
├── test_serve_cli.py          # NEW  Task 7
└── test_asta_cli.py           # MOD  Task 8 — proxy + refresh command tests
web/                           # NEW  Task 9 (scaffold), 10–11 (the dashboard)
├── package.json  vite.config.ts  tsconfig*.json  components.json  index.html
└── src/
    ├── main.tsx  App.tsx  index.css
    ├── api/schema.d.ts        # generated by `poe types`, committed
    ├── api/types.ts           # WS envelope + aliases over the generated schema
    ├── ws.ts                  # reconnecting WebSocket hook
    ├── lib/format.ts          # band/credits formatting helpers
    └── components/            # MappingGate, StatusBar, LotPanel, TierBoard,
                               # MyPanel, Ledgers, AdjustForm, Problems, EventLog
pyproject.toml                 # MOD  Task 9 — poe web-dev / web-build / types
.mcp.json                      # MOD  Task 6 — fantaclaude-asta HTTP entry
.gitignore                     # MOD  Task 9 — web/node_modules, web/dist, web/openapi.json
CLAUDE.md                      # MOD  Task 12 — asta serve network carve-out; verify-transfer note
README.md                      # MOD  Task 12 — Capabilities + Layout
site/docs/{architecture,cli,mcp}.md  # MOD  Task 12
.claude/skills/fanta-asta/SKILL.md   # MOD  Task 12 — the live half
docs/asta-night-runbook.md     # NEW  Task 12 — the night's operating procedure + rehearsal drills
```

Design decisions locked by this structure, so no task re-litigates them:

- **The adapter is transport only.** `asta_live.py` maintains the raw node,
  parses each new state into a `Snapshot`, and hands it to an async callback.
  It never imports the advisor, the server, or anything under `api/`.
- **The server is callback-shaped, not framework-shaped.** `AstaServer` knows
  nothing about FastAPI: WebSocket clients register plain
  `async (str) -> None` senders; `app.py` adapts. That is what makes Task 4
  testable without HTTP and keeps exactly one `mutate()` owner.
- **Mapping is a server phase, not middleware.** The server starts `pending`
  unless flags or a state file answer the mapping; `POST /api/mapping` (the
  screen) or the pending `--me`/`--map` flags move it to `live`. The server
  persists nothing of the mapping (spec: the browser's localStorage pre-fills
  the screen; the state file carries it as a side effect of `render_state`).
- **The board payload is `Board.to_dict()`, verbatim.** The dashboard and the
  REST/WS surface add an envelope around it, never reshape it. The pydantic
  models in `api/models.py` mirror it field for field with `extra="forbid"`,
  and one round-trip test pins the contract; a drift on either side is a red
  test, which is the "types are generated, not hand-written" requirement made
  enforceable.
- **Replay and the live feed drive the same server.** `asta serve --replay
  <file> --speed N` feeds the same `on_snapshot` path the SSE stream feeds,
  so the rehearsal exercises the true pipeline with no network.

---

### Task 1: Feed adapter, part 1 — Firebase constants, anonymous auth, session-code guard

**Files:**
- Create: `core/src/fantaclaude/ingest/asta_live.py`
- Test: `core/tests/test_asta_live.py`

**Interfaces:**
- Consumes: `fantaclaude.asta.snapshot.session_code_is_path(code: str) -> bool`.
- Produces (used by Task 2 in the same module, and by Task 7's serve command):
  `FeedError(RuntimeError)`; `check_session_code(code: str) -> str`;
  `AnonymousAuth(client: httpx.AsyncClient, *, api_key: str = FIREBASE_API_KEY,
  now: Callable[[], float] = time.monotonic)` with `async token() -> str` and
  `invalidate() -> None`; module constants `FIREBASE_API_KEY`,
  `FIREBASE_DATABASE_URL`, `SIGNUP_URL`, `TOKEN_URL`, `TOKEN_REFRESH_MARGIN`.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/test_asta_live.py
import httpx
import pytest
import respx

from fantaclaude.ingest.asta_live import (
    FIREBASE_API_KEY,
    SIGNUP_URL,
    TOKEN_URL,
    AnonymousAuth,
    FeedError,
    check_session_code,
)


def test_session_codes_are_names_never_paths():
    assert check_session_code(" FA-nri-okm ") == "FA-nri-okm"
    for bad in ("", "  ", "FA/okm", "..", "FA\\okm", "FA\x00okm"):
        with pytest.raises(FeedError):
            check_session_code(bad)


@respx.mock
async def test_signup_once_then_cached_until_the_margin():
    respx.post(SIGNUP_URL).respond(200, json={
        "idToken": "tok-1", "refreshToken": "ref-1", "expiresIn": "3600", "localId": "anon"})
    clock = [0.0]
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client, now=lambda: clock[0])
        assert await auth.token() == "tok-1"
        clock[0] = 3600 - 301                       # still inside the margin
        assert await auth.token() == "tok-1"
    assert respx.calls.call_count == 1
    assert respx.calls.last.request.url.params["key"] == FIREBASE_API_KEY


@respx.mock
async def test_refresh_ahead_of_expiry_uses_the_refresh_token():
    respx.post(SIGNUP_URL).respond(200, json={
        "idToken": "tok-1", "refreshToken": "ref-1", "expiresIn": "3600", "localId": "anon"})
    refresh = respx.post(TOKEN_URL).respond(200, json={
        "id_token": "tok-2", "refresh_token": "ref-2", "expires_in": "3600"})
    clock = [0.0]
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client, now=lambda: clock[0])
        await auth.token()
        clock[0] = 3600 - 299                       # past the margin: refresh fires
        assert await auth.token() == "tok-2"
    body = refresh.calls.last.request.content.decode()
    assert "grant_type=refresh_token" in body and "refresh_token=ref-1" in body


@respx.mock
async def test_a_failed_refresh_falls_back_to_a_fresh_anonymous_signup():
    signup = respx.post(SIGNUP_URL)
    signup.side_effect = [
        httpx.Response(200, json={"idToken": "tok-1", "refreshToken": "ref-1", "expiresIn": "3600", "localId": "a"}),
        httpx.Response(200, json={"idToken": "tok-3", "refreshToken": "ref-3", "expiresIn": "3600", "localId": "b"}),
    ]
    respx.post(TOKEN_URL).respond(400, json={"error": {"message": "TOKEN_EXPIRED"}})
    clock = [0.0]
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client, now=lambda: clock[0])
        await auth.token()
        clock[0] = 3600.0
        assert await auth.token() == "tok-3"        # anonymous: a new user is as good as the old one
    assert signup.call_count == 2


@respx.mock
async def test_a_refused_signup_is_a_feed_error_that_names_no_token():
    respx.post(SIGNUP_URL).respond(403, json={"error": {"message": "ADMIN_ONLY_OPERATION"}})
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client)
        with pytest.raises(FeedError) as err:
            await auth.token()
    assert "403" in str(err.value) and "tok" not in str(err.value)


async def test_invalidate_forces_the_next_token_to_be_fetched_again():
    with respx.mock:
        respx.post(SIGNUP_URL).respond(200, json={
            "idToken": "tok-1", "refreshToken": "ref-1", "expiresIn": "3600", "localId": "anon"})
        respx.post(TOKEN_URL).respond(200, json={
            "id_token": "tok-2", "refresh_token": "ref-2", "expires_in": "3600"})
        async with httpx.AsyncClient() as client:
            auth = AnonymousAuth(client, now=lambda: 0.0)
            await auth.token()
            auth.invalidate()                       # auth_revoked mid-stream lands here
            assert await auth.token() == "tok-2"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_asta_live.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.ingest.asta_live'`.

- [ ] **Step 3: Write the module (auth half)**

```python
# core/src/fantaclaude/ingest/asta_live.py
"""FantaAstaLive over Firebase: the live feed (spec, "The live feed:
FantaAstaLive over Firebase" and "The adapter, and the rules that keep it
safe").

Transport only. This module signs in anonymously, holds the SSE stream,
refreshes the token ahead of expiry, reconnects with backoff, maintains the
raw state node, and hands each new state to a callback as a parsed Snapshot.
The set-diff lives in asta/state.py; nothing here knows about boards,
dashboards or tools. Exactly one subscriber exists — the server owns the
stream; no CLI and no MCP tool connects here (spec, "Exactly one
subscriber").

The client config below is FantaAstaLive's own public web-app configuration,
read from the app's bundle (main-VJKJAFYQ.js → chunk-E2X65QDE.js) on
2026-08-31. It is configuration, not a credential: sign-in is anonymous
(accounts:signUp with returnSecureToken and no email), exactly the way the
app itself connects, and the token it yields can read only what the app's
own security rules let any participant read. If FantaAstaLive re-deploys
against a different project, connect fails loud at startup — re-read the
bundle and update these two constants.

The session code is refused at ingestion if it is not a name (spec: it
becomes a path component under records/asta/ and a key in the stream URL);
the guard is the same predicate the snapshot sink uses, applied where the
value arrives.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from fantaclaude.asta.snapshot import session_code_is_path
from fantaclaude.asta.state import Snapshot, SnapshotError, parse_snapshot

FIREBASE_API_KEY = "AIzaSyAji5aMonqYhjfCnHU6YW4TgwOIh8x302Y"          # verified 2026-08-31
FIREBASE_DATABASE_URL = "https://leghe-fantagazzetta-app.firebaseio.com"
SIGNUP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signUp"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
TOKEN_REFRESH_MARGIN = 300.0        # refresh this many seconds before expiry (spec: "refreshed ahead of expiry")
BACKOFF = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
READ_TIMEOUT = 90.0                 # keep-alives arrive every ~30-45s; silence past this is a dead stream

LIVE, RECONNECTING, OFFLINE = "live", "reconnecting", "offline"


class FeedError(RuntimeError):
    """The feed cannot be read: a refused sign-in, a session that does not
    exist, security rules that deny the read, or a node this code cannot
    parse. The message never carries a token."""


def check_session_code(code: str) -> str:
    """The session code as a name: stripped, non-empty, never a path."""
    code = (code or "").strip()
    if not code:
        raise FeedError("the session code is empty")
    if session_code_is_path(code):
        raise FeedError(f"session code {code!r} is a path, not a session code")
    return code


@dataclass
class _Token:
    id_token: str
    refresh_token: str
    expires_at: float


class AnonymousAuth:
    """One anonymous Firebase user: sign up once, refresh ahead of expiry,
    fall back to a fresh sign-up when the refresh is refused (anonymous —
    a new user reads exactly what the old one read)."""

    def __init__(self, client: httpx.AsyncClient, *, api_key: str = FIREBASE_API_KEY,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._client = client
        self._api_key = api_key
        self._now = now
        self._token: _Token | None = None

    def invalidate(self) -> None:
        """Drop the cached token (the stream said auth_revoked)."""
        if self._token is not None:
            self._token = _Token(self._token.id_token, self._token.refresh_token, self._now())

    async def token(self) -> str:
        tok = self._token
        if tok is not None and self._now() < tok.expires_at - TOKEN_REFRESH_MARGIN:
            return tok.id_token
        if tok is not None:
            try:
                return await self._refresh(tok.refresh_token)
            except FeedError:
                pass                                 # refused: fall through to a fresh sign-up
        return await self._signup()

    async def _signup(self) -> str:
        resp = await self._client.post(SIGNUP_URL, params={"key": self._api_key},
                                       json={"returnSecureToken": True})
        payload = self._payload(resp, "anonymous sign-in")
        self._token = _Token(str(payload["idToken"]), str(payload["refreshToken"]),
                             self._now() + float(payload.get("expiresIn") or 3600))
        return self._token.id_token

    async def _refresh(self, refresh_token: str) -> str:
        resp = await self._client.post(TOKEN_URL, params={"key": self._api_key},
                                       data={"grant_type": "refresh_token", "refresh_token": refresh_token})
        payload = self._payload(resp, "token refresh")
        self._token = _Token(str(payload["id_token"]), str(payload["refresh_token"]),
                             self._now() + float(payload.get("expires_in") or 3600))
        return self._token.id_token

    @staticmethod
    def _payload(resp: httpx.Response, what: str) -> dict[str, Any]:
        if resp.status_code != 200:
            code = None
            try:
                code = resp.json().get("error", {}).get("message")
            except (json.JSONDecodeError, AttributeError):
                pass
            raise FeedError(f"{what} answered {resp.status_code}" + (f" ({code})" if code else ""))
        return resp.json()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_asta_live.py -c core/pyproject.toml -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run poe lint && uv run poe fmt
git add core/src/fantaclaude/ingest/asta_live.py core/tests/test_asta_live.py
git commit -m "feat(asta): FantaAstaLive anonymous auth and session-code guard"
```

---

### Task 2: Feed adapter, part 2 — the SSE stream, the maintained node, reconnect, capture

**Files:**
- Modify: `core/src/fantaclaude/ingest/asta_live.py`
- Modify: `core/src/fantaclaude/paths.py` (add `asta_captures_dir()`)
- Test: `core/tests/test_asta_live.py`

**Interfaces:**
- Consumes: Task 1's `AnonymousAuth`, `FeedError`, `check_session_code`;
  `asta.state.parse_snapshot`, `Snapshot`, `SnapshotError`.
- Produces (used by Task 7's serve command):
  `apply_put(node: Any, path: str, data: Any) -> Any`,
  `apply_patch(node: Any, path: str, data: Mapping) -> Any`,
  `sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]`,
  and `AstaLiveFeed(session_code: str, *, client: httpx.AsyncClient,
  on_snapshot: Callable[[Snapshot], Awaitable[None]],
  on_status: Callable[[str], Awaitable[None]],
  auth: AnonymousAuth | None = None, database_url: str = FIREBASE_DATABASE_URL,
  capture: Path | None = None, backoff: Sequence[float] = BACKOFF,
  sleep: Callable[[float], Awaitable[None]] = asyncio.sleep)` with
  `async run() -> None` (runs until cancelled; raises `FeedError` only on the
  fatal cases: no such session, `cancel`, an unparseable node).
  `paths.asta_captures_dir() -> Path` (= `raw_dir() / "asta_live"`).

**Behaviour being encoded** (spec, "The adapter, and the rules that keep it
safe" + failure-modes table):

- Each (re)connect issues `GET {database_url}/sessions/{code}/state.json`
  with `params={"auth": <token>}`, `Accept: text/event-stream`,
  `follow_redirects=True`, and a read timeout of `READ_TIMEOUT` so a silently
  dead connection is discovered between keep-alives.
- `put` at `/` with `data: null` on the **first** event of the first connect →
  `FeedError("no session …")` (fatal: the code is wrong or the admin closed
  it). On a later connect it means the admin deleted the session: also fatal.
- `put`/`patch` maintain the raw node; after each, the node is parsed with
  `parse_snapshot` and handed to `on_snapshot`. A `SnapshotError` is fatal
  (the shape changed; the board stands on its last state and the operator is
  told) — the mirror never guesses.
- `keep-alive` is ignored. `auth_revoked` → `auth.invalidate()` and
  reconnect. `cancel` → `FeedError` (rules deny the read).
- Any transport error or clean end of stream → `on_status(RECONNECTING)`,
  backoff (capped at the last entry), reconnect; a successful connect that
  yields its first event → `on_status(LIVE)` and the backoff resets.
- When `capture` is set, every applied node is appended as one JSON line
  (`json.dumps(node) + "\n"`) — the file replays through `read_snapshots` /
  `asta replay`, which is how a rehearsal capture is made. Parent directories
  are created; the write is a plain append (a torn tail line is skipped by
  `read_snapshots`? No — it raises; so flush per line and accept that a
  crash can lose only the final line, which the state file already holds).

- [ ] **Step 1: Write the failing tests** (append to `core/tests/test_asta_live.py`)

```python
import asyncio
import json

from fantaclaude.ingest.asta_live import (
    LIVE,
    RECONNECTING,
    AstaLiveFeed,
    apply_patch,
    apply_put,
    sse_events,
)

NODE = {"picks": [{"playerId": 100, "teamId": 0, "cost": 10, "index": 0}],
        "teams": [{"id": 0, "connection": {"label": "me"}}, {"id": 1, "connection": {"label": "rival"}}],
        "settings": {"budget": 500, "game": 2, "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]}},
        "selectedPlayerId": None, "turnTeamId": 0, "status": "live", "locked": False}


def test_put_and_patch_maintain_the_node_the_way_firebase_documents_them():
    node = apply_put(None, "/", {"a": {"b": 1}, "c": 2})
    assert node == {"a": {"b": 1}, "c": 2}
    node = apply_put(node, "/a/b", 5)
    assert node["a"]["b"] == 5
    node = apply_put(node, "/d/0", {"x": 1})            # intermediate keys are created
    assert node["d"] == {"0": {"x": 1}}
    node = apply_patch(node, "/", {"c": 3, "e": 4})     # patch merges keys, put replaces
    assert node["c"] == 3 and node["e"] == 4 and node["a"] == {"b": 5}
    node = apply_put(node, "/e", None)                  # null deletes
    assert "e" not in node


async def test_sse_events_parses_frames_and_ignores_comments():
    async def lines():
        for line in ["event: put", 'data: {"path":"/","data":1}', "",
                     ": keepalive comment", "event: keep-alive", "data: null", "",
                     "data: no event name", ""]:
            yield line
    events = [e async for e in sse_events(lines())]
    assert events == [("put", '{"path":"/","data":1}'), ("keep-alive", "null"),
                      ("message", "no event name")]


def _stream_response(frames: list[str]) -> httpx.Response:
    async def agen():
        for frame in frames:
            yield frame.encode()
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=agen())


def _frames(*events: tuple[str, dict | None]) -> list[str]:
    return [f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events]


async def _run_feed(feed: AstaLiveFeed, until: asyncio.Event, timeout: float = 5.0):
    task = asyncio.create_task(feed.run())
    try:
        await asyncio.wait_for(until.wait(), timeout)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, FeedError):
            pass


@respx.mock
async def test_the_stream_puts_patches_and_emits_snapshots(tmp_path):
    respx.post(SIGNUP_URL).respond(200, json={
        "idToken": "tok", "refreshToken": "ref", "expiresIn": "3600", "localId": "anon"})
    respx.get("https://db.example/sessions/FA-nri-okm/state.json").mock(
        return_value=_stream_response(_frames(
            ("put", {"path": "/", "data": NODE}),
            ("keep-alive", None),
            ("patch", {"path": "/", "data": {"selectedPlayerId": 200}}),
            ("put", {"path": "/picks/1", "data": {"playerId": 200, "teamId": 1, "cost": 7, "index": 1}}),
        )))
    seen: list = []
    statuses: list[str] = []
    done = asyncio.Event()

    async def on_snapshot(snap):
        seen.append(snap)
        if len(seen) == 3:
            done.set()

    async def on_status(status):
        statuses.append(status)

    capture = tmp_path / "cap" / "FA-nri-okm.jsonl"
    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed("FA-nri-okm", client=client, on_snapshot=on_snapshot, on_status=on_status,
                            database_url="https://db.example", capture=capture, sleep=lambda s: asyncio.sleep(0))
        await _run_feed(feed, done)
    assert statuses[0] == LIVE
    assert len(seen[0].picks) == 1 and seen[0].selected is None
    assert seen[1].selected == 200
    assert len(seen[2].picks) == 2 and seen[2].picks[1].player_id == 200
    lines = capture.read_text().strip().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["picks"][0]["playerId"] == 100
    auth_param = respx.calls[1].request.url.params["auth"]
    assert auth_param == "tok"


@respx.mock
async def test_a_dropped_stream_reconnects_with_backoff_and_a_full_snapshot_resumes(tmp_path):
    respx.post(SIGNUP_URL).respond(200, json={
        "idToken": "tok", "refreshToken": "ref", "expiresIn": "3600", "localId": "anon"})
    route = respx.get("https://db.example/sessions/FA-nri-okm/state.json")
    route.side_effect = [
        _stream_response(_frames(("put", {"path": "/", "data": NODE}))),          # ends: reconnect
        httpx.ConnectError("down"),                                               # still down
        _stream_response(_frames(("put", {"path": "/", "data": NODE}))),          # back
    ]
    slept: list[float] = []
    statuses: list[str] = []
    seen: list = []
    done = asyncio.Event()

    async def on_snapshot(snap):
        seen.append(snap)
        if len(seen) == 2:
            done.set()

    async def on_status(status):
        statuses.append(status)

    async def fake_sleep(seconds):
        slept.append(seconds)

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed("FA-nri-okm", client=client, on_snapshot=on_snapshot, on_status=on_status,
                            database_url="https://db.example", sleep=fake_sleep)
        await _run_feed(feed, done)
    assert statuses.count(LIVE) == 2 and RECONNECTING in statuses
    assert slept[:2] == [1.0, 2.0]                     # backoff grew while it was down


@respx.mock
async def test_auth_revoked_invalidates_and_reconnects_with_a_fresh_token():
    respx.post(SIGNUP_URL).mock(side_effect=[
        httpx.Response(200, json={"idToken": "tok-1", "refreshToken": "ref-1", "expiresIn": "3600", "localId": "a"}),
    ])
    respx.post(TOKEN_URL).respond(200, json={"id_token": "tok-2", "refresh_token": "ref-2", "expires_in": "3600"})
    route = respx.get("https://db.example/sessions/FA-nri-okm/state.json")
    route.side_effect = [
        _stream_response(_frames(("put", {"path": "/", "data": NODE}), ("auth_revoked", None))),
        _stream_response(_frames(("put", {"path": "/", "data": NODE}))),
    ]
    seen: list = []
    done = asyncio.Event()

    async def on_snapshot(snap):
        seen.append(snap)
        if len(seen) == 2:
            done.set()

    async def on_status(status):
        pass

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed("FA-nri-okm", client=client, on_snapshot=on_snapshot, on_status=on_status,
                            database_url="https://db.example", sleep=lambda s: asyncio.sleep(0))
        await _run_feed(feed, done)
    assert route.calls[0].request.url.params["auth"] == "tok-1"
    assert route.calls[1].request.url.params["auth"] == "tok-2"


@respx.mock
async def test_no_such_session_and_cancel_are_fatal():
    respx.post(SIGNUP_URL).respond(200, json={
        "idToken": "tok", "refreshToken": "ref", "expiresIn": "3600", "localId": "anon"})
    respx.get("https://db.example/sessions/FA-none/state.json").mock(
        return_value=_stream_response(_frames(("put", {"path": "/", "data": None}))))

    async def nothing(_):
        pass

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed("FA-none", client=client, on_snapshot=nothing, on_status=nothing,
                            database_url="https://db.example", sleep=lambda s: asyncio.sleep(0))
        with pytest.raises(FeedError) as err:
            await feed.run()
    assert "FA-none" in str(err.value)

    respx.get("https://db.example/sessions/FA-shut/state.json").mock(
        return_value=_stream_response(_frames(("put", {"path": "/", "data": NODE}), ("cancel", None))))
    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed("FA-shut", client=client, on_snapshot=nothing, on_status=nothing,
                            database_url="https://db.example", sleep=lambda s: asyncio.sleep(0))
        with pytest.raises(FeedError):
            await feed.run()


def test_asta_captures_dir_is_under_raw(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    from fantaclaude.paths import asta_captures_dir, raw_dir
    assert asta_captures_dir() == raw_dir() / "asta_live"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_asta_live.py -c core/pyproject.toml -q`
Expected: FAIL — `ImportError` on `AstaLiveFeed` / `apply_put` / `sse_events`;
`asta_captures_dir` missing.

- [ ] **Step 3: Implement the stream half** (append to `asta_live.py`)

```python
def _segments(path: str) -> list[str]:
    return [seg for seg in path.split("/") if seg]


def apply_put(node: Any, path: str, data: Any) -> Any:
    """Firebase streaming `put`: replace the subtree at `path`; null deletes."""
    segs = _segments(path)
    if not segs:
        return data
    root = node if isinstance(node, dict) else {}
    here = root
    for seg in segs[:-1]:
        nxt = here.get(seg)
        if not isinstance(nxt, dict):
            nxt = {}
            here[seg] = nxt
        here = nxt
    if data is None:
        here.pop(segs[-1], None)
    else:
        here[segs[-1]] = data
    return root


def apply_patch(node: Any, path: str, data: Mapping) -> Any:
    """Firebase streaming `patch`: merge each key of `data` at `path`."""
    root = node if isinstance(node, dict) else {}
    for key, value in data.items():
        root = apply_put(root, f"{path.rstrip('/')}/{key}", value)
    return root


async def sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    """(event, data) frames from an SSE line stream; comments are skipped and
    multi-line data joined the way the protocol says."""
    event, data = "message", []
    async for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:"):].strip())


class AstaLiveFeed:
    """The one subscriber. run() streams `/sessions/<code>/state`, maintains
    the raw node, and emits a parsed Snapshot per change; it returns only by
    cancellation, and raises FeedError only when the feed can never recover
    by retrying (no such session, rules deny the read, a node shape this
    code cannot parse)."""

    def __init__(self, session_code: str, *, client: httpx.AsyncClient,
                 on_snapshot: Callable[[Snapshot], Awaitable[None]],
                 on_status: Callable[[str], Awaitable[None]],
                 auth: AnonymousAuth | None = None,
                 database_url: str = FIREBASE_DATABASE_URL,
                 capture: Path | None = None,
                 backoff: Sequence[float] = BACKOFF,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.session_code = check_session_code(session_code)
        self._client = client
        self._on_snapshot = on_snapshot
        self._on_status = on_status
        self._auth = auth or AnonymousAuth(client)
        self._url = f"{database_url}/sessions/{self.session_code}/state.json"
        self._capture = capture
        self._backoff = tuple(backoff)
        self._sleep = sleep
        self._node: Any = None

    async def run(self) -> None:
        attempt = 0
        while True:
            try:
                if await self._stream_once():
                    attempt = 0            # the stream was healthy: the next drop starts backoff afresh
                # clean end of stream: the server closed it; reconnect
            except (httpx.HTTPError, TimeoutError):
                pass
            attempt = min(attempt, len(self._backoff) - 1)
            await self._on_status(RECONNECTING)
            await self._sleep(self._backoff[attempt])
            attempt += 1

    async def _stream_once(self) -> bool:
        """Stream until the connection ends; True if at least one event was
        applied (the connect was healthy)."""
        token = await self._auth.token()
        timeout = httpx.Timeout(10.0, read=READ_TIMEOUT)
        async with self._client.stream("GET", self._url, params={"auth": token},
                                       headers={"Accept": "text/event-stream"},
                                       timeout=timeout, follow_redirects=True) as resp:
            if resp.status_code != 200:
                await resp.aread()
                if resp.status_code in (401, 403):
                    self._auth.invalidate()
                    raise httpx.HTTPStatusError("unauthorized", request=resp.request, response=resp)
                raise FeedError(f"the feed answered {resp.status_code} for session {self.session_code}")
            first = True
            async for event, data in sse_events(resp.aiter_lines()):
                if event == "keep-alive":
                    continue
                if event == "auth_revoked":
                    self._auth.invalidate()
                    return not first                # reconnect with a fresh token
                if event == "cancel":
                    raise FeedError(f"the feed cancelled session {self.session_code}: the rules deny the read")
                if event not in ("put", "patch"):
                    continue
                body = json.loads(data)
                if event == "put":
                    if body.get("path") in ("/", "") and body.get("data") is None:
                        raise FeedError(f"no session {self.session_code} is being served")
                    self._node = apply_put(self._node, body["path"], body["data"])
                else:
                    self._node = apply_patch(self._node, body["path"], body["data"])
                try:
                    snap = parse_snapshot(self._node)
                except SnapshotError as exc:
                    raise FeedError(f"session {self.session_code}: the node is not a shape this mirror reads: {exc}") from None
                if first:
                    await self._on_status(LIVE)
                    first = False
                self._write_capture()
                await self._on_snapshot(snap)
            return not first

    def _write_capture(self) -> None:
        if self._capture is None:
            return
        self._capture.parent.mkdir(parents=True, exist_ok=True)
        with self._capture.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(self._node, ensure_ascii=False) + "\n")
```

And in `core/src/fantaclaude/paths.py` add:

```python
def asta_captures_dir() -> Path:
    """data/raw/asta_live/: one JSONL of feed nodes per served session — the
    capture `asta replay` rehearses on."""
    return raw_dir() / "asta_live"
```

Note on `run()`: a `FeedError` raised inside `_stream_once` propagates out of
`run()` — the caller (Task 7's serve) reports it and keeps the last board.
The reconnect loop retries only transport errors and clean stream ends, and
a healthy stream (at least one applied event) resets the backoff, which is
what the `..._reconnects_with_backoff...` test's `[1.0, 2.0]` growth pins.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_asta_live.py -c core/pyproject.toml -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Full suite, lint, commit**

```bash
uv run poe test && uv run poe lint
git add core/src/fantaclaude/ingest/asta_live.py core/src/fantaclaude/paths.py core/tests/test_asta_live.py
git commit -m "feat(asta): FantaAstaLive SSE stream — maintained node, reconnect with backoff, capture"
```

---

### Task 3: The typed wire contract — `api/models.py`

**Files:**
- Create: `core/src/fantaclaude/api/__init__.py` (empty)
- Create: `core/src/fantaclaude/api/models.py`
- Test: `core/tests/test_api_models.py`

**Interfaces:**
- Consumes: `Board.to_dict()` (shape in "Source facts"), `pydantic` v2
  (already a core dependency).
- Produces (used by Tasks 5, 6, 9): pydantic models `BandOut`, `BidderOut`,
  `PressureOut`, `LedgerOut`, `SettingsOut`, `LotOut`, `LayerOut`,
  `PriceRowOut`, `BoardPayload` (mirror of `Board.to_dict()`, all
  `extra="forbid"`); envelope models `TeamOut`, `MappingOut`, `HelloPayload`,
  `AdjustIn`, `MappingIn`, `AdjustResult`, `RefreshResult`; helper
  `board_payload(board: Board) -> BoardPayload`.

This is the "types are generated, not hand-written" requirement made
enforceable: the pydantic models are the single source of truth FastAPI turns
into OpenAPI (Task 5) and openapi-typescript turns into TS (Task 9), and the
round-trip test below pins them to what the advisor actually emits. **If the
test disagrees with a model, fix the model to the code's truth — never loosen
a field to `Any` to make it pass.**

- [ ] **Step 1: Write the failing test**

```python
# core/tests/test_api_models.py
"""The wire contract: BoardPayload mirrors Board.to_dict() field for field.

A field the advisor emits that the model does not know is a validation error
(extra="forbid"); a field the model names that the advisor stopped emitting
is a missing-field error. Either way the drift is a red test here, not a
blank dashboard on auction night.
"""
from fantaclaude.api.models import AdjustIn, BoardPayload, HelloPayload, board_payload
from fantaclaude.asta.adjustments import Adjustment, resolve
from fantaclaude.asta.advisor import TeamMapping, derive

from test_advisor import node, pinned_run


def _rich_board(tmp_path, fixture_json, mcp_fixture_json):
    """A board with every optional branch populated: picks, a lot on the
    block, pressure, adjustments of all three kinds, session settings."""
    result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    pids = sorted(pinned.players)
    layer = resolve([Adjustment("value", "limping", player_id=pids[0], factor=0.9),
                     Adjustment("exclude", "not buying him", player_id=pids[1]),
                     Adjustment("target", "heavier here", role_class="Pc", count=2)],
                    pinned.candidates(), sha256="ab" * 32)
    state = node([(pids[2], 1, 30), (pids[3], 0, 12)], selected=pids[4])
    return derive(state, run=pinned, settings=pinned.league, layer=layer,
                  mapping=TeamMapping(mine=0, nicks={1: "Marco"}), participants={})


def test_board_payload_round_trips_the_advisors_own_dict(tmp_path, fixture_json, mcp_fixture_json):
    board = _rich_board(tmp_path, fixture_json, mcp_fixture_json)
    raw = board.to_dict()
    payload = board_payload(board)
    assert payload.model_dump(by_alias=True, mode="json") == raw
    assert payload.lot is not None and payload.lot_pressure is not None
    assert payload.adjustments.count == 3 and len(payload.adjustments.excluded) == 1
    some_row = next(iter(payload.prices.values()))
    assert some_row.pressure is not None and some_row.band.p25 <= some_row.band.p75


def test_an_unknown_field_is_a_red_test_not_a_silent_pass(tmp_path, fixture_json, mcp_fixture_json):
    import pytest
    board = _rich_board(tmp_path, fixture_json, mcp_fixture_json)
    raw = board.to_dict()
    raw["a_field_2b_does_not_know"] = 1
    with pytest.raises(Exception):
        BoardPayload.model_validate(raw)


def test_hello_and_adjust_models_carry_the_envelope():
    hello = HelloPayload.model_validate({
        "phase": "pending", "mode": "feed", "session_code": "FA-nri-okm", "feed": "offline",
        "run": "run 20260830 · …", "scenario": None, "settings": None, "league_conflicts": [], "note": None,
        "teams": [{"team_id": 0, "label": "me"}], "participants": ["Marco"], "mapping": None, "board": None})
    assert hello.phase == "pending" and hello.board is None
    adj = AdjustIn.model_validate({"type": "target", "class": "Dc", "count": 4, "reason": "go heavier"})
    assert adj.role_class == "Dc"
    assert AdjustIn.model_validate({"type": "value", "player": "Bastoni", "factor": 0.85,
                                    "reason": "limping"}).factor == 0.85
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest core/tests/test_api_models.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.api`.

- [ ] **Step 3: Write the models**

```python
# core/src/fantaclaude/api/models.py
"""The wire contract of `asta serve`: pydantic mirrors of the payloads the
advisor emits (spec, "Types are generated, not hand-written": these models
are what FastAPI turns into OpenAPI and openapi-typescript turns into the
dashboard's types).

BoardPayload mirrors Board.to_dict() field for field with extra="forbid" on
every model, so drift on either side is a red test (test_api_models), never
a blank dashboard. Nothing here reshapes a payload: the server sends the
advisor's own dict; these models only *describe* it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fantaclaude.asta.advisor import Board


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BandOut(_Model):
    p25: int
    p50: int
    p75: int


class BidderOut(_Model):
    team_id: int
    label: str
    nick: str | None
    intent: Literal["keen", "neutral", "reluctant"]
    credits: int
    depth: int
    overpay: float
    ceiling: int
    reasons: list[str]


class PressureOut(_Model):
    player_id: int
    expected: int
    estimate: int
    bidders: list[BidderOut]


class SettingsOut(_Model):
    budget: int
    goalkeepers: list[int]          # [low, high]
    outfield: list[int]
    size: list[int]
    game: int
    team_count: int
    source: Literal["session", "league"]


class LedgerOut(_Model):
    team_id: int
    label: str
    nick: str | None
    budget: int
    spent: int
    credits: int
    picks: list[int]
    goalkeepers: int
    outfield: int
    unknown: int
    missing_goalkeepers: int
    missing_outfield: int
    open_slots: int


class LotOut(_Model):
    player_id: int
    name: str
    team_short: str
    role_class: str
    roles: list[str]
    tier: int
    band: BandOut | None
    expected_price: int | None
    sold_to: int | None


class LayerOut(_Model):
    count: int
    applied: int
    value_factor: dict[str, float]
    excluded: list[int]
    targets: dict[str, int]
    problems: list[str]
    sha256: str


class PriceRowOut(_Model):
    player_id: int
    name: str
    team_short: str
    role_class: str
    roles: list[str]
    tier: int
    band: BandOut
    expected_price: int
    value_p50: float
    pressure: PressureOut | None = None


class BoardPayload(_Model):
    run_id: str
    scenario: str
    settings: SettingsOut
    league_conflicts: list[str]
    problems: list[str]
    status: str | None
    locked: bool | None
    picks: int
    me: LedgerOut
    teams: list[LedgerOut]
    market_credits: int
    inflation: float
    composition: dict[str, int]
    credits_by_class: dict[str, int]
    reserve: int
    budget: int
    slot_price: float
    targets_departed: list[str]
    completion_value: float | None
    selected: int | None
    lot: LotOut | None
    lot_pressure: PressureOut | None
    adjustments: LayerOut
    prices: dict[str, PriceRowOut]


def board_payload(board: Board) -> BoardPayload:
    return BoardPayload.model_validate(board.to_dict())


class TeamOut(_Model):
    team_id: int
    label: str


class MappingOut(_Model):
    mine: int
    nicks: dict[str, str]           # TeamMapping.to_dict stringifies the ids


class HelloPayload(_Model):
    phase: Literal["pending", "live"]
    mode: Literal["feed", "replay", "state"]
    session_code: str | None
    feed: str                       # live | reconnecting | offline | replay | state
    run: str                        # PinnedRun.describe()
    scenario: str | None
    settings: SettingsOut | None
    league_conflicts: list[str]
    note: str | None                # e.g. why the --me/--map flags could not answer the screen
    teams: list[TeamOut]
    participants: list[str]         # dossier nicks, for the mapping screen
    mapping: MappingOut | None
    board: BoardPayload | None


class MappingIn(_Model):
    mine: int
    nicks: dict[int, str] = Field(default_factory=dict)


class AdjustIn(_Model):
    type: Literal["value", "exclude", "target"]
    reason: str
    player: str | None = None
    player_id: int | None = None
    factor: float | None = None
    role_class: str | None = Field(default=None, alias="class")
    count: int | None = None

    def to_entry(self) -> dict[str, Any]:
        """The dict adjustment_from_entry validates — the file's own keys."""
        raw = {"player": self.player, "player_id": self.player_id, "type": self.type,
               "factor": self.factor, "class": self.role_class, "count": self.count, "reason": self.reason}
        return {k: v for k, v in raw.items() if v is not None}


class AdjustResult(_Model):
    described: str
    count: int
    player_id: int | None           # resolved by the server; None for a target
    board: BoardPayload


class RefreshResult(_Model):
    board: BoardPayload
    problems: list[str]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_api_models.py -c core/pyproject.toml -q`
Expected: PASS. If `model_dump(by_alias=True, mode="json") == raw` fails on a
numeric type (e.g. the advisor emits a numpy int the model coerced), fix at
the model edge with the matching python type — `json_safe` already runs in
`Board.to_dict()`, so any surviving mismatch is a genuine contract fact to
encode, not to paper over.

- [ ] **Step 5: Lint and commit**

```bash
uv run poe test && uv run poe lint
git add core/src/fantaclaude/api core/tests/test_api_models.py
git commit -m "feat(api): typed wire contract for the board, hello, adjust and refresh payloads"
```

---

### Task 4: `AstaServer` — one owner of live state, async shell around `Auction`

**Files:**
- Create: `core/src/fantaclaude/api/serve.py`
- Test: `core/tests/test_api_serve.py`

**Interfaces:**
- Consumes: `Auction`, `Refresh`, `MutationResult` (asta/auction.py);
  `TeamMapping` (advisor); `Snapshot` (state); `render_state`, `write_state`
  (snapshot); `resolve`, `load_adjustments`, `append_adjustment`,
  `file_sha256`, `AdjustmentsError`, `Adjustment` (adjustments);
  `load_participants`, `Participant` (kb); `describe_event`, `AstaPaths`,
  `UsageError`, `resolve_mapping` (commands/asta.py); `session_from_feed`,
  `compare`, `SessionError` (session); `utc_now`; `LIVE/RECONNECTING/OFFLINE`
  (asta_live).
- Produces (used by Tasks 5, 6, 7):

```python
class PhaseError(RuntimeError): ...   # "the mapping screen has not been answered"

Sender = Callable[[str], Awaitable[None]]

class AstaServer:
    def __init__(self, *, run: PinnedRun, layer: AdjustmentLayer,
                 participants: dict[str, Participant], scenario: str | None,
                 paths: AstaPaths, mode: Literal["feed", "replay", "state"],
                 session_code: str | None = None,
                 mapping: TeamMapping | None = None,
                 pending_me: str | None = None,
                 pending_maps: tuple[str, ...] = ()) -> None
    auction: Auction | None          # None while pending
    last_snapshot: Snapshot | None
    feed_status: str                 # live|reconnecting|offline for feed mode; "replay"/"state" otherwise
    pending_note: str | None         # why the pending flags could not resolve, when they could not
    def hello(self) -> dict[str, Any]
    def subscribe(self, sender: Sender) -> Callable[[], None]
    async def on_snapshot(self, snap: Snapshot) -> None
    async def set_mapping(self, mine: int, nicks: dict[int, str]) -> dict[str, Any]   # -> hello()
    async def set_feed_status(self, status: str) -> None
    async def adjust(self, adjustment: Adjustment) -> dict[str, Any]   # AdjustResult-shaped
    async def refresh(self) -> dict[str, Any]                          # RefreshResult-shaped
```

**The concurrency rules this class owns** (spec, "Concurrency: one owner of
state, and two classes of query"):

- One `asyncio.Lock` serialises every mutation; the ~250 ms board re-derive
  and the fsync'd state-file write run in `asyncio.to_thread` so the event
  loop keeps serving the WebSocket while they run.
- The state file is written inside the same worker call as the mutation, so
  no broadcastable state ever exists that the file does not hold.
- Broadcast sends the advisor's own `Board.to_dict()`; a sender that raises
  is dropped (a dead client detaches itself, localhost has no slow-client
  problem worth a queue).
- `adjust` is the one writer of `adjustments.yml` while the server runs: the
  append, the re-resolve and the `Refresh` mutation happen under the lock in
  one worker call, which is exactly the serialisation
  `asta/adjustments.py::append_adjustment`'s docstring says 2b must add.
- A `SessionError` out of `Auction.mutate` (a snapshot whose settings cannot
  be read) propagates to the caller: the feed task reports it and stops; the
  board stands on its last state. The mirror never guesses.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/test_api_serve.py
import asyncio
import json

import pytest
from fantaclaude.asta.adjustments import EMPTY_LAYER, Adjustment, load_adjustments
from fantaclaude.asta.snapshot import read_state
from fantaclaude.asta.state import parse_snapshot
from fantaclaude.api.serve import AstaServer, PhaseError
from fantaclaude.commands.asta import AstaPaths, UsageError

from test_advisor import SESSION, pinned_run


def snap(picks, *, selected=None, teams=(0, 1, 2), settings=SESSION, status="live"):
    return parse_snapshot({
        "picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i}
                  for i, (pid, tid, cost) in enumerate(picks)],
        "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams],
        "settings": settings, "selectedPlayerId": selected, "status": status, "locked": False})


@pytest.fixture
def server_kit(tmp_path, fixture_json, mcp_fixture_json):
    result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    paths = AstaPaths(db=tmp_path / "data" / "fanta.duckdb", adjustments=tmp_path / "data" / "adjustments.yml",
                      state=tmp_path / "data" / "asta-state.json", records=tmp_path / "records", kb=tmp_path / "kb")
    def make(**kw):
        kw.setdefault("run", pinned)
        kw.setdefault("layer", EMPTY_LAYER)
        kw.setdefault("participants", {})
        kw.setdefault("scenario", None)
        kw.setdefault("paths", paths)
        kw.setdefault("mode", "feed")
        kw.setdefault("session_code", "FA-nri-okm")
        return AstaServer(**kw)
    return make, pinned, paths


def sent(server):
    """Subscribe a recording sender; returns the list of decoded messages."""
    messages = []
    async def sender(text):
        messages.append(json.loads(text))
    server.subscribe(sender)
    return messages


async def test_pending_until_the_mapping_screen_answers_then_live(server_kit):
    make, pinned, paths = server_kit
    server = make()
    messages = sent(server)
    assert server.hello()["phase"] == "pending" and server.hello()["board"] is None
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)]))
    assert server.hello()["phase"] == "pending"                 # a snapshot alone does not open the board
    assert messages[-1]["type"] == "hello"
    assert [t["team_id"] for t in server.hello()["teams"]] == [0, 1, 2]
    hello = await server.set_mapping(0, {})
    assert hello["phase"] == "live"
    board = server.hello()["board"]
    assert board is not None and board["picks"] == 1 and board["me"]["credits"] == 500
    assert paths.state.is_file()                                # the state file exists from the first live board
    assert read_state(paths.state).mapping.mine == 0


async def test_snapshots_mutate_broadcast_and_write_the_state_file(server_kit):
    make, pinned, paths = server_kit
    server = make(mapping=None)
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    messages = sent(server)
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)], selected=pids[1]))
    board_msg = messages[-1]
    assert board_msg["type"] == "board"
    assert any("+" in e for e in board_msg["events"]) and any(e.startswith("lot:") for e in board_msg["events"])
    assert board_msg["board"]["selected"] == pids[1]
    stored = read_state(paths.state)
    assert len(stored.snapshot.picks) == 1


async def test_crash_recovery_a_fresh_server_on_the_last_snapshot_equals_the_long_way(server_kit):
    make, pinned, _ = server_kit
    pids = sorted(pinned.players)
    s1, s2, s3 = (snap([(pids[0], 1, 30)]), snap([(pids[0], 1, 30), (pids[1], 0, 12)]),
                  snap([(pids[1], 0, 12)], selected=pids[2]))     # an undo happened in s3
    a = make()
    await a.set_mapping(0, {})
    for s in (s1, s2, s3):
        await a.on_snapshot(s)
    b = make()
    await b.set_mapping(0, {})
    await b.on_snapshot(s3)                                       # the resubscribe's full snapshot
    assert a.auction.board.to_dict() == b.auction.board.to_dict()


async def test_two_concurrent_adjusts_both_land_and_reprice(server_kit):
    make, pinned, paths = server_kit
    server = make()
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    pids = sorted(pinned.players)
    a = Adjustment("value", "limping", player_id=pids[0], factor=0.8)
    b = Adjustment("exclude", "not buying", player_id=pids[1])
    r1, r2 = await asyncio.gather(server.adjust(a), server.adjust(b))
    assert {r1["count"], r2["count"]} == {1, 2}                   # serialised: one saw one entry, the other two
    assert len(load_adjustments(paths.adjustments)) == 2
    assert str(pids[1]) not in server.auction.board.to_dict()["prices"]


async def test_adjust_refuses_an_inert_entry_and_the_pending_phase(server_kit):
    make, pinned, _ = server_kit
    server = make()
    with pytest.raises(PhaseError):
        await server.adjust(Adjustment("exclude", "why", player_id=1))
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    with pytest.raises(UsageError):
        await server.adjust(Adjustment("exclude", "why", player_id=999_999))


async def test_refresh_rereads_the_file_and_a_malformed_file_leaves_the_layer_standing(server_kit):
    make, pinned, paths = server_kit
    server = make()
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    pids = sorted(pinned.players)
    paths.adjustments.parent.mkdir(parents=True, exist_ok=True)
    paths.adjustments.write_text(f"- player_id: {pids[0]}\n  type: exclude\n  reason: hand-written\n", encoding="utf-8")
    out = await server.refresh()
    assert str(pids[0]) not in out["board"]["prices"]
    paths.adjustments.write_text("]: not yaml", encoding="utf-8")
    from fantaclaude.asta.adjustments import AdjustmentsError
    with pytest.raises(AdjustmentsError):
        await server.refresh()
    assert str(pids[0]) not in server.auction.board.to_dict()["prices"]   # the previous layer stands


async def test_pending_flags_answer_the_screen_when_the_first_snapshot_arrives(server_kit):
    make, pinned, _ = server_kit
    server = make(pending_me="t1")
    await server.on_snapshot(snap([]))
    assert server.hello()["phase"] == "live" and server.hello()["mapping"]["mine"] == 1


async def test_bad_pending_flags_fall_back_to_the_screen_with_a_note(server_kit):
    make, pinned, _ = server_kit
    server = make(pending_me="nobody-by-this-name")
    await server.on_snapshot(snap([]))
    assert server.hello()["phase"] == "pending"
    assert "nobody-by-this-name" in (server.pending_note or "")


async def test_a_dead_sender_is_dropped_not_fatal(server_kit):
    make, pinned, _ = server_kit
    server = make()
    async def dead(text):
        raise RuntimeError("browser gone")
    server.subscribe(dead)
    messages = sent(server)
    await server.on_snapshot(snap([]))
    assert messages[-1]["type"] == "hello"                        # the healthy sender still heard it


async def test_remapping_mid_run_rebuilds_on_the_same_state(server_kit):
    make, pinned, _ = server_kit
    server = make()
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)]))
    await server.set_mapping(0, {})
    before = server.auction.board.to_dict()
    await server.set_mapping(2, {})
    after = server.auction.board.to_dict()
    assert after["me"]["team_id"] == 2 and after["picks"] == before["picks"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest core/tests/test_api_serve.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.api.serve`.

- [ ] **Step 3: Implement `AstaServer`**

```python
# core/src/fantaclaude/api/serve.py
"""One owner of live state (spec, "Concurrency: one owner of state, and two
classes of query"): AstaServer wraps 2a's Auction in an asyncio shell. Every
change — a feed snapshot, an adjustment from any surface, a refresh — passes
through one lock and one worker thread, re-derives the board, writes the
state file, and broadcasts to every WebSocket. Being callback-shaped (plain
async senders, no FastAPI types) is what keeps this testable without HTTP.

The server starts `pending` unless a mapping is handed in (state-file mode)
or `--me`/`--map` flags resolve against the first snapshot; `POST
/api/mapping` (the screen) moves it to `live`. The mapping is never
persisted by the server (spec: the browser pre-fills the screen); it reaches
the state file only inside render_state, as the board's own labels.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fantaclaude.asta.adjustments import (
    Adjustment,
    AdjustmentLayer,
    append_adjustment,
    file_sha256,
    load_adjustments,
    resolve,
)
from fantaclaude.asta.auction import Auction, MutationResult, Refresh
from fantaclaude.asta.advisor import TeamMapping
from fantaclaude.asta.pinned import PinnedRun
from fantaclaude.asta.session import compare, session_from_feed
from fantaclaude.asta.snapshot import render_state, write_state
from fantaclaude.asta.state import Snapshot
from fantaclaude.commands.asta import AstaPaths, UsageError, describe_event, resolve_mapping
from fantaclaude.kb.participants import Participant, load_participants
from fantaclaude.timeutil import utc_now

Sender = Callable[[str], Awaitable[None]]
Mode = Literal["feed", "replay", "state"]


class PhaseError(RuntimeError):
    """The mapping screen has not been answered; the board does not exist yet."""


class AstaServer:
    def __init__(self, *, run: PinnedRun, layer: AdjustmentLayer, participants: dict[str, Participant],
                 scenario: str | None, paths: AstaPaths, mode: Mode, session_code: str | None = None,
                 mapping: TeamMapping | None = None, pending_me: str | None = None,
                 pending_maps: tuple[str, ...] = ()) -> None:
        self.run = run
        self.layer = layer
        self.participants = participants
        self.scenario = scenario
        self.paths = paths
        self.mode: Mode = mode
        self.session_code = session_code
        self.feed_status = "offline" if mode == "feed" else mode
        self.auction: Auction | None = None
        self.last_snapshot: Snapshot | None = None
        self.pending_note: str | None = None
        self._pending_me = pending_me
        self._pending_maps = tuple(pending_maps)
        self._lock = asyncio.Lock()
        self._senders: list[Sender] = []
        if mapping is not None:
            self._build(mapping)

    # -- surface -----------------------------------------------------------

    def hello(self) -> dict[str, Any]:
        board = self.auction.board if self.auction is not None else None
        if board is not None:
            settings = board.settings
            conflicts = list(board.league_conflicts)
            teams = [{"team_id": tid, "label": ledger.label} for tid, ledger in sorted(board.ledgers.items())]
            scenario: str | None = board.scenario
        elif self.last_snapshot is not None and self.last_snapshot.settings:
            settings = session_from_feed(self.last_snapshot.settings,
                                         team_count=len(self.last_snapshot.teams) or self.run.league.team_count)
            conflicts = compare(settings, self.run.league)
            teams = [{"team_id": t.team_id, "label": t.label} for t in self.last_snapshot.teams]
            scenario = self.scenario
        else:
            settings, conflicts, teams, scenario = None, [], [], self.scenario
        return {"phase": "live" if self.auction is not None else "pending", "mode": self.mode,
                "session_code": self.session_code, "feed": self.feed_status, "run": self.run.describe(),
                "scenario": scenario, "settings": None if settings is None else settings.to_dict(),
                "league_conflicts": list(conflicts), "note": self.pending_note,
                "teams": teams, "participants": sorted(self.participants),
                "mapping": None if self.auction is None else self.auction.mapping.to_dict(),
                "board": None if board is None else board.to_dict()}

    def subscribe(self, sender: Sender) -> Callable[[], None]:
        self._senders.append(sender)
        def unsubscribe() -> None:
            if sender in self._senders:
                self._senders.remove(sender)
        return unsubscribe

    async def on_snapshot(self, snap: Snapshot) -> None:
        self.last_snapshot = snap
        if self.auction is None:
            if self._pending_me is not None:
                me, maps = self._pending_me, self._pending_maps
                self._pending_me, self._pending_maps = None, ()
                try:
                    mapping = resolve_mapping(snap.teams, me=me, maps=maps, participants=self.participants)
                except UsageError as exc:
                    self.pending_note = f"--me/--map could not be applied: {exc}; answer the mapping screen"
                else:
                    await self.set_mapping(mapping.mine, mapping.nicks)
                    return
            await self._broadcast({"type": "hello", "hello": self.hello()})
            return
        await self._apply(snap)

    async def set_mapping(self, mine: int, nicks: dict[int, str]) -> dict[str, Any]:
        unknown_nicks = sorted(set(nicks.values()) - set(self.participants))
        if unknown_nicks:
            raise UsageError(f"no dossier for {unknown_nicks} under kb/league/participants; "
                             f"known: {sorted(self.participants)}")
        if self.last_snapshot is not None and self.last_snapshot.teams:
            ids = {t.team_id for t in self.last_snapshot.teams}
            bad = sorted((set(nicks) | {mine}) - ids)
            if bad:
                raise UsageError(f"team(s) {bad} are not in the session, which has {sorted(ids)}")
        async with self._lock:
            await asyncio.to_thread(self._build, TeamMapping(mine, dict(nicks)))
        self.pending_note = None
        hello = self.hello()
        await self._broadcast({"type": "hello", "hello": hello})
        return hello

    async def set_feed_status(self, status: str) -> None:
        self.feed_status = status
        await self._broadcast({"type": "feed", "status": status})

    async def adjust(self, adjustment: Adjustment) -> dict[str, Any]:
        self._require_live()
        player_id: int | None = None
        if adjustment.kind != "target":
            probe = resolve([adjustment], self.run.candidates())
            if probe.problems:
                raise UsageError(probe.problems[0])
            player_id = probe.entries[0].player_id
        async with self._lock:
            def work() -> tuple[int, MutationResult]:
                entries = append_adjustment(self.paths.adjustments, adjustment)
                layer = resolve(load_adjustments(self.paths.adjustments), self.run.candidates(),
                                sha256=file_sha256(self.paths.adjustments))
                self.layer = layer
                return len(entries), self._mutate_and_write(Refresh(layer=layer))
            count, result = await asyncio.to_thread(work)
        await self._broadcast_board(result)
        return {"described": adjustment.describe(), "count": count, "player_id": player_id,
                "board": result.board.to_dict()}

    async def refresh(self) -> dict[str, Any]:
        self._require_live()
        async with self._lock:
            def work() -> MutationResult:
                layer = resolve(load_adjustments(self.paths.adjustments), self.run.candidates(),
                                sha256=file_sha256(self.paths.adjustments))       # AdjustmentsError propagates; the previous layer stands
                participants = {p.nick: p for p in load_participants(self.paths.kb)} if self.paths.kb.is_dir() else {}
                self.layer, self.participants = layer, participants
                return self._mutate_and_write(Refresh(layer=layer, participants=participants))
            result = await asyncio.to_thread(work)
        await self._broadcast_board(result)
        return {"board": result.board.to_dict(), "problems": list(result.board.problems)}

    # -- internals ---------------------------------------------------------

    def _require_live(self) -> None:
        if self.auction is None:
            raise PhaseError("the mapping screen has not been answered; the board does not exist yet")

    def _build(self, mapping: TeamMapping) -> None:
        auction = Auction(self.run, mapping, layer=self.layer, scenario=self.scenario,
                          participants=self.participants)
        if self.last_snapshot is not None:
            auction.mutate(self.last_snapshot)
        self.auction = auction
        self._write_state(auction.board)

    async def _apply(self, snap: Snapshot) -> MutationResult:
        async with self._lock:
            result = await asyncio.to_thread(self._mutate_and_write, snap)
        await self._broadcast_board(result)
        return result

    def _mutate_and_write(self, change: Snapshot | Refresh) -> MutationResult:
        result = self.auction.mutate(change)
        self._write_state(result.board)
        return result

    def _write_state(self, board) -> None:
        write_state(self.paths.state, render_state(board, session_code=self.session_code, written_at=utc_now()))

    async def _broadcast_board(self, result: MutationResult) -> None:
        labels = {tid: ledger.label for tid, ledger in result.board.ledgers.items()}
        events = [describe_event(e, self.run, labels) for e in result.events]
        await self._broadcast({"type": "board", "board": result.board.to_dict(), "events": events})

    async def _broadcast(self, message: dict[str, Any]) -> None:
        text = json.dumps(message, ensure_ascii=False)
        for sender in list(self._senders):
            try:
                await sender(text)
            except Exception:                       # a dead client detaches itself
                if sender in self._senders:
                    self._senders.remove(sender)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_api_serve.py -c core/pyproject.toml -q`
Expected: PASS (11 tests). The concurrency test proves the lock serialises
(counts {1, 2}); the crash-recovery test proves the server preserves the
state machine's purity end to end.

- [ ] **Step 5: Full suite, lint, commit**

```bash
uv run poe test && uv run poe lint
git add core/src/fantaclaude/api/serve.py core/tests/test_api_serve.py
git commit -m "feat(api): AstaServer — one lock, mutate off-loop, state file and broadcast per change"
```

---

### Task 5: The FastAPI app — REST, WebSocket, static frontend

**Files:**
- Modify: `core/pyproject.toml` (via `uv add`)
- Create: `core/src/fantaclaude/api/app.py`
- Test: `core/tests/test_api_app.py`

**Interfaces:**
- Consumes: `AstaServer`, `PhaseError` (Task 4); the models (Task 3);
  `UsageError` (commands/asta.py); `AdjustmentsError`,
  `adjustment_from_entry` (asta/adjustments.py).
- Produces (used by Tasks 6, 7, 9):
  `create_app(server: AstaServer | None, *, web_dist: Path | None = None,
  mcp_app: Any | None = None) -> FastAPI`. Routes: `GET /api/hello ->
  HelloPayload`, `GET /api/board -> BoardPayload`, `POST /api/mapping
  (MappingIn) -> HelloPayload`, `POST /api/adjust (AdjustIn) ->
  AdjustResult`, `POST /api/refresh -> RefreshResult`, `WS /ws`
  (server→client only: a `hello` message on connect, then `board`/`hello`/
  `feed` messages as they happen), static mount of `web_dist` at `/` when its
  `index.html` exists, `mcp_app` mounted at `/mcp` with its lifespan run.
- HTTP error mapping (the contract Tasks 6 and 8 rely on): `PhaseError` →
  **409**; `UsageError` and bad adjust/mapping input → **422**; a malformed
  `adjustments.yml` discovered while appending or refreshing
  (`AdjustmentsError` out of the server) → **400**; `server is None` (the
  schema-dump app) → **503**. Every error body is `{"detail": "<message>"}`.

- [ ] **Step 1: Add the dependencies**

```bash
uv add --package fantaclaude fastapi "uvicorn[standard]"
```

Expected: `core/pyproject.toml` gains both; `uv.lock` updates; `uv run
python -c "import fastapi, uvicorn"` succeeds. (uvicorn is the Task 7
runtime; it enters the dependency list here so one lock change covers the
package.)

- [ ] **Step 2: Write the failing tests**

```python
# core/tests/test_api_app.py
import pytest
from starlette.testclient import TestClient

from fantaclaude.api.app import create_app
from fantaclaude.api.serve import AstaServer
from fantaclaude.asta.adjustments import EMPTY_LAYER
from fantaclaude.asta.state import parse_snapshot
from fantaclaude.commands.asta import AstaPaths

from test_advisor import SESSION, pinned_run


def snap(picks, *, selected=None, teams=(0, 1, 2)):
    return parse_snapshot({
        "picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i}
                  for i, (pid, tid, cost) in enumerate(picks)],
        "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams],
        "settings": SESSION, "selectedPlayerId": selected, "status": "live", "locked": False})


@pytest.fixture
def kit(tmp_path, fixture_json, mcp_fixture_json):
    result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    paths = AstaPaths(db=tmp_path / "data" / "fanta.duckdb", adjustments=tmp_path / "data" / "adjustments.yml",
                      state=tmp_path / "data" / "asta-state.json", records=tmp_path / "records", kb=tmp_path / "kb")
    server = AstaServer(run=pinned, layer=EMPTY_LAYER, participants={}, scenario=None,
                        paths=paths, mode="replay", session_code=None)
    return server, pinned, create_app(server)


def test_hello_then_mapping_then_board(kit):
    server, pinned, app = kit
    with TestClient(app) as client:
        assert client.get("/api/board").status_code == 409
        hello = client.get("/api/hello").json()
        assert hello["phase"] == "pending" and hello["run"].startswith("run ")
        answered = client.post("/api/mapping", json={"mine": 0, "nicks": {}}).json()
        assert answered["phase"] == "live"
        board = client.get("/api/board").json()
        assert board["me"]["credits"] == 500 and board["prices"]


def test_mapping_refuses_an_unknown_dossier_nick(kit):
    server, pinned, app = kit
    with TestClient(app) as client:
        resp = client.post("/api/mapping", json={"mine": 0, "nicks": {"1": "Nobody"}})
        assert resp.status_code == 422 and "Nobody" in resp.json()["detail"]


def test_websocket_hears_hello_then_every_mutation(kit):
    server, pinned, app = kit
    pids = sorted(pinned.players)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "hello" and first["hello"]["phase"] == "pending"
        client.post("/api/mapping", json={"mine": 0, "nicks": {}})
        assert ws.receive_json()["hello"]["phase"] == "live"
        client.post("/api/adjust", json={"type": "exclude", "player_id": pids[0], "reason": "not buying"})
        msg = ws.receive_json()
        assert msg["type"] == "board" and str(pids[0]) not in msg["board"]["prices"]


def test_adjust_maps_the_error_classes_to_the_contract(kit):
    server, pinned, app = kit
    with TestClient(app) as client:
        pending = client.post("/api/adjust", json={"type": "exclude", "player_id": 1, "reason": "x"})
        assert pending.status_code == 409
        client.post("/api/mapping", json={"mine": 0, "nicks": {}})
        bad_input = client.post("/api/adjust", json={"type": "value", "player_id": 1, "reason": "x"})
        assert bad_input.status_code == 422            # value without factor
        inert = client.post("/api/adjust", json={"type": "exclude", "player_id": 999_999, "reason": "x"})
        assert inert.status_code == 422
        server.paths.adjustments.parent.mkdir(parents=True, exist_ok=True)
        server.paths.adjustments.write_text("]: not yaml", encoding="utf-8")
        broken_file = client.post("/api/adjust", json={"type": "exclude",
                                                       "player_id": sorted(pinned.players)[0], "reason": "x"})
        assert broken_file.status_code == 400


def test_refresh_rereads_and_reports(kit):
    server, pinned, app = kit
    pids = sorted(pinned.players)
    with TestClient(app) as client:
        client.post("/api/mapping", json={"mine": 0, "nicks": {}})
        server.paths.adjustments.parent.mkdir(parents=True, exist_ok=True)
        server.paths.adjustments.write_text(f"- player_id: {pids[0]}\n  type: exclude\n  reason: hand-edit\n",
                                            encoding="utf-8")
        out = client.post("/api/refresh")
        assert out.status_code == 200 and str(pids[0]) not in out.json()["board"]["prices"]


def test_static_dist_is_served_when_built_and_a_hint_stands_in_when_not(kit, tmp_path):
    server, pinned, _ = kit
    bare = create_app(server)
    with TestClient(bare) as client:
        resp = client.get("/")
        assert resp.status_code == 200 and "poe web-build" in resp.text
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>fantaclaude asta</title>", encoding="utf-8")
    built = create_app(server, web_dist=dist)
    with TestClient(built) as client:
        assert "fantaclaude asta" in client.get("/").text


def test_the_schema_dump_app_needs_no_server():
    app = create_app(None)
    schema = app.openapi()
    assert "/api/board" in schema["paths"] and "/api/adjust" in schema["paths"]
    with TestClient(app) as client:
        assert client.get("/api/hello").status_code == 503
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest core/tests/test_api_app.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.api.app`.

- [ ] **Step 4: Implement the app factory**

```python
# core/src/fantaclaude/api/app.py
"""The HTTP surface of `asta serve`: REST + WebSocket + the built dashboard
+ the mounted MCP (spec, "Dashboard architecture"). One process serves all
four; every route reads or mutates through the one AstaServer, so the
dashboard, the CLI proxy, and the MCP can never disagree about state.

The WebSocket is one-directional: the server pushes `hello`, `board` and
`feed` messages; mutations arrive over REST (and are broadcast back over
the socket), which keeps exactly one mutation path and makes the socket a
pure renderer's feed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from fantaclaude.api.models import (
    AdjustIn,
    AdjustResult,
    BoardPayload,
    HelloPayload,
    MappingIn,
    RefreshResult,
)
from fantaclaude.api.serve import AstaServer, PhaseError
from fantaclaude.asta.adjustments import AdjustmentsError, adjustment_from_entry
from fantaclaude.commands.asta import UsageError


def create_app(server: AstaServer | None, *, web_dist: Path | None = None,
               mcp_app: Any | None = None) -> FastAPI:
    lifespan = None
    if mcp_app is not None:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with mcp_app.lifespan(mcp_app):
                yield
    app = FastAPI(title="fantaclaude asta", lifespan=lifespan)

    def live() -> AstaServer:
        if server is None:
            raise HTTPException(503, "no auction is being served")
        return server

    @app.exception_handler(PhaseError)
    async def _phase(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(UsageError)
    async def _usage(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(AdjustmentsError)
    async def _adjustments(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/hello", response_model=HelloPayload)
    async def hello() -> Any:
        return live().hello()

    @app.get("/api/board", response_model=BoardPayload)
    async def board() -> Any:
        s = live()
        if s.auction is None:
            raise PhaseError("the mapping screen has not been answered; the board does not exist yet")
        return s.auction.board.to_dict()

    @app.post("/api/mapping", response_model=HelloPayload)
    async def mapping(body: MappingIn) -> Any:
        return await live().set_mapping(body.mine, dict(body.nicks))

    @app.post("/api/adjust", response_model=AdjustResult)
    async def adjust(body: AdjustIn) -> Any:
        try:
            adjustment = adjustment_from_entry(body.to_entry(), "api adjust")
        except AdjustmentsError as exc:                 # bad *input*, not a bad file: 422
            raise HTTPException(422, str(exc)) from None
        return await live().adjust(adjustment)

    @app.post("/api/refresh", response_model=RefreshResult)
    async def refresh() -> Any:
        return await live().refresh()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        s = live()
        await websocket.accept()
        import json as _json
        await websocket.send_text(_json.dumps({"type": "hello", "hello": s.hello()}, ensure_ascii=False))
        unsubscribe = s.subscribe(websocket.send_text)
        try:
            while True:
                await websocket.receive_text()          # the socket is one-directional; drain and ignore
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    if mcp_app is not None:
        app.mount("/mcp", mcp_app)
    if web_dist is not None and (web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist, html=True))
    else:
        @app.get("/", response_class=PlainTextResponse)
        async def hint() -> str:
            return "fantaclaude asta serve is running, but the dashboard is not built: run `poe web-build`.\n"
    return app
```

Implementation notes: move the `JSONResponse` import to the top (the inline
imports above are illustrative compression only — this repo does not tolerate
them outside CLI lazy-loading); `websocket.send_text` bound-method is a valid
`Sender`. The `/api/board` 409 goes through `PhaseError` so the CLI proxy
(Task 8) sees one contract.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_api_app.py -c core/pyproject.toml -q`
Expected: PASS (7 tests).

- [ ] **Step 6: Full suite, lint, commit**

```bash
uv run poe test && uv run poe lint
git add core/pyproject.toml uv.lock core/src/fantaclaude/api/app.py core/tests/test_api_app.py
git commit -m "feat(api): FastAPI surface — REST, one-directional WebSocket, static dashboard mount"
```

---

### Task 6: `fantaclaude-asta` — the auction MCP, served by `asta serve` itself

**Files:**
- Modify: `core/pyproject.toml` (via `uv add`)
- Create: `core/src/fantaclaude/asta/mcp.py`
- Modify: `core/src/fantaclaude/commands/asta.py` (rename `_player` →
  `player_of`, alias kept)
- Modify: `.mcp.json`
- Test: `core/tests/test_asta_mcp.py`

**Interfaces:**
- Consumes: `AstaServer`, `PhaseError` (Task 4); `explain` (asta/pricing.py);
  `_player`, `UsageError` (commands/asta.py — import `_player` as
  `player_of`: rename it publicly in `commands/asta.py`, keeping a `_player =
  player_of` alias so existing callers stand); `adjustment_from_entry`,
  `AdjustmentsError`; `duckdb`.
- Produces (used by Task 7): `build_mcp(server: AstaServer, db_path: Path) ->
  FastMCP` with tools `asta_status`, `asta_board(top: int = 5)`,
  `asta_explain(player: str)`, `asta_adjust(type, reason, player=None,
  player_id=None, factor=None, role_class=None, count=None)`,
  `asta_refresh()`, `asta_query(sql: str, limit: int = 50)`; constant
  `MCP_PATH = "/mcp"`.

**Division of labour** (spec, "A second MCP, for the auction" and "What the
model is for"): auction-state tools read the in-memory `Board` directly on
the event loop (microseconds); `asta_query` opens `fanta.duckdb` **read-only
per call inside `asyncio.to_thread`** so a multi-second scan never freezes
the WebSocket. `asta_adjust` proxies through the same `server.adjust` the
dashboard form and the CLI use — one writer. `asta_board` returns the
compact summary (ledgers, tiers, the lot), never the 553-row prices dict:
the model reads a board, it does not diff one.

- [ ] **Step 1: Declare the dependency**

```bash
uv add --package fantaclaude fastmcp
```

Expected: `fastmcp>=3.4.7` in `core/pyproject.toml` (it is already in the
lock via `fantacalcio-mcp`; core now declares what it imports).

- [ ] **Step 2: Write the failing tests**

```python
# core/tests/test_asta_mcp.py
import duckdb
import pytest
from fastmcp import Client

from fantaclaude.api.serve import AstaServer
from fantaclaude.asta.adjustments import EMPTY_LAYER
from fantaclaude.asta.mcp import build_mcp
from fantaclaude.asta.state import parse_snapshot
from fantaclaude.commands.asta import AstaPaths

from test_advisor import SESSION, pinned_run


def snap(picks, *, selected=None, teams=(0, 1, 2)):
    return parse_snapshot({
        "picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i}
                  for i, (pid, tid, cost) in enumerate(picks)],
        "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams],
        "settings": SESSION, "selectedPlayerId": selected, "status": "live", "locked": False})


@pytest.fixture
async def kit(tmp_path, fixture_json, mcp_fixture_json):
    result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    db = tmp_path / "toy.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'a'), (2, 'b')) v(n, s)")
    con.close()
    paths = AstaPaths(db=db, adjustments=tmp_path / "data" / "adjustments.yml",
                      state=tmp_path / "data" / "asta-state.json", records=tmp_path / "records", kb=tmp_path / "kb")
    server = AstaServer(run=pinned, layer=EMPTY_LAYER, participants={}, scenario=None,
                        paths=paths, mode="replay", session_code="FA-nri-okm")
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    return server, pinned, build_mcp(server, db)


async def test_status_and_board_read_the_live_state(kit):
    server, pinned, mcp = kit
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)], selected=pids[1]))
    async with Client(mcp) as client:
        status = (await client.call_tool("asta_status", {})).data
        assert status["phase"] == "live" and status["picks"] == 1 and status["session_code"] == "FA-nri-okm"
        board = (await client.call_tool("asta_board", {"top": 3})).data
        assert board["me"]["credits"] == 500 and board["lot"]["player_id"] == pids[1]
        assert all(len(rows) <= 3 for rows in board["tiers"].values())
        assert "prices" not in board                       # the compact summary, never the 553-row dict


async def test_explain_names_the_trace_and_adjust_writes_through_the_one_path(kit):
    server, pinned, mcp = kit
    pids = sorted(pinned.players)
    name = pinned.players[pids[0]].name
    async with Client(mcp) as client:
        out = (await client.call_tool("asta_explain", {"player": str(pids[0])})).data
        assert out["player"]["player_id"] == pids[0] and out["trace"]["band"]["p50"] >= 0
        adj = (await client.call_tool("asta_adjust", {"type": "exclude", "player_id": pids[0],
                                                      "reason": "the room says he is gone"})).data
        assert adj["count"] == 1 and adj["band_after"] is None
        out2 = (await client.call_tool("asta_explain", {"player": str(pids[0])})).data
        assert out2["trace"] is None and out2["adjustments"]
    assert server.paths.adjustments.is_file()


async def test_query_runs_read_only_in_a_thread_with_a_row_cap(kit):
    server, pinned, mcp = kit
    async with Client(mcp) as client:
        out = (await client.call_tool("asta_query", {"sql": "SELECT n, s FROM t ORDER BY n", "limit": 1})).data
        assert out["columns"] == ["n", "s"] and out["rows"] == [[1, "a"]] and out["truncated"] is True
        with pytest.raises(Exception) as err:
            await client.call_tool("asta_query", {"sql": "CREATE TABLE nope (x INT)"})
        assert "read" in str(err.value).lower() or "write" in str(err.value).lower()


async def test_tools_refuse_cleanly_while_pending(tmp_path, fixture_json, mcp_fixture_json):
    result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    paths = AstaPaths(db=tmp_path / "toy.duckdb", adjustments=tmp_path / "a.yml",
                      state=tmp_path / "s.json", records=tmp_path / "r", kb=tmp_path / "kb")
    server = AstaServer(run=pinned, layer=EMPTY_LAYER, participants={}, scenario=None,
                        paths=paths, mode="feed", session_code="FA-x-y")
    mcp = build_mcp(server, paths.db)
    async with Client(mcp) as client:
        status = (await client.call_tool("asta_status", {})).data
        assert status["phase"] == "pending"
        with pytest.raises(Exception) as err:
            await client.call_tool("asta_board", {})
        assert "mapping" in str(err.value)
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest core/tests/test_asta_mcp.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.asta.mcp`.

- [ ] **Step 4: Implement the tool surface**

First, in `core/src/fantaclaude/commands/asta.py`, rename `_player` to
`player_of` and keep `_player = player_of` beside it so every existing caller
and test stands unchanged.

```python
# core/src/fantaclaude/asta/mcp.py
"""fantaclaude-asta: the auction MCP (spec, "A second MCP, for the
auction"). Served over HTTP by `asta serve` itself — not a separate process
— so every tool reads the same in-memory state the dashboard is showing,
and being unavailable when no auction is served is correct rather than a
limitation.

Auction-state tools answer from memory on the event loop; `asta_query`
opens fanta.duckdb read-only per call inside a threadpool so an analytical
scan never blocks the WebSocket. `asta_adjust` writes through
server.adjust — the same one-writer path as the dashboard form and the CLI
proxy. The model changes inputs and interprets outputs; it never computes
the number (spec, "What the model is for"): `asta_explain` returns the
pricer's own trace to read, not to recompute.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import duckdb
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fantaclaude.api.serve import AstaServer, PhaseError
from fantaclaude.asta.adjustments import AdjustmentsError, adjustment_from_entry
from fantaclaude.asta.pricing import explain as explain_price
from fantaclaude.commands.asta import UsageError, player_of

MCP_PATH = "/mcp"

INSTRUCTIONS = (
    "Live read-and-adjust access to the fantaclaude auction board while `fantaclaude asta serve` runs. "
    "Bands and pressure are computed by the server; read them, explain them, and turn facts from the room "
    "into adjustments — never recompute a price. `asta_query` reads the analytical database (fanta.duckdb) "
    "read-only; auction state itself is not in the database, use the board tools for it."
)


def build_mcp(server: AstaServer, db_path: Path) -> FastMCP:
    mcp = FastMCP(name="fantaclaude-asta", instructions=INSTRUCTIONS)

    def board():
        if server.auction is None:
            raise ToolError("the mapping screen has not been answered yet; the board does not exist")
        return server.auction.board

    @mcp.tool
    def asta_status() -> dict[str, Any]:
        """The serve process's state: phase, feed status, session, run, picks so far, problem count."""
        hello = server.hello()
        b = hello["board"]
        return {"phase": hello["phase"], "mode": hello["mode"], "feed": hello["feed"],
                "session_code": hello["session_code"], "run": hello["run"], "scenario": hello["scenario"],
                "picks": 0 if b is None else b["picks"],
                "problems": [] if b is None else b["problems"],
                "league_conflicts": hello["league_conflicts"]}

    @mcp.tool
    def asta_board(top: int = 5) -> dict[str, Any]:
        """The board in summary: my ledger, every team's credits and slots, the lot on the block with its
        band and pressure, the top `top` unsold players per role class, composition and inflation. The
        full per-player dict is the dashboard's; ask asta_explain for one player's trace."""
        b = board()
        d = b.to_dict()
        return {"run_id": d["run_id"], "scenario": d["scenario"], "settings": d["settings"],
                "league_conflicts": d["league_conflicts"], "problems": d["problems"],
                "me": d["me"], "teams": d["teams"], "market_credits": d["market_credits"],
                "inflation": d["inflation"], "composition": d["composition"],
                "credits_by_class": d["credits_by_class"], "reserve": d["reserve"], "budget": d["budget"],
                "targets_departed": d["targets_departed"], "lot": d["lot"], "lot_pressure": d["lot_pressure"],
                "adjustments": d["adjustments"], "tiers": b.tiers(top)}

    @mcp.tool
    def asta_explain(player: str) -> dict[str, Any]:
        """One player's price, explained from the pricer's own trace: band, walk/buy values, expected
        price, pressure (who can still bid and how deep), and any adjustment touching him. `player` is
        the listone's spelling ("Martinez L.") or the listone id."""
        b = board()
        try:
            who = player_of(server.run, player)
        except UsageError as exc:
            raise ToolError(str(exc)) from None
        pick = b.state.picks.get(who.player_id)
        trace = explain_price(b.pricing, who.player_id) if who.player_id in b.pricing.prices else None
        pressure = b.pressure[who.player_id].to_dict() if who.player_id in b.pressure else None
        return {"player": who.to_dict(),
                "sold_to": None if pick is None else pick.team_id,
                "cost": None if pick is None else pick.cost,
                "trace": trace, "pressure": pressure,
                "adjustments": [e.adjustment.describe() for e in b.layer.entries if e.player_id == who.player_id]}

    @mcp.tool
    async def asta_adjust(type: str, reason: str, player: str | None = None, player_id: int | None = None,
                          factor: float | None = None, role_class: str | None = None,
                          count: int | None = None) -> dict[str, Any]:
        """Turn a fact from the room into an adjustment — value (with factor), exclude, or target (with
        role_class and count) — appended to data/adjustments.yml with its reason and applied to the board
        at once, through the same single-writer path as the dashboard form."""
        raw = {k: v for k, v in (("player", player), ("player_id", player_id), ("type", type),
                                 ("factor", factor), ("class", role_class), ("count", count),
                                 ("reason", reason)) if v is not None}
        try:
            adjustment = adjustment_from_entry(raw, "asta_adjust")
        except AdjustmentsError as exc:
            raise ToolError(str(exc)) from None
        try:
            out = await server.adjust(adjustment)
        except (PhaseError, UsageError, AdjustmentsError) as exc:
            raise ToolError(str(exc)) from None
        band_after = None
        if out["player_id"] is not None:
            row = out["board"]["prices"].get(str(out["player_id"]))
            band_after = None if row is None else row["band"]
        return {"described": out["described"], "count": out["count"], "band_after": band_after,
                "problems": out["board"]["problems"]}

    @mcp.tool
    async def asta_refresh() -> dict[str, Any]:
        """Reread data/adjustments.yml and the participant dossiers, re-price the whole board, and
        broadcast it — the hand-edited-file case."""
        try:
            out = await server.refresh()
        except (PhaseError, AdjustmentsError) as exc:
            raise ToolError(str(exc)) from None
        return {"problems": out["problems"], "adjustments": out["board"]["adjustments"]}

    @mcp.tool
    async def asta_query(sql: str, limit: int = 50) -> dict[str, Any]:
        """Run one read-only SQL query against fanta.duckdb (players, history, valuations — see
        `fantaclaude schema`). Auction state is NOT in the database; use the board tools. Rows are
        capped at `limit`."""
        def work() -> dict[str, Any]:
            con = duckdb.connect(str(db_path), read_only=True)
            try:
                cursor = con.execute(sql)
                columns = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(limit + 1)
            finally:
                con.close()
            return {"columns": columns, "rows": [list(r) for r in rows[:limit]],
                    "truncated": len(rows) > limit}
        try:
            return await asyncio.to_thread(work)
        except duckdb.Error as exc:
            raise ToolError(str(exc)) from None

    return mcp
```

Then add the endpoint to `.mcp.json` (the server answers only while
`asta serve` runs, which the spec calls correct):

```json
{
  "mcpServers": {
    "fantacalcio": { … unchanged … },
    "fantaclaude-asta": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_asta_mcp.py -c core/pyproject.toml -q`
Expected: PASS. Two fastmcp-3.4.7 surface details to verify while
implementing (both installed, both trivially checkable in-venv, neither a
design question): whether `@mcp.tool` needs parentheses, and whether
`CallToolResult.data` is the structured payload accessor the tests use —
adjust the test accessor to the installed library's real API if it differs,
never the tool shapes.

- [ ] **Step 6: Mount smoke — the MCP answers under the app**

Append to `core/tests/test_api_app.py`:

```python
def test_the_mcp_mounts_under_the_app_and_answers(kit):
    server, pinned, _ = kit
    from fantaclaude.asta.mcp import build_mcp
    mcp_app = build_mcp(server, server.paths.db).http_app(path="/", transport="http", stateless_http=True)
    app = create_app(server, mcp_app=mcp_app)
    with TestClient(app) as client:
        resp = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                           headers={"accept": "application/json, text/event-stream",
                                    "content-type": "application/json"})
        assert resp.status_code != 404
```

Run: `uv run pytest core/tests/test_api_app.py -c core/pyproject.toml -q` — PASS.

- [ ] **Step 7: Full suite, lint, commit**

```bash
uv run poe test && uv run poe lint
git add core/pyproject.toml uv.lock core/src/fantaclaude/asta/mcp.py core/src/fantaclaude/commands/asta.py .mcp.json core/tests/test_asta_mcp.py core/tests/test_api_app.py
git commit -m "feat(asta): fantaclaude-asta MCP — board, explain, adjust, refresh and read-only query over HTTP"
```

---

### Task 7: `fantaclaude asta serve` — startup, sources, the process

**Files:**
- Create: `core/src/fantaclaude/commands/serve.py`
- Modify: `core/src/fantaclaude/paths.py` (add `web_dist_dir()`)
- Modify: `core/src/fantaclaude/cli/app.py` (the `asta serve` command)
- Modify: `core/src/fantaclaude/commands/doctor.py` (the `dashboard` check)
- Test: `core/tests/test_serve_cli.py`, one test appended to
  `core/tests/test_doctor.py`

**Interfaces:**
- Consumes: everything above — `AstaLiveFeed`, `check_session_code`,
  `FeedError`, `OFFLINE` (asta_live); `AstaServer` (api/serve);
  `create_app` (api/app); `build_mcp`, `MCP_PATH` (asta/mcp); `open_run`,
  `load_layer`, `load_dossiers`, `resolve_mapping`, `AstaPaths`, `UsageError`
  (commands/asta); `read_snapshots`, `SnapshotError` (asta/state);
  `read_state`, `StateFileError` (asta/snapshot); `NotReady`
  (commands/ingest); `UnknownScenarioError` (analysis/valuation);
  `asta_captures_dir`, `web_dist_dir` (paths); `uvicorn`, `httpx`.
- Produces:

```python
@dataclass(frozen=True)
class ServeOptions:
    session: str | None = None; replay: Path | None = None; speed: float = 1.0
    state: Path | None = None; run_id: str | None = None; scenario: str | None = None
    me: str | None = None; maps: tuple[str, ...] = (); host: str = "127.0.0.1"
    port: int = 8765; capture: bool = True

@dataclass(frozen=True)
class ServePlan:
    server: AstaServer; mode: str; session_code: str | None
    snapshots: tuple[Snapshot, ...]          # replay mode; () otherwise
    stored_snapshot: Snapshot | None         # state mode; None otherwise
    capture_path: Path | None                # feed mode with capture on; None otherwise
    notes: tuple[str, ...]                   # e.g. the state file's run differing from the pinned one

def prepare(con, paths: AstaPaths, opts: ServeOptions) -> ServePlan
async def run_serve(plan: ServePlan, opts: ServeOptions, paths: AstaPaths) -> None
REPLAY_INTERVAL = 2.0                        # seconds between replayed snapshots at --speed 1
```

**Startup sequence** (spec, "The session code is asked for at launch" and
"`asta serve --run <id>` … names it on the status line"): pin the run (named
on stdout, "superseded" said plainly), load the adjustment layer and the
dossiers, choose exactly one source —

- `--session FA-xxx-xxx` (or the interactive prompt): the live feed. Mapping
  comes from the screen, or from `--me`/`--map` when the first snapshot
  arrives. Capture on by default to
  `data/raw/asta_live/<code>-<UTCdate>.jsonl`.
- `--replay FILE --speed N`: the rehearsal — the captured session drives the
  same server, one snapshot every `REPLAY_INTERVAL / N` seconds; no capture.
- `--state [FILE]`: the post-auction review — `data/asta-state.json` (or
  FILE) served with no feed; the file's own mapping answers the screen,
  flags layer over it exactly as `asta board` does.

— then serve uvicorn on `host:port` with the dashboard at `/`, the API under
`/api`, the WebSocket at `/ws` and the MCP at `/mcp`, until Ctrl-C.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/test_serve_cli.py
import duckdb
import pytest
from pathlib import Path
from typer.testing import CliRunner

from fantaclaude.cli.app import ExitCode, app

from test_asta_cli import _ranked

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


def test_prepare_state_mode_reloads_the_file_and_notes_a_run_mismatch(monkeypatch, tmp_path, fixture_json,
                                                                      mcp_fixture_json):
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
```

And appended to `core/tests/test_doctor.py` (follow its existing fixture
style for building a workspace):

```python
def test_doctor_reports_the_dashboard_bundle(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    from test_asta_cli import _ranked
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    r = runner.invoke(app, ["doctor", "--json"])
    checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["dashboard"]["ok"] is False and "poe web-build" in checks["dashboard"]["detail"]
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    r2 = runner.invoke(app, ["doctor", "--json"])
    checks2 = {c["name"]: c for c in json.loads(r2.stdout)["checks"]}
    assert checks2["dashboard"]["ok"] is True
```

(Adapt the invocation to `test_doctor.py`'s real harness — it has its own
runner/fixtures; the assertion body is the contract. `web_dist_dir()` must
resolve under `FANTACALCIO_HOME`, which `paths.workspace_root()` already
honours.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest core/tests/test_serve_cli.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.commands.serve`.

- [ ] **Step 3: Implement**

`core/src/fantaclaude/paths.py`:

```python
def web_dist_dir() -> Path:
    """web/dist: the built dashboard bundle FastAPI mounts (poe web-build)."""
    return workspace_root() / "web" / "dist"
```

`core/src/fantaclaude/commands/serve.py`:

```python
"""fantaclaude asta serve: the night's one process (spec, "Dashboard
architecture" and "One process in production"). Pins the run and names it,
loads the layer and the dossiers, chooses exactly one source — the live
feed, a replayed capture, or the state file — and serves the dashboard,
the REST API, the WebSocket and the fantaclaude-asta MCP from one uvicorn.

The feed dying is not the server dying: a fatal FeedError is reported and
the board stands on its last state (the printed tier board is the
backstop); transport drops reconnect with backoff inside the adapter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx
import typer
import uvicorn

from fantaclaude.analysis.valuation import UnknownScenarioError
from fantaclaude.api.app import create_app
from fantaclaude.api.serve import AstaServer
from fantaclaude.asta.mcp import build_mcp
from fantaclaude.asta.snapshot import StateFileError, read_state
from fantaclaude.asta.state import Snapshot, SnapshotError, read_snapshots
from fantaclaude.commands.asta import (
    AstaPaths,
    UsageError,
    load_dossiers,
    load_layer,
    open_run,
    resolve_mapping,
)
from fantaclaude.commands.ingest import NotReady
from fantaclaude.ingest.asta_live import OFFLINE, AstaLiveFeed, FeedError, check_session_code
from fantaclaude.paths import asta_captures_dir, web_dist_dir
from fantaclaude.timeutil import utc_now

REPLAY_INTERVAL = 2.0


@dataclass(frozen=True)
class ServeOptions:
    session: str | None = None
    replay: Path | None = None
    speed: float = 1.0
    state: Path | None = None
    run_id: str | None = None
    scenario: str | None = None
    me: str | None = None
    maps: tuple[str, ...] = ()
    host: str = "127.0.0.1"
    port: int = 8765
    capture: bool = True


@dataclass(frozen=True)
class ServePlan:
    server: AstaServer
    mode: str
    session_code: str | None
    snapshots: tuple[Snapshot, ...]
    stored_snapshot: Snapshot | None
    capture_path: Path | None
    notes: tuple[str, ...]


def prepare(con: duckdb.DuckDBPyConnection, paths: AstaPaths, opts: ServeOptions) -> ServePlan:
    sources = [name for name, given in (("--session", opts.session), ("--replay", opts.replay),
                                        ("--state", opts.state)) if given]
    if len(sources) != 1:
        raise UsageError("serve takes exactly one source: --session (the live feed), "
                         "--replay (a captured session), or --state (the state file); got "
                         + (", ".join(sources) or "none"))
    if opts.speed <= 0:
        raise UsageError(f"--speed must be positive, got {opts.speed}")
    if opts.replay is None and opts.speed != 1.0:
        raise UsageError("--speed paces a --replay; it means nothing for a live feed")
    run = open_run(con, opts.run_id)
    try:
        scenario = None if opts.scenario is None else run.scenario(opts.scenario).name
    except UnknownScenarioError as exc:
        raise UsageError(str(exc)) from None
    layer = load_layer(paths.adjustments, run)
    participants = load_dossiers(paths.kb)
    common = dict(run=run, layer=layer, participants=participants, scenario=scenario, paths=paths)
    notes: list[str] = []
    if opts.session is not None:
        try:
            code = check_session_code(opts.session)
        except FeedError as exc:
            raise UsageError(str(exc)) from None
        capture = (asta_captures_dir() / f"{code}-{utc_now():%Y%m%d}.jsonl") if opts.capture else None
        server = AstaServer(**common, mode="feed", session_code=code,
                            pending_me=opts.me, pending_maps=opts.maps)
        return ServePlan(server, "feed", code, (), None, capture, ())
    if opts.replay is not None:
        if not opts.replay.is_file():
            raise UsageError(f"--replay names {opts.replay}, which is not a file")
        try:
            snapshots = tuple(read_snapshots(opts.replay))
        except (OSError, UnicodeDecodeError, SnapshotError) as exc:
            raise NotReady(str(exc)) from None
        if not snapshots:
            raise UsageError(f"{opts.replay} holds no snapshots")
        mapping = None
        if opts.me is not None or opts.maps:
            mapping = resolve_mapping(snapshots[0].teams, me=opts.me, maps=opts.maps, participants=participants)
        server = AstaServer(**common, mode="replay", session_code=None, mapping=mapping)
        return ServePlan(server, "replay", None, snapshots, None, None, ())
    state_path = opts.state
    if not state_path.is_file():
        raise UsageError(f"--state names {state_path}, which is not a file")
    try:
        stored = read_state(state_path)
    except StateFileError as exc:
        raise NotReady(str(exc)) from None
    if stored.run_id != run.run_id:
        notes.append(f"the state file was written under run {stored.run_id}; this board prices run {run.run_id}")
    mapping = (stored.mapping if opts.me is None and not opts.maps
               else resolve_mapping(stored.snapshot.teams, me=opts.me or str(stored.mapping.mine),
                                    maps=opts.maps, participants=participants,
                                    remembered=stored.mapping.nicks))
    server = AstaServer(**common, mode="state", session_code=stored.session_code, mapping=mapping)
    return ServePlan(server, "state", stored.session_code, (), stored.snapshot, None, tuple(notes))


async def _replay_task(server: AstaServer, snapshots: tuple[Snapshot, ...], speed: float) -> None:
    for snap in snapshots:
        await server.on_snapshot(snap)
        await asyncio.sleep(REPLAY_INTERVAL / speed)


async def _feed_task(server: AstaServer, plan: ServePlan) -> None:
    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(plan.session_code, client=client, on_snapshot=server.on_snapshot,
                            on_status=server.set_feed_status, capture=plan.capture_path)
        try:
            await feed.run()
        except FeedError as exc:
            typer.echo(f"the feed is gone: {exc} — the board stands on its last state", err=True)
            await server.set_feed_status(OFFLINE)


async def run_serve(plan: ServePlan, opts: ServeOptions, paths: AstaPaths) -> None:
    mcp_app = build_mcp(plan.server, paths.db).http_app(path="/", transport="http", stateless_http=True)
    app = create_app(plan.server, web_dist=web_dist_dir(), mcp_app=mcp_app)
    config = uvicorn.Config(app, host=opts.host, port=opts.port, log_level="warning")
    uv_server = uvicorn.Server(config)
    side: asyncio.Task | None = None
    if plan.mode == "feed":
        side = asyncio.create_task(_feed_task(plan.server, plan))
    elif plan.mode == "replay":
        side = asyncio.create_task(_replay_task(plan.server, plan.snapshots, opts.speed))
    else:
        await plan.server.on_snapshot(plan.stored_snapshot)
    try:
        await uv_server.serve()          # returns on Ctrl-C; uvicorn installs the signal handlers
    finally:
        if side is not None:
            side.cancel()
            try:
                await side
            except asyncio.CancelledError:
                pass
```

`core/src/fantaclaude/cli/app.py` — the command (same lazy-import,
`_asta_errors`, option-singleton conventions as its siblings):

```python
@asta_app.command("serve")
def asta_serve_cmd(
    session: str | None = typer.Option(None, "--session", help="FantaAstaLive session code (FA-xxx-xxx); prompted for when no source is given."),
    replay: Path | None = typer.Option(None, "--replay", help="Serve a captured session (JSON lines) instead of the live feed — the rehearsal."),
    speed: float = typer.Option(1.0, "--speed", help="Replay pace: one snapshot every 2/N seconds."),
    state: Path | None = typer.Option(None, "--state", help="Serve a state file with no feed — the post-auction review."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    me: str | None = ME_OPTION,
    map_: list[str] | None = MAP_OPTION,
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address. Localhost by design: the room is not served."),
    port: int = typer.Option(8765, "--port", help="One port for the dashboard, the API, the WebSocket and the MCP."),
    no_capture: bool = typer.Option(False, "--no-capture", help="Live mode: do not append feed nodes to data/raw/asta_live/."),
) -> None:
    """Serve the live board: mirror the FantaAstaLive session, price every change, and expose the dashboard (/), the API (/api), the WebSocket (/ws) and the fantaclaude-asta MCP (/mcp) from one process. The only network it touches is the Firebase session, read-only."""
    import asyncio

    from fantaclaude.commands.serve import ServeOptions, prepare, run_serve

    if session is None and replay is None and state is None:
        session = typer.prompt("FantaAstaLive session code (FA-xxx-xxx)")
    opts = ServeOptions(session=session, replay=replay, speed=speed, state=state, run_id=run,
                        scenario=scenario, me=me, maps=tuple(map_ or ()), host=host, port=port,
                        capture=not no_capture)
    paths = _asta_paths()
    with _asta_errors():
        con = _open_read_only()
        try:
            plan = prepare(con, paths, opts)
        finally:
            con.close()
        typer.echo(plan.server.run.describe())
        for note in plan.notes:
            typer.echo(f"note: {note}")
        typer.echo(f"serving {plan.mode} on http://{host}:{port}  (dashboard /, MCP /mcp) — Ctrl-C to stop")
        asyncio.run(run_serve(plan, opts, paths))
```

`core/src/fantaclaude/commands/doctor.py` — one new check, wired into the
same list the other workspace checks join, after the state-file check:

```python
def _dashboard_check() -> Check:
    from fantaclaude.paths import web_dist_dir
    index = web_dist_dir() / "index.html"
    if index.is_file():
        return Check("dashboard", True, f"built ({index})")
    return Check("dashboard", False, "web/dist/index.html missing — run `poe web-build` before the night")
```

One deliberate deviation from the spec, stated rather than slipped: the
spec's doctor list includes "does the session code still connect". That
check needs the network and an anonymous Firebase sign-in per run, and
`doctor` is a command this repo runs freely — CLAUDE.md's discipline
("never fetch to check") wins. The connect check lives where the spec's
failure-modes table actually needs it: `asta serve` verifies the session at
connect, before the room fills, and fails loud (`FeedError: no session …`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_serve_cli.py core/tests/test_doctor.py -c core/pyproject.toml -q`
Expected: PASS. The DB connection closes before serving begins — the run is
in memory, and `asta_query` opens its own read-only connections per call.

- [ ] **Step 5: Full suite, lint, commit**

```bash
uv run poe test && uv run poe lint
git add core/src/fantaclaude/commands/serve.py core/src/fantaclaude/commands/doctor.py \
        core/src/fantaclaude/paths.py core/src/fantaclaude/cli/app.py \
        core/tests/test_serve_cli.py core/tests/test_doctor.py
git commit -m "feat(cli): asta serve — live feed, replay and state-file modes behind one process"
```

---

### Task 8: `asta adjust` proxies to the running server; `asta refresh` exists

**Files:**
- Modify: `core/src/fantaclaude/commands/asta.py` (proxy helpers)
- Modify: `core/src/fantaclaude/cli/app.py` (`adjust --server`, new `refresh`)
- Test: append to `core/tests/test_asta_cli.py`

**Interfaces:**
- Consumes: the HTTP contract of Task 5 (`POST /api/adjust` → 200
  `AdjustResult` | 422 | 409 | 400; `POST /api/refresh` → 200
  `RefreshResult` | 409 | 400), `Adjustment.to_entry()`, `UsageError`,
  `NotReady`, `httpx`.
- Produces (in `commands/asta.py`):

```python
SERVER_URL_DEFAULT = "http://127.0.0.1:8765"
def server_adjust(url: str, adjustment: Adjustment, timeout: float = 5.0) -> dict[str, Any] | None
    # None ⇢ nothing is listening (the offline path takes over); UsageError ⇢ 422; NotReady ⇢ 409/400
def server_refresh(url: str, timeout: float = 30.0) -> dict[str, Any]
    # NotReady when nothing is listening: refresh is a live-server action
```

**Why** (spec, "Live adjustments"): while the server runs it is the one
writer of `adjustments.yml` and the one place a change re-prices the live
board and reaches the dashboard. A CLI append behind the server's back would
be the divergence the design forbids. With no server, the CLI *is* the one
writer and the offline path stands unchanged. The probe is one localhost
connect: refused-in-microseconds when nothing listens.

- [ ] **Step 1: Write the failing tests** (append to `core/tests/test_asta_cli.py`)

```python
import httpx
import respx

ADJUST_URL = "http://127.0.0.1:8765/api/adjust"
REFRESH_URL = "http://127.0.0.1:8765/api/refresh"


def _served_adjust_payload(pid):
    return {"described": f"exclude player_id {pid} (room says gone)", "count": 3, "player_id": pid,
            "board": {"prices": {}, "problems": [], "adjustments": {"count": 3, "applied": 3, "value_factor": {},
                                                                    "excluded": [pid], "targets": {},
                                                                    "problems": [], "sha256": ""}}}


def test_adjust_proxies_to_a_running_server_and_writes_nothing_locally(monkeypatch, tmp_path, fixture_json,
                                                                       mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    board = runner.invoke(app, ["asta", "board", "--json"])
    pid = int(next(iter(json.loads(board.stdout)["prices"])))
    with respx.mock:
        respx.post(ADJUST_URL).respond(200, json=_served_adjust_payload(pid))
        r = runner.invoke(app, ["asta", "adjust", "--type", "exclude", "--player-id", str(pid),
                                "--reason", "room says gone"])
    assert r.exit_code == ExitCode.OK, r.output
    assert "server" in r.output and "3 entries" in r.output
    assert not (tmp_path / "data" / "adjustments.yml").exists()      # the server owns the file


def test_adjust_falls_back_to_the_offline_path_when_nothing_listens(monkeypatch, tmp_path, fixture_json,
                                                                    mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    board = runner.invoke(app, ["asta", "board", "--json"])
    pid = int(next(iter(json.loads(board.stdout)["prices"])))
    with respx.mock:
        respx.post(ADJUST_URL).mock(side_effect=httpx.ConnectError("nothing listening"))
        r = runner.invoke(app, ["asta", "adjust", "--type", "exclude", "--player-id", str(pid),
                                "--reason", "room says gone"])
    assert r.exit_code == ExitCode.OK, r.output
    assert (tmp_path / "data" / "adjustments.yml").exists()          # offline: the CLI is the writer


def test_adjust_maps_server_verdicts_onto_the_exit_contract(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    with respx.mock:
        respx.post(ADJUST_URL).respond(422, json={"detail": "'Nobody' is not in the pinned run"})
        r = runner.invoke(app, ["asta", "adjust", "--type", "exclude", "--player", "Nobody", "--reason", "x"])
    assert r.exit_code == ExitCode.USAGE and "Nobody" in r.output
    with respx.mock:
        respx.post(ADJUST_URL).respond(409, json={"detail": "the mapping screen has not been answered"})
        r2 = runner.invoke(app, ["asta", "adjust", "--type", "exclude", "--player", "Malen", "--reason", "x"])
    assert r2.exit_code == ExitCode.NOT_READY


def test_refresh_needs_a_running_server(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    with respx.mock:
        respx.post(REFRESH_URL).mock(side_effect=httpx.ConnectError("nothing listening"))
        r = runner.invoke(app, ["asta", "refresh"])
    assert r.exit_code == ExitCode.NOT_READY and "asta serve" in r.output
    with respx.mock:
        respx.post(REFRESH_URL).respond(200, json={
            "board": {"adjustments": {"count": 1, "applied": 1, "value_factor": {}, "excluded": [],
                                      "targets": {}, "problems": [], "sha256": "ff"}},
            "problems": []})
        r2 = runner.invoke(app, ["asta", "refresh"])
    assert r2.exit_code == ExitCode.OK and "1 applied" in r2.output
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest core/tests/test_asta_cli.py -c core/pyproject.toml -q -k "proxi or listens or verdicts or refresh_needs"`
Expected: FAIL — the offline path runs where the proxy should (first test
writes the file), `refresh` is an unknown command.

- [ ] **Step 3: Implement**

In `core/src/fantaclaude/commands/asta.py` (httpx imported lazily inside the
functions, matching the CLI's lazy-import convention for optional paths):

```python
SERVER_URL_DEFAULT = "http://127.0.0.1:8765"


def _server_payload(resp) -> dict[str, Any]:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    if resp.status_code == 200:
        return resp.json()
    message = detail or f"the server answered {resp.status_code}"
    if resp.status_code == 422:
        raise UsageError(message)
    raise NotReady(message)          # 409 pending, 400 malformed file, anything else


def server_adjust(url: str, adjustment: Adjustment, timeout: float = 5.0) -> dict[str, Any] | None:
    """POST the adjustment to a running `asta serve`; None when nothing is
    listening there — the offline path appends directly and stays the one
    writer. While a server runs, it is the one writer (spec, "Live
    adjustments"), so the CLI never touches the file behind its back."""
    import httpx

    try:
        resp = httpx.post(f"{url}/api/adjust", json=adjustment.to_entry(), timeout=timeout)
    except httpx.ConnectError:
        return None
    return _server_payload(resp)


def server_refresh(url: str, timeout: float = 30.0) -> dict[str, Any]:
    import httpx

    try:
        resp = httpx.post(f"{url}/api/refresh", timeout=timeout)
    except httpx.ConnectError:
        raise NotReady(f"no `asta serve` is listening at {url} — refresh re-prices a live board; "
                       f"offline boards recompute on every command") from None
    return _server_payload(resp)
```

In `core/src/fantaclaude/cli/app.py`: a shared option singleton
`SERVER_OPTION = typer.Option(SERVER_URL_DEFAULT-equivalent literal,
"--server", help="The running asta serve to proxy through (adjust falls back
to the offline path when nothing is listening).")` — declare the literal
`"http://127.0.0.1:8765"` here and assert equality with
`commands.asta.SERVER_URL_DEFAULT` in a test, keeping the CLI module free of
eager imports.

`asta_adjust_cmd` gains `server_: str = SERVER_OPTION` and, right after
building `adjustment` (before `_open_read_only`):

```python
        from fantaclaude.commands.asta import server_adjust

        proxied = server_adjust(server_, adjustment)
        if proxied is not None:
            prices = proxied["board"].get("prices", {})
            row = None if proxied.get("player_id") is None else prices.get(str(proxied["player_id"]))
            emit({"applied_via": server_, "described": proxied["described"], "count": proxied["count"],
                  "player_id": proxied.get("player_id"),
                  "band": None if row is None else row["band"],
                  "problems": proxied["board"].get("problems", [])},
                 json_=json_, render=_render_adjust_live)
            return
```

with

```python
def _render_adjust_live(payload: dict) -> str:
    lines = [f"applied via the running server at {payload['applied_via']} "
             f"({payload['count']} entries): {payload['described']}"]
    if payload["player_id"] is not None:
        lines.append(f"his band now: {_band(payload['band'])}")
    lines += [f"problem: {p}" for p in payload["problems"]]
    return "\n".join(lines)
```

and the new command:

```python
@asta_app.command("refresh")
def asta_refresh_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    server_: str = SERVER_OPTION,
) -> None:
    """Tell the running `asta serve` to reread data/adjustments.yml and the dossiers and re-price the board — the hand-edited-file case (live-event requirement 6). Offline boards recompute on every command, so this needs the server."""
    from fantaclaude.commands.asta import server_refresh

    with _asta_errors():
        payload = server_refresh(server_)
    adj = payload["board"]["adjustments"]
    emit({"applied_via": server_, "adjustments": adj, "problems": payload["problems"]}, json_=json_,
         render=lambda p: f"refreshed via {p['applied_via']}: {p['adjustments']['count']} adjustment(s), "
                          f"{p['adjustments']['applied']} applied"
                          + ("".join(f"\nproblem: {q}" for q in p["problems"])))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_asta_cli.py -c core/pyproject.toml -q`
Expected: PASS — the new four plus every pre-existing asta CLI test
(the offline fallback keeps them green; the ConnectError probe in tests that
never mock the URL must not fire, so the proxy call happens **only** inside
`asta adjust`/`asta refresh`, never in `board`/`explain`/`replay`/`close`).
Note: existing adjust tests now hit the proxy probe first — they run with no
respx mock, so the real `httpx.post` to 127.0.0.1:8765 must be refused fast;
if any CI environment has that port open, they would misroute. Guard: wrap
the pre-existing adjust invocations' assertions unchanged, and add
`monkeypatch.setattr("fantaclaude.commands.asta.server_adjust", lambda *a, **k: None)`
in a small autouse fixture scoped to the *old* tests only if flakiness
appears; do not weaken the four new tests.

- [ ] **Step 5: Full suite, lint, commit**

```bash
uv run poe test && uv run poe lint
git add core/src/fantaclaude/commands/asta.py core/src/fantaclaude/cli/app.py core/tests/test_asta_cli.py
git commit -m "feat(cli): asta adjust proxies the running server; asta refresh joins the contract"
```

---

### Task 9: `web/` scaffold — Vite, Tailwind, shadcn, generated types, poe tasks

**Files:**
- Create: `web/` (Vite react-ts template + Tailwind v4 + shadcn/ui init)
- Create: `core/src/fantaclaude/api/openapi_dump.py`
- Create: `web/src/api/types.ts`; generate + commit `web/src/api/schema.d.ts`
- Modify: `pyproject.toml` (poe tasks), `.gitignore`
- Test: `core/tests/test_api_app.py` (one appended test for the dump)

**Interfaces:**
- Consumes: `create_app(None)` (Task 5) for the OpenAPI document; node 24 /
  npm 11 (on the machine — "Source facts").
- Produces: `poe web-dev` (vite + the replayed server together), `poe
  web-build` (tsc + vite build → `web/dist/`), `poe types` (OpenAPI →
  `web/src/api/schema.d.ts`); the type aliases Tasks 10–11 import from
  `@/api/types`.

The generated `schema.d.ts` is **committed**: `poe web-build` must work on a
fresh clone without a running server, and `poe types` regenerates it whenever
the models change (a stale one shows up as a `tsc` error or a diff — both
loud). External CLIs (`create vite`, `shadcn`) evolve; where a flag below has
drifted, consult `--help` and keep the *outcome* pinned by this task, not the
exact flag.

- [ ] **Step 1: Scaffold Vite + Tailwind**

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
npm create vite@latest web -- --template react-ts
cd web && npm install
npm install tailwindcss @tailwindcss/vite
npm install -D openapi-typescript concurrently
```

Replace `web/vite.config.ts`:

```ts
import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
});
```

Replace `web/src/index.css` with exactly:

```css
@import "tailwindcss";
```

In `web/index.html` set `<html lang="en" class="dark">` and
`<title>fantaclaude asta</title>`. In `web/tsconfig.json` and
`web/tsconfig.app.json` add under `compilerOptions`:
`"baseUrl": ".", "paths": { "@/*": ["./src/*"] }`.
Delete the template's `src/App.css` and demo assets; `src/App.tsx` becomes a
placeholder (`export default function App() { return <div className="p-8">fantaclaude asta</div> }`)
until Task 10.

- [ ] **Step 2: shadcn/ui init**

```bash
cd web
npx shadcn@latest init --yes --base-color neutral
npx shadcn@latest add button card input badge
```

Outcome to pin (however the CLI spells it this month): `components.json`
exists, `src/lib/utils.ts` (the `cn` helper) exists, `src/components/ui/`
holds `button.tsx`, `card.tsx`, `input.tsx`, `badge.tsx`, and the app still
builds. The dashboard uses these four primitives plus flat Tailwind tables —
the data-dense surfaces (tier board, ledgers) stay hand-rolled `<table>`s on
purpose; shadcn's richer composites (Select, Dialog) are deliberately not
pulled for the deadline build, native controls stand in.

- [ ] **Step 3: package scripts and poe tasks**

`web/package.json` scripts (merge over the template's):

```json
{
  "scripts": {
    "dev": "concurrently -k \"uv run fantaclaude asta serve --replay ../core/tests/fixtures/asta_session_sample.jsonl --speed 5 --me 0\" \"vite\"",
    "build": "tsc -b && vite build",
    "types": "openapi-typescript openapi.json -o src/api/schema.d.ts",
    "preview": "vite preview"
  }
}
```

Root `pyproject.toml`, `[tool.poe.tasks]` (spec: "poe is not the domain
interface" — these are exactly its multi-process chores):

```toml
web-dev = "npm --prefix web run dev"
web-build = "npm --prefix web run build"
types = ["types-openapi", "types-ts"]
types-openapi = "uv run python -m fantaclaude.api.openapi_dump --out web/openapi.json"
types-ts = "npm --prefix web run types"
```

Append to `.gitignore`:

```
web/node_modules/
web/dist/
web/openapi.json
```

- [ ] **Step 4: The OpenAPI dump module and its test**

```python
# core/src/fantaclaude/api/openapi_dump.py
"""Write the API's OpenAPI document (no server needed): `poe types` feeds it
to openapi-typescript so the dashboard's types are generated from the same
pydantic models FastAPI serves — the spec's "types are generated, not
hand-written"."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fantaclaude.api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(create_app(None).openapi()), encoding="utf-8")


if __name__ == "__main__":
    main()
```

Appended to `core/tests/test_api_app.py`:

```python
def test_openapi_dump_writes_the_document(tmp_path, monkeypatch):
    import json
    import sys

    from fantaclaude.api import openapi_dump
    out = tmp_path / "openapi.json"
    monkeypatch.setattr(sys, "argv", ["openapi_dump", "--out", str(out)])
    openapi_dump.main()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/board" in doc["paths"] and "BoardPayload" in doc["components"]["schemas"]
```

- [ ] **Step 5: Generate the types and the WS envelope**

```bash
uv run poe types
```

`web/src/api/types.ts`:

```ts
import type { components } from "./schema";

export type BoardPayload = components["schemas"]["BoardPayload"];
export type HelloPayload = components["schemas"]["HelloPayload"];
export type PriceRow = components["schemas"]["PriceRowOut"];
export type Ledger = components["schemas"]["LedgerOut"];
export type Pressure = components["schemas"]["PressureOut"];
export type Lot = components["schemas"]["LotOut"];

/** The WebSocket envelope. Hand-written: the socket carries the same
 * generated payloads, only this thin union is ours. */
export type WsMessage =
  | { type: "hello"; hello: HelloPayload }
  | { type: "board"; board: BoardPayload; events: string[] }
  | { type: "feed"; status: string };
```

(If openapi-typescript emitted the schema names differently — e.g. suffixed —
follow the generated `schema.d.ts`; the aliases above are the contract the
components import.)

- [ ] **Step 6: Verify the gates**

```bash
uv run pytest core/tests/test_api_app.py -c core/pyproject.toml -q     # PASS
uv run poe web-build                                                    # tsc + vite build succeed; web/dist/ exists
uv run poe test && uv run poe lint
```

- [ ] **Step 7: Commit**

```bash
git add web pyproject.toml .gitignore core/src/fantaclaude/api/openapi_dump.py core/tests/test_api_app.py
git commit -m "feat(web): Vite + Tailwind + shadcn scaffold, generated API types, poe web tasks"
```

(`web/package-lock.json` is committed; `web/node_modules`, `web/dist` and
`web/openapi.json` are ignored.)

---

### Task 10: Dashboard shell — live socket, mapping gate, status, problems

**Files:**
- Create: `web/src/ws.ts`, `web/src/lib/format.ts`
- Create: `web/src/components/MappingGate.tsx`, `StatusBar.tsx`,
  `Problems.tsx`
- Modify: `web/src/App.tsx`, `web/src/main.tsx`

**Interfaces:**
- Consumes: `WsMessage`, `HelloPayload`, `BoardPayload` (Task 9 types); the
  REST + WS contract (Task 5); shadcn `Button`, `Card` primitives.
- Produces: `useLive(): Live` (`{hello, board, feed, events, connected}`);
  `band(b)` formatting helper; the phase-switching `App`.

**Verification for this task and Task 11** is `poe web-build` (tsc is the
gate — the payloads are fully typed) plus a scripted visual pass against the
replayed server; there are no JS unit tests, deliberately: every behaviour
worth a test lives server-side and is already tested there, and the freeze is
in two days. The visual pass is written into each step.

- [ ] **Step 1: The live-state hook**

```ts
// web/src/ws.ts
import { useEffect, useRef, useState } from "react";
import type { BoardPayload, HelloPayload, WsMessage } from "@/api/types";

export interface Live {
  hello: HelloPayload | null;
  board: BoardPayload | null;
  feed: string;
  events: string[];
  connected: boolean;
}

/** One WebSocket, reconnecting with backoff; a REST /api/hello fetch paints
 * the first frame even if the socket is slow. The server holds the state
 * (live-event requirement 1): reconnects simply re-pull `hello`. */
export function useLive(): Live {
  const [state, setState] = useState<Live>({ hello: null, board: null, feed: "offline", events: [], connected: false });
  const retry = useRef(1000);
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { retry.current = 1000; setState(s => ({ ...s, connected: true })); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data) as WsMessage;
        setState(s => {
          if (msg.type === "hello") return { ...s, hello: msg.hello, board: msg.hello.board ?? s.board, feed: msg.hello.feed };
          if (msg.type === "board") return { ...s, board: msg.board, events: [...msg.events, ...s.events].slice(0, 200) };
          return { ...s, feed: msg.status };
        });
      };
      ws.onclose = () => {
        setState(s => ({ ...s, connected: false }));
        if (!closed) { setTimeout(connect, retry.current); retry.current = Math.min(retry.current * 2, 10000); }
      };
    };
    connect();
    fetch("/api/hello").then(r => (r.ok ? r.json() : null)).then(h => {
      if (h) setState(s => (s.hello ? s : { ...s, hello: h, board: h.board ?? s.board, feed: h.feed }));
    }).catch(() => { /* the socket will bring it */ });
    return () => { closed = true; ws?.close(); };
  }, []);
  return state;
}
```

```ts
// web/src/lib/format.ts
export const band = (b: { p25: number; p50: number; p75: number } | null | undefined): string =>
  b ? `${b.p50} [${b.p25}–${b.p75}]` : "—";
```

- [ ] **Step 2: The mapping gate**

```tsx
// web/src/components/MappingGate.tsx
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { HelloPayload } from "@/api/types";

const KEY = (code: string | null) => `fantaclaude-mapping-${code ?? "session"}`;

/** The two identity joins the feed cannot supply (spec): which team is mine,
 * and which dossier each rival maps to. Asked at every connect; this
 * browser's localStorage pre-fills the last answer — the server persists
 * nothing of it, so a lost cache costs one screen of re-selection. */
export function MappingGate({ hello }: { hello: HelloPayload }) {
  const [mine, setMine] = useState<number | null>(hello.mapping?.mine ?? null);
  const [nicks, setNicks] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY(hello.session_code)) ?? "null");
      if (saved) { setMine(saved.mine); setNicks(saved.nicks ?? {}); }
    } catch { /* pre-fill only */ }
  }, [hello.session_code]);

  const submit = async () => {
    if (mine === null) { setError("pick your team"); return; }
    const clean = Object.fromEntries(Object.entries(nicks).filter(([id, v]) => v && Number(id) !== mine));
    const resp = await fetch("/api/mapping", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ mine, nicks: clean }),
    });
    if (!resp.ok) { setError((await resp.json()).detail ?? `mapping refused (${resp.status})`); return; }
    try { localStorage.setItem(KEY(hello.session_code), JSON.stringify({ mine, nicks: clean })); } catch { /* fine */ }
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 p-8">
      <Card className="max-w-2xl mx-auto p-6 space-y-4 bg-neutral-900 border-neutral-700">
        <h1 className="text-xl font-semibold">Who is who?</h1>
        <p className="text-sm text-neutral-400">{hello.run}</p>
        {hello.league_conflicts.map(c => (
          <p key={c} className="text-amber-400 text-sm border border-amber-700 rounded p-2">SESSION &ne; LEAGUE: {c}</p>
        ))}
        {hello.note && <p className="text-amber-400 text-sm">{hello.note}</p>}
        {hello.teams.length === 0 && (
          <p className="text-neutral-400">waiting for the first snapshot&hellip; (feed: {hello.feed})</p>
        )}
        <table className="w-full text-sm">
          <tbody>
            {hello.teams.map(t => (
              <tr key={t.team_id} className="border-b border-neutral-800">
                <td className="py-2 pr-2">
                  <input type="radio" name="mine" checked={mine === t.team_id} onChange={() => setMine(t.team_id)} />
                </td>
                <td className="py-2 pr-4">{t.label} <span className="text-neutral-500">(team {t.team_id})</span></td>
                <td className="py-2">
                  <select
                    className="bg-neutral-950 border border-neutral-700 rounded px-2 py-1 w-full disabled:opacity-40"
                    value={nicks[t.team_id] ?? ""} disabled={mine === t.team_id}
                    onChange={e => setNicks({ ...nicks, [t.team_id]: e.target.value })}>
                    <option value="">&mdash; no dossier &mdash;</option>
                    {hello.participants.map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <Button onClick={submit} disabled={hello.teams.length === 0}>Open the board</Button>
        <p className="text-xs text-neutral-500">
          The radio is my team; each rival can point at a dossier under kb/league/participants.
          Skipping the dossiers only costs the pressure model its priors.
        </p>
      </Card>
    </div>
  );
}
```

- [ ] **Step 3: Status bar and problems banner**

```tsx
// web/src/components/StatusBar.tsx
import type { BoardPayload, HelloPayload } from "@/api/types";

const DOT: Record<string, string> = {
  live: "bg-emerald-500", reconnecting: "bg-amber-500", offline: "bg-red-500",
  replay: "bg-sky-500", state: "bg-sky-500",
};

/** Feed status is always visible (spec): a silently dead feed and a quiet
 * auction look identical from across the table. */
export function StatusBar({ hello, board, feed, connected }: {
  hello: HelloPayload; board: BoardPayload; feed: string; connected: boolean;
}) {
  const s = board.settings;
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 border-b border-neutral-800 text-sm sticky top-0 bg-neutral-950 z-10">
      <span className={`inline-block w-2.5 h-2.5 rounded-full ${DOT[feed] ?? "bg-neutral-500"}`} title={`feed: ${feed}`} />
      <span className="font-semibold">{hello.session_code ?? hello.mode}</span>
      <span className="text-neutral-400">{feed}{connected ? "" : " · socket reconnecting"}</span>
      <span className="text-neutral-400">{board.run_id} · {board.scenario}</span>
      <span className="text-neutral-400">
        {s.budget}cr · gk {s.goalkeepers[0]}-{s.goalkeepers[1]} · roster {s.size[0]}-{s.size[1]} · {s.team_count} teams ({s.source})
      </span>
      <span className="ml-auto text-neutral-400 tabular-nums">
        market {board.market_credits}cr · inflation {board.inflation.toFixed(2)}
      </span>
    </header>
  );
}
```

```tsx
// web/src/components/Problems.tsx
import type { BoardPayload } from "@/api/types";

/** Conflicts and problems are surfaced, never absorbed (spec: "loudly at
 * connect, before bidding opens" — and kept on screen after it). */
export function Problems({ board }: { board: BoardPayload }) {
  const rows = [
    ...board.league_conflicts.map(text => ({ kind: "SESSION ≠ LEAGUE", text })),
    ...board.problems.map(text => ({ kind: "problem", text })),
  ];
  if (rows.length === 0) return null;
  return (
    <div className="px-3 py-1 space-y-1">
      {rows.map((r, i) => (
        <p key={i} className="text-amber-400 text-xs border border-amber-800 rounded px-2 py-1">
          <span className="font-semibold">{r.kind}:</span> {r.text}
        </p>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: The app shell**

```tsx
// web/src/App.tsx
import { useLive } from "./ws";
import { MappingGate } from "./components/MappingGate";
import { StatusBar } from "./components/StatusBar";
import { Problems } from "./components/Problems";

export default function App() {
  const live = useLive();
  if (!live.hello) return <div className="min-h-screen bg-neutral-950 text-neutral-400 p-8">connecting to asta serve&hellip;</div>;
  if (live.hello.phase === "pending" || !live.board) return <MappingGate hello={live.hello} />;
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <StatusBar hello={live.hello} board={live.board} feed={live.feed} connected={live.connected} />
      <Problems board={live.board} />
      <main className="p-3 text-neutral-400">board components land in Task 11</main>
    </div>
  );
}
```

(`main.tsx` stays the Vite template: StrictMode + createRoot + `./index.css`.)

- [ ] **Step 5: Verify — build, then the visual pass**

```bash
uv run poe web-build
uv run fantaclaude asta serve --replay core/tests/fixtures/asta_session_sample.jsonl --speed 10
```

Open http://127.0.0.1:8765 and check: the mapping gate lists the sample's
teams with the run named; picking a team and "Open the board" lands on the
shell with the status bar counting picks up as the replay runs; reloading
the page pre-fills the gate from localStorage. Ctrl-C the server.

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "feat(web): dashboard shell — live socket, mapping gate, status bar, problems banner"
```

---

### Task 11: Dashboard board — lot panel, tier board, my panel, ledgers, adjust form, log

**Files:**
- Create: `web/src/components/LotPanel.tsx`, `TierBoard.tsx`, `MyPanel.tsx`,
  `Ledgers.tsx`, `AdjustForm.tsx`, `EventLog.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `BoardPayload`, `PriceRow` (types); `band` (lib/format); the
  `POST /api/adjust` / `POST /api/refresh` contract; shadcn `Card`, `Button`,
  `Input`, `Badge`.
- Produces: the night's screen. Division of surfaces (spec): everything here
  renders numbers a tool computed — nothing on this screen computes one.

- [ ] **Step 1: Lot panel and tier board**

```tsx
// web/src/components/LotPanel.tsx
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { band } from "@/lib/format";
import type { BoardPayload } from "@/api/types";

/** The lot on the block, auto-focused from the feed's selectedPlayerId: the
 * band is the decision, the room's estimate is only the moment to stop. */
export function LotPanel({ board }: { board: BoardPayload }) {
  const lot = board.lot;
  if (!lot) return <Card className="p-4 bg-neutral-900 border-neutral-800 text-neutral-500">no lot on the block</Card>;
  const pressure = board.lot_pressure;
  return (
    <Card className="p-4 bg-neutral-900 border-neutral-600">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h2 className="text-2xl font-bold">{lot.name}</h2>
        <span className="text-neutral-400">{lot.team_short} · {lot.roles.join("/")} → {lot.role_class} · t{lot.tier}</span>
        {lot.sold_to !== null && <Badge variant="destructive">sold to team {lot.sold_to}</Badge>}
      </div>
      <div className="mt-2 flex items-end gap-8">
        <div>
          <div className="text-xs text-neutral-500">max price (p50 [p25–p75])</div>
          <div className="text-5xl font-bold tabular-nums">{band(lot.band)}</div>
        </div>
        <div>
          <div className="text-xs text-neutral-500">expected</div>
          <div className="text-2xl tabular-nums">{lot.expected_price ?? "—"}</div>
        </div>
        {pressure && (
          <div>
            <div className="text-xs text-neutral-500">room likely to</div>
            <div className="text-2xl tabular-nums">{pressure.estimate}</div>
          </div>
        )}
      </div>
      {pressure && pressure.bidders.length > 0 && (
        <ul className="mt-3 text-sm space-y-1">
          {pressure.bidders.map(b => (
            <li key={b.team_id} className="text-neutral-300">
              <span className={b.intent === "keen" ? "text-red-400" : b.intent === "reluctant" ? "text-emerald-400" : "text-neutral-400"}>
                {b.intent}
              </span>{" "}
              {b.label}{b.nick ? ` (${b.nick})` : ""} up to <span className="tabular-nums font-semibold">{b.ceiling}</span>
              <span className="text-neutral-500"> · {b.credits}cr, depth {b.depth}{b.reasons.length > 0 ? ` · ${b.reasons.join(", ")}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
```

```tsx
// web/src/components/TierBoard.tsx
import { Card } from "@/components/ui/card";
import { band } from "@/lib/format";
import type { BoardPayload, PriceRow } from "@/api/types";

const CLASS_ORDER = ["Por", "Ds", "Dd", "Dc", "B", "E", "M", "C", "W", "T", "A", "Pc"];
const TOP = 8;

/** Per class, the unsold top by max price — the on-screen twin of the
 * printed tier board. The row of the selected lot is highlighted. */
export function TierBoard({ board }: { board: BoardPayload }) {
  const byClass = new Map<string, PriceRow[]>();
  for (const row of Object.values(board.prices)) {
    const rows = byClass.get(row.role_class) ?? [];
    rows.push(row);
    byClass.set(row.role_class, rows);
  }
  const classes = [
    ...CLASS_ORDER.filter(c => byClass.has(c)),
    ...[...byClass.keys()].filter(c => !CLASS_ORDER.includes(c)).sort(),
  ];
  return (
    <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
      {classes.map(cls => {
        const all = byClass.get(cls) ?? [];
        const rows = [...all].sort((a, b) => b.band.p50 - a.band.p50 || b.value_p50 - a.value_p50).slice(0, TOP);
        return (
          <Card key={cls} className="p-2 bg-neutral-900 border-neutral-800">
            <h3 className="font-semibold text-neutral-300 mb-1">
              {cls} <span className="text-neutral-600 text-xs">· {all.length} unsold</span>
            </h3>
            <table className="w-full text-sm">
              <tbody>
                {rows.map(r => (
                  <tr key={r.player_id} className={r.player_id === board.selected ? "bg-neutral-700/50" : ""}>
                    <td className="py-0.5 pr-1 text-neutral-600 tabular-nums">t{r.tier}</td>
                    <td className="py-0.5 pr-2 truncate max-w-40">{r.name} <span className="text-neutral-600">{r.team_short}</span></td>
                    <td className="py-0.5 text-right tabular-nums whitespace-nowrap">{band(r.band)}</td>
                    <td className="py-0.5 pl-2 text-right tabular-nums text-neutral-500" title="room likely to">
                      {r.pressure ? r.pressure.estimate : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: My panel, ledgers, event log**

```tsx
// web/src/components/MyPanel.tsx
import { Card } from "@/components/ui/card";
import type { BoardPayload } from "@/api/types";

export function MyPanel({ board }: { board: BoardPayload }) {
  const me = board.me;
  const completion = Object.entries(board.composition).filter(([, n]) => n > 0)
    .map(([c, n]) => `${c} ${n}·${board.credits_by_class[c] ?? 0}`).join(", ");
  return (
    <Card className="p-3 bg-neutral-900 border-neutral-600 text-sm space-y-1">
      <div className="flex justify-between items-baseline">
        <span className="font-semibold">{me.label}</span>
        <span className="text-3xl font-bold tabular-nums">{me.credits}<span className="text-sm text-neutral-500">cr</span></span>
      </div>
      <p className="text-neutral-400">
        {me.picks.length} picks · gk {me.goalkeepers} · mov {me.outfield}
        {me.missing_goalkeepers + me.missing_outfield > 0 &&
          ` · still needed: gk ${me.missing_goalkeepers}, mov ${me.missing_outfield}`}
      </p>
      <p className="text-neutral-400">reserve {board.reserve} · budget {board.budget} · completion {completion}</p>
      {board.targets_departed.length > 0 && (
        <p className="text-amber-400">departed from the target at {board.targets_departed.join(", ")}</p>
      )}
      {board.adjustments.count > 0 && (
        <p className="text-neutral-500">{board.adjustments.applied}/{board.adjustments.count} adjustments applied</p>
      )}
    </Card>
  );
}
```

```tsx
// web/src/components/Ledgers.tsx
import { Card } from "@/components/ui/card";
import type { BoardPayload } from "@/api/types";

/** Every team's credits from picks[], never from the feed's budget field —
 * the ⚠ marks picks the pinned run cannot name (credits counted, roles not). */
export function Ledgers({ board }: { board: BoardPayload }) {
  return (
    <Card className="p-2 bg-neutral-900 border-neutral-800 text-sm">
      <h3 className="font-semibold text-neutral-300 mb-1">The room</h3>
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-xs">
            <th className="text-left font-normal">team</th>
            <th className="text-right font-normal">cr</th>
            <th className="text-right font-normal">picks</th>
            <th className="text-right font-normal">gk/mov</th>
          </tr>
        </thead>
        <tbody>
          {board.teams.map(t => (
            <tr key={t.team_id} className={t.team_id === board.me.team_id ? "text-emerald-400" : ""}>
              <td className="py-0.5">{t.label}{t.nick ? ` (${t.nick})` : ""}{t.unknown > 0 ? " ⚠" : ""}</td>
              <td className={`py-0.5 text-right tabular-nums ${t.credits < 0 ? "text-red-400" : ""}`}>{t.credits}</td>
              <td className="py-0.5 text-right tabular-nums">{t.picks.length}</td>
              <td className="py-0.5 text-right tabular-nums">{t.goalkeepers}/{t.outfield}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
```

```tsx
// web/src/components/EventLog.tsx
import { Card } from "@/components/ui/card";

export function EventLog({ events }: { events: string[] }) {
  return (
    <Card className="p-2 bg-neutral-900 border-neutral-800 text-xs">
      <h3 className="font-semibold text-neutral-300 mb-1 text-sm">Log</h3>
      <ul className="space-y-0.5 max-h-64 overflow-y-auto">
        {events.length === 0 && <li className="text-neutral-600">nothing yet</li>}
        {events.map((e, i) => <li key={events.length - i} className="text-neutral-400">{e}</li>)}
      </ul>
    </Card>
  );
}
```

- [ ] **Step 3: The adjust form**

```tsx
// web/src/components/AdjustForm.tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { BoardPayload } from "@/api/types";

/** The dashboard's third of the one adjustments file: value / exclude /
 * target, always with a reason, POSTed to the one writer (the server).
 * The refresh button is the hand-edited-file case (live-event req. 6). */
export function AdjustForm({ board }: { board: BoardPayload }) {
  const [type, setType] = useState<"exclude" | "value" | "target">("exclude");
  const [player, setPlayer] = useState("");
  const [factor, setFactor] = useState("0.85");
  const [cls, setCls] = useState("Dc");
  const [count, setCount] = useState("4");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const classes = [...new Set(Object.values(board.prices).map(r => r.role_class))].sort();

  const submit = async () => {
    setNote(null);
    const body: Record<string, unknown> = { type, reason };
    if (type === "target") { body["class"] = cls; body.count = Number(count); }
    else body.player = player;
    if (type === "value") body.factor = Number(factor);
    const resp = await fetch("/api/adjust", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    const out = await resp.json();
    setNote(resp.ok ? `applied: ${out.described}` : (out.detail ?? `refused (${resp.status})`));
    if (resp.ok) { setPlayer(""); setReason(""); }
  };
  const refresh = async () => {
    const resp = await fetch("/api/refresh", { method: "POST" });
    setNote(resp.ok ? "refreshed from adjustments.yml and the dossiers"
                    : ((await resp.json()).detail ?? `refused (${resp.status})`));
  };

  return (
    <Card className="p-3 bg-neutral-900 border-neutral-800 text-sm space-y-2">
      <h3 className="font-semibold text-neutral-300">Adjust</h3>
      <div className="flex gap-2">
        {(["exclude", "value", "target"] as const).map(t => (
          <Button key={t} size="sm" variant={type === t ? "default" : "outline"} onClick={() => setType(t)}>
            {t}
          </Button>
        ))}
      </div>
      {type !== "target" ? (
        <>
          <Input list="adjust-players" value={player} onChange={e => setPlayer(e.target.value)}
                 placeholder='player, the listone way ("Martinez L.")' />
          <datalist id="adjust-players">
            {Object.values(board.prices).map(r => <option key={r.player_id} value={r.name} />)}
          </datalist>
        </>
      ) : (
        <div className="flex gap-2">
          <select value={cls} onChange={e => setCls(e.target.value)}
                  className="bg-neutral-950 border border-neutral-700 rounded px-2 py-1">
            {classes.map(c => <option key={c}>{c}</option>)}
          </select>
          <Input className="w-20" type="number" min="0" value={count} onChange={e => setCount(e.target.value)} />
        </div>
      )}
      {type === "value" && (
        <Input className="w-24" type="number" step="0.05" min="0.05" max="2"
               value={factor} onChange={e => setFactor(e.target.value)} />
      )}
      <Input value={reason} onChange={e => setReason(e.target.value)}
             placeholder="reason — the auction record explains itself" />
      <div className="flex gap-2">
        <Button size="sm" onClick={submit} disabled={!reason || (type !== "target" && !player)}>apply</Button>
        <Button size="sm" variant="outline" onClick={refresh}
                title="reread adjustments.yml and the dossiers, re-price everything">refresh</Button>
      </div>
      {note && <p className="text-neutral-400">{note}</p>}
    </Card>
  );
}
```

- [ ] **Step 4: Wire the grid into `App.tsx`**

Replace the Task 10 placeholder `<main>` with:

```tsx
      <main className="grid grid-cols-12 gap-3 p-3">
        <section className="col-span-12 lg:col-span-8 space-y-3">
          <LotPanel board={live.board} />
          <TierBoard board={live.board} />
        </section>
        <aside className="col-span-12 lg:col-span-4 space-y-3">
          <MyPanel board={live.board} />
          <AdjustForm board={live.board} />
          <Ledgers board={live.board} />
          <EventLog events={live.events} />
        </aside>
      </main>
```

with the matching imports.

- [ ] **Step 5: Verify — build + the full visual pass**

```bash
uv run poe web-build
uv run fantaclaude asta serve --replay core/tests/fixtures/asta_session_sample.jsonl --speed 2
```

Against http://127.0.0.1:8765, watch one full replay: sales tick through the
log and the ledgers; the lot panel follows `selectedPlayerId` with its band
and pressure; an `exclude` submitted from the form removes the player from
his class column and moves the rest of the class (the spec's directional
invariant, seen on screen); `refresh` after hand-editing
`data/adjustments.yml` re-prices without a restart; killing and restarting
the server puts the (pre-filled) gate back and the board returns. Ctrl-C.

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "feat(web): the board — lot focus, tiers, ledgers, my panel, adjust form, event log"
```

---

### Task 12: Documentation, skill, runbook — the phase is not shipped until the paper agrees

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `records/README.md`
- Modify: `.claude/skills/fanta-asta/SKILL.md`
- Modify: `site/docs/architecture.md`, `site/docs/cli.md`, `site/docs/mcp.md`
- Create: `docs/asta-night-runbook.md`

**Interfaces:** none — prose. Every claim below matches what Tasks 1–11
built; where an edit conflicts with drifted reality, reality wins and the
text follows it.

- [ ] **Step 1: CLAUDE.md — the network carve-out and the verify-transfer note**

In "Workspace and tests", replace the sentence
"…deleted only once the transfer into the lega is verified (Phase 2b). Every
`fantaclaude asta` command is local — read-only on the database, no network —
so it may be run freely, during the auction included."
with:

> deleted only once the transfer into the lega is verified
> (`verify-transfer`, a post-auction task blocked on open question 9 — until
> it lands, nothing deletes them). Every `fantaclaude asta` command except
> `serve` is local — read-only on the database, no network — so it may be
> run freely, during the auction included. `asta serve` is the one networked
> command: it subscribes to the FantaAstaLive Firebase session (anonymous
> sign-in, read-only, exactly one subscriber, reconnect with backoff) and
> serves the dashboard, the WebSocket and the `fantaclaude-asta` MCP on
> localhost. Never point it at a live session "to check" — rehearse with
> `--replay`. While it runs it is the one writer of `data/adjustments.yml`;
> `asta adjust` and `asta refresh` proxy to it on localhost, and `adjust`
> falls back to the offline path when nothing is listening.

- [ ] **Step 2: README.md — Capabilities and Layout**

Under **Capabilities**, after the asta-core bullet, add:

> - **Auction night** — `fantaclaude asta serve` mirrors the FantaAstaLive
>   session over its Firebase feed and serves the live dashboard, the
>   WebSocket and the `fantaclaude-asta` MCP from one localhost process;
>   the board re-prices on every sale, adjustments land from the dashboard,
>   the CLI or Claude through one path, and `--replay` rehearses the whole
>   night from a captured session.

Under **Layout**, add lines for `web/` ("the Vite/React dashboard `asta
serve` builds and mounts") and `core/src/fantaclaude/api/` ("FastAPI: REST +
WebSocket + the MCP mount") wherever the existing tree lists siblings.

In `records/README.md`, change "(Phase 2b)" in the asta bullet to "(a
post-auction task, open question 9)".

- [ ] **Step 3: fanta-asta SKILL.md — the live half**

In the front-matter `description`, replace "The live feed, the dashboard and
the MCP tools are Phase 2b and are not here yet." with "During the auction,
`asta serve` mirrors the live session and serves the dashboard and the
`fantaclaude-asta` MCP; `adjust` and `refresh` write through it."

In the body: amend the "every command is local" sentence the same way as
CLAUDE.md (all except `serve`); add to **Modes**:

> ### `serve`
>
> `fantaclaude asta serve --session FA-xxx-xxx` — the night's process: the
> live mirror, the dashboard on http://127.0.0.1:8765, and the
> `fantaclaude-asta` MCP at `/mcp`. `--replay <capture> --speed N` rehearses
> it; `--state` reviews a finished auction. While it runs, prefer the MCP
> tools (`asta_board`, `asta_explain`, `asta_adjust`, `asta_refresh`,
> `asta_query`) over the CLI: they read the same in-memory board the
> dashboard shows. `asta adjust` from the CLI proxies to the server by
> itself; a hand edit of `data/adjustments.yml` needs `asta refresh` (or the
> dashboard's refresh button) to land.

and, in the worked-example section, one MCP-shaped exchange: user says "he's
limping" → `asta_adjust {type: value, player: "Bastoni", factor: 0.85,
reason: "limping, reported in the room"}` → read the returned band and say
what moved.

- [ ] **Step 4: The site docs**

`site/docs/cli.md`, under `## fantaclaude asta`, document `serve` (sources,
the mapping screen, the port layout, capture) and `refresh` (server-only),
and note `adjust`'s proxy behaviour — three short paragraphs in the page's
existing voice.

`site/docs/mcp.md`: add a `## The fantaclaude-asta server` section: served
by `asta serve` at `/mcp` over HTTP, exists only while an auction is served
(and that this is correct), the six tools with one line each, DuckDB opened
read-only in a threadpool for `asta_query`.

`site/docs/architecture.md`: add a short `## The live auction` section with
the flow (the spec's own diagram, updated to what shipped):

```
FantaAstaLive → Firebase → SSE → ingest.asta_live ─┐
        adjustments.yml + dossiers (refresh) ──────┼→ AstaServer.mutate → state file
              dashboard form / CLI / MCP tool ─────┘   → recompute board → WebSocket
```

- [ ] **Step 5: The runbook**

`docs/asta-night-runbook.md`:

```markdown
# Asta night — runbook

The whole operating procedure is: pin the run, `fantaclaude asta serve`,
open localhost, answer the mapping screen. Everything else here is the
before, the drills, and the after.

## The day before (freeze, 3 Sep)

- `fantaclaude doctor` — all green, including `dashboard` (else
  `poe web-build`) and the pinned-run checks.
- `fantaclaude rank` after the league's rules are final; commit `records/`.
  The board names its run at startup — check it is the one you mean.
- Print the tier board (`fantaclaude asta board`) — the paper backstop.
- Rehearse: `fantaclaude asta serve --replay <capture> --speed 5` and run
  the drills below. A capture with picks comes from the rehearsal itself
  (`data/raw/asta_live/…`) or from `core/tests/fixtures/asta_session_sample.jsonl`.

## Drills (each proven once before the night)

1. Exhaust a budget in replay and watch the reserve pin prices down.
2. Admin undoes a lot → the sale reverses on the board (set-diff).
3. Exclude a player mid-run → the rest of his class re-prices.
4. Hand-edit `data/adjustments.yml` → `asta refresh` (or the dashboard
   button) lands it without a restart.
5. Kill the browser, reload → the gate pre-fills, the board returns.
6. Kill the server, restart with the same source → resubscribe rebuilds the
   same board (crash recovery).
7. Drop the network mid-replay (live: the feed dot goes amber, then green).
8. Ask `fantaclaude-asta` a question while the board is live
   (`asta_board`, `asta_explain`, one `asta_query`).
9. Stop the feed and reload from the state file:
   `fantaclaude asta serve --state data/asta-state.json`.

## The night

- Get the session code from the admin (and which mode they run — DRAFT or A
  RILANCI; open question 10 says read the bid fields at the rehearsal if the
  answer is A RILANCI).
- `fantaclaude asta serve --session FA-xxx-xxx` — the run is named on the
  status line; the mapping screen asks who is who (dossiers optional, they
  feed the pressure model); SESSION ≠ LEAGUE conflicts show before bidding.
- The feed dot is always on screen: green live, amber reconnecting, red
  offline. Red with the room still bidding = the printed tier board.
- Facts from the room go in as adjustments with reasons — dashboard form,
  `asta_adjust` through Claude, or `fantaclaude asta adjust`. The mirror is
  faithful: a mistyped price is the admin's to fix.

## After

- `fantaclaude asta close` — copies the state file to `records/asta/`;
  commit `records/`.
- The state files are **kept** until `verify-transfer` (post-auction task,
  open question 9) confirms the lega matches the room. Review any time with
  `fantaclaude asta serve --state records/asta/<file>.json`.
```

- [ ] **Step 6: Verify every gate, then commit**

```bash
uv run poe test && uv run poe lint && uv run poe docs-build && uv run poe web-build
git add CLAUDE.md README.md records/README.md .claude/skills/fanta-asta/SKILL.md site/docs docs/asta-night-runbook.md
git commit -m "docs: asta serve, the dashboard, the auction MCP, and the night's runbook"
```

---

## Final verification (the phase's own definition of done)

After Task 12, on the branch:

1. `uv run poe test` — both suites green, no network touched.
2. `uv run poe lint`, `uv run poe docs-build`, `uv run poe web-build` — green.
3. The rehearsal path end to end, by hand:
   `uv run fantaclaude asta serve --replay core/tests/fixtures/asta_session_sample.jsonl --speed 2`
   → mapping gate → board follows the replay → adjust from the form → adjust
   from the CLI (proxied) → `asta_board` over MCP
   (`fantaclaude-asta` in `.mcp.json` resolves once the server is up) →
   Ctrl-C → `--state data/asta-state.json` reproduces the final board.
4. `fantaclaude doctor` — the new `dashboard` check green after `poe web-build`.
5. The diff touches no live service: the only runtime network code is
   `ingest/asta_live.py` + the two CLI proxies to localhost.

What this phase hands the freeze (3 Sep): the full mock auction of the
spec's "Rehearsal is mandatory" list is executable — replay end to end,
undo, mid-run exclusion, browser kill, server kill with the pre-filled
mapping screen, network drop, an MCP question against the live board, and a
state-file reload with the feed off.
