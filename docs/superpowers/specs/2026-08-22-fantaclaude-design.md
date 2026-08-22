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
| Consumed by | Claude, over stdio | Claude, via skills and poe tasks |

Two concrete couplings, both cheap:

- **As a library.** The MCP's `api.py` is deliberately free of FastMCP imports, so
  `fantaclaude.ingest.mcp_api` imports it directly. No stdio round-trip, no second
  HTTP client, no drift between two copies of the endpoint knowledge.
- **As config.** League settings (budget, roster bounds, modules, bench,
  bonus/malus, substitutions) come from `get_league_settings` rather than from a
  hand-maintained file. See "Configuration".

What the MCP cannot give us yet: the **player database, roster contents, and
market/auction endpoints are unmapped**, and its Phase 2 discovery is blocked
until an auction actually happens. Ingestion therefore stands on the official
XLSX listone plus web sources, with the MCP as a later adapter.

## Known league facts

Verified from the API on 2026-08-22 and recorded here so the analysis is built
against reality rather than defaults:

| fact | value | source |
| --- | --- | --- |
| budget | 500 credits | `settings/rosters.budg`, `teams.cri` |
| roster size | min 23, max 40 | `settings/rosters.msltc` / `xsltc` |
| modules | 11 | `settings/lineup.mods` |
| bench | 12 | `settings/lineup.tbench` |
| substitutions | 5 | `settings/calculate.subst.ssnum` |
| bonus/malus | goal +3, conceded −1, yellow −0.5, red −1, own goal −1, plus penalties/assists/MOTM | `settings/calculate.bnMls` |
| teams | 8 in division A | `teams.divisions` |
| season / matchday | 21 / 1, opened 2026-08-22T16:30 | `status` |

Two of these need resolving in Phase 0 and are tracked in "Open questions": the
team count disagrees with the stated ten participants, and the fields that would
confirm Mantra role constraints (`sroles`, `minrl`, `maxrl` on roster settings)
are currently unmodelled by the MCP.

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
├── pyproject.toml            # workspace root + poe tasks
├── .python-version           # 3.14
├── league.yml                # only what the API cannot tell us
├── mcp/fantacalcio/          # existing MCP (workspace member)
├── core/                     # workspace member, package `fantaclaude`
│   └── src/fantaclaude/
│       ├── ingest/           # listone_xlsx · stats_web · advanced · news · mcp_api
│       ├── model/            # Mantra roles, module slots, scoring rules
│       ├── analysis/         # projection, valuation, tiers, max price
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

**Sequencing note:** the MCP's own Phase 1 cleanup deletes the root `package.json`,
`node_modules/`, `tools/`, `src/client.mjs` and `captured/`. That cleanup must land
before `web/` is scaffolded, so the new frontend's `package.json` is never confused
with the Playwright one being removed. Fixture extraction from `captured/` is
already committed, so nothing blocks it.

### The skill ↔ Python contract

Skills never write ad-hoc Python. They invoke **poe tasks**, which form a stable,
documented CLI:

```
poe ingest-all                  # refresh every source
poe rank --budget 500           # write a valuation run, render exports
poe asta-serve                  # one process: API + WebSocket + built frontend
poe lineup --giornata 3         # optimal XI per allowed module
poe kb-audit                    # list stale knowledge-base documents
```

A skill decides *which* task to run, then interprets the output like an analyst.
This is what keeps a skill at eighty lines instead of letting it quietly become a
second, broken implementation of the ranking logic — and it makes every number in
the system reproducible and testable outside Claude.

### Two kinds of memory

- **`kb/` in the repo** — facts about the world: Mantra rules, house rules, Serie A
  team notes, opponent dossiers. Git-versioned, diffable, readable by any skill.
- **Claude Code's native memory** — facts about *the user*: spending preferences,
  risk appetite, teams they refuse to roster.

Keeping these apart is what stops preferences from being hard-coded into ranking
logic where they can be neither seen nor changed.

## Configuration

`league.yml` is deliberately small. Anything the API knows is fetched, not typed:

```
poe sync-league   # get_league_settings + get_league + list_teams → data/fanta.duckdb
```

`league.yml` holds only what the API cannot express — house rules agreed verbally,
auction format, the mapping from participant names to dossier files, and any
Mantra adaptation limits not recoverable from `sroles`/`minrl`/`maxrl`. Every
value carries a comment naming why it isn't derived.

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
lock error the first time a poe query ran mid-auction. So:

| | Store | Why |
| --- | --- | --- |
| live auction state | `data/asta.sqlite` | WAL mode, multi-process safe, transactional, tiny writes |
| analytical spine | `data/fanta.duckdb` | 600 players × 38 giornate, joins, rankings |

Integration cost is near zero: DuckDB's `sqlite_scanner` attaches the SQLite file
and queries it as native tables, so post-auction analysis joins `asta_log` against
`valuations` in one statement, with no ETL.

### Schema

| Layer | Tables | Notes |
| --- | --- | --- |
| Reference | `players`, `teams`, `fixtures` | identity, Mantra roles, quotazioni, calendar |
| Observed | `player_season`, `player_match`, `advanced_stats` | `player_match` is giornata-level voti — what separates *good* from *lucky* |
| Derived | `valuations`, `market_prices` | outputs, and what things actually sold for |
| Live (SQLite) | `asta_log`, `asta_state` | every sale, every credit balance |

`valuations` rows are stamped with `run_id`, `created_at`, and a hash of the config
that produced them. Rankings will be re-run twenty times in a fortnight; being able
to ask *what moved after I changed the minutes projection* is the difference
between tuning a model and superstition.

`asta_log` is the compounding asset. Logging every sale yields `market_prices` —
observed inflation in this specific league, by these specific people — which
calibrates next season's max prices against reality instead of against a generic
listone.

### Ingestion adapters

Every adapter implements the same two steps: `fetch()` writes an immutable dated
file into `data/raw/`; `load()` returns a frame matching a declared schema. Nothing
downstream knows where data came from.

| adapter | source | status |
| --- | --- | --- |
| `listone_xlsx` | official Quotazioni XLSX, Classic + Mantra roles | Phase 0 |
| `stats_web` | fantacalcio.it statistiche (premium account) | Phase 0 |
| `advanced` | FBref / Understat xG, xA, minutes per 90 | Phase 0 |
| `news` | probabili formazioni, infortuni, squalifiche | Phase 3 |
| `mcp_api` | `fantacalcio_mcp.api` as a library | when endpoints are mapped |

Every row carries `source` and `ingested_at`. `poe ingest-all` is idempotent, and
because raw files are immutable the spine can always be rebuilt from scratch.

**Switchover protocol for `mcp_api`:** run it alongside the existing adapter, diff
the outputs, and only then make it the default. Silent disagreement between two
data sources is worse than either being wrong.

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
│   ├── profile.md                  # tactics, module, set-piece & penalty takers
│   └── players/<slug>.md           # sparse: only where prose changes a decision
├── league/
│   ├── participants/<name>.md      # opponent dossiers
│   ├── history/<season>.md
│   └── asta-2026/                  # live log, snapshots, post-mortem
```

Player notes nest under their club because the weekly loop asks club-shaped
questions — one glob returns the tactical profile and every player note together.
They stay *separate files* rather than one `players.md` per club because a team
profile is stable for weeks while a fitness note is stale in four days; merging
them would put one `updated:` stamp over two different rates of change and defeat
the freshness mechanism below. A transfer moves a file, which is correct anyway,
since a note saying "competes with Thuram for the shirt" is wrong the moment he
leaves. `poe kb-move-player` makes it one command. The authoritative team↔player
relation stays in DuckDB; the filesystem merely mirrors it.

`kb/serie-a/teams/<team>/players/` is **sparse by design** — perhaps sixty players
across the league, only those where prose changes a decision: contested rigori,
fitness risk, a tactical role change that invalidates their history. One file per
600 players is the trap that kills projects like this.

**Every document carries front-matter:** `updated`, `ttl`, `confidence`, `source`.
`poe kb-audit` lists what has expired, and `fanta-manager` is instructed to state
low confidence or refuse rather than quietly leaning on a three-week-old probabile
formazione.

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

1. **Project** — expected fantamedia × expected presenze. Weighted multi-season
   history regressed to the role mean, corrected by xG/xA per 90 to catch players
   who scored twelve from six xG and will not repeat it, with a minutes projection
   sourced from the knowledge base rather than the stats.
2. **Mantra-adjust** — role-flexibility option value across the eleven permitted
   modules, plus role scarcity: there are always fewer credible `T` than `Dc`, and
   scarcity is price.
3. **Value above replacement** — the only currency that converts to money. Not
   "how good is he" but "how much better than the best player available for one
   credit in that slot".
4. **Allocate** — the money supply is 8–10 teams × 500 credits. Distribute the
   budget across slots to maximise expected VOR; this is what produces a **max
   price** per player.
5. **Tier** — cluster within role. In a live room, "if I lose him, these three are
   equivalent" is worth more than a ranked list of 600 names.

Output: a stamped run in `valuations`, rendered to `rankings.md` / `.csv` in
`data/exports/`, plus a one-page asta plan with three scenarios (aggressive-attack,
balanced, value-hunting). The final pre-asta ranking is snapshotted into
`kb/league/asta-2026/` as a permanent record, so next year the model's expectations
can be compared against what things actually went for.

The skill's job is to argue with the model on the user's behalf — "it likes him,
but the knowledge base has a fitness flag" — and re-run under stated constraints.

### `fanta-asta` — live auction copilot

The premise: **pre-auction max prices are wrong by minute 40.** If the `Dc` pool is
drying up while four rivals still need three each and have money, the max on the
current `Dc` should rise. Most auctions are lost by treating a printed list as
gospel.

So it is a state machine. Every sale updates remaining credits for every team, the
remaining pool per role, and unfilled slots. Advice is a **dynamic max price** plus
an **opponent pressure** estimate — who else needs this slot and how deep they can
actually go, from dossiers plus observed spending.

Everything mutating state passes through one function, `apply_sale(player, buyer,
price)`, so manual entry, an undo, and a future MCP feed all share one path.

**Division of surfaces.** Credits, slots, pools, dynamic max prices and bid/stop
are pure functions of state — arithmetic, not judgment. Putting a model in front of
them buys seconds of latency to read back numbers a tool already computed. They
belong on an always-visible dashboard at sub-100ms, which frees a *good* model for
the handful of moments that need one: "I lost Bastoni, re-plan my defence budget",
"Marco is desperate for a `Dc` — worth bidding him up?"

The dashboard persists to `asta.sqlite`; the skill reads the same state through the
API, so turning to chat requires retyping nothing.

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

The optimiser solves player→slot matching across every permitted module
simultaneously. If the league runs a **modificatore di difesa**, that single rule
can outweigh individual player quality by rewarding a full same-club defence, so it
is part of the objective function rather than an afterthought.

Output: the XI, the module, an ordered bench that actually covers the right slots,
the two or three close calls with reasoning, and an "if he doesn't start, do this"
contingency.

Then the part everyone skips: **log predicted versus actual after every giornata.**
By November the projections are calibrated against this league's real scoring
rather than August assumptions.

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
procedure is `poe asta-serve`, then open localhost.

**Types are generated, not hand-written.** FastAPI emits OpenAPI;
`openapi-typescript` turns it into TS types. The Pydantic models stay the single
source of truth for the contract.

`poe web-dev` runs Vite and uvicorn together for day-to-day work.

### Requirements specific to a single-shot live event

1. **State persists after every sale**, never held only in browser memory. The
   laptop sleeps, the browser crashes, the page reloads — nothing is lost.
2. **Undo and edit any logged sale.** A price will be mistyped in a loud room.
3. **Zero network dependency.** All data is loaded before leaving the house;
   nothing is fetched during the auction except the optional reconciliation poll.
4. **`poe asta-backup`** — timestamped snapshot of `asta.sqlite` every N sales.
   Copying a file that small costs nothing; a corrupt file two hours in with no
   snapshot is unrecoverable.
5. **A printed tier board** as the paper backstop. A dead laptop must not end the
   auction.

## Testing

- **Optimiser and role model** — unit tests against hand-solved cases: a
  known-optimal XI, a module that is *infeasible* for a given roster (it must say
  so rather than return garbage), a three-role player counted correctly in each.
- **Ingestion** — golden-file tests against committed sample XLSX/HTML fragments.
  This is the one that earns its keep: fantacalcio.it renames columns most Augusts,
  and the desired outcome is a red test, not silently-null quotazioni.
- **Valuation** — invariants rather than exact numbers, because the numbers are
  meant to change: max prices sum sanely against total credits, tiers are monotone,
  every player has at least one role, no negative VOR.
- **Auction state machine** — property tests over sale sequences: credits never go
  negative, roster bounds hold, undo restores exactly the prior state.
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
| Model overconfidence | Max price is a band, not a number; projection uncertainty propagates to the recommendation |
| Auction state desync | `poe asta-fix` corrects a mislogged sale; the advisor works from partial state rather than demanding correctness |
| Scraping blocked or rate-limited | Aggressive caching, dated raw files, polite intervals, and no fetching during the auction |
| API shape changes | Inherited from the MCP: unknown fields survive in `raw`, unknown error codes pass through |

## Phasing

| Phase | Ships | Target |
| --- | --- | --- |
| **0 — spine** | uv workspace, `sync-league`, DuckDB schema, Mantra role model, listone + stats + advanced ingestion, `kb/` bootstrap | 26 Aug |
| **1 — market** | projection, VOR, allocation, tiers, max prices, asta plan; opponent dossiers via `fanta-kb interview` | 31 Aug |
| **2a — asta core** | state machine, advisor, SQLite persistence, undo, backup, CLI entry | 2 Sep |
| **2b — dashboard** | FastAPI + WebSocket + Vite/shadcn UI, reconciliation poll | 4 Sep |
| **3 — manager** | news ingestion, lineup optimiser, weekly loop, post-giornata calibration | from mid-Sep |

The knowledge base is not a phase — it is the spine plus `kb/`, which every phase
reads and writes back into.

**Cut-line, decided now rather than in a panic.** If Phase 2 runs late, capability
drops in this order: the opponent pressure model, then the dynamic max price,
landing on static prices with live credit and slot tracking. That floor is roughly a
day's work and remains genuinely useful. **`asta_log` is never cut** — losing it
costs next season's calibration.

**Rehearsal is mandatory.** Feature-freeze 48 hours before the auction, then run a
full mock: log thirty fake sales, exhaust the budget, mistype a price and undo it,
kill the browser and reload. Single-shot events are lost to unrehearsed tooling far
more often than to bad models.

## Open questions

1. **Eight teams or ten?** The API reports 8 in division A; the stated league is 10.
   Resolve before Phase 1 — the money supply is 8×500 or 10×500, and every max price
   scales with it.
2. **Mantra confirmation and role constraints.** `sroles`, `minrl` and `maxrl` on
   roster settings are unmodelled by the MCP and are the likely home of per-role
   roster bounds. Decode in Phase 0; fall back to the regolamento.
3. **Is the modificatore di difesa active?** `stbdf` / `smod*` / `skodm` on
   `settings/calculate` are raw and unknown. It materially changes both valuation
   and lineup choice, so it must be resolved in Phase 0.
4. **Is there a player-database endpoint?** Unlike roster and market endpoints, the
   listone is not blocked by the auction. Worth thirty minutes of DevTools discovery
   in Phase 0, since it would beat XLSX parsing and yield Mantra roles directly.
   Falls back to `listone_xlsx`.
5. **Roster 23–40 with 500 credits** is a wide band. The intended composition per
   role drives allocation and needs confirming.

## Non-goals

- Automating bids, or acting on the platform during the auction
- Reimplementing Fantacalcio's scoring engine — the MCP reads it from the API
- A multi-user or hosted service; this is one manager on one laptop
- Docker: `uv` pins the toolchain and the databases are files, so a daemon would
  add failure modes on auction night in exchange for reproducibility across
  machines that do not exist
- Serving the dashboard to the room; it would need a read-only view, since nine
  friends should not be reading these max prices
