# fantaclaude — Design

**Date:** 2026-08-22
**Status:** Draft for review
**Scope:** the whole assistant; each capability gets its own spec and plan afterwards

## Purpose

Manage a Fantacalcio **Mantra** team through Claude: build and maintain a knowledge
base, rank players and set max prices before the auction, bid well during it, and
pick the best lineup every week.

The league is `fantabalotelli3` (id 2578630), season 21. The auction is roughly
**5 September 2026**. That date drives every sequencing decision in this document.

## Relationship to `fantacalcio-mcp`

`mcp/fantacalcio/` already exists and is well underway. This design does not
duplicate it and does not block on it.

| | `fantacalcio-mcp` | `fantaclaude` (this design) |
| --- | --- | --- |
| Question | "what does the league API say?" | "what should I do?" |
| Talks to | `apileague.fantacalcio.it` | the local data spine |
| Consumed by | Claude, over stdio | Claude, via skills and the `fantaclaude` CLI |

Two concrete couplings, both cheap:

- **As a library.** The MCP's `api.py` is deliberately free of FastMCP imports, so
  `fantaclaude.ingest.listone_api` imports it directly. No stdio round-trip, no second
  HTTP client, no drift between two copies of the endpoint knowledge.
- **As config.** League settings (budget, roster bounds, modules, bench,
  bonus/malus, substitutions) come from `get_league_settings` rather than from a
  hand-maintained file. See "League configuration is data, not constants".

What the MCP gives us today, and what it cannot yet: the **player database is
mapped** — `/onboarding/v1/league/players`, 539 rows with the Classic role, the
Mantra role codes and separate Classic and Mantra quotazioni (see the MCP spec,
"The listone") — so the listone is ingested through `fantacalcio_mcp.api` from
Phase 0 with no second credential and no XLSX parser. **Roster contents and the
market/auction endpoints remain unmapped**, and that discovery is blocked until an
auction actually happens; historical statistics come from web sources.

### A second MCP, for the auction

`fantacalcio-mcp` is the *league API* client. Auction state is a different data set
with a different lifetime (see "Succession, not reconciliation"), so it gets its own
MCP surface — served from `core/src/fantaclaude/asta/` — rather than being folded
into the first:

| | `fantacalcio-mcp` | `fantaclaude-mcp` |
| --- | --- | --- |
| Question | "what does the league API say?" | "what is true in the auction right now?" |
| Talks to | `apileague.fantacalcio.it` | the server's live state, plus `fanta.duckdb` read-only |
| Transport | stdio | **HTTP, served by `asta serve` itself** |
| Lifetime | the whole season | only while the auction is being served |

**It is not a separate process.** `asta serve` exposes an MCP endpoint alongside the
dashboard and the WebSocket, so `.mcp.json` points at localhost and auction tools
read the server's own in-memory state directly — no IPC, no serialisation hop, and
no possibility of Claude and the dashboard disagreeing. Analytical tools open
`fanta.duckdb` read-only inside a threadpool, which is what keeps a multi-second scan
off the event loop that serves the WebSocket.

It exists so that questions nobody anticipated can still be asked while the auction
runs — *"who can still outbid me on a `Dc`, and how deep?"* — against exactly the
state the dashboard is showing. Being unavailable when no auction is being served is
correct rather than a limitation.

## League configuration is data, not constants

The league's rules are **mutable** — participant count, budget, modules and
modifiers can all change between seasons and even mid-season. Nothing in this
system may hardcode them. They are ingested, versioned and read at run time,
exactly like player statistics.

This is not a detail. Every valuation depends on the rules in force — the money
supply, the roster bounds, the scoring table — so a rule change silently
invalidates any valuation computed before it.

### Mechanism

`league_settings` is a **snapshot table** in DuckDB, not a config file. Each row
records the full settings payload with `season_id`, `fetched_at`, and a
`rules_hash`. Rows are appended, never overwritten, so a rule change becomes
history rather than a lost fact.

```
fantaclaude sync-league   # get_league + get_league_settings + list_teams -> league_settings
```

Three rules follow from it:

- **`fantaclaude rank` re-syncs first** unless `--offline` is passed, so a ranking run
  can never be built on stale rules. The run's `rules_hash` in `valuations` points
  at the exact `league_settings` row it used. (`asta serve` does *not* imply
  `--offline` — it depends on the live feed — but it never ranks: the valuation is
  pinned and materialised before the night, so no re-sync can fire mid-auction.)
- **Observed prices are stored in absolute credits**, stamped with the `rules_hash`
  in force, and any normalisation is derived on read. See "Prices are stored in
  absolute credits" under "Forecasts are immutable" for why storing a normalised
  value would be both arithmetically wrong and a violation of the
  rebuildable-from-raw rule.
- **A settings change is surfaced, not absorbed.** When `sync-league` writes a
  row whose `rules_hash` differs from the previous one, it reports what changed
  and flags every `valuations` run computed under the old rules as superseded.

### What still cannot be derived

Some rules are agreed verbally and appear in no payload: auction format,
adaptation limits if they are not recoverable from `sroles` / `minrl` / `maxrl`,
and the mapping from participant names to dossier files. These live in
`league.yml`, where **every key carries `source:` and `verified_on:`** so its
provenance is as visible as any knowledge-base document.

`league.yml` is for what the API *cannot* express, never for overriding what it
can. If a key duplicates something the API reports and the two disagree,
`sync-league` **fails loud** rather than picking a winner — the same principle
applied to the adapter switchover protocol.

### Observation on 2026-08-22, for orientation only

Recorded so the design can be read concretely. **No code reads these values;**
they are a dated observation and several are already expected to change:

| field | observed | note |
| --- | --- | --- |
| budget | 500 credits | `budg` |
| roster size | min 23, max 40 | `msltc` / `xsltc` |
| role groups | `sroles: 2`, `minrl: [2, 21]`, `maxrl: [6, 34]` | 2+21 = 23 and 6+34 = 40, so these are **goalkeepers vs outfield** — there is no per-role bound below that |
| modules | 11 | `mods` |
| bench / substitutions | 12 / 5 | `tbench` / `ssnum` |
| bonus/malus | goal +3, conceded -1, yellow -0.5, red -1, own goal -1 | `bnMls` |
| modifiers | `stbdf`, `smod*`, `skodm` all **null** | reads as no modificatore active — but the league is unconfigured, so null may mean "not yet set" |
| teams | 8 | `divisions`, corroborated by `n_s: 8` on the league profile |
| league type | `tipo: 2`; `mods` = the eleven official Mantra schemes | **Mantra, confirmed 2026-08-24** by the module set; `tipo: 2` is consistent with it |
| season / matchday | 21 / 1 | |

Two consequences follow if these hold. **Roster composition is the manager's
choice** within 2–6 goalkeepers and 21–34 outfield players, so the optimiser treats
composition as a decision variable rather than a constraint. And **the modificatore
appears inactive**, which simplifies both valuation and lineup selection — though
that is the observation most likely to change when the league is configured.

## Approach

**Chosen: a data spine with thin skills on top.** One normalised local store, fed
by pluggable ingestion adapters. Every capability reads from that store and never
from a source directly.

The division of labour is strict and load-bearing:

- **Python does the math** — anything deterministic, testable, or combinatorial:
  projections, valuation, budget allocation, lineup optimisation.
- **Skills do the judgment** — reading news, weighing context, explaining a call,
  arguing with you during the auction.

This split is not stylistic. Mantra lineup selection is a bipartite matching
problem (players carry role *sets*, modules demand role *slots*), and auction
budgeting is constrained allocation under uncertainty. Both have exact
algorithms; both produce plausible-looking wrong answers when eyeballed by a
language model. Interpreting the results is where the model is genuinely strong.

**Rejected — auction-first vertical slice.** Fastest to 5 Sep, but the weekly
manager would redo ingestion from scratch and the opponent work would be thrown
away.

**Rejected — skills only, no database.** Simplest, and wrong here: rankings
wouldn't be reproducible week to week, identical fetches would be re-paid for in
tokens, and the two combinatorial problems above would be answered by vibes. It
remains the right approach for the *prose* half of the knowledge base.

## Repository architecture

A uv workspace, so one `uv sync` and one lockfile cover both Python projects and
`core` can import the MCP as a library.

```
fantaclaude/
├── pyproject.toml            # workspace root + poe dev chores
├── .python-version           # 3.14
├── league.yml                # only what the API cannot tell us
├── mcp/fantacalcio/          # existing MCP (workspace member) — league API
├── core/                     # workspace member, package `fantaclaude`
│   └── src/fantaclaude/
│       ├── ingest/           # listone_api · stats_web · advanced · calendar · news · asta_live
│       ├── model/            # Mantra roles, module slots, scoring rules
│       ├── analysis/         # projection, valuation, tiers, max price
│       ├── cli/             # Typer app — the interface skills call
│       ├── asta/             # state machine, advisor, adjustment layer, MCP tools
│       ├── lineup/           # the matching optimiser
│       └── api/              # FastAPI: REST + WebSocket, serves the frontend
├── web/                      # Vite · React · TS · Tailwind · shadcn/ui
├── data/                     # gitignored
│   ├── raw/                  # immutable dated downloads
│   ├── fanta.duckdb          # analytical spine — the only database
│   ├── adjustments.yml       # my beliefs and preferences, hot-reloaded
│   ├── asta-state.json       # snapshot of the mirrored auction
│   └── exports/              # regenerable renderings
├── records/                  # committed — durable exports; live-event requirement 5
├── kb/                       # the knowledge base, committed
└── .claude/skills/           # fanta-kb · fanta-market · fanta-asta · fanta-manager
```

Converting `mcp/fantacalcio/` into a workspace member replaces its standalone
`uv.lock` with the root one. That is a small, mechanical migration and it happens
in Phase 0.

**Naming:** the Python package and the project are `fantaclaude`; the working
directory is still `fantaclaudio/` and stays that way by choice. The tree above
shows the project, not the folder name.

The MCP's Phase 1 cleanup has already run — no `package.json`, `tools/`,
`src/client.mjs`, `captured/` or `node_modules/` remain, and the repository was
re-initialised so they are absent from history too. `web/` can be scaffolded
without waiting on anything.

### The skill ↔ Python contract

Skills never write ad-hoc Python. They invoke the **`fantaclaude` CLI**, a typed
Typer application that is the single interface to every domain operation:

```
fantaclaude sync-league                 # refresh league_settings via fantacalcio_mcp.api
fantaclaude ingest all                  # refresh every source
fantaclaude rank                        # write a valuation run, render exports
fantaclaude lineup --giornata 3         # optimal XI per allowed module
fantaclaude asta serve --session FA-…   # API + WebSocket + frontend + live feed
                       [--run <id>]     # pin a valuation; default: newest not superseded
fantaclaude asta adjust <player> …      # append to adjustments.yml, then refresh
fantaclaude asta refresh                # reread adjustments + dossiers, re-price
fantaclaude asta verify-transfer        # diff the snapshot against the lega
fantaclaude query --sql … --json        # ad-hoc read-only analysis
fantaclaude schema                      # tables, views and columns, for query authors
fantaclaude doctor                      # readiness check before auction night
fantaclaude kb audit / move-player      # stale documents; club transfer
```

Analytical reads open `fanta.duckdb` directly, read-only, including mid-auction.
**Live auction state has no file to open**: it exists only inside `asta serve`, so
reads of it go to the running server, over the MCP or REST, and **mutations to it
proxy to that server** so its derived state stays correct and the dashboard is
notified. See "Concurrency: one owner of state, and two classes of query".

A skill decides *which* command to run, then interprets the output like an
analyst. This is what keeps a skill at eighty lines instead of letting it quietly
become a second, broken implementation of the ranking logic — and it makes every
number in the system reproducible and testable outside Claude.

Four properties make this a contract rather than a convention:

- **`--help` is the documentation.** A skill discovers the interface at runtime
  instead of carrying a copy of the flag list in its `SKILL.md`, which would drift
  within a week.
- **`--json` on every read command.** Skills consume structured output; the user
  gets readable tables. One code path serves both, and no skill ever parses prose.
- **Typed arguments and real exit codes.** A bad flag produces a clear error, and
  a skill can distinguish "nothing ingested yet" from "this crashed" without
  pattern-matching a traceback.
- **Commands are importable functions.** The FastAPI server calls `rank()`
  directly rather than shelling out to itself, so there is exactly one
  implementation of every operation.

`query --sql` is the one escape hatch, and it drifts the same way ad-hoc Python
would if left unguarded. It is bounded by **stable named views** (`v_players_current`,
`v_player_form`, `v_pool_remaining`) and by `fantaclaude schema`, which reports what
exists. Skills query views by name; raw table shapes stay free to change.

**poe is not the domain interface.** It keeps the development chores it is
actually good at — orchestrating heterogeneous, multi-process shell work:

```
poe test · poe lint · poe fmt
poe web-dev      # vite and uvicorn together
poe web-build    # frontend bundle
poe types        # openapi-typescript from the FastAPI schema
```

### Two kinds of memory

- **`kb/` in the repo** — facts about the world: Mantra rules, house rules, Serie A
  team notes, opponent dossiers. Git-versioned, diffable, readable by any skill.
- **`preferences.yml` in the repo** — the user's *computation-affecting* choices:
  risk appetite, maximum share of budget per role, clubs excluded on principle,
  target roster composition. These are optimiser inputs, so they are versioned and
  they feed the model hash. A preference that changes a number cannot live
  somewhere unversioned, or the run stops being reproducible.
- **Claude Code's native memory** — conversational context only: how the user
  likes to be argued with, what they have already rejected this week. Nothing that
  enters a computation.

Keeping these apart is what stops preferences from being hard-coded into ranking
logic where they can be neither seen nor changed — and stops them from silently
breaking reproducibility by living only in a chat session.

## Data layer

### The Mantra role model

A player is a *set* of eligible roles (`Dd; Dc; E`); a module is a *multiset* of
slot requirements. Fielding a team is a matching problem, solved exactly.

The consequence that matters commercially: **role flexibility has option value.**
A player eligible for three slots keeps modules open, and is worth more than his
fantamedia implies. Classic-mode rankings systematically undervalue him, and that
gap is the edge being bought at this auction.

The module definitions are **domain data, not API data**: `settings/lineup.mods`
names the eleven schemes and nothing defines them. They are encoded in
`core/src/fantaclaude/model/modules.yml` from the official *Tabella sostituzioni
per schema* (`content.fantacalcio.it/web/risorse/Tabella-sostituzioni-per-schema-2024-2025.pdf`,
linked from the Mantra regolamento and read on 2026-08-24): eleven modules, eleven
slots each, and for every slot the roles that fill it naturally, the roles that fill
it *adattati* with the malus, and the roles allowed only through a forced
substitution. Twelve roles, not eleven — `B` (braccetto) is the listone's code 19,
confirmed on 2026-08-24 against a player's public role badges. Whether the league
caps the number of `adattati` per lineup is not in that table; if the admin sets one
verbally it is a `league.yml` key with its `source:`.

### One database, and the auction is not in it

`data/fanta.duckdb` is the analytical spine — 600 players × 38 giornate, joins,
rankings — and it is the only database in this design.

**Live auction state is held in memory by the server, not persisted to a store.**
An earlier draft put it in `asta.sqlite`, on the reasoning that losing two hours of
typed sales to a crash was unrecoverable. The live feed removed that premise:
**FantaAstaLive's Firebase session is the durable store.** Kill the server, restart,
resubscribe, and a full snapshot comes back — which is exactly what the set-diff
already handles. Persisting a second copy of someone else's authoritative log buys
nothing and costs a schema, migrations, WAL semantics, a lock file and a
mutation-must-persist discipline threaded through every code path.

What genuinely must survive a restart is small, and none of it is auction events:

| File | Holds | Shape |
| --- | --- | --- |
| `data/adjustments.yml` | my beliefs and preferences — exclusions, value factors, composition intent | declarative, hand- or Claude-editable, hot-reloaded |
| `data/asta-state.json` | the mirrored auction as last seen | whole-state dump, atomically replaced on change |

**The snapshot is a plain state dump, kept so the auction can be reviewed after it
ends** — my roster, everyone else's, and what things went for. It is written with
names, roles and participants resolved rather than raw Firebase ids, so it is
readable on its own. Nothing depends on it during the auction: a restart resubscribes
and gets full state from the feed. It is written the way `auth.py` writes its token
cache — temp file, `fsync`, `os.replace` — because from the moment the admin closes
FantaAstaLive until the transfer is confirmed it is the only record of what the room
paid, and a torn write would lose it. For the same reason a copy goes to `records/`
when the auction closes (see live-event requirement 5), and both are removed once
the transfer is confirmed.

Neither file is a database. There is no schema to migrate, and when the auction is
over there is one small file to delete.

### Succession, not reconciliation

The auction and the league **never describe the same world at the same time**, and
that is what guarantees the two data sets cannot conflict:

- **During the auction**, FantaAstaLive is the sole authority on who owns whom. The
  league API is not consulted about rosters, because the admin has entered nothing
  into the lega yet.
- **Once the admin transfers the results**, the league API becomes the sole
  authority and the auction state is closed to writes.

There is no overlap window — therefore no reconciliation, therefore no conflict, and
no cross-checking poll, which could only manufacture false divergence out of a lega
that is legitimately empty.

**Lifecycle: the auction files are deleted, not archived.** Once the lega roster is
confirmed to match what happened in the room, `asta-state.json` is deleted.
Nothing is promoted into the spine and no parquet is exported: the roster and its
purchase prices come back from the league API with the transfer, so copying them
beforehand would duplicate a source rather than preserve one. The snapshot — and its
copy in `records/`, see live-event requirement 5 — survives only until that
confirmation, as the one record of what the room actually did, which is precisely
what catches a price mistyped during the transfer. `adjustments.yml` is mine and
simply stays.

The check has a name. `fantaclaude asta verify-transfer` diffs the snapshot's rosters
and prices against what the league API reports, and deleting the auction files is
something it offers on a clean diff rather than a step to remember.

This rests on the league API exposing rosters with costs. That endpoint is currently
**unmapped**, so verifying it is a prerequisite for purging rather than an
afterthought — `verify-transfer` cannot be built until it is mapped — and it is
listed as an open question.

### Concurrency: one owner of state, and two classes of query

During the auction a single process owns everything live: `asta serve` holds the
state in memory, subscribes to the feed, serves the dashboard, and serves the MCP.
There is no shared mutable store — `adjustments.yml` is the one shared *file*, and
"Live adjustments" says how its writers are serialised — therefore no cross-process
locking to get right, a whole category of failure the earlier SQLite design had to
defend against.

**DuckDB is single-process, multi-connection.** One process may hold the file
read-write; inside that process concurrent read and write connections coexist safely
under MVCC. The constraint is on processes, not operations. So:

- **Nothing writes DuckDB during the auction.** The server opens it **read-only**,
  and any number of CLI processes may open it read-only alongside — no lock conflict.
- **Outside the auction**, `ingest` and `rank` need read-write. A read-only handle
  held by a long-running server would block them, so the server uses lazy per-request
  connections when it is not serving an auction.
- **Every mutation funnels through one `mutate()` path**, which recomputes derived
  state and broadcasts it. Feed event, adjustment, refresh, MCP write — same path.
  No state change can escape the dashboard's notice, whatever its origin.

**The two query classes, which must not be treated alike.** This distinction is what
made a database look necessary when it was not:

| | Reads | Cost | Route |
| --- | --- | --- | --- |
| Auction state | in-memory structures | microseconds | straight from memory, in-process |
| Analytical | `fanta.duckdb` | up to seconds | read-only connection **in a threadpool** |

Auction-state questions — credits, pools, a player's band — are effectively free and
can be answered anywhere, including on the event loop. Analytical questions cannot:
a multi-second scan on the loop that serves the WebSocket would freeze the dashboard
at the exact moment a question felt urgent. Running them via `asyncio.to_thread`
keeps the loop responsive while the scan proceeds.

**The bid-advice loop touches neither.** It must answer in well under three seconds
and reads only in-memory state, never an analytical query. DuckDB serves exploration
— "what is his away fantamedia over three seasons?" — asked between lots.

`fantaclaude asta serve --run <run_id>` loads the pinned valuation into memory at
startup, so the advice loop never reaches for a file at all. Without `--run` it takes
the newest run whose `rules_hash` is not superseded, and names it on the status line
so the wrong run cannot be pinned silently.

### Live adjustments

The valuation a player deserves changes mid-auction — an injury reported in the room,
a rival filling their last slot, a change of heart about a club. Re-running the full
valuation would be slow and would destroy the pinned run's reproducibility, so
adjustments are their own layer, applied **on top of** the pinned valuation. The base
run stays immutable while the board moves.

**Three kinds, with genuinely different mechanics.** Collapsing them into one
"adjustment" would hide the most useful of the three:

| Kind | Means | Effect |
| --- | --- | --- |
| `value` | a fact about the world — *"he's limping"* | scales that player's projection by a `factor` |
| `exclude` | a preference — *"I will not buy him"* | removes him from **my** completion pool |
| `target` | composition intent — *"go heavier on `Dc`"* | biases the composition `V` optimises over — a weighted starting point, never a bound |

`exclude` is the one worth spelling out, because its effect is indirect and correct.
Excluding a striker does not lower his price; it **raises everyone else's**. He
leaves the pool from which `V(C, S)` builds your best completion, so your fallback at
that role gets worse, `V` drops, and the indifference price on every remaining
striker rises. That behaviour falls out of the existing DP — no scarcity rule, no
multiplier, nothing new to tune.

`target` is the soft one, deliberately. It has the same semantics as the composition
in `preferences.yml` — a starting point with a `weight`, which the optimiser may
depart from when the remaining pool makes that shape a bad idea — rather than a
bound `V` must satisfy, so it can never make the completion infeasible mid-auction.
The cost is that *"go heavier on `Dc`"* may visibly move nothing, so `explain()`
reports when the optimiser departed from a target and what it preferred instead;
the answer to "nothing moved" is on the board, not a mystery.

**They live in a file, never in Python.** `data/adjustments.yml` is declarative and
hot-reloaded, so nothing ever restarts to apply one:

```yaml
- player: Malen
  type: exclude
  reason: "not buying him"
- player: Bastoni
  type: value
  factor: 0.85
  reason: "limping, reported in the room"
```

Three surfaces write that same file — you by hand, Claude through an MCP tool, the
dashboard through a form — and a **refresh** action rereads it, rebuilds the
adjustment layer, recomputes the whole board and broadcasts. Sub-second, since the
design already re-prices every player on every state change. An MCP or dashboard
write refreshes implicitly; the button exists for the hand-edited case and for
forcing a deterministic recompute when you want one.

The file is the one piece of shared mutable state in the design, so its writers are
disciplined the same way: `asta adjust`, the MCP tool and the dashboard form all
proxy to the running server, which rereads the file, appends, and replaces it
atomically before refreshing — one writer, whatever the surface. A hand edit is the
exception that bypasses the server, and it is accepted as such: an editor save that
lands in the same instant as a server append can lose one of the two, which is
visible on the next refresh and costs a retyped line rather than any state.

Every adjustment carries a reason, so the auction record explains itself afterwards —
which is what `giornata-00-asta.md` needs. Because the file is mine rather than the
room's, it outlives the auction: I may still not want Malen next week.

**The MCP shares no database**, but it does share `.auth/tokens.json` with
`fantaclaude sync-league`, which imports `fantacalcio_mcp.api` as a library and
refreshes tokens through the same path. Running both concurrently can race two
logins onto that file: a torn read at best, and duplicated logins at worst, which
the MCP's own design flags as how accounts get locked.

The atomic write is **already implemented** (`auth.py` writes via `mkstemp` →
`fchmod 0600` → `fsync` → `os.replace`). What is missing is cross-process
coordination, and all three parts of it:

- `_login_lock` is an `asyncio.Lock`, which serialises coroutines inside one
  process and does nothing across processes.
- `_load_cache()` runs once in `__init__`, so a second process never observes the
  first's freshly written token and logs in regardless.
- The 60s cooldown and the ATH018 rule are per-instance, so a failed login in one
  process does not restrain another — precisely the behaviour `CLAUDE.md` warns
  gets an account locked.

The Phase 0 task is therefore: a **file lock** (`fcntl.flock` on a sidecar) around
login-and-write, a **cache re-read after acquiring it** so the loser of a race uses
the winner's token instead of logging in again, and a **shared last-attempt stamp**
so the cooldown holds across processes. This is the only place this design modifies
rather than extends the MCP.

### Schema

| Layer | Tables | Notes |
| --- | --- | --- |
| Reference | `players`, `teams`, `fixtures` | identity, Mantra roles, quotazioni, calendar including **midweek European ties per team** — snapshotted, not overwritten |
| Observed | `player_season`, `player_match`, `advanced_stats`, `results` | **base voto plus event counts**, never a precomputed fantavoto |
| Config | `league_settings` | append-only snapshots, one per observed rule change |
| Forecast | `predictions`, `lineup_runs`, `lineup_submitted` | written **before** the deadline, never revised |
| Derived | `valuations`, `market_prices`, `calibration` | outputs, what things sold for, predicted-vs-actual |
| Live | *not in the database* | auction state is in-memory in `asta serve`; see "One database, and the auction is not in it" |

**Two hashes, because there are two ways a run goes stale.** `valuations` rows
carry `run_id`, `created_at`, **`rules_hash`** (the `league_settings` row in force)
and **`model_hash`** (the projection and valuation configuration, including
`preferences.yml`). A rules change supersedes a run for a different reason than a
model change, and collapsing them into one `config_hash` makes exactly one of the
two questions — *what moved after I changed the minutes projection?* and *which
runs predate the rule change?* — unanswerable.

**Fantavoto is computed, never stored.** `player_match` holds the base voto and
the event counts (goals, assists, cards, penalties, clean sheets, own goals);
fantavoto is derived at projection time under the **current** `league_settings`.
Storing a precomputed fantavoto would bake in fantacalcio.it's default bonus/malus,
so a change to this league's scoring — which the design insists is mutable — would
never reach the projections, and the modificatore di difesa could not be evaluated
historically at all.

**The live layer is the exception to "nothing is overwritten", and legitimately so.**
Everywhere else in this design, history is the asset: forecasts are immutable,
settings are appended, raw downloads are dated. The auction snapshot is none of those
things — it is a *cache of someone else's authoritative log*, and the authoritative
copy lives in Firebase while the auction runs and in the lega afterwards. Keeping a
local version history of a mirror would preserve nothing that is not already
preserved upstream.

### Forecasts are immutable, and that is what makes the model improve

`predictions` holds `giornata`, `player_id`, `run_id`, `predicted_fv`, `p_start`
and `created_at`, written **before the deadline** and stamped with `model_hash`.
`lineup_runs` records each XI proposed, the module, and what the rejected
alternatives scored.

A deadline usually produces **several** runs — the user re-runs after team news,
then overrides the result by hand. So `lineup_submitted` records the XI that was
actually fielded, pointing at the run it came from where one applies. Without it,
"did the chosen XI beat the alternatives?" silently compares the wrong XI, and the
calibration measures a lineup nobody played.

Joining those to `results` after the weekend yields a calibration curve per role
and per model version. Overwrite them and there is nothing to measure against —
by November this is what reveals that the minutes projection is systematically
optimistic, and for which kind of player. A forecast that can be edited after the
fact is not a forecast.

**`market_prices` is the compounding asset, and it is ingested rather than
promoted.** What these specific people actually paid is what calibrates next
season's max prices against reality instead of against a generic listone — but that
record comes back from the league API once the admin transfers the auction into the
lega, so it is loaded from there like any other source. The auction snapshot feeds
the night itself and is then deleted; it is not the long-term home of anything.

This is the one place the delete decision has teeth. If the league API turns out not
to expose purchase costs (open question 9), then the snapshot *is* the only record of
them, and it must be kept and loaded into `market_prices` instead. Verify before
deleting.

**Prices are stored in absolute credits**, stamped with the `rules_hash` in force.
An earlier draft of this design said to store them normalised by money supply; that
was wrong twice over. Arithmetically, moving from 8 teams to 10 adds 25% more money
*and* 25% more roster slots, leaving average credits per slot unchanged — dividing
by `n_teams × budget` would deflate every observed price for no reason. What
actually changes is the **distribution**: more slots chase the same finite supply of
good players, so replacement level falls and quality gets relatively dearer while
marginal players stay at one or two credits. And storing only a derived value
discards the observation, contradicting the rule that the spine is rebuildable from
immutable raw data.

So: store what was paid, derive any normalisation on read. The comparison that
actually transfers across rule changes is **observed ÷ predicted under that
config** — which is what `calibration` already computes.

### Ingestion adapters

Every adapter implements the same two steps: `fetch()` writes an immutable dated
file into `data/raw/`; `load()` returns a frame matching a declared schema. Nothing
downstream knows where data came from.

| adapter | source | status |
| --- | --- | --- |
| `listone_api` | `/onboarding/v1/league/players` through `fantacalcio_mcp.api` — Classic role, Mantra role codes, Classic and Mantra quotazioni | Phase 0a |
| `stats_web` | fantacalcio.it voti XLSX, `/api/v1/Excel/votes/<season>/<giornata>`, sent the **website** cookie from .env | Phase 0b |
| `advanced` | FBref / Understat xG, xA, minutes per 90 | Phase 0b |
| `calendar` | Serie A fixtures **plus European midweek ties per team** | Phase 0b |
| `news` | probabili formazioni, infortuni, squalifiche | Phase 3 |
| `rosters_api` | rosters and purchase costs through `fantacalcio_mcp.api` | when that endpoint is mapped (open question 9) |

Every row carries `source` and `ingested_at`. `fantaclaude ingest all` is idempotent, and
because raw files are immutable the spine can always be rebuilt from scratch.

**The backfill degrades gracefully, by design.** Two tiers, not one:

- **`player_season` is the Phase 0 deliverable** — presenze, gol, assist, cards and
  minutes per player per season. It is roughly one listing page per season, it is
  cheap, and it carries most of the projection signal.
- **`player_match` is the stretch** — giornata-level, what separates *good* from
  *lucky*, and roughly 38 × ~600 × 3 rows. Valuable, but nothing is blocked without
  it: a throttled crawl costs precision, not a working model.

An earlier draft made `player_match` the critical path, which would have put a
slow, externally-rate-limited crawl in front of everything else.

Checked on 2026-08-24: fantacalcio.it does publish per-giornata voti as XLSX, at
`/api/v1/Excel/votes/<season>/<giornata>`, so ~114 files beat scraping premium
HTML on every axis — faster, more stable, structured, and it sidesteps the
terms-of-service question that scraping raises. The download answers `401` without
the **website** session, which is a different login from the league API's; how
that session is obtained is the discovery step that opens Phase 0b, and until the
first real file is on disk `stats_web` has no golden fixture to be built against.

Three seasons is the recommendation either way: further back, squad and tactical
changes make the data actively misleading.

**Switchover protocol for a second source of the same data:** run it alongside the existing adapter, diff
the outputs, and only then make it the default. Silent disagreement between two
data sources is worse than either being wrong.

**DuckDB extensions are a hidden network dependency.** Any extension the spine uses
is downloaded on first `INSTALL`, which would fail on auction night behind a bad
connection. They must be installed and verified ahead of time — one of the checks
`fantaclaude doctor` runs, alongside "is the pinned run loadable", "does the session
code still connect", and "does `adjustments.yml` parse".

(Wheel availability for Python 3.14 was checked rather than assumed: `duckdb` and
`pyarrow` both publish cp314 wheels; Typer, FastAPI and uvicorn are pure Python.)

### Name matching

Fantacalcio.it writes `Thuram M.`, FBref writes `Marcus Thuram`, Transfermarkt
disagrees about accents, and Serie A contains two Thurams.

A `player_aliases` table backed by a human-editable `kb/rules/aliases.yml`
override. Unmatched rows are **flagged loudly, never silently dropped** — a silent
drop means a striker quietly missing from the rankings on auction day.

## Knowledge base

DuckDB holds neutral numbers; `kb/` holds opinionated prose with provenance. Prose
never restates a number — it links to a query. "Lautaro averages 7.2" is a lie
waiting to happen; "Lautaro takes penalties unless Calhanoglu is on the pitch" is
durable and no stat table contains it.

Four trees, organised by rate of change:

```
kb/
├── rules/                          # near-static
│   ├── mantra.md                   # roles, modules, adaptation limits, bonus/malus
│   ├── house-rules.md              # this league's deviations
│   └── aliases.yml
├── serie-a/teams/<team>/
│   ├── profile.md                  # tactics, module, takers, rotation_factor
│   └── players/<slug>.md           # sparse: only where prose changes a decision
├── league/
│   ├── participants/<name>.md      # opponent dossiers
│   ├── history/<season>.md
│   └── season-2026-27/             # the journal, append-only
│       ├── giornata-00-asta.md     # the auction is entry zero
│       ├── giornata-01.md
│       └── giornata-02.md …
```

Player notes nest under their club because the weekly loop asks club-shaped
questions — one glob returns the tactical profile and every player note together.
They stay *separate files* rather than one `players.md` per club because a team
profile is stable for weeks while a fitness note is stale in four days; merging
them would put one `updated:` stamp over two different rates of change and defeat
the freshness mechanism below. A transfer moves a file, which is correct anyway,
since a note saying "competes with Thuram for the shirt" is wrong the moment he
leaves. `fantaclaude kb move-player` makes it one command. The authoritative team↔player
relation stays in DuckDB; the filesystem merely mirrors it.

`kb/serie-a/teams/<team>/players/` is **sparse by design** — perhaps sixty players
across the league, only those where prose changes a decision: contested rigori,
fitness risk, a tactical role change that invalidates their history. One file per
600 players is the trap that kills projects like this.

**Every document carries front-matter:** `updated`, `ttl`, `confidence`, `source`.
`fantaclaude kb audit` lists what has expired, and `fanta-manager` is instructed to state
low confidence or refuse rather than quietly leaning on a three-week-old probabile
formazione.

### The season journal

`kb/league/season-2026-27/` is an append-only diary: one short entry per giornata
recording what was decided, what was surprising, and what was learned. The
auction is entry zero.

One rule, defended hard: **no number tables in the journal.** An entry links to
the `run_id` that produced the decision; the numbers stay queryable in DuckDB. A
markdown file asserting "Thuram scored 8.5" is a claim that will eventually be
wrong about which Thuram, and nothing will catch it.

**Entries are drafted automatically, and never block anything.** Results
ingestion generates that giornata's entry with the facts already filled in —
predicted versus actual, the largest misses, whether the chosen XI beat the
rejected alternatives, which calls were close — leaving the judgment blank. The
expensive part of a diary is the blank page, and a two-minute review of a draft
happens in November where a twenty-minute write-up does not.

The trigger is concrete, because "when results land" names no moment that actually
occurs: results enter the system on the **next ingest**, and `fanta-manager` runs
that ingest **early in the week** rather than at the deadline. Tuesday's refresh
produces the draft; Saturday's does not. Without the early ingest the draft would
appear at 12:55 on a Saturday with a 15:00 deadline — exactly what this avoids. Unwritten entries are surfaced as a one-line notice when
`fanta-manager` runs — the same mechanism `fantaclaude kb audit` uses for stale
documents — and never as a refusal.

The governing rule, which the freshness mechanism above already follows:
**refuse when missing information makes the output wrong; notify when it only
makes the future poorer.** A stale probabile formazione corrupts this week's
answer and justifies a refusal. A missing journal entry does not.

**The journal is written far more than it is read.** By March there would be
thirty entries, which is exactly the failure mode that per-player files would have
been. So durable lessons are **promoted out of it** into the documents skills
actually read: "Conte rotates fullbacks in Europa League weeks" belongs in
`kb/serie-a/teams/inter/profile.md`; "Marco benches Juve players in derby weeks"
belongs in his participant dossier. The journal stays a chronological record;
the dossiers stay the working knowledge. This is the write-back loop described
below, given a source.

The division holds throughout: **tracking lives in DuckDB, judgment lives in the
knowledge base.** Mixing them turns the knowledge base into a stale mirror of the
database, which is worse than having neither.

### `fanta-kb`

Three modes:

- **`bootstrap`** — build the tree from scratch: rules from the official
  regolamento, team profiles from the web.
- **`refresh`** — find stale documents, re-fetch, rewrite, update front-matter.
- **`interview`** — elicit opponent knowledge conversationally, asking what
  actually predicts auction behaviour: who they support, who they overpaid for
  last year, whether they spend early or hoard, whether they chase their own club's
  players. Output is a dossier in a fixed schema that `fanta-asta` consumes live.
  When the MCP can read league history, the importer fills the same fields and the
  interview only covers the gaps.

**Skills write back.** The auction logs prices and updates dossiers with observed
behaviour; the weekly manager appends to team profiles when it spots a module
change. The knowledge base compounds instead of decaying from the day it was built.

## Capabilities

### `fanta-market` — pre-auction analysis

Five stages, all in Python, all testable:

1. **Project** — `expected_fantamedia × expected_presenze`, both built here. See
   "Projecting a player" below; the listone quotazione is **not** an input.
2. **Mantra-adjust** — role-flexibility option value across the eleven permitted
   modules, plus role scarcity: there are always fewer credible `T` than `Dc`, and
   scarcity is price.
3. **Value above replacement** — the only currency that converts to money. Not
   "how good is he" but "how much better than the best player available for one
   credit in that slot".
4. **Allocate** — the money supply is `n_teams × budget`, read from the current
   `league_settings` snapshot. Distribute the budget across slots to maximise
   expected VOR; this is what produces a **max price** per player.
   **This is the same function Phase 2 calls live**, given a different pool. See
   "One pricing function" below — if pre-auction and in-auction prices come from
   different code, the board jumps the moment the auction starts and neither number
   can be trusted.
5. **Tier** — cluster within role. In a live room, "if I lose him, these three are
   equivalent" is worth more than a ranked list of 600 names.

Output: a stamped run in `valuations`, rendered to `rankings.md` / `.csv` in
`data/exports/`, plus a one-page asta plan with three scenarios (aggressive-attack,
balanced, value-hunting).

**The permanent record is the `run_id`, and only the `run_id`.** The journal entry
`giornata-00-asta.md` links to it; the exports are disposable renderings; nothing is
snapshotted into `kb/`. An earlier draft named three different permanent records,
one of which was a rankings table copied into the knowledge base — which breaks the
rule that prose never restates a number. Durability is handled by exporting
`valuations` to `records/` (see the live-event requirements), not by duplicating it
into prose.

The skill's job is to argue with the model on the user's behalf — "it likes him,
but the knowledge base has a fitness flag" — and re-run under stated constraints.

### Projecting a player

**The quotazione is a price, never a value.** It is denominated in credits and
represents consensus cost; `v_i` is denominated in expected fantapunti. Seeding
`v_i` from the quotazione would re-derive the listino, make our bids identical to
everyone else's, and leave the whole apparatus computing nothing. Its correct job is
the *expected price* of pool players in the pricing algorithm, and nowhere else.

It returns at the end as a **divergence check**: sorting by
`|our value − value implied by the quotazione|` surfaces the positions where we
disagree most with the market. Those are either the edge or a bug, and they are
exactly the list worth reviewing by hand before the auction. Used as an input
instead, it would regress us toward consensus precisely where we would otherwise
profit.

**Expected fantamedia**, in descending order of how much each part matters:

1. **Recomputed under this league's bonus/malus** from base voto and event counts —
   not optional, or we project someone else's scoring system.
2. **Shrunk toward the role mean**, with shrinkage driven by presenze. A 7.4 across
   eleven appearances is mostly noise.
3. **Weighted across three seasons**, recent heavier.
4. **Luck-corrected via xG/xA per 90.** A refinement, not a blocker.

**Expected presenze** carries more variance than fantamedia and is where the
knowledge base earns its keep — 6.5 over 36 games beats 7.2 over 20:

```
expected_presenze = base × depth_factor × rotation_factor × availability_factor
```

- `depth_factor` — first choice, a two-way battle, or cover. The largest term, and
  invisible to the statistics: last season's minutes say nothing about the
  competitor his club signed in July.
- `rotation_factor` — see below.
- `availability_factor` — injury history, age, suspension risk.

#### European competition and rotation

A squad player at a European club may make 24 league appearances instead of 33 — a
~27% cut in total points. That is not a rounding correction, and it is one of the
larger terms in the model.

But it is **not a club-level multiplier**, and applying it as one would be wrong:

- **It is a depth-chart effect.** The untouchable starters play essentially
  everything regardless of Thursday or Tuesday football. Rotation lands on the
  second tier of the squad, so the factor multiplies against a player's place in the
  pecking order rather than against his club badge.
- **Europa and Conference are harsher than Champions.** Thursday to Sunday forces
  more rotation than Tuesday or Wednesday to Sunday. The competition type matters,
  not merely the presence of one.
- **The coach dominates.** Some rotate on principle; some field the same eleven
  until someone limps off. This is the single largest variable and it appears in no
  stat table — it is prose in the team profile.
- **The inverse is not free value.** A mid-table club without Europe has a thin
  squad, so its starters play everything — at a lower fantamedia, with no cover when
  one gets injured.

`rotation_factor` therefore lives in `kb/serie-a/teams/<team>/profile.md`
front-matter as a visible, dated, hand-editable number combining competition type,
coach tendency and squad depth. It is applied per player through `depth_factor`, not
uniformly across a squad.

**It widens the band as much as it lowers the mean.** Rotation makes presenze *less
predictable*, so a heavy-rotation club pushes p25 and p75 apart rather than merely
shifting p50 down. Because max price is solved at those quantiles, uncertainty is
then priced automatically: the same expectation with more variance is worth less,
which is correct.

**And rotation manufactures cheap value.** The backup who starts sixteen matches at
a big club — ideally role-flexible in Mantra — is exactly the three-credit fifth
slot that wins leagues. The model should surface these rather than only penalising
their teammates.

### `fanta-asta` — live auction copilot

The premise: **pre-auction max prices are wrong by minute 40.** If the `Dc` pool is
drying up while four rivals still need three each and have money, the max on the
current `Dc` should rise. Most auctions are lost by treating a printed list as
gospel.

#### Dynamic max price: indifference against the best completion

The scarcity case — *"I still need a `Dc`, few remain, so any starting `Dc` is now
worth more to me than his listed value"* — reads like judgment but is a definition,
and it is the part of this system that is **most** programmatic.

At any moment the state is: credits `C`, slots still to fill `S`, the remaining
pool, and what rivals can still spend. Let `V(C, S)` be the value of the best legal
completion of the roster from here. For a player `p` offered at `x`:

```
buy   = value(p) + V(C − x, S − slot(p))
walk  = V(C, S)                              # best completion without him
max price = the x at which buy == walk
```

**Scarcity requires no special rule — it falls out of `V`.** With three `Dc` left
and only one buyer, the walk-away plan is still a decent `Dc`, `V(C, S)` stays high
and the max price stays modest. With one `Dc` left and three rivals needing one, the
fallback collapses to a one-credit reserve, `V(C, S)` drops, and the indifference
price rises toward everything that can be spared. A hand-tuned "scarcity multiplier"
would be a worse approximation of something computable exactly.

This is Phase 1's value-above-replacement recomputed against the **live remaining
pool** rather than the full listone. That substitution is the entire dynamic.

#### One pricing function

Phase 1's max price and Phase 2's dynamic max price are **the same function with
different inputs**, and this is a requirement rather than an observation:

```
max_price(player, pool, credits, slots, expected_prices) -> band
```

Phase 1 passes the full listone as `pool` with pre-auction expected prices; Phase 2
passes the live remaining pool. If instead Phase 1 priced by "VOR × credits per
point" and Phase 2 by indifference against `V`, the board would jump discontinuously
the moment the auction opened and neither number would deserve trust.

**Expected prices for the pool** come from the cheapest model that works:
`listone quotazione × observed inflation`, rivals ignored — and the *Mantra*
quotazione (`acsma`), never the Classic one, since 163 of 539 players are priced
differently in the two systems. That is deliberately the
model that survives the cut-line — scarcity behaviour does **not** depend on
opponent modelling, because `V` collapses when the *pool* empties, which is visible
from the sale log alone. The opponent-pressure model sharpens the price estimate; it
is not a precondition for the dynamic effect.

#### The band

Projections are distributions, so the indifference equation is solved at the p25,
p50 and p75 of `value(p)`. The p50 is the number shown; the spread is the band. It
costs three solves instead of one, and it is what makes "max price is a band, not a
number" true rather than aspirational — a 60±4 and a 60±25 call for very different
behaviour when the bidding reaches 58.

#### Why it fits in the latency budget

The naive reading is one optimisation per player per update. It is not:

1. One DP over credits `0…C` for the current slot vector, giving `V(c, S)`.
2. One more per Mantra role class, giving `V(c, S − r)` — roughly eight in total.
3. Each player's max price is then a **binary search over `x`** against those
   tables, since `V` is monotone in credits.

Around nine small DPs plus one binary search per player: well under 100ms, so the
**entire board re-prices on every state change**, not merely the player on the
block. No model runs in this loop, and none needs to.

**Where this is an approximation, stated plainly.** The design claims exactness for
lineup matching, so it should not quietly claim it here. `V(c, S)` is a DP over
credits *and a slot vector*, and multi-role players make the underlying problem a
generalised assignment rather than a clean multiple-choice knapsack. The tractable
version pins each pool player to a single role class when valuing the pool, and
keeps exact matching only for the player actually on the block — where it matters
and where one player is cheap to evaluate. The latency test, not the prose, owns the
budget.

**Decided 2026-08-30 (Phase 2a): one mode.** Measured on the auction laptop with
the 553-player test pool: the focused-only board 28 ms, the exact board 241 ms,
the exact board with the knapsack vectorised over ranks 189 ms — boards
identical band for band. A state change arrives once per sale, every thirty
seconds at the fastest, so a quarter of a second is invisible to a human-paced
auction, while a board that jumps for every non-focused player the moment the
auction opens was the defect. `price_board` prices every player with himself
out of the pool; `focus` and `exact` are gone; the latency test's budget is
500 ms. The "well under 100 ms" above described the nine-DP focused design
and stands as the history of the estimate, not as the requirement.

**And `S` is not a constant.** League settings bound only two role groups
(goalkeepers and outfield, see the observation table), so **roster composition is a
decision variable, not a given**: within those bounds the manager chooses how many
defenders, midfielders and forwards to carry. `V` therefore optimises composition as
well as players, and the target composition in `preferences.yml` is a starting point
the optimiser may depart from — not a constraint it must satisfy. A live `target`
adjustment is that same starting point, edited during the auction. Any hard split
(*"3 portieri, 8 difensori…"*) is a house rule and belongs in `league.yml` with its
`source:`.

The auction follows the same bounds. Confirmed with the admin on 2026-08-24: the
only enforced rule is that **two goalkeepers are mandatory**, the rest as each
manager chooses — which is the league's own `sroles: 2` shape, `minrl: [2, 21]`,
to the number, and not the fixed classic counts the session observed on 23 August
carried. So composition stays a decision variable on the night, `S` stays
denominated in Mantra role classes, and the one bounded bucket — goalkeeper — is
unambiguous in Mantra (`Por`), so enforcing it needs no classic-role mapping. There
is no verbal house rule to record in `league.yml`: the admin's rule and the API's
lower bound are the same number. (Should "two" turn out to mean *exactly* two
rather than at least two, that is a tightening of `maxrl` and goes in `league.yml`
with `source: admin`.) The session's settings are still checked against these
bounds at connect.

#### The algorithm, concretely

Five steps, so the plan does not have to invent them:

1. **Expected pool prices, self-calibrating.** Not a fixed multiplier:
   `inflation = credits still on the market ÷ sum of quotazioni of the unsold
   credible pool`. If the room overspent early, residual prices deflate on their
   own. One division, recomputed per sale. The denominator is the same top-~30
   candidates per role the DP already values, not every unsold name: the long tail
   of one-credit players nobody will buy would otherwise dominate it, and late in
   the night both terms shrink toward noise — so the ratio is also clamped to a
   range set in `PricingConfig`.
2. **Per-role value curves.** For each role `r`, `f_r(c)` = the most points
   obtainable buying exactly `k_r` players of that role for `c` credits. A DP over
   the top ~30 candidates (beyond that nothing changes) × `k_r` × credits.
3. **Completion value `V(c)`.** Combine the role curves by max-plus convolution,
   then repeat dropping one slot per role to get `V_{S−r}(c)` — about eight
   variants, reusing the curves already in memory.
4. **Max price by binary search**, since `V` is monotone in credits.
   **The detail that changes the answer:** in *both* branches the player leaves the
   pool — if you do not buy him, someone else does. Computing `walk` with him still
   available overstates the fallback and depresses the ceiling.
5. **Band and adjustments.** A `value` adjustment is a multiplicative `factor` on
   `v_i`, applied before anything else, so p25, p50 and p75 scale together — a
   fitness doubt shrinks the upside as well as the mean, which is what a doubt about
   presenze does. The band comes from re-running only the binary search at
   p25/p50/p75 of the adjusted `v_i` — three searches, not three DPs.

Opponent pressure stays **outside** this: it answers *what will he actually cost*,
not *what is he worth to me*. Two different numbers, displayed separately.

#### The pricing module

The pricing rule is the piece most likely to be tuned by hand, at speed, under
pressure. It gets its own bounded module, `core/src/fantaclaude/asta/pricing.py`,
under four constraints:

- **Pure.** No I/O, no database, no network, no logging. A frozen dataclass in, a
  frozen dataclass out — testable without starting anything.
- **Bounded**, ~250 lines. Growth past that means something which is not pricing has
  moved in.
- **Tunable without editing code.** Every parameter in a `PricingConfig` at the top
  of the file, loadable from `pricing.yml`. Whoever tunes the numbers never opens the
  algorithm; whoever changes the algorithm never hunts for the numbers.
- **`explain()` beside `price()`**, returning the trace: `V` with and without, the
  fallback chosen, the adjustments applied. This is what lets the model explain
  *why 48* without computing it — the invariant that keeps it out of the loop.

```python
def price_board(state: AuctionState, cfg: PricingConfig,
                focus: PlayerId | None = None) -> BoardPricing: ...
```

#### The live feed: FantaAstaLive over Firebase

The admin runs the auction on **FantaAstaLive** (`fanta-asta-live.fantacalcio.it`),
which publishes its state to a Firebase Realtime Database that any participant can
read. That turns the sale log from a typing exercise into an **event feed**: the
dashboard mirrors what the admin records, as it happens, without the user touching a
keyboard in a loud room.

Verified against a live session on 2026-08-23. Anonymous Firebase sign-in
(`identitytoolkit.googleapis.com/v1/accounts:signUp`) yields a token that reads
`/sessions/<code>/state`, whose shape is:

```
picks[]  lastPick  selectedPlayerId  turnTeamId  status  locked
teams[]  settings  options  pickOrder  hostId  playerListHash
```

`picks[]` is the authoritative assignment log — `{playerId, teamId, cost, value,
index, timestamp}` — and it is **strictly more than the league API can supply**:
exact player identity, from which Mantra roles follow, rather than the classic
`{p, d, c, a}` counts that cannot tell a `Dc` from a `Dd`. This is the input the
old reconciliation design wanted and could not get. Of those fields only `playerId`,
`teamId` and `cost` are consumed: `value` is captured and ignored, since what
FantaAstaLive puts there is unverified and `cost` is what was paid.

`selectedPlayerId` is the other prize, and the spec previously had no equivalent:
the instant the admin puts a player up, the board can **auto-focus that lot** and
show its band, the slot it fills and the pressure against it *before* the bidding
opens. `turnTeamId` and `pickOrder` say whose call it is.

**What the feed did not carry, in the mode observed, is a live bid ladder.** It
published completed sales and the selected lot, never the climbing price — the
session was DRAFT-shaped (`turnTeamId`, `pickOrder`), where the admin assigns each
lot. So the dashboard answers *what this player is worth to you* and the room tells
you *what it is at* — which is the right split anyway, since the band is the
decision and the current bid is only the moment to stop. FantaAstaLive's other mode,
A RILANCI, necessarily publishes the current offer; see open question 10.

**Derive credits from `picks[]`, never from `teams[].currentBudget`.** Observed
directly: after 181 credits had been spent, the mirrored budget field still read
500. It is an initial snapshot that the app recomputes client-side. Trusting it
would silently corrupt every max price on the board.

**Session settings are authoritative for the night, and every change to them is
surfaced.** The session carries its own `budget` and role bounds — the observed one
was 500 credits with `gk3/def8/mid8/atk6`, which is *not* this league's
configuration nor what the admin says they will run (two goalkeepers mandatory,
the rest free; see "`S` is not a constant"). The local state captured on
2026-08-23 suggests those per-role numbers are carried for both game types while
the enforced bounds in Mantra (`settings.game = 2`) are `gk` and `mov` —
`teams[].missingPlayers` counts only those two — which would make the check a
comparison of two numbers rather than two taxonomies; confirmed at the rehearsal. What the room is playing is what the
room is playing, so the session wins; but a mismatch against `league.yml` is surfaced **loudly at
connect, before bidding opens**. The settings node arrives in the same snapshot as
`picks[]`, so nothing is polled: each snapshot's settings are diffed against the
last, and a change — the admin correcting the budget after the connect-time warning,
say — is announced on the status line and re-prices the board. Pricing a 500-credit
auction against a 1000-credit config is invisible until it is expensive.

#### The adapter, and the rules that keep it safe

`fantaclaude.ingest.asta_live` owns the connection and emits sale events; it knows
nothing about dashboards. Transport is Server-Sent Events over `httpx` — no Firebase
SDK, no JavaScript, no second runtime.

- **Set-diff, never append-only.** The admin can undo and re-enter a lot, which
  rewrites `picks[]`. Every event is therefore reconciled as a *diff* between the
  snapshot and the rows already logged from the feed, emitting adds, removals and
  cost edits. Applying the same snapshot twice is a no-op, which is what makes
  reconnects and replays safe for free.
- **The mirror is faithful, and never diverges.** There is no local correction path
  and no override flag: whatever the admin records is what the board shows. If they
  mistype a price, that price is what enters the lega and is therefore what was
  actually paid — a private local fix would invent a truth that exists only on this
  laptop, and would leave the dashboard disagreeing with the room. The remedy for an
  admin error is to tell the admin; their edit arrives through the same set-diff.
- **Token refresh is mandatory, not defensive.** The `idToken` expires in about an
  hour; the auction runs three or four. Unrefreshed, the feed dies partway through
  the most valuable stretch of the night, so it is refreshed on the `refreshToken`
  ahead of expiry.
- **Exactly one subscriber.** The server owns the stream. No CLI and no MCP connects
  to Firebase — not because a second reader could double-apply a pick (the set-diff
  makes that a no-op) but because there is exactly one `mutate()` and one derived
  state, and a second subscriber would be a second owner of both.
- **Reconnect with backoff.** A resubscribe returns a full snapshot, so recovery
  needs no bookkeeping of its own.
- **Nicks are scrubbed at ingestion.** `peers[].nick` is whatever someone typed, so
  an `@`-shaped nick is replaced by its `teamId` before it can reach the snapshot,
  the dashboard or a tool result. The repository rule that an email address never
  reaches a tool result applies to the mirror too.
- **The session code is refused at ingestion if it is not a name.** The feed's session
  code is written into `data/asta-state.json` and becomes a path component under
  `records/asta/` when `asta close` copies the night's record out. The adapter
  therefore refuses a code carrying a path separator, `.`/`..`, or a control
  character, at the moment it would write it — the same rule the nick scrub follows,
  and for the same reason: a value that arrives from outside is sanitised where it
  arrives, not where it is finally used. 2a guards the sink as well (`copy_to_records`
  refuses such a code, and the `--session` flag refuses it as a usage error), but that
  guard is a backstop. Left to the sink alone, a malformed code is discovered at
  `close` — after the room has gone home, when the state file is the only record of
  what was paid and the copy into `records/` is the one thing standing between it and
  a gitignored disk.

**Two identity joins, both resolved before the auction rather than during it.** The
player join is Firebase `playerId` → listone `id`, and they are the same
fantacalcio.it identifier: FantaAstaLive's own player directory (539 rows) joins the
league API listone on `id` with every name agreeing, verified 2026-08-24. Auction
ingestion therefore bypasses "Name matching" entirely, and an unknown `playerId` is
a fault to surface, not a name to fuzzy-match.
The team join picks **which team is mine** and maps every other `teamId` and its
free-text `peers[].nick` (`"host"`, a first name, whatever someone typed) onto a
participant dossier, through a **mapping screen at every connect**. The server
persists nothing of it: the previous answer is kept in the browser's `localStorage`
and pre-filled, so after a restart the screen is one glance and one click, and a
lost browser profile costs one screen of re-selection rather than any state. That
is what keeps "a restart resubscribes and gets full state from the feed" literally
true — the mapping is the one input the feed cannot supply, and it is re-asked
rather than recovered. Skipping the screen means discovering at minute one that
opponent pressure is attached to the wrong people.

**There is no manual entry mode.** An earlier draft kept one as a fallback, inherited
from when the user did the typing. With the feed as the sole source it would be a
second data-entry surface built for a case that ends the auction anyway — if
FantaAstaLive is unreadable, the admin cannot run the lots either. The documented
backstop when there is no feed is the **printed tier board**, which the
single-shot requirements already call for and which costs nothing to carry.

#### What the model is for

The rule: **in the loop when the input is unobservable or the objective is in
question; out of it when the answer is a function of state.**

| Question | Decided by |
| --- | --- |
| Max price, scarcity, pressure, bid or stop | **Math.** A function of state, sub-100ms, reproducible |
| "He is limping." "Marco says he is done spending." | **The user or the model → an adjustment.** A fact goes in; the math recomputes |
| "Why 62 for a player I valued at 30?" | **The model.** Reads the computation trace and explains it, or flags a fragile assumption |
| "Should I abandon `Dc` and build elsewhere?" | **The model.** This changes the objective; the optimiser then evaluates the new plan |

The invariant: **the model changes inputs and interprets outputs; it never computes
the number.** A model inside the pricing loop is slower, unreproducible, and
subtly wrong exactly when the room is loudest.

So it is a state machine. Every sale updates remaining credits for every team, the
remaining pool per role, and unfilled slots. Advice is a **dynamic max price** plus
an **opponent pressure** estimate — who else needs this slot and how deep they can
actually go, from dossiers plus observed spending.

Everything mutating state passes through one `mutate()` path — the FantaAstaLive
feed, a live adjustment, a refresh, an MCP-driven write — which
recomputes derived state and broadcasts it. That is what guarantees a change made
from a CLI command mid-auction appears on the dashboard immediately, and it is why
the feed needed no new machinery: it is one more caller of a path the design already
had.

**Division of surfaces.** Credits, slots, pools, dynamic max prices and bid/stop
are pure functions of state — arithmetic, not judgment. Putting a model in front of
them buys seconds of latency to read back numbers a tool already computed. They
belong on an always-visible dashboard at sub-100ms, which frees a *good* model for
the handful of moments that need one: "I lost Bastoni, re-plan my defence budget",
"Marco is desperate for a `Dc` — worth bidding him up?"

The dashboard and the MCP read the same in-memory state from the same process, so
turning to chat requires retyping nothing and the two can never disagree.

**Dossiers are loaded, not read live.** Opponent dossiers are markdown, but the bid
loop cannot parse markdown inside its latency budget. At `asta serve` startup the
structured front-matter of each `kb/league/participants/*.md` — spending pattern,
club biases, hoarder or early-spender — is parsed into memory. The prose stays for the
model to read when explaining a call; the numbers the pressure model needs are
already structured. Refresh rereads them too, so editing a dossier mid-auction takes
effect without a restart.

**No reconciliation against the league API, by design.** The admin records the
auction in FantaAstaLive and transfers the results into the lega *afterwards*, so
while the auction runs the league API has nothing to say about rosters and polling it
would report divergence from a lega that is legitimately empty. The feed is the
source; see "Succession, not reconciliation".

### `fanta-manager` — the weekly loop

Ingest news (probabili, infortuni, squalifiche, all timestamped) → refresh the
affected team profiles → per-player probability of starting and expected fantavoto
given the matchup → optimise.

**European weeks are known in advance, and this is where that pays.** The season-level
`rotation_factor` is an average; the weekly loop can do better. A giornata following
a Thursday Europa tie cuts `p_start` for *that club's* rotation-prone players
specifically, on that weekend — which is a concrete lineup decision rather than an
estimate smeared across thirty-eight matches. It is the more actionable half of the
rotation model, and it needs only the European fixture flag in `fixtures`.

The optimiser solves player→slot matching across every permitted module
simultaneously. If the league runs a **modificatore di difesa**, that single rule
can outweigh individual player quality by rewarding a full same-club defence, so it
is part of the objective function rather than an afterthought.

Output: the XI, the module, an ordered bench that actually covers the right slots,
the two or three close calls with reasoning, and an "if he doesn't start, do this"
contingency.

Then the part everyone skips: **log predicted versus actual after every giornata.**
Predictions were written to `predictions` before the deadline and are never
revised, so the comparison is honest; the result lands in `calibration`, and the
narrative lands in that giornata's journal entry. By November the projections are
calibrated against this league's real scoring rather than August assumptions.

## Dashboard architecture

**Vite + React + TypeScript + Tailwind + shadcn/ui**, served by FastAPI.

Next.js was considered and rejected: SSR, RSC, routing, edge and SEO are all
irrelevant to a single-user real-time dashboard on localhost, while the second
runtime, the build-step parity quirks and the server/client boundary decisions are
real costs on a single-shot live event. shadcn/ui is not Next-specific and drops
into Vite cleanly. A Textual TUI was also considered and rejected: this needs to be
glanceable on a second screen, and dense tables read better in a browser.

**Live updates come from the application layer.** State lives in the server process,
so every source of change converges on one path:

```
FantaAstaLive → Firebase → SSE → ingest.asta_live ─┐
              adjustments.yml + refresh ───────────┼→ mutate() → snapshot →
                            CLI / skill / MCP ─────┘   recompute derived →
                                                       broadcast over WebSocket
```

On reconnect a client pulls full state, then resumes applying broadcasts. Because
every mutation path goes through `mutate()`, no state change can escape the
broadcast — whether it originated with the admin two seats away or with a CLI
command typed mid-auction.

**The session code is asked for at launch.** `fantaclaude asta serve` prompts for
the FantaAstaLive session code (or takes `--session FA-xxx-xxx`), signs in
anonymously, runs the settings check and the team-mapping screen, and only then opens
the board. The result is FantaAstaLive with the analysis attached: the same event
stream the room is watching, plus dynamic max prices, opponent pressure and roster
planning that the platform has no notion of.

**Feed status is always visible** — `live` / `reconnecting` / `offline` — because a
silently dead feed and a quiet auction look identical from across the table.

**One process in production.** `npm run build` emits static files that FastAPI
mounts alongside the API and WebSocket. On auction night the entire operating
procedure is `fantaclaude asta serve`, then open localhost.

**Types are generated, not hand-written.** FastAPI emits OpenAPI;
`openapi-typescript` turns it into TS types. The Pydantic models stay the single
source of truth for the contract.

`poe web-dev` runs Vite and uvicorn together for day-to-day work.

### Requirements specific to a single-shot live event

1. **Nothing lives only in the browser, and nothing needs to.** The laptop sleeps,
   the browser crashes, the page reloads — the server holds the state and the client
   re-pulls it. If the *server* dies, recovery is a resubscribe: Firebase returns a
   full snapshot. The durable store is the admin's session, which is why this design
   keeps no auction database of its own. The one thing the browser does remember —
   the last team mapping — is a pre-filled default, not state: the screen is asked
   again on every connect, and losing the cache means answering it from scratch.
2. **Sales are never edited here, because they are not ours to edit.** Undo and
   correction belong to the admin's session and arrive through the feed. See "The
   mirror is faithful".
3. **Network is assumed; the analysis is still local.** The auction itself runs on
   FantaAstaLive, so a dead network ends the auction rather than merely the
   dashboard — an offline operating mode would be designing for a scenario that
   cannot occur. `asta serve` therefore connects freely, and the earlier `--offline`
   implication is **removed**, since it would have blocked the very feed the design
   now depends on. What stays local is the *analysis*: the valuation is pinned and
   materialised before the night, so no ranking, model call or scrape ever runs
   inside the advice loop. Transient drops are handled by reconnect-with-backoff and
   token refresh, which are protocol facts rather than outages.
4. **Recovery is resubscription, not backup.** With the feed as the durable store
   there is no database to snapshot or corrupt: a restart reconnects and receives the
   full state. `asta-state.json` exists for the *later* problem — the admin's session
   going away after the auction, while the record is still needed to check their
   transfer into the lega.
5. **Durable records leave `data/`; the auction files do not become records.**
   Snapshots to the same gitignored directory protect against corruption, not against
   losing the disk — and the immutable forecasts and every `run_id` the journal links
   to all live there, so `valuations` and `league_settings` are exported to `records/`
   as parquet. The auction snapshot is the exception: per "Succession, not
   reconciliation" it is **deleted** once the admin's transfer into the lega is
   confirmed, because the roster and its prices come back from the league API. It
   does pass through `records/` on the way — copied there when the auction closes,
   so the days between the room and the transfer are not spent with the only record
   of what was paid on one gitignored disk — and the copy is removed with the
   original. A journal entry that links to a `run_id` nothing can resolve is
   worthless; a duplicate of a roster the API will hand back is merely clutter.
6. **A refresh action that recomputes from current inputs.** Adjustments, dossiers
   and the pinned run are reread and the whole board is re-priced, without a restart.
   Mid-auction the useful edit is a belief — *"I'm not buying Malen"* — and it must
   land in seconds, from the dashboard, from Claude, or from a hand-edited file.
7. **A printed tier board** as the paper backstop. A dead laptop must not end the
   auction.

## Testing

- **Optimiser and role model** — unit tests against hand-solved cases: a
  known-optimal XI, a module that is *infeasible* for a given roster (it must say
  so rather than return garbage), a three-role player counted correctly in each.
- **Projection** — a heavier `rotation_factor` must lower expected presenze *and*
  widen the p25–p75 band, not merely shift the mean. And the listone quotazione must
  appear nowhere in the value path: a test that perturbs every quotazione and
  asserts projected values are unchanged keeps the price/value boundary honest.
- **Dynamic max price** — the scarcity property is a testable invariant, not a
  vibe: holding everything else fixed, shrinking the remaining pool at a needed
  role must never *lower* the max price for that role, and exhausting it must drive
  the price to the credits available. Plus a latency test asserting a full-board
  re-price stays inside the budget, since that constraint is what keeps the model
  out of the loop.
- **Ingestion** — golden-file tests against committed sample XLSX/HTML fragments.
  This is the one that earns its keep: fantacalcio.it renames columns most Augusts,
  and the desired outcome is a red test, not silently-null quotazioni.
- **Valuation** — invariants rather than exact numbers, because the numbers are
  meant to change: max prices sum sanely against total credits, tiers are monotone,
  every player has at least one role, no negative VOR.
- **Scoring is league-configurable** — the same event counts under two different
  `league_settings` must yield two different fantavoti. This is the test that would
  have caught a stored fantavoto silently baking in fantacalcio.it's defaults.
- **One pricing function** — Phase 1 and Phase 2 must agree: called with the full
  pool and pre-auction prices, the live pricer reproduces the pre-auction board
  exactly. Any drift here is invisible until auction night.
- **Auction state machine** — property tests over sale sequences: no negative
  credits reach the pricing (`Ledger.credits` is deliberately unclamped, because
  the mirror stays faithful to what the admin recorded — an overspend reads
  `-100`; `build_pool_state` clamps and `price_board` refuses a negative, which
  is where the invariant lives), roster bounds hold, and applying a snapshot that
  drops a previously-seen
  pick (the admin undoing a lot) restores exactly the state before it. The board is a
  pure function of the feed, so any sequence of snapshots must converge on the same
  state as replaying only the last one.
- **CLI** — Typer's `CliRunner` invokes commands in-process, so the contract skills
  depend on is covered: exit codes, `--json` shape, and rejection of bad arguments.
  This is the layer whose breakage would be silent, since a skill sees only output.
- **The live feed** — the diff engine is where a mirror silently corrupts state, so
  it is tested against recorded snapshots: a normal sale, an admin undo, a cost edit,
  a duplicate, an unknown `playerId`, and the same snapshot applied twice, which
  must be a no-op. Token refresh is tested
  on a stubbed clock, because the failure it prevents arrives at minute sixty of a
  four-hour event and never in a short test run.
- **Replay is the rehearsal harness.** A captured SSE session replays through the
  whole pipeline with `--replay <file> --speed N`, no network and no live auction.
  Without it the feed's first real exercise would be auction night itself. The
  capture on disk (`captured/fantaastalive-state-2026-08-23.json`) is the
  pre-auction local state — settings, options, the player directory, no picks — and
  seeds the settings and directory tests; a capture *with* picks comes from the
  rehearsal or a scripted test session, and the diff-engine fixture waits for it.
- **Adjustments are hot-reloaded, and `exclude` has a directional invariant.**
  Rewriting `adjustments.yml` and refreshing must change the board without a restart;
  and excluding a player from a role must **raise** the max price of the *best*
  remaining player at that role, never lower it. That is the same monotonicity the
  scarcity test asserts, reached from the other direction, for the class's own top
  candidate, and it is what proves the exclusion reaches `V` rather than just
  annotating a row. It does not hold for every remaining player at the role: the
  pricing DP has no such invariant in general -- exclusion lowers both the buy and
  walk branches for the players left behind, and the reserve/budget loop and the
  optimal composition shift together whenever the best allocation moves, so a
  lower-ranked remaining candidate can come out cheaper even as the top one gets
  dearer. Confirmed empirically (Phase 2a, Task 10 review): pricing 220-player
  synthetic pools against the real, unfolded `modules.yml` weight curve, excluding a
  class's best player made *some* other remaining member of the class cheaper in 73
  of 132 class x seed trials, mostly with no composition change at all.
- **Crash recovery is a test, not a hope.** Kill the server mid-run, restart, accept
  the pre-filled mapping, and the state rebuilt from the Firebase snapshot must equal
  the state before the kill.
  Separately, loading `asta-state.json` with no feed available must reproduce the same
  board — that is the post-auction path, and it is the one nobody would otherwise
  exercise until they needed it.
- **Skills** — not unit-testable. Each `SKILL.md` carries one worked example
  showing the expected shape of a good answer.

Following the existing MCP conventions: pytest, `respx` for HTTP, no test touches
the network.

## Failure modes

| Failure | Handling |
| --- | --- |
| Source layout drift | Schema assertion at load, fail loud; immutable raw files mean we fix the parser and replay |
| Stale news on giornata day | Expired TTL means stated low confidence or refusal, never silent use |
| Name mismatch | Flagged, never dropped |
| Model overconfidence | Max price is a band: the indifference solve is run at p25/p50/p75 of projected value |
| Auction state desync | Impossible by construction: the board is a pure function of the feed, so a resubscribe reconciles it |
| Two processes racing a token refresh | File lock around login-and-write, cache re-read after acquiring, shared cooldown stamp |
| A query locking out the dashboard mid-auction | Nothing writes DuckDB during the asta and every reader opens it read-only; analytical queries run in a threadpool so they never block the event loop |
| Server killed mid-auction | Resubscribe on restart for a full Firebase snapshot. No database to recover or corrupt |
| Admin's session gone after the auction | `asta-state.json` — written atomically, copied to `records/` at close — holds the last mirrored state, which is what `asta verify-transfer` checks the lega against |
| Scraping blocked or rate-limited | Aggressive caching, dated raw files, polite intervals, and no fetching during the auction |
| API shape changes | Inherited from the MCP: unknown fields survive in `raw`, unknown error codes pass through |
| Missing DuckDB extension on auction night | Extensions installed and verified ahead of time; `fantaclaude doctor` fails loud well before the night |
| Losing the disk | Durable records committed to `records/`, not left in gitignored `data/` |
| Feed drops mid-auction | Reconnect with backoff; a resubscribe returns a full snapshot and the set-diff makes re-applying it a no-op |
| Firebase token expires at minute 60 | Refreshed on the `refreshToken` ahead of expiry; a failed refresh retries and is surfaced on the status line |
| Admin undoes a lot in FantaAstaLive | Set-diff emits the removal and the board re-prices; nothing local resists it |
| Session settings disagree with `league.yml` | Surfaced loudly at connect, before bidding opens; the session wins for the night, and a later change to its settings is diffed out of the next snapshot and announced |
| Anonymous Firebase read blocked or rules tightened | Detected at connect rather than mid-auction, so it is known before the room fills |
| Admin never shares the session code | No feed and therefore no live board; the printed tier board is the backstop |

## Phasing

| Phase | Ships | Target |
| --- | --- | --- |
| **0a — spine** | uv workspace (including `.mcp.json` still resolving via the root lock), MCP token-cache hardening and `players()`, DuckDB schema, `sync-league` with the `league.yml` cross-check, Mantra role model with the module table, listone ingestion through the API, the CLI contract (`schema`, `query`, `doctor`, `kb audit`), `kb/` scaffold | 26 Aug |
| **0b — history** | website-session discovery, then `stats_web` (`player_season` and `player_match` from the voti XLSX), `calendar`, `advanced`; `kb/` bootstrap through `fanta-kb` | after 0a |
| **1 — market** | projection, VOR, allocation, tiers, max prices, asta plan; opponent dossiers via `fanta-kb interview` | 29 Aug |
| **2a — asta core** | state machine, advisor, adjustment layer, state snapshot, CLI entry; plus the six items carried from Phase 1's review (below): the `exact`/focused decision **first**, then the `sync-league` helper and per-class roster bounds as groundwork, the continuous demand fold, and the cleanup | 31 Aug |
| **2b — dashboard** | FastAPI + WebSocket + Vite/shadcn UI, FantaAstaLive feed, `fantaclaude-mcp` | 2 Sep |
| **freeze + rehearsal** | no new features; full mock auction end to end | 3 Sep |
| **3 — manager** | news ingestion, lineup optimiser, weekly loop, post-giornata calibration | from mid-Sep |

The knowledge base is not a phase — it is the spine plus `kb/`, which every phase
reads and writes back into.

### Carried into 2a from Phase 1's review

Five items were found reviewing Phase 1 and deliberately not fixed there, because each
is either a decision 2a has to make anyway or a refactor that gets harder once the live
auction is built on top of it. They are recorded here rather than in a backlog so 2a
starts from them.

**Order within 2a.** The `exact`/focused decision comes first, before the advisor is
written, because it determines whether the advisor may call `price_board` per state
change at all. The two refactors come next and before the state machine: both are
cheap, neither changes behaviour, and both get materially harder once `asta` is a third
caller of the sync flow and once live state is expressed through `PoolState`. The
continuous demand fold and the cleanup are last and are the first things to drop.

**Against the cut-line below.** If the dynamic max price is cut, the `exact`/focused
decision goes with it — a static board has no focused mode to reconcile — so that
decision is worth making early precisely because it is the one that becomes free if the
cut-line is reached. The two refactors survive every cut: they are groundwork for the
state machine, which is the floor.

**One design question 2a must answer, not a defect:**

- **`exact` is a second pricing mode behind one function name.** The pre-auction board
  prices everyone with `exact=True`; the latency-bounded live board prices only `focus`
  exactly, so the committed `records/` board and the live board disagree for every
  non-focused player the moment the auction opens. "The live pricer reproduces the
  pre-auction board exactly" is tested only for the focused player, and the discrepancy
  is explained in a prose `note` in `explain()` rather than designed away. 2a has to
  choose: re-run `exact=True` per state change against the latency budget (the exact
  board measures ~270 ms against a 100 ms budget), or ship a board that jumps and say
  by how much. Decide it before the advisor is written, not during the auction.
  **Decided 2026-08-30: re-run exactly per state change; see "Why it fits in the
  latency budget".**

**Two refactors to do first, as groundwork:**

- **`rank_cmd` re-implements `sync_league_cmd`'s fetch/conflict/apply flow** and drops
  the `SyncReport`, so a rules change detected during `rank` supersedes every earlier
  run without showing the diff or count that `sync-league` renders. The two copies have
  already diverged. Do the shared helper **before** 2a's `asta` command becomes the
  third copy.
- **Goalkeeper bounds are two scalar `PoolState` fields plus `cls == "Por"` branches**,
  while every other class already has the per-class `hard_minimums` dict. A "3 portieri,
  8 difensori" house rule, or the roster-bound contingency this document already
  anticipates, needs new fields and more branches. `class_min` / `class_max:
  dict[str, int]` is the general shape, and `PoolState` is how 2a expresses live state —
  widen it before building on it.

**One modelling improvement, deferred because it moves every price:**

- **The unsatisfiable-demand fold is all-or-nothing.** Phase 1 folds a role class's
  module demand onto the classes its players actually pin to, but only when that class
  has *literally zero* pinned supply, so one listone row can move ~0.5 slots of demand
  per module and every price with it, from a routine re-sync. A class with one supplier
  against six league-wide slots is as unsatisfiable as one with none. Phase 1 ships a
  `thin_classes` warning so the cliff is visible; the continuous version — fold in
  proportion to the shortfall — should **replace** that warning rather than sit beside
  it. Held back because the retained-fraction shape is a design question rather than a
  derivation, and because it would move every price a third time in one branch.

**Cleanup carried forward,** none of it load-bearing: `analysis/valuation._digest`
duplicates `league/settings.rules_hash`'s formula; `doctor._read_only` re-implements
`connect(read_only=True)` and the database is opened up to six times per `doctor` run,
so a file held by a writer reports "cannot open database" and "skipped: no database"
two lines apart; `rank._load_preferences` is another copy of the `safe_load … or {}`
loader and catches only `yaml.YAMLError`; the front-matter prologue is copied across
`kb/notes.py`, `kb/participants.py` and `kb/profiles.py`, and `kb/audit._validator_for`
re-encodes the loaders' globs as parent-name checks so audit and `rank` can accept
different files; `analysis/history.EVENT_COLUMNS` re-lists `Events`' fields, making a
mismatch a `TypeError` at rank time rather than an import error; `valuation._finite` and
`pricing._json` are two scrubbers for one JSON-safety rule while `pricing.explain()`
applies neither; and `exports._rows` is rebuilt five times per rank, with
`exports._header` and `cli/app._render_rank` hand-kept near-copies that already print
different fields.

**Cut-line, decided now rather than in a panic.** If Phase 2 runs late, capability
drops in this order: the opponent pressure model, then the dynamic max price,
landing on static prices with live credit and slot tracking. That floor is roughly a
day's work and remains genuinely useful.

The order works because **dynamic pricing does not depend on opponent modelling**:
with pool prices from `listone × observed inflation` and rivals ignored, `V` still
collapses as the pool at a needed role empties, which is what produces the scarcity
behaviour. Opponent pressure improves the price estimate; it is not load-bearing for
the effect.

**The feed is not cuttable, because nothing sits behind it.** Removing manual entry
made the feed load-bearing: no feed means no live board, and the fallback is the
printed tier board rather than a second data-entry surface. That is a deliberate
trade — one source, faithfully mirrored, instead of two that can disagree — and it
raises the stakes on the two connect-time checks, which is why they run before the
room fills rather than during. The state snapshot is never cut: without it there is
no record of the room to check the admin's transfer against.

Adding the feed is close to cost-neutral, because the reconciliation poll and the
`asta sync` button are both **removed** — they were designed for an admin who
records sales into the lega live, which is not what this admin does.

**Dates are set backwards from the freeze, not forwards from today.** The auction
is ~5 September and the freeze is 48 hours before it, so **2b must land on 2
September** or the rehearsal cannot rehearse the dashboard — which was the point of
having one.

**Two tasks reach into existing code**, both named here rather than appearing as a
surprise diff. The MCP token cache needs cross-process locking (see
"Concurrency"), touching `mcp/fantacalcio/auth.py`, a file with its own spec and
tests — the only place this design *modifies* the MCP. And `api.py` gains one
method, `players()`, for the listone endpoint the MCP spec mapped after its tool
surface was built — an *extension* in the MCP's own one-method-per-endpoint style,
with no new tool (539 rows is not a tool result).

**The `player_match` crawl runs in the background** from the start of Phase 0b, but
nothing waits on it: `player_season` carries the projection, and a throttled crawl
costs precision rather than blocking a phase.

**Two cheap verifications gate decisions made elsewhere in this document.** That
Firebase `playerId` equals the listone `id` decided whether auction ingestion could
skip name matching — done on 2026-08-24, it can (open question 8). That the league
API exposes rosters with purchase costs decides whether the auction store may be
purged rather than kept — still open, and answerable only once a roster exists
(open question 9).

**Rehearsal is mandatory**, on 3 September: replay a captured FantaAstaLive session
end to end, exhaust the budget, have the admin undo a lot and confirm the board
follows, exclude a player mid-run and watch the rest of that role re-price, kill the
browser and reload, kill the server and restart through the pre-filled mapping
screen, drop the network mid-run and watch the reconnect recover, ask
`fantaclaude-mcp` a question while the board is live, and reload from
`asta-state.json` with the feed switched off. Single-shot events are lost to unrehearsed tooling far more
often than to bad models.

## Open questions

1. **When do the league's rules settle?** The league is still forming (8 teams
   observed, ten expected) and the rules may change again. Not blocking — settings
   are read at run time — but the final pre-asta ranking must be produced *after*
   the freeze, and any earlier run treated as provisional.
2. **~~Is this league actually configured for Mantra?~~ Resolved 2026-08-24.** Yes.
   The league's `mods` — `343`, `3412`, `3421`, `352`, `3511`, `433`, `4312`, `442`,
   `4141`, `4411`, `4231` — are the Mantra regolamento's eleven schemes one for one,
   and `tipo: 2` is consistent with that. `sroles: 2` showing roster bounds that are
   not Mantra-shaped is no contradiction: Mantra governs lineup roles, not roster
   composition.
3. **~~Is the modificatore di difesa active?~~ Decided 2026-08-29.** Inactive
   (every modifier field null on every snapshot since 2026-08-22). In Mantra
   the modifier is the D-Factor — the five best voti among Dc/B/Dd/Ds/E/M with
   at least three true defenders, optionally the goalkeeper, averaged and
   mapped to points; its thresholds are not published and are customisable
   per league, so they live in `model/d_factor.yml` as data, empty until
   transcribed from the league's settings page. Phase 1 models the mechanism
   (`model/d_factor.py`) and applies a per-player uplift when
   `calculate.smodd` is non-null; any other modifier key turning non-null
   makes `rank` refuse.
4. **~~Does the admin record sales during the auction?~~ Resolved 2026-08-23.** No:
   the admin runs the auction in FantaAstaLive and transfers the results into the
   lega afterwards. That retired the reconciliation design in favour of the live feed
   and the succession rule. What remains open is narrower — **will the admin share
   the session code**, and does their session's configuration match what they have
   said (two goalkeepers mandatory, composition otherwise free — confirmed verbally
   on 2026-08-24)? Both are answerable before the rehearsal, and both now matter more
   than they did: with manual entry removed, no session code means no live board.
5. **~~Are per-giornata voti available as XLSX?~~ Resolved 2026-08-29.** They
   are: the voti page links `fantacalcio.it/api/v1/Excel/votes/<season>/<giornata>`,
   and the quotazioni page `…/api/v1/Excel/prices/<season>/<giornata>`, so
   `stats_web` should be an authenticated XLSX download rather than an HTML scraper.
   Both answer `401` without a session for every season probed (17 through 21), so
   the download needs the **fantacalcio.it website login** — a different session
   from the league API's `apileague` token, and one more credential to keep in
   `.env`. The session is carried by two cookies, `fantacalcio.it` and
   `client.fantacalcio.it` (both host-only on `www.fantacalcio.it`), alongside
   load-balancer stickiness (`AWSALB`/`AWSALBCORS`) and a run of consent/analytics
   cookies that carry no session; the pair lasts about a week (observed expiry
   2026-09-04, roughly seven days after capture), so the capture has to be
   repeated on that cadence. The cookie header is captured from a browser by the
   account holder and pasted into `.env` as `FANTACALCIO_WEB_COOKIE` — code
   sends it and never obtains it; there is no login code in this repo. All three
   seasons probed answered `200 … xlsx`: the current season (21, 2026-27) and
   two of the three back seasons spot-checked, 20 (2025-26) and 18 (2023-24) —
   so the back catalogue is served, not gated to the current season. A giornata
   not yet played (21/38, the season's last) also answers `200`, not `404`:
   the body is a one-sheet placeholder workbook whose only cell reads "File
   ancora non disponibile. Riprova più tardi" rather than a voti table — an
   adapter has to detect this by shape, not by status code. Every real workbook
   carries three sheets in the same order — `Fantacalcio`, `Statistico`,
   `Italia`, one per voto source — each laid out identically: four title and
   disclaimer rows, then the header row on row 6,
   `Cod., Ruolo, Nome, Voto, Gf, Gs, Rp, Rs, Rf, Au, Amm, Esp, Ass`, then player
   rows grouped under club blocks, each opened by a row carrying only the club
   name (every other cell blank); a senza-voto reads `6*`. `Cod.` is the
   fantacalcio.it player id, and it is the join key `stats_web` relies on to
   land in the current listone: 92% of giornata 1 2026-27's codes match, against
   67% for 2025-26 and 41% for 2023-24 — falling off as expected, since players
   leave Serie A over the intervening seasons. Recorded 2026-08-28: the voti
   HTML page (`/voti-fantacalcio-serie-a/<season>/<giornata>`) is public — no
   session required — and carries the same data keyed by the fantacalcio.it
   player id, with `55` as its senza-voto sentinel; the spec's original
   "premium HTML" premise for that page was wrong, but it stands as the
   fallback source should the XLSX export ever be withdrawn.
6. **~~Is there a player-database endpoint?~~ Resolved 2026-08-23.** Yes:
   `/onboarding/v1/league/players`, mapped in the MCP spec ("The listone") — Classic
   role, Mantra role codes and separate Mantra quotazioni. It is Phase 0a's listone
   source; the XLSX is no longer needed for it.
7. **Target roster composition.** Bounds allow 2–6 goalkeepers and 21–34 outfield,
   and the admin has confirmed the auction keeps that freedom (two goalkeepers
   mandatory, the rest as chosen), so the shape is chosen rather than given. The optimiser can
   propose one; the user should state a preference in `preferences.yml` to start
   from. Decided 2026-08-29: the optimiser proposes the composition;
   `preferences.yml` keeps `target_composition: {Por: 2}` as a soft prior
   (raised demand weights, never a bound), and `rank` prints the composition
   it chose per scenario.
8. **~~Does Firebase `playerId` equal the listone `Id`?~~ Resolved 2026-08-24.** It
   does: FantaAstaLive's player directory (539 rows, the ids `picks[].playerId` is
   drawn from) joins the league API listone on `id` with all 539 names agreeing.
   Auction ingestion skips name matching entirely.
9. **Does the league API expose rosters with purchase costs?** The `/market/v1/…`
   namespace exists but roster contents are unmapped, and no cost field appears in
   any captured fixture. The MCP spec ("Ownership — unresolved") records the paths
   already probed and found absent, that `/market/v2/*` is edge-blocked, and the
   decisive test: diff the listone the moment one player is assigned. Purging the
   auction store assumes the answer is yes. Until it is verified, keep the file —
   the cost of being wrong is losing the only record of what the room paid.
10. **Does FantaAstaLive expose anything during active bidding? Sharpened
    2026-08-24.** FantaAstaLive runs in one of two modes: **DRAFT**, turn-based,
    where the admin assigns each lot, and **A RILANCI**, where anyone bids at any
    time and the lot goes to the last offer when a countdown expires. The observed
    session carried `turnTeamId` and `pickOrder`, which is DRAFT-shaped — that is
    why no bid ladder appeared. In A RILANCI the current offer and countdown must be
    published to every client, so a live bid *would* be in the state node. The
    question is therefore **which mode the admin will run** — ask when asking for
    the session code — and, if A RILANCI, the bid fields are read at the rehearsal
    so the board can show distance-to-max live instead of only the band.
    FantaAstaLive's own local state (captured 2026-08-23, pre-auction) carries
    `options.bids` and `options.draft` side by side and a `bids-log` list, so the
    ladder exists client-side; what the rehearsal checks is whether it is mirrored
    into the session node.

11. **Should the club penalty rate fall back for a promoted club? Found
    2026-09-02.** `penalty_rate_clubs` is built from `last_back` — the single
    most recent *completed* season (20) — so a club absent from it has no
    observed rate, and `_taker_warning`'s sibling warning fires. In the
    2026-27 listone that is Frosinone, Monza and Venezia: all three played
    seasons 18/19 and are back in 21, none played 20. The consequence is
    bounded and deliberate (the projection does not redistribute on a rate it
    never observed, so the taker is not punished) but it is real: for three of
    twenty clubs, the profile's penalty taker changes nothing, and a promoted
    club's designated taker is valued conservatively against an established
    club's. The candidate fixes — read those clubs' own seasons 18/19, or fall
    back to a league-average rate — each move every price at those clubs and
    mint a new `model_hash`, so **not before the 2026-27 auction**. Phase 3.

12. **The team snapshot reads only the first page. Found 2026-09-02.**
    `fetch_snapshot` calls `api.teams(page=1, league=league)` and never asks for
    page 2. The endpoint's page size is 10, so the defect is invisible in a
    league of ten or fewer and silent above it: at eleven teams the response
    carried ten objects and `divisions[A].count = 11`; at twelve, ten objects
    and `count = 12`. The teams that fall off are the newest, which is exactly
    the case that matters before an auction — a manager who has just joined is
    the one the snapshot cannot see.

    It does **not** corrupt `team_count`, which reads the league profile's
    `n_s` and only falls back to `len(team_rows)` when that is null; and the
    auction binds rivals by nick against the FantaAstaLive session rather than
    against this list, so the dossiers are unaffected. What it does break is any
    reading of the embedded team list as complete. Fix is to page until
    exhausted and cross-check the total against `divisions[].count` — after the
    2026-27 auction, not during the freeze.

13. **`n_s` is the league's configured size, not its actual one. Found
    2026-09-02.** The valuation reads it for `team_count`, and it is baked into
    `rules_hash`, so it sets the market (`teams x budget`) and every price. It
    is set by the admin and drifts freely from reality: it read 8 while ten
    teams existed, then 12 when the true figure was 10. There is deliberately no
    override — `team_count` is in `league_yml.COMPARABLE`, so a disagreeing
    entry makes `apply_sync` refuse and record nothing. That refusal is correct
    (a league.yml that silently overrode the API would be worse) but it means
    **the pre-auction run is blocked on the admin setting the number
    correctly**, and that dependency deserves to be visible rather than
    discovered on the night.

## Non-goals

- Automating bids, or acting on the platform during the auction
- Reimplementing Fantacalcio's scoring engine — the MCP reads it from the API
- A multi-user or hosted service; this is one manager on one laptop
- Docker: `uv` pins the toolchain and the databases are files, so a daemon would
  add failure modes on auction night in exchange for reproducibility across
  machines that do not exist
- Serving the dashboard to the room; it would need a read-only view, since nine
  friends should not be reading these max prices
- Writing to FantaAstaLive, joining the session as a bidding participant, or acting
  on the platform in any way. The feed is read-only and the mirror is one-directional:
  the admin's session is the record, and this dashboard is a reader of it
