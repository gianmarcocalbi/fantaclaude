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
  `fantaclaude.ingest.mcp_api` imports it directly. No stdio round-trip, no second
  HTTP client, no drift between two copies of the endpoint knowledge.
- **As config.** League settings (budget, roster bounds, modules, bench,
  bonus/malus, substitutions) come from `get_league_settings` rather than from a
  hand-maintained file. See "League configuration is data, not constants".

What the MCP cannot give us yet: the **player database, roster contents, and
market/auction endpoints are unmapped**, and its Phase 2 discovery is blocked
until an auction actually happens. Ingestion therefore stands on the official
XLSX listone plus web sources, with the MCP as a later adapter.

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
  at the exact `league_settings` row it used. (`asta serve` implies `--offline`, so
  nothing reaches the network mid-auction.)
- **Observed prices are stored in absolute credits**, stamped with the `rules_hash`
  in force, and any normalisation is derived on read. See "Nothing is overwritten"
  for why storing a normalised value would be both arithmetically wrong and a
  violation of the rebuildable-from-raw rule.
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
applied to the `mcp_api` switchover.

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
| league type | `tipo: 2` | candidate Mantra marker, unconfirmed |
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
├── mcp/fantacalcio/          # existing MCP (workspace member)
├── core/                     # workspace member, package `fantaclaude`
│   └── src/fantaclaude/
│       ├── ingest/           # listone_xlsx · stats_web · advanced · news · mcp_api
│       ├── model/            # Mantra roles, module slots, scoring rules
│       ├── analysis/         # projection, valuation, tiers, max price
│       ├── cli/             # Typer app — the interface skills call
│       ├── asta/             # state machine, advisor, persistence
│       ├── lineup/           # the matching optimiser
│       └── api/              # FastAPI: REST + WebSocket, serves the frontend
├── web/                      # Vite · React · TS · Tailwind · shadcn/ui
├── data/                     # gitignored
│   ├── raw/                  # immutable dated downloads
│   ├── fanta.duckdb          # analytical spine
│   ├── asta.sqlite           # live auction state
│   └── exports/              # regenerable renderings
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
fantaclaude asta serve                  # one process: API + WebSocket + frontend
fantaclaude asta adjust <player> …      # live override on the pinned valuation
fantaclaude asta sync                   # reconcile against the league API
fantaclaude asta undo / fix / backup    # revert, correct, snapshot
fantaclaude query --sql … --json        # ad-hoc read-only analysis
fantaclaude schema                      # tables, views and columns, for query authors
fantaclaude doctor                      # offline-readiness check before auction night
fantaclaude kb audit / move-player      # stale documents; club transfer
```

Reads open the databases directly, including mid-auction. **Mutations to live
auction state proxy to a running server** so its derived state stays correct and the
dashboard is notified. See "Concurrency: reads are free, mutations have one owner".

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

Adaptation rules (how many `adattati` the league permits) are league-specific and
resolved in Phase 0 from `sroles`/`minrl`/`maxrl` plus the official regolamento.

### Two stores, split by workload

DuckDB is single-writer: while a process holds the file read-write, another
process opening it fails on the lock. Using it for live auction state would mean a
lock error the first time a CLI query ran mid-auction. So:

| | Store | Why |
| --- | --- | --- |
| live auction state | `data/asta.sqlite` | WAL mode, multi-process safe, transactional, tiny writes |
| analytical spine | `data/fanta.duckdb` | 600 players × 38 giornate, joins, rankings |

Integration cost is near zero: DuckDB's `sqlite_scanner` attaches the SQLite file
and queries it as native tables, so post-auction analysis joins `asta_log` against
`valuations` in one statement, with no ETL.

### Concurrency: reads are free, mutations have one owner

Several processes run at once — the dashboard, CLI invocations from skills, and
the MCP server spawned by Claude Code. Claude is expected to run queries and CLI
commands *during* the auction, and anything they change must appear on the
dashboard immediately.

**DuckDB is single-process, multi-connection.** One process may hold the file
read-write; inside that process, concurrent read and write connections coexist
safely under MVCC. The constraint is on processes, not on operations.

So the rules are:

- **Nothing writes DuckDB during the auction.** The pinned valuation is already
  materialised into SQLite, and `market_prices` is written afterwards. The server
  therefore opens DuckDB **read-only**, and any number of CLI processes may open it
  read-only alongside — no lock conflict, no proxy needed for reads. Claude can run
  analytical queries mid-auction against the file directly.
- **`asta.sqlite` mutations always go through the server** — not for locking, which
  WAL already handles, but for **broadcast**: a direct write would leave the
  server's derived state stale and fire no WebSocket update.
- **Detection is a lock file, not a guess.** The server holds an exclusive
  `flock` on `data/.asta.lock` for its lifetime. A CLI mutation takes the same lock;
  acquiring it means no server is running and direct mode is safe, failing to
  acquire means proxy over HTTP. A missed detection would silently break the
  broadcast invariant, so it must never depend on a port probe or a stale pidfile.
- **Outside the auction**, `ingest` and `rank` need read-write and take the same
  lock briefly. A read-only handle held by a long-running server blocks them, so the
  server drops to lazy per-request connections when not serving an auction.
- **Every mutation funnels through one `mutate()` path** which recomputes derived
  state and broadcasts it. CLI, HTTP, WebSocket or a future MCP-driven sale — same
  path. No state change can escape the dashboard's notice, whatever its origin.

Keeping analytical queries out of the server also keeps them off the async event
loop, where a multi-second DuckDB scan would stall the WebSocket broadcast.

**Two paths, deliberately separated by latency.** The bid-advice loop must answer
in well under three seconds, so it reads `asta.sqlite` only and never runs an
analytical query. DuckDB serves exploration — "what is his away fantamedia over
three seasons?" — asked between lots, not inside the advice loop.

`fantaclaude asta serve --run <run_id>` still materialises the pinned valuation
into `asta.sqlite` at startup, now for those two reasons rather than to dodge a
lock: hot-path latency, and resilience for a single-shot event whose entire state
then lives in one small file that is snapshotted every N sales.

### Live adjustments

The valuation a player deserves can change mid-auction — an injury reported in
the room, a rival filling their last slot, a change of heart about a club. Re-running
the full valuation would be slow and would destroy the pinned run's
reproducibility, so adjustments are their own layer:

```
fantaclaude asta adjust <player> --multiplier 0.8 --reason "limping off in the 60th"
fantaclaude asta adjust <player> --exclude --reason "not paying this"
```

Append-only rows in `asta.sqlite`, applied **on top of** the pinned valuation when
computing dynamic max prices, and broadcast the moment they land. The base run
stays immutable while the board moves live.

Every adjustment carries a reason, so the auction record explains itself
afterwards — which is precisely what `giornata-00-asta.md` and next season's
calibration need.

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
| Live (SQLite) | `asta_log`, `asta_adjustments`, `asta_valuation`, `asta_participants` | append-only events, live overrides, the pinned run, materialised dossiers |

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

**`asta_log` is append-only, corrected by compensating events.** A mistake is
recorded as `void(ref)` or `correction(ref, price)`, never by editing or deleting
the original row. Effective state is a fold over the log. This keeps the auction
record honest — the mistake and its correction are both part of what happened —
and it is what "nothing is overwritten" means when applied to the live store.
`market_prices` reads the effective state, not the raw log.

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

`asta_log` is the compounding asset. Logging every sale yields `market_prices` —
what these specific people actually paid — which calibrates next season's max
prices against reality instead of against a generic listone.

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
| `listone_xlsx` | official Quotazioni XLSX, Classic + Mantra roles | Phase 0 |
| `stats_web` | fantacalcio.it statistiche (premium account) | Phase 0 — see backfill note |
| `advanced` | FBref / Understat xG, xA, minutes per 90 | Phase 0 |
| `calendar` | Serie A fixtures **plus European midweek ties per team** | Phase 0 |
| `news` | probabili formazioni, infortuni, squalifiche | Phase 3 |
| `mcp_api` | `fantacalcio_mcp.api` as a library | when endpoints are mapped |

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

Worth checking first: fantacalcio.it publishes per-giornata voti as XLSX downloads
(`Voti_Fantacalcio_Stagione_…_Giornata_N.xlsx`). If that holds, ~114 files beat
scraping premium HTML on every axis — faster, more stable, structured, and it
sidesteps the terms-of-service question that scraping raises. Confirm before
building `stats_web`.

Three seasons is the recommendation either way: further back, squad and tactical
changes make the data actively misleading.

**Switchover protocol for `mcp_api`:** run it alongside the existing adapter, diff
the outputs, and only then make it the default. Silent disagreement between two
data sources is worse than either being wrong.

**DuckDB extensions are a hidden network dependency.** `sqlite_scanner` and friends
are downloaded on first `INSTALL`, which would fail on auction night behind a bad
connection. They must be installed and verified ahead of time — one of the checks
`fantaclaude doctor` runs, alongside "is the pinned run materialised", "is the token
warm", and "does anything still want the network".

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
`listone quotazione × observed inflation`, rivals ignored. That is deliberately the
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

**And `S` is not a constant.** League settings bound only two role groups
(goalkeepers and outfield, see the observation table), so **roster composition is a
decision variable, not a given**: within those bounds the manager chooses how many
defenders, midfielders and forwards to carry. `V` therefore optimises composition as
well as players, and the target composition in `preferences.yml` is a starting point
the optimiser may depart from — not a constraint it must satisfy. Any hard split
(*"3 portieri, 8 difensori…"*) is a house rule and belongs in `league.yml` with its
`source:`.

#### The algorithm, concretely

Five steps, so the plan does not have to invent them:

1. **Expected pool prices, self-calibrating.** Not a fixed multiplier:
   `inflation = credits still on the market ÷ sum of quotazioni of unsold players`.
   If the room overspent early, residual prices deflate on their own. One division,
   recomputed per sale.
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
5. **Band and adjustments.** `asta_adjustments` multiply `v_i` first; the band comes
   from re-running only the binary search at p25/p50/p75 of `v_i` — three searches,
   not three DPs.

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

#### The sync button, and what the API can honestly tell us

A `sync` action — a button on the dashboard, `fantaclaude asta sync` from a skill,
the same `mutate()` path either way — pulls the league API, reconciles, recomputes
and broadcasts. Sub-second, with no model involved.

The verified endpoints supply exactly the opponent-pressure inputs: **credits spent
and roster counts per team**. The honest limit is granularity — those counts arrive
as classic `{p, d, c, a}`, so the API reports that a rival filled *a defender*,
never whether it was a `Dc` or a `Dd`, which in Mantra is the distinction that
matters.

Hence the division: **the API is authoritative for money, the local log is
authoritative for roles.** A disagreement between the two totals means a sale went
unlogged — the reconciliation signal, obtained for free.

**Two caveats that keep this honest.** First, all of it presumes the admin records
sales *during* the auction; if they are entered afterwards, reconciliation is worth
nothing and the rehearsal cannot detect that. This is a question for the league
admin, not a design assumption — it is listed as an open question. Second, sync is
only sub-second while the token is valid: an expired token turns it into a login
round-trip, so `asta serve` **pre-warms the token at startup** and a sync failure is
reported and ignored rather than blocking the auction.

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

Everything mutating state passes through one `mutate()` path — `apply_sale`, an
undo, a live adjustment, a future MCP feed — which recomputes derived state and
broadcasts it. That is what guarantees a change made from a CLI command mid-auction
appears on the dashboard immediately.

**Division of surfaces.** Credits, slots, pools, dynamic max prices and bid/stop
are pure functions of state — arithmetic, not judgment. Putting a model in front of
them buys seconds of latency to read back numbers a tool already computed. They
belong on an always-visible dashboard at sub-100ms, which frees a *good* model for
the handful of moments that need one: "I lost Bastoni, re-plan my defence budget",
"Marco is desperate for a `Dc` — worth bidding him up?"

The dashboard persists to `asta.sqlite`; the skill reads the same state through the
API, so turning to chat requires retyping nothing.

**Dossiers are materialised, not read live.** Opponent dossiers are markdown, but
the bid loop cannot parse markdown inside its latency budget. At `asta serve`
startup the structured front-matter of each `kb/league/participants/*.md` — spending
pattern, club biases, hoarder or early-spender — is loaded into `asta_participants`
in SQLite. The prose stays for the model to read when explaining a call; the numbers
the pressure model needs are already in a table.

**Live reconciliation, from verified endpoints only.** The league admin is expected
to record sales on fantacalcio.it during the auction. The player-database and
market endpoints are unmapped, but the already-verified `teams` endpoint exposes
`crs` (credits spent) and `r` (roster counts) per team. Polling it detects that a
team spent 45 credits and gained a defender without knowing which player — enough
to flag a divergence from manual entry. This is a **cross-check, never a source**:
manual entry stays authoritative, and the poller only raises discrepancies.

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

**Live updates come from the application layer, not the database.** Neither DuckDB
nor SQLite offers change notification, so:

```
client POSTs a sale → server applies the transition → persists →
recomputes derived state → broadcasts full state over WebSocket to every client
```

On reconnect a client pulls full state, then resumes applying broadcasts. Because
every mutation path goes through `apply_sale`, no state change can escape the
broadcast.

**One process in production.** `npm run build` emits static files that FastAPI
mounts alongside the API and WebSocket. On auction night the entire operating
procedure is `fantaclaude asta serve`, then open localhost.

**Types are generated, not hand-written.** FastAPI emits OpenAPI;
`openapi-typescript` turns it into TS types. The Pydantic models stay the single
source of truth for the contract.

`poe web-dev` runs Vite and uvicorn together for day-to-day work.

### Requirements specific to a single-shot live event

1. **State persists after every sale**, never held only in browser memory. The
   laptop sleeps, the browser crashes, the page reloads — nothing is lost.
2. **Undo and edit any logged sale.** A price will be mistyped in a loud room.
3. **Zero network dependency.** All data is loaded before leaving the house.
   `asta serve` implies `--offline`, so nothing — including the re-sync that `rank`
   performs by default — reaches the network unless the user explicitly runs
   `asta sync`. Otherwise a stray `rank()` mid-auction would hit the live API.
4. **`fantaclaude asta backup`** — timestamped snapshot of `asta.sqlite` every N sales.
   Copying a file that small costs nothing; a corrupt file two hours in with no
   snapshot is unrecoverable.
5. **Durable records leave `data/`.** Snapshots to the same gitignored directory
   protect against corruption, not against losing the disk — and the "compounding
   asset", the immutable forecasts and every `run_id` the journal links to all live
   there. After the auction, `asta.sqlite` is committed to `records/` (it is tiny),
   along with parquet exports of `valuations`, `market_prices` and `league_settings`.
   A journal entry that links to a `run_id` nothing can resolve is worthless.
6. **A printed tier board** as the paper backstop. A dead laptop must not end the
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
- **Auction state machine** — property tests over sale sequences: credits never go
  negative, roster bounds hold, and a `void` compensating event restores exactly the
  state before the sale it references while leaving both rows in the log.
- **CLI** — Typer's `CliRunner` invokes commands in-process, so the contract skills
  depend on is covered: exit codes, `--json` shape, and rejection of bad arguments.
  This is the layer whose breakage would be silent, since a skill sees only output.
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
| Auction state desync | `fantaclaude asta fix` corrects a mislogged sale; the advisor works from partial state rather than demanding correctness |
| Two processes racing a token refresh | File lock around login-and-write, cache re-read after acquiring, shared cooldown stamp |
| A query locking out the dashboard mid-auction | Nothing writes DuckDB during the asta, so every reader opens it read-only; only SQLite mutations proxy, and only for broadcast |
| Scraping blocked or rate-limited | Aggressive caching, dated raw files, polite intervals, and no fetching during the auction |
| API shape changes | Inherited from the MCP: unknown fields survive in `raw`, unknown error codes pass through |
| Missing DuckDB extension on auction night | Extensions installed and verified ahead of time; `fantaclaude doctor` fails loud with the network off |
| Losing the disk | Durable records committed to `records/`, not left in gitignored `data/` |

## Phasing

| Phase | Ships | Target |
| --- | --- | --- |
| **0 — spine** | uv workspace (including `.mcp.json` still resolving via the root lock), `sync-league`, DuckDB schema, Mantra role model, listone + `player_season` ingestion, `kb/` bootstrap, MCP token-cache hardening | 26 Aug |
| **1 — market** | projection, VOR, allocation, tiers, max prices, asta plan; opponent dossiers via `fanta-kb interview` | 29 Aug |
| **2a — asta core** | state machine, advisor, SQLite persistence, undo, backup, CLI entry | 31 Aug |
| **2b — dashboard** | FastAPI + WebSocket + Vite/shadcn UI, reconciliation poll | 2 Sep |
| **freeze + rehearsal** | no new features; full mock auction end to end | 3 Sep |
| **3 — manager** | news ingestion, lineup optimiser, weekly loop, post-giornata calibration | from mid-Sep |

The knowledge base is not a phase — it is the spine plus `kb/`, which every phase
reads and writes back into.

**Cut-line, decided now rather than in a panic.** If Phase 2 runs late, capability
drops in this order: the opponent pressure model, then the dynamic max price,
landing on static prices with live credit and slot tracking. That floor is roughly a
day's work and remains genuinely useful.

The order works because **dynamic pricing does not depend on opponent modelling**:
with pool prices from `listone × observed inflation` and rivals ignored, `V` still
collapses as the pool at a needed role empties, which is what produces the scarcity
behaviour. Opponent pressure improves the price estimate; it is not load-bearing for
the effect. **`asta_log` is never cut** — losing it costs next season's calibration.

**Dates are set backwards from the freeze, not forwards from today.** The auction
is ~5 September and the freeze is 48 hours before it, so **2b must land on 2
September** or the rehearsal cannot rehearse the dashboard — which was the point of
having one.

**One task reaches into existing code:** the MCP token cache needs cross-process
locking (see "Concurrency"), touching `mcp/fantacalcio/auth.py`, a file with its own
spec and tests. It is the only place this design modifies rather than extends the
MCP, so it is named here rather than appearing as a surprise diff.

**The `player_match` crawl runs in the background** from the start of Phase 0, but
nothing waits on it: `player_season` carries the projection, and a throttled crawl
costs precision rather than blocking a phase.

**Rehearsal is mandatory**, on 3 September: log thirty fake sales, exhaust the
budget, mistype a price and undo it, kill the browser and reload, run
`fantaclaude doctor` with the network off, and confirm the admin's live updates
actually appear. Single-shot events are lost to unrehearsed tooling far more often
than to bad models.

## Open questions

1. **When do the league's rules settle?** The league is still forming (8 teams
   observed, ten expected) and the rules may change again. Not blocking — settings
   are read at run time — but the final pre-asta ranking must be produced *after*
   the freeze, and any earlier run treated as provisional.
2. **Is this league actually configured for Mantra?** The whole design assumes it.
   `tipo: 2` is a candidate marker, and `sroles: 2` shows roster bounds are *not*
   Mantra-shaped — which is not a contradiction, since Mantra governs lineup roles
   rather than roster composition, but it is load-bearing enough to confirm before
   the role model is built.
3. **Is the modificatore di difesa active?** Every modifier field is currently null,
   which reads as inactive. Re-check once the league is configured; it materially
   changes both valuation and lineup choice.
4. **Does the admin record sales *during* the auction?** The whole reconciliation
   design rests on it, and if sales are entered afterwards the sync button is
   decorative. A question for the admin, answerable this week, and testable at the
   rehearsal.
5. **Are per-giornata voti available as XLSX?** If `Voti_Fantacalcio_Stagione_…
   _Giornata_N.xlsx` exists, ~114 downloads beat scraping premium HTML and avoid the
   terms-of-service question. Check before building `stats_web`.
6. **Is there a player-database endpoint?** Unlike roster and market endpoints, the
   listone is not blocked by the auction. Worth thirty minutes of DevTools discovery,
   since it would yield Mantra roles directly. Falls back to `listone_xlsx`.
7. **Target roster composition.** Bounds allow 2–6 goalkeepers and 21–34 outfield,
   so the shape is chosen rather than given. The optimiser can propose one; the user
   should state a preference in `preferences.yml` to start from.

## Non-goals

- Automating bids, or acting on the platform during the auction
- Reimplementing Fantacalcio's scoring engine — the MCP reads it from the API
- A multi-user or hosted service; this is one manager on one laptop
- Docker: `uv` pins the toolchain and the databases are files, so a daemon would
  add failure modes on auction night in exchange for reproducibility across
  machines that do not exist
- Serving the dashboard to the room; it would need a read-only view, since nine
  friends should not be reading these max prices
