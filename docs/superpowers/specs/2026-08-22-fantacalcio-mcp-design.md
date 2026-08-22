# fantacalcio-mcp — Design

**Date:** 2026-08-22
**Status:** Draft for review
**Location:** `mcp/fantacalcio/`

## Purpose

An MCP server that lets Claude read and (eventually) act on a Leghe Fantacalcio.it
league through the site's private API, without a browser in the loop.

The consumer is Claude Code running locally. Success means asking "what are my
league's rules?" or "who's in my league?" in natural language and getting a
correct answer, and later "set my formation" and having it stick.

## Background: what the API actually is

`https://apileague.fantacalcio.it` is the private backend behind the Leghe
Fantacalcio.it SPA. There is no published contract. Every endpoint below was
observed from a real authenticated session on 2026-08-22 and verified with a
live call returning HTTP 200.

Two headers authenticate every request:

```
app_key:       <32-char static site key>
Authorization: Bearer <JWT>
```

The `app_key` is a site-wide constant, not per-session — it is byte-identical
before and after login.

### Token model

Login returns two kinds of JWT (RS256, `iss: https://leghe.fantacalcio.it`,
`aud: fantacalcio`, **1-year `exp`**):

| token | `role` | claims | used for |
| --- | --- | --- | --- |
| account | `user` | `user_id` | `/onboarding/v2/profile/{id}` |
| league | `user_league` | `user_id`, `l_id`, `t_id` | every `/onboarding/v1/league/*` call |

**League context lives inside the token.** This is the single most important
fact about this API: no `/league/*` endpoint accepts a league identifier.
Operating on a different league means presenting a different JWT.

### Login contract

Verified by probing with deliberately malformed bodies (no real password used):

```
POST /onboarding/v1/login
app_key: <key>
Content-Type: application/json

{"username": "...", "password": "..."}
```

| body | response |
| --- | --- |
| `{}` | `400 ATH006 Credentials missing` |
| `{"username": "x"}` | `400 ATH006 Credentials missing` |
| `{"username": "x", "password": "bad"}` | `400 ATH018 Invalid username or password` |

No reCAPTCHA token, no signed header, no device id, no nonce. The reCAPTCHA on
`leghe.fantacalcio.it` belongs to the legacy jQuery site, whose login is a
different, older `PUT utente/login?alias_lega=…` returning base64-encoded
bodies. The string `onboarding` appears nowhere in those legacy bundles.

The response carries **a league JWT per league** the account belongs to:

```jsonc
{ "success": true, "data": {
    "jwt": "<account token>",
    "utente": { "id": 10426252, "username": "…" },
    "leghe": [ { "id": 2578630, "alias": "fantabalotelli3", "nome": "Fantabalotelli3",
                 "id_squadra": 11560832, "jwt": "<league token>", "token": "<128-char>" } ]
} }
```

This is why password auth is worth the storage cost: one POST yields every
league token, so multi-league support and recovery-from-expiry both come free.
The purpose of the separate 128-char `token` field is unknown; it is not needed
for any endpoint we call and will be preserved as raw, not modelled.

### Verified endpoints

All returned HTTP 200 against league 2578630 on 2026-08-22.

| method | path | notes |
| --- | --- | --- |
| POST | `/onboarding/v1/login` | account + league tokens |
| DELETE | `/onboarding/v1/logout` | observed, not called |
| GET | `/onboarding/v2/profile/{userId}` | account token; `leghe[]` |
| GET | `/onboarding/v1/league/profile` | `{lega:{…}}` name, admins, founding year |
| GET | `/onboarding/v1/league/status` | `{sto, activ, sId, mday, mstr}` |
| GET | `/onboarding/v1/league/competitions` | array (empty in this league) |
| GET | `/onboarding/v1/league/teams/my` | caller's team |
| GET | `/onboarding/v1/league/teams?page=` | paginated, with `divisions` |
| GET | `/onboarding/v1/league/settings/rosters` | budget, roster size |
| GET | `/onboarding/v1/league/settings/lineup` | modules, bench, switch |
| GET | `/onboarding/v1/league/settings/calculate` | bonus/malus, subs, modifiers |
| GET | `/onboarding/v1/invitation/participants?pageNumber=&pageSize=` | managers per team |
| GET | `/onboarding/v1/invitation/invitees?…` | pending invites (empty) |
| GET | `/onboarding/v1/team/countMessage` | notification count |
| GET | `/onboarding/v1/adv` | advertising payload — not exposed |
| GET | `/market/v1/time` | server clock |

**Unmapped and required for phase 2:** roster contents (which players a team
owns), player database, lineup submission, market/auction operations,
calendar and results. None were exercised because this league's auction has not
happened — every roster is empty (`r: {p:0,d:0,c:0,a:0}`) and season 21 matchday
1 opened 2026-08-22T16:30. See "Phase 2 discovery" below.

## Architecture

Layered, so the client is testable without FastMCP and writes are physically
isolated from reads.

```
mcp/fantacalcio/
  pyproject.toml            # uv, requires-python >=3.14
  src/fantacalcio_mcp/
    __init__.py
    config.py               # env + credential resolution
    auth.py                 # login, token cache, expiry, 401 recovery
    api.py                  # httpx transport; one method per endpoint
    models.py               # pydantic models: decoded fields + raw
    server.py               # FastMCP tool definitions (thin)
    writes.py               # phase 2; not imported unless enabled
    __main__.py             # entrypoint, --transport flag
  tests/
    fixtures/               # recorded JSON payloads, PII scrubbed
    test_auth.py test_api.py test_models.py test_server.py
```

`api.py` must never import FastMCP. `server.py` must contain no HTTP logic.
This boundary is what makes the whole client testable against fixtures with
zero network access.

### Paths and the surrounding repo

The MCP lives at `mcp/fantacalcio/` inside the `fantaclaudio` workspace. It is
the only code in the repo; the Node and Playwright artefacts that produced this
spec are **deleted** as part of phase 1 (see "Cleanup" below). Nothing in the
MCP imports them, and browser-based auth is obsolete now that the login
contract is known.

State resolution, so there is no ambiguity about which directory wins:

- `FANTACALCIO_HOME` if set, else the workspace root (the directory containing
  `mcp/`), **not** the process working directory — Claude Code spawns the
  server with an unpredictable cwd
- `.env` and `.auth/tokens.json` both resolve against that root, so the MCP
  reuses the credentials already captured there rather than keeping a second copy

### Data flow

```
Claude ──stdio──► server.py ──► api.py ──► httpx ──► apileague.fantacalcio.it
                     │            │
                  models.py    auth.py (token, 401 → re-login once)
```

## Auth & token lifecycle

`auth.py` has one responsibility: hand `api.py` a valid league JWT.

**Credential resolution order**, first hit wins:

1. macOS keychain — `security find-generic-password -s fantacalcio-mcp -w`
2. `.env` — `FANTACALCIO_USERNAME` / `FANTACALCIO_PASSWORD`
3. `.env` — `FANTACALCIO_LEAGUE_TOKEN` (token-only mode; no auto-recovery)
4. Error naming exactly which of the three to set

Keychain is the documented default. `.env` exists so setup never blocks.
Token-only mode is supported because it lets a user run this without ever
handing the server a password, at the cost of a manual refresh once a year.

**Token cache:** `.auth/tokens.json`, mode `0600`, holding account and league
JWTs keyed by league alias. A file, not memory — stdio servers are spawned and
killed constantly by the client, and in-memory caching would mean a login
round-trip on every Claude Code restart. `exp` is checked before every use, so
an expired token triggers a proactive re-login rather than a failed call.

**Failure handling:** a `401`/`403` triggers exactly one re-login and one
retry, then fails with the server's own error message. No retry loop — repeated
failed logins are how accounts get locked. `ATH018` (bad credentials) never
retries at all; it is a configuration error, not a transient one.

**League selection:** tools take an optional `league` alias, defaulting to the
sole league when the account has one and erroring with the list of aliases when
it has several. `auth.py` is the only module aware that switching leagues means
switching tokens.

## Payload modelling

Pydantic models with verified field names, plus a `raw` dict carrying the
untouched payload. Nothing is discarded and no guess is presented as fact.

The rule: **a field gets a friendly name only if its meaning is confirmed by
observed data.** Everything else stays in `raw` and is documented as unknown.
A misnamed field is worse than an absent one, because Claude cannot tell it is
wrong.

### Confirmed mappings

`teams/my` and `teams`:

| raw | modelled as | evidence |
| --- | --- | --- |
| `id` | `team_id` | equals `t_id` in the JWT |
| `n` | `name` | "Sanzimippi FC" |
| `nu` | `owner_username` | "Edo" |
| `idu` | `owner_user_id` | matches `all[0].id` |
| `all[]` | `coaches[]` | `{id, n}` pairs; multi-manager teams exist |
| `cri` | `credits_initial` | 500, equals `budg` in roster settings |
| `crs` | `credits_spent` | 0 with an empty roster |
| `cr` | `credits_remaining` | 500 = `cri` − `crs` |
| `r` | `roster_counts` | `{p,d,c,a}` = goalkeepers/defenders/midfielders/forwards |
| `d` | `division` | "A"; matches `divisions: [{division:"A", count:8}]` |
| `l`,`m`,`ms` | `logo`, `jersey`, `jersey_small` | image filenames |

`settings/rosters`: `budg` → `budget`, `msltc`/`xsltc` → `roster_min`/`roster_max`
(23/40). `settings/lineup`: `mods` → `modules` (11 formations), `tbench` →
`bench_size` (12). `settings/calculate`: `bnMls` → `bonus_malus` with each
`bm*` key expanded (`bmgs` goal scored `[3,3]`, `bmgc` goal conceded `[-1,-1]`,
`bmyc` yellow `[-0.5,-0.5]`, `bmrc` red `[-1,-1]`, `bmog` own goal `[-1,-1]`,
penalty scored/missed/saved, assists, MOTM); `subst` → `substitutions`
(`ssnum` = 5). `status`: `sId` → `season_id` (21), `mday` → `matchday` (1),
`mstr` → `matchday_start`, `activ` → `active`.

### Explicitly unknown — kept raw, documented as such

`bm`, `st` (`"1;1;1"`), `c`, `pl`, `cal`, `cs` on teams; `mplys`, `hdslt`,
`fsltc`, `tcap`, `cmod`, `count`, `sroles`, `minrl`, `maxrl` on roster
settings; `hlnp`, `rlnp`, `fbench`, `assu`, `lcap`, `lswi`, `elnp`, `brdrs`,
`bseq` on lineup settings; `stbdf`, `smod*`, `skodm`, `step` internals on
calculate. `lswi` and `rlnp` plausibly correspond to the "Switch" and "recupero
formazione precedente" toggles in the UI, but plausible is not confirmed, so
they stay raw until observed changing with a known setting change.

## Tool surface

Seven read tools, not thirteen. Endpoints are consolidated along the lines
users actually ask about, because tool-list bloat degrades selection accuracy
and phase 2 needs headroom.

| tool | endpoints | returns |
| --- | --- | --- |
| `get_account` | `profile` | user, and every league with alias — the multi-league entry point |
| `get_league` | `league/profile` + `league/status` | name, id, founding year, admins, season, matchday, kickoff |
| `get_league_settings` | `settings/rosters` + `settings/lineup` + `settings/calculate` | budget, roster bounds, modules, bench, bonus/malus, substitutions, modifiers |
| `get_my_team` | `teams/my` | name, credits, roster counts, coaches |
| `list_teams` | `league/teams` + `invitation/participants` | every team with its managers, merged; `include_pending` folds in `invitees` |
| `list_competitions` | `league/competitions` | configured competitions |
| `get_server_time` | `market/v1/time` | server clock, for deadline math |

`countMessage` and `adv` are not exposed — a notification badge and an ad
payload are noise in a tool list.

`list_teams` merges two endpoints because they answer one question with
complementary halves: `teams` has credits and division, `participants` has
manager names. The API already partially masks manager emails
(`p.l***@***.it`); the model drops the email field entirely rather than
forwarding even a masked one.

## Transport

**stdio by default.** Claude Code spawns the process via `uv run`; there is no
port, no tunnel, and credentials never cross a network boundary.

`--transport http` is available and changes nothing about `server.py`. Two
guardrails on that path:

- binds `127.0.0.1` unless a host is passed explicitly
- **writes refuse to enable over HTTP**, unconditionally

An internet-reachable endpoint that can bid in an auction is a different threat
model than a local pipe, and enabling that should be a deliberate decision, not
a flag combination someone trips over.

## Error handling

The API returns structured codes; they are mapped to actionable messages rather
than forwarded raw:

| code | meaning | surfaced as |
| --- | --- | --- |
| `ATH000` | app_key not authorized | "app_key rejected — it may have rotated; re-capture it" |
| `ATH006` | credentials missing | configuration error naming the missing var |
| `ATH007` | app_key missing | configuration error |
| `ATH018` | bad username/password | configuration error, never retried |
| `401`/`403` on a league call | token expired | one silent re-login and retry |

Unknown codes pass through verbatim with status and body — inventing a friendly
message for an unrecognised failure hides information.

## Testing

`respx` against recorded fixtures in `tests/fixtures/`, scrubbed of tokens,
emails, and the league password. **No test hits the network**, so the suite
cannot mutate a real league or depend on season state.

- `test_auth.py` — resolution order, cache read/write, expiry detection, single
  retry on 401, no retry on ATH018
- `test_api.py` — URL construction, headers, pagination, error mapping
- `test_models.py` — decoding against fixtures; `raw` preserves every input key
- `test_server.py` — tool registration, schemas, league-selection defaulting

One live smoke check (`make smoke`) hits read-only endpoints with real
credentials, kept out of the default suite.

## Security

- `.env` and `.auth/` stay gitignored; token cache is `0600`
- `captured/api-dump.json` contains the league join password (`lega.parola`) in
  cleartext until phase 1 cleanup deletes it. Fixtures must scrub it, and it
  must never be committed
- After cleanup no browser profile and no recorded live payloads remain on
  disk; the only secrets left are the credentials in `.env`/keychain and the
  token cache
- The league profile model omits `parola` entirely; Claude has no reason to see it
- Manager emails are dropped, not forwarded
- Writes are import-gated: `writes.py` is not imported unless
  `FANTACALCIO_ENABLE_WRITES=1`, so "can this touch my league?" is answerable
  by reading one line

## Phasing

**Phase 1 — read-only.** Everything above. Unblocked; ships against verified
endpoints.

**Phase 1 cleanup — remove the Playwright/Node exploration code.** The browser
was scaffolding for one question — how does auth work — and that question is
answered. Password login makes every part of it dead code, so it goes:

| removed | was |
| --- | --- |
| `tools/capture-session.mjs` | Playwright credential capture |
| `tools/probe-api.mjs` | Node endpoint prober |
| `src/client.mjs` | Node API client, superseded by `api.py` |
| `package.json`, `package-lock.json`, `node_modules/` | Node toolchain |
| `.auth/chromium-profile/` | logged-in browser profile |
| `captured/` | recorded payloads |

**Ordering constraint, and it matters:** `captured/api-dump.json` is the only
recorded copy of real API responses, and the test fixtures are derived from it.
Extract and scrub fixtures into `mcp/fantacalcio/tests/fixtures/` **before**
deleting `captured/`, or the test suite loses its ground truth and the payloads
have to be re-fetched from the live league.

Deleting `.auth/chromium-profile/` also removes a stored logged-in browser
session from disk, and deleting `captured/` removes the cleartext league
password — both are security improvements, not just tidying. `.auth/` itself
survives, since `tokens.json` lives there.

**Phase 2 — discovery.** Map the unmapped surface: roster contents, player
database, lineup submission, market/auction, calendar.

Method: browser DevTools → perform each action once → **Copy as cURL** on the
resulting request → replay it against the API to confirm the shape. This needs
no retained tooling, which is why deleting the capture harness costs nothing.
The trade-off is honest: DevTools is manual where the Playwright script logged
everything automatically. That automation was worth keeping only if discovery
were continuous, and it is not — it is a handful of actions, done once. If
phase 2 turns out to need bulk capture, a throwaway script is an hour's work
and should be written then and deleted again, not carried for months on the
chance it gets used.

This phase is **blocked on league state**, not on effort: rosters are empty and
the auction has not run, so there is no lineup to submit and no market to
observe. It unblocks when the league's asta happens.

**Phase 3 — writes.** Tools behind `FANTACALCIO_ENABLE_WRITES=1`, stdio only.
Each write tool returns a preview of what it will send and requires explicit
confirmation. Scope to be specified after phase 2, since the payloads are
unknown.

## Risks

- **Undocumented API.** No contract, no versioning, no notice before a breaking
  change. Mitigation: models tolerate unknown fields via `raw`; unknown error
  codes pass through.
- **Terms of service.** This uses non-public endpoints. Personal, read-only use
  of one's own league data is the intended scope. Anything wider warrants
  talking to Fantacalcio.it first.
- **Password storage.** Real cost, accepted for self-healing and multi-league.
  Keychain is the default; token-only mode exists for users who decline.
- **Field misinterpretation.** Mitigated by refusing to name unconfirmed
  fields.

## Open questions

1. Does `app_key` rotate? Observed stable across login/logout, but a rotation
   would break every stored config. `ATH000` handling covers it.
2. Is `leghe[].token` (128 chars) needed by any endpoint? Unused so far.
3. Does the account token grant anything the league token does not, beyond
   `/profile`? Only `/profile` was observed using it.

## Non-goals

- Reimplementing Fantacalcio's UI or scoring engine
- HTML scraping — this is a JSON API client
- Supporting the legacy `utente/*` API
- Serving multiple users; this is a single-account personal server
