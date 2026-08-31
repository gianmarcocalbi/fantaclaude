# fantaclaude Phase 2a — asta core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the auction's core without the dashboard or the feed — the state machine that mirrors a FantaAstaLive session as a pure function of its snapshots, the advisor that re-prices the whole board on every state change from a pinned valuation run, the adjustment layer (`data/adjustments.yml`: `value`, `exclude`, `target`), the opponent-pressure estimate from dossiers and observed spending, the atomically written state snapshot (`data/asta-state.json`, copied to `records/` at close), and the `fantaclaude asta` commands that drive all of it offline — so that Phase 2b only has to add transport (SSE, WebSocket, the browser) around one `mutate()` path. Plus the items Phase 1's review carried into 2a: the `exact`/focused decision (made first), the shared re-sync flow and the per-class roster bounds (groundwork), the continuous demand fold, and the cleanup.

**Architecture:** Everything in this phase is pure or importable, and the I/O sits at the edges. `asta/pricing.py` keeps one pricing mode (decision below) and prices every player with himself out of the pool. `asta/state.py` decodes a feed node into a `Snapshot` and set-diffs it against the previous one — adds, undos, cost edits, the lot on the block, a settings change — so the state is a function of the last snapshot and replays are free. `asta/session.py` reads the night's rules from the session (authoritative) or from the run's league settings (offline). `asta/pinned.py` loads a valuation run back from `valuation_runs`/`valuations`/`valuation_prices` with everything the live board needs to reproduce it at minute zero. `asta/adjustments.py` parses, appends (atomically, text-preserving) and resolves the adjustments against the run. `asta/advisor.py` turns state + run + adjustments + mapping into ledgers per team, my `PoolState`, the priced board and the lot's trace; `asta/pressure.py` estimates who else can bid and how deep; `asta/auction.py` is the one owner — `mutate()` applies a change, re-derives the board and notifies listeners. `asta/snapshot.py` writes and reads the state file. `commands/asta.py` and the `fantaclaude asta` group (`board`, `explain`, `replay`, `adjust`, `close`) are the CLI entry, all local, none touching the network.

**Tech Stack:** Python 3.14.7, uv 0.12.5 (workspace), duckdb 1.5.5, typer 0.27.1, pyyaml 6.0.3, numpy 2.5.2, pydantic 2.13.4, poethepoet 0.48.0, pytest 9.1.1, ruff 0.16.4. **No new dependency**: property-style tests use `numpy.random.default_rng` with a fixed seed, as `test_pricing.big_pool` already does.

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` — sections "A second MCP, for the auction" (the tools 2b serves read the state 2a builds), "League configuration is data, not constants", "One database, and the auction is not in it", "Succession, not reconciliation", "Concurrency: one owner of state, and two classes of query", "Live adjustments", "Schema" (the live layer's exception), "`fanta-asta` — live auction copilot" (dynamic max price, one pricing function, the band, why it fits in the latency budget, the algorithm concretely, the pricing module, the live feed's shape, the adapter's rules — set-diff, credits from `picks[]`, session settings authoritative, nicks scrubbed — what the model is for, dossiers loaded not read), "Requirements specific to a single-shot live event" (4, 5, 6, 7), "Testing" (Dynamic max price, One pricing function, Auction state machine, The live feed's diff engine, Replay, Adjustments hot-reloaded and `exclude`'s directional invariant, Crash recovery's `asta-state.json` half), "Phasing" (the 2a row, "Carried into 2a from Phase 1's review", the cut-line), open questions 4, 9 and 10. The Phase 1 plan (`docs/superpowers/plans/2026-08-29-fantaclaude-phase-1-market.md`) defines every interface this plan consumes; the code on `main` at `dd27138` is the truth where the two differ.

**Decisions this plan takes, stated so the user can overturn them before execution** (the spec names the first as 2a's to make; the rest are the plan's readings of the spec, each one sentence):

1. **One pricing mode: the whole board is priced exactly on every state change.** Measured on this laptop on 2026-08-30 with `test_pricing.big_pool` (553 players): the focused-only board 28 ms, the exact board 241 ms, the exact board with the knapsack vectorised over ranks 189 ms (boards byte-identical). A state change arrives once per sale — every thirty seconds at the fastest — so a quarter of a second is invisible to a human-paced auction, while the alternative (a board that jumps for every non-focused player the moment the auction opens, explained in a prose `note`) is the defect the spec named. The approximate mode, `focus` and `exact` are **removed**, not defaulted: a second mode behind one function name is what Phase 1's review objected to. The latency test's budget becomes 500 ms (about twice the measured cost); the spec's "well under 100 ms" described the ~nine-DP focused design and is revised in Task 9's docs commit.
2. **The set-diff lives in the state machine, not in the feed adapter.** `apply_snapshot(state, snapshot)` computes adds, removals and cost edits from two snapshots, so 2b's `ingest/asta_live.py` is transport only (SSE, token refresh, reconnect) and hands decoded nodes to `mutate()`; the diff-engine tests the spec lists under "The live feed" are therefore this plan's (Task 4).
3. **Session settings carry ranges, read as `[classic, mantra]` pairs.** The observed `settings.roles` pairs (`gk: [3, 3]`, `mov: [22, 22]`, `size: [25, 25]`, `game: 2`) are one count per game type, not a min/max — the spec's own reading, confirmable only at the rehearsal. `SessionSettings` therefore stores `(low, high)` per bucket: from the feed `low == high == pair[game - 1]`; from the league's settings row `(minrl[i], maxrl[i])` and `(roster_min, roster_max)`, which is what the pre-auction board was priced under. If the rehearsal shows the pair means something else, one function (`session._pair`) changes.
4. **The live board follows one scenario of the pinned run** (`--scenario`, default the run's first, `balanced`): its targets and budget shares are the starting point, and a `target` adjustment edits them. A run's `config` gains `demand_by_module` (Task 6) so the live board never re-derives the demand and the minute-zero board equals the committed one exactly — for runs recorded before that key exists, the demand is re-derived and the board says so.
5. **The team mapping is an input, never persisted by the server** (spec: the browser remembers it). Offline it comes from `--me` / `--map` on `asta replay`, or from the state file, which records it beside the resolved names so `asta board` after the auction needs no flags.
6. **Opponent pressure is a ceiling per rival and an estimate for the lot**, displayed beside the band and never folded into it: a rival can bid when he has a slot in the lot's bucket and credits beyond one per other open slot; his dossier's `avoids`/`overpays`/`favourite_clubs`/`max_single_share`/`budget_style` move his intent and cap his depth; his observed overpay ratio scales what he is likely to go to. It is Task 8, the first thing the cut-line drops, and nothing else depends on it.
7. **The continuous fold retains `min(1, supply / need)` of a class's demand**, `need` being the league-wide starting slots the modules draw from the class (`per-module demand × teams`), monotone non-increasing across the fixed-point iteration so it terminates; it replaces the `thin_classes` warning (Task 10). On the current listone (no pure `Dd`/`Ds`) it folds exactly what the all-or-nothing version folds, so no committed price moves.
8. **The doctor's single-connection cleanup is done in Task 9**, where three checks are added to it, rather than in Task 11 — touching the file twice for the sake of the spec's ordering would be worse than the ordering.

## Global Constraints

- **Python is 3.14.7**, uv ≥ 0.12.5, workspace root `/Users/grimid3v/Workspace/fantaclaudio`; `fantaclaude.paths` derives every path from the MCP's `workspace_root()` (honours `FANTACALCIO_HOME`). Tests set `FANTACALCIO_HOME` to a `tmp_path` whenever a CLI command touches the filesystem.
- **No test performs network I/O, and nothing in this phase adds a network call.** Every `fantaclaude asta` command is local: it reads `fanta.duckdb` read-only, `data/adjustments.yml`, `data/asta-state.json` and the knowledge base. `rank` (unless `--offline`) and `sync-league` still call the live league API through the one re-sync flow Task 2 builds; tests monkeypatch `fantaclaude.api_client.run_with_api`. No FantaAstaLive connection exists until 2b.
- **The board is a pure function of the feed.** `AuctionState` is rebuilt from the last snapshot alone; applying a snapshot twice is a no-op; any sequence converges on replaying only the last one; nothing local corrects what the admin recorded (spec, "The mirror is faithful"). Credits are derived from `picks[]`, never read from `teams[].currentBudget`.
- **One pricing function, one mode.** `price_board(state, cfg)` prices every player with himself out of the pool. The pre-auction board of a run and the live board of an empty auction under that run's league settings are the same computation, and Task 6's `test_the_live_board_at_minute_zero_reproduces_the_pinned_board` asserts equality band for band; it must stay green in every later task.
- **`pricing.py` stays pure**: no I/O, no clock, no logging; it imports nothing from the package but `fantaclaude.values`. The other `asta/` modules may import the model, the kb and the league layers; only the pricing function is bounded this way.
- **Adjustments carry a reason, resolve loudly, and never crash a refresh.** An unresolved or ambiguous `player` is reported in the layer's `problems` and is inert; a malformed file is an `AdjustmentsError` the caller reports while the previous layer stands. The file is appended text-first (comments survive) and replaced atomically (temp file, `fsync`, `os.replace`).
- **Every file the auction writes is written atomically** through `fantaclaude.atomic.write_atomic` — `data/asta-state.json`, `data/adjustments.yml`, the `records/asta/` copy — because from the moment the admin closes FantaAstaLive until the transfer is confirmed the snapshot is the only record of what the room paid.
- **Email addresses never reach a snapshot, a state file, a tool result or a stored payload.** Team labels are scrubbed at `parse_snapshot` (an `@`-shaped label becomes `team <id>`); dossiers already refuse them; tests of the scrubber use synthetic addresses in code, never in a committed fixture.
- **Nothing hardcodes a league rule.** Budgets, team counts, the goalkeeper and roster bounds come from the session node or the run's `league_settings` row; module demand and hard minimums from `modules.yml` through the run; the pricing knobs from the run's stored `config["pricing"]`, never from the working tree's `pricing.yml` (the live board must reproduce the committed run, not the file as it is today).
- **`records/` files are never rewritten**; `records/asta/<session>-<stamp>.json` is written once at close and refused if it exists with different content. `data/` stays gitignored; `data/adjustments.yml` is mine and stays after the auction; `data/asta-state.json` is deleted by 2b's `verify-transfer` (open question 9), never by anything here.
- **Exit codes are the contract**: `0` ok, `1` unexpected error, `2` usage (a `--me`/`--map` that names no team, an ambiguous or unknown player in `adjust`/`explain`, a bad `--type`/`--factor`/`--class`/`--scenario`), `3` not ready (no database, no valuation run, the newest run superseded and no `--run`, `adjustments.yml` malformed, the state file malformed, `league.yml` malformed), `4` conflict (`league.yml` vs the API, from a re-sync). `ruff check core` is clean on `main` and must stay clean; after writing a task's files run `uv run ruff check --fix core` once (it only reorders and wraps imports), then `uv run ruff check core` must be silent. `typer.Option` defaults on `list[...]` parameters are module-level singletons (B008), as in `cli/app.py`.
- **DuckDB is single-process for writes.** Every `asta` command opens the database read-only, so any number of them may run beside a (2b) server that also holds it read-only; `rank` still opens read-write once, after the re-sync.
- **Commit messages document the change, never the tool.** No `Claude-Session:` trailer, no `Co-Authored-By: Claude`, no "Generated with Claude Code". One commit per task; the spec revision in Task 9 is one further deliberate `docs(spec):` commit, as CLAUDE.md allows for a revision.
- **This plan lives on the branch `feat/phase-2a-asta-core`** (created 2026-08-30 from `main` at `dd27138`). It is committed once, when finished; nothing is pushed until the phase is done or the user says so.

## Source facts observed on 2026-08-30

Recorded because the state machine and the session reader are written against them; every number below was measured on this machine, read from a committed fixture, or read from the gitignored capture — never from memory.

**Baseline on `main` (`dd27138`)**: `uv run poe test` → 111 passed (MCP) and 368 passed (core); `uv run ruff check core` → clean. The core counts stated at the end of Tasks 1–8 were measured on 2026-08-30 (their code was run in a scratch worktree while this plan was drafted, a verification the user then stopped as double work); the counts in Tasks 9–11 are estimates. Either way the executor replaces the number with the one measured.

**The pricing cost** (`test_pricing.big_pool`, 553 players, 11 classes, budget 500, `PricingConfig()` defaults, three runs, minimum): focused-only board 28 ms; exact board 241 ms; exact board with `_curve` vectorised over ranks 189 ms. The vectorised exact board equals the old exact board on every band of the big pool, the small pool, a roster-max-8 pool and an owned-keeper pool; `buy_value` differs in the 13th significant digit on 27 non-candidate players of the big pool, from two additions associated the other way round.

**The FantaAstaLive capture** (`captured/fantaastalive-state-2026-08-23.json` — the app's *local* state, pre-auction, JSON-encoded twice: `json.loads(json.load(f))`; the top level is `{"_users": {"-1": {...}}, "version": 1, "_sessions": {"FA-nri-okm": null}}`). Under `_users["-1"]`: `settings` = `{PlayerStack: "default", beatRaise: 1, budget: 500, buzzAction: "raise", buzzer: false, buzzerKit: "blue", concurrencyTimeLimit: 100, countdownInterval: 2000, countdownSeconds: 10, countdownType: "auction", game: 2, listType: "default", marketType: 0, minimumBid: {type: "fixed", value: 1}, participants: 2, playerValueType: "fmv", playersCallConfig: {type: "default"}, roles: {atk: [6, 6], def: [8, 8], gk: [3, 3], mid: [8, 8], mov: [22, 22], size: [25, 25]}, selfRaise: true, style: "live", type: "default"}`; `options.draft` = `{firstPickIndex: 1, pickOrderType: "default", maxAheadPicks: 1, rosterValueType: "current"}`; `options.bids` repeats the settings; `teams` = two entries `{color, completed: false, connection: {active, guest, host, label: "host" | "Claude", peerId, uid}, currentBudget: 500, fullfilled: false, icon, id: 0 | 1, maxOffer: 476, missingPlayers: {gk: 3, mov: 22}, picksCount: 0, rosterValue: 0}`; `players` = 539 rows `{index, id, name, fullName, zone: {classic: "atk", mantra: "mov"}, roleIndex, roles: ["pc"] (lower-case Mantra codes), prices: [35, 35, 35, 35], price: 35, marketValues, team: "Inter", championship, foot, birthplace, birthYear, birthday, ageGroup, image, gone: false, stats}` — `id` is the listone id (`2764` is Martinez L., `price 35` = his `acsma`); `picks`, `bids-log`, `pick-order` are empty lists; `nick` = `"Claude"`. Note `mov = def + mid + atk = 22` and `size = gk + mov = 25`: the pairs are exact counts, one per game type, and this is the default FantaAstaLive roster, not the league's (2–6 goalkeepers, 23–40 players). **The session node** (`/sessions/<code>/state`, spec) carries `picks[] {playerId, teamId, cost, value, index, timestamp}`, `lastPick`, `selectedPlayerId`, `turnTeamId`, `status`, `locked`, `teams[]`, `settings`, `options`, `pickOrder`, `hostId`, `playerListHash`; no capture of it with picks exists yet, so Task 4's fixture is the capture's settings and teams with a scripted pick sequence, generated by `_extract_asta.py`.

**The league's bounds** (`mcp/fantacalcio/tests/fixtures/roster_settings.json`, the same values as the live snapshot): `budg 500`, `msltc 23`, `xsltc 40`, `sroles 2`, `minrl [2, 21]`, `maxrl [6, 34]`; `league_profile.n_s 8`. `RunContext` reads `minrl[0]`/`maxrl[0]` as the goalkeeper bounds; the outfield pair `[21, 34]` is a group bound the pricing DP expresses only through the roster bounds (with 2 keepers, 23–40 players means 21–38 outfield; the API's 34 binds only above 36 players) — the ledger counts it exactly, the pricer approximates it, and the difference is inside the roster the DP never fills.

**The fixtures the tests reuse**: `core/tests/fixtures/listone_sample.json` (17 players over 8 clubs, ids `3`, `5841`, `2120`, `254`, `5877`, `2764`, `2194`, `2423`, `2097`, `6052`, `2517`, `536`, `309`, `152`, `2297`, `791`, `2640`; `Por` are `3`, `5841`, `2297`); `test_valuation.seeded(tmp_path, fixture_json, mcp_fixture_json)` builds the ready workspace with profiles and a back season for six players, and `test_valuation.run(tmp_path)` returns a `ValuationRun` under `PREFS = {"risk_appetite": "balanced", "max_budget_share_per_role": {}, "excluded_clubs": [], "target_composition": {"Por": 2}}`; `test_rank_cli._workspace` adds `pricing.yml`, a three-scenario `preferences.yml` and a `league.yml`. On that fixture a run prices 17 players, 8 teams × 500 credits, giornata 1 of season 21, and `test_run_valuation_projects_prices_and_stamps` pins the shape.

---

## File Structure

| file | responsibility |
| --- | --- |
| `core/src/fantaclaude/values.py` | `+ json_safe` — the one scrubber for -inf/inf/nan (Task 1) |
| `core/src/fantaclaude/asta/pricing.py` | one exact mode, `_curve` vectorised over ranks, `focus`/`exact` removed (Task 1); `PoolState.class_min`/`class_max` (Task 3) |
| `core/src/fantaclaude/cli/app.py` | `_league_yml_or_exit`, `_fetch_league` — the one re-sync flow (Task 2); the `asta` group (Task 9) |
| `core/src/fantaclaude/commands/rank.py` | `rank(..., sync=)`, `RankReport.sync` (Task 2) |
| `core/src/fantaclaude/analysis/valuation.py` | `RunContext.class_min`/`class_max` (Task 3); `config["demand_by_module"]` (Task 6); `config["demand_kept"]` and the fold warning (Task 10); `json_safe` (Task 11) |
| `core/src/fantaclaude/asta/session.py` | `SessionSettings`, `session_from_feed`, `session_from_league`, `league_bounds`, `compare` (Task 4) |
| `core/src/fantaclaude/asta/state.py` | `Pick`, `Team`, `Snapshot`, `parse_snapshot`, `read_snapshots`, `AuctionState`, the events, `apply_snapshot` (Task 4) |
| `core/tests/fixtures/_extract_asta.py`, `asta_session_sample.jsonl` | the capture's settings and teams with a scripted pick sequence (Task 4) |
| `core/src/fantaclaude/atomic.py` | `write_atomic` (Task 5) |
| `core/src/fantaclaude/asta/adjustments.py` | `Adjustment`, `parse_adjustments`, `load_adjustments`, `append_adjustment`, `AdjustmentLayer`, `resolve`, `apply_layer` (Task 5) |
| `core/src/fantaclaude/asta/pinned.py` | `PinnedPlayer`, `PinnedRun`, `newest_run_id`, `load_pinned_run` (Task 6) |
| `core/src/fantaclaude/asta/advisor.py` | `TeamMapping`, `Ledger`, `Board`, `build_ledgers`, `build_pool_state`, `derive` (Task 6); pressure wired in (Task 8) |
| `core/src/fantaclaude/asta/auction.py` | `Auction.mutate()` — the one owner of live state (Task 6) |
| `core/src/fantaclaude/asta/snapshot.py` | `render_state`, `write_state`, `read_state`, `copy_to_records` (Task 7) |
| `core/src/fantaclaude/asta/pressure.py` | `PressureConfig`, `Bidder`, `Pressure`, `pressure_for`, `pressure_board` (Task 8) |
| `core/src/fantaclaude/paths.py` | `+ adjustments_path()`, `asta_state_path()` (Task 9) |
| `core/src/fantaclaude/commands/asta.py` | `open_run`, `load_layer`, `board_report`, `explain_report`, `replay_report`, `adjust`, `close_auction` — importable (Task 9) |
| `core/src/fantaclaude/commands/doctor.py` | one read-only connection per run; `+ pinned_run`, `adjustments`, `asta_state` checks (Task 9) |
| `.claude/skills/fanta-asta/SKILL.md`, `core/README.md`, `site/docs/cli.md`, `records/README.md`, `CLAUDE.md`, the spec | the 2a contract, the docs, the decision recorded (Task 9) |
| `core/src/fantaclaude/model/demand.py` | `FoldedDemand`, the continuous `satisfiable_demand`, `thin_classes` removed (Task 10) |
| `core/src/fantaclaude/league/settings.py`, `yamlio.py`, `kb/audit.py`, `kb/profiles.py`, `kb/notes.py`, `kb/participants.py`, `analysis/history.py`, `analysis/exports.py`, `commands/rank.py`, `asta/pricing_config.py`, `model/d_factor.py`, `league/league_yml.py` | the cleanup (Task 11) |
| `core/tests/test_pricing.py`, `test_rank_cli.py`, `test_sync_league.py`, `test_valuation.py`, `test_session.py`, `test_state.py`, `test_adjustments.py`, `test_atomic.py`, `test_pinned.py`, `test_advisor.py`, `test_auction.py`, `test_snapshot.py`, `test_pressure.py`, `test_asta_cli.py`, `test_doctor.py`, `test_demand.py`, `test_yamlio.py`, `test_values.py`, `test_league_settings.py`, `test_kb_audit.py`, `test_history.py` | one module per source module |

---

### Task 1: One pricing mode — the `exact`/focused decision

**Files:**
- Modify: `core/src/fantaclaude/values.py`, `core/src/fantaclaude/asta/pricing.py`, `core/src/fantaclaude/analysis/valuation.py:12-19,544,601`
- Test: `core/tests/test_pricing.py`, `core/tests/test_valuation.py:139`, `core/tests/test_values.py`

**Interfaces:**
- Consumes: `PoolState`, `PricingConfig`, `PoolPlayer`, `OwnedPlayer`, `Band`, `BoardPricing` as Phase 1 defined them; `model.demand.rank_weights`, `hard_minimums`, `module_demand`.
- Produces: `price_board(state: PoolState, cfg: PricingConfig) -> BoardPricing` — no `focus`, no `exact`; `PlayerPrice(player_id, role_class, band, expected_price, rank_weight, walk_value, buy_value)` — no `exact` field; `explain(board, player_id) -> dict` without `exact`/`note`, JSON-safe; `values.json_safe(value) -> value` (recursive, tuples to lists, non-finite floats to `None`); `record_run` writes `True` into `valuation_prices.exact`; `test_pricing.LATENCY_BUDGET = 0.5`.

The decision and its evidence are in the plan header (decision 1). What changes in the algorithm: the knapsack updates every rank in one numpy operation per player (the right-hand side reads the tables as they stood before him, which the descending loop over `j` used to guarantee one rank at a time); a candidate is priced from his own leave-one-out knapsack, as `exact=True` did; a player the DP never considered is priced from the class's shared hole curves, which are exact for him because he was in no table — the old approximate branch, renamed `_class_holes` and no longer an approximation of anything; and the binary search always splits the credits between the class and the rest point by point (`_column`), so there is one search, not a search and a lookup.

- [ ] **Step 1: Write the failing tests**

Replace `core/tests/test_pricing.py` with:

```python
import json
import time

import numpy as np
import pytest
from fantaclaude.asta.pricing import (
    Band,
    BoardPricing,
    OwnedPlayer,
    PlayerPrice,
    PoolPlayer,
    PoolState,
    PricingConfig,
    explain,
    price_board,
)
from fantaclaude.asta.pricing_config import PricingConfigError, load_pricing_config
from fantaclaude.model.demand import (
    ROLE_CLASSES,
    hard_minimums,
    module_demand,
    rank_weights,
)
from fantaclaude.model.modules import load_modules

CFG = PricingConfig()
WEIGHTS = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=CFG.bench_weight)
HARD = hard_minimums(load_modules())


def player(pid, cls, value, quot, spread=0.25):
    return PoolPlayer(pid, f"p{pid}", cls, value * (1 - spread), value, value * (1 + spread), quot)


def small_pool():
    """Values in remaining-season fantapunti, quotazioni as the listone would price them."""
    spec = {"Por": [(120, 12), (60, 4), (20, 1)], "Dd": [(90, 8), (40, 2)], "Ds": [(90, 8), (40, 2)],
            "Dc": [(150, 20), (120, 12), (90, 8), (60, 4), (30, 1)], "E": [(110, 10), (70, 5), (30, 1)],
            "M": [(100, 9), (60, 4), (30, 1)], "C": [(130, 14), (90, 8), (60, 4), (30, 1)],
            "W": [(120, 12), (80, 6), (30, 1)], "T": [(140, 16), (80, 6), (30, 1)],
            "A": [(160, 22), (110, 10), (60, 4), (30, 1)], "Pc": [(220, 36), (150, 20), (80, 6), (30, 1)]}
    pool, pid = [], 100
    for cls, entries in spec.items():
        for value, quot in entries:
            pool.append(player(pid, cls, value, quot))
            pid += 1
    return tuple(pool)


def state(pool=None, **kw):
    base = {"credits": 500, "market_credits": 4000, "pool": pool or small_pool(), "weights": WEIGHTS,
            "hard_minimums": HARD, "roster_min": 1, "roster_max": 40, "min_goalkeepers": 2, "max_goalkeepers": 6}
    base.update(kw)
    return PoolState(**base)


def by_class(pool, cls):
    return [p for p in pool if p.role_class == cls]


def test_bands_are_ordered_and_bounded():
    board = price_board(state(), CFG)
    assert isinstance(board, BoardPricing) and set(board.prices) == {p.player_id for p in small_pool()}
    for price in board.prices.values():
        assert isinstance(price, PlayerPrice) and isinstance(price.band, Band)
        assert 0 <= price.band.p25 <= price.band.p50 <= price.band.p75 <= board.budget
        assert price.expected_price >= 1
    assert board.reserve == 0 and board.budget == 500
    assert sum(board.credits_by_class.values()) <= 500 and 3 <= sum(board.composition.values()) <= 40
    assert board.slot_price == 0.0
    assert board.composition["Por"] >= 2 and board.composition["Dc"] >= 2                # the hard minimums hold
    d = board.to_dict()
    assert d["inflation"] == board.inflation and d["prices"][str(100)]["band"]["p50"] == board.prices[100].band.p50


def test_inflation_is_self_calibrating_and_clamped():
    pool = small_pool()
    quot = sum(p.quotazione for p in pool)                    # every class has <= 30 players, so all are credible
    assert price_board(state(market_credits=quot), CFG).inflation == pytest.approx(1.0)
    assert price_board(state(market_credits=quot * 10), CFG).inflation == CFG.inflation_ceiling
    assert price_board(state(market_credits=quot // 10), CFG).inflation == CFG.inflation_floor
    board = price_board(state(market_credits=quot), CFG)
    assert all(board.expected_prices[p.player_id] == max(1, p.quotazione) for p in pool)


def test_scarcity_never_lowers_the_price_and_exhaustion_drives_it_to_the_credits_available():
    pool = small_pool()
    dc = by_class(pool, "Dc")
    target = dc[1]                                              # value 120
    owned = (OwnedPlayer(1, "Dc", 150.0),)                      # one Dc owned: one more needed by the hard minimum
    prices = []
    for keep in (dc, dc[1:], dc[1:3], [target]):
        rest = tuple(p for p in pool if p.role_class != "Dc") + tuple(keep)
        prices.append(price_board(state(rest, owned=owned), CFG).prices[target.player_id].band.p50)
    assert prices == sorted(prices), prices                     # shrinking the Dc pool never lowers his price
    # only he is left and one Dc is required: walking away is infeasible, so the price is every credit
    # not needed by the other hard slots -- the two cheapest goalkeepers at their expected prices
    last = price_board(state(tuple(p for p in pool if p.role_class != "Dc") + (target,), owned=owned), CFG)
    por_costs = sorted(last.expected_prices[p.player_id] for p in by_class(pool, "Por"))
    assert last.prices[target.player_id].band.p50 == 500 - sum(por_costs[:2])
    assert last.prices[target.player_id].walk_value == float("-inf")


def test_excluding_a_player_raises_everyone_else_at_his_class_and_removes_him():
    pool = small_pool()
    dc = by_class(pool, "Dc")
    before = price_board(state(), CFG)
    after = price_board(state(excluded=frozenset({dc[0].player_id})), CFG)
    assert dc[0].player_id not in after.prices
    for p in dc[1:]:
        assert after.prices[p.player_id].band.p50 >= before.prices[p.player_id].band.p50
    # weakly for the class, strictly for the man who inherits his slot: without the best Dc the second is worth more
    assert after.prices[dc[1].player_id].band.p50 > before.prices[dc[1].player_id].band.p50
    assert all(after.prices[p.player_id].band.p50 >= 0 for p in pool if p.role_class != "Dc")


def test_owned_players_consume_ranks_and_bounds():
    pool = small_pool()
    por = by_class(pool, "Por")
    full = price_board(state(owned=tuple(OwnedPlayer(i, "Por", 50.0) for i in range(CFG.max_goalkeepers))), CFG)
    assert all(full.prices[p.player_id].band == Band(0, 0, 0) for p in por)          # no goalkeeper slot left
    assert full.composition["Por"] == 0
    plain = price_board(state(), CFG)
    assert plain.prices[por[0].player_id].rank_weight == WEIGHTS["Por"][0]
    one = price_board(state(owned=(OwnedPlayer(1, "Por", 120.0),)), CFG)
    assert one.prices[por[0].player_id].rank_weight == WEIGHTS["Por"][1]              # he would be my second keeper


CLIFF = (0.939, 0.12, 0.06)                     # the shape the real demand gives A, W and Dc: a starter and two benches


def cliff_state(values=(230.0, 222.0, 207.0, 197.0), quots=(30, 28, 25, 23), **kw):
    pool = tuple(player(200 + i, "A", v, q, spread=0.05) for i, (v, q) in enumerate(zip(values, quots, strict=True)))
    base = {"credits": 500, "market_credits": 500, "pool": pool, "weights": {"A": CLIFF}, "hard_minimums": {},
            "roster_min": 1, "roster_max": 40, "min_goalkeepers": 0, "max_goalkeepers": 6}
    base.update(kw)
    return PoolState(**base)


def test_a_player_who_is_not_his_classs_best_still_has_a_price():
    """Regression. The buy branch used to seat the bought player at rank 1 by
    construction while the walk branch let the class's genuine best sit there,
    so buy - walk was negative for everyone but that best whenever the weights
    are cliff-shaped -- and on the real board 540 of 553 players priced at 0.
    Which rank he carries is the DP's decision: a second striker worth 222
    against a best of 230 is bought as the bench man, not as the starter."""
    board = price_board(cliff_state(), CFG)
    prices = [board.prices[200 + i].band.p50 for i in range(4)]
    assert all(x > 0 for x in prices[:3]), prices               # the class has three ranks and they were 0, 0 before
    assert prices[3] == 0, prices                               # a fourth striker fills no rank: he really is worth nothing
    assert prices == sorted(prices, reverse=True), prices
    second = board.prices[201]
    assert second.rank_weight == CLIFF[1] and second.buy_value >= second.walk_value    # bought as the first bench


def test_a_max_price_is_non_increasing_down_a_classs_value_ranking():
    """A worse player is never worth more: the property the all-zero board
    satisfied vacuously, checked class by class on a 553-player pool -- which
    has more players per class than the DP takes as candidates, so both ways
    of pricing a man (his own knapsack, or the class's curves for a player no
    table holds) are on the same ranking."""
    board = price_board(state(big_pool(), roster_min=23), CFG)
    ranked: dict[str, list] = {}
    for p in sorted(big_pool(), key=lambda p: (-p.value_p50, p.player_id)):
        ranked.setdefault(p.role_class, []).append(board.prices[p.player_id].band.p50)
    for cls, prices in ranked.items():
        assert len(prices) > CFG.candidates_per_class, cls
        assert prices == sorted(prices, reverse=True), (cls, prices[:12])
        assert prices[1] > 0 and prices[2] > 0, (cls, prices[:12])            # the #2 and #3 of a populated class
    assert sum(1 for p in board.prices.values() if p.band.p50 > 0) > len(board.prices) // 2


def test_every_player_is_priced_with_himself_out_of_the_pool():
    """One mode (Phase 2a's decision): a player's walk-away plan never counts
    him. Removing a candidate from the pool must therefore leave every other
    price in his class where it was -- they were already priced without him
    in the walk branch -- except where his absence changes what the class can
    field at all, which is the scarcity effect and moves prices up, never down."""
    pool = small_pool()
    pc = by_class(pool, "Pc")
    before = price_board(state(), CFG)
    without = price_board(state(tuple(p for p in pool if p.player_id != pc[0].player_id)), CFG)
    for p in pc[1:]:
        assert without.prices[p.player_id].band.p50 >= before.prices[p.player_id].band.p50
    # and his own price is what the board said it was when he was on it: the
    # board is one computation, not a lot-by-lot re-solve that could disagree with itself
    again = price_board(state(), CFG)
    assert again.prices[pc[0].player_id] == before.prices[pc[0].player_id]


def test_one_pricing_function_is_deterministic():
    a = price_board(state(), CFG).to_dict()
    b = price_board(state(), CFG).to_dict()
    assert a == b


def test_a_target_is_soft_and_a_departure_is_reported():
    plain = price_board(state(), CFG)
    nudged_weights = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=CFG.bench_weight,
                                  targets={"W": 3}, target_weight=CFG.target_weight)
    nudged = price_board(state(weights=nudged_weights, targets={"W": 3}), CFG)
    assert nudged.composition["W"] >= plain.composition["W"] and nudged.targets_departed == ()
    impossible = price_board(state(weights=nudged_weights, targets={"W": 9}), CFG)
    assert impossible.targets_departed == ("W",) and impossible.completion_value > float("-inf")


def test_a_budget_share_caps_a_class():
    capped = price_board(state(class_budget_share={"Pc": 0.1}), CFG)
    assert capped.credits_by_class["Pc"] <= 50
    assert capped.prices[by_class(small_pool(), "Pc")[0].player_id].band.p50 <= 50


def test_the_reserve_keeps_one_credit_per_unfilled_slot():
    """Reserving credits shrinks the budget, which can buy fewer players,
    which needs a larger reserve: the board is only coherent if the reserve
    it prints covers the slots the completion it prints leaves unfilled."""
    filled = price_board(state(roster_min=23), CFG)
    assert filled.reserve == 0 and filled.budget == 500          # the completion already reaches the minimum
    for roster_min in (25, 30, 35, 40):
        board = price_board(state(roster_min=roster_min), CFG)
        bought = sum(board.composition.values())
        assert board.reserve > 0, roster_min                      # the completion falls short of the minimum
        assert board.reserve >= roster_min - bought, (roster_min, board.reserve, bought)
        assert board.budget == 500 - board.reserve
        assert all(p.band.p75 <= board.budget for p in board.prices.values())


def test_the_roster_maximum_binds_through_a_slot_price():
    """Nothing in the demand bounds the roster at the league's maximum, so a
    tight maximum is enforced by charging every player a slot price -- the
    shadow price of a roster place -- found by bisection until the
    completion fits; a loose maximum costs nothing."""
    loose = price_board(state(roster_max=40), CFG)
    assert loose.slot_price == 0.0
    tight = price_board(state(roster_max=8), CFG)
    assert tight.slot_price > 0 and sum(tight.composition.values()) <= 8
    assert tight.composition["Por"] >= 2 and tight.composition["Dc"] >= 2         # the hard minimums still hold
    assert all(0 <= p.band.p25 <= p.band.p50 <= p.band.p75 <= tight.budget for p in tight.prices.values())
    assert explain(tight, by_class(small_pool(), "Pc")[0].player_id)["slot_price"] == tight.slot_price


def test_a_pool_class_the_weights_do_not_know_is_refused():
    bad = small_pool() + (player(999, "Xy", 50, 3),)
    with pytest.raises(ValueError, match="Xy"):
        price_board(state(bad), CFG)


def test_a_board_is_valid_json_even_where_a_branch_is_impossible():
    """-inf is a real answer inside -- no completion exists without him, or
    his class has no slot left -- and JSON has no such number, so a board
    reports the impossible branch as null rather than -Infinity, and so does
    the trace explain() hands the model."""
    saturated = price_board(state(owned=tuple(OwnedPlayer(i, "Por", 50.0) for i in range(CFG.max_goalkeepers))), CFG)
    por = by_class(small_pool(), "Por")[0]
    assert saturated.prices[por.player_id].buy_value == float("-inf")          # inside, the branch is impossible
    d = json.loads(json.dumps(saturated.to_dict(), allow_nan=False))           # outside, it is null
    assert d["prices"][str(por.player_id)]["buy_value"] is None
    assert d["prices"][str(por.player_id)]["walk_value"] == saturated.completion_value
    assert json.loads(json.dumps(explain(saturated, por.player_id), allow_nan=False))["buy_value"] is None
    keeperless = price_board(state(tuple(p for p in small_pool() if p.role_class != "Por")), CFG)
    assert keeperless.completion_value == float("-inf")                        # two goalkeepers are a hard minimum
    assert json.loads(json.dumps(keeperless.to_dict(), allow_nan=False))["completion_value"] is None


def test_explain_reads_back_the_trace():
    pool = small_pool()
    pc = by_class(pool, "Pc")[0]
    board = price_board(state(), CFG)
    trace = explain(board, pc.player_id)
    assert trace["player_id"] == pc.player_id and trace["band"] == board.prices[pc.player_id].band.to_dict()
    assert trace["inflation"] == board.inflation and trace["composition"] == board.composition
    assert trace["slot_price"] == board.slot_price
    if trace["band"]["p50"] > 0:                                               # at his p50 max price, buying is worth at least walking
        assert trace["walk_value"] <= trace["buy_value"] + 1e-9
    with pytest.raises(KeyError):
        explain(board, 424242)


def big_pool(n=553, seed=7):
    rng = np.random.default_rng(seed)
    pool = []
    for pid in range(n):
        cls = ROLE_CLASSES[pid % len(ROLE_CLASSES)]
        value = float(np.exp(rng.normal(4.3, 0.6)))            # ~ 75 fantapunti, long right tail
        quot = int(max(1, min(40, round(value / 6 + rng.normal(0, 2)))))
        pool.append(player(pid, cls, value, quot))
    return tuple(pool)


LATENCY_BUDGET = 0.5


def test_a_full_board_re_prices_inside_the_latency_budget():
    """The spec's constraint that keeps the model out of the loop, at the
    budget Phase 2a set when it chose one exact mode: the whole 553-player
    board -- every player priced with himself out of the pool -- must re-price
    in under half a second. Measured 2026-08-30 on the auction laptop: 189-241
    ms per board (the focused-only board this replaced took 28 ms), so the
    budget holds with about twice the headroom. A state change arrives once
    per sale, which is once every half a minute at the fastest; a quarter of a
    second on that cadence is what a human-paced auction never notices."""
    st = state(big_pool(), roster_min=23)
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        board = price_board(st, CFG)
        timings.append(time.perf_counter() - start)
    assert min(timings) < LATENCY_BUDGET, timings
    assert len(board.prices) == 553


def test_pricing_yml_is_loaded_and_validated(tmp_path, monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import pricing_yml_path

    assert load_pricing_config(pricing_yml_path()) == PricingConfig()          # the committed file is the defaults
    path = tmp_path / "pricing.yml"
    path.write_text("bench_weight: 0.2\nmax_per_class: 5\n")
    cfg = load_pricing_config(path)
    assert cfg.bench_weight == 0.2 and cfg.max_per_class == 5 and cfg.inflation_ceiling == 2.5
    # `.nan` / `.inf` are floats, and nothing range-checks a knob, so they used
    # to load: bench_weight NaN makes every rank weight NaN and every max price
    # with it, and neither survives the canonical_json that model_hash and the
    # stored config both go through.
    for bad in ("bench_weight: heavy\n", "unknown_knob: 1\n", "- a list\n", "max_per_class: 2.5\n",
                "bench_weight: .nan\n", "inflation_ceiling: .inf\n"):
        path.write_text(bad)
        with pytest.raises(PricingConfigError):
            load_pricing_config(path)
```

Append to `core/tests/test_values.py`:

```python


def test_json_safe_scrubs_non_finite_floats_at_any_depth():
    import json
    import math

    from fantaclaude.values import json_safe

    value = {"a": -math.inf, "b": [1.0, math.nan, (2, math.inf)], "c": {"d": 3}, "e": "x", "f": True}
    safe = json_safe(value)
    assert safe == {"a": None, "b": [1.0, None, [2, None]], "c": {"d": 3}, "e": "x", "f": True}
    json.dumps(safe, allow_nan=False)                     # what a DuckDB JSON column and a tool result both need
    assert json_safe(1.5) == 1.5 and json_safe(None) is None
```

In `core/tests/test_valuation.py`, line 139, replace `assert set(board.prices) == set(by_id) and all(p.exact for p in board.prices.values())` with `assert set(board.prices) == set(by_id)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_pricing.py core/tests/test_values.py -q`
Expected: FAIL — `ImportError: cannot import name 'json_safe'` from `test_values`; in `test_pricing` every test that calls `price_board(...)` still passes against the old code except `test_every_player_is_priced_with_himself_out_of_the_pool` (the old default was the approximate board: `again.prices[...] == before.prices[...]` holds but the class's other prices are *not* monotone under removal without `exact=True`) and `test_a_board_is_valid_json_even_where_a_branch_is_impossible` (`explain()` returned `-inf` for `buy_value`, and `json.dumps(..., allow_nan=False)` raises `ValueError`).

- [ ] **Step 3: Add `json_safe` to `values.py`**

Append to `core/src/fantaclaude/values.py`:

```python


def json_safe(value: Any) -> Any:
    """The same value with every non-finite float -- -inf, inf, nan -- replaced
    by None, at any depth; tuples come back as lists, as JSON would have them.

    A -inf is a real answer inside the pricing (no completion exists without
    this player; his class has no slot left) and not a number JSON has, and
    DuckDB's JSON column refuses it. One scrubber for the one rule, used by
    every to_dict and explain that a board or a run is written from -- it used
    to be two private copies, and explain() applied neither."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value
```

- [ ] **Step 4: Rewrite `pricing.py` with one mode**

Replace `core/src/fantaclaude/asta/pricing.py` with:

```python
"""The one pricing function: a max price is the indifference point between
buying a player and the best completion without him.

Phase 1 calls this with the full listone and pre-auction expected prices;
Phase 2 calls it with the live remaining pool. Same function, so the board
cannot jump when the auction opens (spec, "One pricing function").

State: my credits, the pool, what I already own, the demand weights per
role class and rank (model/demand.py), the hard minimums, the league's
bounds. V(c) is the value of the best completion of my roster with c
credits at the pool's expected prices; for a player p offered at x,
buy(x) = max over the rank a he could take of w_a * value(p) +
V_{-p,-a}(C - x), and walk = V_{-p}(C) -- in both branches p leaves the
pool: if I do not buy him, someone else does. He is not seated at his
class's first rank by construction: which rank he carries depends on how
many better players the completion also buys, so it is the DP's decision,
and taking the maximum over the ranks is how it makes it. The max price is
the largest x with buy(x) >= walk, found by binary search since every
V_{-p,-a} is monotone in credits and so is their maximum; solved at p25,
p50 and p75 of value(p), which is the band.

The machinery (spec, "The algorithm, concretely"): expected prices are
quotazione x inflation, inflation = credits still on the market over the
quotazioni of the credible pool, clamped; per class a knapsack over the
top candidates gives f_r(j, c), the best weighted value of exactly j
players for at most c credits, the j-th chosen (in value order) carrying
the j-th rank weight; the classes combine by max-plus convolution; a
class's curve with one rank left free is what the buy branch completes
from, one such curve per rank. Every player is priced with himself removed
from his class's curve -- one knapsack per candidate, and the class's own
curves for a player the DP never considered, who leaves nothing behind when
he leaves the pool. There is one mode, decided in Phase 2a (2026-08-30):
an earlier version priced only the lot on the block exactly and the rest
of the board from full-pool tables, so the committed pre-auction board and
the live board disagreed for every other player the moment the auction
opened. The exact board re-prices 553 players in about a quarter of a
second on the auction laptop, which a human-paced auction never notices,
so the approximation was removed rather than explained. Composition is a
decision variable: the DP chooses how many of each class within the ranks
the demand gives it; a target only raises weights (a soft prior), and a
departure from it is reported. A completion that cannot meet a hard
minimum is worth -inf, which is what drives the last needed Dc's price to
the credits available. A class budget share caps both what the completion
may spend on the class and what any of its players may be priced at. One
credit is reserved for every roster slot the completion leaves unfilled,
iterated to the running maximum so the reserve and the completion it pays
for agree; when the completion would exceed the roster maximum, a slot
price (the shadow price of a roster place, found by bisection) is charged
per player until it fits, and reported.

Pure: no I/O, no clock, numpy inside, frozen dataclasses at the edges.
Every tunable is in PricingConfig, loaded from pricing.yml elsewhere. A
-inf inside is an impossible branch, and `to_dict` reports it as None
(values.json_safe) so a board is valid JSON for whoever stores it.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from fantaclaude.values import json_safe

NEG = -math.inf
SLOT_PRICE_STEPS = 12


@dataclass(frozen=True)
class PricingConfig:
    candidates_per_class: int = 30      # the DP values the top N by value and the top N by value per credit
    max_per_class: int = 6              # a cap on the ranks a class may have (the demand sets the real number)
    max_goalkeepers: int = 3
    bench_weight: float = 0.12          # the first bench rank of a class: the chance to start anyway
    bench_decay: float = 0.5            # each further bench rank is worth this much of the previous
    bench_slots_per_class: int = 1      # bench ranks beyond the peak demand of any module
    target_weight: float = 0.8          # what a preferences target raises a rank's weight to
    inflation_floor: float = 0.6
    inflation_ceiling: float = 2.5
    replacement_price: int = 1          # the price a replacement-level player is expected to cost
    tiers_per_class: int = 5
    tier_pool: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PoolPlayer:
    player_id: int
    name: str
    role_class: str
    value_p25: float
    value_p50: float
    value_p75: float
    quotazione: int


@dataclass(frozen=True)
class OwnedPlayer:
    player_id: int
    role_class: str
    value_p50: float


@dataclass(frozen=True)
class PoolState:
    credits: int
    market_credits: int
    pool: tuple[PoolPlayer, ...]
    weights: dict[str, tuple[float, ...]]
    hard_minimums: dict[str, int]
    owned: tuple[OwnedPlayer, ...] = ()
    excluded: frozenset[int] = frozenset()
    roster_min: int = 23
    roster_max: int = 40
    min_goalkeepers: int = 2
    max_goalkeepers: int = 6
    targets: dict[str, int] = field(default_factory=dict)
    class_budget_share: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Band:
    p25: int
    p50: int
    p75: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class PlayerPrice:
    player_id: int
    role_class: str
    band: Band
    expected_price: int
    rank_weight: float        # the rank the completion leaves him at his p50 max price, not his class's first
    walk_value: float
    buy_value: float          # rank_weight * value_p50 - the slot price + the completion at the p50 max price

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"player_id": self.player_id, "role_class": self.role_class, "band": self.band.to_dict(),
                          "expected_price": self.expected_price, "rank_weight": self.rank_weight,
                          "walk_value": self.walk_value, "buy_value": self.buy_value})


@dataclass(frozen=True)
class BoardPricing:
    prices: dict[int, PlayerPrice]
    inflation: float
    expected_prices: dict[int, int]
    composition: dict[str, int]
    credits_by_class: dict[str, int]
    completion_value: float
    reserve: int
    budget: int
    slot_price: float
    targets_departed: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"prices": {str(k): v.to_dict() for k, v in self.prices.items()}, "inflation": self.inflation,
                          "expected_prices": {str(k): v for k, v in self.expected_prices.items()},
                          "composition": self.composition, "credits_by_class": self.credits_by_class,
                          "completion_value": self.completion_value, "reserve": self.reserve, "budget": self.budget,
                          "slot_price": self.slot_price, "targets_departed": list(self.targets_departed)})


@dataclass(frozen=True)
class _Class:
    name: str
    players: tuple[PoolPlayer, ...]
    costs: np.ndarray
    values: np.ndarray
    weights: tuple[float, ...]
    j_min: int
    j_max: int
    cap: int | None


def _curve(costs: np.ndarray, values: np.ndarray, weights: tuple[float, ...] | np.ndarray, budget: int,
           penalty: float = 0.0) -> np.ndarray:
    """dp[v, j, c]: the best weighted value of exactly j players for at most c
    credits, less the slot price each, under rank weighting v. `weights` is a
    stack of weightings (a single row broadcasts to one): they share the one
    pass over the class, because they differ in what the j-th chosen player is
    worth and not in which players exist. Every rank is updated in one numpy
    operation per player: the right-hand side reads the tables as they stood
    before him, which is what a descending loop over j used to guarantee one
    rank at a time, at k times the Python overhead."""
    w = np.atleast_2d(np.asarray(weights, dtype=np.float64))
    k = w.shape[1]
    dp = np.full((w.shape[0], k + 1, budget + 1), NEG)
    dp[:, 0, :] = 0.0
    for cost, value in zip(costs.tolist(), values.tolist()):
        if cost > budget:
            continue
        gain = dp[:, :-1, :budget + 1 - cost] + (w * value - penalty)[:, :, None]
        np.maximum(dp[:, 1:, cost:], gain, out=dp[:, 1:, cost:])
    return dp


def _hole_weights(weights: tuple[float, ...]) -> np.ndarray:
    """Row a: the rank weights the completion keeps when the player on the
    block takes rank a himself. Pricing him means maximising over the rows --
    which rank his value earns against the players the completion actually
    buys is the DP's decision, not rank 1 by construction. Ordering falls out:
    seating him above a better player is never the maximising row, because
    sorted values against sorted weights is the larger sum."""
    k = len(weights)
    return np.array([[weights[r] for r in range(k) if r != a] for a in range(k)],
                    dtype=np.float64).reshape(k, max(0, k - 1))


def _best(dp: np.ndarray, j_min: int, j_max: int, cap: int | None) -> np.ndarray:
    """The best of the j in range, over the last two axes of dp: (..., j, c) -> (..., c)."""
    j_max = min(j_max, dp.shape[-2] - 1)
    if j_min > j_max:
        return np.full(dp.shape[:-2] + dp.shape[-1:], NEG)
    best = dp[..., j_min:j_max + 1, :].max(axis=-2)
    if cap is not None and cap < best.shape[-1] - 1:
        best = best.copy()
        best[..., cap + 1:] = best[..., cap, None]
    return best


def _maxplus(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Both are non-decreasing (a curve is "for at most c credits"), so a
    spend k that buys nothing more than k - 1 does is dominated by k - 1,
    which leaves a credit for the other side: only the steps of `a` are
    worth visiting."""
    n = a.shape[-1]
    out = np.full(b.shape, NEG)
    steps = np.flatnonzero((a > NEG) & np.r_[True, a[1:] > a[:-1]]).tolist()
    for k in steps:
        np.maximum(out[..., k:], a[k] + b[..., :n - k], out=out[..., k:])
    return out


def _at(a: np.ndarray, b: np.ndarray, c: int) -> float:
    return float((a[:c + 1] + b[..., :c + 1][..., ::-1]).max())


def _expected_prices(state: PoolState, cfg: PricingConfig) -> tuple[float, dict[int, int]]:
    by_class: dict[str, list[PoolPlayer]] = {}
    for p in state.pool:
        by_class.setdefault(p.role_class, []).append(p)
    credible: set[int] = set()
    for players in by_class.values():
        credible.update(p.player_id for p in sorted(players, key=lambda q: -q.value_p50)[:cfg.candidates_per_class])
    quot = sum(p.quotazione for p in state.pool if p.player_id in credible)
    raw = state.market_credits / quot if quot > 0 else 1.0
    inflation = min(cfg.inflation_ceiling, max(cfg.inflation_floor, raw))
    return inflation, {p.player_id: max(1, round(p.quotazione * inflation)) for p in state.pool}


def _classes(state: PoolState, cfg: PricingConfig, expected: dict[int, int], budget: int) -> list[_Class]:
    owned = Counter(o.role_class for o in state.owned)
    grouped: dict[str, list[PoolPlayer]] = {cls: [] for cls in state.weights}
    for p in state.pool:
        if p.player_id in state.excluded:
            continue
        if p.role_class not in grouped:
            raise ValueError(f"player {p.player_id} has role class {p.role_class!r}, which the weights do not know")
        grouped[p.role_class].append(p)
    classes: list[_Class] = []
    for cls, ranks in state.weights.items():
        players = grouped[cls]
        by_value = sorted(players, key=lambda p: (-p.value_p50, p.player_id))
        by_ratio = sorted(players, key=lambda p: (-p.value_p50 / expected[p.player_id], p.player_id))
        chosen = ({p.player_id for p in by_value[:cfg.candidates_per_class]}
                  | {p.player_id for p in by_ratio[:cfg.candidates_per_class]})
        candidates = tuple(p for p in by_value if p.player_id in chosen)
        m = owned.get(cls, 0)
        k_max = min(cfg.max_goalkeepers, state.max_goalkeepers) if cls == "Por" else cfg.max_per_class
        k_max = min(k_max, len(ranks))
        j_max = max(0, k_max - m)
        need = max(state.hard_minimums.get(cls, 0), state.min_goalkeepers if cls == "Por" else 0)
        weights = tuple(ranks[m + i] if m + i < len(ranks) else ranks[-1] for i in range(j_max))
        cap = int(state.class_budget_share[cls] * budget) if cls in state.class_budget_share else None
        classes.append(_Class(cls, candidates, np.array([expected[p.player_id] for p in candidates], dtype=np.int64),
                              np.array([p.value_p50 for p in candidates], dtype=np.float64), weights,
                              max(0, need - m), j_max, cap))
    return classes


@dataclass
class _Solution:
    budget: int
    penalty: float
    total: np.ndarray
    others: dict[str, np.ndarray]
    composition: dict[str, int]
    credits: dict[str, int]


def _solve(classes: list[_Class], budget: int, penalty: float = 0.0) -> _Solution:
    zero = np.zeros(budget + 1)
    dps = {c.name: _curve(c.costs, c.values, c.weights, budget, penalty)[0] for c in classes}
    best = {c.name: _best(dps[c.name], c.j_min, c.j_max, c.cap) for c in classes}
    prefix = [zero]
    for c in classes:
        prefix.append(_maxplus(prefix[-1], best[c.name]))
    suffix = [zero]
    for c in reversed(classes):
        suffix.append(_maxplus(suffix[-1], best[c.name]))
    suffix.reverse()                                            # suffix[i] = every class from i on
    others = {c.name: _maxplus(prefix[i], suffix[i + 1]) for i, c in enumerate(classes)}
    composition: dict[str, int] = {}
    credits: dict[str, int] = {}
    remaining = budget
    for i in range(len(classes) - 1, -1, -1):
        c = classes[i]
        dp, pre = dps[c.name], prefix[i]
        top = min(remaining, c.cap) if c.cap is not None else remaining
        best_value, best_j, best_c = NEG, 0, 0
        for j in range(c.j_min, min(c.j_max, dp.shape[0] - 1) + 1):
            candidates = dp[j, :top + 1] + pre[remaining - np.arange(top + 1)]
            idx = int(np.argmax(candidates))
            if candidates[idx] > best_value:
                best_value, best_j, best_c = float(candidates[idx]), j, idx
        composition[c.name], credits[c.name] = best_j, best_c
        remaining -= best_c
    return _Solution(budget, penalty, prefix[-1], others, composition, credits)


def _fit_roster(classes: list[_Class], budget: int, slots: int) -> _Solution:
    """The completion within `slots` players: free if it fits, else the
    smallest per-player slot price that makes it fit, by bisection."""
    free = _solve(classes, budget)
    if sum(free.composition.values()) <= slots:
        return free
    lo, hi = 0.0, max((float(c.weights[0] * c.values.max()) for c in classes if c.weights and c.values.size), default=1.0)
    fit = _solve(classes, budget, hi)
    for _ in range(SLOT_PRICE_STEPS):
        mid = (lo + hi) / 2
        candidate = _solve(classes, budget, mid)
        if sum(candidate.composition.values()) <= slots:
            hi, fit = mid, candidate
        else:
            lo = mid
    return fit


def _class_holes(c: _Class, budget: int, penalty: float) -> np.ndarray:
    """The class's curves with one rank left free and nobody removed: row a is
    the best the class does around a player seated at rank a. Exact for a
    player the DP never considered -- he was in no table, so his leaving the
    pool leaves every table as it is -- and shared by all of them."""
    dp = _curve(c.costs, c.values, _hole_weights(c.weights), budget, penalty)
    return _best(dp, max(0, c.j_min - 1), max(0, c.j_max - 1), c.cap)


def _column(buy: np.ndarray, others: np.ndarray, c: int) -> np.ndarray:
    """Per rank he could take, buying him with c credits left for the rest:
    the split of c between his class and the rest of the roster, maximised
    point by point. The binary search asks for a handful of points, and a
    whole max-plus convolution per player is what an exact board cannot
    afford."""
    if c < 0:
        return np.full(buy.shape[0], NEG)
    return (others[:c + 1] + buy[:, :c + 1][:, ::-1]).max(axis=1)


def _max_price(buy: np.ndarray, others: np.ndarray, walk: float, budget: int) -> int:
    """The largest x in [0, budget] with buy(budget - x) >= walk; buy(.) is a
    maximum of non-decreasing curves, so the predicate is monotone in x. No
    completion without him (walk = -inf) makes it every credit that still
    leaves the buy branch feasible."""
    def ok(c: int) -> bool:
        value = float(_column(buy, others, c).max())
        return value > NEG if walk == NEG else value >= walk
    if not ok(budget):
        return 0
    lo, hi = 0, budget
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ok(budget - mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def price_board(state: PoolState, cfg: PricingConfig) -> BoardPricing:
    if state.credits < 0:
        raise ValueError("credits cannot be negative")
    inflation, expected = _expected_prices(state, cfg)
    slots = max(0, state.roster_max - len(state.owned))
    reserve, budget = 0, state.credits
    classes = _classes(state, cfg, expected, budget)
    solution = _fit_roster(classes, budget, slots)
    while True:                     # the reserve and the completion it pays for have to agree: reserving credits
        short = state.roster_min - len(state.owned) - sum(solution.composition.values())   # shrinks the budget,
        need = min(state.credits, max(reserve, short))                    # which can buy fewer players, which
        if need <= reserve:                                               # reserves more. Taking the running
            break                                                         # maximum makes that non-decreasing and
        reserve, budget = need, state.credits - need                      # bounded by roster_min, so it settles
        classes = _classes(state, cfg, expected, budget)                  # (2-3 solves) instead of oscillating.
        solution = _fit_roster(classes, budget, slots)
    penalty = solution.penalty
    by_class = {c.name: c for c in classes}
    candidate_of = {p.player_id: c.name for c in classes for p in c.players}
    shared: dict[str, np.ndarray] = {}
    prices: dict[int, PlayerPrice] = {}
    for p in state.pool:
        if p.player_id in state.excluded:
            continue
        c = by_class[p.role_class]
        if c.j_max == 0:
            prices[p.player_id] = PlayerPrice(p.player_id, c.name, Band(0, 0, 0), expected[p.player_id], 0.0,
                                              float(solution.total[budget]), NEG)
            continue
        k = len(c.weights)
        others = solution.others[c.name]
        if p.player_id in candidate_of:
            keep = [i for i, q in enumerate(c.players) if q.player_id != p.player_id]
            stack = np.zeros((k + 1, k))                        # row 0 walks away from him, row a + 1 seats him at rank a
            stack[0] = c.weights
            stack[1:, :k - 1] = _hole_weights(c.weights)        # the padding column is never read: j stops at j_max - 1
            dp = _curve(c.costs[keep], c.values[keep], stack, budget, penalty)
            walk = _at(others, _best(dp[0], c.j_min, c.j_max, c.cap), budget)
            holes = _best(dp[1:], max(0, c.j_min - 1), max(0, c.j_max - 1), c.cap)
        else:                                        # in no table, so the class's own curves are exact for him
            if c.name not in shared:
                shared[c.name] = _class_holes(c, budget, penalty)
            walk, holes = float(solution.total[budget]), shared[c.name]
        # buy(c) = max over the rank he takes; every row already leaves that rank
        # free, so scarcity and the rank weight both fall out of the same maximum.
        ranks = np.asarray(c.weights)[:, None]
        buys = [holes + (ranks * v - penalty) for v in (p.value_p25, p.value_p50, p.value_p75)]
        band = Band(*(_max_price(b, others, walk, budget) for b in buys))
        if c.cap is not None:                                   # a budget share caps the class, so it caps the price
            band = Band(*(min(x, c.cap) for x in (band.p25, band.p50, band.p75)))
        at_p50 = _column(buys[1], others, budget - band.p50)
        taken = int(np.argmax(at_p50))
        buy = float(at_p50[taken]) if at_p50[taken] > NEG else NEG
        prices[p.player_id] = PlayerPrice(p.player_id, c.name, band, expected[p.player_id], c.weights[taken], walk, buy)
    owned = Counter(o.role_class for o in state.owned)
    departed = tuple(cls for cls, n in state.targets.items()
                     if solution.composition.get(cls, 0) + owned.get(cls, 0) < n)
    return BoardPricing(prices, inflation, expected, solution.composition, solution.credits,
                        float(solution.total[budget]), reserve, budget, penalty, departed)


def explain(board: BoardPricing, player_id: int) -> dict[str, Any]:
    """The trace behind one price, for the model to read: never a recomputation."""
    price = board.prices[player_id]
    return json_safe({"player_id": player_id, "role_class": price.role_class, "band": price.band.to_dict(),
                      "expected_price": price.expected_price, "rank_weight": price.rank_weight,
                      "walk_value": price.walk_value, "buy_value": price.buy_value,
                      "inflation": board.inflation, "composition": board.composition,
                      "credits_by_class": board.credits_by_class, "completion_value": board.completion_value,
                      "reserve": board.reserve, "budget": board.budget, "slot_price": board.slot_price,
                      "targets_departed": list(board.targets_departed)})
```

- [ ] **Step 5: Follow the callers in `valuation.py`**

In `core/src/fantaclaude/analysis/valuation.py`: in the module docstring replace `allocate (price_board with exact=True, once per scenario --\nthe composition is the DP's)` with `allocate (price_board, once per scenario -- the composition is\nthe DP's)`; replace `boards[scenario.name] = price_board(state, pricing_cfg, exact=True)` with `boards[scenario.name] = price_board(state, pricing_cfg)`; and in `record_run` replace the line `price.band.p75, price.walk_value, price.exact, canonical_json(_finite(price.to_dict()))]` with:

```python
              # `exact` is always true since Phase 2a decided on one pricing mode; the column
              # stays, so the runs recorded before the decision still read the same way.
              price.band.p75, price.walk_value, True, canonical_json(_finite(price.to_dict()))]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_pricing.py core/tests/test_values.py core/tests/test_valuation.py core/tests/test_rank_cli.py -q`
Expected: PASS; `test_a_full_board_re_prices_inside_the_latency_budget` prints nothing but its timings should be 0.18–0.30 s on this machine (`-s` shows them on a failure). `uv run pytest core/tests -q` → 368 passed (18 in `test_pricing`: the focused-player test is gone, the leave-one-out test is new).

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/values.py core/src/fantaclaude/asta/pricing.py core/src/fantaclaude/analysis/valuation.py core/tests/test_pricing.py core/tests/test_values.py core/tests/test_valuation.py
git commit -m "feat(asta): one pricing mode -- every player priced with himself out of the pool, the knapsack vectorised over ranks"
```

---

### Task 2: One re-sync flow for every command that re-syncs

**Files:**
- Modify: `core/src/fantaclaude/cli/app.py:60-111,682-774`, `core/src/fantaclaude/commands/rank.py:19-36,73-98,203-240`
- Test: `core/tests/test_rank_cli.py`, `core/tests/test_sync_league.py`

**Interfaces:**
- Consumes: `commands.sync_league.prepare_sync`, `apply_sync`, `SyncReport`; `league.league_yml.load_league_yml`, `LeagueYmlError`; `api_client.run_with_api`.
- Produces: `cli/app._league_yml_or_exit() -> dict[str, Provenanced] | None` (a malformed `league.yml` exits 3 from any command); `cli/app._fetch_league(entries, *, json_: bool, league: str | None) -> LeagueSnapshot` (the network half, before any database is opened; a conflict is rendered and exits 4 here); `rank(..., sync: SyncReport | None = None) -> RankReport` with `RankReport.sync` and `to_dict()["sync"]` (`None` under `--offline`); `_render_rank` prints the `sync-league` lines first when the rules changed.

Phase 1's review: `rank_cmd` re-implemented `sync_league_cmd`'s fetch/conflict/apply flow and dropped the `SyncReport`, so a rules change detected during `rank` superseded every earlier run without showing the diff or the count that `sync-league` renders; and `sync-league` let a malformed `league.yml` escape as a traceback while `rank` exited 3. One flow now, before 2a's `asta` commands would have become a third copy — they turn out not to re-sync at all (every `asta` command is local), but the helper is the shape any later network command uses.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_rank_cli.py`, add `import asyncio` as the first import, and in `test_rank_re_syncs_first_unless_offline` replace the block from `monkeypatch.setattr("fantaclaude.api_client.run_with_api", fake_run_with_api)` through `assert runner.invoke(app, ["rank", "--offline", "--json"]).exit_code == ExitCode.OK and calls == []` with:

```python
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", fake_run_with_api)
    result = runner.invoke(app, ["rank", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert calls == ["sync"] and payload["players"] == 17
    assert payload["sync"]["changed"] is False and payload["sync"]["superseded_runs"] == 0     # the seeded rules, unchanged

    calls.clear()
    offline = json.loads(runner.invoke(app, ["rank", "--offline", "--json"]).stdout)
    assert calls == [] and offline["sync"] is None

    # A rules change detected by the re-sync is reported the way sync-league
    # reports it -- the diff and the runs it supersedes -- not absorbed. The
    # card maluses are not league.yml keys, so a change is a change, not a conflict.
    calculate = dict(mcp_fixture_json("calculation_settings"))
    calculate["bnMls"] = {**calculate["bnMls"], "bmyc": [-1, -1]}
    changed_api = fake_api({"calculation_settings": calculate})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(changed_api)))
    plain = runner.invoke(app, ["rank"])
    assert plain.exit_code == ExitCode.OK, plain.output
    assert "changed: snapshot 2" in plain.stdout and "calculate.bnMls.bmyc: [-0.5, -0.5] -> [-1, -1]" in plain.stdout
    assert "2 valuation run(s) computed under the old rules are now superseded" in plain.stdout
    calculate["bnMls"] = {**calculate["bnMls"], "bmrc": [-2, -2]}
    changed_again = fake_api({"calculation_settings": calculate})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(changed_again)))
    moved = runner.invoke(app, ["rank", "--json"])
    assert moved.exit_code == ExitCode.OK, moved.output
    sync = json.loads(moved.stdout)["sync"]
    assert sync["changed"] is True and sync["snapshot_id"] == 3 and sync["superseded_runs"] == 1     # only the run under snapshot 2
    assert sync["diff"] == [{"path": "calculate.bnMls.bmrc", "before": [-1, -1], "after": [-2, -2]}]
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", fake_run_with_api)
```

and, at the end of the same test, replace the last five lines (from `conflict = runner.invoke(app, ["rank"])`) with:

```python
    conflict = runner.invoke(app, ["rank"])
    assert conflict.exit_code == ExitCode.CONFLICT and "CONFLICT budget" in conflict.stdout
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0] == 4
    con.close()

    # a malformed league.yml is not-ready, and refuses before the network is touched
    (tmp_path / "league.yml").write_text("budget: 500\n")
    calls.clear()
    malformed = runner.invoke(app, ["rank"])
    assert malformed.exit_code == ExitCode.NOT_READY and "league.yml" in malformed.stderr and calls == []
```

In `core/tests/test_sync_league.py`, at the end of `test_cli_sync_league_json_and_exit_codes`, append:

```python

    # a league.yml leaf without provenance is not-ready (3), the same code rank gives it,
    # and it is refused before the network is touched
    (tmp_path / "league.yml").write_text("budget: 1000\n")
    calls_before = len(api.calls)
    result = runner.invoke(app, ["sync-league"])
    assert result.exit_code == ExitCode.NOT_READY and "league.yml" in result.stderr
    assert len(api.calls) == calls_before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_rank_cli.py::test_rank_re_syncs_first_unless_offline core/tests/test_sync_league.py::test_cli_sync_league_json_and_exit_codes -q`
Expected: FAIL — `KeyError: 'sync'` in the rank test; in the sync test `result.exit_code == 1` (the `LeagueYmlError` traceback).

- [ ] **Step 3: The two helpers and the two commands in `cli/app.py`**

Replace the whole of `sync_league_cmd` (from `@app.command("sync-league")` to its `raise typer.Exit(code=ExitCode.CONFLICT)`) with:

```python
def _league_yml_or_exit():
    """league.yml's provenanced entries, or None when there is no file. A
    malformed file is not-ready (exit 3) whichever command reads it -- it
    used to be a traceback from sync-league and exit 3 from rank."""
    import yaml

    from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
    from fantaclaude.paths import league_yml_path

    path = league_yml_path()
    if not path.is_file():
        return None
    try:
        return load_league_yml(path)
    except LeagueYmlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        typer.echo(f"{path}: {exc}", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None


def _fetch_league(entries, *, json_: bool, league: str | None):
    """The network half of a re-sync, before any database is opened. DuckDB
    is single-writer, so the write lock must not span six round-trips, and
    connect() creates the file, so a failed fetch must not leave an
    empty-but-valid database behind. A league.yml conflict is rendered here
    and exits 4: nothing is recorded and no database is created. One copy of
    this flow for every command that re-syncs -- sync-league and rank today;
    rank used to carry its own, which had already drifted (it dropped the
    SyncReport, so a rules change detected mid-rank superseded every earlier
    run without showing the diff or the count)."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.sync_league import apply_sync, prepare_sync

    snap, conflicts = run_with_api(lambda api: prepare_sync(api, entries, league=league))
    if conflicts:
        emit(apply_sync(None, snap, conflicts).to_dict(), json_=json_, render=_render_sync)
        raise typer.Exit(code=ExitCode.CONFLICT)
    return snap


@app.command("sync-league")
def sync_league_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh league_settings from the league API: profile, status, the three settings payloads and the team list."""
    from fantaclaude.commands.sync_league import apply_sync
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    snap = _fetch_league(_league_yml_or_exit(), json_=json_, league=league)
    con = connect()
    try:
        apply_schema(con)
        report = apply_sync(con, snap, [])
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_sync)
```

In `_render_rank`, replace its first three lines (`s = payload["summary"]` and the `lines = [(f"run ...` opening) with:

```python
    s = payload["summary"]
    lines = []
    if payload.get("sync") and payload["sync"]["changed"]:       # the rules moved under this run: say so, as sync-league would
        lines.append(_render_sync(payload["sync"]))
    lines += [(f"run {payload['run_id']} · rules {payload['rules_hash']} · model {payload['model_hash']} · "
               f"inputs {payload['inputs_hash']}"),
```

(the rest of the list literal is unchanged; mind the one extra space of indentation on the continuation lines of the first tuple.)

In `rank_cmd`, replace the import block and the `league.yml` loading (from `from fantaclaude.analysis.valuation import UnknownScenarioError` down to the `raise typer.Exit(code=ExitCode.NOT_READY) from None` that follows `load_league_yml`) with:

```python
    from fantaclaude.analysis.valuation import UnknownScenarioError
    from fantaclaude.commands.ingest import NotReady
    from fantaclaude.commands.rank import check_ready, rank
    from fantaclaude.commands.sync_league import apply_sync
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.paths import (
        exports_dir,
        kb_dir,
        preferences_yml_path,
        pricing_yml_path,
        records_dir,
    )
    from fantaclaude.timeutil import utc_now

    entries = _league_yml_or_exit()
```

and replace the block from `snap = conflicts = None` down to the `rank(...)` call with:

```python
    snap = None if offline else _fetch_league(entries, json_=json_, league=league)
    con = connect()
    try:
        apply_schema(con)
        sync = apply_sync(con, snap, []) if snap is not None else None
        try:
            report = rank(con, now=utc_now(), kb_dir=kb_dir(), preferences_path=preferences_yml_path(),
                          pricing_path=pricing_yml_path(), exports_dir=exports_dir(), records_dir=records_dir(),
                          league_yml=entries, scenarios=list(scenario) if scenario else None, sync=sync)
```

- [ ] **Step 4: Carry the report through `commands/rank.py`**

Add `from fantaclaude.commands.sync_league import SyncReport` after the `NotReady` import. In `RankReport`, after `top: dict[str, list[dict[str, Any]]] = field(default_factory=dict)` add:

```python
    # the re-sync that preceded the run, when there was one: a rules change
    # detected here is reported with its diff and the runs it superseded, as
    # sync-league reports it, instead of being absorbed silently
    sync: SyncReport | None = None
```

and end `to_dict` with `"freeze": self.freeze.to_dict() if self.freeze is not None else None, "top": self.top,\n                "sync": self.sync.to_dict() if self.sync is not None else None}`. Give `rank()` a last keyword parameter `sync: SyncReport | None = None` and pass `sync=sync` into the `RankReport(...)` it returns.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_rank_cli.py core/tests/test_sync_league.py core/tests/test_cli_app.py -q`
Expected: PASS. `uv run pytest core/tests -q` → 368 passed.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/cli/app.py core/src/fantaclaude/commands/rank.py core/tests/test_rank_cli.py core/tests/test_sync_league.py
git commit -m "refactor(cli): one re-sync flow, and rank reports the rules change it applied"
```

---

### Task 3: Roster bounds per class — `class_min` / `class_max`

**Files:**
- Modify: `core/src/fantaclaude/asta/pricing.py` (`PoolState`, `_classes`, the docstring), `core/src/fantaclaude/analysis/valuation.py` (`RunContext`, `load_context`, `run_valuation`)
- Test: `core/tests/test_pricing.py`

**Interfaces:**
- Consumes: Task 1's `pricing.py`.
- Produces: `PoolState(credits, market_credits, pool, weights, hard_minimums, owned=(), excluded=frozenset(), roster_min=23, roster_max=40, class_min: dict[str, int] = {}, class_max: dict[str, int] = {}, targets={}, class_budget_share={})` — `min_goalkeepers`/`max_goalkeepers` are gone; `RunContext.class_min`/`class_max: dict[str, int]` (`{"Por": minrl[0]}` / `{"Por": maxrl[0]}`) replace `min_goalkeepers`/`max_goalkeepers`. The pricing knob `PricingConfig.max_goalkeepers` stays as it is: it is named for the goalkeepers and it feeds `model_hash`, so renaming it would stamp every run as a new model for no change in any price.

- [ ] **Step 1: Write the failing test**

In `core/tests/test_pricing.py`, in `state()` replace `"roster_min": 1, "roster_max": 40, "min_goalkeepers": 2, "max_goalkeepers": 6}` with `"roster_min": 1, "roster_max": 40, "class_min": {"Por": 2}, "class_max": {"Por": 6}}`; in `cliff_state()` replace `"roster_min": 1, "roster_max": 40, "min_goalkeepers": 0, "max_goalkeepers": 6}` with `"roster_min": 1, "roster_max": 40}`; and insert before `def test_a_budget_share_caps_a_class():`

```python
def test_a_class_bound_is_generic_not_a_goalkeeper_branch():
    """Phase 1 carried the goalkeeper bounds as two scalars behind `cls ==
    "Por"` branches, so a house rule like "3 portieri, 8 difensori" needed
    new fields and more branches. The bounds are per class: the goalkeepers'
    are one entry, and any other class takes the same two dicts."""
    plain = price_board(state(), CFG)
    floored = price_board(state(class_min={"Por": 2, "E": 3}), CFG)
    assert floored.composition["E"] == 3 > plain.composition["E"]
    e = by_class(small_pool(), "E")
    assert floored.prices[e[2].player_id].band.p50 > plain.prices[e[2].player_id].band.p50       # the third E is needed now
    capped = price_board(state(class_max={"Por": 6, "Pc": 1}), CFG)
    pc = by_class(small_pool(), "Pc")
    assert capped.composition["Pc"] == 1 < plain.composition["Pc"]
    assert capped.prices[pc[1].player_id].band.p50 < plain.prices[pc[1].player_id].band.p50       # one Pc slot, and he is the second
    # a class cannot be floored above the ranks the demand gives it: the floor binds through -inf, as a hard minimum does
    starved = price_board(state(tuple(p for p in small_pool() if p.role_class != "Dc"), class_min={"Por": 2, "Dc": 2}), CFG)
    assert starved.completion_value == float("-inf")


```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_pricing.py -q`
Expected: FAIL — `TypeError: PoolState.__init__() got an unexpected keyword argument 'class_min'` on every test that builds a state.

- [ ] **Step 3: Widen `PoolState` and make `_classes` generic**

In `core/src/fantaclaude/asta/pricing.py` replace, in `PoolState`,

```python
    roster_min: int = 23
    roster_max: int = 40
    min_goalkeepers: int = 2
    max_goalkeepers: int = 6
    targets: dict[str, int] = field(default_factory=dict)
```

with

```python
    roster_min: int = 23
    roster_max: int = 40
    class_min: dict[str, int] = field(default_factory=dict)     # the league's or the house's floor per class (Por 2)
    class_max: dict[str, int] = field(default_factory=dict)     # and its ceiling (Por 6); hard_minimums are the modules'
    targets: dict[str, int] = field(default_factory=dict)
```

and in `_classes` replace

```python
        m = owned.get(cls, 0)
        k_max = min(cfg.max_goalkeepers, state.max_goalkeepers) if cls == "Por" else cfg.max_per_class
        k_max = min(k_max, len(ranks))
        j_max = max(0, k_max - m)
        need = max(state.hard_minimums.get(cls, 0), state.min_goalkeepers if cls == "Por" else 0)
```

with

```python
        m = owned.get(cls, 0)
        # the pricing knob for goalkeepers is named for them; the league's and the house's bounds are per class
        cap_cfg = cfg.max_goalkeepers if cls == "Por" else cfg.max_per_class
        k_max = min(cap_cfg, state.class_max.get(cls, cap_cfg), len(ranks))
        j_max = max(0, k_max - m)
        need = max(state.hard_minimums.get(cls, 0), state.class_min.get(cls, 0))
```

In the module docstring replace `role class and rank (model/demand.py), the hard minimums, the league's\nbounds.` with `role class and rank (model/demand.py), the hard minimums, the league's\nbounds per class (class_min / class_max: the goalkeepers' 2-6 today, a\nhouse rule's "3 portieri" tomorrow) and for the whole roster.` and re-wrap the paragraph.

- [ ] **Step 4: Follow the change through `valuation.py`**

In `RunContext` replace the two fields `min_goalkeepers: int` and `max_goalkeepers: int` with:

```python
    class_min: dict[str, int]       # per role class, from minrl/maxrl read as [goalkeepers, outfield]; a
    class_max: dict[str, int]       # house rule ("3 portieri, 8 difensori") lands here, never in a branch
```

In `load_context`'s `return RunContext(...)` replace the two positional arguments `int(minrl[0]), int(maxrl[0]),` with `{"Por": int(minrl[0])}, {"Por": int(maxrl[0])},`. In `run_valuation`'s `PoolState(...)` replace `min_goalkeepers=ctx.min_goalkeepers, max_goalkeepers=ctx.max_goalkeepers,` with `class_min=ctx.class_min, class_max=ctx.class_max,`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run ruff check core && uv run pytest core/tests/test_pricing.py core/tests/test_valuation.py core/tests/test_rank_cli.py -q`
Expected: PASS; every pre-existing pricing and valuation test is unchanged in outcome, which is the proof the refactor moved no price. `uv run pytest core/tests -q` → 369 passed.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/asta/pricing.py core/src/fantaclaude/analysis/valuation.py core/tests/test_pricing.py
git commit -m "refactor(asta): roster bounds per class in PoolState, the goalkeepers as one entry"
```

---

### Task 4: The state machine — session settings, snapshots, and the set-diff

**Files:**
- Create: `core/src/fantaclaude/asta/session.py`, `core/src/fantaclaude/asta/state.py`, `core/tests/fixtures/_extract_asta.py`, `core/tests/fixtures/asta_session_sample.jsonl` (generated by the script)
- Test: `core/tests/test_session.py`, `core/tests/test_state.py`

**Interfaces:**
- Consumes: `league.settings.EMAIL_PATTERN`, `diff_payloads`, `record_snapshot`/`snapshot_from_payloads` (tests); `values.is_number`; the `fixture_file`, `db`, `mcp_fixture_json` fixtures in `conftest.py`.
- Produces: `session.SessionSettings(budget, goalkeepers: (low, high), outfield: (low, high), size: (low, high), game, team_count, source, raw)` with `.is_mantra`, `.to_dict()`; `session.session_from_feed(settings: Mapping, *, team_count) -> SessionSettings`; `session.session_from_league(*, budget, team_count, roster_min, roster_max, minrl, maxrl) -> SessionSettings`; `session.league_bounds(con, snapshot_id) -> SessionSettings`; `session.compare(session, league) -> list[str]`; `session.SessionError`; `session.GAME_MANTRA = 2`. `state.Pick(player_id, team_id, cost, index, timestamp=None)` with `.to_node()`; `state.Team(team_id, label)`; `state.Snapshot(picks, teams, settings, selected, turn_team, status, locked, player_list_hash)` with `.to_node()`; `state.parse_snapshot(node) -> Snapshot`; `state.read_snapshots(path) -> list[Snapshot]` (JSON lines); `state.scrub_label(label, team_id) -> str`; `state.AuctionState(picks: dict[int, Pick], teams, settings, selected, turn_team, status, locked, player_list_hash, duplicates)` with `.empty()`, `.team_ids()`, `.picks_of(team_id)`, `.spent(team_id)`, `.to_snapshot()`; the events `SaleAdded(player_id, team_id, cost)`, `SaleRemoved(player_id, team_id, cost)`, `CostEdited(player_id, team_id, before, after)`, `LotSelected(player_id | None)`, `SettingsChanged(changes: tuple[(path, before, after), ...])`, `StatusChanged(status, locked)`, the union `Event`; `state.apply_snapshot(state, snapshot) -> tuple[AuctionState, tuple[Event, ...]]`; `state.SnapshotError`.

- [ ] **Step 1: Write the fixture's extract script and generate the fixture**

Create `core/tests/fixtures/_extract_asta.py`:

```python
"""One-shot: build asta_session_sample.jsonl from captured/fantaastalive-state-2026-08-23.json.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_asta.py

The capture is FantaAstaLive's local state before any auction -- no picks --
encoded as JSON twice (json.loads(json.load(f))). Its `settings` and its two
`teams` are kept as the session node carries them (the spec's node shape:
picks[], lastPick, selectedPlayerId, turnTeamId, status, locked, teams[],
settings, options, pickOrder, hostId, playerListHash); the peer ids and
uids are dropped, being opaque and read by nothing. `currentBudget` is kept
at its stale 500 on purpose: it is the field the mirror must never trust.

The picks are scripted here over listone_sample.json's ids, so the sequence
exercises everything the diff engine has to handle: a sale, a second sale,
a cost edit, an undo, the same player re-sold to another team while a lot
is on the block, the same snapshot twice, and a playerId the listone does
not have. A third team is added with an @-shaped label that is not an
address (no domain): the case the scrub must leave alone.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "fantaastalive-state-2026-08-23.json"
OUT = Path(__file__).with_name("asta_session_sample.jsonl")

MARTINEZ, BASTONI, SVILAR, UNKNOWN = 2764, 2120, 5841, 999999
T0 = 1787600000000                                   # ms; the capture's own stamps are of this size


def pick(player_id: int, team_id: int, cost: int, value: int, index: int) -> dict:
    return {"playerId": player_id, "teamId": team_id, "cost": cost, "value": value, "index": index,
            "timestamp": T0 + index * 60_000}


def main() -> None:
    local = json.loads(json.loads(CAPTURE.read_text(encoding="utf-8")))["_users"]["-1"]
    prices = {p["id"]: p["price"] for p in local["players"]}
    teams = [{"id": t["id"], "connection": {"label": t["connection"]["label"], "host": t["connection"]["host"]},
              "currentBudget": t["currentBudget"], "missingPlayers": t["missingPlayers"], "picksCount": t["picksCount"]}
             for t in local["teams"]]
    teams.append({"id": 2, "connection": {"label": "@bomber", "host": False}, "currentBudget": 500,
                  "missingPlayers": dict(teams[0]["missingPlayers"]), "picksCount": 0})
    a = pick(MARTINEZ, 0, 120, prices[MARTINEZ], 0)
    b = pick(BASTONI, 1, 40, prices[BASTONI], 1)
    b_edited = {**b, "cost": 45}
    b_resold = pick(BASTONI, 0, 45, prices[BASTONI], 2)               # re-sold: a new lot, a new stamp
    unknown = pick(UNKNOWN, 2, 3, 1, 3)
    steps = [([], None), ([a], None), ([a, b], None), ([a, b_edited], None), ([a], None),
             ([a, b_resold], SVILAR), ([a, b_resold], SVILAR), ([a, b_resold, unknown], None)]
    lines = []
    for picks, selected in steps:
        node = {"picks": picks, "lastPick": picks[-1] if picks else None, "selectedPlayerId": selected,
                "turnTeamId": len(picks) % 3, "status": "live", "locked": False, "teams": teams,
                "settings": local["settings"], "options": local["options"], "pickOrder": [0, 1, 2], "hostId": 0,
                "playerListHash": "sample"}
        lines.append(json.dumps(node, ensure_ascii=False, sort_keys=True))
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} snapshots, {len(teams)} teams, settings.roles {local['settings']['roles']}")


if __name__ == "__main__":
    main()
```

Run: `uv run python core/tests/fixtures/_extract_asta.py`
Expected: `wrote 8 snapshots, 3 teams, settings.roles {'atk': [6, 6], 'def': [8, 8], 'gk': [3, 3], 'mid': [8, 8], 'mov': [22, 22], 'size': [25, 25]}` and a 17 KB `core/tests/fixtures/asta_session_sample.jsonl` (eight lines). The fixture is committed; the capture is not.

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_session.py`:

```python
import pytest
from fantaclaude.asta.session import (
    GAME_MANTRA,
    SessionError,
    SessionSettings,
    compare,
    league_bounds,
    session_from_feed,
    session_from_league,
)
from fantaclaude.asta.state import read_snapshots
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads

LEAGUE = session_from_league(budget=500, team_count=8, roster_min=23, roster_max=40, minrl=[2, 21], maxrl=[6, 34])


def test_the_captured_settings_read_as_exact_counts(fixture_file):
    node = read_snapshots(fixture_file("asta_session_sample.jsonl"))[0]
    s = session_from_feed(node.settings, team_count=len(node.teams))
    assert s == SessionSettings(500, (3, 3), (22, 22), (25, 25), GAME_MANTRA, 3, "session", node.settings)
    assert s.is_mantra and s.to_dict() == {"budget": 500, "goalkeepers": [3, 3], "outfield": [22, 22], "size": [25, 25],
                                            "game": 2, "team_count": 3, "source": "session"}


def test_the_pair_is_read_by_the_game_in_play():
    """The observed pairs are all equal, so the reading ([classic, mantra])
    cannot be wrong yet; a session that sets them apart is read by its game."""
    roles = {"gk": [3, 2], "mov": [22, 21], "size": [25, 23]}
    mantra = session_from_feed({"budget": 500, "game": 2, "roles": roles}, team_count=8)
    assert (mantra.goalkeepers, mantra.outfield, mantra.size) == ((2, 2), (21, 21), (23, 23))
    classic = session_from_feed({"budget": 500, "game": 1, "roles": roles}, team_count=8)
    assert (classic.goalkeepers, classic.outfield, classic.size) == ((3, 3), (22, 22), (25, 25)) and not classic.is_mantra
    bare = session_from_feed({"budget": 500, "game": 2, "roles": {"gk": 2, "mov": 21, "size": 23}}, team_count=8)
    assert bare.goalkeepers == (2, 2) and bare.size == (23, 23)
    for bad, text in (({"budget": 500, "game": 2, "roles": {"gk": [3, 3], "mov": [22, 22], "size": [24, 24]}}, "size 24"),
                      ({"budget": 500, "game": 2, "roles": {"gk": [3, 3], "size": [25, 25]}}, "roles.mov"),
                      ({"budget": 500, "game": 2, "roles": {"gk": [3, True], "mov": [22, 22], "size": [25, 25]}}, "roles.gk"),
                      ({"game": 2, "roles": roles}, "budget"), ({"budget": 500, "game": 3, "roles": roles}, "game"),
                      ({"budget": 500, "game": 2}, "roles"), ({"budget": -5, "game": 2, "roles": roles}, "budget")):
        with pytest.raises(SessionError, match=text):
            session_from_feed(bad, team_count=8)


def test_league_bounds_read_the_run_settings_row(db, mcp_fixture_json):
    record_snapshot(db, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    bounds = league_bounds(db, 1)
    assert bounds == LEAGUE and bounds.source == "league" and bounds.is_mantra
    assert (bounds.goalkeepers, bounds.outfield, bounds.size) == ((2, 6), (21, 34), (23, 40))
    with pytest.raises(SessionError, match="snapshot 9"):
        league_bounds(db, 9)


def test_compare_surfaces_what_the_session_plays_outside_the_league():
    """The session wins for the night; a mismatch is announced at connect,
    before bidding opens, never absorbed."""
    session = session_from_feed({"budget": 500, "game": 2, "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]}},
                                team_count=2)
    assert compare(session, LEAGUE) == ["teams: 2 in the session, 8 in the league"]      # 3, 22 and 25 are inside the bounds
    assert compare(session_from_feed(session.raw, team_count=8), LEAGUE) == []
    rich = session_from_feed({**session.raw, "budget": 1000}, team_count=8)
    assert compare(rich, LEAGUE) == ["budget: the session plays 1000 credits, the league says 500"]
    thin = session_from_feed({**session.raw, "roles": {"gk": [1, 1], "mov": [22, 22], "size": [23, 23]}}, team_count=8)
    assert compare(thin, LEAGUE) == ["goalkeepers: the session fills 1, the league allows 2-6"]
    classic = session_from_feed({**session.raw, "game": 1}, team_count=8)
    assert compare(classic, LEAGUE) == ["game: the session is game 1, the league is Mantra (2)"]
    assert compare(LEAGUE, LEAGUE) == []
```

Create `core/tests/test_state.py`:

```python
import json

import numpy as np
import pytest
from fantaclaude.asta.state import (
    AuctionState,
    CostEdited,
    LotSelected,
    Pick,
    SaleAdded,
    SaleRemoved,
    SettingsChanged,
    Snapshot,
    SnapshotError,
    StatusChanged,
    Team,
    apply_snapshot,
    parse_snapshot,
    read_snapshots,
    scrub_label,
)

SETTINGS = {"budget": 500, "game": 2, "roles": {"gk": [2, 2], "mov": [6, 6], "size": [8, 8]}}


def node(picks, *, selected=None, teams=(0, 1, 2, 3), settings=SETTINGS, status="live", locked=False):
    return {"picks": [{"playerId": pid, "teamId": tid, "cost": cost, "value": 1, "index": i, "timestamp": 1000 + i}
                      for i, (pid, tid, cost) in enumerate(picks)],
            "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams], "settings": settings,
            "selectedPlayerId": selected, "turnTeamId": 0, "status": status, "locked": locked}


def replay(snapshots):
    state, log = AuctionState.empty(), []
    for snap in snapshots:
        state, events = apply_snapshot(state, snap)
        log.append(events)
    return state, log


def test_parse_snapshot_reads_the_capture_shaped_node(fixture_file):
    first = read_snapshots(fixture_file("asta_session_sample.jsonl"))[0]
    assert first.picks == () and [t.team_id for t in first.teams] == [0, 1, 2]
    assert [t.label for t in first.teams] == ["host", "Claude", "@bomber"]     # an @ without a domain is a nick, not an address
    assert first.settings["budget"] == 500 and first.settings["roles"]["gk"] == [3, 3]
    assert first.selected is None and first.turn_team == 0 and first.status == "live" and first.locked is False
    assert first.player_list_hash == "sample"


def test_a_sale_an_edit_an_undo_a_resale_a_duplicate_and_an_unknown_player(fixture_file):
    """The scripted fixture, one snapshot per line, and the events each one
    is worth against the one before -- the cases the spec's diff-engine test
    names, plus a re-sale to another team."""
    state, log = replay(read_snapshots(fixture_file("asta_session_sample.jsonl")))
    assert log[0] == (StatusChanged("live", False),)                      # the first snapshot: a baseline, not a sale
    assert log[1] == (SaleAdded(2764, 0, 120),)
    assert log[2] == (SaleAdded(2120, 1, 40),)
    assert log[3] == (CostEdited(2120, 1, 40, 45),)                        # the admin corrected the price
    assert log[4] == (SaleRemoved(2120, 1, 45),)                           # and then undid the lot
    assert log[5] == (SaleAdded(2120, 0, 45), LotSelected(5841))           # re-sold to the host, Svilar on the block
    assert log[6] == ()                                                    # the same snapshot twice is a no-op
    assert log[7] == (SaleAdded(999999, 2, 3), LotSelected(None))          # an id the listone lacks is the advisor's fault to name
    assert state.spent(0) == 165 and state.spent(1) == 0 and state.spent(2) == 3
    assert [p.player_id for p in state.picks_of(0)] == [2764, 2120] and state.team_ids() == (0, 1, 2)
    assert state.picks[2120] == Pick(2120, 0, 45, 2, 1787600120000)


def test_the_state_is_the_last_snapshots_whatever_came_before(fixture_file):
    snapshots = read_snapshots(fixture_file("asta_session_sample.jsonl"))
    replayed, _ = replay(snapshots)
    direct, _ = apply_snapshot(AuctionState.empty(), snapshots[-1])
    assert replayed == direct
    again, events = apply_snapshot(replayed, snapshots[-1])
    assert events == () and again == replayed
    # an undo restores exactly the state before the lot: snapshot 4 is snapshot 1 again
    after_undo, _ = replay(snapshots[:5])
    before_sale, _ = replay(snapshots[:2])
    assert after_undo.picks == before_sale.picks


def test_any_sequence_of_snapshots_converges_on_the_last_one():
    """Property, over seeded random sale sequences: the board is a pure
    function of the feed, so applying every snapshot, applying them in any
    order, and applying only the last one all end in the same state; and
    the credits a team spent are exactly the costs of its picks."""
    rng = np.random.default_rng(11)
    players = list(range(100, 130))
    for _ in range(20):
        snapshots = []
        for _ in range(int(rng.integers(1, 12))):
            chosen = rng.choice(players, size=int(rng.integers(0, 12)), replace=False).tolist()
            picks = [(pid, int(rng.integers(0, 4)), int(rng.integers(1, 60))) for pid in chosen]
            snapshots.append(parse_snapshot(node(picks, selected=int(rng.choice(players)) if rng.random() < 0.5 else None)))
        forward, log = replay(snapshots)
        shuffled = [snapshots[i] for i in rng.permutation(len(snapshots) - 1)] + [snapshots[-1]]
        assert replay(shuffled)[0] == forward == apply_snapshot(AuctionState.empty(), snapshots[-1])[0]
        for team in range(4):
            assert forward.spent(team) == sum(p.cost for p in forward.picks_of(team)) >= 0
        assert all(isinstance(e, (SaleAdded, SaleRemoved, CostEdited, LotSelected, StatusChanged)) for evs in log for e in evs)
        # the events of a step are the exact difference: replaying them onto the picks reproduces the picks
        picks: dict[int, tuple[int, int]] = {}
        for events in log:
            for e in events:
                if isinstance(e, SaleAdded):
                    picks[e.player_id] = (e.team_id, e.cost)
                elif isinstance(e, SaleRemoved):
                    del picks[e.player_id]
                elif isinstance(e, CostEdited):
                    picks[e.player_id] = (e.team_id, e.after)
        assert picks == {pid: (p.team_id, p.cost) for pid, p in forward.picks.items()}


def test_a_pick_moved_to_another_team_and_a_player_listed_twice():
    moved, events = apply_snapshot(apply_snapshot(AuctionState.empty(), parse_snapshot(node([(7, 0, 10)])))[0],
                                   parse_snapshot(node([(7, 1, 12)])))
    assert events == (SaleRemoved(7, 0, 10), SaleAdded(7, 1, 12)) and moved.picks[7].team_id == 1
    twice, _ = apply_snapshot(AuctionState.empty(), parse_snapshot(node([(7, 0, 10), (8, 1, 5), (7, 2, 30)])))
    assert twice.picks[7] == Pick(7, 2, 30, 2, 1002) and twice.duplicates == (7,)     # the later pick by index stood


def test_settings_and_status_changes_are_events_after_the_first_snapshot():
    first, events = apply_snapshot(AuctionState.empty(), parse_snapshot(node([])))
    assert events == (StatusChanged("live", False),)                     # the settings are a baseline the first time
    richer = parse_snapshot(node([], settings={**SETTINGS, "budget": 1000}, status="closed", locked=True))
    second, events = apply_snapshot(first, richer)
    assert events == (SettingsChanged((("budget", 500, 1000),)), StatusChanged("closed", True))
    assert second.settings["budget"] == 1000 and second.status == "closed" and second.locked is True
    _, events = apply_snapshot(second, richer)
    assert events == ()


def test_labels_are_scrubbed_and_firebase_shaped_lists_are_read():
    raw = {"picks": {"0": {"playerId": 7, "teamId": 0, "cost": 10, "index": 0}, "1": None,
                     "2": {"playerId": 8, "teamId": 1, "cost": 5, "index": 2}},
           "teams": [{"id": 0, "connection": {"label": "someone@example.invalid"}}, {"id": 1, "nick": "  "},
                     {"id": 2, "name": "Marco"}, {"id": 3}],
           "settings": SETTINGS}
    snap = parse_snapshot(raw)
    assert [p.player_id for p in snap.picks] == [7, 8] and snap.picks[1].index == 2
    assert [t.label for t in snap.teams] == ["team 0", "team 1", "Marco", "team 3"]
    assert scrub_label("x@y.invalid", 9) == "team 9" and scrub_label("@bomber", 9) == "@bomber" and scrub_label(None, 9) == "team 9"
    assert "@example" not in json.dumps(snap.to_node())


def test_the_snapshot_round_trips_through_the_feed_shape():
    snap = parse_snapshot(node([(7, 0, 10), (8, 1, 5)], selected=9))
    assert parse_snapshot(snap.to_node()) == snap
    state, _ = apply_snapshot(AuctionState.empty(), snap)
    assert state.to_snapshot() == snap and parse_snapshot(state.to_snapshot().to_node()) == snap
    assert snap.teams[0] == Team(0, "t0")


def test_malformed_nodes_are_refused(tmp_path):
    for bad, text in (({"picks": 5}, "picks is int"), ({"picks": [{"teamId": 0, "cost": 1}]}, "playerId"),
                      ({"picks": [{"playerId": 1, "teamId": 0, "cost": -1}]}, "cost"),
                      ({"picks": [{"playerId": True, "teamId": 0, "cost": 1}]}, "playerId"),
                      ({"picks": [], "locked": "no"}, "locked"), ({"picks": [], "settings": []}, "settings"),
                      ({"picks": [], "teams": [{"connection": {"label": "x"}}]}, "teams\\[0\\].id"),
                      ({"picks": {"a": {}}}, "list indexes"), ([], "not a mapping")):
        with pytest.raises(SnapshotError, match=text):
            parse_snapshot(bad)
    path = tmp_path / "session.jsonl"
    path.write_text(json.dumps(node([])) + "\n\n{not json\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="session.jsonl:3"):
        read_snapshots(path)
    path.write_text(json.dumps(node([])) + "\n" + json.dumps({"picks": 5}) + "\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="session.jsonl:2: picks"):
        read_snapshots(path)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    assert read_snapshots(empty) == []
    assert isinstance(parse_snapshot(node([])), Snapshot)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_session.py core/tests/test_state.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'fantaclaude.asta.session'`.

- [ ] **Step 4: Write `session.py`**

Create `core/src/fantaclaude/asta/session.py`:

```python
"""The night's rules: what the FantaAstaLive session says it is playing.

Session settings are authoritative for the night, and every change to them
is surfaced (spec, "Session settings are authoritative for the night").
They come from the feed's `settings` node -- or, with no session, from the
league's own settings row the pinned run was priced under, which is what
makes the offline board the committed board.

Observed 2026-08-23 (captured/fantaastalive-state-2026-08-23.json, the
app's local state, pre-auction): `settings.budget 500`, `settings.game 2`,
`settings.participants 2`, `settings.roles = {gk: [3, 3], def: [8, 8],
mid: [8, 8], atk: [6, 6], mov: [22, 22], size: [25, 25]}`, with `mov = def
+ mid + atk` and `size = gk + mov`: exact counts, one per game type. The
pairs are read as [classic, mantra] -- the spec's reading, confirmable only
at the rehearsal; with every observed pair equal the reading cannot yet be
wrong, and `_pair` is the one place to change if it is. In Mantra the
enforced buckets are `gk` and `mov` (`teams[].missingPlayers` counts those
two). The league's own bounds are ranges (2-6 goalkeepers, 23-40 players),
so every bucket is carried as a (low, high) pair either way, and a
session's exact count is the pair (n, n).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import duckdb

from fantaclaude.values import is_number

GAME_CLASSIC = 1
GAME_MANTRA = 2
Bounds = tuple[int, int]


class SessionError(ValueError):
    """The settings lack a number the board cannot be priced without, or carry a shape this reader does not know."""


@dataclass(frozen=True)
class SessionSettings:
    budget: int
    goalkeepers: Bounds
    outfield: Bounds
    size: Bounds
    game: int
    team_count: int
    source: str                              # "session" | "league"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mantra(self) -> bool:
        return self.game == GAME_MANTRA

    def to_dict(self) -> dict[str, Any]:
        return {"budget": self.budget, "goalkeepers": list(self.goalkeepers), "outfield": list(self.outfield),
                "size": list(self.size), "game": self.game, "team_count": self.team_count, "source": self.source}


def _count(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SessionError(f"{where} is {value!r}; expected a count")
    return value


def _pair(roles: Mapping[str, Any], key: str, game: int) -> Bounds:
    """One bucket of settings.roles as (low, high): a [classic, mantra] pair
    read by the game in play, or a bare count for either game."""
    value = roles.get(key)
    if isinstance(value, list) and len(value) == 2:
        n = _count(value[1 if game == GAME_MANTRA else 0], f"settings.roles.{key}")
        return n, n
    if isinstance(value, int) and not isinstance(value, bool):
        n = _count(value, f"settings.roles.{key}")
        return n, n
    raise SessionError(f"settings.roles.{key} is {value!r}; expected a [classic, mantra] pair of counts")


def session_from_feed(settings: Mapping[str, Any], *, team_count: int) -> SessionSettings:
    budget = settings.get("budget")
    if not is_number(budget) or budget < 0:
        raise SessionError(f"settings.budget is {budget!r}; expected the credits per team")
    game = settings.get("game")
    if game not in (GAME_CLASSIC, GAME_MANTRA):
        raise SessionError(f"settings.game is {game!r}; expected {GAME_CLASSIC} (classic) or {GAME_MANTRA} (Mantra)")
    roles = settings.get("roles")
    if not isinstance(roles, Mapping):
        raise SessionError(f"settings.roles is {roles!r}; expected the per-bucket counts")
    gk, mov, size = _pair(roles, "gk", game), _pair(roles, "mov", game), _pair(roles, "size", game)
    if size[0] != gk[0] + mov[0]:
        raise SessionError(f"settings.roles.size {size[0]} is not gk {gk[0]} + mov {mov[0]}")
    return SessionSettings(int(budget), gk, mov, size, int(game), int(team_count), "session", dict(settings))


def session_from_league(*, budget: int, team_count: int, roster_min: int, roster_max: int,
                        minrl: list[int], maxrl: list[int]) -> SessionSettings:
    """The league's own bounds, read the way the design reads `sroles: 2`:
    minrl / maxrl are [goalkeepers, outfield]."""
    return SessionSettings(int(budget), (int(minrl[0]), int(maxrl[0])), (int(minrl[1]), int(maxrl[1])),
                           (int(roster_min), int(roster_max)), GAME_MANTRA, int(team_count), "league")


def league_bounds(con: duckdb.DuckDBPyConnection, snapshot_id: int) -> SessionSettings:
    """The settings row a run was priced under, as bounds."""
    row = con.execute("SELECT budget, team_count, roster_min, roster_max, payload FROM league_settings "
                      "WHERE snapshot_id = ?", [snapshot_id]).fetchone()
    if row is None:
        raise SessionError(f"league_settings has no snapshot {snapshot_id}")
    payload = row[4] if isinstance(row[4], dict) else json.loads(row[4])
    rosters = payload.get("rosters") or {}
    minrl, maxrl = rosters.get("minrl") or [], rosters.get("maxrl") or []
    if any(v is None for v in row[:4]) or len(minrl) < 2 or len(maxrl) < 2:
        raise SessionError(f"league_settings snapshot {snapshot_id} lacks the budget, the team count or the roster bounds")
    return session_from_league(budget=row[0], team_count=row[1], roster_min=row[2], roster_max=row[3],
                               minrl=minrl, maxrl=maxrl)


def _span(bounds: Bounds) -> str:
    return str(bounds[0]) if bounds[0] == bounds[1] else f"{bounds[0]}-{bounds[1]}"


def compare(session: SessionSettings, league: SessionSettings) -> list[str]:
    """What the session plays that the league's settings do not allow --
    surfaced loudly at connect, before bidding opens; the session wins for
    the night (spec, "Session settings are authoritative for the night")."""
    out: list[str] = []
    if session.budget != league.budget:
        out.append(f"budget: the session plays {session.budget} credits, the league says {league.budget}")
    if session.team_count != league.team_count:
        out.append(f"teams: {session.team_count} in the session, {league.team_count} in the league")
    if not session.is_mantra:
        out.append(f"game: the session is game {session.game}, the league is Mantra ({GAME_MANTRA})")
    for name, ours, theirs in (("goalkeepers", session.goalkeepers, league.goalkeepers),
                               ("outfield", session.outfield, league.outfield), ("roster", session.size, league.size)):
        if ours[0] < theirs[0] or ours[1] > theirs[1]:
            out.append(f"{name}: the session fills {_span(ours)}, the league allows {_span(theirs)}")
    return out
```

- [ ] **Step 5: Write `state.py`**

Create `core/src/fantaclaude/asta/state.py`:

```python
"""The auction as the feed describes it -- picks, the lot on the block, the
teams, the settings -- and the set-diff that turns one snapshot into events
(spec, "The adapter, and the rules that keep it safe").

The state is a pure function of the last snapshot: apply_snapshot returns
the state that snapshot describes and the events that separate it from the
state before -- adds, removals (the admin undid a lot), cost edits, the lot
changing, the settings changing, the session's status changing. Applying
the same snapshot twice is a no-op, and any sequence of snapshots ends
where replaying only the last one would, which is what makes reconnects
and replays safe for free. Nothing here corrects anything: whatever the
admin records is what the board shows (spec, "The mirror is faithful").

Credits are derived from picks, never read from teams[].currentBudget
(observed 2026-08-23: after 181 credits spent the mirrored field still read
500). A pick's playerId is the listone id (spec, open question 8), so the
advisor names a player from the pinned run and never fuzzy-matches; a pick
it cannot name is a fault it surfaces. Nicks are scrubbed here, at
ingestion: an @-shaped label is replaced by the team id before it can reach
a state file, a dashboard or a tool result.

The node shape is the spec's (`picks[] {playerId, teamId, cost, value,
index, timestamp}`, `selectedPlayerId`, `turnTeamId`, `status`, `locked`,
`teams[]`, `settings`, `options`, `pickOrder`, `hostId`, `playerListHash`);
of a pick only playerId, teamId and cost are consumed -- `value` is what
FantaAstaLive lists him at, and `cost` is what was paid. Firebase returns a
list with holes as an object keyed by index, so both shapes are read.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fantaclaude.league.settings import EMAIL_PATTERN, diff_payloads


class SnapshotError(ValueError):
    """The node is not the shape the mirror reads; the message names the field."""


@dataclass(frozen=True)
class Pick:
    player_id: int
    team_id: int
    cost: int
    index: int
    timestamp: int | None = None

    def to_node(self) -> dict[str, Any]:
        """The feed's own shape, so a state file reloads through parse_snapshot."""
        return {"playerId": self.player_id, "teamId": self.team_id, "cost": self.cost, "index": self.index,
                "timestamp": self.timestamp}


@dataclass(frozen=True)
class Team:
    team_id: int
    label: str                     # scrubbed: never an email address

    def to_node(self) -> dict[str, Any]:
        return {"id": self.team_id, "connection": {"label": self.label}}


@dataclass(frozen=True)
class Snapshot:
    picks: tuple[Pick, ...]
    teams: tuple[Team, ...]
    settings: dict[str, Any]
    selected: int | None = None
    turn_team: int | None = None
    status: str | None = None
    locked: bool | None = None
    player_list_hash: str | None = None

    def to_node(self) -> dict[str, Any]:
        return {"picks": [p.to_node() for p in self.picks], "teams": [t.to_node() for t in self.teams],
                "settings": dict(self.settings), "selectedPlayerId": self.selected, "turnTeamId": self.turn_team,
                "status": self.status, "locked": self.locked, "playerListHash": self.player_list_hash}


def scrub_label(label: Any, team_id: int) -> str:
    """A team's display name: whatever someone typed, unless it has the shape
    of an email address or is empty, in which case the team id stands in."""
    text = label.strip() if isinstance(label, str) else ""
    if not text or EMAIL_PATTERN.search(text):
        return f"team {team_id}"
    return text


def _int(value: Any, where: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotError(f"{where} is {value!r}; expected an integer")
    if minimum is not None and value < minimum:
        raise SnapshotError(f"{where} is {value!r}; expected at least {minimum}")
    return value


def _optional_int(value: Any, where: str) -> int | None:
    return None if value is None else _int(value, where)


def _entries(value: Any, where: str) -> list[Any]:
    """A Firebase list: an array, or an object keyed by index when the array
    had holes. None entries are holes and are skipped."""
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v is not None]
    if isinstance(value, Mapping):
        try:
            keys = sorted(value, key=int)
        except (TypeError, ValueError):
            raise SnapshotError(f"{where} is keyed by {list(value)[:3]}; expected list indexes") from None
        return [value[k] for k in keys if value[k] is not None]
    raise SnapshotError(f"{where} is {type(value).__name__}; expected a list")


def parse_snapshot(node: Mapping[str, Any]) -> Snapshot:
    if not isinstance(node, Mapping):
        raise SnapshotError("the state node is not a mapping")
    picks: list[Pick] = []
    for i, raw in enumerate(_entries(node.get("picks"), "picks")):
        if not isinstance(raw, Mapping):
            raise SnapshotError(f"picks[{i}] is {raw!r}; expected a mapping")
        picks.append(Pick(_int(raw.get("playerId"), f"picks[{i}].playerId"),
                          _int(raw.get("teamId"), f"picks[{i}].teamId"),
                          _int(raw.get("cost"), f"picks[{i}].cost", minimum=0),
                          _int(raw.get("index", i), f"picks[{i}].index"),
                          _optional_int(raw.get("timestamp"), f"picks[{i}].timestamp")))
    teams: list[Team] = []
    for i, raw in enumerate(_entries(node.get("teams"), "teams")):
        if not isinstance(raw, Mapping):
            raise SnapshotError(f"teams[{i}] is {raw!r}; expected a mapping")
        team_id = _int(raw.get("id"), f"teams[{i}].id")
        connection = raw.get("connection") if isinstance(raw.get("connection"), Mapping) else {}
        teams.append(Team(team_id, scrub_label(connection.get("label") or raw.get("nick") or raw.get("name"), team_id)))
    settings = node.get("settings")
    if settings is not None and not isinstance(settings, Mapping):
        raise SnapshotError(f"settings is {type(settings).__name__}; expected a mapping")
    locked = node.get("locked")
    if locked is not None and not isinstance(locked, bool):
        raise SnapshotError(f"locked is {locked!r}; expected a boolean")
    status = node.get("status")
    list_hash = node.get("playerListHash")
    return Snapshot(tuple(sorted(picks, key=lambda p: (p.index, p.player_id))),
                    tuple(sorted(teams, key=lambda t: t.team_id)), dict(settings or {}),
                    _optional_int(node.get("selectedPlayerId"), "selectedPlayerId"),
                    _optional_int(node.get("turnTeamId"), "turnTeamId"),
                    None if status is None else str(status), locked, list_hash if isinstance(list_hash, str) else None)


def read_snapshots(path: Path) -> list[Snapshot]:
    """One state node per line (JSON lines): the shape a captured session replays through."""
    out: list[Snapshot] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            node = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"{path}:{number}: {exc}") from None
        try:
            out.append(parse_snapshot(node))
        except SnapshotError as exc:
            raise SnapshotError(f"{path}:{number}: {exc}") from None
    return out


@dataclass(frozen=True)
class AuctionState:
    picks: dict[int, Pick]                 # by player_id: a player is sold once
    teams: tuple[Team, ...]
    settings: dict[str, Any]
    selected: int | None = None
    turn_team: int | None = None
    status: str | None = None
    locked: bool | None = None
    player_list_hash: str | None = None
    duplicates: tuple[int, ...] = ()       # listed twice in one snapshot: the last pick by index stood, and the board says so

    @classmethod
    def empty(cls) -> AuctionState:
        return cls({}, (), {})

    def team_ids(self) -> tuple[int, ...]:
        return tuple(sorted({t.team_id for t in self.teams} | {p.team_id for p in self.picks.values()}))

    def picks_of(self, team_id: int) -> tuple[Pick, ...]:
        return tuple(sorted((p for p in self.picks.values() if p.team_id == team_id), key=lambda p: (p.index, p.player_id)))

    def spent(self, team_id: int) -> int:
        return sum(p.cost for p in self.picks.values() if p.team_id == team_id)

    def to_snapshot(self) -> Snapshot:
        return Snapshot(tuple(sorted(self.picks.values(), key=lambda p: (p.index, p.player_id))), self.teams,
                        dict(self.settings), self.selected, self.turn_team, self.status, self.locked, self.player_list_hash)


@dataclass(frozen=True)
class SaleAdded:
    player_id: int
    team_id: int
    cost: int


@dataclass(frozen=True)
class SaleRemoved:
    player_id: int
    team_id: int
    cost: int


@dataclass(frozen=True)
class CostEdited:
    player_id: int
    team_id: int
    before: int
    after: int


@dataclass(frozen=True)
class LotSelected:
    player_id: int | None


@dataclass(frozen=True)
class SettingsChanged:
    changes: tuple[tuple[str, Any, Any], ...]      # (dotted path, before, after), as sync-league reports a rules change


@dataclass(frozen=True)
class StatusChanged:
    status: str | None
    locked: bool | None


Event = SaleAdded | SaleRemoved | CostEdited | LotSelected | SettingsChanged | StatusChanged


def state_from_snapshot(snap: Snapshot) -> AuctionState:
    picks: dict[int, Pick] = {}
    duplicates: set[int] = set()
    for pick in snap.picks:                     # sorted by index: the later pick of a player listed twice stands
        if pick.player_id in picks:
            duplicates.add(pick.player_id)
        picks[pick.player_id] = pick
    return AuctionState(picks, snap.teams, dict(snap.settings), snap.selected, snap.turn_team, snap.status, snap.locked,
                        snap.player_list_hash, tuple(sorted(duplicates)))


def apply_snapshot(state: AuctionState, snap: Snapshot) -> tuple[AuctionState, tuple[Event, ...]]:
    """The state the snapshot describes, and what separates it from `state`.
    Pure: the new state carries nothing of the old one, so a replay of every
    snapshot and a replay of the last alone agree; the events are the
    difference, in a deterministic order (by player id)."""
    new = state_from_snapshot(snap)
    events: list[Event] = []
    for pid in sorted(set(state.picks) | set(new.picks)):
        before, after = state.picks.get(pid), new.picks.get(pid)
        if after is None:
            events.append(SaleRemoved(pid, before.team_id, before.cost))
        elif before is None:
            events.append(SaleAdded(pid, after.team_id, after.cost))
        elif before.team_id != after.team_id:
            events.append(SaleRemoved(pid, before.team_id, before.cost))
            events.append(SaleAdded(pid, after.team_id, after.cost))
        elif before.cost != after.cost:
            events.append(CostEdited(pid, after.team_id, before.cost, after.cost))
    if new.selected != state.selected:
        events.append(LotSelected(new.selected))
    if state.settings and new.settings != state.settings:      # the first snapshot's settings are the baseline
        events.append(SettingsChanged(tuple((c.path, c.before, c.after) for c in diff_payloads(state.settings, new.settings))))
    if (new.status, new.locked) != (state.status, state.locked):
        events.append(StatusChanged(new.status, new.locked))
    return new, tuple(events)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_session.py core/tests/test_state.py -q`
Expected: PASS, 13 tests. `uv run pytest core/tests -q` → 382 passed.

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/asta/session.py core/src/fantaclaude/asta/state.py core/tests/fixtures/_extract_asta.py core/tests/fixtures/asta_session_sample.jsonl core/tests/test_session.py core/tests/test_state.py
git commit -m "feat(asta): the state machine -- session settings as bounds, the feed's snapshot, and the set-diff into events"
```

---

### Task 5: The adjustment layer — `data/adjustments.yml`, appended atomically, resolved loudly

**Files:**
- Create: `core/src/fantaclaude/atomic.py`, `core/src/fantaclaude/asta/adjustments.py`
- Test: `core/tests/test_atomic.py`, `core/tests/test_adjustments.py`

**Interfaces:**
- Consumes: `asta.pricing.PoolPlayer`; `ingest.names.match_listone`, `Candidate`, `Match`, `AMBIGUOUS`; `model.demand.ROLE_CLASSES`; `values.is_number`.
- Produces: `atomic.write_atomic(path, data: bytes, *, mode=0o644) -> None`; `adjustments.KINDS`, `FACTOR_RANGE`, `HEADER`; `Adjustment(kind, reason, player=None, player_id=None, factor=None, role_class=None, count=None)` with `.to_entry()`, `.describe()`; `AdjustmentsError`; `adjustment_from_entry(raw, where) -> Adjustment` (public: `asta adjust` builds an entry from flags and validates it the same way); `parse_adjustments(text, *, where="adjustments.yml") -> list[Adjustment]`; `load_adjustments(path) -> list[Adjustment]` (no file → `[]`); `file_sha256(path) -> str` (`""` when missing); `render_entry(adjustment) -> str`; `append_adjustment(path, adjustment) -> list[Adjustment]`; `Resolved(adjustment, player_id, note=None)`; `AdjustmentLayer(entries, value_factor: dict[int, float], excluded: frozenset[int], targets: dict[str, int], problems: tuple[str, ...], sha256="")` with `.factor(player_id)`, `.to_dict()`; `EMPTY_LAYER`; `resolve(adjustments, candidates, *, sha256="") -> AdjustmentLayer`; `apply_layer(pool, layer) -> tuple[PoolPlayer, ...]`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_atomic.py`:

```python
import os

import pytest
from fantaclaude.atomic import write_atomic


def test_write_atomic_replaces_the_file_whole_and_leaves_no_temp_behind(tmp_path):
    path = tmp_path / "deep" / "state.json"
    write_atomic(path, b'{"a": 1}')
    assert path.read_bytes() == b'{"a": 1}' and (path.stat().st_mode & 0o777) == 0o644
    write_atomic(path, b'{"a": 2}', mode=0o600)
    assert path.read_bytes() == b'{"a": 2}' and (path.stat().st_mode & 0o777) == 0o600
    assert sorted(p.name for p in path.parent.iterdir()) == ["state.json"]


def test_a_failed_replace_leaves_the_old_file_standing(tmp_path, monkeypatch):
    """The state file is the only record of what the room paid between the
    auction and the transfer: a crash mid-write must cost nothing."""
    path = tmp_path / "state.json"
    write_atomic(path, b"old")

    def boom(src, dst):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_atomic(path, b"new")
    assert path.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]       # the temp file is cleaned up too
```

Create `core/tests/test_adjustments.py`:

```python
import json

import pytest
from fantaclaude.asta.adjustments import (
    EMPTY_LAYER,
    Adjustment,
    AdjustmentLayer,
    AdjustmentsError,
    append_adjustment,
    apply_layer,
    file_sha256,
    load_adjustments,
    parse_adjustments,
    resolve,
)
from fantaclaude.asta.pricing import PoolPlayer
from fantaclaude.ingest.names import Candidate

EXAMPLE = """\
- player: Malen             # the listone's spelling, or player_id: 1234
  type: exclude
  reason: not buying him
- player: Bastoni
  type: value
  factor: 0.85              # (0, 2]
  reason: limping, reported in the room
- type: target
  class: Dc                 # a role class
  count: 4                  # the composition to start from
  reason: go heavier on Dc
"""

CANDIDATES = [Candidate(2764, "Martinez L.", "INT", "Inter"), Candidate(2120, "Bastoni", "INT", "Inter"),
              Candidate(5841, "Svilar", "ROM", "Roma"), Candidate(11, "Rossi", "GEN", "Genoa"),
              Candidate(12, "Rossi", "PAR", "Parma"), Candidate(13, "Malen", "ATA", "Atalanta")]


def test_the_documented_file_parses_into_three_kinds():
    got = parse_adjustments(EXAMPLE)
    assert got == [Adjustment("exclude", "not buying him", player="Malen"),
                   Adjustment("value", "limping, reported in the room", player="Bastoni", factor=0.85),
                   Adjustment("target", "go heavier on Dc", role_class="Dc", count=4)]
    assert [a.describe() for a in got] == ["exclude Malen (not buying him)", "value Bastoni x0.85 (limping, reported in the room)",
                                           "target Dc 4 (go heavier on Dc)"]
    assert got[1].to_entry() == {"player": "Bastoni", "type": "value", "factor": 0.85, "reason": "limping, reported in the room"}
    assert parse_adjustments("") == [] and parse_adjustments("# only a comment\n") == []
    assert Adjustment("exclude", "r", player_id=7).describe() == "exclude player_id 7 (r)"


def test_every_malformed_entry_is_refused_by_name():
    for text, match in (("- {player: X, type: bench, reason: r}", "type must be one of"),
                        ("- {player: X, type: exclude}", "reason"), ("- {player: X, type: exclude, reason: '  '}", "reason"),
                        ("- {player: X, type: value, reason: r}", "factor"), ("- {player: X, type: value, factor: 0, reason: r}", "factor"),
                        ("- {player: X, type: value, factor: 2.5, reason: r}", "factor"),
                        ("- {player: X, type: value, factor: heavy, reason: r}", "factor"),
                        ("- {player: X, type: exclude, factor: 0.5, reason: r}", "factor belongs"),
                        ("- {type: target, count: 4, reason: r}", "class must be"), ("- {type: target, class: Xy, count: 4, reason: r}", "class"),
                        ("- {type: target, class: Dc, count: -1, reason: r}", "count"), ("- {type: target, class: Dc, count: 2.5, reason: r}", "count"),
                        ("- {type: target, class: Dc, count: 4, player: X, reason: r}", "names a class"),
                        ("- {player: X, type: exclude, class: Dc, reason: r}", "belong to a target"),
                        ("- {player: X, type: exclude, foo: 1, reason: r}", "unknown key"),
                        ("- {player: X, player_id: 3, type: exclude, reason: r}", "name the player once"),
                        ("- {type: exclude, reason: r}", "name the player once"), ("- {player: '', type: exclude, reason: r}", "spelling"),
                        ("- {player_id: true, type: exclude, reason: r}", "player_id"), ("- {player_id: -1, type: exclude, reason: r}", "player_id"),
                        ("- 5", "must be a mapping"), ("player: X", "top level must be a list"), ("- {player: X, type: [", "adjustments.yml")):
        with pytest.raises(AdjustmentsError, match=match):
            parse_adjustments(text)
    with pytest.raises(AdjustmentsError, match="entry 2"):
        parse_adjustments("- {player: X, type: exclude, reason: r}\n- {player: Y, type: nope, reason: r}\n")


def test_append_keeps_the_text_and_replaces_atomically(tmp_path):
    path = tmp_path / "data" / "adjustments.yml"
    assert load_adjustments(path) == [] and file_sha256(path) == ""
    first = append_adjustment(path, Adjustment("exclude", "not buying him", player="Malen"))
    assert first == [Adjustment("exclude", "not buying him", player="Malen")]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# adjustments.yml") and "- player: Malen\n  type: exclude\n  reason: not buying him\n" in text
    path.write_text(text + "# a hand-written note stays\n", encoding="utf-8")
    second = append_adjustment(path, Adjustment("value", "limping", player="Bastoni", factor=0.85))
    assert second == first + [Adjustment("value", "limping", player="Bastoni", factor=0.85)]
    assert "# a hand-written note stays" in path.read_text(encoding="utf-8")
    assert load_adjustments(path) == second and len(file_sha256(path)) == 64
    assert sorted(p.name for p in path.parent.iterdir()) == ["adjustments.yml"]       # no temp file left behind
    third = append_adjustment(path, Adjustment("target", "go heavier", role_class="Dc", count=4))
    assert third[-1].to_entry() == {"type": "target", "class": "Dc", "count": 4, "reason": "go heavier"}
    # a file someone broke by hand is not appended to: the append would have hidden the break
    path.write_text("- {player: X, type: nope, reason: r}\n", encoding="utf-8")
    with pytest.raises(AdjustmentsError, match="entry 1"):
        append_adjustment(path, Adjustment("exclude", "r", player="Malen"))
    assert path.read_text(encoding="utf-8") == "- {player: X, type: nope, reason: r}\n"
    with pytest.raises(AdjustmentsError):
        load_adjustments(path)


def test_resolve_binds_names_to_the_run_and_names_what_it_cannot():
    adjustments = parse_adjustments(EXAMPLE) + parse_adjustments(
        "- {player: Nobody, type: exclude, reason: r}\n- {player: Rossi, type: value, factor: 0.5, reason: r}\n"
        "- {player_id: 424242, type: exclude, reason: r}\n- {player: Bastoni, type: value, factor: 0.7, reason: later wins}\n"
        "- {player: 'Rossi M.', type: exclude, reason: r}\n- {type: target, class: Dc, count: 3, reason: later wins}\n")
    layer = resolve(adjustments, CANDIDATES, sha256="abc")
    assert layer.excluded == {13} and layer.value_factor == {2120: 0.7} and layer.targets == {"Dc": 3}    # later entries win
    assert layer.factor(2120) == 0.7 and layer.factor(2764) == 1.0 and layer.sha256 == "abc"
    assert len(layer.problems) == 4
    assert "'Nobody' is not in the pinned run" in layer.problems[0] and "inert" in layer.problems[0]
    assert "'Rossi' is 2 players of the run ('Rossi', 'Rossi'); add the initial" in layer.problems[1]     # two clubs, no initial
    assert "player_id 424242 is not in the pinned run" in layer.problems[2]
    assert "'Rossi M.' is not how the listone spells 'Rossi', 'Rossi'" in layer.problems[3]
    assert [e.player_id for e in layer.entries] == [13, 2120, None, None, None, None, 2120, None, None]
    d = json.loads(json.dumps(layer.to_dict()))
    assert d["count"] == 9 and d["applied"] == 5 and d["excluded"] == [13] and d["value_factor"] == {"2120": 0.7}
    assert EMPTY_LAYER == AdjustmentLayer((), {}, frozenset(), {}, ()) and resolve([], CANDIDATES) == EMPTY_LAYER


def test_apply_layer_scales_the_three_quantiles_together():
    pool = (PoolPlayer(2120, "Bastoni", "Dc", 80.0, 100.0, 120.0, 14), PoolPlayer(2764, "Martinez L.", "Pc", 200.0, 240.0, 280.0, 35))
    layer = resolve([Adjustment("value", "limping", player="Bastoni", factor=0.85)], CANDIDATES)
    scaled = apply_layer(pool, layer)
    assert scaled[0] == PoolPlayer(2120, "Bastoni", "Dc", 68.0, 85.0, 102.0, 14) and scaled[1] == pool[1]
    assert apply_layer(pool, EMPTY_LAYER) is pool
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_atomic.py core/tests/test_adjustments.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'fantaclaude.atomic'`.

- [ ] **Step 3: Write `atomic.py`**

Create `core/src/fantaclaude/atomic.py`:

```python
"""One way to write a file the auction cannot afford to tear.

From the moment the admin closes FantaAstaLive until the transfer into the
lega is confirmed, data/asta-state.json is the only record of what the
room paid, and data/adjustments.yml is the one shared file three surfaces
write. Both are written the way the MCP writes its token cache: a temp file
in the target's own directory, fsynced, then os.replace over the target --
a reader sees the old file or the new one and never a torn one, and a
crash mid-write leaves the old file standing.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Write `adjustments.py`**

Create `core/src/fantaclaude/asta/adjustments.py`:

```python
"""Live adjustments: my beliefs and preferences, applied on top of the pinned
valuation and never inside it (spec, "Live adjustments").

Three kinds with different mechanics. `value` scales a player's projection
by a factor -- p25, p50 and p75 together, so a fitness doubt shrinks the
upside as well as the mean. `exclude` removes him from *my* completion
pool, which raises everyone else at his class through V and lowers nobody.
`target` edits the composition the optimiser starts from: a soft prior it
may depart from, never a bound, and the board reports the departure. Every
entry carries a reason, so the auction record explains itself afterwards.

data/adjustments.yml is a list; the file is mine, hand-editable, and it
outlives the auction. Three surfaces append to it (this module today; an
MCP tool and the dashboard in 2b), so appending is text-first -- the new
entry is rendered and added after the existing text, comments and all --
and the replacement is atomic. A malformed file is an AdjustmentsError the
caller reports while the previous layer stands; a player the pinned run
cannot resolve is a problem the layer names and the entry is inert. Both
are surfaced, never silent (spec, "Name matching"). A later entry for the
same player and kind wins.

    - player: Malen             # the listone's spelling, or player_id: 1234
      type: exclude
      reason: not buying him
    - player: Bastoni
      type: value
      factor: 0.85              # (0, 2]
      reason: limping, reported in the room
    - type: target
      class: Dc                 # a role class
      count: 4                  # the composition to start from
      reason: go heavier on Dc
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.asta.pricing import PoolPlayer
from fantaclaude.atomic import write_atomic
from fantaclaude.ingest.names import AMBIGUOUS, Candidate, Match, match_listone
from fantaclaude.model.demand import ROLE_CLASSES
from fantaclaude.values import is_number

KINDS = ("value", "exclude", "target")
FACTOR_RANGE = (0.0, 2.0)             # exclusive of 0
KEYS = frozenset({"player", "player_id", "type", "factor", "class", "count", "reason"})
HEADER = "# adjustments.yml -- my beliefs and preferences for the auction (fantaclaude asta adjust)\n"


class AdjustmentsError(ValueError):
    """adjustments.yml is malformed; the message names the entry."""


@dataclass(frozen=True)
class Adjustment:
    kind: str
    reason: str
    player: str | None = None
    player_id: int | None = None
    factor: float | None = None
    role_class: str | None = None
    count: int | None = None

    def to_entry(self) -> dict[str, Any]:
        """The file's own shape, keys in reading order."""
        entry: dict[str, Any] = {}
        if self.player is not None:
            entry["player"] = self.player
        if self.player_id is not None:
            entry["player_id"] = self.player_id
        entry["type"] = self.kind
        if self.kind == "value":
            entry["factor"] = self.factor
        if self.kind == "target":
            entry["class"], entry["count"] = self.role_class, self.count
        entry["reason"] = self.reason
        return entry

    def describe(self) -> str:
        who = self.player if self.player is not None else f"player_id {self.player_id}"
        if self.kind == "target":
            return f"target {self.role_class} {self.count} ({self.reason})"
        if self.kind == "value":
            return f"value {who} x{self.factor:g} ({self.reason})"
        return f"exclude {who} ({self.reason})"


def adjustment_from_entry(raw: Any, where: str) -> Adjustment:
    """One entry of the file (or of `asta adjust`'s flags) validated into an Adjustment; the message names `where`."""
    if not isinstance(raw, dict):
        raise AdjustmentsError(f"{where}: must be a mapping, got {raw!r}")
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise AdjustmentsError(f"{where}: unknown key(s) {unknown}; known: {sorted(KEYS)}")
    kind = raw.get("type")
    if kind not in KINDS:
        raise AdjustmentsError(f"{where}: type must be one of {KINDS}, got {kind!r}")
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise AdjustmentsError(f"{where}: reason must say why -- the auction record explains itself afterwards")
    player, player_id = raw.get("player"), raw.get("player_id")
    if kind == "target":
        if player is not None or player_id is not None:
            raise AdjustmentsError(f"{where}: a target names a class, not a player")
        cls, count = raw.get("class"), raw.get("count")
        if cls not in ROLE_CLASSES:
            raise AdjustmentsError(f"{where}: class must be one of {ROLE_CLASSES}, got {cls!r}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise AdjustmentsError(f"{where}: count must be a whole number of players, got {count!r}")
        return Adjustment(kind, reason.strip(), role_class=cls, count=count)
    if (player is None) == (player_id is None):
        raise AdjustmentsError(f"{where}: name the player once -- `player` (the listone's spelling) or `player_id`")
    if player is not None and (not isinstance(player, str) or not player.strip()):
        raise AdjustmentsError(f"{where}: player must be the listone's spelling, got {player!r}")
    if player_id is not None and (isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0):
        raise AdjustmentsError(f"{where}: player_id must be the listone id, got {player_id!r}")
    if raw.get("class") is not None or raw.get("count") is not None:
        raise AdjustmentsError(f"{where}: class and count belong to a target")
    factor = raw.get("factor")
    if kind == "value":
        if not is_number(factor) or not FACTOR_RANGE[0] < float(factor) <= FACTOR_RANGE[1]:
            raise AdjustmentsError(f"{where}: factor must be a number in (0, {FACTOR_RANGE[1]:g}], got {factor!r}")
        factor = float(factor)
    elif factor is not None:
        raise AdjustmentsError(f"{where}: factor belongs to a value adjustment")
    return Adjustment(kind, reason.strip(), player=player.strip() if player else None, player_id=player_id, factor=factor)


def parse_adjustments(text: str, *, where: str = "adjustments.yml") -> list[Adjustment]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AdjustmentsError(f"{where}: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, list):
        raise AdjustmentsError(f"{where}: the top level must be a list of adjustments")
    return [adjustment_from_entry(raw, f"{where}: entry {i + 1}") for i, raw in enumerate(data)]


def load_adjustments(path: Path) -> list[Adjustment]:
    """The file's entries; no file is no adjustments."""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AdjustmentsError(f"{path}: {exc}") from None
    return parse_adjustments(text, where=str(path))


def file_sha256(path: Path) -> str:
    """The layer's stamp for the state file: which adjustments.yml a board was priced under."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def render_entry(adjustment: Adjustment) -> str:
    return yaml.safe_dump([adjustment.to_entry()], sort_keys=False, allow_unicode=True, default_flow_style=False)


def append_adjustment(path: Path, adjustment: Adjustment) -> list[Adjustment]:
    """Reread, append, replace atomically -- one writer per append whatever
    the surface. Text-first, so a hand-written comment survives; the whole
    file is re-parsed before it is written, so the file the next refresh
    reads is known good, and a file that is already malformed is not
    appended to (the hand edit that broke it is a person's to fix)."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    parse_adjustments(existing, where=str(path))
    text = HEADER if not existing.strip() else existing if existing.endswith("\n") else existing + "\n"
    text += render_entry(adjustment)
    result = parse_adjustments(text, where=str(path))
    write_atomic(path, text.encode("utf-8"))
    return result


@dataclass(frozen=True)
class Resolved:
    adjustment: Adjustment
    player_id: int | None
    note: str | None = None            # why the entry is inert, when it is


@dataclass(frozen=True)
class AdjustmentLayer:
    entries: tuple[Resolved, ...]
    value_factor: dict[int, float]
    excluded: frozenset[int]
    targets: dict[str, int]
    problems: tuple[str, ...]
    sha256: str = ""

    def factor(self, player_id: int) -> float:
        return self.value_factor.get(player_id, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {"count": len(self.entries), "applied": sum(1 for e in self.entries if e.note is None),
                "value_factor": {str(k): v for k, v in sorted(self.value_factor.items())},
                "excluded": sorted(self.excluded), "targets": dict(self.targets), "problems": list(self.problems),
                "sha256": self.sha256}


EMPTY_LAYER = AdjustmentLayer((), {}, frozenset(), {}, ())


def _why(name: str, match: Match, candidates: list[Candidate]) -> str:
    named = {c.player_id: c.name for c in candidates}
    close = ", ".join(repr(named[i]) for i in match.candidates if i in named)
    if match.status == AMBIGUOUS:
        return f"{name!r} is {len(match.candidates)} players of the run ({close}); add the initial the listone uses"
    if match.candidates:
        return f"{name!r} is not how the listone spells {close}; use the listone's spelling"
    return f"{name!r} is not in the pinned run; write him the listone's way -- surname first, then the initial"


def resolve(adjustments: list[Adjustment], candidates: list[Candidate], *, sha256: str = "") -> AdjustmentLayer:
    """Bind every entry to the pinned run's players. An entry that resolves
    to nobody is inert and named in `problems`; nothing is dropped silently."""
    known = {c.player_id for c in candidates}
    entries: list[Resolved] = []
    factors: dict[int, float] = {}
    excluded: set[int] = set()
    targets: dict[str, int] = {}
    problems: list[str] = []
    for a in adjustments:
        if a.kind == "target":
            targets[a.role_class] = a.count
            entries.append(Resolved(a, None))
            continue
        if a.player_id is not None:
            pid = a.player_id if a.player_id in known else None
            note = None if pid is not None else f"player_id {a.player_id} is not in the pinned run"
        else:
            match = match_listone(a.player, candidates)
            pid = match.player_id
            note = None if pid is not None else _why(a.player, match, candidates)
        if pid is None:
            problems.append(f"{a.describe()}: {note}; the adjustment is inert")
        elif a.kind == "value":
            factors[pid] = a.factor
        else:
            excluded.add(pid)
        entries.append(Resolved(a, pid, note))
    return AdjustmentLayer(tuple(entries), factors, frozenset(excluded), targets, tuple(problems), sha256)


def apply_layer(pool: tuple[PoolPlayer, ...], layer: AdjustmentLayer) -> tuple[PoolPlayer, ...]:
    """The pool with every value factor applied to the three quantiles at
    once. Exclusion is not applied here: it is PoolState.excluded, which is
    what makes it reach V rather than annotate a row."""
    if not layer.value_factor:
        return pool
    out = []
    for p in pool:
        f = layer.value_factor.get(p.player_id)
        out.append(p if f is None else PoolPlayer(p.player_id, p.name, p.role_class, p.value_p25 * f, p.value_p50 * f,
                                                  p.value_p75 * f, p.quotazione))
    return tuple(out)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_atomic.py core/tests/test_adjustments.py -q`
Expected: PASS, 7 tests. `uv run pytest core/tests -q` → 389 passed.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/atomic.py core/src/fantaclaude/asta/adjustments.py core/tests/test_atomic.py core/tests/test_adjustments.py
git commit -m "feat(asta): the adjustment layer -- value, exclude and target entries, appended atomically, resolved against the run"
```

---

### Task 6: The pinned run, the advisor, and the one owner of state

**Files:**
- Create: `core/src/fantaclaude/asta/pinned.py`, `core/src/fantaclaude/asta/advisor.py`, `core/src/fantaclaude/asta/auction.py`
- Modify: `core/src/fantaclaude/model/demand.py:80-96` (`rank_weights` gains `min_ranks`), `core/src/fantaclaude/analysis/valuation.py` (the demand is stored per module and read in a stable order; `min_ranks=ctx.class_min`)
- Test: `core/tests/test_pinned.py`, `core/tests/test_advisor.py`, `core/tests/test_auction.py`, `core/tests/test_demand.py:67-68`

**Interfaces:**
- Consumes: Tasks 1–5; `analysis.valuation.load_scenarios`, `Scenario`, `UnknownScenarioError`, `PreferencesError`, `record_run`; `analysis.ordering.rank_key`; `model.demand.hard_minimums`, `module_demand`, `rank_weights`, `satisfiable_demand`; `model.roles.Role`; `kb.participants.Participant` (Task 8 only); the test helpers `test_valuation.seeded`, `test_valuation.run`, `test_valuation.PREFS`.
- Produces: `model.demand.rank_weights(..., min_ranks: Mapping[str, int] | None = None)`; `valuation_runs.config["demand_by_module"]` (module code → class → demand, module codes sorted); `pinned.PinnedPlayer(player_id, name, team_short, classic_role, role_class, roles, value_p25, value_p50, value_p75, quotazione, tier)` with `.is_goalkeeper`, `.pool_player()`, `.to_dict()`; `pinned.PinnedRun(run_id, created_at, rules_hash, model_hash, superseded, settings_snapshot_id, listone_snapshot_id, season_id, giornata, players, pricing_cfg, scenarios, demand, demand_rederived, hard_minimums, league: SessionSettings, prices: dict[str, dict[int, Band]], club_names)` with `.scenario(name=None)`, `.candidates()`, `.weights(targets, min_ranks)`, `.describe()`; `pinned.PinnedRunError`; `pinned.newest_run_id(con) -> str | None`; `pinned.load_pinned_run(con, run_id=None) -> PinnedRun`. `advisor.TeamMapping(mine, nicks: dict[int, str] = {})`; `advisor.Ledger(team_id, label, nick, budget, spent, picks, goalkeepers, outfield, unknown)` with `.credits`, `.missing(settings)`, `.room(settings)`, `.open_slots(settings)`, `.to_dict(settings)`; `advisor.Lot`; `advisor.Board(run_id, scenario, state, settings, league_conflicts, ledgers, mine, pool_state, pricing, selected, lot, layer, problems, players, club_names, pressure)` with `.me`, `.market_credits`, `.price_of(pid)`, `.tiers(n)`, `.to_dict()`; `advisor.build_ledgers(state, settings, run, mapping) -> (dict[int, Ledger], list[str])`; `advisor.build_pool_state(state, settings, run, layer, ledgers, mine, scenario_name=None) -> PoolState`; `advisor.derive(state, *, run, settings, layer=EMPTY_LAYER, mapping, scenario=None) -> Board`. `auction.Refresh(layer=None)`; `auction.MutationResult(events, board)`; `auction.Auction(run, mapping, *, settings=None, layer=EMPTY_LAYER, scenario=None)` with `.state`, `.settings`, `.layer`, `.board`, `.subscribe(listener)`, `.mutate(change) -> MutationResult`.

Two things the tests below forced, recorded so the executor does not rediscover them: a session that fills three goalkeepers gives `Por` a floor above the two ranks the module demand gives it, and the DP then has no legal completion (`-inf` everywhere) — so a class floor extends the rank weights the way a target does, at bench weight (`min_ranks`); and `rank_weights` sums floats over the modules, so the run stores its folded demand with the module codes sorted (the order `canonical_json` stores them in) and the live board reads it back in that order — otherwise the minute-zero board differs from the committed one in the last bit.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_demand.py`, after the two lines `extended = rank_weights(...targets={"Pc": 4})` / `assert extended["Pc"] == (0.8, 0.8, 0.8, 0.8)`, add:

```python
    # a class floor the roster must fill extends the ranks too, at bench weight: a forced third keeper is a bench keeper
    floored = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1, min_ranks={"Por": 3})
    assert floored["Por"] == (1.0, 0.1, 0.05) and floored["Pc"] == base["Pc"]
```

Create `core/tests/test_pinned.py`:

```python
import json

import pytest
from fantaclaude.analysis.valuation import UnknownScenarioError, record_run
from fantaclaude.asta.pinned import (
    PinnedRun,
    PinnedRunError,
    load_pinned_run,
    newest_run_id,
)
from fantaclaude.asta.pricing import PricingConfig
from fantaclaude.db.connection import connect
from test_valuation import PREFS, run, seeded


def recorded(tmp_path, fixture_json, mcp_fixture_json, **kw):
    """A seeded workspace with one run recorded; returns (the ValuationRun, an open read-write connection)."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path, **kw)
    record_run(con, result)
    return result, con


def test_load_pinned_run_reads_the_run_back(tmp_path, fixture_json, mcp_fixture_json):
    prefs = {**PREFS, "scenarios": {"value-hunting": {"risk_appetite": "cautious", "max_budget_share_per_role": {"Pc": 0.25}}}}
    result, con = recorded(tmp_path, fixture_json, mcp_fixture_json, preferences=prefs)
    try:
        assert newest_run_id(con) == result.run_id
        pinned = load_pinned_run(con)
        assert isinstance(pinned, PinnedRun) and pinned.run_id == result.run_id and not pinned.superseded
        assert pinned.rules_hash == result.rules_hash and pinned.model_hash == result.model_hash
        assert pinned.settings_snapshot_id == 1 and pinned.listone_snapshot_id == 1 and pinned.season_id == 21
        assert len(pinned.players) == 17
        lautaro = pinned.players[2764]
        projection = {p.player_id: p for p in result.projections}[2764]
        assert lautaro.name == "Martinez L." and lautaro.team_short == "INT" and lautaro.roles == ("Pc",)
        assert lautaro.role_class == "Pc" and not lautaro.is_goalkeeper and pinned.players[5841].is_goalkeeper
        assert (lautaro.value_p25, lautaro.value_p50, lautaro.value_p75) == (projection.value_p25, projection.value_p50, projection.value_p75)
        assert lautaro.quotazione == 35 and lautaro.tier == result.tiers[2764]
        assert lautaro.pool_player() == result.pool[[p.player_id for p in result.pool].index(2764)]
        assert pinned.pricing_cfg == PricingConfig() and [s.name for s in pinned.scenarios] == ["balanced", "value-hunting"]
        assert pinned.scenario().name == "balanced" and pinned.scenario("value-hunting").max_budget_share_per_role == {"Pc": 0.25}
        with pytest.raises(UnknownScenarioError, match="nope"):
            pinned.scenario("nope")
        assert pinned.demand == result.config["demand_by_module"] and not pinned.demand_rederived
        assert list(pinned.demand) == sorted(pinned.demand)                     # module-code order, as canonical_json stores it
        assert pinned.hard_minimums == {"Por": 1, "Dc": 2}
        assert (pinned.league.budget, pinned.league.team_count, pinned.league.goalkeepers, pinned.league.size) == (500, 8, (2, 6), (23, 40))
        assert pinned.league.source == "league"
        assert pinned.prices["balanced"][2764] == result.boards["balanced"].prices[2764].band
        assert pinned.prices["value-hunting"][2764] == result.boards["value-hunting"].prices[2764].band
        assert pinned.club_names["INT"] == "Inter" and pinned.club_names["ATA"] == "Atalanta"
        names = {c.player_id: c for c in pinned.candidates()}
        assert names[2764].name == "Martinez L." and names[2764].team_name == "Inter" and len(names) == 17
        assert result.run_id in pinned.describe() and "current" in pinned.describe()
        assert lautaro.to_dict()["roles"] == ["Pc"]
    finally:
        con.close()


def test_no_run_a_superseded_run_and_a_run_pinned_by_id(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    try:
        with pytest.raises(PinnedRunError, match="no valuation run to pin"):
            load_pinned_run(con)
        with pytest.raises(PinnedRunError, match="no valuation run 'nope'"):
            load_pinned_run(con, "nope")
    finally:
        con.close()
    result, con = run(tmp_path)
    record_run(con, result)
    try:
        # a rules change supersedes the run: nothing to pin without --run, but the run still loads by id and says so
        con.execute("INSERT INTO league_settings (fetched_at, league_id, season_id, matchday, rules_hash, team_count, budget, "
                    "roster_min, roster_max, modules, bench_size, substitutions, payload) SELECT fetched_at, league_id, "
                    "season_id, matchday, 'ffffffffffffffff', team_count, 600, roster_min, roster_max, modules, bench_size, "
                    "substitutions, payload FROM league_settings WHERE snapshot_id = 1")
        assert newest_run_id(con) is None
        with pytest.raises(PinnedRunError, match="superseded"):
            load_pinned_run(con)
        pinned = load_pinned_run(con, result.run_id)
        assert pinned.superseded and "superseded" in pinned.describe()
        assert pinned.league.budget == 500                    # the row the run was priced under, not the newest
    finally:
        con.close()


def test_a_run_recorded_before_demand_by_module_re_derives_it_and_says_so(tmp_path, fixture_json, mcp_fixture_json):
    result, con = recorded(tmp_path, fixture_json, mcp_fixture_json)
    try:
        config = json.loads(con.execute("SELECT config FROM valuation_runs WHERE run_id = ?", [result.run_id]).fetchone()[0])
        del config["demand_by_module"]
        con.execute("UPDATE valuation_runs SET config = ?::JSON WHERE run_id = ?", [json.dumps(config), result.run_id])
        pinned = load_pinned_run(con)
        assert pinned.demand_rederived and "re-derived" in pinned.describe()
        assert pinned.demand == {code: result.config["demand_by_module"][code] for code in sorted(result.config["demand_by_module"])}
        config["pricing"]["no_such_knob"] = 1
        con.execute("UPDATE valuation_runs SET config = ?::JSON WHERE run_id = ?", [json.dumps(config), result.run_id])
        with pytest.raises(PinnedRunError, match="cannot be read back"):
            load_pinned_run(con)
    finally:
        con.close()
```

Create `core/tests/test_advisor.py`:

```python
import json

import pytest
from fantaclaude.analysis.valuation import record_run
from fantaclaude.asta.adjustments import Adjustment, resolve
from fantaclaude.asta.advisor import Board, Ledger, TeamMapping, build_ledgers, derive
from fantaclaude.asta.pinned import load_pinned_run
from fantaclaude.asta.session import session_from_feed
from fantaclaude.asta.state import (
    AuctionState,
    apply_snapshot,
    parse_snapshot,
    read_snapshots,
)
from test_valuation import PREFS, run, seeded

SESSION = {"budget": 500, "game": 2, "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]}}


def pinned_run(tmp_path, fixture_json, mcp_fixture_json, **kw):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path, **kw)
    record_run(con, result)
    try:
        return result, load_pinned_run(con)
    finally:
        con.close()


def replayed(fixture_file, upto=None):
    state = AuctionState.empty()
    for snap in read_snapshots(fixture_file("asta_session_sample.jsonl"))[:upto]:
        state, _ = apply_snapshot(state, snap)
    return state


def node(picks, *, selected=None, teams=(0, 1, 2), settings=SESSION):
    """The state one synthetic snapshot describes."""
    snap = parse_snapshot({"picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i} for i, (pid, tid, cost) in enumerate(picks)],
                           "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams], "settings": settings,
                           "selectedPlayerId": selected, "status": "live", "locked": False})
    return apply_snapshot(AuctionState.empty(), snap)[0]


def test_the_live_board_at_minute_zero_reproduces_the_pinned_board(tmp_path, fixture_json, mcp_fixture_json):
    """One pricing function (spec): the run's committed board and the live
    board of an empty auction under the run's own league bounds are the same
    computation -- the same function, the same inputs, read back from the
    run's rows -- and agree band for band, inflation, composition and all."""
    prefs = {**PREFS, "scenarios": {"value-hunting": {"risk_appetite": "cautious", "max_budget_share_per_role": {"Pc": 0.25}}}}
    result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json, preferences=prefs)
    for scenario in ("balanced", "value-hunting"):
        board = derive(AuctionState.empty(), run=pinned, settings=pinned.league, mapping=TeamMapping(mine=0), scenario=scenario)
        assert isinstance(board, Board) and board.scenario == scenario and board.problems == () and board.league_conflicts == ()
        assert board.pricing.to_dict() == result.boards[scenario].to_dict()
        assert all(board.pricing.prices[pid].band == band for pid, band in pinned.prices[scenario].items())
        assert board.me.credits == 500 and board.market_credits == 4000 and len(board.ledgers) == 8
        assert board.pool_state.roster_min == 23 and board.pool_state.class_min == {"Por": 2} and board.pool_state.class_max == {"Por": 6}


def test_ledgers_follow_the_picks_and_name_what_the_run_cannot(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    state = replayed(fixture_file)
    settings = session_from_feed(state.settings, team_count=len(state.teams))
    board = derive(state, run=pinned, settings=settings, mapping=TeamMapping(mine=1, nicks={0: "Marco"}))
    host, me, third = board.ledgers[0], board.me, board.ledgers[2]
    assert isinstance(host, Ledger) and host.label == "host" and host.nick == "Marco" and host.spent == 165 and host.credits == 335
    assert [p.player_id for p in host.picks] == [2764, 2120] and host.goalkeepers == 0 and host.outfield == 2
    assert me.label == "Claude" and me.credits == 500 and me.picks == () and me.missing(settings) == (3, 22)
    assert third.label == "@bomber" and third.spent == 3 and third.unknown == 1 and third.outfield == 0
    assert board.market_credits == 335 + 500 + 497 and board.pool_state.credits == 500
    assert set(board.pricing.prices) == set(pinned.players) - {2764, 2120}          # the sold leave the pool
    assert len(board.problems) == 1 and "999999" in board.problems[0] and "@bomber" in board.problems[0]
    assert board.league_conflicts == ("teams: 3 in the session, 8 in the league",)
    assert board.selected is None and board.lot is None
    with_lot = derive(replayed(fixture_file, 6), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert with_lot.lot is not None and with_lot.lot.name == "Svilar" and with_lot.lot.role_class == "Por"
    assert with_lot.lot.band == with_lot.pricing.prices[5841].band and with_lot.lot.band.p50 > 0 and with_lot.lot.sold_to is None
    assert with_lot.problems == ()
    tiers = board.tiers(2)
    assert list(tiers) and all(len(rows) <= 2 for rows in tiers.values())
    assert tiers["Pc"][0]["band"]["p50"] >= tiers["Pc"][-1]["band"]["p50"] and "name" in tiers["Pc"][0]
    payload = json.loads(json.dumps(board.to_dict(), allow_nan=False))
    assert payload["me"]["credits"] == 500 and payload["teams"][0]["spent"] == 165 and payload["picks"] == 3
    assert payload["prices"]["5841"]["role_class"] == "Por" and "2764" not in payload["prices"]
    assert "@example" not in json.dumps(payload) and payload["adjustments"]["count"] == 0


def test_a_sale_to_me_and_a_lot_already_sold(tmp_path, fixture_json, mcp_fixture_json):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    settings = session_from_feed(SESSION, team_count=3)
    before = derive(node([]), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    after = derive(node([(5841, 1, 30)], selected=5841), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert after.me.credits == 470 and after.me.goalkeepers == 1 and after.me.missing(settings) == (2, 22)
    assert after.pool_state.credits == 470 and [o.player_id for o in after.pool_state.owned] == [5841]
    assert after.pool_state.owned[0].role_class == "Por" and 5841 not in after.pricing.prices
    assert after.market_credits == before.market_credits - 30
    assert after.lot is not None and after.lot.sold_to == 1 and after.lot.band is None and after.lot.expected_price is None
    assert after.pricing.composition["Por"] + after.me.goalkeepers >= 3               # the session's three keepers, one bought
    # a team over its budget, and my team missing from the session, are problems -- never a crash
    broke = derive(node([(2764, 0, 600)]), run=pinned, settings=settings, mapping=TeamMapping(mine=7))
    assert any("spent 600 of 500" in p for p in broke.problems) and any("my team 7" in p for p in broke.problems)
    assert broke.ledgers[0].credits == -100 and broke.market_credits == 500 * 3          # a negative balance buys nothing


def test_adjustments_reach_the_board_through_v(tmp_path, fixture_json, mcp_fixture_json):
    """`exclude` raises the class, `value` scales one man's band, `target`
    moves the composition the optimiser starts from -- through V, never by
    annotating a row (spec, "Adjustments are hot-reloaded, and `exclude` has a
    directional invariant")."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    mapping = TeamMapping(mine=0)
    plain = derive(AuctionState.empty(), run=pinned, settings=pinned.league, mapping=mapping)
    excluded = resolve([Adjustment("exclude", "not buying him", player="Martinez L.")], pinned.candidates())
    without = derive(AuctionState.empty(), run=pinned, settings=pinned.league, layer=excluded, mapping=mapping)
    assert 2764 not in without.pricing.prices and 2764 in plain.pricing.prices
    for pid, player in pinned.players.items():
        if player.role_class == "Pc" and pid != 2764:
            assert without.pricing.prices[pid].band.p50 >= plain.pricing.prices[pid].band.p50
    layer = resolve([Adjustment("exclude", "not buying him", player="Martinez L."),
                     Adjustment("value", "knee", player="Hojlund", factor=0.5),
                     Adjustment("target", "more keepers", role_class="Por", count=3),
                     Adjustment("exclude", "typo", player="Nobody")], pinned.candidates(), sha256="s")
    adjusted = derive(AuctionState.empty(), run=pinned, settings=pinned.league, layer=layer, mapping=mapping)
    assert adjusted.pricing.prices[6052].band.p50 < without.pricing.prices[6052].band.p50       # half the value, a lower band
    assert adjusted.pool_state.targets == {"Por": 3} and adjusted.pool_state.weights["Por"][2] == pytest.approx(0.8)
    assert adjusted.problems == layer.problems and "'Nobody'" in adjusted.problems[0]
    assert adjusted.to_dict()["adjustments"]["excluded"] == [2764] and adjusted.to_dict()["adjustments"]["sha256"] == "s"
    # an excluded player who is then sold to me is simply owned: the exclusion was about my bidding
    settings = session_from_feed(SESSION, team_count=3)
    bought = derive(node([(2764, 0, 90)]), run=pinned, settings=settings, layer=layer, mapping=mapping)
    assert [o.player_id for o in bought.pool_state.owned] == [2764] and bought.pool_state.excluded == frozenset()


def test_an_impossible_roster_is_a_problem_not_a_crash(tmp_path, fixture_json, mcp_fixture_json):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    five_keepers = session_from_feed({**SESSION, "roles": {"gk": [5, 5], "mov": [20, 20], "size": [25, 25]}}, team_count=3)
    board = derive(node([]), run=pinned, settings=five_keepers, mapping=TeamMapping(mine=1))
    assert board.pricing.completion_value == float("-inf")
    assert any("no completion" in p and "max_goalkeepers" in p for p in board.problems)
    assert json.loads(json.dumps(board.to_dict(), allow_nan=False))["completion_value"] is None
    ledgers, problems = build_ledgers(node([]), five_keepers, pinned, TeamMapping(mine=1))
    assert sorted(ledgers) == [0, 1, 2] and problems == []
```

Create `core/tests/test_auction.py`:

```python
import pytest
from fantaclaude.asta.adjustments import Adjustment, resolve
from fantaclaude.asta.advisor import TeamMapping, derive
from fantaclaude.asta.auction import Auction, MutationResult, Refresh
from fantaclaude.asta.session import SessionError
from fantaclaude.asta.state import (
    AuctionState,
    LotSelected,
    SaleAdded,
    SettingsChanged,
    StatusChanged,
    apply_snapshot,
    parse_snapshot,
    read_snapshots,
)
from test_advisor import pinned_run


def test_every_change_goes_through_mutate_and_reaches_every_listener(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    auction = Auction(pinned, TeamMapping(mine=1, nicks={0: "Marco"}))
    assert auction.settings is pinned.league and auction.board.me.credits == 500 and len(auction.board.ledgers) == 8
    seen: list[MutationResult] = []
    auction.subscribe(seen.append)
    snapshots = read_snapshots(fixture_file("asta_session_sample.jsonl"))
    results = [auction.mutate(snap) for snap in snapshots]
    assert [r.events for r in results] == [r.events for r in seen] and len(seen) == 8
    assert results[0].events == (StatusChanged("live", False),) and results[1].events == (SaleAdded(2764, 0, 120),)
    assert results[5].events == (SaleAdded(2120, 0, 45), LotSelected(5841)) and results[6].events == ()
    assert auction.settings.source == "session" and auction.settings.team_count == 3 and auction.settings.goalkeepers == (3, 3)
    assert auction.board.ledgers[0].spent == 165 and auction.board.me.credits == 500
    assert auction.board.league_conflicts == ("teams: 3 in the session, 8 in the league",)
    # the board is a function of the last snapshot: derive() on that snapshot alone is the same board
    state, _ = apply_snapshot(AuctionState.empty(), snapshots[-1])
    direct = derive(state, run=pinned, settings=auction.settings, mapping=auction.mapping)
    assert auction.board.to_dict() == direct.to_dict()
    # a refresh re-derives without a feed event: an exclusion lands, and nothing else moves
    layer = resolve([Adjustment("exclude", "not buying him", player="Hojlund")], pinned.candidates(), sha256="x")
    refreshed = auction.mutate(Refresh(layer=layer))
    assert refreshed.events == () and 6052 not in refreshed.board.pricing.prices and seen[-1] is refreshed
    assert auction.layer is layer and auction.board.layer.sha256 == "x"
    forced = auction.mutate(Refresh())
    assert forced.board.to_dict() == refreshed.board.to_dict()


def test_a_settings_change_mid_auction_is_an_event_and_re_prices_the_board(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    auction = Auction(pinned, TeamMapping(mine=1))
    snapshots = read_snapshots(fixture_file("asta_session_sample.jsonl"))
    for snap in snapshots[:3]:
        auction.mutate(snap)
    richer = parse_snapshot({**snapshots[2].to_node(), "settings": {**snapshots[2].settings, "budget": 1000}})
    result = auction.mutate(richer)
    assert result.events == (SettingsChanged((("budget", 500, 1000),)),)
    assert auction.settings.budget == 1000 and auction.board.me.credits == 960 and auction.board.ledgers[0].credits == 880
    assert auction.board.league_conflicts[0].startswith("budget: the session plays 1000")
    # a settings node this code cannot read leaves the auction exactly where it was
    before = auction.board.to_dict()
    broken = parse_snapshot({**snapshots[2].to_node(), "settings": {"budget": "lots"}})
    with pytest.raises(SessionError, match="budget"):
        auction.mutate(broken)
    assert auction.board.to_dict() == before and auction.settings.budget == 1000
    with pytest.raises(TypeError):
        auction.mutate("not a change")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_demand.py core/tests/test_pinned.py core/tests/test_advisor.py core/tests/test_auction.py -q`
Expected: FAIL — `TypeError: rank_weights() got an unexpected keyword argument 'min_ranks'` in `test_demand`; `ModuleNotFoundError: No module named 'fantaclaude.asta.pinned'` for the other three.

- [ ] **Step 3: `rank_weights` learns a class floor**

In `core/src/fantaclaude/model/demand.py`, replace the signature and docstring of `rank_weights` with:

```python
def rank_weights(demand_by_module: Mapping[str, Mapping[str, float]], *, max_rank: int, bench_weight: float,
                 bench_decay: float = 0.5, bench_slots: int = 1, targets: Mapping[str, int] | None = None,
                 target_weight: float = 0.8, min_ranks: Mapping[str, int] | None = None) -> dict[str, tuple[float, ...]]:
    """Class -> weight of the k-th player of that class, k = 1 .. the ranks
    the class has (the peak demand of any module, rounded up, plus
    bench_slots; a target extends them, and so does a class floor the
    roster must fill -- at bench weight, since a forced third keeper starts
    no more than a chosen one; never more than max_rank)."""
```

and, after the two lines `if targets:` / `ranks = max(ranks, targets.get(cls, 0))`, add:

```python
        if min_ranks:
            ranks = max(ranks, min_ranks.get(cls, 0))
```

- [ ] **Step 4: The run stores its demand per module, in a stable order, and floors the goalkeepers**

In `core/src/fantaclaude/analysis/valuation.py`, `run_valuation`: after the `demand = satisfiable_demand(...)` call (three lines) add:

```python
    # In module-code order, which is the order canonical_json stores it in: the
    # rank weights are floating-point sums over the modules, so the live board
    # (asta/pinned.py reads config["demand_by_module"] back) must add them in
    # the same order to reproduce this run's board to the last bit.
    demand = {code: demand[code] for code in sorted(demand)}
```

In the scenario loop, replace the `weights = rank_weights(demand, ... target_weight=pricing_cfg.target_weight)` call with the same call plus `min_ranks=ctx.class_min` as its last keyword argument:

```python
        weights = rank_weights(demand, max_rank=max_rank, bench_weight=pricing_cfg.bench_weight,
                               bench_decay=pricing_cfg.bench_decay, bench_slots=pricing_cfg.bench_slots_per_class,
                               targets=scenario.target_composition, target_weight=pricing_cfg.target_weight,
                               min_ranks=ctx.class_min)
```

In the `config = {...}` literal, after the `"demand": {cls: ...}` entry add:

```python
              # and the same demand per module, so the live board reads the run's own
              # weights back instead of re-deriving them (asta/pinned.py)
              "demand_by_module": demand,
```

- [ ] **Step 5: Write `pinned.py`**

Create `core/src/fantaclaude/asta/pinned.py`:

```python
"""A valuation run read back for the night (spec: "`asta serve --run <id>`
loads the pinned valuation into memory at startup, so the advice loop
never reaches for a file at all").

Everything the live board needs to reproduce the run's own board at minute
zero comes from the run's rows, never from the working tree: the
projections and quotazioni from `valuations`; the pricing knobs, the
scenarios and the folded per-module demand from `valuation_runs.config`;
the league's bounds from the `league_settings` row the run was priced
under; the committed bands from `valuation_prices`. pricing.yml as it is
today may already be a different model -- the run is the record. A run
recorded before `config` carried `demand_by_module` has its demand
re-derived from its own rows' role sets, and says so.

Without a run id the newest run whose rules_hash is not superseded is
taken and named (spec: "so the wrong run cannot be pinned silently"); a
superseded run can be pinned by id, and the board says it is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from fantaclaude.analysis.valuation import (
    PreferencesError,
    Scenario,
    UnknownScenarioError,
    load_scenarios,
)
from fantaclaude.asta.pricing import Band, PoolPlayer, PricingConfig
from fantaclaude.asta.session import SessionError, SessionSettings, league_bounds
from fantaclaude.ingest.names import Candidate
from fantaclaude.model.demand import (
    hard_minimums,
    module_demand,
    rank_weights,
    satisfiable_demand,
)
from fantaclaude.model.roles import Role


class PinnedRunError(RuntimeError):
    """No run to pin, or a run this code cannot read back."""


@dataclass(frozen=True)
class PinnedPlayer:
    player_id: int
    name: str
    team_short: str
    classic_role: str
    role_class: str
    roles: tuple[str, ...]
    value_p25: float
    value_p50: float
    value_p75: float
    quotazione: int
    tier: int

    @property
    def is_goalkeeper(self) -> bool:
        return "Por" in self.roles

    def pool_player(self) -> PoolPlayer:
        return PoolPlayer(self.player_id, self.name, self.role_class, self.value_p25, self.value_p50, self.value_p75,
                          self.quotazione)

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short,
                "classic_role": self.classic_role, "role_class": self.role_class, "roles": list(self.roles),
                "value_p25": self.value_p25, "value_p50": self.value_p50, "value_p75": self.value_p75,
                "quotazione": self.quotazione, "tier": self.tier}


@dataclass(frozen=True)
class PinnedRun:
    run_id: str
    created_at: datetime
    rules_hash: str
    model_hash: str
    superseded: bool
    settings_snapshot_id: int
    listone_snapshot_id: int
    season_id: int
    giornata: int
    players: dict[int, PinnedPlayer]
    pricing_cfg: PricingConfig
    scenarios: list[Scenario]
    demand: dict[str, dict[str, float]]          # per module, folded, as the run priced it
    demand_rederived: bool
    hard_minimums: dict[str, int]
    league: SessionSettings                       # the bounds the run was priced under
    prices: dict[str, dict[int, Band]]            # per scenario, the committed bands
    club_names: dict[str, str]                    # team_short -> the listone's club name

    def scenario(self, name: str | None = None) -> Scenario:
        if name is None:
            return self.scenarios[0]
        for scenario in self.scenarios:
            if scenario.name == name:
                return scenario
        raise UnknownScenarioError(f"run {self.run_id} has no scenario {name!r}; it has {[s.name for s in self.scenarios]}")

    def candidates(self) -> list[Candidate]:
        return [Candidate(p.player_id, p.name, p.team_short, self.club_names.get(p.team_short, p.team_short))
                for p in sorted(self.players.values(), key=lambda p: p.player_id)]

    def weights(self, targets: dict[str, int], min_ranks: dict[str, int]) -> dict[str, tuple[float, ...]]:
        cfg = self.pricing_cfg
        return rank_weights(self.demand, max_rank=max(cfg.max_per_class, cfg.max_goalkeepers), bench_weight=cfg.bench_weight,
                            bench_decay=cfg.bench_decay, bench_slots=cfg.bench_slots_per_class, targets=targets,
                            target_weight=cfg.target_weight, min_ranks=min_ranks)

    def describe(self) -> str:
        state = "superseded by a rules change" if self.superseded else "current"
        return (f"run {self.run_id} · rules {self.rules_hash} · model {self.model_hash} · {len(self.players)} players · "
                f"scenarios {', '.join(s.name for s in self.scenarios)} · {state}"
                + (" · demand re-derived (the run predates demand_by_module)" if self.demand_rederived else ""))


def newest_run_id(con: duckdb.DuckDBPyConnection) -> str | None:
    row = con.execute("SELECT run_id FROM v_valuation_runs WHERE NOT superseded "
                      "ORDER BY created_at DESC, run_id DESC LIMIT 1").fetchone()
    return None if row is None else str(row[0])


def _rederive_demand(players: dict[int, PinnedPlayer], cfg: PricingConfig) -> dict[str, dict[str, float]]:
    supply = [frozenset(Role(r) for r in p.roles) for p in players.values()]
    return satisfiable_demand(module_demand(), supply, max_rank=max(cfg.max_per_class, cfg.max_goalkeepers),
                              bench_weight=cfg.bench_weight, bench_decay=cfg.bench_decay, bench_slots=cfg.bench_slots_per_class)


def load_pinned_run(con: duckdb.DuckDBPyConnection, run_id: str | None = None) -> PinnedRun:
    if run_id is None:
        run_id = newest_run_id(con)
        if run_id is None:
            count = con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0]
            raise PinnedRunError("every valuation run is superseded by a rules change -- run `fantaclaude rank`, "
                                 "or pin one by id with --run" if count else "no valuation run to pin -- run `fantaclaude rank`")
    row = con.execute("SELECT run_id, created_at, rules_hash, model_hash, superseded, settings_snapshot_id, "
                      "listone_snapshot_id, season_id, giornata, config FROM v_valuation_runs WHERE run_id = ?",
                      [run_id]).fetchone()
    if row is None:
        raise PinnedRunError(f"no valuation run {run_id!r}")
    config = row[9] if isinstance(row[9], dict) else json.loads(row[9])
    try:
        pricing_cfg = PricingConfig(**config["pricing"])
        scenarios = load_scenarios(config["preferences"])
    except (KeyError, TypeError, PreferencesError) as exc:
        raise PinnedRunError(f"run {run_id}: its config cannot be read back by this code ({exc})") from None
    players = {int(r[0]): PinnedPlayer(int(r[0]), str(r[1]), str(r[2] or ""), str(r[3]), str(r[4]), tuple(r[5]),
                                       float(r[6]), float(r[7]), float(r[8]), int(r[9] or 0), int(r[10]))
               for r in con.execute("SELECT player_id, name, team_short, classic_role, role_class, roles, value_p25, "
                                    "value_p50, value_p75, quot_mantra, tier FROM valuations WHERE run_id = ? "
                                    "ORDER BY player_id", [run_id]).fetchall()}
    if not players:
        raise PinnedRunError(f"run {run_id} has no valuations rows")
    demand = config.get("demand_by_module")
    rederived = not demand
    if rederived:
        demand = _rederive_demand(players, pricing_cfg)
    try:
        league = league_bounds(con, int(row[5]))
    except SessionError as exc:
        raise PinnedRunError(f"run {run_id}: {exc}") from None
    prices: dict[str, dict[int, Band]] = {}
    for scenario, pid, p25, p50, p75 in con.execute(
            "SELECT scenario, player_id, max_p25, max_p50, max_p75 FROM valuation_prices WHERE run_id = ?", [run_id]).fetchall():
        prices.setdefault(str(scenario), {})[int(pid)] = Band(int(p25), int(p50), int(p75))
    clubs = {str(short): str(name) for name, short in con.execute(
        "SELECT name, short FROM teams WHERE snapshot_id = ?", [int(row[6])]).fetchall() if short}
    return PinnedRun(run_id=str(row[0]), created_at=row[1], rules_hash=str(row[2]), model_hash=str(row[3]),
                     superseded=bool(row[4]), settings_snapshot_id=int(row[5]), listone_snapshot_id=int(row[6]),
                     season_id=int(row[7]), giornata=int(row[8]), players=players, pricing_cfg=pricing_cfg,
                     scenarios=scenarios, demand={code: dict(by_class) for code, by_class in demand.items()},
                     demand_rederived=rederived, hard_minimums=hard_minimums(), league=league, prices=prices,
                     club_names=clubs)
```

- [ ] **Step 6: Write `advisor.py`**

Create `core/src/fantaclaude/asta/advisor.py`:

```python
"""The board: what the auction state is worth to me, re-derived whole on
every state change (spec, "`fanta-asta` -- live auction copilot").

derive() turns the feed's state, the pinned run, the adjustment layer and
the team mapping into: a ledger per team (credits from the picks, never
from the feed's budget field; the buckets the session fills; what the run
cannot name), my PoolState -- the unsold pool with the value factors
applied, my picks as owned, the excluded, the targets, the credits still
on the market -- the priced board (price_board, one mode, every player
with himself out of the pool), the lot on the block with its band, and the
problems a person has to see: a pick the run cannot name, a team over its
budget, a session outside the league's bounds, a roster no completion can
make legal. Opponent pressure is layered on by asta/pressure.py.

At minute zero, under the run's own league bounds, this is the run's
committed board band for band (spec, "One pricing function"): the same
function, the same inputs, read back from the run's rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fantaclaude.analysis.ordering import rank_key
from fantaclaude.asta.adjustments import EMPTY_LAYER, AdjustmentLayer, apply_layer
from fantaclaude.asta.pinned import PinnedRun
from fantaclaude.asta.pricing import (
    NEG,
    Band,
    BoardPricing,
    OwnedPlayer,
    PlayerPrice,
    PoolState,
    price_board,
)
from fantaclaude.asta.session import SessionSettings, compare
from fantaclaude.asta.state import AuctionState, Pick
from fantaclaude.model.demand import ROLE_CLASSES
from fantaclaude.values import json_safe


@dataclass(frozen=True)
class TeamMapping:
    """Which team is mine, and which dossier each other team's id maps to.
    The feed cannot supply it and the server never persists it (spec: the
    browser pre-fills it); offline it comes from flags or the state file."""
    mine: int
    nicks: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"mine": self.mine, "nicks": {str(k): v for k, v in sorted(self.nicks.items())}}


@dataclass(frozen=True)
class Ledger:
    team_id: int
    label: str
    nick: str | None
    budget: int
    spent: int
    picks: tuple[Pick, ...]
    goalkeepers: int
    outfield: int
    unknown: int                 # picks the run cannot name: credits counted, roles not

    @property
    def credits(self) -> int:
        return self.budget - self.spent

    def missing(self, settings: SessionSettings) -> tuple[int, int]:
        """(goalkeepers, outfield) still needed to reach the session's floor."""
        return max(0, settings.goalkeepers[0] - self.goalkeepers), max(0, settings.outfield[0] - self.outfield)

    def room(self, settings: SessionSettings) -> tuple[int, int]:
        """(goalkeepers, outfield) the session still lets the team buy."""
        return max(0, settings.goalkeepers[1] - self.goalkeepers), max(0, settings.outfield[1] - self.outfield)

    def open_slots(self, settings: SessionSettings) -> int:
        return max(0, settings.size[1] - len(self.picks))

    def to_dict(self, settings: SessionSettings) -> dict[str, Any]:
        gk, mov = self.missing(settings)
        return {"team_id": self.team_id, "label": self.label, "nick": self.nick, "budget": self.budget, "spent": self.spent,
                "credits": self.credits, "picks": [p.player_id for p in self.picks], "goalkeepers": self.goalkeepers,
                "outfield": self.outfield, "unknown": self.unknown, "missing_goalkeepers": gk, "missing_outfield": mov,
                "open_slots": self.open_slots(settings)}


@dataclass(frozen=True)
class Lot:
    player_id: int
    name: str
    team_short: str
    role_class: str
    roles: tuple[str, ...]
    tier: int
    band: Band | None            # None when he is sold or excluded
    expected_price: int | None
    sold_to: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short, "role_class": self.role_class,
                "roles": list(self.roles), "tier": self.tier, "band": None if self.band is None else self.band.to_dict(),
                "expected_price": self.expected_price, "sold_to": self.sold_to}


@dataclass(frozen=True)
class Board:
    run_id: str
    scenario: str
    state: AuctionState
    settings: SessionSettings
    league_conflicts: tuple[str, ...]
    ledgers: dict[int, Ledger]
    mine: int
    pool_state: PoolState
    pricing: BoardPricing
    selected: int | None
    lot: Lot | None
    layer: AdjustmentLayer
    problems: tuple[str, ...]
    players: dict[int, Any] = field(default_factory=dict)          # the run's PinnedPlayers, for the renderings
    club_names: dict[str, str] = field(default_factory=dict)       # team_short -> club name, for the dossiers
    pressure: dict[int, Any] = field(default_factory=dict)         # player_id -> pressure.Pressure (Task 8)

    @property
    def me(self) -> Ledger:
        return self.ledgers[self.mine]

    @property
    def market_credits(self) -> int:
        return self.pool_state.market_credits

    def price_of(self, player_id: int) -> PlayerPrice | None:
        return self.pricing.prices.get(player_id)

    def tiers(self, n: int = 5) -> dict[str, list[dict[str, Any]]]:
        """The printed tier board: per class, the unsold top n by max price."""
        out: dict[str, list[dict[str, Any]]] = {}
        for cls in ROLE_CLASSES:
            rows = [self.players[pid] for pid in self.pricing.prices if self.players[pid].role_class == cls]
            rows.sort(key=lambda p: (-self.pricing.prices[p.player_id].band.p50, *rank_key(p)))
            if rows:
                out[cls] = [self._row(p) for p in rows[:n]]
        return out

    def _row(self, p: Any) -> dict[str, Any]:
        price = self.pricing.prices[p.player_id]
        row = {"player_id": p.player_id, "name": p.name, "team_short": p.team_short, "role_class": p.role_class,
               "roles": list(p.roles), "tier": p.tier, "band": price.band.to_dict(), "expected_price": price.expected_price,
               "value_p50": p.value_p50}
        if p.player_id in self.pressure:
            row["pressure"] = self.pressure[p.player_id].to_dict()
        return row

    def to_dict(self) -> dict[str, Any]:
        return json_safe({
            "run_id": self.run_id, "scenario": self.scenario, "settings": self.settings.to_dict(),
            "league_conflicts": list(self.league_conflicts), "problems": list(self.problems),
            "status": self.state.status, "locked": self.state.locked, "picks": len(self.state.picks),
            "me": self.me.to_dict(self.settings),
            "teams": [ledger.to_dict(self.settings) for _, ledger in sorted(self.ledgers.items())],
            "market_credits": self.market_credits, "inflation": self.pricing.inflation,
            "composition": self.pricing.composition, "credits_by_class": self.pricing.credits_by_class,
            "reserve": self.pricing.reserve, "budget": self.pricing.budget, "slot_price": self.pricing.slot_price,
            "targets_departed": list(self.pricing.targets_departed), "completion_value": self.pricing.completion_value,
            "selected": self.selected, "lot": None if self.lot is None else self.lot.to_dict(),
            "lot_pressure": self.pressure[self.selected].to_dict() if self.selected in self.pressure else None,
            "adjustments": self.layer.to_dict(),
            "prices": {str(pid): self._row(self.players[pid]) for pid in sorted(self.pricing.prices)}})


def build_ledgers(state: AuctionState, settings: SessionSettings, run: PinnedRun,
                  mapping: TeamMapping) -> tuple[dict[int, Ledger], list[str]]:
    """One ledger per team the session shows -- or, with no session, one per
    league team -- credits derived from the picks alone."""
    ids = set(state.team_ids())
    if not ids:
        ids = set(range(settings.team_count))
    problems: list[str] = []
    if mapping.mine not in ids:
        problems.append(f"my team {mapping.mine} is not in the session, which has teams {sorted(ids)}")
        ids.add(mapping.mine)
    labels = {t.team_id: t.label for t in state.teams}
    ledgers: dict[int, Ledger] = {}
    for team_id in sorted(ids):
        picks = state.picks_of(team_id)
        gk = mov = unknown = 0
        for pick in picks:
            player = run.players.get(pick.player_id)
            if player is None:
                unknown += 1
                problems.append(f"{labels.get(team_id, f'team {team_id}')} bought player {pick.player_id} for {pick.cost}, "
                                f"which run {run.run_id} does not have: his credits count, his roles do not -- "
                                f"check the listone the run was priced on")
            elif player.is_goalkeeper:
                gk += 1
            else:
                mov += 1
        spent = sum(p.cost for p in picks)
        if spent > settings.budget:
            problems.append(f"{labels.get(team_id, f'team {team_id}')} spent {spent} of {settings.budget} credits")
        ledgers[team_id] = Ledger(team_id, labels.get(team_id, f"team {team_id}"), mapping.nicks.get(team_id),
                                  settings.budget, spent, picks, gk, mov, unknown)
    return ledgers, problems


def build_pool_state(state: AuctionState, settings: SessionSettings, run: PinnedRun, layer: AdjustmentLayer,
                     ledgers: dict[int, Ledger], mine: int, scenario_name: str | None = None) -> PoolState:
    scenario = run.scenario(scenario_name)
    sold = set(state.picks)
    pool = apply_layer(tuple(p.pool_player() for pid, p in sorted(run.players.items()) if pid not in sold), layer)
    me = ledgers[mine]
    owned = tuple(OwnedPlayer(p.player_id, run.players[p.player_id].role_class,
                              run.players[p.player_id].value_p50 * layer.factor(p.player_id))
                  for p in me.picks if p.player_id in run.players)
    targets = {**scenario.target_composition, **layer.targets}
    class_min = {"Por": settings.goalkeepers[0]}
    return PoolState(credits=max(0, me.credits), market_credits=sum(max(0, ledger.credits) for ledger in ledgers.values()),
                     pool=pool, weights=run.weights(targets, class_min), hard_minimums=run.hard_minimums, owned=owned,
                     excluded=frozenset(pid for pid in layer.excluded if pid not in sold),
                     roster_min=settings.size[0], roster_max=settings.size[1], class_min=class_min,
                     class_max={"Por": settings.goalkeepers[1]}, targets=targets,
                     class_budget_share=scenario.max_budget_share_per_role)


def derive(state: AuctionState, *, run: PinnedRun, settings: SessionSettings, layer: AdjustmentLayer = EMPTY_LAYER,
           mapping: TeamMapping, scenario: str | None = None) -> Board:
    scenario_obj = run.scenario(scenario)
    ledgers, problems = build_ledgers(state, settings, run, mapping)
    pool_state = build_pool_state(state, settings, run, layer, ledgers, mapping.mine, scenario_obj.name)
    pricing = price_board(pool_state, run.pricing_cfg)
    if pricing.completion_value == NEG:
        problems.append("no completion of my roster is legal under these bounds: the board's prices are zero -- "
                        f"the session fills {settings.goalkeepers[0]}-{settings.goalkeepers[1]} goalkeepers and "
                        f"{settings.size[0]}-{settings.size[1]} players, the pricing caps goalkeepers at "
                        f"{run.pricing_cfg.max_goalkeepers} (pricing.yml max_goalkeepers)")
    lot = None
    if state.selected is not None:
        player = run.players.get(state.selected)
        if player is None:
            problems.append(f"the lot on the block, player {state.selected}, is not in run {run.run_id}")
        else:
            price = pricing.prices.get(state.selected)
            pick = state.picks.get(state.selected)
            lot = Lot(player.player_id, player.name, player.team_short, player.role_class, player.roles, player.tier,
                      None if price is None else price.band, None if price is None else price.expected_price,
                      None if pick is None else pick.team_id)
    problems.extend(layer.problems)
    conflicts = tuple(compare(settings, run.league)) if settings.source == "session" else ()
    if run.superseded:
        problems.append(f"run {run.run_id} is superseded by a rules change; it was pinned by id")
    return Board(run.run_id, scenario_obj.name, state, settings, conflicts, ledgers, mapping.mine, pool_state, pricing,
                 state.selected, lot, layer, tuple(problems), players=run.players, club_names=run.club_names)
```

- [ ] **Step 7: Write `auction.py`**

Create `core/src/fantaclaude/asta/auction.py`:

```python
"""One owner of live state (spec, "Concurrency: one owner of state, and two
classes of query"): every change -- a feed snapshot, a new adjustment
layer, a refresh -- goes through mutate(), which re-derives the board and
tells every listener. 2b's server is one listener (the WebSocket
broadcast, the state file); the CLI's replay is another. No I/O here: the
caller reads the feed or the file and hands the result in, so a change
made from any surface reaches the board through the same path and no
state change can escape a listener's notice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fantaclaude.asta.adjustments import EMPTY_LAYER, AdjustmentLayer
from fantaclaude.asta.advisor import Board, TeamMapping, derive
from fantaclaude.asta.pinned import PinnedRun
from fantaclaude.asta.session import SessionSettings, session_from_feed
from fantaclaude.asta.state import AuctionState, Event, Snapshot, apply_snapshot


@dataclass(frozen=True)
class Refresh:
    """Re-derive from the inputs as they are now: a re-read adjustments.yml,
    or nothing new at all -- a forced deterministic recompute (spec,
    live-event requirement 6)."""
    layer: AdjustmentLayer | None = None


@dataclass(frozen=True)
class MutationResult:
    events: tuple[Event, ...]
    board: Board


Change = Snapshot | Refresh
Listener = Callable[[MutationResult], None]


class Auction:
    def __init__(self, run: PinnedRun, mapping: TeamMapping, *, settings: SessionSettings | None = None,
                 layer: AdjustmentLayer = EMPTY_LAYER, scenario: str | None = None) -> None:
        self.run = run
        self.mapping = mapping
        self.settings = settings or run.league
        self.layer = layer
        self.scenario = scenario
        self.state = AuctionState.empty()
        self.listeners: list[Listener] = []
        self.board = self._derive()

    def subscribe(self, listener: Listener) -> None:
        self.listeners.append(listener)

    def _derive(self) -> Board:
        return derive(self.state, run=self.run, settings=self.settings, layer=self.layer, mapping=self.mapping,
                      scenario=self.scenario)

    def mutate(self, change: Change) -> MutationResult:
        """Apply one change, re-derive the board, notify. A snapshot whose
        settings this code cannot read raises before anything is touched, so
        the auction stays where it was."""
        events: tuple[Event, ...] = ()
        if isinstance(change, Snapshot):
            settings = self.settings
            if change.settings:
                settings = session_from_feed(change.settings, team_count=len(change.teams) or self.settings.team_count)
            self.state, events = apply_snapshot(self.state, change)
            self.settings = settings
        elif isinstance(change, Refresh):
            if change.layer is not None:
                self.layer = change.layer
        else:
            raise TypeError(f"not a change: {change!r}")
        self.board = self._derive()
        result = MutationResult(events, self.board)
        for listener in self.listeners:
            listener(result)
        return result
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_demand.py core/tests/test_pinned.py core/tests/test_advisor.py core/tests/test_auction.py core/tests/test_valuation.py -q`
Expected: PASS. `uv run pytest core/tests -q` → 399 passed. `test_the_live_board_at_minute_zero_reproduces_the_pinned_board` is the one-pricing-function guarantee and must stay green in every later task.

- [ ] **Step 9: Commit**

```bash
git add core/src/fantaclaude/model/demand.py core/src/fantaclaude/analysis/valuation.py core/src/fantaclaude/asta/pinned.py core/src/fantaclaude/asta/advisor.py core/src/fantaclaude/asta/auction.py core/tests/test_demand.py core/tests/test_pinned.py core/tests/test_advisor.py core/tests/test_auction.py
git commit -m "feat(asta): the pinned run read back, the board derived from state, and one mutate() that owns it"
```

---

### Task 7: The state snapshot — `data/asta-state.json`, and its copy to `records/`

**Files:**
- Create: `core/src/fantaclaude/asta/snapshot.py`
- Test: `core/tests/test_snapshot.py`

**Interfaces:**
- Consumes: `advisor.Board`, `TeamMapping`; `state.Snapshot`, `parse_snapshot`, `SnapshotError`; `atomic.write_atomic`; `values.json_safe`; the test helpers `test_advisor.pinned_run`, `test_advisor.replayed`.
- Produces: `snapshot.STATE_VERSION = 1`; `snapshot.render_state(board, *, session_code, written_at) -> dict`; `snapshot.write_state(path, payload) -> None`; `snapshot.StoredState(snapshot, mapping, session_code, run_id, scenario, written_at, payload)`; `snapshot.read_state(path) -> StoredState`; `snapshot.copy_to_records(path, records_dir, *, session_code, closed_at) -> Path` (`records/asta/<code or 'session'>-<UTC stamp>.json`, written once); `snapshot.StateFileError`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_snapshot.py`:

```python
import json
from datetime import UTC, datetime

import pytest
from fantaclaude.asta.advisor import TeamMapping, derive
from fantaclaude.asta.session import session_from_feed
from fantaclaude.asta.snapshot import (
    STATE_VERSION,
    StateFileError,
    StoredState,
    copy_to_records,
    read_state,
    render_state,
    write_state,
)
from fantaclaude.asta.state import AuctionState, apply_snapshot
from test_advisor import pinned_run, replayed

WHEN = datetime(2026, 9, 5, 22, 30, tzinfo=UTC)


def test_the_state_file_reads_on_its_own_and_reloads_the_same_board(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    """The post-auction path (spec, "Crash recovery is a test"): loading the
    state file with no feed available must reproduce the board."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    state = replayed(fixture_file, 6)
    settings = session_from_feed(state.settings, team_count=len(state.teams))
    mapping = TeamMapping(mine=1, nicks={0: "Marco"})
    board = derive(state, run=pinned, settings=settings, mapping=mapping)
    payload = render_state(board, session_code="FA-nri-okm", written_at=WHEN)
    assert payload["version"] == STATE_VERSION and payload["written_at"] == "2026-09-05T22:30:00+00:00"
    assert payload["session"] == {"code": "FA-nri-okm", "status": "live", "locked": False, "settings": settings.to_dict()}
    assert payload["run_id"] == pinned.run_id and payload["scenario"] == "balanced" and payload["me"] == 1
    host = payload["teams"][0]
    assert host["label"] == "host" and host["nick"] == "Marco" and host["spent"] == 165 and host["credits"] == 335
    assert [p["name"] for p in host["picks"]] == ["Martinez L.", "Bastoni"] and host["picks"][0]["roles"] == ["Pc"]
    assert payload["selected"]["name"] == "Svilar" and payload["selected"]["band"]["p50"] > 0
    assert payload["feed"]["picks"][0] == {"playerId": 2764, "teamId": 0, "cost": 120, "index": 0, "timestamp": 1787600000000}
    text = json.dumps(payload, allow_nan=False)
    assert "@example" not in text and "uid" not in text

    path = tmp_path / "data" / "asta-state.json"
    write_state(path, payload)
    assert sorted(p.name for p in path.parent.iterdir() if p.name.startswith("asta")) == ["asta-state.json"]
    stored = read_state(path)
    assert isinstance(stored, StoredState) and stored.mapping == mapping and stored.session_code == "FA-nri-okm"
    assert stored.run_id == pinned.run_id and stored.scenario == "balanced" and stored.written_at == payload["written_at"]
    reloaded, _ = apply_snapshot(AuctionState.empty(), stored.snapshot)
    again = derive(reloaded, run=pinned, settings=session_from_feed(stored.snapshot.settings, team_count=len(stored.snapshot.teams)),
                   mapping=stored.mapping)
    assert again.to_dict() == board.to_dict()
    assert render_state(again, session_code="FA-nri-okm", written_at=WHEN) == payload


def test_a_state_file_this_code_did_not_write_is_refused(tmp_path):
    path = tmp_path / "asta-state.json"
    for text, match in (("{not json", "asta-state.json"), ("[]", "version"), ('{"version": 99}', "version"),
                        ('{"version": 1, "me": 0}', "asta-state.json"),
                        ('{"version": 1, "me": 0, "teams": [], "run_id": "r", "scenario": "s", "written_at": "w", "feed": {"picks": 5}}',
                         "picks")):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StateFileError, match=match):
            read_state(path)
    with pytest.raises(StateFileError):
        read_state(tmp_path / "missing.json")


def test_the_records_copy_is_written_once(tmp_path):
    path = tmp_path / "data" / "asta-state.json"
    write_state(path, {"version": STATE_VERSION, "me": 0})
    records = tmp_path / "records"
    copy = copy_to_records(path, records, session_code="FA-nri-okm", closed_at=WHEN)
    assert copy == records / "asta" / "FA-nri-okm-20260905T223000Z.json" and copy.read_bytes() == path.read_bytes()
    assert copy_to_records(path, records, session_code="FA-nri-okm", closed_at=WHEN) == copy       # the same bytes again: fine
    write_state(path, {"version": STATE_VERSION, "me": 1})
    with pytest.raises(StateFileError, match="never rewritten"):
        copy_to_records(path, records, session_code="FA-nri-okm", closed_at=WHEN)
    assert copy_to_records(path, records, session_code=None, closed_at=WHEN).name == "session-20260905T223000Z.json"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_snapshot.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'fantaclaude.asta.snapshot'`.

- [ ] **Step 3: Write `snapshot.py`**

Create `core/src/fantaclaude/asta/snapshot.py`:

```python
"""data/asta-state.json: the mirrored auction as last seen, kept for the days
between the room and the transfer (spec, "One database, and the auction is
not in it": a plain state dump, atomically replaced on change, written
with names, roles and participants resolved so it reads on its own; and
live-event requirement 5: a copy to records/ when the auction closes, both
removed once the transfer is confirmed -- by 2b's verify-transfer, open
question 9, never here).

Nothing depends on the file during the auction: a restart resubscribes and
gets full state from the feed. Read back with no feed available it
reproduces the board (the post-auction path the spec's crash-recovery test
names): the feed's own node is kept under `feed`, verbatim in shape, beside
the resolved names, so a state file reloads through parse_snapshot and
derive() gives the same board -- the names are for the reader, the ids are
what is reloaded. The mapping travels with it, because the feed cannot
supply it and the server never persists it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fantaclaude.asta.advisor import Board, TeamMapping
from fantaclaude.asta.state import Snapshot, SnapshotError, parse_snapshot
from fantaclaude.atomic import write_atomic
from fantaclaude.values import json_safe

STATE_VERSION = 1


class StateFileError(ValueError):
    """The state file is not one this code wrote, or is torn."""


def render_state(board: Board, *, session_code: str | None, written_at: datetime) -> dict[str, Any]:
    teams = []
    for team_id, ledger in sorted(board.ledgers.items()):
        picks = []
        for pick in ledger.picks:
            player = board.players.get(pick.player_id)
            picks.append({"player_id": pick.player_id, "name": None if player is None else player.name,
                          "team_short": None if player is None else player.team_short,
                          "roles": [] if player is None else list(player.roles), "cost": pick.cost, "index": pick.index,
                          "timestamp": pick.timestamp})
        teams.append({"id": team_id, "label": ledger.label, "nick": ledger.nick, "budget": ledger.budget,
                      "spent": ledger.spent, "credits": ledger.credits, "picks": picks})
    return json_safe({
        "version": STATE_VERSION, "written_at": written_at.isoformat(),
        "session": {"code": session_code, "status": board.state.status, "locked": board.state.locked,
                    "settings": board.settings.to_dict()},
        "run_id": board.run_id, "scenario": board.scenario, "adjustments_sha256": board.layer.sha256,
        "me": board.mine, "teams": teams, "selected": None if board.lot is None else board.lot.to_dict(),
        "problems": list(board.problems), "league_conflicts": list(board.league_conflicts),
        "feed": board.state.to_snapshot().to_node()})


def write_state(path: Path, payload: dict[str, Any]) -> None:
    write_atomic(path, (json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))


@dataclass(frozen=True)
class StoredState:
    snapshot: Snapshot
    mapping: TeamMapping
    session_code: str | None
    run_id: str
    scenario: str
    written_at: str
    payload: dict[str, Any]


def read_state(path: Path) -> StoredState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateFileError(f"{path}: {exc}") from None
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        raise StateFileError(f"{path}: not a fantaclaude state file of version {STATE_VERSION}")
    try:
        snapshot = parse_snapshot(payload["feed"])
        mine = int(payload["me"])
        nicks = {int(t["id"]): str(t["nick"]) for t in payload["teams"] if t.get("nick")}
        return StoredState(snapshot, TeamMapping(mine, nicks), payload.get("session", {}).get("code"),
                           str(payload["run_id"]), str(payload["scenario"]), str(payload["written_at"]), payload)
    except (KeyError, TypeError, ValueError, SnapshotError) as exc:
        raise StateFileError(f"{path}: {exc}") from None


def copy_to_records(path: Path, records_dir: Path, *, session_code: str | None, closed_at: datetime) -> Path:
    """The state file's copy under records/asta/, written once: a file that
    exists with the same bytes is fine, one with different bytes is refused
    -- records are never rewritten."""
    data = path.read_bytes()
    target = records_dir / "asta" / f"{session_code or 'session'}-{closed_at:%Y%m%dT%H%M%SZ}.json"
    if target.exists():
        if target.read_bytes() == data:
            return target
        raise StateFileError(f"{target} exists with different content; records are never rewritten")
    write_atomic(target, data)
    return target
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_snapshot.py -q`
Expected: PASS, 3 tests. `uv run pytest core/tests -q` → 402 passed.

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/asta/snapshot.py core/tests/test_snapshot.py
git commit -m "feat(asta): the state snapshot -- names resolved, the feed node verbatim, written atomically, copied once to records/"
```

---

### Task 8: Opponent pressure — who else can bid, how deep, and what beating the room costs

**Files:**
- Create: `core/src/fantaclaude/asta/pressure.py`
- Modify: `core/src/fantaclaude/asta/advisor.py` (`derive(..., participants=None)`), `core/src/fantaclaude/asta/auction.py` (`participants` through `Auction` and `Refresh`)
- Test: `core/tests/test_pressure.py`

**Interfaces:**
- Consumes: `advisor.Board`, `Ledger`; `pinned.PinnedPlayer`; `session.SessionSettings`; `kb.participants.Participant` (its `avoids`, `overpays`, `favourite_clubs`, `budget_style`, `max_single_share`); the test helpers `test_advisor.SESSION`, `node`, `pinned_run`.
- Produces: `pressure.PressureConfig(keen_factor=1.25, reluctant_factor=0.75, early_spent_share=0.5, min_bid=1)`, `pressure.DEFAULT`; `pressure.KEEN`, `NEUTRAL`, `RELUCTANT`; `pressure.Bidder(team_id, label, nick, intent, credits, depth, overpay, ceiling, reasons)`; `pressure.Pressure(player_id, expected, bidders, estimate)` with `.to_dict()`; `pressure.overpay_ratio(ledger, players) -> float | None`; `pressure.room_ratio(ledgers, players) -> float`; `pressure.pressure_for(player, expected, *, ledgers, mine, settings, players, club_names, participants, cfg=DEFAULT) -> Pressure`; `pressure.pressure_board(board, participants, cfg=DEFAULT) -> Board`; `advisor.derive(..., participants: dict[str, Participant] | None = None)` fills `Board.pressure` when given; `auction.Auction(..., participants=None)` and `auction.Refresh(layer=None, participants=None)`.

This is the first thing the cut-line drops (spec): nothing after it depends on it, and `derive` without `participants` is the board without pressure.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_pressure.py`:

```python
import json
from pathlib import Path

from fantaclaude.asta.advisor import Ledger, TeamMapping, derive
from fantaclaude.asta.pinned import PinnedPlayer
from fantaclaude.asta.pressure import (
    KEEN,
    NEUTRAL,
    RELUCTANT,
    Pressure,
    PressureConfig,
    overpay_ratio,
    pressure_board,
    pressure_for,
    room_ratio,
)
from fantaclaude.asta.session import session_from_feed
from fantaclaude.asta.state import Pick
from fantaclaude.kb.audit import FrontMatter
from fantaclaude.kb.participants import Participant
from test_advisor import SESSION, node, pinned_run

SETTINGS = session_from_feed({"budget": 500, "game": 2, "roles": {"gk": [2, 2], "mov": [6, 6], "size": [8, 8]}}, team_count=4)
LAUTARO = PinnedPlayer(2764, "Martinez L.", "INT", "A", "Pc", ("Pc",), 200.0, 240.0, 280.0, 35, 1)
SVILAR = PinnedPlayer(5841, "Svilar", "ROM", "P", "Por", ("Por",), 80.0, 100.0, 120.0, 18, 1)
CHEAP = PinnedPlayer(3, "Radunovic", "CAG", "P", "Por", ("Por",), 10.0, 20.0, 30.0, 1, 3)
PLAYERS = {p.player_id: p for p in (LAUTARO, SVILAR, CHEAP)}
CLUBS = {"INT": "Inter", "ROM": "Roma", "CAG": "Cagliari"}


def ledger(team_id, *, nick=None, picks=(), gk=0, mov=0):
    picks = tuple(Pick(pid, team_id, cost, i) for i, (pid, cost) in enumerate(picks))
    return Ledger(team_id, f"t{team_id}", nick, 500, sum(p.cost for p in picks), picks, gk, mov, 0)


def dossier(nick, **kw):
    fields = {"team": None, "budget_style": "steady", "favourite_clubs": (), "overpays": (), "avoids": (), "max_single_share": None}
    fields.update(kw)
    return Participant(path=Path(f"{nick}.md"), nick=nick, front_matter=FrontMatter(None, None, None, None, {}), **fields)


def test_a_rival_bids_only_with_a_slot_and_credits_beyond_one_per_other_slot():
    ledgers = {0: ledger(0), 1: ledger(1, picks=((3, 1),), gk=1), 2: ledger(2, picks=((5841, 18),), gk=2),
               3: ledger(3, picks=((999, 496),), mov=1)}                         # 999: a pick the run cannot name
    assert room_ratio(ledgers, PLAYERS) == 1.0
    p = pressure_for(SVILAR, 20, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS, participants={})
    assert isinstance(p, Pressure) and [b.team_id for b in p.bidders] == [1]           # 2 has both keepers, 3 has 4 credits and 7 slots
    only = p.bidders[0]
    assert only.credits == 499 and only.depth == 499 - 6 and only.intent == NEUTRAL and only.reasons == ()
    assert only.ceiling == 20 and p.estimate == 21 and p.expected == 20
    nobody = pressure_for(SVILAR, 20, ledgers={0: ledger(0), 2: ledgers[2]}, mine=0, settings=SETTINGS, players=PLAYERS,
                          club_names=CLUBS, participants={})
    assert nobody.bidders == () and nobody.estimate == 20


def test_the_dossier_moves_intent_and_caps_depth():
    participants = {"Marco": dossier("Marco", budget_style="early", favourite_clubs=("Inter",), overpays=("Pc",), avoids=("Por",)),
                    "Luca": dossier("Luca", budget_style="hoarder", max_single_share=0.3),
                    "Anna": dossier("Anna", overpays=("Por",), avoids=("Por",)), "Gigi": dossier("Gigi", avoids=("Por",))}
    ledgers = {0: ledger(0), 1: ledger(1, nick="Marco"), 2: ledger(2, nick="Luca"), 3: ledger(3, nick="Anna"),
               4: ledger(4, nick="Nobody"), 5: ledger(5, nick="Gigi")}
    lautaro = pressure_for(LAUTARO, 100, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS,
                           participants=participants)
    by_team = {b.team_id: b for b in lautaro.bidders}
    marco, luca, anna, unknown = by_team[1], by_team[2], by_team[3], by_team[4]
    assert marco.intent == KEEN and marco.ceiling == 125 and set(marco.reasons) == {"overpays Pc", "Inter is a favourite club",
                                                                                     "spends early, and has not yet"}
    assert luca.intent == RELUCTANT and luca.depth == 150 and luca.ceiling == 75                 # 0.3 x 500 caps him; he hoards
    assert "never more than 30% of the budget on one player" in luca.reasons and "hoards" in luca.reasons[0]
    assert anna.intent == NEUTRAL and anna.ceiling == 100 and unknown.intent == NEUTRAL and unknown.reasons == ()
    assert [b.team_id for b in lautaro.bidders] == [1, 3, 4, 5, 2] and lautaro.estimate == 126
    svilar = pressure_for(SVILAR, 20, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS,
                          participants=participants)
    intents = {b.team_id: b.intent for b in svilar.bidders}
    assert intents[5] == RELUCTANT                        # Gigi avoids keepers
    assert intents[1] == NEUTRAL                          # Marco avoids them too, but spends early: the two cancel
    assert intents[3] == NEUTRAL                          # Anna both overpays and avoids them
    assert {b.team_id: b.ceiling for b in svilar.bidders}[5] == 15
    keen_cfg = PressureConfig(keen_factor=2.0)
    assert pressure_for(LAUTARO, 100, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS,
                        participants=participants, cfg=keen_cfg).bidders[0].ceiling == 200


def test_observed_overpaying_scales_the_ceiling_against_the_room():
    ledgers = {0: ledger(0), 1: ledger(1, picks=((5841, 36),), gk=1), 2: ledger(2, picks=((3, 1),), gk=1)}
    assert overpay_ratio(ledgers[1], PLAYERS) == 2.0 and overpay_ratio(ledgers[2], PLAYERS) == 1.0 and overpay_ratio(ledgers[0], PLAYERS) is None
    room = room_ratio(ledgers, PLAYERS)
    assert room == 37 / 19                                # every purchase weighted by its quotazione, not one ratio per team
    p = pressure_for(LAUTARO, 100, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS, participants={})
    by_team = {b.team_id: b for b in p.bidders}
    assert by_team[1].overpay == 2.0 / room and by_team[1].ceiling == round(100 * 2.0 / room)
    assert by_team[2].overpay == 1.0 / room and by_team[2].ceiling == round(100 / room)
    assert by_team[1].ceiling <= by_team[1].depth
    assert json.loads(json.dumps(p.to_dict()))["bidders"][0]["overpay"] == round(2.0 / room, 3)


def test_pressure_board_puts_an_estimate_beside_every_unsold_band(tmp_path, fixture_json, mcp_fixture_json):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    settings = session_from_feed(SESSION, team_count=3)
    participants = {"Marco": dossier("Marco", favourite_clubs=("Inter",), overpays=("Pc",))}
    state = node([(3, 2, 1)])
    board = derive(state, run=pinned, settings=settings, mapping=TeamMapping(mine=1, nicks={0: "Marco"}), participants=participants)
    assert set(board.pressure) == set(board.pricing.prices)
    lautaro = board.pressure[2764]
    assert lautaro.bidders[0].team_id == 0 and lautaro.bidders[0].intent == KEEN and lautaro.estimate == lautaro.bidders[0].ceiling + 1
    assert lautaro.expected == board.pricing.prices[2764].expected_price
    payload = board.to_dict()
    assert payload["prices"]["2764"]["pressure"]["estimate"] == lautaro.estimate and payload["lot_pressure"] is None
    plain = derive(state, run=pinned, settings=settings, mapping=TeamMapping(mine=1, nicks={0: "Marco"}))
    assert plain.pressure == {} and "pressure" not in plain.to_dict()["prices"]["2764"]
    assert pressure_board(plain, participants).to_dict() == payload
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_pressure.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'fantaclaude.asta.pressure'`.

- [ ] **Step 3: Write `pressure.py`**

Create `core/src/fantaclaude/asta/pressure.py`:

```python
"""Opponent pressure: who else can bid on a lot, how deep, and what beating
the room is likely to cost (spec: "an opponent pressure estimate -- who
else needs this slot and how deep they can actually go, from dossiers plus
observed spending"). Displayed beside the band and never folded into it:
the band is what he is worth to me, the pressure is what he will cost.

Per rival, from his ledger: he can bid when the session still lets him buy
in the lot's bucket (goalkeeper or outfield) and his credits exceed one
per other open slot -- that difference is his depth. From his dossier
(kb/league/participants, loaded at startup, spec "Dossiers are loaded, not
read live"): `avoids` the class is reluctant; `overpays` the class, or the
lot's club among his `favourite_clubs`, is keen; `max_single_share` caps
the depth; an `early` spender with less than half his budget gone is keen
and a `hoarder` in the same spot is reluctant; keen and reluctant together
cancel to neutral. From what he has paid so far: his overpay ratio -- what
he paid over the quotazioni of what he bought, against the room's -- scales
what he is likely to go to. His ceiling is the expected price, times the
intent's factor, times his overpay, never above his depth. The estimate
for the lot is one credit past the keenest rival's ceiling, or the
expected price when nobody can bid. First on the cut-line (spec, "Cut-line,
decided now"): nothing else depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from fantaclaude.asta.advisor import Board, Ledger
from fantaclaude.asta.pinned import PinnedPlayer
from fantaclaude.asta.session import SessionSettings
from fantaclaude.kb.participants import Participant

KEEN, NEUTRAL, RELUCTANT = "keen", "neutral", "reluctant"


@dataclass(frozen=True)
class PressureConfig:
    keen_factor: float = 1.25
    reluctant_factor: float = 0.75
    early_spent_share: float = 0.5          # below this share of the budget spent, an early spender is keen and a hoarder reluctant
    min_bid: int = 1


DEFAULT = PressureConfig()


@dataclass(frozen=True)
class Bidder:
    team_id: int
    label: str
    nick: str | None
    intent: str
    credits: int
    depth: int
    overpay: float
    ceiling: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "label": self.label, "nick": self.nick, "intent": self.intent,
                "credits": self.credits, "depth": self.depth, "overpay": round(self.overpay, 3), "ceiling": self.ceiling,
                "reasons": list(self.reasons)}


@dataclass(frozen=True)
class Pressure:
    player_id: int
    expected: int
    bidders: tuple[Bidder, ...]          # ceiling descending
    estimate: int

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "expected": self.expected, "estimate": self.estimate,
                "bidders": [b.to_dict() for b in self.bidders]}


def _paid_and_quoted(ledger: Ledger, players: dict[int, PinnedPlayer]) -> tuple[int, int]:
    bought = [p for p in ledger.picks if p.player_id in players and players[p.player_id].quotazione > 0]
    return sum(p.cost for p in bought), sum(players[p.player_id].quotazione for p in bought)


def overpay_ratio(ledger: Ledger, players: dict[int, PinnedPlayer]) -> float | None:
    """What the team paid over the quotazioni of what it bought; None before it bought anything priced."""
    paid, quot = _paid_and_quoted(ledger, players)
    return paid / quot if quot else None


def room_ratio(ledgers: dict[int, Ledger], players: dict[int, PinnedPlayer]) -> float:
    """The room's own overpay, every purchase weighted by its quotazione -- one
    broke team's ratio counts for what it bought, not for a whole team's worth."""
    totals = [_paid_and_quoted(ledger, players) for ledger in ledgers.values()]
    paid, quot = sum(p for p, _ in totals), sum(q for _, q in totals)
    return paid / quot if quot else 1.0


def _intent(reasons_keen: list[str], reasons_reluctant: list[str]) -> str:
    if reasons_keen and not reasons_reluctant:
        return KEEN
    if reasons_reluctant and not reasons_keen:
        return RELUCTANT
    return NEUTRAL


def pressure_for(player: PinnedPlayer, expected: int, *, ledgers: dict[int, Ledger], mine: int,
                 settings: SessionSettings, players: dict[int, PinnedPlayer], club_names: dict[str, str],
                 participants: dict[str, Participant], cfg: PressureConfig = DEFAULT) -> Pressure:
    room = room_ratio(ledgers, players)
    club = club_names.get(player.team_short, player.team_short)
    bidders: list[Bidder] = []
    for team_id, ledger in sorted(ledgers.items()):
        if team_id == mine:
            continue
        gk_room, mov_room = ledger.room(settings)
        if (gk_room if player.is_goalkeeper else mov_room) <= 0:
            continue
        depth = ledger.credits - max(0, ledger.open_slots(settings) - 1) * cfg.min_bid
        if depth < cfg.min_bid:
            continue
        keen: list[str] = []
        reluctant: list[str] = []
        depth_note = None
        dossier = participants.get(ledger.nick) if ledger.nick else None
        if dossier is not None:
            if player.role_class in dossier.avoids:
                reluctant.append(f"avoids {player.role_class}")
            if player.role_class in dossier.overpays:
                keen.append(f"overpays {player.role_class}")
            if club in dossier.favourite_clubs:
                keen.append(f"{club} is a favourite club")
            spent_share = ledger.spent / ledger.budget if ledger.budget else 0.0
            if dossier.budget_style == "early" and spent_share < cfg.early_spent_share:
                keen.append("spends early, and has not yet")
            if dossier.budget_style == "hoarder" and spent_share < cfg.early_spent_share:
                reluctant.append("hoards, and still has most of his budget")
            if dossier.max_single_share is not None:
                cap = round(dossier.max_single_share * ledger.budget)
                if cap < depth:
                    depth = cap
                    depth_note = f"never more than {dossier.max_single_share:.0%} of the budget on one player"
        intent = _intent(keen, reluctant)
        team_ratio = overpay_ratio(ledger, players)
        overpay = team_ratio / room if team_ratio is not None and room else 1.0
        factor = {KEEN: cfg.keen_factor, RELUCTANT: cfg.reluctant_factor}.get(intent, 1.0)
        ceiling = int(min(depth, max(cfg.min_bid, round(expected * factor * overpay))))
        reasons = tuple(keen + reluctant + ([depth_note] if depth_note else []))
        bidders.append(Bidder(team_id, ledger.label, ledger.nick, intent, ledger.credits, depth, overpay, ceiling, reasons))
    bidders.sort(key=lambda b: (-b.ceiling, b.team_id))
    estimate = bidders[0].ceiling + cfg.min_bid if bidders else expected
    return Pressure(player.player_id, expected, tuple(bidders), estimate)


def pressure_board(board: Board, participants: dict[str, Participant], cfg: PressureConfig = DEFAULT) -> Board:
    """The board with a pressure estimate beside every unsold player's band."""
    pressure = {pid: pressure_for(board.players[pid], price.expected_price, ledgers=board.ledgers, mine=board.mine,
                                  settings=board.settings, players=board.players, club_names=board.club_names,
                                  participants=participants, cfg=cfg)
                for pid, price in board.pricing.prices.items()}
    return replace(board, pressure=pressure)
```

- [ ] **Step 4: Wire the dossiers through `derive` and `Auction`**

In `core/src/fantaclaude/asta/advisor.py`: add `from fantaclaude.kb.participants import Participant` to the imports (after the `session` import); change `derive`'s signature to

```python
def derive(state: AuctionState, *, run: PinnedRun, settings: SessionSettings, layer: AdjustmentLayer = EMPTY_LAYER,
           mapping: TeamMapping, scenario: str | None = None,
           participants: dict[str, Participant] | None = None) -> Board:
```

and replace its final `return Board(...)` statement with:

```python
    board = Board(run.run_id, scenario_obj.name, state, settings, conflicts, ledgers, mapping.mine, pool_state, pricing,
                  state.selected, lot, layer, tuple(problems), players=run.players, club_names=run.club_names)
    if participants is not None:
        from fantaclaude.asta.pressure import pressure_board

        board = pressure_board(board, participants)
    return board
```

(the import is local because `pressure.py` imports `Board` from this module.)

In `core/src/fantaclaude/asta/auction.py`: add `from fantaclaude.kb.participants import Participant`; give `Refresh` a second field `participants: dict[str, Participant] | None = None` and extend its docstring's first line to "a re-read adjustments.yml, re-read dossiers, or nothing new at all"; give `Auction.__init__` a last keyword parameter `participants: dict[str, Participant] | None = None` stored as `self.participants`; pass `participants=self.participants` in `_derive`; and in `mutate`'s `Refresh` branch add

```python
            if change.participants is not None:
                self.participants = change.participants
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_pressure.py core/tests/test_advisor.py core/tests/test_auction.py -q`
Expected: PASS. `uv run pytest core/tests -q` → 406 passed.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/asta/pressure.py core/src/fantaclaude/asta/advisor.py core/src/fantaclaude/asta/auction.py core/tests/test_pressure.py
git commit -m "feat(asta): opponent pressure -- a ceiling per rival from the ledger and the dossier, an estimate for the lot"
```

---

### Task 9: `fantaclaude asta` — the CLI entry, the doctor's three checks, the docs and the skill

**Files:**
- Create: `core/src/fantaclaude/commands/asta.py`, `core/tests/test_asta_cli.py`, `.claude/skills/fanta-asta/SKILL.md`
- Modify: `core/src/fantaclaude/paths.py`, `core/src/fantaclaude/cli/app.py` (the `asta` group; `doctor`'s paths; `from pathlib import Path`), `core/src/fantaclaude/commands/doctor.py` (one read-only connection; `pinned_run`, `adjustments`, `asta_state`), `core/README.md`, `site/docs/cli.md`, `records/README.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-08-22-fantaclaude-design.md`
- Test: `core/tests/test_asta_cli.py`, `core/tests/test_doctor.py`

**Interfaces:**
- Consumes: Tasks 4–8; `cli/app._open_read_only`, `emit`, `ExitCode`; `commands.ingest.NotReady`; `ingest.names.match_listone`; `kb.participants.load_participants`, `ParticipantError`; `test_rank_cli._workspace`.
- Produces: `paths.adjustments_path() -> data/adjustments.yml`, `paths.asta_state_path() -> data/asta-state.json`; `commands.asta.AstaPaths(db, adjustments, state, records, kb)`; `commands.asta.UsageError` (exit 2); `open_run(con, run_id=None) -> PinnedRun`; `load_layer(path, run) -> AdjustmentLayer`; `load_dossiers(kb_dir) -> dict[str, Participant]`; `resolve_mapping(teams, *, me, maps, participants) -> TeamMapping`; `BoardReport(board, run, source, mapping, notes, top)` / `board_report(con, *, paths, run_id=None, scenario=None, state_file=None, fresh=False, me=None, maps=(), top=5)`; `ExplainReport` / `explain_report(con, *, paths, player, **board_kw)`; `describe_event(event, run, labels) -> str`; `ReplayStep`, `ReplayReport` / `replay_report(con, *, paths, file, run_id=None, scenario=None, me=None, maps=(), write_state_to=None, now=None)`; `AdjustReport` / `adjust(con, *, paths, adjustment, run_id=None, scenario=None, state_file=None, fresh=False)`; `close_auction(paths, *, now, session_code=None) -> Path`. The CLI: `fantaclaude asta board|explain|replay|adjust|close`, every one with `--json`. `DoctorPaths(..., adjustments, asta_state)`; checks `pinned_run`, `adjustments`, `asta_state` appended after `valuations`; the database opened once per `doctor` run, so a file held by a writer is reported once as "cannot open database" and everywhere else as "skipped: database unavailable" (the cleanup item the spec lists, done here because this task touches every database check anyway — decision 8).

The code below was written but not run before this plan was finished; the executor should expect to adjust a rendering or an assertion, not the shape.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_asta_cli.py`:

```python
import json
from pathlib import Path

from fantaclaude.cli.app import ExitCode, app
from test_rank_cli import _workspace
from typer.testing import CliRunner

runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "asta_session_sample.jsonl"

DOSSIER = """---
updated: 2026-08-30
ttl: 90d
confidence: medium
source: interview
nick: Marco
budget_style: early
favourite_clubs: [Inter]
overpays: [Pc]
avoids: []
---

# Marco
"""


def _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """The rank CLI test's workspace with one run recorded and one dossier; returns the run id."""
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["rank", "--offline", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    (tmp_path / "kb" / "league" / "participants").mkdir(parents=True)
    (tmp_path / "kb" / "league" / "participants" / "marco.md").write_text(DOSSIER, encoding="utf-8")
    return json.loads(result.stdout)["run_id"]


def test_board_prices_the_run_against_an_empty_auction(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    run_id = _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "board", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == run_id and payload["scenario"] == "balanced" and payload["source"].startswith("an empty auction")
    assert payload["settings"]["source"] == "league" and payload["me"]["credits"] == 500 and len(payload["teams"]) == 8
    assert payload["market_credits"] == 4000 and payload["problems"] == [] and payload["lot"] is None
    assert "Pc" in payload["tiers"] and payload["tiers"]["Pc"][0]["band"]["p50"] >= 0
    # the same bands the run committed: one pricing function, read back
    query = runner.invoke(app, ["query", "--sql", f"SELECT player_id, max_p50 FROM valuation_prices WHERE run_id = '{run_id}' "
                                                 f"AND scenario = 'balanced'", "--json"])
    committed = {str(pid): p50 for pid, p50 in json.loads(query.stdout)["rows"]}
    assert payload["prices"] and all(payload["prices"][pid]["band"]["p50"] == committed[pid] for pid in payload["prices"])
    plain = runner.invoke(app, ["asta", "board", "--top", "2"])
    assert plain.exit_code == ExitCode.OK, plain.output
    assert f"run {run_id}" in plain.stdout and "  Pc: " in plain.stdout and "lot: none" in plain.stdout
    assert runner.invoke(app, ["asta", "board", "--scenario", "value-hunting", "--json"]).exit_code == ExitCode.OK
    assert runner.invoke(app, ["asta", "board", "--scenario", "nope"]).exit_code == ExitCode.USAGE
    assert runner.invoke(app, ["asta", "board", "--run", "nope"]).exit_code == ExitCode.NOT_READY


def test_board_refuses_without_a_run_or_a_database(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "board"])
    assert result.exit_code == ExitCode.NOT_READY and "no valuation run" in result.stderr
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path / "empty"))
    result = runner.invoke(app, ["asta", "board"])
    assert result.exit_code == ExitCode.NOT_READY and "no database" in result.stderr


def test_explain_reads_one_players_trace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "explain", "Martinez L.", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["player"]["player_id"] == 2764 and payload["player"]["role_class"] == "Pc" and payload["sold_to"] is None
    board = json.loads(runner.invoke(app, ["asta", "board", "--json"]).stdout)
    assert payload["trace"]["band"] == board["prices"]["2764"]["band"] and payload["trace"]["inflation"] == board["inflation"]
    assert len(payload["pressure"]["bidders"]) == 7 and payload["pressure"]["estimate"] >= payload["pressure"]["expected"]
    assert json.loads(runner.invoke(app, ["asta", "explain", "2764", "--json"]).stdout)["player"]["name"] == "Martinez L."
    plain = runner.invoke(app, ["asta", "explain", "Martinez L."])
    assert plain.exit_code == ExitCode.OK and "band " in plain.stdout and "pressure: est." in plain.stdout
    missing = runner.invoke(app, ["asta", "explain", "Nobody"])
    assert missing.exit_code == ExitCode.USAGE and "Nobody" in missing.stderr


def test_replay_runs_the_captured_session_and_writes_the_state_file(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--map", "host=Marco", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["mapping"] == {"mine": 1, "nicks": {"0": "Marco"}} and len(payload["steps"]) == 8
    assert payload["steps"][1]["events"] == ["+ Martinez L. (Pc) -> host for 120"]
    assert payload["steps"][4]["events"] == ["- Bastoni (Dc) <- Claude (45, undone)"]
    assert payload["steps"][5]["lot"]["name"] == "Svilar" and payload["steps"][6]["events"] == []
    assert payload["steps"][7]["events"][0] == "+ player 999999 (not in the run) -> @bomber for 3"
    assert payload["me"]["credits"] == 500 and payload["teams"][0]["spent"] == 165 and payload["written"] is None
    assert any("999999" in p for p in payload["problems"])
    assert payload["league_conflicts"] == ["teams: 3 in the session, 8 in the league"]
    assert payload["prices"]["5841"]["pressure"]["bidders"][0]["nick"] == "Marco"

    written = runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "1", "--write-state", "--json"])
    assert written.exit_code == ExitCode.OK, written.output
    state_file = tmp_path / "data" / "asta-state.json"
    assert json.loads(written.stdout)["written"] == str(state_file) and state_file.is_file()
    # the board now reads the state file: the mirrored auction, the mapping remembered
    board = runner.invoke(app, ["asta", "board", "--json"])
    assert board.exit_code == ExitCode.OK, board.output
    payload = json.loads(board.stdout)
    assert payload["source"].startswith("state file") and payload["picks"] == 3 and payload["me"]["label"] == "Claude"
    assert payload["mapping"]["mine"] == 1 and payload["teams"][0]["spent"] == 165 and payload["settings"]["source"] == "session"
    fresh = json.loads(runner.invoke(app, ["asta", "board", "--fresh", "--json"]).stdout)
    assert fresh["picks"] == 0 and fresh["settings"]["source"] == "league"
    plain = runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude"])
    assert plain.exit_code == ExitCode.OK, plain.output
    assert "undone" in plain.stdout and "final " in plain.stdout
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE)]).exit_code == ExitCode.USAGE              # three teams: which is mine?
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "nobody"]).exit_code == ExitCode.USAGE
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--map", "host=Luca"]).exit_code == ExitCode.USAGE
    assert runner.invoke(app, ["asta", "replay", str(tmp_path / "missing.jsonl"), "--me", "Claude"]).exit_code == ExitCode.USAGE


def test_adjust_appends_and_shows_what_moved(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "adjust", "--type", "exclude", "--player", "Martinez L.", "--reason", "not buying him",
                                 "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["player_id"] == 2764 and payload["count"] == 1
    assert payload["before"]["band"] is not None and payload["after"]["band"] is None
    path = tmp_path / "data" / "adjustments.yml"
    assert "- player: Martinez L.\n  type: exclude\n  reason: not buying him\n" in path.read_text(encoding="utf-8")
    board = json.loads(runner.invoke(app, ["asta", "board", "--json"]).stdout)
    assert "2764" not in board["prices"] and board["adjustments"]["applied"] == 1
    value = runner.invoke(app, ["asta", "adjust", "--type", "value", "--player-id", "6052", "--factor", "0.5", "--reason", "knee",
                                "--json"])
    assert value.exit_code == ExitCode.OK, value.output
    v = json.loads(value.stdout)
    assert v["count"] == 2 and v["after"]["band"]["p50"] <= v["before"]["band"]["p50"]
    target = runner.invoke(app, ["asta", "adjust", "--type", "target", "--class", "Por", "--count", "3", "--reason", "keepers"])
    assert target.exit_code == ExitCode.OK and "appended to" in target.stdout
    # a player the run cannot resolve, or a malformed entry, is a bad argument: refused and never written
    for args in (["--type", "exclude", "--player", "Nobody", "--reason", "r"],
                 ["--type", "nope", "--player", "Martinez L.", "--reason", "r"],
                 ["--type", "value", "--player", "Bastoni", "--reason", "r"],
                 ["--type", "exclude", "--player", "Bastoni"]):
        bad = runner.invoke(app, ["asta", "adjust", *args])
        assert bad.exit_code == ExitCode.USAGE, (args, bad.output)
    assert path.read_text(encoding="utf-8").count("type:") == 3


def test_close_copies_the_state_file_to_records_and_doctor_sees_it_all(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    nothing = runner.invoke(app, ["asta", "close"])
    assert nothing.exit_code == ExitCode.NOT_READY and "no state file" in nothing.stderr
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "Claude", "--write-state"]).exit_code == ExitCode.OK
    result = runner.invoke(app, ["asta", "close", "--session", "FA-nri-okm", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    copy = Path(json.loads(result.stdout)["records"])
    assert copy.parent == tmp_path / "records" / "asta" and copy.name.startswith("FA-nri-okm-") and copy.is_file()
    assert copy.read_bytes() == (tmp_path / "data" / "asta-state.json").read_bytes()
    doctor = json.loads(runner.invoke(app, ["doctor", "--json"]).stdout)
    by = {c["name"]: c for c in doctor["checks"]}
    assert by["pinned_run"]["ok"] and by["adjustments"]["ok"] and by["asta_state"]["ok"]
    assert "3 picks" in by["asta_state"]["detail"] and "none yet" in by["adjustments"]["detail"]
```

In `core/tests/test_doctor.py`: extend `NAMES` with `"pinned_run", "adjustments", "asta_state"` at the end; in `_paths` add `adjustments=root / "data" / "adjustments.yml", asta_state=root / "data" / "asta-state.json"` to the `DoctorPaths(...)` call; in `test_every_check_passes_on_a_ready_workspace` replace `["fixtures", "kb_profiles", "valuations"]` with `["fixtures", "kb_profiles", "valuations", "pinned_run"]`; and append:

```python


def test_a_database_held_by_a_writer_is_reported_once(tmp_path, fixture_json, mcp_fixture_json):
    """One read-only connection per run: a file a writer holds used to be
    'cannot open database' on one line and 'skipped: no database' two lines
    later, because every check opened its own connection and drew its own
    conclusion."""
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    writer = connect(tmp_path / "data" / "fanta.duckdb")          # the same process: DuckDB refuses a second configuration
    try:
        by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    finally:
        writer.close()
    assert not by["database"].ok and by["database"].detail.startswith("cannot open database")
    for name in ("extensions", "league_settings", "listone", "player_match", "advanced", "fixtures", "kb_takers", "scoring",
                 "valuations", "pinned_run"):
        assert by[name].detail == "skipped: database unavailable", name
    assert "no database" not in " ".join(c.detail for c in by.values())


def test_the_asta_checks_read_the_run_the_adjustments_and_the_state_file(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.analysis.valuation import record_run
    from test_valuation import run, seeded

    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path)
    record_run(con, result)
    con.close()
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["pinned_run"].ok and result.run_id in by["pinned_run"].detail and "current" in by["pinned_run"].detail
    assert by["adjustments"].ok and "none yet" in by["adjustments"].detail
    assert by["asta_state"].ok and "no state file" in by["asta_state"].detail
    (tmp_path / "data" / "adjustments.yml").write_text(
        "- {player: 'Martinez L.', type: exclude, reason: r}\n- {player: Nobody, type: value, factor: 0.5, reason: r}\n")
    (tmp_path / "data" / "asta-state.json").write_text("{not json")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["adjustments"].ok and "1 inert" in by["adjustments"].detail and "'Nobody'" in by["adjustments"].detail
    assert not by["asta_state"].ok and "asta-state.json" in by["asta_state"].detail
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_asta_cli.py core/tests/test_doctor.py -q`
Expected: FAIL — `TypeError: DoctorPaths.__init__() got an unexpected keyword argument 'adjustments'` in every doctor test; in `test_asta_cli` every command exits 2 with `No such command 'asta'`.

- [ ] **Step 3: The two paths**

Append to `core/src/fantaclaude/paths.py`:

```python


def adjustments_path() -> Path:
    """data/adjustments.yml: my beliefs and preferences for the auction -- mine, hand-editable, outlives the auction."""
    return data_dir() / "adjustments.yml"


def asta_state_path() -> Path:
    """data/asta-state.json: the mirrored auction as last seen, written atomically; deleted by verify-transfer (2b)."""
    return data_dir() / "asta-state.json"
```

- [ ] **Step 4: Write `commands/asta.py`**

Create `core/src/fantaclaude/commands/asta.py`:

```python
"""fantaclaude asta: the auction core, offline (spec, "The skill <-> Python
contract"). Importable on purpose -- 2b's server calls these functions and
the CLI adds argument parsing and rendering.

Every function here opens the database read-only, reads data/adjustments.yml,
data/asta-state.json and the dossiers, and touches no network. `board`
prices the pinned run against the mirrored auction as last seen (or an
empty one under the run's own league settings), `explain` reads one
player's trace, `replay` runs a captured session through the whole
pipeline (the rehearsal harness), `adjust` appends a belief and shows what
it moved, `close` copies the state file to records/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.valuation import UnknownScenarioError
from fantaclaude.asta.adjustments import (
    Adjustment,
    AdjustmentLayer,
    AdjustmentsError,
    append_adjustment,
    file_sha256,
    load_adjustments,
    resolve,
)
from fantaclaude.asta.advisor import Board, TeamMapping, derive
from fantaclaude.asta.auction import Auction
from fantaclaude.asta.pinned import PinnedPlayer, PinnedRun, PinnedRunError, load_pinned_run
from fantaclaude.asta.pricing import explain as explain_price
from fantaclaude.asta.session import SessionError, SessionSettings, session_from_feed
from fantaclaude.asta.snapshot import (
    StateFileError,
    StoredState,
    copy_to_records,
    read_state,
    render_state,
    write_state,
)
from fantaclaude.asta.state import (
    AuctionState,
    CostEdited,
    Event,
    LotSelected,
    SaleAdded,
    SaleRemoved,
    SettingsChanged,
    Snapshot,
    SnapshotError,
    StatusChanged,
    Team,
    apply_snapshot,
    read_snapshots,
)
from fantaclaude.commands.ingest import NotReady
from fantaclaude.ingest.names import match_listone
from fantaclaude.kb.participants import Participant, ParticipantError, load_participants
from fantaclaude.timeutil import utc_now
from fantaclaude.values import json_safe


class UsageError(ValueError):
    """A flag names something that does not exist -- a bad argument, not a bad file (exit 2)."""


@dataclass(frozen=True)
class AstaPaths:
    db: Path
    adjustments: Path
    state: Path
    records: Path
    kb: Path


def open_run(con: duckdb.DuckDBPyConnection, run_id: str | None = None) -> PinnedRun:
    try:
        return load_pinned_run(con, run_id)
    except PinnedRunError as exc:
        raise NotReady(str(exc)) from None


def load_layer(path: Path, run: PinnedRun) -> AdjustmentLayer:
    try:
        adjustments = load_adjustments(path)
    except AdjustmentsError as exc:
        raise NotReady(str(exc)) from None
    return resolve(adjustments, run.candidates(), sha256=file_sha256(path))


def load_dossiers(kb_dir: Path) -> dict[str, Participant]:
    try:
        return {p.nick: p for p in load_participants(kb_dir)}
    except ParticipantError as exc:
        raise NotReady(str(exc)) from None


def _team(teams: tuple[Team, ...], key: str) -> Team:
    by_label = [t for t in teams if t.label.casefold() == key.casefold()]
    if len(by_label) == 1:
        return by_label[0]
    if key.isdigit():
        by_id = [t for t in teams if t.team_id == int(key)]
        if by_id:
            return by_id[0]
    labels = ", ".join(f"{t.team_id} ({t.label})" for t in teams)
    if len(by_label) > 1:
        raise UsageError(f"{key!r} names {len(by_label)} teams; use the id: {labels}")
    raise UsageError(f"no team {key!r}; the session has {labels}")


def resolve_mapping(teams: tuple[Team, ...], *, me: str | None, maps: tuple[str, ...],
                    participants: dict[str, Participant]) -> TeamMapping:
    """--me names my team by label or id; --map team=nick binds a team to a dossier."""
    nicks: dict[int, str] = {}
    if not teams:                    # no session: the league's teams are numbered, and mine is 0 unless told otherwise
        if me is not None and not me.isdigit():
            raise UsageError(f"--me must be a team number when there is no session, got {me!r}")
        for entry in maps:
            key, sep, nick = entry.partition("=")
            if not sep or not key.isdigit():
                raise UsageError(f"--map takes team=nick, with a team number when there is no session, got {entry!r}")
            if nick not in participants:
                raise UsageError(f"no dossier for {nick!r} under kb/league/participants; known: {sorted(participants)}")
            nicks[int(key)] = nick
        return TeamMapping(int(me) if me is not None else 0, nicks)
    if me is None:
        if len(teams) != 1:
            raise UsageError("which team is mine? --me one of " + ", ".join(f"{t.team_id} ({t.label})" for t in teams))
        mine = teams[0].team_id
    else:
        mine = _team(teams, me).team_id
    for entry in maps:
        key, sep, nick = entry.partition("=")
        if not sep or not nick:
            raise UsageError(f"--map takes team=nick, got {entry!r}")
        if nick not in participants:
            raise UsageError(f"no dossier for {nick!r} under kb/league/participants; known: {sorted(participants)}")
        nicks[_team(teams, key).team_id] = nick
    return TeamMapping(mine, nicks)


def _stored(paths: AstaPaths, state_file: Path | None, fresh: bool) -> tuple[StoredState | None, Path]:
    path = state_file or paths.state
    if fresh or not path.is_file():
        return None, path
    try:
        return read_state(path), path
    except StateFileError as exc:
        raise NotReady(str(exc)) from None


def _settings(snapshot: Snapshot | None, run: PinnedRun) -> SessionSettings:
    if snapshot is None or not snapshot.settings:
        return run.league
    try:
        return session_from_feed(snapshot.settings, team_count=len(snapshot.teams) or run.league.team_count)
    except SessionError as exc:
        raise NotReady(f"the session's settings cannot be read: {exc}") from None


def _player(run: PinnedRun, key: str) -> PinnedPlayer:
    if key.isdigit() and int(key) in run.players:
        return run.players[int(key)]
    match = match_listone(key, run.candidates())
    if match.player_id is None:
        named = {p.player_id: p.name for p in run.players.values()}
        close = ", ".join(repr(named[i]) for i in match.candidates if i in named)
        raise UsageError(f"{key!r} is not a player of run {run.run_id}" + (f"; did you mean {close}?" if close else
                                                                            "; write him the listone's way, or give his id"))
    return run.players[match.player_id]


@dataclass(frozen=True)
class BoardReport:
    board: Board
    run: PinnedRun
    source: str
    mapping: TeamMapping
    notes: tuple[str, ...]
    top: int = 5

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"run": self.run.describe(), "source": self.source, "mapping": self.mapping.to_dict(),
                          "notes": list(self.notes), "tiers": self.board.tiers(self.top), **self.board.to_dict()})


def board_report(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, run_id: str | None = None,
                 scenario: str | None = None, state_file: Path | None = None, fresh: bool = False,
                 me: str | None = None, maps: tuple[str, ...] = (), top: int = 5) -> BoardReport:
    run = open_run(con, run_id)
    layer = load_layer(paths.adjustments, run)
    participants = load_dossiers(paths.kb)
    stored, path = _stored(paths, state_file, fresh)
    notes: list[str] = []
    if stored is None:
        state, settings = AuctionState.empty(), run.league
        mapping = resolve_mapping((), me=me, maps=maps, participants=participants)
        source = "an empty auction under the run's league settings"
    else:
        state, _ = apply_snapshot(AuctionState.empty(), stored.snapshot)
        settings = _settings(stored.snapshot, run)
        mapping = (stored.mapping if me is None and not maps
                   else resolve_mapping(stored.snapshot.teams, me=me or str(stored.mapping.mine), maps=maps, participants=participants))
        source = f"state file {path} (written {stored.written_at}, session {stored.session_code or '?'})"
        if stored.run_id != run.run_id:
            notes.append(f"the state file was written under run {stored.run_id}; this board prices run {run.run_id}")
    try:
        board = derive(state, run=run, settings=settings, layer=layer, mapping=mapping, scenario=scenario,
                       participants=participants)
    except UnknownScenarioError as exc:
        raise UsageError(str(exc)) from None
    return BoardReport(board, run, source, mapping, tuple(notes), top)


@dataclass(frozen=True)
class ExplainReport:
    player: PinnedPlayer
    report: BoardReport
    trace: dict[str, Any] | None
    sold_to: int | None
    cost: int | None
    pressure: dict[str, Any] | None
    adjustments: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"run": self.report.run.describe(), "source": self.report.source, "player": self.player.to_dict(),
                          "sold_to": self.sold_to, "cost": self.cost, "trace": self.trace, "pressure": self.pressure,
                          "adjustments": list(self.adjustments), "problems": list(self.report.board.problems)})


def explain_report(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, player: str, **board_kw: Any) -> ExplainReport:
    report = board_report(con, paths=paths, **board_kw)
    who = _player(report.run, player)
    board = report.board
    pick = board.state.picks.get(who.player_id)
    trace = explain_price(board.pricing, who.player_id) if who.player_id in board.pricing.prices else None
    pressure = board.pressure[who.player_id].to_dict() if who.player_id in board.pressure else None
    applied = tuple(e.adjustment.describe() for e in board.layer.entries if e.player_id == who.player_id)
    return ExplainReport(who, report, trace, None if pick is None else pick.team_id, None if pick is None else pick.cost,
                         pressure, applied)


def describe_event(event: Event, run: PinnedRun, labels: dict[int, str]) -> str:
    def name(pid: int | None) -> str:
        if pid is None:
            return "none"
        player = run.players.get(pid)
        return f"{player.name} ({player.role_class})" if player else f"player {pid} (not in the run)"

    if isinstance(event, SaleAdded):
        return f"+ {name(event.player_id)} -> {labels.get(event.team_id, f'team {event.team_id}')} for {event.cost}"
    if isinstance(event, SaleRemoved):
        return f"- {name(event.player_id)} <- {labels.get(event.team_id, f'team {event.team_id}')} ({event.cost}, undone)"
    if isinstance(event, CostEdited):
        return f"= {name(event.player_id)}: {event.before} -> {event.after}"
    if isinstance(event, LotSelected):
        return f"lot: {name(event.player_id)}"
    if isinstance(event, SettingsChanged):
        return "settings: " + "; ".join(f"{path} {before!r} -> {after!r}" for path, before, after in event.changes)
    if isinstance(event, StatusChanged):
        return f"status {event.status}, locked {event.locked}"
    return repr(event)


@dataclass(frozen=True)
class ReplayStep:
    index: int
    events: tuple[str, ...]
    credits: int
    picks: int
    lot: dict[str, Any] | None
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "events": list(self.events), "credits": self.credits, "picks": self.picks,
                "lot": self.lot, "problems": list(self.problems)}


@dataclass(frozen=True)
class ReplayReport:
    steps: tuple[ReplayStep, ...]
    board: Board
    run: PinnedRun
    mapping: TeamMapping
    written: Path | None

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"run": self.run.describe(), "mapping": self.mapping.to_dict(),
                          "steps": [s.to_dict() for s in self.steps], "written": None if self.written is None else str(self.written),
                          "tiers": self.board.tiers(), **self.board.to_dict()})


def replay_report(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, file: Path, run_id: str | None = None,
                  scenario: str | None = None, me: str | None = None, maps: tuple[str, ...] = (),
                  write_state_to: Path | None = None, now: datetime | None = None) -> ReplayReport:
    run = open_run(con, run_id)
    layer = load_layer(paths.adjustments, run)
    participants = load_dossiers(paths.kb)
    if not file.is_file():
        raise UsageError(f"{file} is not a file")
    try:
        snapshots = read_snapshots(file)
    except (OSError, UnicodeDecodeError, SnapshotError) as exc:
        raise NotReady(str(exc)) from None
    if not snapshots:
        raise UsageError(f"{file} holds no snapshots")
    mapping = resolve_mapping(snapshots[0].teams, me=me, maps=maps, participants=participants)
    try:
        auction = Auction(run, mapping, layer=layer, scenario=scenario, participants=participants)
    except UnknownScenarioError as exc:
        raise UsageError(str(exc)) from None
    steps: list[ReplayStep] = []
    for i, snap in enumerate(snapshots):
        try:
            result = auction.mutate(snap)
        except SessionError as exc:
            raise NotReady(f"{file}: snapshot {i}: {exc}") from None
        board = result.board
        labels = {t: ledger.label for t, ledger in board.ledgers.items()}
        steps.append(ReplayStep(i, tuple(describe_event(e, run, labels) for e in result.events), board.me.credits,
                                len(board.state.picks), None if board.lot is None else board.lot.to_dict(), board.problems))
    written = None
    if write_state_to is not None:
        write_state(write_state_to, render_state(auction.board, session_code=None, written_at=now or utc_now()))
        written = write_state_to
    return ReplayReport(tuple(steps), auction.board, run, mapping, written)


def _class_view(board: Board, cls: str, top: int = 5) -> list[dict[str, Any]]:
    return board.tiers(top).get(cls, [])


@dataclass(frozen=True)
class AdjustReport:
    adjustment: Adjustment
    player_id: int | None
    path: Path
    count: int
    before: dict[str, Any]
    after: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"adjustment": self.adjustment.to_entry(), "described": self.adjustment.describe(),
                          "player_id": self.player_id, "path": str(self.path), "count": self.count,
                          "before": self.before, "after": self.after})


def _effect(board: Board, player_id: int | None, cls: str) -> dict[str, Any]:
    price = None if player_id is None else board.pricing.prices.get(player_id)
    return {"band": None if price is None else price.band.to_dict(), "class": cls, "top": _class_view(board, cls),
            "composition": board.pricing.composition, "targets_departed": list(board.pricing.targets_departed),
            "problems": list(board.problems)}


def adjust(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, adjustment: Adjustment, run_id: str | None = None,
           scenario: str | None = None, state_file: Path | None = None, fresh: bool = False) -> AdjustReport:
    """Append one adjustment and show what it moved. The player is resolved
    against the pinned run first: an entry that resolves to nobody is a bad
    argument here, refused and never written, rather than appended inert."""
    run = open_run(con, run_id)
    player_id = None
    if adjustment.kind != "target":
        probe = resolve([adjustment], run.candidates())
        if probe.problems:
            raise UsageError(probe.problems[0])
        player_id = probe.entries[0].player_id
    cls = adjustment.role_class if adjustment.kind == "target" else run.players[player_id].role_class
    kw = {"run_id": run_id, "scenario": scenario, "state_file": state_file, "fresh": fresh}
    before = board_report(con, paths=paths, **kw)
    try:
        entries = append_adjustment(paths.adjustments, adjustment)
    except AdjustmentsError as exc:
        raise NotReady(str(exc)) from None
    after = board_report(con, paths=paths, **kw)
    return AdjustReport(adjustment, player_id, paths.adjustments, len(entries), _effect(before.board, player_id, cls),
                        _effect(after.board, player_id, cls))


def close_auction(paths: AstaPaths, *, now: datetime, session_code: str | None = None) -> Path:
    """Copy the state file to records/ when the auction closes (live-event
    requirement 5): the days between the room and the transfer are not spent
    with the only record of what was paid on one gitignored disk."""
    if not paths.state.is_file():
        raise NotReady(f"no state file at {paths.state} -- nothing mirrored yet")
    try:
        stored = read_state(paths.state)
        return copy_to_records(paths.state, paths.records, session_code=session_code or stored.session_code, closed_at=now)
    except StateFileError as exc:
        raise NotReady(str(exc)) from None
```

- [ ] **Step 5: The doctor opens the database once and gains three checks**

Replace `core/src/fantaclaude/commands/doctor.py` with the version below. It is the Phase 1 file with: the docstring's new paragraph; `DoctorPaths.adjustments`/`asta_state`; `_open()`; every database-reading check taking the shared connection (`_database_checks(con, detail, skip, path, now)`, `_profiles_check(kb, con)`, `_takers_check(kb, con, skip)`, `_notes_check(kb, con)`, `_scoring_check(con, skip)`, `_valuations_check(con, skip, now)`); `_read_only` deleted; the three new checks; `run_doctor` opening once inside a `try/finally`.

```python
"""fantaclaude doctor: is the workspace ready for the night?

Every check reports existence, parseability, coverage or age -- never a
value. A token is "present, expires in N days", an app key is "set", the
website cookie is "set", and nothing here can leak into a terminal log.

The database is opened once, read-only, for every check that reads it: a
file held by a writer used to be reported as "cannot open database" by one
check and "skipped: no database" by the next, because each check opened
its own connection and drew its own conclusion.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import yaml
from fantacalcio_mcp.auth import AuthError, is_expired
from fantacalcio_mcp.config import ConfigurationError, load_dotenv, resolve_credentials

from fantaclaude.analysis.valuation import PreferencesError, load_preferences
from fantaclaude.asta.adjustments import AdjustmentsError, load_adjustments, resolve
from fantaclaude.asta.pinned import PinnedRunError, load_pinned_run
from fantaclaude.asta.pricing_config import PricingConfigError, load_pricing_config
from fantaclaude.asta.snapshot import StateFileError, read_state
from fantaclaude.config import WEB_COOKIE_KEY
from fantaclaude.db.schema import SCHEMA_VERSION
from fantaclaude.ingest.names import (
    AliasError,
    Candidate,
    load_aliases,
    load_candidates,
    match_listone,
    unresolved_detail,
)
from fantaclaude.kb.notes import (
    NoteError,
    load_player_notes,
    misdeclared_team_notes,
    misplaced_notes,
    orphan_notes,
)
from fantaclaude.kb.participants import ParticipantError, load_participants
from fantaclaude.kb.profiles import ProfileError, load_profiles
from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
from fantaclaude.model.d_factor import DFactorTableError, load_d_factor
from fantaclaude.model.modules import ModuleTableError, load_modules
from fantaclaude.model.scoring import (
    BonusMalus,
    ScoringError,
    modifier_status,
    voto_sheet,
)

CORE_DB_CHECKS = ("database", "extensions", "league_settings", "listone")
HISTORY_DB_CHECKS = ("player_match", "advanced", "fixtures")


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
    pricing: Path
    adjustments: Path
    asta_state: Path


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
    live = 0
    unreadable = 0
    for jwt in jwts:
        try:
            if not is_expired(jwt, now=now.timestamp()):
                live += 1
        except AuthError:
            # A corrupted cached token is treated the same as expired: the
            # next call re-logs in and heals it, rather than doctor raising.
            unreadable += 1
    suffix = f" ({unreadable} unreadable, treated as expired)" if unreadable else ""
    if live == 0:
        return Check("token_cache", False,
                     f"{len(jwts)} league token(s), all expired -- the next call must log in{suffix}")
    return Check("token_cache", True, f"{live}/{len(jwts)} league token(s) valid{suffix}")


def _open(path: Path) -> tuple[duckdb.DuckDBPyConnection | None, str, str]:
    """(the one read-only connection, the database check's detail when there
    is none, the one reason every other database check skips)."""
    if not path.is_file():
        return (None, f"no database at {path} -- run `fantaclaude sync-league` and `fantaclaude ingest listone`",
                "skipped: no database")
    try:
        return duckdb.connect(str(path), read_only=True), "", ""
    except duckdb.Error as exc:
        return None, f"cannot open database at {path}: {exc}", "skipped: database unavailable"


def _history_checks(con: duckdb.DuckDBPyConnection, now: datetime) -> list[Check]:
    checks: list[Check] = []
    coverage = con.execute(
        "SELECT season_id, count(*), max(fetched_at) FROM v_voti_files_current "
        "GROUP BY season_id ORDER BY season_id").fetchall()
    if not coverage:
        checks.append(Check("player_match", False, "no voti yet -- run `fantaclaude ingest stats-web`"))
    else:
        detail = "; ".join(f"season {row[0]}: giornate {row[1]}" for row in coverage)
        checks.append(Check("player_match", True, f"{detail}; newest {_age(coverage[-1][2], now)}"))
    seasons = con.execute(
        "SELECT snapshot_id, season_id, row_count, matched, ambiguous, unmatched, fetched_at FROM advanced_snapshots "
        "WHERE snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id) "
        "ORDER BY season_id").fetchall()
    if not seasons:
        checks.append(Check("advanced", False, "no Understat rows yet -- run `fantaclaude ingest advanced`"))
    else:
        # Finding F9: advanced_snapshots.matched stores counts["matched"]
        # alone -- alias-resolved players (aliases.yml's whole purpose) are
        # counted separately with no column of their own, so the printed
        # numbers under-counted matched by the alias count and never closed
        # against row_count. Derived here without a schema change, the same
        # way record_advanced's own duplicate path already does (a
        # match_status = 'alias' query), and surfaced so the numbers close.
        alias_counts = dict(con.execute(
            "SELECT snapshot_id, count(*) FROM advanced_stats WHERE match_status = 'alias' "
            "AND snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id) "
            "GROUP BY snapshot_id").fetchall())
        detail = "; ".join(
            f"season {r[1]}: {r[2]} rows, {r[3]} matched, {alias_counts.get(r[0], 0)} alias, "
            f"{r[4]} ambiguous, {r[5]} unmatched" for r in seasons)
        keyed = con.execute("SELECT count(*) FROM advanced_snapshots WHERE aliases_sha256 IS NULL "
                            "AND snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id)").fetchone()[0]
        if keyed:
            detail += f"; {keyed} season(s) recorded before the full dedupe key -- the next `ingest advanced --rematch` re-matches them"
        checks.append(Check("advanced", True, f"{detail}; newest {_age(seasons[-1][6], now)}"))
    current = con.execute("SELECT max(season_id) FROM v_league_settings_current").fetchone()[0]
    serie_a = con.execute(
        "SELECT count(DISTINCT giornata) FROM v_fixtures_current WHERE competition = 'SA' AND season_id = ?",
        [current]).fetchone()[0]
    ties = con.execute(
        "SELECT count(*), count(DISTINCT team_short) FROM v_european_ties WHERE season_id = ?",
        [current]).fetchone()
    if not serie_a:
        checks.append(Check("fixtures", False,
                            f"no Serie A calendar for season {current} -- run `fantaclaude ingest calendar`"))
    else:
        checks.append(Check("fixtures", True,
                            f"season {current}: {serie_a} giornate; {ties[0]} European ties for {ties[1]} clubs"))
    return checks


def _database_checks(con: duckdb.DuckDBPyConnection | None, detail: str, skip: str, path: Path,
                     now: datetime) -> tuple[list[Check], list[Check]]:
    """(the Phase 0a checks, the history checks) -- reported in two places so the
    check order stays the documented one."""
    if con is None:
        return ([Check("database", False, detail)] + [Check(name, False, skip) for name in CORE_DB_CHECKS[1:]],
                [Check(name, False, skip) for name in HISTORY_DB_CHECKS])
    core: list[Check] = []
    history: list[Check] = []
    try:
        version = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
        note = (" -- any ingest or sync-league migrates it forward"
                if version is not None and version < SCHEMA_VERSION else "")
        core.append(Check("database", version == SCHEMA_VERSION,
                          f"schema version {version}, code expects {SCHEMA_VERSION}{note}"))
        installed = {r[0] for r in con.execute(
            "SELECT extension_name FROM duckdb_extensions() WHERE installed").fetchall()}
        needed = {"json", "parquet"}
        core.append(Check("extensions", needed <= installed,
                          f"installed: {', '.join(sorted(needed & installed)) or 'none'}; "
                          f"missing: {', '.join(sorted(needed - installed)) or 'none'}"))
        row = con.execute("SELECT fetched_at, rules_hash, budget, team_count FROM v_league_settings_current").fetchone()
        if row is None:
            core.append(Check("league_settings", False, "no snapshot -- run `fantaclaude sync-league`"))
        else:
            core.append(Check("league_settings", True,
                              f"rules {row[1]}, budget {row[2]}, {row[3]} teams, {_age(row[0], now)}"))
        row = con.execute("SELECT fetched_at, player_count FROM listone_snapshots "
                          "ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        if row is None:
            core.append(Check("listone", False, "no snapshot -- run `fantaclaude ingest listone`"))
        else:
            core.append(Check("listone", True, f"{row[1]} players, {_age(row[0], now)}"))
        if version != SCHEMA_VERSION:
            history = [Check(name, False, f"skipped: schema version {version}, expected {SCHEMA_VERSION}")
                       for name in HISTORY_DB_CHECKS]
        else:
            history = _history_checks(con, now)
    except duckdb.Error as exc:
        # The file can exist and still not carry the schema: connect() creates
        # it before apply_schema runs, so an interrupted first sync-league
        # leaves exactly this state. Report the checks that did not run rather
        # than raising out of doctor -- the check names are a contract.
        done = {c.name for c in core} | {c.name for c in history}
        for name in CORE_DB_CHECKS:
            if name not in done:
                core.append(Check(name, False, f"database at {path} is unusable: {exc}" if name == "database"
                                  else "skipped: database unusable"))
        for name in HISTORY_DB_CHECKS:
            if name not in done:
                history.append(Check(name, False, "skipped: database unusable"))
    return core, history


def _preferences_check(path: Path) -> Check:
    """The same loader `rank` runs, not a look-alike (finding 4).

    Parsing the file and demanding a `target_composition` key made doctor
    disagree with `rank` in both directions: `excluded_clubs`, a bad
    `risk_appetite` or a scenario naming an unknown role class all passed
    here and then exited 2 in `rank` -- after the live re-sync this command
    exists to gate had already been spent -- while a file with no
    `target_composition` failed here and ranked without complaint."""
    if not path.is_file():
        return Check("preferences", False, f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return Check("preferences", False, f"does not parse: {exc}")
    if data is not None and not isinstance(data, dict):
        return Check("preferences", False, "the top level must be a mapping")
    try:
        scenarios = load_preferences(data or {})
    except PreferencesError as exc:
        return Check("preferences", False, str(exc))
    return Check("preferences", True, f"{len(scenarios)} scenario(s): "
                                      + ", ".join(f"{s.name} ({s.quantile})" for s in scenarios))


def _profiles_check(kb: Path, con: duckdb.DuckDBPyConnection | None) -> Check:
    """Every listone club has a profile, and its `europe` agrees with the fixtures."""
    try:
        profiles = load_profiles(kb)
    except ProfileError as exc:
        return Check("kb_profiles", False, str(exc))
    teams: dict[str, str] = {}
    ties: dict[str, set[str]] = {}
    if con is not None:
        try:
            teams = {short: name for name, short in con.execute("SELECT name, short FROM v_teams_current").fetchall()}
            current = con.execute("SELECT max(season_id) FROM v_league_settings_current").fetchone()[0]
            for short, competition in con.execute(
                    "SELECT DISTINCT team_short, competition FROM v_european_ties WHERE season_id = ?",
                    [current]).fetchall():
                ties.setdefault(short, set()).add(competition)
        except duckdb.Error:
            teams, ties = {}, {}
    profiled = {p.team_short for p in profiles}
    problems: list[str] = []
    missing = sorted(name for short, name in teams.items() if short not in profiled)
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    if ties:
        for profile in profiles:
            actual = ties.get(profile.team_short, set())
            if actual and profile.europe not in actual:
                problems.append(f"{profile.team}: profile says {profile.europe}, fixtures say {'/'.join(sorted(actual))}")
    total = len(teams) if teams else len(profiles)
    head = f"{len(profiled & set(teams)) if teams else len(profiles)}/{total} teams profiled"
    if problems:
        return Check("kb_profiles", False, f"{head}; {'; '.join(problems)}")
    return Check("kb_profiles", True, f"{head}; europe agrees with the fixtures")


def _takers_check(kb: Path, con: duckdb.DuckDBPyConnection | None, skip: str) -> Check:
    """Every set-piece taker a profile names, resolved against the listone the
    way `rank` resolves them (finding 20b).

    Notes get `orphan_notes` and `misdeclared_team_notes` precisely because
    they carry a `player_id`. A taker carries only a name, so nothing checked
    him at all: a taker who transferred, or whom the listone re-spelt
    ("Martinez" -> "Martinez L."), silently dropped his whole club back to
    historical penalty splits -- and the only thing that said so was a
    `run.warnings` line from `rank`, i.e. after the live re-sync this command
    exists to gate. Every role is resolved, not only `penalties`: only that
    one feeds the model today, but a name the club's squad does not have is a
    profile gone stale whichever line it sits on."""
    try:
        profiles = load_profiles(kb)
    except ProfileError as exc:
        return Check("kb_takers", False, str(exc))          # the kb_profiles check says the same; keep the names honest
    if con is None:
        return Check("kb_takers", False, skip)
    try:
        candidates = load_candidates(con)
    except duckdb.Error as exc:
        return Check("kb_takers", False, f"skipped: {exc}")
    squads: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        squads.setdefault(candidate.team_short, []).append(candidate)
    named = 0
    problems: list[str] = []
    for profile in sorted(profiles, key=lambda p: p.team):
        squad = squads.get(profile.team_short, [])
        for role, name in sorted(profile.takers.items()):
            if not name:
                continue
            named += 1
            match = match_listone(name, squad)
            if match.player_id is None:
                problems.append(f"{profile.team} {role}: {name!r} "
                                f"{unresolved_detail(profile.team, match, squad)}")
    head = f"{named - len(problems)}/{named} takers resolve against the listone"
    if problems:
        return Check("kb_takers", False, f"{head}; " + "; ".join(problems))
    return Check("kb_takers", True, head)


def _notes_check(kb: Path, con: duckdb.DuckDBPyConnection | None) -> Check:
    try:
        notes = load_player_notes(kb)
    except NoteError as exc:
        return Check("kb_notes", False, str(exc))
    names: dict[int, str] = {}
    shorts: dict[int, str] = {}
    if con is not None:
        try:
            rows = con.execute("SELECT player_id, team_name, team_short FROM v_players_current").fetchall()
            names = {int(pid): str(name) for pid, name, _ in rows}
            shorts = {int(pid): str(short) for pid, _, short in rows}
        except duckdb.Error:
            names, shorts = {}, {}
    moved = misplaced_notes(notes, names)
    orphans = orphan_notes(notes, names)
    mismatched = misdeclared_team_notes(notes, shorts)
    problems = []
    if moved:
        problems.append("misplaced: " + "; ".join(
            f"{n.name} sits under {n.path.parent.parent.name}, belongs under {slug}" for n, slug in moved))
    if orphans:
        # inputs_hash sees every one of these, and build_inputs never looks any of them
        # up: a run with one looks like a new run even though nothing in it applied.
        problems.append("orphan (player_id not in the listone, has no effect): " + ", ".join(
            f"{n.name} ({n.path})" for n in orphans))
    if mismatched:
        problems.append("team_short disagrees with the listone: " + "; ".join(
            f"{n.name} says {n.team_short}, listone says {short}" for n, short in mismatched))
    if problems:
        return Check("kb_notes", False, f"{len(notes)} notes; " + "; ".join(problems))
    return Check("kb_notes", True, f"{len(notes)} notes")


def _participants_check(kb: Path, league_yml: Path) -> Check:
    try:
        dossiers = load_participants(kb)
    except ParticipantError as exc:
        return Check("kb_participants", False, str(exc))
    mapped: dict[str, str] = {}
    if league_yml.is_file():
        try:
            for key, entry in load_league_yml(league_yml).items():
                if key.startswith("participants."):
                    mapped[key.removeprefix("participants.")] = str(entry.value)
        except (LeagueYmlError, yaml.YAMLError):
            pass                                              # the league_yml check reports it
    by_nick = {d.nick: d for d in dossiers}
    problems = [f"league.yml maps {nick} to {path}, which does not load"
                for nick, path in mapped.items() if not (kb.parent / path).is_file() or nick not in by_nick]
    head = f"{len(dossiers)} dossiers; league.yml maps {len(mapped)}"
    if problems:
        return Check("kb_participants", False, f"{head}; {'; '.join(problems)}")
    return Check("kb_participants", True, head)


def _scoring_check(con: duckdb.DuckDBPyConnection | None, skip: str) -> Check:
    if con is None:
        return Check("scoring", False, skip)
    try:
        row = con.execute("SELECT payload FROM v_league_settings_current").fetchone()
    except duckdb.Error as exc:
        return Check("scoring", False, f"skipped: {exc}")
    if row is None:
        return Check("scoring", False, "no league_settings snapshot -- run `fantaclaude sync-league`")
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    calculate = payload.get("calculate") or {}
    try:
        sheet = voto_sheet(calculate)
        BonusMalus.from_calculate(calculate)
    except ScoringError as exc:
        return Check("scoring", False, str(exc))
    status = modifier_status(calculate)
    head = f"voto source {calculate.get('sourcev')} -> sheet {sheet} (mapping unverified: confirm on the league's calcolo page)"
    if status.unknown_active:
        return Check("scoring", False, f"{head}; modifier(s) {list(status.unknown_active)} active: `rank` refuses until modelled")
    if status.d_factor:
        try:
            table = load_d_factor()
        except DFactorTableError as exc:
            return Check("scoring", False, f"{head}; D-Factor active; {exc}")
        if table.is_empty:
            return Check("scoring", False, f"{head}; D-Factor active but model/d_factor.yml has no bands -- transcribe the league's table")
        return Check("scoring", True, f"{head}; D-Factor active, table verified {table.verified_on}")
    return Check("scoring", True, f"{head}; no modifier active")


def _pricing_check(path: Path) -> Check:
    try:
        cfg = load_pricing_config(path)
    except PricingConfigError as exc:
        return Check("pricing", False, str(exc))
    return Check("pricing", True, f"{len(cfg.to_dict())} knobs; bench_weight {cfg.bench_weight}, "
                                  f"candidates {cfg.candidates_per_class}, inflation [{cfg.inflation_floor}, {cfg.inflation_ceiling}]")


def _valuations_check(con: duckdb.DuckDBPyConnection | None, skip: str, now: datetime) -> Check:
    if con is None:
        return Check("valuations", False, skip)
    try:
        row = con.execute("SELECT run_id, created_at, superseded, scenarios FROM v_valuation_runs "
                          "ORDER BY created_at DESC, run_id DESC LIMIT 1").fetchone()
    except duckdb.Error as exc:
        return Check("valuations", False, f"skipped: {exc}")
    if row is None:
        return Check("valuations", False, "no valuation run yet -- run `fantaclaude rank`")
    state = "superseded by a rules change -- re-run `fantaclaude rank`" if row[2] else "not superseded"
    return Check("valuations", not row[2], f"run {row[0]}, {_age(row[1], now)}, scenarios {', '.join(row[3])}; {state}")


def _pinned_run_check(con: duckdb.DuckDBPyConnection | None, skip: str) -> Check:
    """Is the run `asta` would pin loadable -- rows, config, its settings row (spec: a doctor check for the night)."""
    if con is None:
        return Check("pinned_run", False, skip)
    try:
        run = load_pinned_run(con)
    except PinnedRunError as exc:
        return Check("pinned_run", False, str(exc))
    except duckdb.Error as exc:
        return Check("pinned_run", False, f"skipped: {exc}")
    return Check("pinned_run", True, run.describe())


def _adjustments_check(path: Path, con: duckdb.DuckDBPyConnection | None) -> Check:
    """Does data/adjustments.yml parse, and does every entry resolve against the run it would be applied to."""
    if not path.is_file():
        return Check("adjustments", True, f"none yet ({path} does not exist)")
    try:
        adjustments = load_adjustments(path)
    except AdjustmentsError as exc:
        return Check("adjustments", False, str(exc))
    head = f"{len(adjustments)} adjustment(s)"
    if con is None:
        return Check("adjustments", True, f"{head}, parse; no database to resolve them against")
    try:
        run = load_pinned_run(con)
    except (PinnedRunError, duckdb.Error):
        return Check("adjustments", True, f"{head}, parse; no run to resolve them against (see pinned_run)")
    layer = resolve(adjustments, run.candidates())
    if layer.problems:
        return Check("adjustments", False, f"{head}, {len(layer.problems)} inert: " + "; ".join(layer.problems))
    kinds = {kind: sum(1 for e in layer.entries if e.adjustment.kind == kind) for kind in ("value", "exclude", "target")}
    return Check("adjustments", True, f"{head} resolved against run {run.run_id}: "
                                      + ", ".join(f"{n} {kind}" for kind, n in kinds.items() if n))


def _asta_state_check(path: Path, now: datetime) -> Check:
    if not path.is_file():
        return Check("asta_state", True, "no state file (no auction mirrored yet)")
    try:
        stored = read_state(path)
        written = datetime.fromisoformat(stored.written_at)
    except (StateFileError, ValueError) as exc:
        return Check("asta_state", False, str(exc))
    return Check("asta_state", True, f"session {stored.session_code or '?'}, run {stored.run_id}, "
                                     f"{len(stored.snapshot.picks)} picks, written {_age(written, now)}")


def run_doctor(paths: DoctorPaths, *, now: datetime) -> list[Check]:
    # Mirror load_settings() exactly -- same merge, same resolver. Deriving
    # this independently made doctor disagree with the commands it exists to
    # predict, in both directions: it passed a username whose password did not
    # resolve, and failed a workspace configured through the environment.
    env = {**(load_dotenv(paths.env) if paths.env.is_file() else {}), **os.environ}
    app_key = (env.get("FANTACALCIO_APP_KEY") or "").strip()
    checks = [Check("env", bool(app_key),
                    "FANTACALCIO_APP_KEY set" if app_key
                    else f"FANTACALCIO_APP_KEY not set in {paths.env} or the environment")]
    try:
        credentials = resolve_credentials(env)
    except ConfigurationError as exc:
        checks.append(Check("credentials", False, str(exc).split(".")[0]))
    else:
        checks.append(Check("credentials", True,
                            "login mode (password from the keychain or .env)"
                            if credentials.can_login
                            else "token-only mode (no self-healing on expiry)"))
    checks.append(_token_cache(paths.token_cache, now))
    con, detail, skip = _open(paths.db)
    try:
        core, history = _database_checks(con, detail, skip, paths.db, now)
        checks.extend(core)
        try:
            entries = load_league_yml(paths.league_yml) if paths.league_yml.is_file() else None
            checks.append(Check("league_yml", entries is not None,
                                f"{len(entries)} provenanced keys" if entries is not None else f"{paths.league_yml} is missing"))
        except (LeagueYmlError, yaml.YAMLError) as exc:
            checks.append(Check("league_yml", False, str(exc)))
        checks.append(_preferences_check(paths.preferences))
        kb_ok = (paths.kb / "README.md").is_file() and (paths.kb / "rules" / "aliases.yml").is_file()
        checks.append(Check("kb", kb_ok, f"{paths.kb}" + ("" if kb_ok else " lacks README.md or rules/aliases.yml")))
        try:
            checks.append(Check("modules", True, f"{len(load_modules())} modules"))
        except (ModuleTableError, OSError, ValueError, yaml.YAMLError) as exc:
            checks.append(Check("modules", False, str(exc)))
        cookie = (env.get(WEB_COOKIE_KEY) or "").strip()
        checks.append(Check("web_session", bool(cookie),
                            f"{WEB_COOKIE_KEY} set" if cookie
                            else f"{WEB_COOKIE_KEY} not set -- `fantaclaude ingest stats-web` will be skipped"))
        checks.extend(history)
        aliases_file = paths.kb / "rules" / "aliases.yml"
        try:
            aliases = load_aliases(aliases_file) if aliases_file.is_file() else None
            checks.append(Check("aliases", aliases is not None,
                                f"{len(aliases.players) + len(aliases.teams)} sections" if aliases is not None
                                else f"{aliases_file} is missing"))
        # Finding F8: load_aliases calls path.read_text(encoding="utf-8"), which
        # can raise OSError (permissions) or UnicodeDecodeError (non-UTF-8) --
        # neither is an AliasError or a yaml.YAMLError, so left uncaught either
        # one took the whole `fantaclaude doctor` command down, unlike every
        # other check here, which reports a failure as a failed check.
        except (AliasError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            checks.append(Check("aliases", False, str(exc)))
        checks.append(_profiles_check(paths.kb, con))
        checks.append(_takers_check(paths.kb, con, skip))
        checks.append(_notes_check(paths.kb, con))
        checks.append(_participants_check(paths.kb, paths.league_yml))
        checks.append(_scoring_check(con, skip))
        checks.append(_pricing_check(paths.pricing))
        checks.append(_valuations_check(con, skip, now))
        checks.append(_pinned_run_check(con, skip))
        checks.append(_adjustments_check(paths.adjustments, con))
        checks.append(_asta_state_check(paths.asta_state, now))
    finally:
        if con is not None:
            con.close()
    return checks
```

- [ ] **Step 6: The `asta` group in `cli/app.py`**

Add `from pathlib import Path` to the imports at the top of `core/src/fantaclaude/cli/app.py` (after `from enum import IntEnum`). In `doctor_cmd`, add `adjustments_path` and `asta_state_path` to the `from fantaclaude.paths import (...)` list, extend the command's docstring with ", the pinned run, adjustments.yml, the auction state file", and end the `DoctorPaths(...)` call with `pricing=pricing_yml_path(), adjustments=adjustments_path(), asta_state=asta_state_path())`. Then insert, immediately before `def main() -> None:`:

```python
asta_app = typer.Typer(name="asta", help="The auction core, offline: the pinned run priced against the mirrored session, "
                                          "adjustments, the state file. No network.", no_args_is_help=True)
app.add_typer(asta_app)

# Module-level singletons (B008), shared by the asta commands.
RUN_OPTION = typer.Option(None, "--run", help="Pin this valuation run (default: the newest not superseded).")
ONE_SCENARIO_OPTION = typer.Option(None, "--scenario", help="The run's scenario to price under (default: its first).")
STATE_OPTION = typer.Option(None, "--state", help="A state file to load instead of data/asta-state.json.")
FRESH_OPTION = typer.Option(False, "--fresh", help="Ignore any state file: an empty auction under the run's league settings.")
ME_OPTION = typer.Option(None, "--me", help="My team, by label or id (a state file remembers it).")
MAP_OPTION = typer.Option(None, "--map", help="team=nick -- bind a team to its dossier under kb/league/participants; repeatable.")


def _asta_paths():
    from fantaclaude.commands.asta import AstaPaths
    from fantaclaude.paths import adjustments_path, asta_state_path, db_path, kb_dir, records_dir

    return AstaPaths(db=db_path(), adjustments=adjustments_path(), state=asta_state_path(), records=records_dir(), kb=kb_dir())


@contextmanager
def _asta_errors():
    """The asta commands' half of the exit-code contract: a bad flag is 2, a missing or malformed input is 3."""
    from fantaclaude.analysis.valuation import UnknownScenarioError
    from fantaclaude.commands.asta import UsageError
    from fantaclaude.commands.ingest import NotReady

    try:
        yield
    except NotReady as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    except (UsageError, UnknownScenarioError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.USAGE) from None


def _band(b: dict | None) -> str:
    return "-" if b is None else f"{b['p50']} [{b['p25']}-{b['p75']}]"


def _render_lot(payload: dict) -> str:
    lot = payload.get("lot")
    if lot is None:
        return "lot: none on the block"
    line = f"lot: {lot['name']} ({lot['role_class']}, {lot['team_short']}, t{lot['tier']}) band {_band(lot['band'])}"
    if lot.get("sold_to") is not None:
        line += f" · sold to team {lot['sold_to']}"
    elif lot.get("expected_price") is not None:
        line += f" · expected {lot['expected_price']}"
    pressure = payload.get("lot_pressure")
    if pressure and pressure["bidders"]:
        top = pressure["bidders"][0]
        line += (f" · pressure: est. {pressure['estimate']} ({top['label']} {top['intent']} up to {top['ceiling']}"
                 + (f", {len(pressure['bidders']) - 1} more" if len(pressure["bidders"]) > 1 else "") + ")")
    return line


def _render_board(payload: dict) -> str:
    s, me = payload["settings"], payload["me"]
    lines = [payload["run"], f"source: {payload['source']}",
             (f"session: {s['budget']} credits · goalkeepers {s['goalkeepers'][0]}-{s['goalkeepers'][1]} · outfield "
              f"{s['outfield'][0]}-{s['outfield'][1]} · roster {s['size'][0]}-{s['size'][1]} · {s['team_count']} teams "
              f"({s['source']}) · scenario {payload['scenario']}")]
    lines += [f"SESSION != LEAGUE: {c}" for c in payload["league_conflicts"]]
    lines.append(f"me: {me['label']} (team {me['team_id']}) · {me['credits']} credits · {len(me['picks'])} picks "
                 f"(gk {me['goalkeepers']}, mov {me['outfield']}) · still needed: gk {me['missing_goalkeepers']}, "
                 f"mov {me['missing_outfield']} · market {payload['market_credits']} credits")
    comp = ", ".join(f"{cls} {n}·{payload['credits_by_class'].get(cls, 0)}" for cls, n in payload["composition"].items() if n)
    departed = f" · departed from the target at {', '.join(payload['targets_departed'])}" if payload["targets_departed"] else ""
    lines.append(f"board: inflation {payload['inflation']:.2f} · reserve {payload['reserve']} · budget {payload['budget']} "
                 f"· completion {comp}{departed}")
    lines.append(_render_lot(payload))
    for cls, rows in payload["tiers"].items():
        lines.append(f"  {cls}: " + " · ".join(
            f"{r['name']} {_band(r['band'])} t{r['tier']}" + (f" p{r['pressure']['estimate']}" if r.get("pressure") else "")
            for r in rows))
    adj = payload["adjustments"]
    lines.append(f"adjustments: {adj['count']} ({adj['applied']} applied)" + (f" · sha {adj['sha256'][:8]}" if adj["sha256"] else ""))
    lines += [f"note: {n}" for n in payload.get("notes", [])]
    lines += [f"problem: {p}" for p in payload["problems"]]
    return "\n".join(lines)


@asta_app.command("board")
def asta_board_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    state: Path | None = STATE_OPTION,
    fresh: bool = FRESH_OPTION,
    me: str | None = ME_OPTION,
    map_: list[str] | None = MAP_OPTION,
    top: int = typer.Option(5, "--top", help="Players per class on the tier board."),
) -> None:
    """Price the pinned run against the mirrored auction (data/asta-state.json if present, else an empty one): my credits and slots, the completion, the lot on the block, the tier board. Local."""
    from fantaclaude.commands.asta import board_report

    with _asta_errors():
        con = _open_read_only()
        try:
            report = board_report(con, paths=_asta_paths(), run_id=run, scenario=scenario, state_file=state, fresh=fresh,
                                  me=me, maps=tuple(map_ or ()), top=top)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_board)


def _render_explain(payload: dict) -> str:
    p = payload["player"]
    lines = [payload["run"], f"source: {payload['source']}",
             f"{p['name']} ({p['team_short']}, {'/'.join(p['roles'])} -> {p['role_class']}, t{p['tier']}) · "
             f"value {p['value_p50']:.1f} [{p['value_p25']:.1f}-{p['value_p75']:.1f}] · quotazione {p['quotazione']}"]
    if payload["sold_to"] is not None:
        lines.append(f"sold to team {payload['sold_to']} for {payload['cost']}")
    trace = payload["trace"]
    if trace is None:
        lines.append("not priced: sold, or excluded by an adjustment")
    else:
        lines.append(f"band {_band(trace['band'])} · expected {trace['expected_price']} · rank weight {trace['rank_weight']:.3f} · "
                     f"walk {trace['walk_value']} · buy {trace['buy_value']}")
        lines.append(f"board: inflation {trace['inflation']:.2f} · reserve {trace['reserve']} · budget {trace['budget']} · "
                     f"slot price {trace['slot_price']:.2f} · completion " + ", ".join(
                         f"{cls} {n}" for cls, n in trace["composition"].items() if n))
    if payload["pressure"]:
        pr = payload["pressure"]
        lines.append(f"pressure: est. {pr['estimate']} (expected {pr['expected']}); " + "; ".join(
            f"{b['label']} {b['intent']} up to {b['ceiling']} (credits {b['credits']}, depth {b['depth']}"
            + (", " + ", ".join(b["reasons"]) if b["reasons"] else "") + ")" for b in pr["bidders"]))
    lines += [f"adjustment: {a}" for a in payload["adjustments"]]
    lines += [f"problem: {q}" for q in payload["problems"]]
    return "\n".join(lines)


@asta_app.command("explain")
def asta_explain_cmd(
    player: str = typer.Argument(..., help="A player, the listone's way (\"Martinez L.\") or by id."),
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    state: Path | None = STATE_OPTION,
    fresh: bool = FRESH_OPTION,
) -> None:
    """The trace behind one player's price on the current board -- for the model to read, never to recompute."""
    from fantaclaude.commands.asta import explain_report

    with _asta_errors():
        con = _open_read_only()
        try:
            report = explain_report(con, paths=_asta_paths(), player=player, run_id=run, scenario=scenario,
                                    state_file=state, fresh=fresh)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_explain)


def _render_replay(payload: dict) -> str:
    lines = [payload["run"], f"me: team {payload['mapping']['mine']}"]
    for step in payload["steps"]:
        events = "; ".join(step["events"]) or "(no change)"
        lot = f" · lot {step['lot']['name']} {_band(step['lot']['band'])}" if step["lot"] else ""
        lines.append(f"{step['index']:>3}: {events} · me {step['credits']} credits · {step['picks']} picks{lot}")
    lines.append("final " + _render_board({**payload, "source": "the last snapshot", "notes": []}).split("\n", 1)[1])
    if payload["written"]:
        lines.append(f"state written to {payload['written']}")
    return "\n".join(lines)


@asta_app.command("replay")
def asta_replay_cmd(
    file: Path = typer.Argument(..., help="A captured session: one state node per line (JSON lines)."),
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    me: str | None = ME_OPTION,
    map_: list[str] | None = MAP_OPTION,
    write_state: bool = typer.Option(False, "--write-state", help="Write data/asta-state.json from the last snapshot."),
) -> None:
    """Run a captured session through the whole pipeline -- the rehearsal harness -- and print what every snapshot moved."""
    from fantaclaude.commands.asta import replay_report

    paths = _asta_paths()
    with _asta_errors():
        con = _open_read_only()
        try:
            report = replay_report(con, paths=paths, file=file, run_id=run, scenario=scenario, me=me,
                                   maps=tuple(map_ or ()), write_state_to=paths.state if write_state else None)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_replay)


def _render_adjust(payload: dict) -> str:
    before, after = payload["before"], payload["after"]
    lines = [f"appended to {payload['path']} ({payload['count']} entries): {payload['described']}"]
    if payload["player_id"] is not None:
        lines.append(f"his band: {_band(before['band'])} -> {_band(after['band'])}")
    top = " · ".join(f"{a['name']} {_band(b['band'])} -> {_band(a['band'])}" for b, a in zip(before["top"], after["top"])
                     if b["player_id"] == a["player_id"])
    lines.append(f"{after['class']}: {top}" if top else f"{after['class']}: " + " · ".join(
        f"{r['name']} {_band(r['band'])}" for r in after["top"]))
    comp = ", ".join(f"{cls} {before['composition'].get(cls, 0)}->{n}" for cls, n in after["composition"].items()
                     if n != before["composition"].get(cls, 0))
    if comp:
        lines.append(f"composition moved: {comp}")
    if after["targets_departed"]:
        lines.append(f"departed from the target at {', '.join(after['targets_departed'])}")
    lines += [f"problem: {p}" for p in after["problems"]]
    return "\n".join(lines)


@asta_app.command("adjust")
def asta_adjust_cmd(
    type_: str = typer.Option(..., "--type", help="value | exclude | target."),
    reason: str = typer.Option(..., "--reason", help="Why -- the auction record explains itself afterwards."),
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    player: str | None = typer.Option(None, "--player", help="The player, the listone's way (\"Martinez L.\")."),
    player_id: int | None = typer.Option(None, "--player-id", help="Or his listone id."),
    factor: float | None = typer.Option(None, "--factor", help="value: scale his projection by this (0, 2]."),
    class_: str | None = typer.Option(None, "--class", help="target: the role class."),
    count: int | None = typer.Option(None, "--count", help="target: the composition to start from."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    state: Path | None = STATE_OPTION,
    fresh: bool = FRESH_OPTION,
) -> None:
    """Append a belief to data/adjustments.yml -- a value factor, an exclusion, a target -- and show what it moved on the board."""
    from fantaclaude.asta.adjustments import AdjustmentsError, adjustment_from_entry
    from fantaclaude.commands.asta import UsageError, adjust

    raw = {k: v for k, v in (("player", player), ("player_id", player_id), ("type", type_), ("factor", factor),
                             ("class", class_), ("count", count), ("reason", reason)) if v is not None}
    with _asta_errors():
        try:
            adjustment = adjustment_from_entry(raw, "asta adjust")
        except AdjustmentsError as exc:
            raise UsageError(str(exc)) from None
        con = _open_read_only()
        try:
            report = adjust(con, paths=_asta_paths(), adjustment=adjustment, run_id=run, scenario=scenario,
                            state_file=state, fresh=fresh)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_adjust)


@asta_app.command("close")
def asta_close_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    session: str | None = typer.Option(None, "--session", help="The session code to name the copy by (default: the file's)."),
) -> None:
    """Copy data/asta-state.json to records/asta/ when the auction closes -- the record of what the room paid, until the transfer is verified."""
    from fantaclaude.commands.asta import close_auction
    from fantaclaude.timeutil import utc_now

    with _asta_errors():
        path = close_auction(_asta_paths(), now=utc_now(), session_code=session)
    emit({"records": str(path)}, json_=json_, render=lambda p: f"copied to {p['records']} -- commit records/")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_asta_cli.py core/tests/test_doctor.py core/tests/test_cli_app.py -q`
Expected: PASS. `uv run pytest core/tests -q` → about 413 passed (406 + 6 in `test_asta_cli` + 2 in `test_doctor`, minus nothing). If a rendering assertion fails, fix the renderer to say what the test expects rather than the other way round — the wording is the contract the skill reads.

- [ ] **Step 8: The docs and the skill**

In `core/README.md`, after the `fantaclaude rank` row of the commands table, add:

```markdown
| `fantaclaude asta board [--run ID] [--scenario NAME] [--state FILE] [--fresh] [--me TEAM] [--map TEAM=NICK]… [--top N]` | the pinned run priced against the mirrored auction (`data/asta-state.json` when it exists, else an empty auction under the run's league settings): my credits and slots, the completion, the lot on the block with its band and the pressure against it, the tier board per class |
| `fantaclaude asta explain PLAYER` | one player's trace on the current board — band, expected price, walk/buy values, the completion, the pressure, the adjustments applied to him |
| `fantaclaude asta replay FILE --me TEAM [--map TEAM=NICK]… [--write-state]` | a captured session (one FantaAstaLive state node per line) through the whole pipeline: what every snapshot moved, the final board — the rehearsal harness |
| `fantaclaude asta adjust --type value\|exclude\|target [--player NAME \| --player-id ID] [--factor F] [--class CLS --count N] --reason WHY` | append a belief to `data/adjustments.yml` and show what it moved |
| `fantaclaude asta close [--session CODE]` | copy `data/asta-state.json` to `records/asta/` when the auction closes |
```

and after the paragraph that starts "`sync-league`, `ingest` and `rank` (unless `--offline`) call the live league API", add: "Every `fantaclaude asta` command is local: it opens the database read-only and touches no network, so it may be run freely — during the auction included." In "Layout", after the sentence about `pricing.yml`, add: "`data/adjustments.yml` is the auction's adjustment file — mine, hand-editable, appended by `fantaclaude asta adjust`, every entry with a `reason`; `data/asta-state.json` is the mirrored auction as last seen, written atomically and never edited by hand; `records/asta/` holds its copy from `fantaclaude asta close` until the transfer into the lega is verified."

In `site/docs/cli.md`, change "Three groups of commands" to "Four groups of commands", append before the closing paragraph:

```markdown
## `fantaclaude asta`

The auction core, offline: `asta board` prices the newest valuation run
against the auction as last mirrored (or an empty one), `asta explain` reads
one player's trace, `asta replay` runs a captured FantaAstaLive session
through the whole pipeline as a rehearsal, `asta adjust` appends a belief —
a value factor, an exclusion, a target composition — and shows what it moved,
and `asta close` copies the state file to `records/` when the auction ends.
The live feed and the dashboard that sit on top of these are Phase 2b.
```

and extend the closing sentence: "… everything else in the CLI, `asta` included, works against data already on disk."

In `records/README.md`, replace the bullet "the auction snapshot between the auction and the confirmed transfer into the lega (Phase 2)." with: "`asta/<session>-<UTC stamp>.json` — the auction state file as it stood when the auction closed, copied by `fantaclaude asta close`; it and `data/asta-state.json` are deleted only once `verify-transfer` (Phase 2b) confirms the lega matches the room."

In `CLAUDE.md`, "Workspace and tests", append a paragraph:

```markdown
`data/adjustments.yml` is the auction's adjustment file — mine, hand-editable,
appended by `fantaclaude asta adjust`; every entry needs a `reason`.
`data/asta-state.json` is the mirrored auction as last seen: written
atomically by the tooling, never edited by hand, copied to `records/asta/` by
`fantaclaude asta close` and deleted only once the transfer into the lega is
verified (Phase 2b). Every `fantaclaude asta` command is local — read-only on
the database, no network — so it may be run freely, during the auction
included.
```

Create `.claude/skills/fanta-asta/SKILL.md`:

```markdown
---
name: fanta-asta
description: The auction copilot's offline half with fantaclaude — read the board the pinned run gives against the mirrored auction (`asta board`), explain one price (`asta explain`), turn a fact from the room into an adjustment (`asta adjust`), rehearse on a captured session (`asta replay`), close the auction (`asta close`). Use before and during the auction, and to rehearse. The live feed, the dashboard and the MCP tools are Phase 2b and are not here yet.
---

# fanta-asta

Python does the math; this skill does the judgment. It never computes a max
price: it reads the board `fantaclaude asta board` prints, changes *inputs*
(an adjustment with a reason, a dossier, the scenario) and reads again.
Discover the CLI with `fantaclaude asta --help`; every command takes `--json`
and every one is local — no network, the database read-only — so it may be
run as often as needed, during the auction included.

Three rules, defended hard:

- **The model changes inputs and interprets outputs; it never computes the
  number.** A max price is a band the pricer solved; "why 62 for a player I
  valued at 30?" is answered by `asta explain`, which reads the trace —
  `walk_value`, `buy_value`, the completion, the inflation — never by
  re-deriving it.
- **A fact from the room is an adjustment with a reason.** "He's limping" →
  `asta adjust --type value --player "Bastoni" --factor 0.85 --reason "limping,
  reported in the room"`. "I will not buy him" → `--type exclude`. "Go heavier
  on Dc" → `--type target --class Dc --count 4`. The file is
  `data/adjustments.yml`; it outlives the auction, and every entry says why.
- **The mirror is faithful.** The board shows what the admin recorded; a
  mistyped price is the admin's to fix, never ours. The one input the feed
  cannot supply is which team is mine (`--me`) and which dossier each rival
  maps to (`--map host=Marco`); a state file remembers them.

## Modes

### `board`

`fantaclaude asta board` — the pinned run (the newest not superseded; `--run`
to pin another; `--scenario` to price under another of its scenarios) against
`data/asta-state.json` when one exists, else an empty auction under the run's
league settings. Read: the `session:` line and any `SESSION != LEAGUE` line
(the session wins for the night; a mismatch is announced, never absorbed);
`me:` credits, picks, what is still needed; `board:` inflation, reserve, the
completion it would buy; `lot:` the player on the block with his band and the
pressure against him; the tier board per class; every `problem:`.

### `explain`

`fantaclaude asta explain "Martinez L."` (or by id) — his band, expected
price, rank weight, walk and buy values, the completion around him, the
pressure (each rival's ceiling and why), the adjustments applied to him.

### `adjust`

Resolve the player the listone's way (`"Martinez L."`, with the initial the
listone uses) or by `--player-id`; an entry that resolves to nobody is
refused, never appended. The command prints his band before and after, and
the class's top players before and after: `exclude` raises the class, `value`
moves him alone, `target` moves the composition (and says when the optimiser
departed from it).

### `replay`

`fantaclaude asta replay captured/<session>.jsonl --me Claude --map host=Marco`
— one FantaAstaLive state node per line, through the whole pipeline: per
snapshot the events (a sale, an undo, a cost edit, the lot), my credits, the
lot's band; then the final board. `--write-state` writes `data/asta-state.json`
from the last snapshot, so `asta board` then reads it. This is the rehearsal
harness: run it before the night with the capture from the rehearsal session.

### `close`

`fantaclaude asta close --session FA-xxx-xxx` — copies the state file to
`records/asta/`; commit `records/`. The file is deleted only once
`verify-transfer` (2b) confirms the lega.

## Worked example

**Ask:** "Bastoni is on the block, the room says he's limping — what do I do?"

**Good answer:** runs `fantaclaude asta board --json`, reads the lot: Bastoni
(Dc, INT) band 38/45/52, expected 40, pressure est. 47 (Marco keen up to 46);
runs `asta adjust --type value --player Bastoni --factor 0.85 --reason
"limping, reported in the room"`, reads the new band 32/38/44; tells the user
"38 is the number now, 44 at most; Marco will likely go to 46 — let him".

**Bad answer:** computes a discount by hand; edits `data/asta-state.json`;
writes "Bastoni is worth 38" into the knowledge base; connects to anything.
```

- [ ] **Step 9: Record the decision in the spec**

In `docs/superpowers/specs/2026-08-22-fantaclaude-design.md`:

Under "Why it fits in the latency budget", after the paragraph ending "The latency test, not the prose, owns the budget.", add:

```markdown
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
```

Under "Carried into 2a from Phase 1's review", at the end of the `exact` bullet, add: " **Decided 2026-08-30: re-run exactly per state change; see "Why it fits in the latency budget".**"

- [ ] **Step 10: Final check and commits**

Run: `uv run poe test && uv run ruff check core && uv run poe docs-build`
Expected: both suites green; ruff silent; the site builds with `--strict`.

```bash
git add core/src/fantaclaude/paths.py core/src/fantaclaude/commands/asta.py core/src/fantaclaude/commands/doctor.py core/src/fantaclaude/cli/app.py core/tests/test_asta_cli.py core/tests/test_doctor.py core/README.md site/docs/cli.md records/README.md CLAUDE.md .claude/skills/fanta-asta/SKILL.md
git commit -m "feat(cli): fantaclaude asta -- board, explain, replay, adjust, close; the doctor's pinned-run, adjustments and state-file checks"
git add docs/superpowers/specs/2026-08-22-fantaclaude-design.md
git commit -m "docs(spec): record the one-pricing-mode decision and its measurement"
```

---

### Task 10: The continuous demand fold

**Files:**
- Modify: `core/src/fantaclaude/model/demand.py` (`FoldedDemand`, `satisfiable_demand(..., teams=...)`, `_fold_into` takes a fraction, `thin_classes` and `THIN_SUPPLY_RATIO` deleted), `core/src/fantaclaude/analysis/valuation.py` (the call, the warning, `config["demand_kept"]`), `core/src/fantaclaude/asta/pinned.py` (`_rederive_demand` takes the team count)
- Test: `core/tests/test_demand.py`, `core/tests/test_valuation.py`

**Interfaces:**
- Consumes: `model.demand.rank_weights`, `pin_class`, `player_classes`, `module_demand`; `RunContext.team_count`.
- Produces: `demand.FoldedDemand(by_module: dict[str, dict[str, float]], kept: dict[str, float], iterations: int)` with `.to_dict()`; `demand.satisfiable_demand(demand_by_module, supply, *, teams: int, max_rank, bench_weight, bench_decay=0.5, bench_slots=1) -> FoldedDemand`; `valuation_runs.config["demand_kept"]` (class → retained fraction) and a run warning per partially supplied class; `thin_classes` gone.

The retained fraction (decision 7): a class keeps `min(1, supply / need)` of its own demand, `supply` being the players who pin to it at the current weights and `need` the league-wide starting slots the modules draw from it (its per-module average demand × the team count); the rest moves onto the classes its players pin to, in the proportion the listone supplies them, or onto the module's other classes when nobody carries it at all. `kept` is monotone non-increasing across the fixed-point iteration, so it terminates as the all-or-nothing version did. On a listone with no pure `Dd`/`Ds` the fold is the old fold exactly (`kept` 0), so no committed price moves; with one pure `Dd` the class keeps 1 / 4.36 of its demand instead of all of it. This is the last modelling change of the phase and the first to drop if 2a runs late (spec, "Order within 2a"). The code below was not run before the plan was finished.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_demand.py`: change `FOLD = {"max_rank": 6, "bench_weight": 0.1}` to `FOLD = {"teams": 8, "max_rank": 6, "bench_weight": 0.1}`; drop `thin_classes` from the import list; in `test_demand_no_player_can_pin_to_is_folded_onto_the_classes_that_field_it`, `test_folding_conserves_demand_and_leaves_none_of_it_unsatisfiable`, `test_a_listone_that_can_pin_to_every_class_is_left_alone` and `test_a_class_no_player_carries_at_all_still_conserves_the_eleven`, read the module demand from `.by_module` — i.e. `folded = satisfiable_demand(raw, supply, **FOLD).by_module` and `assert satisfiable_demand(raw, supply, **FOLD).by_module == {code: dict(by_class) ...}`; delete `test_thin_classes_names_the_ones_whose_pricing_rests_on_a_handful` and `test_a_niche_class_with_enough_bodies_for_the_league_is_not_thin`; add:

```python
def test_the_fold_is_continuous_in_the_shortfall():
    """One listed pure Dd used to hand the class its whole half-slot back
    and move every price on the board. The class keeps the share of its
    demand its supply covers: n pure Dd against the 6/11 x 8 = 4.36 starting
    slots the league draws from Dd, never more than all of it, never less
    than nothing, and the eleven units of every module conserved."""
    raw = module_demand(load_modules())
    base = listone_shaped_supply()
    need = 6 / 11 * 8
    previous = 0.0
    for n in (0, 1, 2, 4, 5):
        folded = satisfiable_demand(raw, (*base, *([R({Role.Dd})] * n)), **FOLD)
        kept = folded.kept["Dd"]
        assert kept == pytest.approx(min(1.0, n / need)) and kept >= previous
        dd = sum(m.get("Dd", 0.0) for m in folded.by_module.values()) / len(raw)
        assert dd == pytest.approx(6 / 11 * kept)
        for code, by_class in folded.by_module.items():
            assert sum(by_class.values()) == pytest.approx(11.0), code
        assert folded.kept["Ds"] == 0.0 and folded.kept["E"] == 1.0 and folded.iterations >= 1
        previous = kept
    none = satisfiable_demand(raw, base, **FOLD)
    assert none.kept["Dd"] == 0.0 and all("Dd" not in m for m in none.by_module.values())
    assert none.to_dict()["kept"]["Dd"] == 0.0 and set(none.to_dict()) == {"by_module", "kept", "iterations"}
```

In `core/tests/test_valuation.py`, in `test_the_run_prices_only_demand_its_own_listone_can_supply` replace the last assertion (`assert not any("rests on that handful" ...)`) with:

```python
        # a listone that supplies every class in proportion says nothing, and records what it kept
        assert not any("supplies the class at" in w for w in result.warnings)
        assert result.config["demand_kept"]["Dd"] == 0.0 and result.config["demand_kept"]["E"] == 1.0
```

and replace `test_one_listed_player_of_a_class_is_the_edge_the_fold_stands_on` (its name, docstring and the assertions after `after, con = run(tmp_path)`) with:

```python
def test_one_listed_player_of_a_class_moves_the_board_by_his_share_of_the_demand(tmp_path, fixture_json, mcp_fixture_json):
    """The fold is continuous in the shortfall: a single listed pure `Dd`
    keeps 1 / (6/11 x 8) of the class's demand, not all of it, and the run
    says so in a warning instead of standing on a knife edge."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    before, con = run(tmp_path)
    con.close()
    con = connect(tmp_path / "data" / "fanta.duckdb")
    con.execute("INSERT INTO players (snapshot_id, player_id, name, team_name, team_short, classic_role, mantra_roles, "
                "mantra_role_codes, quot_current_mantra, age, transfer_flag, raw) "
                "VALUES (1, 99001, 'Terzino D.', 'Inter', 'INT', 'D', ['Dd'], [7], 10, 24, false, '{}'::JSON)")
    con.close()
    after, con = run(tmp_path)
    try:
        kept = 1 / (6 / 11 * 8)
        assert before.config["demand_kept"]["Dd"] == 0.0 and before.config["demand"]["Dd"] == 0.0
        assert after.config["demand_kept"]["Dd"] == pytest.approx(kept)
        assert after.config["demand"]["Dd"] == pytest.approx(6 / 11 * kept)
        assert after.config["demand"]["E"] < before.config["demand"]["E"]
        assert sum(after.config["demand"].values()) == pytest.approx(11.0)
        assert any(w.startswith("Dd: the listone supplies the class at 23%") for w in after.warnings)
        moved = [p.player_id for p in before.pool
                 if after.boards["balanced"].prices[p.player_id].band.p50
                 != before.boards["balanced"].prices[p.player_id].band.p50]
        assert moved, "one listed Dd still moves the board -- by a quarter of a slot, not half a slot per module"
    finally:
        con.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_demand.py core/tests/test_valuation.py -q`
Expected: FAIL — `ImportError` (the demand tests no longer import `thin_classes` but `satisfiable_demand` refuses `teams=`: `TypeError: satisfiable_demand() got an unexpected keyword argument 'teams'`), and `KeyError: 'demand_kept'` in the valuation tests.

- [ ] **Step 3: The continuous fold in `demand.py`**

In `core/src/fantaclaude/model/demand.py`: add `from dataclasses import dataclass` and `from typing import Any` to the imports; replace the module docstring's paragraph that begins "Demand has to be *satisfiable*, though" with:

```
Demand has to be *satisfiable*, though, and the pin is what decides that.
A class can draw slots in every module and still take no player: Dd and Ds
each draw half of every module's eleven, but every player who can play
there is also an E or a Dc, both of which outweigh a flank, so `pin_class`
never pins anyone to Dd or Ds. `satisfiable_demand` keeps, for each class,
the share of its demand its own supply covers -- the players who pin to it
against the starting slots the league draws from it, the per-module demand
times the team count -- and moves the rest onto the classes its players do
pin to, in the proportion this listone supplies them, conserved module by
module and read off the listone at run time rather than typed. A listone
with enough pure Dd folds nothing; one with a single pure Dd keeps a
quarter of the class's demand rather than all of it, which is what keeps
one listed player from moving every price on the board (Phase 1 folded
all or nothing and warned about the edge; the fraction replaces the
warning). The retained share only ever falls across the fixed-point
iteration, so it terminates.
```

Replace `_fold_into` with:

```python
def _fold_into(demand: dict[str, dict[str, float]], cls: str, pins: Mapping[str, int], fraction: float) -> None:
    """Move `fraction` of `cls`'s demand, module by module, onto the classes
    `pins` counts -- never back onto `cls` itself."""
    targets = {target: count for target, count in pins.items() if target != cls}
    total = sum(targets.values())
    for by_class in demand.values():
        have = by_class.get(cls, 0.0)
        moved = have * fraction
        if not moved:
            continue
        if have - moved > 1e-12:
            by_class[cls] = have - moved
        else:
            by_class.pop(cls, None)
        if total:
            for target, count in targets.items():
                by_class[target] = by_class.get(target, 0.0) + moved * count / total
            continue
        # Nobody else in the listone carries the role, so there is no
        # distribution to read and the slot cannot be filled by anyone. Its
        # worth goes to whatever else the module fields, in proportion to what
        # that already draws: the eleven units are what a module is worth and
        # they have to land somewhere.
        rest = sum(share for other, share in by_class.items() if other != cls)
        if rest <= 0:
            by_class[cls] = by_class.get(cls, 0.0) + moved
            continue
        for other, share in list(by_class.items()):
            if other != cls:
                by_class[other] = share + moved * share / rest
```

Replace `satisfiable_demand`, `THIN_SUPPLY_RATIO` and `thin_classes` (everything from `def satisfiable_demand` down to the line before `def pin_class`) with:

```python
@dataclass(frozen=True)
class FoldedDemand:
    by_module: dict[str, dict[str, float]]      # module code -> class -> the demand priced, after the fold
    kept: dict[str, float]                      # class -> the share of its own demand it retained (1.0: fully supplied)
    iterations: int

    def to_dict(self) -> dict[str, Any]:
        return {"by_module": {code: dict(by_class) for code, by_class in self.by_module.items()},
                "kept": dict(self.kept), "iterations": self.iterations}


def satisfiable_demand(demand_by_module: Mapping[str, Mapping[str, float]], supply: Iterable[frozenset[Role]], *,
                       teams: int, max_rank: int, bench_weight: float, bench_decay: float = 0.5,
                       bench_slots: int = 1) -> FoldedDemand:
    """Module demand with every class's unsupplied share folded onto the
    classes its players do pin to, in the proportion the listone supplies.

    `need` is the league-wide starting slots the modules draw from a class
    (its average demand per module times the team count); `supply` is the
    players who pin to it at the current weights. A class keeps
    min(1, supply / need) of its demand. The pins depend on the weights and
    the weights on the demand, so it is iterated to a fixed point; the kept
    share is taken as the running minimum, so it never rises and the loop
    ends. Demand is conserved module by module."""
    players = tuple(supply)
    raw = {code: dict(by_class) for code, by_class in demand_by_module.items()}
    modules = len(raw) or 1
    need = {cls: sum(by_class.get(cls, 0.0) for by_class in raw.values()) / modules * teams for cls in ROLE_CLASSES}
    kept = dict.fromkeys(ROLE_CLASSES, 1.0)
    demand = raw
    iterations = 0
    for _ in range(len(ROLE_CLASSES) * 4):
        iterations += 1
        weights = rank_weights(demand, max_rank=max_rank, bench_weight=bench_weight, bench_decay=bench_decay,
                               bench_slots=bench_slots)
        pinned: dict[str, int] = {}
        pins_of: dict[str, dict[str, int]] = {}
        for roles in players:
            cls = pin_class(roles, weights)
            pinned[cls] = pinned.get(cls, 0) + 1
            for carried in player_classes(roles):
                counts = pins_of.setdefault(carried, {})
                counts[cls] = counts.get(cls, 0) + 1
        proposed = {cls: min(kept[cls], min(1.0, pinned.get(cls, 0) / need[cls]) if need[cls] > 0 else 1.0)
                    for cls in ROLE_CLASSES}
        if all(abs(proposed[cls] - kept[cls]) < 1e-12 for cls in ROLE_CLASSES):
            break
        kept = proposed
        demand = {code: dict(by_class) for code, by_class in raw.items()}
        for cls in ROLE_CLASSES:
            if kept[cls] < 1.0:
                _fold_into(demand, cls, pins_of.get(cls, {}), 1.0 - kept[cls])
    return FoldedDemand(demand, kept, iterations)
```

- [ ] **Step 4: The run records what it kept and warns per partially supplied class**

In `core/src/fantaclaude/analysis/valuation.py`: drop `thin_classes` from the `model.demand` import; replace the `demand = satisfiable_demand(...)` call and the sorted-order line with:

```python
    folded = satisfiable_demand(module_demand(), listone_role_sets(con), teams=ctx.team_count, max_rank=max_rank,
                                bench_weight=pricing_cfg.bench_weight, bench_decay=pricing_cfg.bench_decay,
                                bench_slots=pricing_cfg.bench_slots_per_class)
    # In module-code order, which is the order canonical_json stores it in: the
    # rank weights are floating-point sums over the modules, so the live board
    # (asta/pinned.py reads config["demand_by_module"] back) must add them in
    # the same order to reproduce this run's board to the last bit.
    demand = {code: folded.by_module[code] for code in sorted(folded.by_module)}
```

replace the `thin_classes` loop (the comment block "satisfiable_demand asks only whether a class has any player…" and the `for cls, pinned, slots in thin_classes(...)` loop) with:

```python
    # A class the listone supplies at less than the league's starting slots keeps
    # only that share of its demand; the rest is priced through the classes its
    # players price as. Said once per run, so a partially supplied class is never
    # a surprise on the board.
    for cls, fraction in sorted(folded.kept.items()):
        if 0.0 < fraction < 1.0:
            warnings.append(f"{cls}: the listone supplies the class at {fraction:.0%} of the starting slots the league draws "
                            f"from it; the other {1 - fraction:.0%} of its demand is priced through the classes its players "
                            f"price as")
```

and in the `config = {...}` literal, after `"demand_by_module": demand,` add `"demand_kept": folded.kept,`.

In `core/src/fantaclaude/asta/pinned.py`: change `_rederive_demand(players, cfg)` to `_rederive_demand(players, cfg, teams)` returning `satisfiable_demand(module_demand(), supply, teams=teams, max_rank=..., ...).by_module`, and in `load_pinned_run` move the `league = league_bounds(...)` block above the `demand = config.get("demand_by_module")` line and call `_rederive_demand(players, pricing_cfg, league.team_count)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run pytest core/tests/test_demand.py core/tests/test_valuation.py core/tests/test_pinned.py core/tests/test_advisor.py -q`
Expected: PASS; `test_the_live_board_at_minute_zero_reproduces_the_pinned_board` still green. `uv run pytest core/tests -q` → about 412 passed (two thin-class tests gone, one fold test added). If `test_one_listed_player_of_a_class_moves_the_board_by_his_share_of_the_demand` finds the 23% warning worded differently, align the test to the code's wording; if it finds `kept` differing from `1 / 4.36`, the iteration re-pinned a multi-role player under the folded weights — check `pins_of` excludes the class itself and that `need` is computed from the raw demand.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/model/demand.py core/src/fantaclaude/analysis/valuation.py core/src/fantaclaude/asta/pinned.py core/tests/test_demand.py core/tests/test_valuation.py
git commit -m "feat(demand): fold a class's demand in proportion to its shortfall, replacing the thin-class warning"
```

---

### Task 11: The cleanup carried from Phase 1's review

**Files:**
- Create: `core/src/fantaclaude/yamlio.py`, `core/tests/test_yamlio.py`
- Modify: `core/src/fantaclaude/analysis/valuation.py` (`_digest`, `_finite`), `core/src/fantaclaude/league/settings.py` (`digest`), `core/src/fantaclaude/commands/rank.py` (`_load_preferences`), `core/src/fantaclaude/commands/doctor.py` (`_preferences_check`), `core/src/fantaclaude/asta/pricing_config.py`, `core/src/fantaclaude/league/league_yml.py`, `core/src/fantaclaude/model/d_factor.py`, `core/src/fantaclaude/kb/audit.py`, `core/src/fantaclaude/kb/profiles.py`, `core/src/fantaclaude/kb/notes.py`, `core/src/fantaclaude/kb/participants.py`, `core/src/fantaclaude/analysis/history.py`, `core/src/fantaclaude/analysis/exports.py`, `core/src/fantaclaude/cli/app.py` (`_render_rank`)
- Test: `core/tests/test_yamlio.py`, `core/tests/test_league_settings.py`, `core/tests/test_kb_audit.py`, `core/tests/test_history.py`, `core/tests/test_valuation.py`

**Interfaces:**
- Produces: `league.settings.digest(view) -> str` (sixteen hex characters of the sha256 of `canonical_json(view)` — the one formula behind `rules_hash`, `model_hash` and `inputs_hash`); `yamlio.YamlFileError`, `yamlio.read_yaml_mapping(path) -> dict[str, Any]`; `kb.audit.read_front_matter(path) -> FrontMatter`; `kb.profiles.PROFILE_GLOB`, `kb.notes.NOTE_GLOB`, `kb.participants.PARTICIPANT_GLOB`; `analysis.history.EVENT_COLUMNS` derived from `Events`; `analysis.exports.header_lines(run_id, rules_hash, model_hash, inputs_hash, summary, warnings) -> list[str]`, `analysis.exports.render_exports(run, exports_dir) -> tuple[Path, Path, Path]`; `valuation._finite` and `pricing._json` gone (`values.json_safe` since Task 1); the doctor's single connection is Task 9's. None of it is load-bearing (spec): every step below must leave every existing test green, and the two hashes must not move — `test_the_run_is_deterministic_and_the_hashes_track_their_inputs` and the settings tests are the guard.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_yamlio.py`:

```python
import pytest
from fantaclaude.yamlio import YamlFileError, read_yaml_mapping


def test_read_yaml_mapping_reads_a_mapping_and_names_every_way_a_file_can_be_wrong(tmp_path):
    path = tmp_path / "x.yml"
    path.write_text("a: 1\nb: [1, 2]\n", encoding="utf-8")
    assert read_yaml_mapping(path) == {"a": 1, "b": [1, 2]}
    path.write_text("", encoding="utf-8")
    assert read_yaml_mapping(path) == {}
    for text, match in (("- a list\n", "top level must be a mapping"), ("a: [\n", "x.yml")):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(YamlFileError, match=match):
            read_yaml_mapping(path)
    with pytest.raises(YamlFileError, match="missing"):
        read_yaml_mapping(tmp_path / "missing.yml")
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(YamlFileError, match="x.yml"):
        read_yaml_mapping(path)
```

Append to `core/tests/test_league_settings.py`:

```python


def test_digest_is_the_one_formula_behind_every_hash():
    import hashlib

    from fantaclaude.league.settings import canonical_json, digest

    view = {"b": 1, "a": [1, 2]}
    assert digest(view) == hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()[:16]
    assert len(digest(view)) == 16 and digest(view) == digest({"a": [1, 2], "b": 1})
```

Append to `core/tests/test_kb_audit.py`:

```python


def test_the_validator_is_chosen_by_the_loaders_own_glob():
    from pathlib import PurePosixPath

    from fantaclaude.kb.audit import _validator_for
    from fantaclaude.kb.notes import load_note
    from fantaclaude.kb.participants import load_participant
    from fantaclaude.kb.profiles import load_profile

    assert _validator_for(PurePosixPath("serie-a/teams/inter/profile.md")) is load_profile
    assert _validator_for(PurePosixPath("serie-a/teams/inter/players/thuram.md")) is load_note
    assert _validator_for(PurePosixPath("league/participants/marco.md")) is load_participant
    assert _validator_for(PurePosixPath("league/participants/deep/marco.md")) is None
    assert _validator_for(PurePosixPath("serie-a/teams/inter/deeper/profile.md")) is None
    assert _validator_for(PurePosixPath("rules/mantra.md")) is None
```

Append to `core/tests/test_history.py`:

```python


def test_event_columns_are_the_events_fields():
    from dataclasses import fields

    from fantaclaude.analysis.history import EVENT_COLUMNS
    from fantaclaude.model.scoring import Events

    assert EVENT_COLUMNS == tuple(f.name for f in fields(Events))
```

In `core/tests/test_valuation.py`, `test_exports_render_the_run_and_records_keep_it`, replace the two lines `md, csv = write_rankings(result, exports)` / `plan = write_asta_plan(result, exports)` with `md, csv, plan = render_exports(result, exports)` and import `render_exports` beside `export_records`; after `assert result.run_id in text ...` add `assert "17 players" in text` (the header now carries the player count, as the CLI's status line does).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_yamlio.py core/tests/test_league_settings.py core/tests/test_kb_audit.py core/tests/test_history.py core/tests/test_valuation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.yamlio'`, `ImportError: cannot import name 'digest'`, `cannot import name 'render_exports'`, `_validator_for() takes a Path` (the old signature matched on parent names and returns the wrong loader for the deep paths), and `EVENT_COLUMNS` in its old hand-typed order.

- [ ] **Step 3: One digest**

In `core/src/fantaclaude/league/settings.py`, after `canonical_json`, add:

```python
def digest(view: Any) -> str:
    """Sixteen hex characters of the sha256 of the canonical JSON of `view`:
    the one formula behind rules_hash, model_hash and inputs_hash."""
    return hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()[:16]
```

and make `rules_hash` end with `return digest(_rules_view(rosters, lineup, calculate, team_count))`. In `core/src/fantaclaude/analysis/valuation.py`, delete `_digest` (and the now-unused `hashlib` import), import `digest` beside `canonical_json` from `fantaclaude.league.settings`, and replace the two `_digest(` calls (in `model_hash` and `inputs_hash`) with `digest(`.

- [ ] **Step 4: One JSON scrubber**

In `core/src/fantaclaude/analysis/valuation.py`, delete `_finite` (and the `math` import if nothing else uses it), add `from fantaclaude.values import is_number, json_safe`, and replace the four `_finite(` calls in `record_run` with `json_safe(`.

- [ ] **Step 5: One YAML mapping reader**

Create `core/src/fantaclaude/yamlio.py`:

```python
"""One reader for every YAML file that must be a mapping.

preferences.yml, pricing.yml, league.yml and d_factor.yml were each read by
their own copy of `safe_load(...) or {}` with their own subset of the
errors caught -- rank's copy caught only yaml.YAMLError, so a file that
was not UTF-8 was a traceback there and a clean not-ready everywhere else.
Every caller wraps YamlFileError in its own error class, so the exit codes
and the messages the skills key on do not change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class YamlFileError(ValueError):
    """The file is missing, unreadable, not YAML, or not a mapping; the message names the path."""


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise YamlFileError(f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise YamlFileError(f"{path}: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise YamlFileError(f"{path}: the top level must be a mapping")
    return data
```

Then, at each of the four readers, replace the file-reading prologue with the helper, wrapping its error in the caller's own class so nothing downstream changes:

- `core/src/fantaclaude/commands/rank.py`: delete `_load_preferences` (and the `yaml` import); in `check_ready` replace `preferences = _load_preferences(preferences_path)` with
  ```python
      try:
          preferences = read_yaml_mapping(preferences_path)
      except YamlFileError as exc:
          raise NotReady(str(exc)) from None
  ```
  importing `from fantaclaude.yamlio import YamlFileError, read_yaml_mapping`.
- `core/src/fantaclaude/commands/doctor.py`, `_preferences_check`: replace everything from `if not path.is_file():` through `if data is not None and not isinstance(data, dict): ... return Check(...)` with
  ```python
      try:
          data = read_yaml_mapping(path)
      except YamlFileError as exc:
          return Check("preferences", False, str(exc))
  ```
  and `load_preferences(data)` below it (the `or {}` is the helper's).
- `core/src/fantaclaude/asta/pricing_config.py`: replace the `try: data = yaml.safe_load(...)` block and the `if not isinstance(data, dict)` check with
  ```python
      try:
          data = read_yaml_mapping(path)
      except YamlFileError as exc:
          raise PricingConfigError(str(exc)) from None
  ```
  (the `yaml` import goes; `test_pricing_yml_is_loaded_and_validated` still expects `PricingConfigError` for `- a list`).
- `core/src/fantaclaude/league/league_yml.py`, `load_league_yml`: replace `data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}` and the top-level check with
  ```python
      try:
          data = read_yaml_mapping(path)
      except YamlFileError as exc:
          raise LeagueYmlError(str(exc)) from None
  ```
- `core/src/fantaclaude/model/d_factor.py`, `load_d_factor`: replace its read of the file — the `safe_load` of `path.read_text(...)`, the `except` that turns a YAML syntax error into `DFactorTableError`, and the top-level-mapping check — with `read_yaml_mapping(path)` inside a `try/except YamlFileError as exc: raise DFactorTableError(str(exc)) from None`; keep every later validation (the bands, `verified_on`, `source`) as it is. `test_d_factor.py` and `test_rank_exits_not_ready_when_the_hand_written_d_factor_table_does_not_parse` are the guard.

- [ ] **Step 6: One front-matter prologue, and the audit chooses the validator by the loader's glob**

In `core/src/fantaclaude/kb/audit.py`, after `parse_front_matter`, add:

```python
def read_front_matter(path: Path) -> FrontMatter:
    """The document's front-matter, or a FrontMatterError naming the file --
    for a missing block as for a malformed one. The one prologue every
    structured loader (profiles, notes, participants) used to carry."""
    try:
        front_matter = parse_front_matter(path.read_text(encoding="utf-8"))
    except (FrontMatterError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise FrontMatterError(f"{path}: {exc}") from None
    if front_matter is None:
        raise FrontMatterError(f"{path}: no front-matter block")
    return front_matter
```

replace `_validator_for` with:

```python
def _validator_for(rel: PurePosixPath):
    """The structured loader a document must satisfy beyond the four keys,
    chosen by the same glob the loader reads the tree with -- so the audit
    and `rank` accept exactly the same files. Imported lazily: those
    modules import this one."""
    from fantaclaude.kb.notes import NOTE_GLOB, load_note
    from fantaclaude.kb.participants import PARTICIPANT_GLOB, load_participant
    from fantaclaude.kb.profiles import PROFILE_GLOB, load_profile

    for glob, loader in ((PROFILE_GLOB, load_profile), (NOTE_GLOB, load_note), (PARTICIPANT_GLOB, load_participant)):
        if rel.full_match(glob):
            return loader
    return None
```

(add `PurePosixPath` to the `pathlib` import) and in `audit()` call it as `_validator_for(PurePosixPath(rel))`.

In `core/src/fantaclaude/kb/profiles.py` add `PROFILE_GLOB = "serie-a/teams/*/profile.md"` beside `PROFILE_KEYS`, make `load_profiles` glob with it, and replace `load_profile`'s prologue (the `try: front_matter = parse_front_matter(...)` block and the `if front_matter is None` check) with

```python
    try:
        front_matter = read_front_matter(path)
    except FrontMatterError as exc:
        raise ProfileError(str(exc)) from None
```

importing `read_front_matter` from `fantaclaude.kb.audit` (and dropping the now-unused `yaml` and `parse_front_matter` imports). Do the same in `core/src/fantaclaude/kb/notes.py` (`NOTE_GLOB = "serie-a/teams/*/players/*.md"`, `NoteError`) and `core/src/fantaclaude/kb/participants.py` (`PARTICIPANT_GLOB = "league/participants/*.md"`, `ParticipantError`).

- [ ] **Step 7: The event columns come from `Events`**

In `core/src/fantaclaude/analysis/history.py` replace the `EVENT_COLUMNS = (...)` tuple with `EVENT_COLUMNS = tuple(f.name for f in fields(Events))` (importing `fields` from `dataclasses`): the SELECT lists the columns by name and the rows are zipped back into `Events(**...)` by the same names, so the order is `Events`' and a field added to `Events` without a column becomes a `duckdb.Error` at the query, at import of the test suite, rather than a `TypeError` at rank time.

- [ ] **Step 8: The exports build their rows once and share the header with the CLI**

In `core/src/fantaclaude/analysis/exports.py`: replace `_header` with

```python
def header_lines(run_id: str, rules_hash: str, model_hash: str, inputs_hash: str, summary: dict, warnings: list[str]) -> list[str]:
    """The status lines of a run, for rankings.md, the asta plan and the CLI alike -- one copy, so they cannot print different facts."""
    return [f"run `{run_id}` · rules {rules_hash} · model {model_hash} · inputs {inputs_hash}",
            f"{summary['players']} players · {summary['team_count']} teams × {summary['budget']} credits = "
            f"{summary['market_credits']} on the market · giornata {summary['giornate_played']} played, "
            f"{summary['giornate_remaining']} remaining · voti sheet {summary['sheet']}"
            + (" · D-Factor active" if summary.get("d_factor_active") else ""),
            *(f"warning: {w}" for w in warnings)]


def _header(run: ValuationRun) -> list[str]:
    return header_lines(run.run_id, run.rules_hash, run.model_hash, run.inputs_hash, run.summary, run.warnings)
```

give `write_rankings` and `write_asta_plan` a keyword parameter `tables: dict[str, list[dict]] | None = None` and make each read `rows = (tables or {}).get(name) or _rows(run, name)` wherever it called `_rows(run, name)` (the plan's "Cheap value" and "We disagree" sections reuse the first scenario's rows rather than calling `_rows` again), and add

```python
def render_exports(run: ValuationRun, exports_dir: Path) -> tuple[Path, Path, Path]:
    """rankings.md, rankings.csv and asta-plan.md, from one set of rows per scenario."""
    tables = {s.name: _rows(run, s.name) for s in run.scenarios}
    md, csv_path = write_rankings(run, exports_dir, tables=tables)
    return md, csv_path, write_asta_plan(run, exports_dir, tables=tables)
```

In `core/src/fantaclaude/commands/rank.py` replace the two calls `md, csv = write_rankings(run, exports_dir)` / `plan = write_asta_plan(run, exports_dir)` with `md, csv, plan = render_exports(run, exports_dir)` (importing `render_exports` instead of the two writers). In `core/src/fantaclaude/cli/app.py`, `_render_rank`, replace the two hand-kept header lines (the `run … · rules … · model … · inputs …` tuple and the `players · teams × credits · giornata … · voti sheet …` tuple) with `*header_lines(payload["run_id"], payload["rules_hash"], payload["model_hash"], payload["inputs_hash"], s, payload["warnings"])` (importing `header_lines` from `fantaclaude.analysis.exports` inside the function), and delete the later `for w in payload["warnings"]: lines.append(f"warning: {w}")` loop, which the header now prints.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: both suites green, about 416 core tests; every pre-existing test unchanged in outcome, in particular `test_the_run_is_deterministic_and_the_hashes_track_their_inputs` (the hashes did not move), `test_pricing_yml_is_loaded_and_validated`, `test_rank_refuses_when_not_ready`, `test_exit_codes_split_on_the_defect_not_on_the_exception_class` (the exit codes did not move) and `test_rank_exits_not_ready_when_the_hand_written_d_factor_table_does_not_parse`.

- [ ] **Step 10: Commit**

```bash
git add core/src/fantaclaude/yamlio.py core/src/fantaclaude/league/settings.py core/src/fantaclaude/analysis/valuation.py core/src/fantaclaude/commands/rank.py core/src/fantaclaude/commands/doctor.py core/src/fantaclaude/asta/pricing_config.py core/src/fantaclaude/league/league_yml.py core/src/fantaclaude/model/d_factor.py core/src/fantaclaude/kb/audit.py core/src/fantaclaude/kb/profiles.py core/src/fantaclaude/kb/notes.py core/src/fantaclaude/kb/participants.py core/src/fantaclaude/analysis/history.py core/src/fantaclaude/analysis/exports.py core/src/fantaclaude/cli/app.py core/tests/test_yamlio.py core/tests/test_league_settings.py core/tests/test_kb_audit.py core/tests/test_history.py core/tests/test_valuation.py
git commit -m "refactor: one digest, one JSON scrubber, one YAML reader, one front-matter prologue, event columns from Events, exports rendered once"
```

---

## Self-Review

**Spec coverage, the 2a row and the sections it draws on:**

| spec requirement | task |
| --- | --- |
| 2a row: "state machine, advisor, adjustment layer, state snapshot, CLI entry" | 4 (state machine), 6 (advisor, `mutate()`), 5 (adjustments), 7 (snapshot), 9 (CLI) |
| "the `exact`/focused decision first" — re-run exactly per state change or ship a board that jumps and say by how much | 1 (decided: exact, measured, the approximate mode removed; recorded in the spec in 9) |
| "the `sync-league` helper" — `rank_cmd` re-implements the fetch/conflict/apply flow and drops the `SyncReport` | 2 |
| "per-class roster bounds" — `class_min` / `class_max` in `PoolState` before live state is expressed through it | 3 |
| "the continuous demand fold" — replace the `thin_classes` warning, fold in proportion to the shortfall | 10 |
| "the cleanup" — `_digest`, `doctor._read_only` and the six opens, `rank._load_preferences`, the front-matter prologue and `_validator_for`, `EVENT_COLUMNS`, `_finite`/`_json` and `explain()`, `exports._rows`/`_header`/`_render_rank` | 11 (the doctor half in 9, `_json` in 1) |
| Dynamic max price: VOR recomputed against the live remaining pool; scarcity falls out of `V`; the band; every state change re-prices the whole board | 6 (`build_pool_state`, `derive`), 1 (one mode) |
| One pricing function: the live pricer called with the full pool and pre-auction prices reproduces the pre-auction board exactly | 6 (`test_the_live_board_at_minute_zero_reproduces_the_pinned_board`, band for band and `to_dict` for `to_dict`) |
| `asta serve --run` pins a valuation; without it the newest run not superseded, named on the status line | 6 (`newest_run_id`, `PinnedRun.describe`), 9 (`--run`, the `run` line of every report) |
| Live adjustments: `value` / `exclude` / `target` with their three mechanics; every one carries a reason; hot-reloaded; three surfaces write one file through one writer; `exclude` raises everyone else's price through `V`; `target` is soft and a departure is reported | 5 (the file, the append, the layer), 6 (`Refresh`, `test_adjustments_reach_the_board_through_v`, `targets_departed`), 9 (`asta adjust`) |
| The mirror is faithful; set-diff, never append-only; the same snapshot twice is a no-op; credits from `picks[]`, never `currentBudget`; an unknown `playerId` is a fault to surface; nicks scrubbed at ingestion | 4 (`apply_snapshot`, `scrub_label`, `test_a_sale_an_edit_an_undo…`), 6 (`build_ledgers` problems) |
| Session settings authoritative for the night, a mismatch surfaced at connect, a later change diffed and announced | 4 (`compare`, `SettingsChanged`), 6 (`league_conflicts`), Auction (`test_a_settings_change_mid_auction…`) |
| Dossiers loaded, not read live; opponent pressure from dossiers plus observed spending; displayed separately from the max price | 8 |
| `asta-state.json`: a plain state dump, atomically replaced, names resolved, copied to `records/` at close, reloaded with no feed reproduces the board | 7, 9 (`asta close`, `asta board` reading the file) |
| `mutate()` as the one path every change goes through, recomputing derived state and notifying | 6 (`Auction`) |
| Replay is the rehearsal harness | 4 (`read_snapshots`, the fixture), 9 (`asta replay`) |
| `doctor` checks "is the pinned run loadable", "does `adjustments.yml` parse" (extensions were already checked) | 9 |
| Testing — Dynamic max price (scarcity monotone, exhaustion, latency), One pricing function, Auction state machine (credits never negative in the ledgers, undo restores, any sequence converges), The live feed's diff engine (a sale, an undo, a cost edit, a duplicate, an unknown `playerId`, the same snapshot twice), Adjustments hot-reloaded and `exclude`'s directional invariant, Crash recovery's state-file half | 1, 6, 4, 4, 6, 7 |
| Exit codes and `--json` on every read command; commands importable | 9 (`commands/asta.py`, `_asta_errors`) |
| The skill carries one worked example | 9 (`fanta-asta`) |

**Deliberately not in this plan** (each named in the spec as 2b or later, or as blocked): the FantaAstaLive adapter (`ingest/asta_live.py`: SSE, anonymous sign-in, token refresh, reconnect with backoff, the one subscriber), `asta serve`, the FastAPI/WebSocket server and the Vite dashboard, the served `fantaclaude-mcp`, the mapping screen (2a's `--me`/`--map` and the state file stand in for it), `asta refresh` as a server proxy (2a's `Refresh` is the in-process half), `verify-transfer` and the deletion of the state files (open question 9), the A RILANCI bid ladder (open question 10), `market_prices` and `calibration`, the auction journal entry (`fanta-market plan` writes it), `league.yml` house-rule keys for per-class bounds (`RunContext.class_min` is where one would land; none exists), and the outfield group bound `[21, 34]` inside the pricer (the ledger counts it, the pricer binds it through the roster bounds, and the difference sits above the 36-player roster the DP never fills — recorded in "Source facts").

**Assumptions stated where the plan had to choose** (each is one function or one constant, and each is named in a docstring): the `settings.roles` pairs read as `[classic, mantra]` by `settings.game` (`session._pair`); the outfield bucket is `mov` and the roster is `size`; a team's label is `connection.label`, then `nick`, then `name`, then the id; a pick listed twice in one node is resolved by index and flagged; a class floor extends the rank weights at bench weight (`rank_weights(min_ranks=)`); the live board follows one scenario, its first by default; the opponent model's factors (1.25 keen, 0.75 reluctant, one credit reserved per other open slot, the room's overpay as an aggregate ratio) and that keen and reluctant cancel; the estimate is one credit past the keenest rival's ceiling; the fold retains `min(1, supply / need)` with `need` from the raw demand and the running minimum across the iteration; the state file's `records/` name is `<session>-<UTC stamp>.json`; the latency budget is 500 ms.

**Placeholder scan:** no `TBD`, `TODO`, "implement later", "add validation", "handle edge cases", "similar to Task N"; every code step carries its code; the two steps that patch files the plan does not print whole (Task 11's `load_d_factor`, `_render_rank`) name the exact lines to replace and the exact replacement.

**Type consistency, checked across tasks:** `price_board(state, cfg)` (1) is what `valuation.run_valuation` (1, 3, 6, 10) and `advisor.derive` (6) call; `PoolState.class_min`/`class_max` (3) are what `build_pool_state` (6) fills; `SessionSettings.goalkeepers/outfield/size` as `(low, high)` (4) are what `Ledger.missing/room/open_slots` (6), `build_pool_state` (6), `compare` (4) and `pressure_for` (8) read; `Snapshot.settings`/`teams` (4) are what `Auction.mutate` (6) passes to `session_from_feed(settings, team_count=)` (4) and what `read_state` (7) reloads through `parse_snapshot` (4); `AuctionState.picks_of/spent/team_ids/to_snapshot` (4) are what `build_ledgers` (6) and `render_state` (7) use; `AdjustmentLayer.value_factor/excluded/targets/problems/sha256/factor()` (5) are what `build_pool_state`, `derive` (6) and `render_state` (7) read; `PinnedRun.players/pricing_cfg/scenarios/demand/hard_minimums/league/prices/club_names/candidates()/weights(targets, min_ranks)/scenario()/describe()` (6) are what `advisor` (6), `pressure` (8), `commands/asta` and `doctor` (9) use; `rank_weights(..., min_ranks=)` (6) is what `PinnedRun.weights` (6) and `run_valuation` (6) call; `Board.players/club_names/pressure/ledgers/mine/lot/layer/problems/league_conflicts/tiers()/to_dict()` (6, 8) are what `pressure_board` (8), `render_state` (7) and the reports (9) read; `Refresh(layer=, participants=)` and `Auction(run, mapping, *, settings, layer, scenario, participants)` (6, 8) are what `replay_report` (9) drives; `FoldedDemand.by_module/kept` (10) is what `run_valuation` and `_rederive_demand` (10) read; `header_lines(...)` (11) takes the same six values from `ValuationRun` and from the rank payload. The test helpers reused across files — `test_valuation.seeded/run/PREFS`, `test_rank_cli._workspace`, `test_advisor.pinned_run/replayed/node/SESSION`, `test_doctor._ready_workspace/_paths` — keep the signatures the tasks call them with.

**What was measured and what was not:** the core counts after Tasks 1–8 (368 → 368 → 369 → 382 → 389 → 399 → 402 → 406) were measured; Tasks 9–11 state estimates; the pricing timings in decision 1 and the byte-identity of the one-mode board against the old exact board were measured on 2026-08-30.
