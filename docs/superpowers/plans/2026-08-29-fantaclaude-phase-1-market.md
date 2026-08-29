# fantaclaude Phase 1 — market — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the spine into a pre-auction board — project every listone player from his own history under *this* league's scoring, price him against the best completion of a roster whose composition the optimiser chooses, and write one stamped, reproducible `valuations` run rendered to `rankings.md`/`.csv` and a three-scenario asta plan — plus the contracts the auction and the weekly loop will read: player notes, opponent dossiers (`fanta-kb interview`), the D-Factor, and a `records/` export that survives a lost disk.

**Architecture:** Three pure layers under one command. `model/scoring.py` recomputes the fantavoto from base voto and event counts under the `league_settings` snapshot in force (the pair-valued `bnMls` keys, the voto source, the modifier flags — nothing hardcoded); `analysis/history.py` reads the observed layer into per-player, per-season lines; `analysis/projection.py` turns lines plus the knowledge base's numbers (`rotation_factor`, a note's `depth`/`availability`, the club's penalty taker) into a value distribution — p25/p50/p75 of the remaining season's fantapunti — with the listone quotazione kept out of the value path by construction. `asta/pricing.py` is the one pricing function the spec demands: a frozen `PoolState` in, a `BoardPricing` out, numpy inside, no I/O — per-class knapsack curves weighted by the demand each Mantra role class draws from the eleven modules (`model/demand.py`, derived from `modules.yml`, never typed), max-plus convolution into the completion value `V`, and a binary search for the indifference price at three quantiles, exact for the player on the block and for every player of a pre-auction run. `analysis/valuation.py` assembles a run — VOR against the best one-credit player, tiers by the largest gaps, the divergence check against the quotazione — stamps it with `rules_hash`, `model_hash` and `inputs_hash`, and `commands/rank.py` writes it, renders the exports, and copies the durable rows to `records/` as parquet. The schema moves to version 3 with a rebuilt `advanced_snapshots` whose dedupe key finally covers every input of the match (raw bytes, aliases file, listone snapshot), so a changed alias re-matches on its own.

**Tech Stack:** Python 3.14.7, uv 0.12.5 (workspace), duckdb 1.5.5, typer 0.27.1, pyyaml 6.0.3, httpx 0.28.1, pydantic 2.13.4, openpyxl 3.1.5, **numpy 2.5.2 (new; cp314 wheel resolved 2026-08-29 with `uv pip install --dry-run "numpy>=2.3"`)**, poethepoet 0.48.0, pytest 9.1.1, pytest-asyncio 1.4.0, respx 0.23.1, ruff 0.16.4.

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` — sections "League configuration is data, not constants", "The Mantra role model", "Schema" (Derived layer, the two hashes, "Fantavoto is computed, never stored"), "Knowledge base" (player notes, participants, `fanta-kb interview`), "`fanta-market` — pre-auction analysis" (the five stages, the permanent record), "Projecting a player", "European competition and rotation", "Dynamic max price", "One pricing function", "The band", "Why it fits in the latency budget", "The algorithm, concretely", "The pricing module", "Live adjustments" (`target` semantics), "Requirements specific to a single-shot live event" (5: `records/`), "Testing" (Projection, Valuation, Scoring is league-configurable, Dynamic max price, One pricing function, CLI, Skills), "Phasing" row 1, open questions 1, 3 and 7. The Phase 0a and 0b plans (`docs/superpowers/plans/2026-08-24-fantaclaude-phase-0a-spine.md`, `2026-08-28-fantaclaude-phase-0b-history.md`) define every interface this plan consumes; the code on `main` at `f234136` is the truth where the two differ.

**Decisions taken with the user on 2026-08-29, before this plan was written:**

1. **Roster composition is proposed by the optimiser.** `preferences.yml` keeps only `target_composition: {Por: 2}`; the allocator chooses how many of each role class to carry within the league's bounds, and `fantaclaude rank` prints the composition it chose. A target in `preferences.yml` is a soft prior (raised demand weights), never a bound.
2. **`fanta-kb interview` ships as a contract, the interviews run later.** This plan adds the dossier front-matter, `load_participants`, the `kb audit`/`doctor` checks, the `league.yml` mirror and the skill's `interview` mode; no dossier is written in this phase.
3. **The D-Factor is modelled now.** The Mantra defence modifier (fantacalcio.it calls it *D-Factor*: the best five voti among Dc/B/Dd/Ds/E/M with at least three true defenders, optionally the goalkeeper as a sixth, averaged and mapped to points) is implemented as a table-driven pure function and enters the projection as a per-player uplift when the settings say it is active. Its thresholds are **league data**: the regolamento pages (`/regolamenti/sistema-mantra`, `/regolamenti/leghe-private`, `/regolamenti/fantacalcio`, read 2026-08-29) describe the mechanism and say the platform "proposes the most common version, with customisable bonus/malus output" — no page publishes the table. So `model/d_factor.yml` ships with an **empty** `bands` list and `verified_on: null`; `rank` refuses (exit 3) if the modifier is active while the table is empty; Task 10 tells the account holder where to read the league's own table and how to transcribe it. Any *other* modifier key turning non-null makes `rank` refuse, naming the key.
4. **The `advanced_snapshots` dedupe key is fixed in this phase**, riding the schema bump Phase 1 makes anyway.

## Global Constraints

- **Python is 3.14.7**, uv ≥ 0.12.5, workspace root `/Users/grimid3v/Workspace/fantaclaudio`; `fantaclaude.paths` derives every path from the MCP's `workspace_root()` (honours `FANTACALCIO_HOME`). Tests set `FANTACALCIO_HOME` to a `tmp_path` whenever a CLI command touches the filesystem.
- **No test performs network I/O.** `rank` re-syncs the league through `fantaclaude.api_client.run_with_api` unless `--offline`; tests pass `--offline` or monkeypatch `fantaclaude.api_client.run_with_api`. The live league API is called exactly where this plan says (Task 10: one `fantaclaude rank` without `--offline`) and nowhere else; nothing here adds a login of any kind.
- **The quotazione is a price, never a value.** No code under `analysis/projection.py` reads `quot_*`; the quotazione enters only `asta/pricing.py` as the expected price of pool players and `analysis/valuation.py` as the divergence check. Task 6's `test_quotazione_is_not_in_the_value_path` perturbs every quotazione and asserts every projected value is unchanged; it must stay green in every later task.
- **League rules are never hardcoded.** Bonus/malus, the voto source, the modifier flags, the budget, the team count and the roster bounds are read from `v_league_settings_current`; role priors are computed from the history under the same scoring, not typed; module demand is derived from `modules.yml`. The D-Factor table is a YAML file with `source`/`verified_on`, empty until transcribed from the league's own settings page.
- **`bnMls` pairs must agree.** Every bonus key is a two-element list whose meaning is unverified (all observed pairs are equal: `[3, 3]`, `[-0.5, -0.5]`…). `BonusMalus.from_calculate` refuses a pair whose values differ and names the key, so the first league that sets them apart fails loud rather than silently picking an index. The three assist keys (`bmass`, `bmasf`, `bmasg`) must agree with each other for the same reason; the workbook has one `Ass` column.
- **`pricing.py` is pure and bounded.** No I/O, no database, no logging, no clock; frozen dataclasses in and out; every tunable in `PricingConfig`, loadable from `pricing.yml` by a separate module; `explain()` beside `price_board()`. Target ~300 lines: the DP, the convolution, the search, the explanation. Growth past that means something which is not pricing has moved in.
- **Forecast rows are immutable.** `valuation_runs`, `valuations` and `valuation_prices` are append-only; a run is never edited; supersession is a derived view (`v_valuation_runs.superseded`), not an update.
- **Nothing is overwritten**, with the same one exception as Phase 0b (`record_advanced(..., force=True)` re-derives an existing snapshot whose full key is identical) and one new, deliberate one: `data/exports/*.md|csv` are regenerable renderings and are rewritten by every `rank`. `records/` files are named by `run_id`/`rules_hash` and are never rewritten.
- **Every run before the freeze is provisional** (spec, open question 1). `rank` says so on its status line when the league has fewer teams than `league.yml` expects or the auction date is inside seven days; the final pre-auction run is the one after the freeze.
- **Email addresses never reach a tool result or a stored payload.** Participant dossiers carry a nick and a team name, never an address; `load_participant` rejects an `@`-shaped value in any front-matter field.
- **Exit codes are the contract**: `0` ok, `1` unexpected error, `2` usage, `3` not ready (no database, no listone, no history, unknown modifier active, D-Factor active with an empty table, voto source unknown, pricing.yml malformed), `4` conflict (`league.yml` vs the API, from the re-sync). `ruff check core` is clean on `main` and must stay clean; the 13 pre-existing findings are all under `mcp/fantacalcio/` and are not this plan's to fix. After writing a task's files run `uv run ruff check --fix core` once (it only reorders and wraps imports), then `uv run ruff check core` must be silent. `typer.Option` defaults on `list[...]` parameters are module-level singletons (B008), as in `cli/app.py`.
- **DuckDB is single-process for writes.** `rank` opens read-write once, after the network re-sync, and closes before returning. Read-only pre-reads (`doctor`, `query`) never coexist with it in one process.
- **Commit messages document the change, never the tool.** No `Claude-Session:` trailer, no `Co-Authored-By: Claude`, no "Generated with Claude Code". One commit per task; the spec revision in Task 10 is one further deliberate `docs(spec):` commit, as CLAUDE.md allows for a revision.
- **This plan lives on the branch `feat/phase-1-market`** (created 2026-08-29 from `main` at `f234136`). It is committed once, when finished; nothing is pushed until the phase is done or the user says so.

## Source facts observed on 2026-08-29

Recorded here because the scoring function and the projection are written against them; each module's docstring repeats the part it depends on. Every number below was read from the live database (`fanta.duckdb`, read-only) or from a committed fixture, never from memory.

**`settings/calculate` (`mcp/fantacalcio/tests/fixtures/calculation_settings.json`; the live snapshot, `rules_hash bc74428832035639`, carries the same fields and values)** — `sourcev: 1`; `bnMls`: `bmgs [3, 3]` (gol), `bmpsc [3, 3]` (rigore segnato), `bmasf`/`bmass`/`bmasg [1, 1]` (assist, three spellings), `bmgc [-1, -1]` (gol subito), `bmpsa [3, 3]` (rigore parato), `bmpns [-2, -2]` (rigore sbagliato — the site's default is −3, so this league already deviates), `bmyc [-0.5, -0.5]`, `bmrc [-1, -1]`, `bmog [-1, -1]` (autogol — default −2), `bmcsh 0` (porta imbattuta off), `bmycsv 0`, `bmcg`/`bmdg`/`bmeg`/`motm [0, 0]` (meaning unconfirmed, all zero, kept raw); every modifier field — `stbdf`, `smodg`, `smodd`, `smodm`, `skodm`, `smodf`, `smodl`, `smodp`, `smodcp` — is `null`. `rosters`: `budg 500`, `msltc 23`, `xsltc 40`, `sroles 2`, `minrl [2, 21]`, `maxrl [6, 34]`. `league_profile`: `n_s 8`. `teams[]`: `n` (team name), `nu` (owner nick).

**The voti workbook's event columns** (`v_player_match_current`, seasons 18–21, sheet `Fantacalcio`): `Gf` **excludes** penalty goals — of 258 rows with `pen_scored > 0`, 223 carry `goals = 0` and only 35 carry `goals >= pen_scored`, so a penalty goal is scored through `bmpsc × pen_scored` and never double-counted through `bmgs`; `Gs` (goals conceded) is non-zero only on goalkeeper rows (517 of 767 `P` rows, none of 3957 `D` rows), so `bmgc × goals_conceded` needs no role gate; a senza-voto row has `voto NULL` and `senza_voto = true` (1139 of 12686 rows in season 20); the coach row (`classic_role = 'ALL'`, 760 rows in season 20) parses like a player and must be filtered out of every consumer. Three sheets — `Fantacalcio`, `Statistico`, `Italia` — carry 38367 rows each; the public voti page lists the sources in that order, which is the basis of the `sourcev → sheet` hypothesis in Task 2.

**Per-role scoring shape, season 20, sheet `Fantacalcio`, players only, under this league's bonus/malus** — mean voto / sd of the voto / mean fantavoto / sd of the per-match fantavoto, the fantavoto figures including penalty-goal points scored through `bmpsc × pen_scored` (per the `Gf`-excludes-penalties fact above -- a figure computed without them, as an earlier version of this table did, is off by the club's penalty-taking share): `P` 6.17 / 0.55 / 5.03 / 1.54; `D` 5.93 / 0.58 / 6.00 / 1.07; `C` 5.99 / 0.58 / 6.23 / 1.37; `A` 5.99 / 0.69 / 6.58 / 1.96. These are what `history.role_priors` computes at run time; they are quoted so a test's synthetic numbers look like the real ones, and so a reviewer can tell a plausible prior from a bug.

**Coverage**: 553 listone players; 376 have a season-20 line; `v_player_season.appearances` averages 20.3 rows and `presenze` (rows with a voto) 18.5 per player-season in the back seasons; season 21 has 2 giornate. Understat, season 20: 367 matched of 586 rows; season 21: 306 of 322. Reference lines: `Martinez L.` (`player_id 2764`, Inter, `Pc`, `acsma 35`) season 20: 30 presenze, media voto 6.42, 17 goals, 6 assists, 2205 minutes, xG 17.1, xA 6.3; `Thuram` (`4871`) 29 / 6.43 / 13 / 6 / xG 11.9; `Hojlund` (`6052`) 33 / 6.21 / 11 / 5 / xG 13.3.

**The listone by Mantra role set** (`v_players_current`): 283 single-role, 249 two-role, 21 three-role players; the common sets are `Dc` 76, `Por` 70, `M;C` 67, `Pc` 61, `C;W` 31, `Ds;E` 31, `Dd;E` 29, `A` 25, `T;A` 25, `C` 25, `Ds;Dc` 19, `T;W` 16, `Dd;Dc` 15, `T` 11, `W` 9, `Dd;Ds;E` 8, `Ds;B;E` 7, `E;T` 6, `E` 6, `W;A` 5, `Dd;B;E` 4 — `B` never appears alone. Mantra quotazioni sum to 3609 (16 players ≥ 20, 303 between 5 and 19, 234 ≤ 4); by classic role: `A` 97 players / 927, `C` 188 / 1308, `D` 198 / 1091, `P` 70 / 283.

**The fixtures the tests reuse**: `core/tests/fixtures/listone_sample.json` — 17 players over 8 clubs, ids `3` (Radunovic, Cagliari, `Por`, acsma 1), `5841` (Roma `Por` 18), `2120` (Inter `Dc` 14), `254` (Inter `E;T` 30), `5877` (Carlos Augusto, Inter, `B;Ds;E` 8), `2764` (Martinez L., Inter, `Pc` 35), `2194` (Inter `M;C` 28), `2423` (Pulisic, Milan, `W;A` 23), `2097` (Fiorentina `Pc` 25), `6052` (Hojlund, Napoli, `Pc` 28), `2517` (Napoli `W` 14), `536` (Napoli `T` 9), `309` (Roma `A` 15), `152` (Inter `C` 10), `2297` (Atalanta `Por` 1), `791` (Genoa `Dd;Ds;E` 2), `2640` (Kolasinac, Atalanta, `Ds;Dc` 6); `voti_sample.xlsx` — the Atalanta and Bologna blocks of giornata 1, 2026-27, every sheet; `understat_sample.json` — 10 rows for season 20; the MCP settings fixtures above. `test_doctor._ready_workspace` seeds all of them into one workspace and is reused by the `rank` CLI tests.

---

## File Structure

| file | responsibility |
| --- | --- |
| `core/pyproject.toml`, `uv.lock` | `+ numpy>=2.5` |
| `core/src/fantaclaude/db/schema.py` | `SCHEMA_VERSION = 3`; `advanced_snapshots` rebuilt with the full dedupe key; `valuation_runs`, `valuations`, `valuation_prices`; `v_valuation_runs`, `v_valuations_current`, `v_valuation_prices_current`; the 2→3 migration |
| `core/src/fantaclaude/ingest/advanced.py`, `commands/ingest.py`, `cli/app.py` | `record_advanced` keyed on `(sha256, aliases_sha256, listone_snapshot_id)`; `--rematch` appends when the key moved |
| `core/src/fantaclaude/model/scoring.py` | `BonusMalus`, `Events`, `event_points`, `fantavoto`, `voto_sheet`, `modifier_status` |
| `core/src/fantaclaude/model/d_factor.yml`, `model/d_factor.py` | the D-Factor table (league data, empty until transcribed) and the pure `defensive_average` / `d_factor_points` |
| `core/src/fantaclaude/model/demand.py` | role classes, per-module fractional demand, rank weights, hard minimums, `pin_class` — all from `modules.yml` |
| `core/src/fantaclaude/kb/notes.py`, `kb/participants.py`, `kb/audit.py` | `PlayerNote`/`load_player_notes`, `Participant`/`load_participants`; both validated by the audit |
| `core/src/fantaclaude/analysis/history.py` | `SeasonLine`, `RolePrior`, `History`, `load_history` — the observed layer under the league's scoring |
| `core/src/fantaclaude/analysis/projection.py` | `ProjectionConfig`, `PlayerInputs`, `Projection`, `project_player`, `project_all` |
| `core/src/fantaclaude/asta/pricing.py`, `asta/pricing_config.py`, `pricing.yml` | the pure pricing function and its YAML-loaded config |
| `core/src/fantaclaude/analysis/valuation.py` | `Scenario`, `load_scenarios`, `model_hash`, `inputs_hash`, `build_pool`, `replacement_levels`, `assign_tiers`, `divergence`, `run_valuation`, `record_run` |
| `core/src/fantaclaude/analysis/exports.py` | `rankings.md`, `rankings.csv`, `asta-plan.md`, `records/` parquet |
| `core/src/fantaclaude/commands/rank.py`, `cli/app.py` | `rank()` importable; `fantaclaude rank [--offline] [--scenario …]` |
| `core/src/fantaclaude/commands/sync_league.py` | superseded runs reported when the rules hash moves |
| `core/src/fantaclaude/commands/doctor.py` | `+ kb_notes, kb_participants, scoring, pricing, valuations` checks |
| `core/src/fantaclaude/paths.py` | `+ exports_dir()`, `pricing_yml_path()` |
| `preferences.yml`, `pricing.yml`, `records/README.md`, `kb/README.md`, `core/README.md`, `CLAUDE.md` | the scenarios block; the pricing knobs; documentation |
| `.claude/skills/fanta-market/SKILL.md`, `.claude/skills/fanta-kb/SKILL.md` | the new skill; the `interview` mode |
| `core/tests/test_schema.py`, `test_advanced.py`, `test_scoring.py`, `test_d_factor.py`, `test_demand.py`, `test_kb_notes.py`, `test_kb_participants.py`, `test_history.py`, `test_projection.py`, `test_pricing.py`, `test_valuation.py`, `test_rank_cli.py`, `test_doctor.py`, `test_sync_league.py` | one module per source module |

Baseline on `main` (`f234136`): `uv run poe test` → 111 passed (MCP) and 203 passed (core); `uv run ruff check core` → clean. Every task's final step states the expected core count after it; the executor replaces the estimate with the measured number.

---

### Task 1: Schema version 3 — the valuation tables and the advanced dedupe key

**Files:**
- Modify: `core/src/fantaclaude/db/schema.py`, `core/src/fantaclaude/ingest/advanced.py`, `core/src/fantaclaude/commands/ingest.py`, `core/src/fantaclaude/commands/doctor.py:96-112`, `core/src/fantaclaude/cli/app.py:245-266`
- Test: `core/tests/test_schema.py`, `core/tests/test_advanced.py`, `core/tests/test_doctor.py`, `core/tests/test_ingest_all.py:332`

**Interfaces:**
- Consumes: `apply_schema`, `record_advanced(con, season_id, rows, raw, *, candidates, teams, aliases, force=False)`, `rematch_advanced_seasons`, `RawStore.sha256_of`.
- Produces: `SCHEMA_VERSION == 3`; tables `valuation_runs(run_id, created_at, rules_hash, model_hash, inputs_hash, settings_snapshot_id, listone_snapshot_id, season_id, giornata, scenarios VARCHAR[], config JSON, summary JSON)`, `valuations(run_id, player_id, name, team_short, classic_role, role_class, roles VARCHAR[], exp_presenze, exp_fantamedia, exp_voto, value_p25, value_p50, value_p75, replacement, vor, tier, quot_mantra, implied_value, divergence, explain JSON)`, `valuation_prices(run_id, scenario, player_id, role_class, expected_price, max_p25, max_p50, max_p75, walk_value, exact BOOLEAN, explain JSON)`; views `v_valuation_runs` (`+ superseded BOOLEAN`), `v_valuations_current`, `v_valuation_prices_current`; `advanced_snapshots(..., aliases_sha256 VARCHAR, listone_snapshot_id INTEGER, ...)` with `UNIQUE (sha256, aliases_sha256, listone_snapshot_id)`; `record_advanced(con, season_id, rows, raw, *, candidates, teams, aliases, aliases_sha256: str, listone_snapshot_id: int, force=False)`; `AdvancedIngestResult` gains `aliases_sha256`, `listone_snapshot_id`; `advanced_key(con, aliases_path) -> tuple[str, int]` in `commands/ingest.py`.

- [ ] **Step 1: Write the failing schema tests**

Replace `core/tests/test_schema.py` with:

```python
import duckdb
import pytest
from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.db.schema import (
    SCHEMA_VERSION,
    SchemaVersionMismatch,
    apply_schema,
    schema_report,
)

V2_OBJECTS = {"voti_files", "player_match", "advanced_snapshots", "advanced_stats", "fixture_snapshots",
              "fixtures", "v_voti_files_current", "v_player_match_current", "v_player_season",
              "v_player_form", "v_advanced_current", "v_advanced_unmatched", "v_fixtures_current",
              "v_european_ties"}
V3_OBJECTS = {"valuation_runs", "valuations", "valuation_prices",
              "v_valuation_runs", "v_valuations_current", "v_valuation_prices_current"}

# advanced_snapshots exactly as Phase 0b created it: the shape a live version-2 file carries.
V2_ADVANCED_SNAPSHOTS = """
CREATE TABLE advanced_snapshots (
    snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('seq_advanced_snapshots'),
    season_id   INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_path    VARCHAR NOT NULL,
    sha256      VARCHAR NOT NULL UNIQUE,
    row_count   INTEGER NOT NULL,
    matched     INTEGER NOT NULL,
    ambiguous   INTEGER NOT NULL,
    unmatched   INTEGER NOT NULL
)"""


def _columns(con, table):
    return [r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()]


def test_apply_schema_is_idempotent(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    assert apply_schema(con) == SCHEMA_VERSION == 3
    assert apply_schema(con) == SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
    con.close()


def test_schema_report_lists_tables_and_views(db):
    report = schema_report(db)
    kinds = {t.name: t.kind for t in report.tables}
    assert kinds["players"] == "table" and kinds["v_players_current"] == "view"
    assert {"league_settings", "listone_snapshots", "teams", "player_aliases",
            "v_league_settings_current", "v_teams_current"} <= set(kinds)
    assert V2_OBJECTS <= set(kinds) and V3_OBJECTS <= set(kinds)
    assert kinds["valuations"] == "table" and kinds["v_valuation_runs"] == "view"
    players = next(t for t in report.tables if t.name == "players")
    assert [c.name for c in players.columns][:3] == ["snapshot_id", "player_id", "name"]
    assert players.rows == 0
    assert report.version == SCHEMA_VERSION
    assert report.to_dict()["version"] == SCHEMA_VERSION


def test_advanced_snapshots_carries_the_full_dedupe_key(db):
    cols = _columns(db, "advanced_snapshots")
    assert cols == ["snapshot_id", "season_id", "fetched_at", "source", "raw_path", "sha256",
                    "aliases_sha256", "listone_snapshot_id", "row_count", "matched", "ambiguous", "unmatched"]
    row = ["x", "raw", "abc", "al1", 1, 0, 0, 0, 0]
    db.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
               "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (20, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(duckdb.Error):                      # the same three inputs twice is a constraint violation
        db.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
                   "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (20, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    row[3] = "al2"                                          # a changed aliases file is a new derivation
    db.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
               "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (20, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert db.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 2


def test_a_version_1_file_is_migrated_forward_in_place(tmp_path):
    """The Phase 0a database must not be rebuilt with more live-API calls:
    the DDL is additive, so apply_schema upgrades it and keeps its rows."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    for view in sorted(v for v in V2_OBJECTS | V3_OBJECTS if v.startswith("v_")):
        con.execute(f"DROP VIEW {view}")
    for table in ("player_match", "voti_files", "advanced_stats", "advanced_snapshots", "fixtures", "fixture_snapshots",
                  "valuation_prices", "valuations", "valuation_runs"):
        con.execute(f"DROP TABLE {table}")
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (1)")
    con.execute("INSERT INTO teams VALUES (1, 15, 'Roma', 'ROM')")
    con.close()

    con = connect(path)
    assert apply_schema(con) == 3
    assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 2      # history of versions kept
    assert con.execute("SELECT name FROM teams").fetchone()[0] == "Roma"               # v1 rows survive
    assert con.execute("SELECT count(*) FROM v_player_season").fetchone()[0] == 0
    assert "aliases_sha256" in _columns(con, "advanced_snapshots")
    con.close()


def test_a_version_2_file_gets_its_advanced_snapshots_rebuilt(tmp_path):
    """The live Phase 0b file: advanced_snapshots exists in the old shape with
    rows and UNIQUE(sha256). DuckDB cannot drop a constraint, so the table is
    rebuilt around its rows; the old rows get a NULL key -- which is what
    makes the next `ingest advanced` re-match them under the full key."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    for view in sorted(v for v in V3_OBJECTS if v.startswith("v_")):
        con.execute(f"DROP VIEW {view}")
    for table in ("valuation_prices", "valuations", "valuation_runs", "advanced_snapshots"):
        con.execute(f"DROP TABLE {table}")
    con.execute(V2_ADVANCED_SNAPSHOTS)
    con.execute("INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, row_count, matched, "
                "ambiguous, unmatched) VALUES (20, now(), 'understat', 'p', 'deadbeef', 10, 5, 1, 4)")
    con.execute("INSERT INTO advanced_stats VALUES (1, 20, '7006', 'Lautaro', ['Inter'], 2764, 'matched', [2764], "
                "30, 2205, 17, 6, 17.1, 6.3, 14, 14.0, 90, 30, 3, 0, 20.0, 5.0, 'F', '{}')")
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (2)")
    con.close()

    con = connect(path)
    assert apply_schema(con) == 3
    assert _columns(con, "advanced_snapshots")[6:8] == ["aliases_sha256", "listone_snapshot_id"]
    kept = con.execute("SELECT snapshot_id, sha256, aliases_sha256, listone_snapshot_id, matched FROM advanced_snapshots").fetchall()
    assert kept == [(1, "deadbeef", None, None, 5)]
    assert con.execute("SELECT count(*) FROM v_advanced_current").fetchone()[0] == 1
    nxt = con.execute("SELECT nextval('seq_advanced_snapshots')").fetchone()[0]
    assert nxt >= 2                                          # the sequence continues past the kept rows
    assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'advanced_snapshots_v2'").fetchone()[0] == 0
    con.close()


def test_a_newer_file_is_refused(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    apply_schema(con)
    con.execute("INSERT INTO schema_version (version) VALUES (99)")
    with pytest.raises(SchemaVersionMismatch):
        apply_schema(con)
    con.close()


def test_read_only_connection_requires_an_existing_file(tmp_path):
    with pytest.raises(DatabaseMissing):
        connect(tmp_path / "missing.duckdb", read_only=True)


def test_read_only_connection_rejects_writes(tmp_path):
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    con.close()
    ro = connect(path, read_only=True)
    with pytest.raises(duckdb.Error):
        ro.execute("INSERT INTO teams VALUES (1, 1, 'x', 'X')")
    ro.close()


def test_write_connection_creates_the_parent_directory(tmp_path):
    con = connect(tmp_path / "nested" / "x.duckdb")
    con.close()
    assert (tmp_path / "nested" / "x.duckdb").is_file()


def test_views_over_empty_history_are_queryable(db):
    for view in sorted(v for v in V2_OBJECTS | V3_OBJECTS if v.startswith("v_")):
        assert db.execute(f"SELECT count(*) FROM {view}").fetchone()[0] == 0, view


def test_valuation_views_pick_the_newest_run_under_the_rules_in_force(db, mcp_fixture_json):
    from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads

    snap = snapshot_from_payloads(profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
                                  rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
                                  calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams"))
    record_snapshot(db, snap)
    for run_id, rules, created in (("r1", snap.rules_hash, "2026-08-29 10:00:00"), ("r2", "0000000000000000", "2026-08-29 11:00:00"),
                                   ("r3", snap.rules_hash, "2026-08-29 09:00:00")):
        db.execute("INSERT INTO valuation_runs VALUES (?, ?, ?, 'm', 'i', 1, 1, 21, 2, ['balanced'], '{}', '{}')",
                   [run_id, created, rules])
        db.execute("INSERT INTO valuations VALUES (?, 2764, 'Martinez L.', 'INT', 'A', 'Pc', ['Pc'], 33.0, 7.1, 6.4, "
                   "200.0, 234.0, 260.0, 90.0, 144.0, 1, 35, 230.0, 4.0, '{}')", [run_id])
        db.execute("INSERT INTO valuation_prices VALUES (?, 'balanced', 2764, 'Pc', 42, 60, 68, 75, 1500.0, true, '{}')", [run_id])
    superseded = dict(db.execute("SELECT run_id, superseded FROM v_valuation_runs").fetchall())
    assert superseded == {"r1": False, "r2": True, "r3": False}
    assert db.execute("SELECT run_id FROM v_valuations_current").fetchall() == [("r1",)]      # newest, not superseded
    assert db.execute("SELECT run_id FROM v_valuation_prices_current").fetchall() == [("r1",)]
```

- [ ] **Step 2: Run the schema tests to verify they fail**

Run: `uv run pytest core/tests/test_schema.py -q`
Expected: FAIL — `SCHEMA_VERSION == 3` is false, `V3_OBJECTS` are missing, `aliases_sha256` is not a column.

- [ ] **Step 3: Move the schema to version 3**

In `core/src/fantaclaude/db/schema.py`, replace the module docstring's last two sentences and `SCHEMA_VERSION`, split the `advanced_snapshots` DDL out into its own constant, add the three tables and three views, and add the migration. The full file after the edit:

```python
"""The analytical spine's DDL, applied idempotently.

Snapshot tables, never overwrites: league_settings appends one row per
observed rule change, listone_snapshots/players append one snapshot per
ingest, and the v_*_current views pick the latest. Raw payloads travel in a
JSON column so a field the models do not name is still there to query.
Version 2 (Phase 0b) added the observed history -- player_match from the
voti workbooks, advanced_stats from Understat, fixtures from the Serie A
calendar and UEFA -- and the views over them. Version 3 (Phase 1) adds the
derived layer -- valuation_runs, valuations and valuation_prices, every row
immutable, supersession a view -- and rebuilds advanced_snapshots around a
dedupe key that covers every input of the match: the raw bytes, the aliases
file and the listone snapshot, so a changed alias re-matches on its own.
The DDL is additive: apply_schema upgrades an older file in place and
refuses only a newer one; the one table whose constraint changed (version 2
to 3) is rebuilt around its rows, because DuckDB cannot drop a constraint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import duckdb

SCHEMA_VERSION = 3

ADVANCED_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS advanced_snapshots (
    snapshot_id         INTEGER PRIMARY KEY DEFAULT nextval('seq_advanced_snapshots'),
    season_id           INTEGER NOT NULL,
    fetched_at          TIMESTAMP NOT NULL,
    source              VARCHAR NOT NULL,
    raw_path            VARCHAR NOT NULL,
    sha256              VARCHAR NOT NULL,
    aliases_sha256      VARCHAR,
    listone_snapshot_id INTEGER,
    row_count           INTEGER NOT NULL,
    matched             INTEGER NOT NULL,
    ambiguous           INTEGER NOT NULL,
    unmatched           INTEGER NOT NULL,
    UNIQUE (sha256, aliases_sha256, listone_snapshot_id)
)"""

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
CREATE SEQUENCE IF NOT EXISTS seq_voti_files START 1;
CREATE TABLE IF NOT EXISTS voti_files (
    file_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_voti_files'),
    season_id   INTEGER NOT NULL,
    giornata    INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_path    VARCHAR NOT NULL,
    sha256      VARCHAR NOT NULL,
    sheets      VARCHAR[] NOT NULL,
    row_count   INTEGER NOT NULL,
    UNIQUE (season_id, giornata, sha256)
);
CREATE TABLE IF NOT EXISTS player_match (
    file_id        INTEGER NOT NULL,
    season_id      INTEGER NOT NULL,
    giornata       INTEGER NOT NULL,
    sheet          VARCHAR NOT NULL,
    player_id      INTEGER NOT NULL,
    name           VARCHAR NOT NULL,
    team           VARCHAR NOT NULL,
    classic_role   VARCHAR NOT NULL,
    voto           DECIMAL(4,2),
    senza_voto     BOOLEAN NOT NULL,
    goals          INTEGER NOT NULL,
    goals_conceded INTEGER NOT NULL,
    pen_saved      INTEGER NOT NULL,
    pen_missed     INTEGER NOT NULL,
    pen_scored     INTEGER NOT NULL,
    own_goals      INTEGER NOT NULL,
    yellow         INTEGER NOT NULL,
    red            INTEGER NOT NULL,
    assists        INTEGER NOT NULL,
    raw            JSON NOT NULL,
    PRIMARY KEY (file_id, sheet, player_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_advanced_snapshots START 1;
""" + ADVANCED_SNAPSHOTS_DDL + """;
CREATE TABLE IF NOT EXISTS advanced_stats (
    snapshot_id  INTEGER NOT NULL,
    season_id    INTEGER NOT NULL,
    source_id    VARCHAR NOT NULL,
    player_name  VARCHAR NOT NULL,
    teams        VARCHAR[] NOT NULL,
    player_id    INTEGER,
    match_status VARCHAR NOT NULL,
    candidates   INTEGER[] NOT NULL,
    games        INTEGER NOT NULL,
    minutes      INTEGER NOT NULL,
    goals        INTEGER NOT NULL,
    assists      INTEGER NOT NULL,
    xg           DOUBLE NOT NULL,
    xa           DOUBLE NOT NULL,
    npg          INTEGER NOT NULL,
    npxg         DOUBLE NOT NULL,
    shots        INTEGER NOT NULL,
    key_passes   INTEGER NOT NULL,
    yellow       INTEGER NOT NULL,
    red          INTEGER NOT NULL,
    xg_chain     DOUBLE NOT NULL,
    xg_buildup   DOUBLE NOT NULL,
    position     VARCHAR NOT NULL,
    raw          JSON NOT NULL,
    PRIMARY KEY (snapshot_id, source_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_fixture_snapshots START 1;
CREATE TABLE IF NOT EXISTS fixture_snapshots (
    snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('seq_fixture_snapshots'),
    competition VARCHAR NOT NULL,
    season_id   INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_paths   VARCHAR[] NOT NULL,
    sha256      VARCHAR NOT NULL,
    row_count   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fixtures (
    snapshot_id INTEGER NOT NULL,
    competition VARCHAR NOT NULL,
    season_id   INTEGER NOT NULL,
    source_id   VARCHAR NOT NULL,
    round       VARCHAR NOT NULL,
    giornata    INTEGER,
    phase       VARCHAR,
    kickoff     TIMESTAMP,
    home        VARCHAR NOT NULL,
    away        VARCHAR NOT NULL,
    home_short  VARCHAR,
    away_short  VARCHAR,
    raw         JSON NOT NULL,
    PRIMARY KEY (snapshot_id, source_id)
);
CREATE TABLE IF NOT EXISTS valuation_runs (
    run_id               VARCHAR PRIMARY KEY,
    created_at           TIMESTAMP NOT NULL,
    rules_hash           VARCHAR NOT NULL,
    model_hash           VARCHAR NOT NULL,
    inputs_hash          VARCHAR NOT NULL,
    settings_snapshot_id INTEGER NOT NULL,
    listone_snapshot_id  INTEGER NOT NULL,
    season_id            INTEGER NOT NULL,
    giornata             INTEGER NOT NULL,
    scenarios            VARCHAR[] NOT NULL,
    config               JSON NOT NULL,
    summary              JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS valuations (
    run_id         VARCHAR NOT NULL,
    player_id      INTEGER NOT NULL,
    name           VARCHAR NOT NULL,
    team_short     VARCHAR,
    classic_role   VARCHAR NOT NULL,
    role_class     VARCHAR NOT NULL,
    roles          VARCHAR[] NOT NULL,
    exp_presenze   DOUBLE NOT NULL,
    exp_fantamedia DOUBLE NOT NULL,
    exp_voto       DOUBLE NOT NULL,
    value_p25      DOUBLE NOT NULL,
    value_p50      DOUBLE NOT NULL,
    value_p75      DOUBLE NOT NULL,
    replacement    DOUBLE NOT NULL,
    vor            DOUBLE NOT NULL,
    tier           INTEGER NOT NULL,
    quot_mantra    INTEGER,
    implied_value  DOUBLE,
    divergence     DOUBLE,
    explain        JSON NOT NULL,
    PRIMARY KEY (run_id, player_id)
);
CREATE TABLE IF NOT EXISTS valuation_prices (
    run_id         VARCHAR NOT NULL,
    scenario       VARCHAR NOT NULL,
    player_id      INTEGER NOT NULL,
    role_class     VARCHAR NOT NULL,
    expected_price INTEGER NOT NULL,
    max_p25        INTEGER NOT NULL,
    max_p50        INTEGER NOT NULL,
    max_p75        INTEGER NOT NULL,
    walk_value     DOUBLE NOT NULL,
    exact          BOOLEAN NOT NULL,
    explain        JSON NOT NULL,
    PRIMARY KEY (run_id, scenario, player_id)
);
CREATE OR REPLACE VIEW v_voti_files_current AS
    SELECT f.* FROM voti_files f
    WHERE f.file_id = (SELECT max(g.file_id) FROM voti_files g
                       WHERE g.season_id = f.season_id AND g.giornata = f.giornata);
CREATE OR REPLACE VIEW v_player_match_current AS
    SELECT m.* FROM player_match m
    WHERE m.file_id IN (SELECT file_id FROM v_voti_files_current);
CREATE OR REPLACE VIEW v_advanced_current AS
    SELECT a.* FROM advanced_stats a
    WHERE a.snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id);
CREATE OR REPLACE VIEW v_advanced_unmatched AS
    SELECT season_id, source_id, player_name, teams, match_status, candidates
    FROM v_advanced_current WHERE player_id IS NULL;
CREATE OR REPLACE VIEW v_player_season AS
    SELECT m.season_id, m.sheet, m.player_id, any_value(m.name) AS name,
           list(DISTINCT m.team) AS teams,
           count(*) AS appearances,
           count(*) FILTER (WHERE NOT m.senza_voto) AS presenze,
           avg(m.voto) AS media_voto,
           sum(m.goals) AS goals, sum(m.assists) AS assists,
           sum(m.goals_conceded) AS goals_conceded,
           sum(m.pen_scored) AS pen_scored, sum(m.pen_missed) AS pen_missed,
           sum(m.pen_saved) AS pen_saved, sum(m.own_goals) AS own_goals,
           sum(m.yellow) AS yellow, sum(m.red) AS red,
           any_value(a.minutes) AS minutes, any_value(a.games) AS games_understat,
           any_value(a.xg) AS xg, any_value(a.xa) AS xa
    FROM v_player_match_current m
    LEFT JOIN (SELECT season_id, player_id, sum(minutes) AS minutes, sum(games) AS games,
                      sum(xg) AS xg, sum(xa) AS xa
               FROM v_advanced_current WHERE player_id IS NOT NULL
               GROUP BY season_id, player_id) a
           ON a.season_id = m.season_id AND a.player_id = m.player_id
    GROUP BY m.season_id, m.sheet, m.player_id;
CREATE OR REPLACE VIEW v_player_form AS
    SELECT season_id, sheet, player_id, any_value(name) AS name,
           count(*) AS n, avg(voto) AS media_voto, sum(goals) AS goals,
           sum(assists) AS assists, max(giornata) AS last_giornata
    FROM (SELECT season_id, sheet, player_id, name, giornata, voto, goals, assists,
                 dense_rank() OVER (PARTITION BY season_id, sheet, player_id
                                    ORDER BY giornata DESC) AS rn
          FROM v_player_match_current
          WHERE NOT senza_voto AND season_id = (SELECT max(season_id) FROM voti_files))
    WHERE rn <= 5
    GROUP BY season_id, sheet, player_id;
CREATE OR REPLACE VIEW v_fixtures_current AS
    SELECT x.* FROM fixtures x
    WHERE x.snapshot_id IN (SELECT max(snapshot_id) FROM fixture_snapshots
                            GROUP BY competition, season_id);
CREATE OR REPLACE VIEW v_european_ties AS
    SELECT * FROM (
        SELECT competition, season_id, source_id, round, phase, kickoff, home, away,
               unnest([home_short, away_short]) AS team_short
        FROM v_fixtures_current WHERE competition <> 'SA')
    WHERE team_short IS NOT NULL;
CREATE OR REPLACE VIEW v_valuation_runs AS
    SELECT r.*, coalesce(r.rules_hash <> (SELECT rules_hash FROM v_league_settings_current), true) AS superseded
    FROM valuation_runs r;
CREATE OR REPLACE VIEW v_valuations_current AS
    SELECT v.* FROM valuations v
    WHERE v.run_id = (SELECT run_id FROM v_valuation_runs WHERE NOT superseded
                      ORDER BY created_at DESC, run_id DESC LIMIT 1);
CREATE OR REPLACE VIEW v_valuation_prices_current AS
    SELECT p.* FROM valuation_prices p
    WHERE p.run_id = (SELECT run_id FROM v_valuation_runs WHERE NOT superseded
                      ORDER BY created_at DESC, run_id DESC LIMIT 1);
"""


class SchemaVersionMismatch(RuntimeError):
    """The file was written by a different schema version; migrate before use."""


def _stored_version(con: duckdb.DuckDBPyConnection) -> int | None:
    try:
        return con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    except duckdb.CatalogException:
        return None


def _has_column(con: duckdb.DuckDBPyConnection, table: str, column: str) -> bool | None:
    """None when the table does not exist."""
    exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'main' "
                         "AND table_name = ?", [table]).fetchone()[0]
    if not exists:
        return None
    return column in {r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()}


def _migrate_advanced_snapshots_to_v3(con: duckdb.DuckDBPyConnection) -> None:
    """Version 2 keyed advanced_snapshots on sha256 alone (UNIQUE), so a
    changed alias or listone could never re-match an already-recorded file.
    DuckDB cannot drop a UNIQUE constraint, so the table is rebuilt around
    its rows: the old rows keep their snapshot_id (advanced_stats points at
    it) and get a NULL aliases_sha256/listone_snapshot_id, which no new row
    ever has -- the next ingest re-matches them under the full key and
    appends. The sequence is untouched, so new ids continue past the old."""
    if _has_column(con, "advanced_snapshots", "aliases_sha256") is not False:
        return
    con.execute("ALTER TABLE advanced_snapshots RENAME TO advanced_snapshots_v2")
    con.execute(ADVANCED_SNAPSHOTS_DDL)
    con.execute("INSERT INTO advanced_snapshots SELECT snapshot_id, season_id, fetched_at, source, raw_path, sha256, "
                "NULL, NULL, row_count, matched, ambiguous, unmatched FROM advanced_snapshots_v2")
    con.execute("DROP TABLE advanced_snapshots_v2")


def apply_schema(con: duckdb.DuckDBPyConnection) -> int:
    """Create what is missing, then reconcile the version row.

    The DDL is additive (CREATE ... IF NOT EXISTS, CREATE OR REPLACE VIEW),
    so running it against an older file upgrades it in place -- the live
    database keeps its rows instead of being rebuilt with more live-API
    calls. A table whose *constraint* changed is rebuilt first, around its
    rows. A stored version *newer* than the code is the one case that is
    refused: the code cannot know what that file holds.
    """
    stored = _stored_version(con)
    if stored is not None and stored > SCHEMA_VERSION:
        raise SchemaVersionMismatch(f"database is at schema {stored}, code expects {SCHEMA_VERSION}")
    if stored is not None and stored < 3:
        _migrate_advanced_snapshots_to_v3(con)
    for statement in DDL.split(";"):
        if statement.strip():
            con.execute(statement)
    if stored is None or stored < SCHEMA_VERSION:
        con.execute("INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION])
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

Two DuckDB facts this relies on, both to be confirmed by the tests rather than trusted: `ALTER TABLE … RENAME TO` is supported; `DESCRIBE "advanced_snapshots"` lists columns in definition order. If `duckdb.CatalogException` is not the exception a missing `schema_version` raises on this version, widen the `except` in `_stored_version` to `duckdb.Error` — the intent is "no version table yet".

- [ ] **Step 4: Run the schema tests to verify they pass**

Run: `uv run pytest core/tests/test_schema.py -q`
Expected: 11 passed.

- [ ] **Step 5: Write the failing advanced-dedupe tests**

In `core/tests/test_advanced.py`, replace `test_record_advanced_matches_flags_and_dedupes` and `test_record_advanced_force_re_matches_the_same_file` with the two below, and update every other `record_advanced(` call in the file to pass `aliases_sha256="a1", listone_snapshot_id=1` (the value is arbitrary in a unit test; the mechanism is what is tested):

```python
def test_record_advanced_matches_flags_and_dedupes(db, tmp_path, fixture_json):
    _listone(db, tmp_path, fixture_json)
    store = RawStore(tmp_path / "raw")
    raw = store.write("advanced", fixture_json("understat_sample"), label="20")
    season_id, rows = load_advanced(raw.path)
    aliases = Aliases(players={"understat": {"Pietro Terracciano": 3}},        # any listone id: the mechanism is what is tested
                      teams={"understat": {"AC Milan": "Milan"}})
    key = {"aliases_sha256": "a1", "listone_snapshot_id": 1}
    result = record_advanced(db, season_id, rows, raw, candidates=load_candidates(db),
                             teams=load_teams(db), aliases=aliases, **key)
    assert result.snapshot_id == 1 and result.inserted == 10 and not result.skipped_duplicate
    assert (result.matched, result.alias, result.ambiguous, result.unmatched) == (5, 1, 1, 3)
    assert (result.aliases_sha256, result.listone_snapshot_id) == ("a1", 1)
    assert result.ambiguous_names == [{"name": "Josep Martínez", "teams": ["Inter"],
                                       "candidates": [{"player_id": 2764, "name": "Martinez L."}]}]
    assert result.unresolved_teams == ["Bologna", "Cremonese", "Pisa", "Sassuolo"]

    status = dict(db.execute("SELECT player_name, match_status FROM v_advanced_current").fetchall())
    assert status["Lautaro Martínez"] == "matched" and status["Rasmus Højlund"] == "matched"
    assert status["Kevin De Bruyne"] == "matched" and status["Christian Pulisic"] == "matched"
    assert status["Sead Kolasinac"] == "matched" and status["Josep Martínez"] == "ambiguous"
    assert status["Pietro Terracciano"] == "alias" and status["Jamie Vardy"] == "unmatched"
    ids = dict(db.execute("SELECT player_name, player_id FROM v_advanced_current").fetchall())
    assert ids["Lautaro Martínez"] == 2764 and ids["Christian Pulisic"] == 2423 and ids["Josep Martínez"] is None
    assert db.execute("SELECT count(*) FROM v_advanced_unmatched").fetchone()[0] == 4
    assert db.execute("SELECT candidates FROM v_advanced_unmatched WHERE player_name = 'Josep Martínez'").fetchone()[0] == [2764]
    assert db.execute("SELECT teams FROM v_advanced_current WHERE source_id = '10985'").fetchone()[0] == ["Bologna", "Cagliari"]
    assert db.execute("SELECT minutes FROM v_player_season").fetchall() == []          # no voti yet: the view stays empty

    again = record_advanced(db, season_id, rows, raw, candidates=load_candidates(db),
                            teams=load_teams(db), aliases=aliases, **key)
    assert again.skipped_duplicate and again.snapshot_id == 1 and again.inserted == 0
    assert (again.matched, again.ambiguous, again.unmatched) == (5, 1, 3)

    changed = fixture_json("understat_sample")
    changed["payload"]["players"][0]["goals"] = "18"
    raw2 = store.write("advanced", changed, label="20")
    second = record_advanced(db, *load_advanced(raw2.path), raw2, candidates=load_candidates(db),
                             teams=load_teams(db), aliases=aliases, **key)
    assert second.snapshot_id == 2
    assert db.execute("SELECT count(*) FROM advanced_stats").fetchone()[0] == 20         # history kept
    assert db.execute("SELECT goals FROM v_advanced_current WHERE source_id = '7006'").fetchone()[0] == 18


def test_the_dedupe_key_covers_the_aliases_file_and_the_listone(db, tmp_path, fixture_json):
    """The match is a function of three inputs -- the raw bytes, the aliases
    file and the listone snapshot -- so a change to any of them is a new
    derivation and appends a snapshot on its own; `force` is only for
    re-deriving an identical key in place (a matcher code change)."""
    _listone(db, tmp_path, fixture_json)
    store = RawStore(tmp_path / "raw")
    raw = store.write("advanced", fixture_json("understat_sample"), label="20")
    season_id, rows = load_advanced(raw.path)
    common = {"candidates": load_candidates(db), "teams": load_teams(db)}
    first = record_advanced(db, season_id, rows, raw, aliases=Aliases(), aliases_sha256="a1", listone_snapshot_id=1, **common)
    assert first.snapshot_id == 1 and not first.skipped_duplicate
    assert db.execute("SELECT player_id FROM v_advanced_current WHERE player_name = 'Josep Martínez'").fetchone()[0] is None

    # The same three inputs again: a no-op, as before.
    noop = record_advanced(db, season_id, rows, raw, aliases=Aliases(), aliases_sha256="a1", listone_snapshot_id=1, **common)
    assert noop.skipped_duplicate and noop.snapshot_id == 1

    # An alias added after the first recording: a different aliases_sha256, so
    # it re-matches and appends -- no flag needed, nothing overwritten.
    aliased = Aliases(players={"understat": {"Josep Martínez": 2764}})
    second = record_advanced(db, season_id, rows, raw, aliases=aliased, aliases_sha256="a2", listone_snapshot_id=1, **common)
    assert not second.skipped_duplicate and second.snapshot_id == 2 and second.alias == 1
    assert db.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM advanced_stats").fetchone()[0] == 20           # both derivations kept
    assert db.execute("SELECT player_id, match_status FROM v_advanced_current WHERE player_name = 'Josep Martínez'").fetchone() == (2764, "alias")

    # A new listone snapshot: the same again.
    third = record_advanced(db, season_id, rows, raw, aliases=aliased, aliases_sha256="a2", listone_snapshot_id=2, **common)
    assert third.snapshot_id == 3

    # force=True on an identical key re-derives that snapshot in place.
    forced = record_advanced(db, season_id, rows, raw, aliases=aliased, aliases_sha256="a2", listone_snapshot_id=2,
                             force=True, **common)
    assert forced.snapshot_id == 3 and not forced.skipped_duplicate
    assert db.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM advanced_stats").fetchone()[0] == 30
```

In `test_cli_ingest_advanced_rematch_re_derives_without_any_network_call`, the alias change now moves the key, so `--rematch` **appends** rather than re-deriving in place. Replace the four assertions after `after = json.loads(result.stdout)["advanced"][0]` with:

```python
    assert after["ambiguous"] == 0 and after["alias"] == 1 and after["skipped_duplicate"] is False
    assert after["snapshot_id"] == before["snapshot_id"] + 1                   # a new derivation: appended, not overwritten
    assert after["aliases_sha256"] != before["aliases_sha256"]

    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 2
    current = con.execute(
        "SELECT player_id, match_status FROM v_advanced_current WHERE player_name = 'Josep Martínez'").fetchone()
    assert current == (2764, "alias")
    con.close()
```

Add one test at the end of `test_advanced.py`:

```python
def test_cli_ingest_advanced_needs_a_listone(monkeypatch, tmp_path, mcp_fixture_json):
    """The dedupe key names the listone snapshot the match was made against,
    so there is nothing to record before one exists -- exit 3, not a silent
    all-unmatched snapshot."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    (tmp_path / "kb" / "rules").mkdir(parents=True)
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("understat: {}\n")
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    _league(con, mcp_fixture_json)
    con.close()
    respx.post(URL).mock(return_value=httpx.Response(200, json={"success": True, "players": [
        {"id": "1", "player_name": "X", "games": "1", "time": "90", "goals": "0", "assists": "0", "xG": "0", "xA": "0",
         "npg": "0", "npxG": "0", "shots": "0", "key_passes": "0", "yellow_cards": "0", "red_cards": "0",
         "position": "F", "team_title": "Inter", "xGChain": "0", "xGBuildup": "0"}]}))

    async def no_pause(seconds=None):
        pass

    monkeypatch.setattr("fantaclaude.commands.ingest.polite_pause", no_pause)
    result = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20"])
    assert result.exit_code == ExitCode.NOT_READY and "ingest listone" in result.stderr
```

Also run `grep -rn "no effect on its own" core/tests` — the one CLI assertion on the old render hint (if any) changes to the new wording in Step 7: `"applies on the next"`.

- [ ] **Step 6: Run the advanced tests to verify they fail**

Run: `uv run pytest core/tests/test_advanced.py -q`
Expected: FAIL — `record_advanced() got an unexpected keyword argument 'aliases_sha256'`.

- [ ] **Step 7: Key the advanced snapshot on all three inputs**

In `core/src/fantaclaude/ingest/advanced.py`, replace `AdvancedIngestResult` and `record_advanced` (everything from `@dataclass(frozen=True)\nclass AdvancedIngestResult` to the end of the file) with:

```python
@dataclass(frozen=True)
class AdvancedIngestResult:
    snapshot_id: int | None
    season_id: int
    inserted: int
    skipped_duplicate: bool
    matched: int
    alias: int
    ambiguous: int
    unmatched: int
    ambiguous_names: list[dict[str, Any]]
    unresolved_teams: list[str]
    sha256: str
    raw_path: str
    aliases_sha256: str
    listone_snapshot_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "season_id": self.season_id, "inserted": self.inserted,
                "skipped_duplicate": self.skipped_duplicate, "matched": self.matched, "alias": self.alias,
                "ambiguous": self.ambiguous, "unmatched": self.unmatched,
                "ambiguous_names": self.ambiguous_names, "unresolved_teams": self.unresolved_teams,
                "sha256": self.sha256, "raw_path": self.raw_path,
                "aliases_sha256": self.aliases_sha256, "listone_snapshot_id": self.listone_snapshot_id}


def record_advanced(con: duckdb.DuckDBPyConnection, season_id: int, rows: list[AdvancedRow],
                    raw: RawFile, *, candidates: list[Candidate], teams: dict[str, str],
                    aliases: Aliases, aliases_sha256: str, listone_snapshot_id: int,
                    force: bool = False) -> AdvancedIngestResult:
    """One snapshot per distinct *derivation*: the raw bytes, the aliases
    file and the listone snapshot the names were matched against. The same
    three inputs twice is a no-op; a change to any of them appends a new
    snapshot with a fresh match, and v_advanced_current picks the newest
    per season -- so an alias added to kb/rules/aliases.yml, or a listone
    move, applies on the next record without a flag and without touching
    the earlier derivation (nothing is overwritten).

    `force=True` (CLI: `ingest advanced --rematch`) is now only for an
    *identical* key -- a change to the matcher's code, say -- and re-derives
    that same snapshot in place: `advanced_snapshots` is UNIQUE over the
    three inputs, so a second row for them is a constraint violation, not
    just redundant. The raw file's identity (snapshot_id, sha256,
    fetched_at, raw_path) is untouched either way.
    """
    existing = con.execute(
        "SELECT snapshot_id, matched, ambiguous, unmatched FROM advanced_snapshots "
        "WHERE sha256 = ? AND aliases_sha256 = ? AND listone_snapshot_id = ?",
        [raw.sha256, aliases_sha256, listone_snapshot_id]).fetchone()
    if existing is not None and not force:
        alias_count = con.execute(
            "SELECT count(*) FROM advanced_stats WHERE snapshot_id = ? AND match_status = 'alias'",
            [existing[0]]).fetchone()[0]
        return AdvancedIngestResult(existing[0], season_id, 0, True, existing[1], alias_count,
                                    existing[2], existing[3], [], [], raw.sha256, str(raw.path),
                                    aliases_sha256, listone_snapshot_id)
    matcher = Matcher(candidates, aliases.players_for("understat"))
    team_aliases = aliases.teams_for("understat")
    names = {c.player_id: c.name for c in candidates}
    counts: Counter[str] = Counter()
    ambiguous_names: list[dict[str, Any]] = []
    unresolved: set[str] = set()
    records: list[list[Any]] = []
    for r in rows:
        shorts: list[str] = []
        for team in r.teams:
            short = resolve_team(team, teams, team_aliases)
            if short is None:
                unresolved.add(team)          # relegated or foreign in a back season: expected, reported
            else:
                shorts.append(short)
        match = matcher.match(r.player_name, tuple(shorts))
        counts[match.status] += 1
        if match.status == AMBIGUOUS:
            ambiguous_names.append({"name": r.player_name, "teams": list(r.teams),
                                    "candidates": [{"player_id": pid, "name": names[pid]}
                                                   for pid in match.candidates]})
        records.append([None, season_id, r.source_id, r.player_name, list(r.teams), match.player_id,
                        match.status, list(match.candidates), r.games, r.minutes, r.goals, r.assists,
                        r.xg, r.xa, r.npg, r.npxg, r.shots, r.key_passes, r.yellow, r.red,
                        r.xg_chain, r.xg_buildup, r.position, json.dumps(r.raw, ensure_ascii=False)])
    con.begin()
    try:
        if existing is not None:
            snapshot_id = existing[0]          # force=True on an identical key: same row, re-derived in place
            con.execute(
                "UPDATE advanced_snapshots SET matched = ?, ambiguous = ?, unmatched = ? WHERE snapshot_id = ?",
                [counts["matched"], counts["ambiguous"], counts["unmatched"], snapshot_id])
            con.execute("DELETE FROM advanced_stats WHERE snapshot_id = ?", [snapshot_id])
        else:
            snapshot_id = con.execute(
                "INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
                "listone_snapshot_id, row_count, matched, ambiguous, unmatched) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING snapshot_id",
                [season_id, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, aliases_sha256,
                 listone_snapshot_id, len(rows), counts["matched"], counts["ambiguous"],
                 counts["unmatched"]]).fetchone()[0]
        for record in records:
            record[0] = snapshot_id
        con.executemany(
            "INSERT INTO advanced_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?::JSON)", records)
    except Exception:
        con.rollback()
        raise
    con.commit()
    return AdvancedIngestResult(snapshot_id, season_id, len(rows), False, counts["matched"], counts["alias"],
                                counts["ambiguous"], counts["unmatched"], ambiguous_names,
                                sorted(unresolved), raw.sha256, str(raw.path), aliases_sha256, listone_snapshot_id)
```

Update the module docstring's last sentence to: "Names are matched onto the listone by ingest.names; unmatched and ambiguous rows are stored with player_id NULL and reported, never dropped. A snapshot is keyed on the raw bytes, the aliases file and the listone snapshot together, so a changed alias re-matches on the next record."

In `core/src/fantaclaude/commands/ingest.py`, add after `class NotReady`:

```python
def advanced_key(con: duckdb.DuckDBPyConnection, aliases_path: Path) -> tuple[str, int]:
    """The two inputs of an Understat match besides the raw bytes: the
    aliases file's content and the listone snapshot the names are matched
    against. Together with sha256 they key advanced_snapshots."""
    listone = con.execute("SELECT max(snapshot_id) FROM listone_snapshots").fetchone()[0]
    if listone is None:
        raise NotReady("no listone snapshot -- run `fantaclaude ingest listone` first")
    return RawStore.sha256_of(aliases_path), int(listone)
```

and thread it through both callers:

```python
def record_advanced_seasons(con: duckdb.DuckDBPyConnection, raws: dict[int, RawFile],
                            aliases_path: Path) -> list[AdvancedIngestResult]:
    aliases = load_aliases(aliases_path)
    aliases_sha256, listone_snapshot_id = advanced_key(con, aliases_path)
    candidates, teams = load_candidates(con), load_teams(con)
    results = []
    for season_id in sorted(raws):
        loaded_season, rows = load_advanced(raws[season_id].path)
        results.append(record_advanced(con, loaded_season, rows, raws[season_id],
                                       candidates=candidates, teams=teams, aliases=aliases,
                                       aliases_sha256=aliases_sha256, listone_snapshot_id=listone_snapshot_id))
    return results


def rematch_advanced_seasons(con: duckdb.DuckDBPyConnection, store: RawStore, seasons: list[int],
                             aliases_path: Path) -> list[AdvancedIngestResult]:
    """Re-record each requested season's most recent on-disk raw file -- zero
    network. With the full dedupe key a changed alias or listone appends a
    new derivation on its own; `force=True` covers the remaining case, an
    identical key re-derived in place after a matcher change."""
    aliases = load_aliases(aliases_path)
    aliases_sha256, listone_snapshot_id = advanced_key(con, aliases_path)
    candidates, teams = load_candidates(con), load_teams(con)
    results = []
    for season_id in sorted(seasons):
        paths = store.list("advanced", ext="json", label=str(season_id))
        if not paths:
            raise NotReady(f"no advanced/{season_id} raw file on disk yet -- run `fantaclaude ingest advanced` first")
        path = paths[-1]                       # the most recent fetch for this season
        raw = _raw_file_from_disk(path, "advanced")
        loaded_season, rows = load_advanced(path)
        results.append(record_advanced(con, loaded_season, rows, raw, candidates=candidates, teams=teams,
                                       aliases=aliases, aliases_sha256=aliases_sha256,
                                       listone_snapshot_id=listone_snapshot_id, force=True))
    return results
```

In `cli/app.py`'s `ingest_advanced_cmd`, the non-rematch branch calls `record_advanced_seasons`, which can now raise `NotReady` (no listone). Wrap it the way the rematch branch already does:

```python
    with _source_errors():
        raws = run_web(lambda http: fetch_advanced_seasons(http, store, seasons))
        con = connect()
        try:
            apply_schema(con)
            try:
                results = record_advanced_seasons(con, raws, aliases_path())
            except NotReady as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=ExitCode.NOT_READY) from None
        finally:
            con.close()
```

(`NotReady` is imported at the top of that branch as the rematch branch does: `from fantaclaude.commands.ingest import NotReady`.) In `_render_advanced`, replace the two-line hint under `if r["ambiguous"]:` with:

```python
                lines.append(f"  resolve it with an `understat:` alias in kb/rules/aliases.yml -- it applies on the next "
                             f"`fantaclaude ingest advanced --season {r['season_id']} --rematch` (zero network)")
```

In `commands/doctor.py` `_history_checks`, extend the `advanced` detail so the key is visible: change the `detail = "; ".join(...)` for seasons to

```python
        detail = "; ".join(
            f"season {r[1]}: {r[2]} rows, {r[3]} matched, {alias_counts.get(r[0], 0)} alias, "
            f"{r[4]} ambiguous, {r[5]} unmatched" for r in seasons)
        keyed = con.execute("SELECT count(*) FROM advanced_snapshots WHERE aliases_sha256 IS NULL "
                            "AND snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id)").fetchone()[0]
        if keyed:
            detail += f"; {keyed} season(s) recorded before the full dedupe key -- the next `ingest advanced --rematch` re-matches them"
```

- [ ] **Step 8: Run the advanced, doctor and ingest-all tests**

Run: `uv run pytest core/tests/test_advanced.py core/tests/test_doctor.py core/tests/test_ingest_all.py -q`
Expected: all pass (`_ready_workspace` in `test_doctor.py` calls `record_advanced` directly — add `aliases_sha256="a1", listone_snapshot_id=1` to that call and to the one in `test_advanced_check_surfaces_alias_resolved_players`; `test_ingest_all.py` goes through `record_advanced_seasons`, which computes the key itself, but `test_cli_ingest_all_migrates_a_stale_v1_database` hardcodes the version twice — `assert seen_versions[0] == 2` and, six lines later, `... FROM schema_version").fetchone()[0] == 2` — change both literals to `SCHEMA_VERSION`, importing it from `fantaclaude.db.schema`).

- [ ] **Step 9: Lint, full suite, commit**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: ruff silent; MCP 111 passed; core 205 passed (203 + 3 schema tests, and the two replaced record tests collect one fewer case than before).

```bash
git add core/src/fantaclaude/db/schema.py core/src/fantaclaude/ingest/advanced.py core/src/fantaclaude/commands/ingest.py core/src/fantaclaude/commands/doctor.py core/src/fantaclaude/cli/app.py core/tests/test_schema.py core/tests/test_advanced.py core/tests/test_doctor.py core/tests/test_ingest_all.py
git commit -m "feat(db): schema 3 -- the valuation tables, and an advanced dedupe key that covers the aliases file and the listone"
```

---
### Task 2: Scoring under the league's rules, and the D-Factor as data

**Files:**
- Create: `core/src/fantaclaude/model/scoring.py`, `core/src/fantaclaude/model/d_factor.py`, `core/src/fantaclaude/model/d_factor.yml`, `core/tests/test_scoring.py`, `core/tests/test_d_factor.py`

**Interfaces:**
- Consumes: `fantaclaude.model.roles.Role`; the `calculate` payload as stored in `league_settings.payload["calculate"]` (the MCP fixture `calculation_settings.json` is its shape).
- Produces: `BONUS_KEYS`, `ASSIST_KEYS`, `MODIFIER_KEYS`, `D_FACTOR_KEY`, `VOTO_SOURCES`, `ScoringError`, `BonusMalus(goal, penalty_goal, assist, goal_conceded, penalty_saved, penalty_missed, yellow, red, own_goal)` with `from_calculate(calculate)` and `to_dict()`, `Events(goals, pen_scored, assists, goals_conceded, pen_saved, pen_missed, yellow, red, own_goals)` with `__add__` and `scaled(factor)`, `event_points(events, bm) -> float`, `fantavoto(voto, events, bm) -> float`, `voto_sheet(calculate) -> str`, `ModifierStatus(d_factor, d_factor_raw, unknown_active)` with `any_active` and `to_dict()`, `modifier_status(calculate)`; `D_FACTOR_YML`, `D_FACTOR_ROLES`, `TRUE_DEFENDERS`, `COUNTED`, `MIN_TRUE_DEFENDERS`, `DFactorTableError`, `Band(floor, points)`, `DFactorTable(bands, with_goalkeeper, source, verified_on)` with `is_empty`, `points(average)`, `slope(average)`, `to_dict()`, `load_d_factor(path=D_FACTOR_YML)`, `defensive_average(players, *, goalkeeper=None, with_goalkeeper=False) -> float | None`, `d_factor_points(players, table, *, goalkeeper=None) -> float`.

- [ ] **Step 1: Write the failing scoring tests**

Create `core/tests/test_scoring.py`:

```python
import pytest
from fantaclaude.model.scoring import (
    ASSIST_KEYS,
    BONUS_KEYS,
    D_FACTOR_KEY,
    MODIFIER_KEYS,
    VOTO_SOURCES,
    BonusMalus,
    Events,
    ScoringError,
    event_points,
    fantavoto,
    modifier_status,
    voto_sheet,
)


def test_bonus_malus_is_read_from_the_settings_payload(mcp_fixture_json):
    bm = BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))
    assert bm == BonusMalus(goal=3, penalty_goal=3, assist=1, goal_conceded=-1, penalty_saved=3,
                            penalty_missed=-2, yellow=-0.5, red=-1, own_goal=-1)
    assert bm.to_dict()["penalty_missed"] == -2
    assert BONUS_KEYS["goal"] == "bmgs" and ASSIST_KEYS == ("bmass", "bmasf", "bmasg")


def test_fantavoto_is_hand_computed_under_the_league_rules(mcp_fixture_json):
    bm = BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))
    # an open-play goal, a penalty goal (Gf excludes it, Rf carries it), an assist, a booking
    assert fantavoto(6.5, Events(goals=1, pen_scored=1, assists=1, yellow=1), bm) == pytest.approx(13.0)
    # a goalkeeper: two conceded, one penalty saved
    assert fantavoto(6.0, Events(goals_conceded=2, pen_saved=1), bm) == pytest.approx(7.0)
    assert event_points(Events(pen_missed=1, own_goals=1, red=1), bm) == pytest.approx(-4.0)
    assert event_points(Events(), bm) == 0.0


def test_scoring_is_league_configurable(mcp_fixture_json):
    """The same event counts under two different league_settings must yield
    two different fantavoti -- the test that would catch a stored fantavoto
    silently baking in fantacalcio.it's defaults."""
    calculate = mcp_fixture_json("calculation_settings")
    other = mcp_fixture_json("calculation_settings")
    other["bnMls"]["bmgs"] = [4, 4]
    other["bnMls"]["bmog"] = [-2, -2]
    events = Events(goals=1, own_goals=1)
    a = fantavoto(6.0, events, BonusMalus.from_calculate(calculate))
    b = fantavoto(6.0, events, BonusMalus.from_calculate(other))
    assert a == pytest.approx(8.0) and b == pytest.approx(8.0)                 # +1 on the goal, -1 on the own goal: they cancel
    goal_only = Events(goals=1)
    assert fantavoto(6.0, goal_only, BonusMalus.from_calculate(calculate)) == pytest.approx(9.0)
    assert fantavoto(6.0, goal_only, BonusMalus.from_calculate(other)) == pytest.approx(10.0)


def test_a_pair_whose_values_differ_is_refused(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmgs"] = [3, 2]
    with pytest.raises(ScoringError, match="bmgs"):
        BonusMalus.from_calculate(calculate)
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmasf"] = [2, 2]
    with pytest.raises(ScoringError, match="assist"):
        BonusMalus.from_calculate(calculate)
    calculate = mcp_fixture_json("calculation_settings")
    del calculate["bnMls"]["bmrc"]
    with pytest.raises(ScoringError, match="bmrc"):
        BonusMalus.from_calculate(calculate)
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmyc"] = "half"
    with pytest.raises(ScoringError, match="bmyc"):
        BonusMalus.from_calculate(calculate)


def test_a_scalar_bonus_is_accepted_too(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmgs"] = 3
    assert BonusMalus.from_calculate(calculate).goal == 3.0


def test_events_add_and_scale():
    total = Events(goals=1, assists=2) + Events(goals=2, yellow=1)
    assert total == Events(goals=3, assists=2, yellow=1)
    assert Events(goals=3, assists=2).scaled(0.5) == Events(goals=1.5, assists=1.0)


def test_voto_sheet_follows_sourcev(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    assert calculate["sourcev"] == 1 and voto_sheet(calculate) == "Fantacalcio"
    assert VOTO_SOURCES == {1: "Fantacalcio", 2: "Statistico", 3: "Italia"}
    calculate["sourcev"] = 9
    with pytest.raises(ScoringError, match="sourcev"):
        voto_sheet(calculate)
    calculate["sourcev"] = True
    with pytest.raises(ScoringError):
        voto_sheet(calculate)


def test_modifier_status_reads_the_nine_flags(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    assert MODIFIER_KEYS == ("stbdf", "smodg", "smodd", "smodm", "skodm", "smodf", "smodl", "smodp", "smodcp")
    status = modifier_status(calculate)
    assert not status.d_factor and status.unknown_active == () and not status.any_active
    assert status.to_dict() == {"d_factor": False, "d_factor_raw": None, "unknown_active": []}

    calculate[D_FACTOR_KEY] = 1
    status = modifier_status(calculate)
    assert status.d_factor and status.d_factor_raw == 1 and status.unknown_active == () and status.any_active

    calculate["smodf"] = {"on": True}
    status = modifier_status(calculate)
    assert status.d_factor and status.unknown_active == ("smodf",)

    calculate[D_FACTOR_KEY] = 0                              # a falsy value reads as off
    calculate["smodf"] = None
    assert not modifier_status(calculate).any_active
```

- [ ] **Step 2: Run the scoring tests to verify they fail**

Run: `uv run pytest core/tests/test_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.model.scoring`.

- [ ] **Step 3: Write the scoring module**

Create `core/src/fantaclaude/model/scoring.py`:

```python
"""Scoring under this league's rules: the fantavoto from the base voto and
the event counts, the voto source, and the modifier flags.

Everything here is read from the `settings/calculate` payload of the
league_settings snapshot in force, never typed. `bnMls` carries each
bonus/malus as a two-element list whose meaning is unverified -- every
pair observed so far is equal (`bmgs [3, 3]`, `bmyc [-0.5, -0.5]`, ...) --
so a pair whose values differ is refused, naming the key: the first league
to set them apart fails loud instead of getting a silently chosen index.
The three assist keys (bmass, bmasf, bmasg) must agree with each other for
the same reason: the voti workbook has one `Ass` column.

The workbook's `Gf` excludes penalty goals (observed 2026-08-29: of 258
rows with a penalty scored, 223 carry Gf = 0), so a penalty goal is scored
through penalty_goal x pen_scored and never double-counted through goal.
`Gs` is non-zero only on goalkeeper rows, so goal_conceded x goals_conceded
needs no role gate. Keys the models do not name (bmcsh, bmycsv, bmcg, bmdg,
bmeg, motm -- all zero in every payload seen) stay raw.

`sourcev` selects the voto source. The workbook's sheets are, in order,
Fantacalcio, Statistico, Italia -- the order the public voti page lists its
three sources -- and `sourcev` is 1 in the observed league, so 1 ->
Fantacalcio is the working hypothesis; `doctor` prints the resolved sheet
so the account holder can check it against the league's own calcolo page.
Any other value is refused.

The modifier fields (stbdf, smod*, skodm) are all null in the observed
league. `smodd` is read as the Mantra D-Factor (the defence modifier -- the
only one the Mantra regolamento offers; "d" for difesa); any *other* key
turning non-null is an unknown modifier, and the projection refuses to run
rather than price a rule it does not model. A falsy value (None, 0, false,
an empty container) reads as off.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

BONUS_KEYS: dict[str, str] = {
    "goal": "bmgs", "penalty_goal": "bmpsc", "assist": "bmass", "goal_conceded": "bmgc",
    "penalty_saved": "bmpsa", "penalty_missed": "bmpns", "yellow": "bmyc", "red": "bmrc",
    "own_goal": "bmog",
}
ASSIST_KEYS = ("bmass", "bmasf", "bmasg")
MODIFIER_KEYS = ("stbdf", "smodg", "smodd", "smodm", "skodm", "smodf", "smodl", "smodp", "smodcp")
D_FACTOR_KEY = "smodd"
VOTO_SOURCES: dict[int, str] = {1: "Fantacalcio", 2: "Statistico", 3: "Italia"}


class ScoringError(ValueError):
    """The settings payload does not carry a scoring table this module can read."""


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pair(calculate: dict[str, Any], key: str) -> float:
    bn = calculate.get("bnMls") or {}
    if key not in bn:
        raise ScoringError(f"bnMls lacks {key}")
    value = bn[key]
    if _number(value):
        return float(value)
    if not isinstance(value, list) or len(value) != 2 or not all(_number(v) for v in value):
        raise ScoringError(f"bnMls.{key} is neither a number nor a pair of numbers: {value!r}")
    if value[0] != value[1]:
        raise ScoringError(f"bnMls.{key} = {value!r}: the two values differ and the pair's meaning is unverified")
    return float(value[0])


@dataclass(frozen=True)
class BonusMalus:
    goal: float
    penalty_goal: float
    assist: float
    goal_conceded: float
    penalty_saved: float
    penalty_missed: float
    yellow: float
    red: float
    own_goal: float

    @classmethod
    def from_calculate(cls, calculate: dict[str, Any]) -> BonusMalus:
        values = {name: _pair(calculate, key) for name, key in BONUS_KEYS.items()}
        present = calculate.get("bnMls") or {}
        assists = {key: _pair(calculate, key) for key in ASSIST_KEYS if key in present}
        if len(set(assists.values())) > 1:
            raise ScoringError(f"the assist keys disagree ({assists}) and the workbook has one Ass column")
        return cls(**values)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class Events:
    goals: float = 0.0
    pen_scored: float = 0.0
    assists: float = 0.0
    goals_conceded: float = 0.0
    pen_saved: float = 0.0
    pen_missed: float = 0.0
    yellow: float = 0.0
    red: float = 0.0
    own_goals: float = 0.0

    def __add__(self, other: Events) -> Events:
        return Events(**{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)})

    def scaled(self, factor: float) -> Events:
        return Events(**{f.name: getattr(self, f.name) * factor for f in fields(self)})

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def event_points(events: Events, bm: BonusMalus) -> float:
    return (bm.goal * events.goals + bm.penalty_goal * events.pen_scored + bm.assist * events.assists
            + bm.goal_conceded * events.goals_conceded + bm.penalty_saved * events.pen_saved
            + bm.penalty_missed * events.pen_missed + bm.yellow * events.yellow + bm.red * events.red
            + bm.own_goal * events.own_goals)


def fantavoto(voto: float, events: Events, bm: BonusMalus) -> float:
    return voto + event_points(events, bm)


def voto_sheet(calculate: dict[str, Any]) -> str:
    source = calculate.get("sourcev")
    if not _number(source) or source not in VOTO_SOURCES:
        raise ScoringError(f"calculate.sourcev = {source!r} is not a voto source this code knows ({VOTO_SOURCES})")
    return VOTO_SOURCES[int(source)]


@dataclass(frozen=True)
class ModifierStatus:
    d_factor: bool
    d_factor_raw: Any
    unknown_active: tuple[str, ...]

    @property
    def any_active(self) -> bool:
        return self.d_factor or bool(self.unknown_active)

    def to_dict(self) -> dict[str, Any]:
        return {"d_factor": self.d_factor, "d_factor_raw": self.d_factor_raw,
                "unknown_active": list(self.unknown_active)}


def modifier_status(calculate: dict[str, Any]) -> ModifierStatus:
    active = {key: calculate.get(key) for key in MODIFIER_KEYS if calculate.get(key)}
    d_factor = D_FACTOR_KEY in active
    unknown = tuple(key for key in MODIFIER_KEYS if key in active and key != D_FACTOR_KEY)
    return ModifierStatus(d_factor, active.get(D_FACTOR_KEY), unknown)
```

- [ ] **Step 4: Run the scoring tests to verify they pass**

Run: `uv run pytest core/tests/test_scoring.py -q`
Expected: 8 passed.

- [ ] **Step 5: Write the failing D-Factor tests**

Create `core/tests/test_d_factor.py`:

```python
from datetime import date

import pytest
from fantaclaude.model.d_factor import (
    COUNTED,
    D_FACTOR_ROLES,
    D_FACTOR_YML,
    MIN_TRUE_DEFENDERS,
    TRUE_DEFENDERS,
    Band,
    DFactorTable,
    DFactorTableError,
    d_factor_points,
    defensive_average,
    load_d_factor,
)
from fantaclaude.model.roles import Role

R = frozenset
TABLE = DFactorTable(bands=(Band(7.0, 6.0), Band(6.5, 3.0), Band(6.0, 1.0), Band(5.5, 0.0), Band(0.0, -1.0)),
                     with_goalkeeper=False, source="synthetic", verified_on=date(2026, 8, 29))


def test_the_shipped_table_is_empty_and_says_so():
    """League data, not a constant: the regolamento does not publish the
    thresholds, so the file ships empty and rank refuses while the D-Factor
    is active (Task 9)."""
    table = load_d_factor(D_FACTOR_YML)
    assert table.is_empty and table.verified_on is None and table.points(7.5) == 0.0
    text = D_FACTOR_YML.read_text(encoding="utf-8")
    assert "verified_on: null" in text and "bands: []" in text


def test_a_table_is_loaded_sorted_and_validated(tmp_path):
    path = tmp_path / "d.yml"
    path.write_text("source: 'Leghe > Impostazioni > Calcolo > D-Factor (2026-09-01)'\nverified_on: 2026-09-01\n"
                    "with_goalkeeper: true\nbands:\n  - {min: 6.0, points: 1}\n  - {min: 7.0, points: 6}\n  - {min: 6.5, points: 3}\n")
    table = load_d_factor(path)
    assert [b.floor for b in table.bands] == [7.0, 6.5, 6.0] and table.with_goalkeeper
    assert table.points(7.2) == 6 and table.points(6.5) == 3 and table.points(6.49) == 1 and table.points(5.0) == 0.0
    assert table.to_dict()["bands"][0] == {"min": 7.0, "points": 6.0}
    assert table.slope(6.1) == pytest.approx((3 - 1) / 0.5)                  # from the 6.0 band up to the 6.5 band
    assert table.slope(7.5) == 0.0 and TABLE.slope(6.1) == pytest.approx(4.0)

    for bad in ("bands: 3\n", "bands:\n  - {min: 6, points: x}\n", "bands:\n  - {min: 6, points: 1}\n  - {min: 6, points: 2}\n",
                "bands:\n  - {min: 6, points: 1}\nverified_on: null\n", "- a list\n"):
        path.write_text(bad)
        with pytest.raises(DFactorTableError):
            load_d_factor(path)


def test_defensive_average_takes_the_best_five_with_three_true_defenders():
    assert D_FACTOR_ROLES == {Role.Dc, Role.B, Role.Dd, Role.Ds, Role.E, Role.M} and TRUE_DEFENDERS < D_FACTOR_ROLES
    assert (COUNTED, MIN_TRUE_DEFENDERS) == (5, 3)
    lineup = [(R({Role.Por}), 7.5), (R({Role.Dc}), 6.0), (R({Role.Dc}), 6.5), (R({Role.Ds, Role.E}), 5.5),
              (R({Role.E}), 7.0), (R({Role.M}), 7.0), (R({Role.E, Role.W}), 6.5), (R({Role.C}), 8.0),
              (R({Role.T}), 6.0), (R({Role.A}), 7.5), (R({Role.Pc}), 6.0)]
    # The five best among the D-Factor roles would be E 7.0, M 7.0, Dc 6.5, E/W 6.5, Dc 6.0 -- only two true
    # defenders, so the rule takes the best three true defenders (6.5, 6.0, 5.5) and the best two of the rest (7.0, 7.0).
    assert defensive_average(lineup) == pytest.approx((6.5 + 6.0 + 5.5 + 7.0 + 7.0) / 5)
    assert defensive_average(lineup, goalkeeper=7.5, with_goalkeeper=True) == pytest.approx((6.5 + 6.0 + 5.5 + 7.0 + 7.0 + 7.5) / 6)
    assert defensive_average(lineup, with_goalkeeper=True) is None            # 5+1 without a goalkeeper vote
    assert defensive_average(lineup[:5]) is None                              # four eligible: fewer than five
    two_defenders = [(R({Role.Dc}), 6.0), (R({Role.Dc}), 6.5), (R({Role.E}), 7.0), (R({Role.M}), 7.0), (R({Role.E}), 6.5), (R({Role.M}), 6.0)]
    assert defensive_average(two_defenders) is None                           # fewer than three true defenders
    assert d_factor_points(lineup, TABLE) == 1.0 and d_factor_points(two_defenders, TABLE) == 0.0   # 6.4 sits in the 6.0 band
    assert d_factor_points(lineup, DFactorTable((), False, None, None)) == 0.0
```

- [ ] **Step 6: Run the D-Factor tests to verify they fail**

Run: `uv run pytest core/tests/test_d_factor.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.model.d_factor`.

- [ ] **Step 7: Write the D-Factor table and module**

Create `core/src/fantaclaude/model/d_factor.yml`:

```yaml
# The Mantra D-Factor table -- LEAGUE DATA, not a constant.
#
# fantacalcio.it's Mantra regolamento (https://www.fantacalcio.it/regolamenti/sistema-mantra,
# read 2026-08-29) defines the mechanism -- the five best voti among Dc, B, Dd,
# Ds, E, M with at least three true defenders (Dc, B, Dd, Ds), optionally the
# goalkeeper as a sixth ("5+1"), averaged and mapped to points -- but publishes
# no thresholds: the leghe-private regolamento says the platform "proposes the
# most common version" and lets each league customise the output. The table
# is therefore read off THIS league's settings page (Leghe > la lega >
# Impostazioni > Calcolo > Modificatori/D-Factor) by the account holder, once
# the admin activates it, and transcribed here with the date. Until then it
# is empty, and `fantaclaude rank` refuses to run while the D-Factor is
# active (settings/calculate.smodd non-null) and this list is empty.
#
# Shape when filled (the numbers below are NOT the league's -- illustrative only):
#   bands:
#     - {min: 7.0, points: 6}     # average voto >= 7.0 -> +6
#     - {min: 6.5, points: 3}
#   with_goalkeeper: false        # true for the "5+1" variant
#   source: "Leghe > Impostazioni > Calcolo > D-Factor"
#   verified_on: 2026-09-01
source: null
verified_on: null
with_goalkeeper: false
bands: []
```

Create `core/src/fantaclaude/model/d_factor.py`:

```python
"""The Mantra D-Factor: the defence modifier, as data plus a pure function.

Mechanism (fantacalcio.it, "Regolamento sistema Mantra", read 2026-08-29):
the five defensive men of a lineup are the five best voti among the
players with a role in Dc, B, Dd, Ds, E, M, provided at least three of the
five are true defenders (Dc, B, Dd, Ds); a "5+1" variant adds the
goalkeeper; the average of those voti maps to points for the whole team.
The thresholds are NOT published -- the regolamento says the platform
"proposes the most common version" and lets a league customise the output
-- so they are league data, read off the league's own settings page, kept
in d_factor.yml with a source and a date. The file ships empty; while the
D-Factor is active and the table is empty, `rank` refuses.

The best five under the "at least three true defenders" rule are the best
three true defenders plus the best two of the remaining eligible players:
for a sum with one cardinality constraint the greedy choice is the optimum.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .roles import Role

D_FACTOR_YML = Path(__file__).with_name("d_factor.yml")
D_FACTOR_ROLES: frozenset[Role] = frozenset({Role.Dc, Role.B, Role.Dd, Role.Ds, Role.E, Role.M})
TRUE_DEFENDERS: frozenset[Role] = frozenset({Role.Dc, Role.B, Role.Dd, Role.Ds})
COUNTED = 5
MIN_TRUE_DEFENDERS = 3


class DFactorTableError(ValueError):
    """d_factor.yml does not describe a table this module can apply."""


@dataclass(frozen=True)
class Band:
    floor: float           # applies when the average is >= floor
    points: float


@dataclass(frozen=True)
class DFactorTable:
    bands: tuple[Band, ...]          # descending by floor
    with_goalkeeper: bool
    source: str | None
    verified_on: date | None

    @property
    def is_empty(self) -> bool:
        return not self.bands

    def points(self, average: float) -> float:
        for band in self.bands:
            if average >= band.floor:
                return band.points
        return 0.0

    def slope(self, average: float) -> float:
        """Points per unit of average voto around `average`: the rise to the
        next band up, over the distance to it -- the gradient the projection
        uses for a per-player uplift, since a step read at one point would
        say most defenders are worth nothing to the modifier."""
        above = [b for b in self.bands if b.floor > average]
        if not above:
            return 0.0
        nxt = min(above, key=lambda b: b.floor)
        floor_here = max((b.floor for b in self.bands if b.floor <= average), default=average)
        span = nxt.floor - floor_here
        return (nxt.points - self.points(average)) / span if span > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"bands": [{"min": b.floor, "points": b.points} for b in self.bands],
                "with_goalkeeper": self.with_goalkeeper, "source": self.source,
                "verified_on": self.verified_on.isoformat() if self.verified_on else None}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_d_factor(path: Path = D_FACTOR_YML) -> DFactorTable:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DFactorTableError(f"{path}: the top level must be a mapping")
    raw_bands = data.get("bands")
    if raw_bands is None:
        raw_bands = []
    if not isinstance(raw_bands, list):
        raise DFactorTableError(f"{path}: bands must be a list")
    bands: list[Band] = []
    for entry in raw_bands:
        if not isinstance(entry, dict) or not _number(entry.get("min")) or not _number(entry.get("points")):
            raise DFactorTableError(f"{path}: every band is {{min: <average>, points: <points>}}, got {entry!r}")
        bands.append(Band(float(entry["min"]), float(entry["points"])))
    bands.sort(key=lambda b: -b.floor)
    floors = [b.floor for b in bands]
    if len(set(floors)) != len(floors):
        raise DFactorTableError(f"{path}: two bands share the same min")
    verified_on = data.get("verified_on")
    if isinstance(verified_on, datetime):
        verified_on = verified_on.date()
    if verified_on is not None and not isinstance(verified_on, date):
        raise DFactorTableError(f"{path}: verified_on must be an ISO date or null")
    source = data.get("source")
    if source is not None and not isinstance(source, str):
        raise DFactorTableError(f"{path}: source must be text or null")
    if bands and (verified_on is None or not source):
        raise DFactorTableError(f"{path}: a filled table needs source and verified_on")
    with_goalkeeper = data.get("with_goalkeeper", False)
    if not isinstance(with_goalkeeper, bool):
        raise DFactorTableError(f"{path}: with_goalkeeper must be true or false")
    return DFactorTable(tuple(bands), with_goalkeeper, source, verified_on)


def defensive_average(players: Sequence[tuple[frozenset[Role], float]], *, goalkeeper: float | None = None,
                      with_goalkeeper: bool = False) -> float | None:
    """The average the D-Factor is computed on, or None when the lineup does
    not qualify (fewer than five eligible players, fewer than three true
    defenders among them, or a 5+1 table without a goalkeeper vote)."""
    eligible = sorted(((i, roles, voto) for i, (roles, voto) in enumerate(players) if roles & D_FACTOR_ROLES),
                      key=lambda item: -item[2])
    if len(eligible) < COUNTED:
        return None
    defenders = [item for item in eligible if item[1] & TRUE_DEFENDERS]
    if len(defenders) < MIN_TRUE_DEFENDERS:
        return None
    chosen = defenders[:MIN_TRUE_DEFENDERS]
    taken = {item[0] for item in chosen}
    chosen += [item for item in eligible if item[0] not in taken][:COUNTED - MIN_TRUE_DEFENDERS]
    votes = [item[2] for item in chosen]
    if with_goalkeeper:
        if goalkeeper is None:
            return None
        votes.append(goalkeeper)
    return sum(votes) / len(votes)


def d_factor_points(players: Sequence[tuple[frozenset[Role], float]], table: DFactorTable, *,
                    goalkeeper: float | None = None) -> float:
    if table.is_empty:
        return 0.0
    average = defensive_average(players, goalkeeper=goalkeeper, with_goalkeeper=table.with_goalkeeper)
    return 0.0 if average is None else table.points(average)
```

- [ ] **Step 8: Run the D-Factor tests, lint, full suite, commit**

Run: `uv run pytest core/tests/test_d_factor.py core/tests/test_scoring.py -q && uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: 11 passed in the two files; ruff silent; core 216 passed.

```bash
git add core/src/fantaclaude/model/scoring.py core/src/fantaclaude/model/d_factor.py core/src/fantaclaude/model/d_factor.yml core/tests/test_scoring.py core/tests/test_d_factor.py
git commit -m "feat(model): the fantavoto under the league's own bonus/malus, the voto source, the modifier flags, and the D-Factor as data"
```

---
### Task 3: Demand — what each role class is worth to a roster, from the module table

**Files:**
- Create: `core/src/fantaclaude/model/demand.py`, `core/tests/test_demand.py`

**Interfaces:**
- Consumes: `fantaclaude.model.modules.load_modules`, `Module`, `Slot`; `fantaclaude.model.roles.Role`.
- Produces: `ROLE_CLASSES: tuple[str, ...]` (`"Por", "Dd", "Ds", "Dc", "E", "M", "C", "W", "T", "A", "Pc"`), `role_class(role) -> str` (`B -> "Dc"`), `player_classes(roles) -> frozenset[str]`, `module_demand(modules=None) -> dict[str, dict[str, float]]` (module code → class → fractional natural slots), `rank_weights(demand_by_module, *, max_rank, bench_weight, bench_decay=0.5, bench_slots=1, targets=None, target_weight=0.8) -> dict[str, tuple[float, ...]]` (a class has as many ranks as the peak demand of any module, rounded up, plus `bench_slots`; a target extends them; never more than `max_rank`), `hard_minimums(modules=None) -> dict[str, int]`, `pin_class(roles, weights) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_demand.py`:

```python
from itertools import pairwise

import pytest
from fantaclaude.model.demand import (
    ROLE_CLASSES,
    hard_minimums,
    module_demand,
    pin_class,
    player_classes,
    rank_weights,
    role_class,
)
from fantaclaude.model.modules import load_modules
from fantaclaude.model.roles import Role

R = frozenset


def test_role_classes_fold_b_into_dc():
    assert ROLE_CLASSES == ("Por", "Dd", "Ds", "Dc", "E", "M", "C", "W", "T", "A", "Pc")
    assert role_class(Role.B) == "Dc" and role_class(Role.Pc) == "Pc"
    assert player_classes(R({Role.B, Role.Ds, Role.E})) == {"Dc", "Ds", "E"}


def test_every_module_spreads_eleven_units_of_demand():
    demand = module_demand(load_modules())
    assert set(demand) == set(load_modules())
    for code, by_class in demand.items():
        assert sum(by_class.values()) == pytest.approx(11.0), code
        assert set(by_class) <= set(ROLE_CLASSES)
    # 3-4-3: Por 1; Dc, Dc, Dc/B -> 3; E, E -> 2; M/C -> 0.5 M + 0.5 C; C -> 1; W/A x2 -> 1 W + 1 A; A/Pc -> 0.5 + 0.5
    assert demand["343"] == pytest.approx({"Por": 1, "Dc": 3, "E": 2, "M": 0.5, "C": 1.5, "W": 1, "A": 1.5, "Pc": 0.5})
    assert demand["433"]["Dc"] == 2 and demand["433"]["Ds"] == 1 and demand["433"]["Dd"] == 1
    assert "E" not in demand["433"]


def test_rank_weights_follow_module_coverage_and_floor_at_the_bench():
    weights = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1)
    assert set(weights) == set(ROLE_CLASSES)
    for cls, w in weights.items():
        assert all(a >= b for a, b in pairwise(w)), cls                 # non-increasing in rank
        assert min(w) > 0 and max(w) <= 1.0
    # ranks: the peak demand of any module, rounded up, plus one bench slot
    assert {cls: len(w) for cls, w in weights.items()} == {"Por": 2, "Dd": 2, "Ds": 2, "Dc": 4, "E": 3, "M": 3, "C": 3,
                                                           "W": 3, "T": 3, "A": 3, "Pc": 2}
    assert weights["Por"] == (1.0, 0.1)
    assert weights["Dc"] == pytest.approx((1.0, 1.0, 5 / 11, 0.1))          # a third Dc in the five back-three modules
    assert weights["Ds"] == pytest.approx((6 / 11, 0.1))                    # a Ds slot in the six back-four modules
    # Pc: two A/Pc slots (a whole unit) in 3-4-1-2, 3-5-2, 4-4-2; A/Pc plus a third of T/A/Pc in 4-3-1-2; half a unit elsewhere
    assert weights["Pc"][0] == pytest.approx((3 * 1.0 + (0.5 + 1 / 3) + 7 * 0.5) / 11)
    # W: a whole unit in six modules and half a unit in three; the second rank's coverage (half a slot in 4-1-4-1) is
    # below the floor, so it is the first bench rank, and the third decays
    assert weights["W"] == pytest.approx(((6 + 3 * 0.5) / 11, 0.1, 0.05))
    assert rank_weights(module_demand(load_modules()), max_rank=2, bench_weight=0.1)["Dc"] == (1.0, 1.0)


def test_a_target_raises_the_weights_it_names_and_nothing_else():
    base = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1)
    nudged = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1,
                          targets={"W": 3, "Por": 2}, target_weight=0.8)
    assert nudged["W"] == (0.8, 0.8, 0.8) and nudged["Por"] == (1.0, 0.8)
    assert nudged["Dc"] == base["Dc"] and nudged["Pc"] == base["Pc"]
    extended = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1, targets={"Pc": 4})
    assert extended["Pc"] == (0.8, 0.8, 0.8, 0.8)                            # a target extends the ranks to reach it
    with pytest.raises(ValueError, match="Xy"):
        rank_weights(module_demand(load_modules()), max_rank=4, bench_weight=0.1, targets={"Xy": 1})


def test_hard_minimums_are_the_slots_every_module_needs_from_one_class():
    assert hard_minimums(load_modules()) == {"Por": 1, "Dc": 2}


def test_pin_class_takes_the_class_with_the_most_demand():
    weights = rank_weights(module_demand(load_modules()), max_rank=4, bench_weight=0.1)
    assert pin_class(R({Role.Pc}), weights) == "Pc"
    assert pin_class(R({Role.Ds, Role.E}), weights) == "E"                  # E: ~1 slot per module; Ds: 6 of 11
    assert pin_class(R({Role.B, Role.Ds, Role.E}), weights) == "Dc"         # B folds into Dc, and Dc draws two full slots everywhere
    assert pin_class(R({Role.B}), weights) == "Dc"
    with pytest.raises(ValueError):
        pin_class(R(), weights)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_demand.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.model.demand`.

- [ ] **Step 3: Write the demand module**

Create `core/src/fantaclaude/model/demand.py`:

```python
"""What each Mantra role class is worth to a roster, derived from the modules.

The pricing DP pins every pool player to one role class and values the k-th
player of a class by how much of a starting slot he can expect: a weight in
[0, 1] per rank, read off modules.yml -- never typed. In each module every
slot's natural roles share one unit of demand equally (an "A/Pc" slot is
half an A and half a Pc; "Dc/B" is a whole Dc, since B is folded into the
Dc class -- it is natural only beside Dc and never appears alone in the
listone). The k-th player of class r then gets, in module m, whatever
fraction of m's demand for r is left after k-1 players took theirs, and
his weight is the average over the eleven modules: two Dc are a full slot
in every module, a third Dc is a slot in the five back-three modules
(5/11), a fourth is bench.

How many ranks a class has is demand too: the most slots any module draws
from the class, rounded up, plus `bench_slots` -- a fifth Pc is not a
roster slot anyone prices. A bench rank's floor is `bench_weight` (the
chance to start through injuries and rotation), decaying by `bench_decay`
for every further bench rank: the first backup plays sometimes, the third
never. A target in preferences.yml raises the weights of the ranks it
names to `target_weight` (and extends the ranks to reach it): a soft prior
the optimiser may still depart from, never a bound (spec, "Live
adjustments": `target`). Hard minimums are the slots every module needs
from one class alone (Por 1, Dc 2 -- no other role fills a "Dc" slot even
adapted): a roster without them can field nothing, so the pricing DP treats
a completion without them as worth -inf, which is what drives the last
needed Dc's price to the credits available.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from .modules import Module, load_modules
from .roles import Role

ROLE_CLASSES: tuple[str, ...] = ("Por", "Dd", "Ds", "Dc", "E", "M", "C", "W", "T", "A", "Pc")
_MERGED: dict[Role, str] = {Role.B: "Dc"}


def role_class(role: Role) -> str:
    return _MERGED.get(role, role.value)


def player_classes(roles: frozenset[Role]) -> frozenset[str]:
    return frozenset(role_class(r) for r in roles)


def module_demand(modules: Mapping[str, Module] | None = None) -> dict[str, dict[str, float]]:
    """Module code -> role class -> the natural slots it draws, fractional
    for a composite slot; every module sums to eleven."""
    modules = load_modules() if modules is None else modules
    demand: dict[str, dict[str, float]] = {}
    for code, module in modules.items():
        by_class: dict[str, float] = {}
        for slot in module.slots:
            classes = player_classes(slot.natural)
            for cls in classes:
                by_class[cls] = by_class.get(cls, 0.0) + 1.0 / len(classes)
        demand[code] = by_class
    return demand


def rank_weights(demand_by_module: Mapping[str, Mapping[str, float]], *, max_rank: int, bench_weight: float,
                 bench_decay: float = 0.5, bench_slots: int = 1, targets: Mapping[str, int] | None = None,
                 target_weight: float = 0.8) -> dict[str, tuple[float, ...]]:
    """Class -> weight of the k-th player of that class, k = 1 .. the ranks
    the class has (the peak demand of any module, rounded up, plus
    bench_slots; a target extends them; never more than max_rank)."""
    unknown = sorted(set(targets or {}) - set(ROLE_CLASSES))
    if unknown:
        raise ValueError(f"target_composition names classes that do not exist: {unknown}; choose from {ROLE_CLASSES}")
    n = len(demand_by_module)
    weights: dict[str, tuple[float, ...]] = {}
    for cls in ROLE_CLASSES:
        peak = max((by_class.get(cls, 0.0) for by_class in demand_by_module.values()), default=0.0)
        ranks = math.ceil(peak - 1e-9) + bench_slots
        if targets:
            ranks = max(ranks, targets.get(cls, 0))
        ranks = max(1, min(max_rank, ranks))
        coverage = [sum(min(1.0, max(0.0, by_class.get(cls, 0.0) - (k - 1))) for by_class in demand_by_module.values()) / n
                    if n else 0.0 for k in range(1, ranks + 1)]
        first_bench = next((k for k, c in enumerate(coverage, 1) if c < bench_weight), None)
        out: list[float] = []
        for k, weight in enumerate(coverage, 1):
            if first_bench is not None and k >= first_bench:
                weight = max(weight, bench_weight * bench_decay ** (k - first_bench))
            if targets and k <= targets.get(cls, 0):
                weight = max(weight, target_weight)
            out.append(weight)
        weights[cls] = tuple(out)
    return weights


def hard_minimums(modules: Mapping[str, Module] | None = None) -> dict[str, int]:
    """Class -> slots that every module fills from that class and no other."""
    modules = load_modules() if modules is None else modules
    minimums: dict[str, int] = {}
    for cls in ROLE_CLASSES:
        exclusive = [sum(1 for slot in module.slots if player_classes(slot.natural) == {cls}) for module in modules.values()]
        if exclusive and min(exclusive) > 0:
            minimums[cls] = min(exclusive)
    return minimums


def pin_class(roles: frozenset[Role], weights: Mapping[str, tuple[float, ...]]) -> str:
    """The one class a multi-role player is valued under when the pool is
    priced: the class with the most demand across the modules, ties broken
    by ROLE_CLASSES order. The exact matching for the player on the block
    is the auction's job (spec, "Where this is an approximation")."""
    classes = player_classes(roles)
    if not classes:
        raise ValueError("a player carries at least one role")
    return max(sorted(classes, key=ROLE_CLASSES.index), key=lambda cls: sum(weights[cls]))
```

Note `max(sorted(...), key=...)` returns the *first* maximum in `ROLE_CLASSES` order, which is the tie-break the docstring promises.

- [ ] **Step 4: Run the tests, lint, full suite, commit**

Run: `uv run pytest core/tests/test_demand.py -q && uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: 6 passed; ruff silent; core 222 passed. If `test_pin_class_takes_the_class_with_the_most_demand` fails on `Ds;E`, print `sum(weights["E"])` and `sum(weights["Ds"])` — the assertion encodes the module table's arithmetic (E draws about one slot per module, Ds one in the six back-four modules), and a different answer means `module_demand` split a composite slot wrongly, not that the expectation is wrong.

```bash
git add core/src/fantaclaude/model/demand.py core/tests/test_demand.py
git commit -m "feat(model): per-class demand weights, hard minimums and role pinning derived from the module table"
```

---
### Task 4: Knowledge-base contracts Phase 1 reads — player notes and participant dossiers

**Files:**
- Create: `core/src/fantaclaude/kb/notes.py`, `core/src/fantaclaude/kb/participants.py`, `core/tests/test_kb_notes.py`, `core/tests/test_kb_participants.py`
- Modify: `core/src/fantaclaude/kb/audit.py:85-106`, `kb/README.md`

**Interfaces:**
- Consumes: `fantaclaude.kb.audit.parse_front_matter`, `FrontMatter`, `FrontMatterError`; `fantaclaude.kb.profiles.team_slug`; `fantaclaude.model.demand.ROLE_CLASSES`; `fantaclaude.league.settings.EMAIL_PATTERN`.
- Produces: `DEPTHS = ("starter", "contested", "cover", "out")`, `NoteError`, `PlayerNote(path, player_id, name, team_short, depth, availability, prior_fantamedia, front_matter)`, `load_note(path)`, `load_player_notes(kb_dir) -> dict[int, PlayerNote]` (a duplicate `player_id` raises), `misplaced_notes(notes, team_name_of) -> list[tuple[PlayerNote, str]]`; `BUDGET_STYLES = ("early", "steady", "hoarder")`, `ParticipantError`, `Participant(path, nick, team, budget_style, favourite_clubs, overpays, avoids, max_single_share, front_matter)`, `load_participant(path)`, `load_participants(kb_dir) -> list[Participant]` (sorted by nick; a duplicate nick raises). The audit validates both kinds of document the way it validates profiles.

- [ ] **Step 1: Write the failing note tests**

Create `core/tests/test_kb_notes.py`:

```python
from datetime import date

import pytest
from fantaclaude.kb.audit import audit
from fantaclaude.kb.notes import (
    DEPTHS,
    NoteError,
    PlayerNote,
    load_note,
    load_player_notes,
    misplaced_notes,
)

NOTE = """---
updated: 2026-08-30
ttl: 7d
confidence: medium
source: "sky.it 2026-08-30"
player_id: {player_id}
name: {name}
team_short: {short}
depth: {depth}
availability: {availability}
{extra}---

# {name}

Why the number above is what it is.
"""


def _write(kb, slug, *, player_id=2764, name="Martinez L.", short="INT", depth="starter", availability="1.0",
           extra="", filename=None):
    folder = kb / "serie-a" / "teams" / slug / "players"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (filename or f"{name.lower().replace(' ', '-').replace('.', '')}.md")
    path.write_text(NOTE.format(player_id=player_id, name=name, short=short, depth=depth,
                                availability=availability, extra=extra), encoding="utf-8")
    return path


def test_load_note_reads_the_structured_front_matter(tmp_path):
    path = _write(tmp_path / "kb", "inter", extra="prior_fantamedia: 6.8\n")
    note = load_note(path)
    assert isinstance(note, PlayerNote)
    assert (note.player_id, note.name, note.team_short, note.depth) == (2764, "Martinez L.", "INT", "starter")
    assert note.availability == 1.0 and note.prior_fantamedia == 6.8 and note.path == path
    assert note.front_matter.updated == date(2026, 8, 30)
    assert DEPTHS == ("starter", "contested", "cover", "out")


def test_depth_is_optional_and_availability_defaults_to_one(tmp_path):
    path = _write(tmp_path / "kb", "inter")
    text = path.read_text(encoding="utf-8").replace("depth: starter\n", "").replace("availability: 1.0\n", "")
    path.write_text(text, encoding="utf-8")
    note = load_note(path)
    assert note.depth is None and note.availability == 1.0 and note.prior_fantamedia is None


@pytest.mark.parametrize("edit, message", [
    (lambda t: t.replace("depth: starter", "depth: titolare"), "depth"),
    (lambda t: t.replace("availability: 1.0", "availability: 1.5"), "availability"),
    (lambda t: t.replace("player_id: 2764", "player_id: lautaro"), "player_id"),
    (lambda t: t.replace("team_short: INT", "team_short: Inter"), "team_short"),
    (lambda t: t.replace("---\nupdated", "updated", 1), "front-matter"),
    (lambda t: t.replace("name: Martinez L.\n", ""), "name"),
])
def test_load_note_fails_loud(tmp_path, edit, message):
    path = _write(tmp_path / "kb", "inter")
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(NoteError, match=message):
        load_note(path)


def test_prior_fantamedia_must_be_a_plausible_voto(tmp_path):
    path = _write(tmp_path / "kb", "inter", extra="prior_fantamedia: 12\n")
    with pytest.raises(NoteError, match="prior_fantamedia"):
        load_note(path)


def test_load_player_notes_keys_by_id_and_refuses_duplicates(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "inter")
    _write(kb, "napoli", player_id=6052, name="Hojlund", short="NAP", depth="contested", availability="0.8")
    notes = load_player_notes(kb)
    assert set(notes) == {2764, 6052} and notes[6052].availability == 0.8
    assert load_player_notes(tmp_path / "nowhere") == {}
    _write(kb, "milan", player_id=2764, name="Martinez L.", short="INT", filename="dupe.md")
    with pytest.raises(NoteError, match="2764"):
        load_player_notes(kb)


def test_misplaced_notes_name_the_folder_the_note_should_be_in(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "inter")
    _write(kb, "napoli", player_id=6052, name="Hojlund", short="NAP")
    notes = load_player_notes(kb)
    moved = misplaced_notes(notes, {2764: "Inter", 6052: "Atalanta"})            # Hojlund moved club in the listone
    assert [(n.player_id, slug) for n, slug in moved] == [(6052, "atalanta")]
    assert misplaced_notes(notes, {2764: "Inter"}) == []                          # a player no longer in the listone is not misplaced


def test_the_audit_validates_notes(tmp_path):
    kb = tmp_path / "kb"
    good = _write(kb, "inter")
    bad = _write(kb, "napoli", player_id=6052, name="Hojlund", short="NAP", depth="titolare")
    statuses = {e.path: e.status for e in audit(kb, date(2026, 8, 31))}
    assert statuses[str(good.relative_to(kb))] == "ok"
    assert statuses[str(bad.relative_to(kb))] == "invalid"
```

- [ ] **Step 2: Run the note tests to verify they fail**

Run: `uv run pytest core/tests/test_kb_notes.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.kb.notes`.

- [ ] **Step 3: Write the notes module and hook the audit**

Create `core/src/fantaclaude/kb/notes.py`:

```python
"""Player notes: the sparse per-player judgment the projection reads.

kb/serie-a/teams/<slug>/players/<name>.md exists only where prose changes
a decision (spec, "Knowledge base"): a contested shirt, a fitness risk, a
newcomer with no Serie A history. Beside the audit's four keys the
front-matter carries what the projection needs as numbers -- player_id
(the listone id, the only join; the file's location is a mirror of the
club and never the key), depth (starter | contested | cover | out: an
absolute statement about now, which replaces the statistical presenze
rate), availability (0..1, multiplies presenze), prior_fantamedia (a
newcomer's expected fantamedia, used only when he has no history). The
prose below is for the model. This loader is the front-matter's only
reader, so a malformed note fails here with its path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.kb.audit import FrontMatter, FrontMatterError, parse_front_matter
from fantaclaude.kb.profiles import team_slug

DEPTHS = ("starter", "contested", "cover", "out")
PRIOR_RANGE = (3.0, 10.0)


class NoteError(ValueError):
    """A note's front-matter is missing or malformed; the message names the file."""


@dataclass(frozen=True)
class PlayerNote:
    path: Path
    player_id: int
    name: str
    team_short: str
    depth: str | None
    availability: float
    prior_fantamedia: float | None
    front_matter: FrontMatter

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short, "depth": self.depth,
                "availability": self.availability, "prior_fantamedia": self.prior_fantamedia,
                "updated": self.front_matter.updated.isoformat() if self.front_matter.updated else None}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_note(path: Path) -> PlayerNote:
    try:
        front_matter = parse_front_matter(path.read_text(encoding="utf-8"))
    except (FrontMatterError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise NoteError(f"{path}: {exc}") from None
    if front_matter is None:
        raise NoteError(f"{path}: no front-matter block")
    data: dict[str, Any] = front_matter.raw
    player_id = data.get("player_id")
    if isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0:
        raise NoteError(f"{path}: player_id must be the listone id, got {player_id!r}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise NoteError(f"{path}: name must be the listone's spelling")
    short = data.get("team_short")
    if not isinstance(short, str) or len(short) != 3 or not short.isupper():
        raise NoteError(f"{path}: team_short must be the listone's three-letter code, got {short!r}")
    depth = data.get("depth")
    if depth is not None and depth not in DEPTHS:
        raise NoteError(f"{path}: depth must be one of {DEPTHS}, got {depth!r}")
    availability = data.get("availability", 1.0)
    if not _number(availability) or not 0.0 <= float(availability) <= 1.0:
        raise NoteError(f"{path}: availability must be a number in [0, 1], got {availability!r}")
    prior = data.get("prior_fantamedia")
    if prior is not None and (not _number(prior) or not PRIOR_RANGE[0] <= float(prior) <= PRIOR_RANGE[1]):
        raise NoteError(f"{path}: prior_fantamedia must be a voto-sized number in {PRIOR_RANGE}, got {prior!r}")
    return PlayerNote(path=path, player_id=player_id, name=name.strip(), team_short=short, depth=depth,
                      availability=float(availability), prior_fantamedia=None if prior is None else float(prior),
                      front_matter=front_matter)


def load_player_notes(kb_dir: Path) -> dict[int, PlayerNote]:
    """Every kb/serie-a/teams/*/players/*.md, by player_id; two notes for one id raise."""
    notes: dict[int, PlayerNote] = {}
    for path in sorted(kb_dir.glob("serie-a/teams/*/players/*.md")):
        note = load_note(path)
        if note.player_id in notes:
            raise NoteError(f"{path}: player_id {note.player_id} already has a note at {notes[note.player_id].path}")
        notes[note.player_id] = note
    return notes


def misplaced_notes(notes: dict[int, PlayerNote], team_name_of: dict[int, str]) -> list[tuple[PlayerNote, str]]:
    """Notes whose folder is not the slug of the player's current club --
    with the slug they belong under. A player the listone no longer has is
    not misplaced: there is nowhere better to put him."""
    moved: list[tuple[PlayerNote, str]] = []
    for player_id, note in sorted(notes.items()):
        team = team_name_of.get(player_id)
        if team is None:
            continue
        expected = team_slug(team)
        if note.path.parent.parent.name != expected:
            moved.append((note, expected))
    return moved
```

In `core/src/fantaclaude/kb/audit.py`, replace the profile special-case (the block starting `if path.name == "profile.md" and path.parent.parent.name == "teams":` through its `continue`) with:

```python
            validator = _validator_for(path)
            if validator is not None:
                try:
                    validator(path)
                except ValueError as exc:
                    entries.append(AuditEntry(rel, "invalid", str(exc).split(": ", 1)[-1]))
                    continue
```

and add, above `audit`:

```python
def _validator_for(path: Path):
    """The structured loader a document must satisfy beyond the four keys:
    profiles, player notes and participant dossiers each have one. Imported
    lazily -- those modules import this one."""
    if path.name == "profile.md" and path.parent.parent.name == "teams":
        from fantaclaude.kb.profiles import load_profile

        return load_profile
    if path.parent.name == "players" and path.parent.parent.parent.name == "teams":
        from fantaclaude.kb.notes import load_note

        return load_note
    if path.parent.name == "participants" and path.parent.parent.name == "league":
        from fantaclaude.kb.participants import load_participant

        return load_participant
    return None
```

`ProfileError`, `NoteError` and `ParticipantError` are all `ValueError`s, which is what the single `except` relies on.

- [ ] **Step 4: Run the note tests to verify they pass**

Run: `uv run pytest core/tests/test_kb_notes.py core/tests/test_kb_profiles.py core/tests/test_kb_audit.py -q`
Expected: all pass (the profile tests still see `invalid` for a bad profile).

- [ ] **Step 5: Write the failing participant tests**

Create `core/tests/test_kb_participants.py`:

```python
from datetime import date

import pytest
from fantaclaude.kb.audit import audit
from fantaclaude.kb.participants import (
    BUDGET_STYLES,
    Participant,
    ParticipantError,
    load_participant,
    load_participants,
)

DOSSIER = """---
updated: 2026-09-01
ttl: 90d
confidence: medium
source: "interview 2026-09-01"
nick: {nick}
team: {team}
budget_style: {style}
favourite_clubs: [Juventus]
overpays: [Pc, A]
avoids: [Por]
{extra}---

# {nick}

Spends early, chases Juventus players, never pays for a goalkeeper.
"""


def _write(kb, nick, *, team="Sanzimippi FC", style="early", extra="", filename=None):
    folder = kb / "league" / "participants"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (filename or f"{nick.lower()}.md")
    path.write_text(DOSSIER.format(nick=nick, team=team, style=style, extra=extra), encoding="utf-8")
    return path


def test_load_participant_reads_the_fixed_schema(tmp_path):
    path = _write(tmp_path / "kb", "Marco", extra="max_single_share: 0.3\n")
    p = load_participant(path)
    assert isinstance(p, Participant)
    assert (p.nick, p.team, p.budget_style) == ("Marco", "Sanzimippi FC", "early")
    assert p.favourite_clubs == ("Juventus",) and p.overpays == ("Pc", "A") and p.avoids == ("Por",)
    assert p.max_single_share == 0.3 and p.front_matter.updated == date(2026, 9, 1)
    assert BUDGET_STYLES == ("early", "steady", "hoarder")
    assert p.to_dict()["overpays"] == ["Pc", "A"]


def test_team_and_share_are_optional(tmp_path):
    path = _write(tmp_path / "kb", "Marco")
    text = path.read_text(encoding="utf-8").replace("team: Sanzimippi FC\n", "")
    path.write_text(text, encoding="utf-8")
    p = load_participant(path)
    assert p.team is None and p.max_single_share is None


@pytest.mark.parametrize("edit, message", [
    (lambda t: t.replace("budget_style: early", "budget_style: wild"), "budget_style"),
    (lambda t: t.replace("overpays: [Pc, A]", "overpays: [Bomber]"), "overpays"),
    (lambda t: t.replace("avoids: [Por]", "avoids: Por"), "avoids"),
    (lambda t: t.replace("nick: Marco\n", ""), "nick"),
    (lambda t: t.replace("favourite_clubs: [Juventus]", "favourite_clubs: [Juventus, 3]"), "favourite_clubs"),
    (lambda t: t.replace("---\nupdated", "updated", 1), "front-matter"),
])
def test_load_participant_fails_loud(tmp_path, edit, message):
    path = _write(tmp_path / "kb", "Marco")
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ParticipantError, match=message):
        load_participant(path)


def test_an_email_shaped_value_is_refused_anywhere_in_the_front_matter(tmp_path):
    path = _write(tmp_path / "kb", "Marco", extra="contact: marco@example.it\n")
    with pytest.raises(ParticipantError, match="email"):
        load_participant(path)
    path = _write(tmp_path / "kb", "marco@example.it")
    with pytest.raises(ParticipantError, match="email"):
        load_participant(path)


def test_max_single_share_is_a_share(tmp_path):
    path = _write(tmp_path / "kb", "Marco", extra="max_single_share: 30\n")
    with pytest.raises(ParticipantError, match="max_single_share"):
        load_participant(path)


def test_load_participants_sorts_by_nick_and_refuses_a_duplicate_nick(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "Marco")
    _write(kb, "Anna", style="hoarder")
    assert [p.nick for p in load_participants(kb)] == ["Anna", "Marco"]
    assert load_participants(tmp_path / "nowhere") == []
    _write(kb, "Marco", filename="marco-bis.md")
    with pytest.raises(ParticipantError, match="Marco"):
        load_participants(kb)


def test_the_audit_validates_dossiers(tmp_path):
    kb = tmp_path / "kb"
    good = _write(kb, "Marco")
    bad = _write(kb, "Anna", style="wild")
    statuses = {e.path: e.status for e in audit(kb, date(2026, 9, 2))}
    assert statuses[str(good.relative_to(kb))] == "ok" and statuses[str(bad.relative_to(kb))] == "invalid"
```

- [ ] **Step 6: Run the participant tests to verify they fail**

Run: `uv run pytest core/tests/test_kb_participants.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.kb.participants`.

- [ ] **Step 7: Write the participants module**

Create `core/src/fantaclaude/kb/participants.py`:

```python
"""Opponent dossiers: the fixed front-matter the auction's pressure model
loads at startup (spec, "Dossiers are loaded, not read live").

kb/league/participants/<nick>.md is written by `fanta-kb interview`. Beside
the audit's four keys the front-matter carries: nick (as the league shows
it -- the join to the FantaAstaLive team mapping), team (the league team
name, optional until the auction assigns one), budget_style (early |
steady | hoarder), favourite_clubs (listone club names), overpays and
avoids (role classes), max_single_share (the largest share of a budget
ever seen on one player, optional). The prose is what the model reads to
explain a call. No field may carry an email address -- the repository
rule that an address never reaches a tool result applies to the files a
tool would read back.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.kb.audit import FrontMatter, FrontMatterError, parse_front_matter
from fantaclaude.league.settings import EMAIL_PATTERN
from fantaclaude.model.demand import ROLE_CLASSES

BUDGET_STYLES = ("early", "steady", "hoarder")


class ParticipantError(ValueError):
    """A dossier's front-matter is missing or malformed; the message names the file."""


@dataclass(frozen=True)
class Participant:
    path: Path
    nick: str
    team: str | None
    budget_style: str
    favourite_clubs: tuple[str, ...]
    overpays: tuple[str, ...]
    avoids: tuple[str, ...]
    max_single_share: float | None
    front_matter: FrontMatter

    def to_dict(self) -> dict[str, Any]:
        return {"nick": self.nick, "team": self.team, "budget_style": self.budget_style,
                "favourite_clubs": list(self.favourite_clubs), "overpays": list(self.overpays),
                "avoids": list(self.avoids), "max_single_share": self.max_single_share,
                "updated": self.front_matter.updated.isoformat() if self.front_matter.updated else None}


def _names(data: dict[str, Any], key: str, path: Path, *, allowed: tuple[str, ...] | None = None) -> tuple[str, ...]:
    value = data.get(key, [])
    if value is None:
        value = []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ParticipantError(f"{path}: {key} must be a list of names, got {value!r}")
    if allowed is not None:
        bad = [v for v in value if v not in allowed]
        if bad:
            raise ParticipantError(f"{path}: {key} names classes that do not exist: {bad}; choose from {allowed}")
    return tuple(v.strip() for v in value)


def _no_emails(data: dict[str, Any], path: Path) -> None:
    for key, value in data.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            if isinstance(v, str) and EMAIL_PATTERN.search(v):
                raise ParticipantError(f"{path}: {key} carries an email address; dossiers never do")


def load_participant(path: Path) -> Participant:
    try:
        front_matter = parse_front_matter(path.read_text(encoding="utf-8"))
    except (FrontMatterError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ParticipantError(f"{path}: {exc}") from None
    if front_matter is None:
        raise ParticipantError(f"{path}: no front-matter block")
    data: dict[str, Any] = front_matter.raw
    _no_emails(data, path)
    nick = data.get("nick")
    if not isinstance(nick, str) or not nick.strip():
        raise ParticipantError(f"{path}: nick must be the name the league shows")
    team = data.get("team")
    if team is not None and (not isinstance(team, str) or not team.strip()):
        raise ParticipantError(f"{path}: team must be the league team name or absent")
    style = data.get("budget_style")
    if style not in BUDGET_STYLES:
        raise ParticipantError(f"{path}: budget_style must be one of {BUDGET_STYLES}, got {style!r}")
    share = data.get("max_single_share")
    if share is not None and (isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < float(share) <= 1):
        raise ParticipantError(f"{path}: max_single_share is a share of the budget in (0, 1], got {share!r}")
    return Participant(path=path, nick=nick.strip(), team=team.strip() if team else None, budget_style=style,
                       favourite_clubs=_names(data, "favourite_clubs", path),
                       overpays=_names(data, "overpays", path, allowed=ROLE_CLASSES),
                       avoids=_names(data, "avoids", path, allowed=ROLE_CLASSES),
                       max_single_share=None if share is None else float(share), front_matter=front_matter)


def load_participants(kb_dir: Path) -> list[Participant]:
    """Every kb/league/participants/*.md, by nick; two dossiers for one nick raise."""
    by_nick: dict[str, Participant] = {}
    for path in sorted(kb_dir.glob("league/participants/*.md")):
        p = load_participant(path)
        if p.nick in by_nick:
            raise ParticipantError(f"{path}: nick {p.nick!r} already has a dossier at {by_nick[p.nick].path}")
        by_nick[p.nick] = p
    return [by_nick[nick] for nick in sorted(by_nick)]
```

- [ ] **Step 8: Document the two contracts in `kb/README.md`**

Replace the tree block and add the contracts, so the file reads:

```markdown
# kb/ — the knowledge base

DuckDB holds neutral numbers; this tree holds opinionated prose with
provenance. **Prose never restates a number** — it links to a query or a
`run_id`. "Lautaro averages 7.2" is a lie waiting to happen; "Lautaro takes
penalties unless Calhanoglu is on the pitch" is durable and no table has it.

```
kb/
├── rules/                     # near-static: mantra.md, house-rules.md, aliases.yml
├── serie-a/teams/<slug>/      # profile.md: front-matter (team, team_short, coach, module, europe,
│   │                          #   rotation_factor, takers) read by fantaclaude.kb.profiles; prose for the model
│   └── players/<name>.md      # sparse: front-matter (player_id, name, team_short, depth, availability,
│                              #   prior_fantamedia) read by fantaclaude.kb.notes -- only where prose changes a decision
└── league/
    ├── participants/<nick>.md # opponent dossiers: front-matter (nick, team, budget_style, favourite_clubs,
    │                          #   overpays, avoids, max_single_share) read by fantaclaude.kb.participants
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
lacks front-matter, and what is malformed — for a profile, a player note or a
dossier, "malformed" includes its structured keys. An expired document is a
notice for the skill that would use it — the skill states low confidence or
refuses; the audit itself never refuses.

## The numbers the code reads

- **Team profile** (`fantaclaude.kb.profiles`): `rotation_factor` (0.5–1.0, the
  European load and the coach's habit, applied to every player of the club
  through his presenze), `takers.penalties` (the player the projection gives the
  club's penalties to), `europe`, `module`, `coach`.
- **Player note** (`fantaclaude.kb.notes`): `player_id` is the join — the folder
  is a mirror of the club, and `fantaclaude doctor` says when a note sits under
  the wrong club. `depth` (`starter | contested | cover | out`) *replaces* the
  statistical presenze rate: it is a statement about now, not a multiplier on
  last season. `availability` (0–1) multiplies presenze. `prior_fantamedia` is
  read only for a player with no Serie A history.
- **Participant dossier** (`fantaclaude.kb.participants`): `budget_style`
  (`early | steady | hoarder`), `favourite_clubs`, `overpays`/`avoids` (role
  classes), `max_single_share` — what the auction's pressure model loads at
  startup. No field ever carries an email address.

`/fanta-kb bootstrap` fills this tree, `/fanta-kb refresh` renews it and
`/fanta-kb interview` writes the dossiers (`.claude/skills/fanta-kb/SKILL.md`).
A profile's `europe` must agree with `v_european_ties`; `fantaclaude doctor`
says when it does not.
```

- [ ] **Step 9: Run the kb tests, lint, full suite, commit**

Run: `uv run pytest core/tests/test_kb_notes.py core/tests/test_kb_participants.py core/tests/test_kb_profiles.py core/tests/test_kb_audit.py -q && uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: all pass; ruff silent; core 246 passed.

```bash
git add core/src/fantaclaude/kb/notes.py core/src/fantaclaude/kb/participants.py core/src/fantaclaude/kb/audit.py core/tests/test_kb_notes.py core/tests/test_kb_participants.py kb/README.md
git commit -m "feat(kb): player notes and participant dossiers with validated front-matter, audited like profiles"
```

---
### Task 5: History — the observed layer under the league's scoring

**Files:**
- Create: `core/src/fantaclaude/analysis/__init__.py` (empty), `core/src/fantaclaude/analysis/history.py`, `core/tests/test_history.py`
- Modify: `core/tests/conftest.py` (two seed helpers)

**Interfaces:**
- Consumes: `v_player_match_current`, `v_voti_files_current`, `v_advanced_current`, `v_players_current`; `fantaclaude.model.scoring.{BonusMalus, Events, fantavoto}`; `fantaclaude.model.seasons.{SERIE_A_GIORNATE, back_seasons}`.
- Produces: `SeasonLine(season_id, team, classic_role, appearances, presenze, giornate, voto_mean, events, fantavoto_mean, fantavoto_var, minutes, xg, xa, npxg, understat_games)`, `RolePrior(classic_role, fantavoto_mean, fantavoto_sd, voto_mean, presenze_rate, rows)`, `History(sheet, current_season, seasons, giornate, lines, priors, club_penalty_rate)` with `lines_for(player_id) -> tuple[SeasonLine, ...]` (newest first) and `giornate_played`, `load_history(con, *, sheet, bm, current_season, back=3) -> History`; `conftest.seed_voti(con, season_id, giornata, rows, *, sheets=None)` and `conftest.seed_advanced(con, season_id, rows)`.

- [ ] **Step 1: Add the seed helpers to `core/tests/conftest.py`**

Append:

```python
def seed_voti(con, season_id: int, giornata: int, rows, *, sheets=None) -> int:
    """One synthetic voti workbook -- one file, every sheet, as the real export is.
    `rows` are (player_id, name, team, classic_role, voto, events) for the Fantacalcio
    sheet, where voto None means senza voto and events is a dict of the workbook's
    count columns; `sheets` maps further sheet names to their own rows."""
    by_sheet = {"Fantacalcio": rows, **(sheets or {})}
    file_id = con.execute(
        "INSERT INTO voti_files (season_id, giornata, fetched_at, source, raw_path, sha256, sheets, row_count) "
        "VALUES (?, ?, now(), 'seed', ?, ?, ?, ?) RETURNING file_id",
        [season_id, giornata, f"seed/{season_id}-{giornata}", f"seed-{season_id}-{giornata}", list(by_sheet),
         sum(len(r) for r in by_sheet.values())],
    ).fetchone()[0]
    for sheet, sheet_rows in by_sheet.items():
        for player_id, name, team, role, voto, events in sheet_rows:
            e = {"goals": 0, "goals_conceded": 0, "pen_saved": 0, "pen_missed": 0, "pen_scored": 0,
                 "own_goals": 0, "yellow": 0, "red": 0, "assists": 0, **(events or {})}
            con.execute(
                "INSERT INTO player_match VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
                [file_id, season_id, giornata, sheet, player_id, name, team, role, voto, voto is None,
                 e["goals"], e["goals_conceded"], e["pen_saved"], e["pen_missed"], e["pen_scored"], e["own_goals"],
                 e["yellow"], e["red"], e["assists"]])
    return file_id


def seed_advanced(con, season_id: int, rows) -> int:
    """`rows` are (player_id, minutes, games, xg, xa); one matched Understat row each."""
    snapshot_id = con.execute(
        "INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
        "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (?, now(), 'seed', ?, ?, 'seed', 1, ?, ?, 0, 0) "
        "RETURNING snapshot_id",
        [season_id, f"seed/adv-{season_id}", f"seed-adv-{season_id}", len(rows), len(rows)]).fetchone()[0]
    for player_id, minutes, games, xg, xa in rows:                     # npxg is seeded equal to xg
        con.execute(
            "INSERT INTO advanced_stats VALUES (?, ?, ?, ?, ?, ?, 'matched', [?], ?, ?, 0, 0, ?, ?, 0, ?, 0, 0, 0, 0, "
            "0.0, 0.0, 'F', '{}')",
            [snapshot_id, season_id, f"u{player_id}", f"p{player_id}", ["X"], player_id, player_id, games, minutes, xg, xa, xg])
    return snapshot_id
```

- [ ] **Step 2: Write the failing history tests**

Create `core/tests/test_history.py`:

```python
import pytest
from conftest import seed_advanced, seed_voti
from fantaclaude.analysis.history import History, RolePrior, SeasonLine, load_history
from fantaclaude.model.scoring import BonusMalus, Events


@pytest.fixture
def bm(mcp_fixture_json):
    return BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))


def _seed(db):
    # season 20: giornate 1-3 exist; Lautaro (2764) plays two, one senza voto; a goalkeeper; a coach row to ignore
    seed_voti(db, 20, 1, [(2764, "Martinez L.", "Inter", "A", 7.0, {"goals": 1, "pen_scored": 1}),
                          (5841, "Svilar", "Roma", "P", 6.0, {"goals_conceded": 2}),
                          (688, "Sarri", "Atalanta", "ALL", 6.0, {}),
                          (2640, "Kolasinac", "Atalanta", "D", 6.0, {"yellow": 1})])
    seed_voti(db, 20, 2, [(2764, "Martinez L.", "Inter", "A", 6.0, {"assists": 1}),
                          (5841, "Svilar", "Roma", "P", 6.5, {"pen_saved": 1}),
                          (2640, "Kolasinac", "Atalanta", "D", 5.5, {"pen_missed": 1})])
    seed_voti(db, 20, 3, [(2764, "Martinez L.", "Inter", "A", None, {}),
                          (5841, "Svilar", "Roma", "P", 6.0, {"goals_conceded": 1})])
    # season 21: one giornata played; the workbook's other sheet must not leak in
    seed_voti(db, 21, 1, [(2764, "Martinez L.", "Inter", "A", 6.5, {"goals": 1}),
                          (5841, "Svilar", "Roma", "P", 6.0, {})],
              sheets={"Italia": [(2764, "Martinez L.", "Inter", "A", 9.0, {"goals": 3})]})
    seed_advanced(db, 20, [(2764, 170, 2, 1.4, 0.3)])


def test_load_history_builds_season_lines_under_the_league_scoring(db, bm):
    _seed(db)
    history = load_history(db, sheet="Fantacalcio", bm=bm, current_season=21, back=3)
    assert isinstance(history, History) and history.sheet == "Fantacalcio"
    assert history.seasons == (18, 19, 20, 21) and history.giornate == {20: 3, 21: 1}
    assert history.giornate_played == 1

    lines = history.lines_for(2764)
    assert [line.season_id for line in lines] == [21, 20]                       # newest first
    s20 = lines[1]
    assert isinstance(s20, SeasonLine)
    assert (s20.team, s20.classic_role, s20.appearances, s20.presenze, s20.giornate) == ("Inter", "A", 3, 2, 3)
    assert s20.voto_mean == pytest.approx(6.5)
    assert s20.events == Events(goals=1, pen_scored=1, assists=1)
    # fantavoti: 7 + 3 + 3 = 13 and 6 + 1 = 7 -> mean 10, population variance 9
    assert s20.fantavoto_mean == pytest.approx(10.0) and s20.fantavoto_var == pytest.approx(9.0)
    assert (s20.minutes, s20.understat_games, s20.xg, s20.xa, s20.npxg) == (170, 2, pytest.approx(1.4), pytest.approx(0.3), pytest.approx(1.4))
    s21 = lines[0]
    assert (s21.presenze, s21.giornate, s21.fantavoto_mean, s21.minutes) == (1, 1, pytest.approx(9.5), None)

    keeper = history.lines_for(5841)[1]
    assert keeper.events == Events(goals_conceded=3, pen_saved=1)
    assert keeper.fantavoto_mean == pytest.approx(((6 - 2) + (6.5 + 3) + (6 - 1)) / 3)
    assert history.lines_for(688) == () and history.lines_for(999) == ()      # the coach row is not a player


def test_role_priors_and_club_penalties_come_from_the_back_seasons(db, bm):
    _seed(db)
    history = load_history(db, sheet="Fantacalcio", bm=bm, current_season=21, back=3)
    prior = history.priors["A"]
    assert isinstance(prior, RolePrior)
    assert prior.rows == 2 and prior.fantavoto_mean == pytest.approx(10.0) and prior.fantavoto_sd == pytest.approx(3.0)
    assert prior.voto_mean == pytest.approx(6.5)
    assert prior.presenze_rate == pytest.approx(2 / 3)                          # Lautaro: 2 voti in 3 giornate
    assert history.priors["D"].fantavoto_mean == pytest.approx(((6 - 0.5) + (5.5 - 2)) / 2)
    assert "ALL" not in history.priors and "C" not in history.priors           # no rows, no prior
    assert history.club_penalty_rate == {"Inter": pytest.approx(1 / 3), "Atalanta": pytest.approx(1 / 3)}


def test_an_empty_history_is_empty_not_broken(db, bm):
    history = load_history(db, sheet="Fantacalcio", bm=bm, current_season=21)
    assert history.lines_for(2764) == () and history.priors == {} and history.giornate_played == 0
```

- [ ] **Step 3: Run the history tests to verify they fail**

Run: `uv run pytest core/tests/test_history.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.analysis`.

- [ ] **Step 4: Write the history module**

Create `core/src/fantaclaude/analysis/__init__.py` empty, and `core/src/fantaclaude/analysis/history.py`:

```python
"""The observed layer, read once per run and scored under the league's rules.

player_match holds the base voto and the event counts (spec, "Fantavoto is
computed, never stored"); the fantavoto of every row is computed here with
the BonusMalus in force, so a rule change reaches every projection and the
priors alike. One sheet -- the voto source the league scores with. Coach
rows (classic_role 'ALL') are not players and are dropped. Understat's
minutes and xG/xA are joined by season and listone id from v_advanced_current
(matched rows only). Role priors and the clubs' penalty rates come from the
back seasons only: the current season's handful of giornate is a signal for
the player, not a population.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import fmean, pvariance

import duckdb

from fantaclaude.model.scoring import BonusMalus, Events, fantavoto
from fantaclaude.model.seasons import back_seasons

COACH_ROLE = "ALL"
EVENT_COLUMNS = ("goals", "goals_conceded", "pen_saved", "pen_missed", "pen_scored", "own_goals", "yellow", "red", "assists")


@dataclass(frozen=True)
class SeasonLine:
    season_id: int
    team: str
    classic_role: str
    appearances: int
    presenze: int
    giornate: int
    voto_mean: float
    events: Events
    fantavoto_mean: float
    fantavoto_var: float
    minutes: int | None
    xg: float | None
    xa: float | None
    npxg: float | None
    understat_games: int | None


@dataclass(frozen=True)
class RolePrior:
    classic_role: str
    fantavoto_mean: float
    fantavoto_sd: float
    voto_mean: float
    presenze_rate: float
    rows: int


@dataclass(frozen=True)
class History:
    sheet: str
    current_season: int
    seasons: tuple[int, ...]
    giornate: dict[int, int]
    lines: dict[int, tuple[SeasonLine, ...]] = field(default_factory=dict)
    priors: dict[str, RolePrior] = field(default_factory=dict)
    club_penalty_rate: dict[str, float] = field(default_factory=dict)

    def lines_for(self, player_id: int) -> tuple[SeasonLine, ...]:
        return self.lines.get(player_id, ())

    @property
    def giornate_played(self) -> int:
        return self.giornate.get(self.current_season, 0)


def load_history(con: duckdb.DuckDBPyConnection, *, sheet: str, bm: BonusMalus, current_season: int,
                 back: int = 3) -> History:
    seasons = (*back_seasons(current_season, back), current_season)
    giornate = {int(s): int(n) for s, n in con.execute(
        "SELECT season_id, count(DISTINCT giornata) FROM v_voti_files_current WHERE season_id = ANY(?) GROUP BY 1",
        [list(seasons)]).fetchall()}
    advanced = {(int(s), int(p)): (int(m), int(g), float(xg), float(xa), float(npxg))
                for s, p, m, g, xg, xa, npxg in con.execute(
                    "SELECT season_id, player_id, sum(minutes), sum(games), sum(xg), sum(xa), sum(npxg) "
                    "FROM v_advanced_current WHERE player_id IS NOT NULL AND season_id = ANY(?) GROUP BY 1, 2",
                    [list(seasons)]).fetchall()}
    rows = con.execute(
        "SELECT season_id, giornata, player_id, team, classic_role, voto, senza_voto, "
        + ", ".join(EVENT_COLUMNS) + " FROM v_player_match_current WHERE sheet = ? AND classic_role <> ? "
        "AND season_id = ANY(?) ORDER BY season_id, player_id, giornata",
        [sheet, COACH_ROLE, list(seasons)]).fetchall()

    per_player_season: dict[tuple[int, int], dict] = {}
    role_rows: dict[str, list[tuple[float, float]]] = defaultdict(list)          # role -> (voto, fantavoto), back seasons
    role_presenze: dict[str, list[tuple[int, int]]] = defaultdict(list)          # role -> (presenze, giornate) per player-season
    club_penalties: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for season_id, giornata, player_id, team, role, voto, senza_voto, *counts in rows:
        events = Events(**{name: float(value) for name, value in zip(EVENT_COLUMNS, counts)})
        acc = per_player_season.setdefault((int(season_id), int(player_id)), {
            "team": team, "role": role, "appearances": 0, "presenze": 0, "votes": [], "fantavoti": [], "events": Events()})
        acc["team"], acc["role"] = team, role                    # the last giornata's club and role
        acc["appearances"] += 1
        acc["events"] = acc["events"] + events
        club_penalties[int(season_id)][team] += int(events.pen_scored + events.pen_missed)
        if senza_voto or voto is None:
            continue
        fv = fantavoto(float(voto), events, bm)
        acc["presenze"] += 1
        acc["votes"].append(float(voto))
        acc["fantavoti"].append(fv)
        if int(season_id) != current_season:
            role_rows[role].append((float(voto), fv))

    lines: dict[int, list[SeasonLine]] = defaultdict(list)
    for (season_id, player_id), acc in sorted(per_player_season.items(), key=lambda item: (-item[0][0], item[0][1])):
        adv = advanced.get((season_id, player_id))
        line = SeasonLine(
            season_id=season_id, team=acc["team"], classic_role=acc["role"], appearances=acc["appearances"],
            presenze=acc["presenze"], giornate=giornate.get(season_id, 0),
            voto_mean=fmean(acc["votes"]) if acc["votes"] else 0.0, events=acc["events"],
            fantavoto_mean=fmean(acc["fantavoti"]) if acc["fantavoti"] else 0.0,
            fantavoto_var=pvariance(acc["fantavoti"]) if len(acc["fantavoti"]) > 1 else 0.0,
            minutes=adv[0] if adv else None, understat_games=adv[1] if adv else None,
            xg=adv[2] if adv else None, xa=adv[3] if adv else None, npxg=adv[4] if adv else None)
        lines[player_id].append(line)
        if season_id != current_season and line.giornate:
            role_presenze[acc["role"]].append((line.presenze, line.giornate))

    priors: dict[str, RolePrior] = {}
    for role, pairs in role_rows.items():
        votes = [v for v, _ in pairs]
        fvs = [fv for _, fv in pairs]
        rates = [p / g for p, g in role_presenze.get(role, []) if g]
        priors[role] = RolePrior(role, fmean(fvs), pvariance(fvs) ** 0.5 if len(fvs) > 1 else 0.0, fmean(votes),
                                 fmean(rates) if rates else 0.0, len(pairs))

    last_back = max((s for s in seasons if s != current_season and s in giornate), default=None)
    club_rate = ({team: n / giornate[last_back] for team, n in club_penalties[last_back].items() if n}
                 if last_back is not None and giornate.get(last_back) else {})
    return History(sheet=sheet, current_season=current_season, seasons=seasons, giornate=giornate,
                   lines={pid: tuple(ls) for pid, ls in lines.items()}, priors=priors, club_penalty_rate=club_rate)
```

- [ ] **Step 5: Run the history tests, lint, full suite, commit**

Run: `uv run pytest core/tests/test_history.py -q && uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: 3 passed; ruff silent; core 249 passed. If DuckDB rejects `= ANY(?)` with a Python list, use `season_id IN (SELECT unnest(?))` — the intent is a bound list of seasons.

```bash
git add core/src/fantaclaude/analysis/__init__.py core/src/fantaclaude/analysis/history.py core/tests/test_history.py core/tests/conftest.py
git commit -m "feat(analysis): the observed layer as per-season lines scored under the league's bonus/malus, with role priors"
```

---
### Task 6: Projection — expected presenze and fantamedia as a distribution

**Files:**
- Create: `core/src/fantaclaude/analysis/projection.py`, `core/tests/test_projection.py`

**Interfaces:**
- Consumes: `SeasonLine`, `RolePrior` (Task 5); `BonusMalus`, `Events`, `event_points` (Task 2); `DFactorTable` (Task 2); `PlayerNote` (Task 4); `Role`.
- Produces: `ProjectionConfig` (frozen, `to_dict()`, `depth_rate(depth)`), `PlayerInputs(player_id, name, team_short, team_name, classic_role, roles, role_class, quotazione, age, lines, rotation_factor, note, penalty_taker, club_has_taker, club_penalty_rate)`, `Projection(player_id, name, team_short, team_name, classic_role, role_class, roles, quotazione, exp_presenze, exp_fantamedia, exp_voto, value_p25, value_p50, value_p75, explain)` with `to_dict()`, `D_FACTOR_CLASSES`, `project_player(inputs, *, cfg, prior, bm, giornate_remaining, current_season, d_factor=None) -> Projection`, `project_all(inputs, *, cfg, priors, bm, giornate_remaining, current_season, d_factor=None) -> list[Projection]`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_projection.py`:

```python
from dataclasses import replace
from datetime import date

import pytest
from fantaclaude.analysis.history import RolePrior, SeasonLine
from fantaclaude.analysis.projection import (
    D_FACTOR_CLASSES,
    PlayerInputs,
    Projection,
    ProjectionConfig,
    project_all,
    project_player,
)
from fantaclaude.kb.audit import FrontMatter
from fantaclaude.kb.notes import PlayerNote
from fantaclaude.model.d_factor import Band, DFactorTable
from fantaclaude.model.roles import Role
from fantaclaude.model.scoring import BonusMalus, Events

CFG = ProjectionConfig()
PRIOR_A = RolePrior("A", fantavoto_mean=6.5, fantavoto_sd=1.9, voto_mean=6.0, presenze_rate=0.5, rows=2000)
PRIOR_D = RolePrior("D", fantavoto_mean=6.0, fantavoto_sd=1.1, voto_mean=5.93, presenze_rate=0.5, rows=4000)
TABLE = DFactorTable(bands=(Band(7.0, 6.0), Band(6.5, 3.0), Band(6.0, 1.0), Band(5.5, 0.0)),
                     with_goalkeeper=False, source="synthetic", verified_on=date(2026, 8, 29))


@pytest.fixture
def bm(mcp_fixture_json):
    return BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))


def line(season_id, presenze, *, giornate=38, voto=6.4, events=None, fv_var=3.0, xg=None, xa=None, npxg=None,
         games=None, team="Inter", role="A"):
    events = events or Events()
    return SeasonLine(season_id=season_id, team=team, classic_role=role, appearances=presenze, presenze=presenze,
                      giornate=giornate, voto_mean=voto, events=events, fantavoto_mean=0.0, fantavoto_var=fv_var,
                      minutes=None, xg=xg, xa=xa, npxg=npxg, understat_games=games)


def inputs(**overrides):
    base = {"player_id": 2764, "name": "Martinez L.", "team_short": "INT", "team_name": "Inter", "classic_role": "A",
            "roles": frozenset({Role.Pc}), "role_class": "Pc", "quotazione": 35, "age": 29,
            "lines": (line(20, 30, events=Events(goals=15, pen_scored=2, assists=6)),),
            "rotation_factor": 1.0, "note": None, "penalty_taker": False, "club_has_taker": False, "club_penalty_rate": 0.0}
    base.update(overrides)
    return PlayerInputs(**base)


def note(**overrides):
    base = {"path": None, "player_id": 2764, "name": "Martinez L.", "team_short": "INT", "depth": None, "availability": 1.0,
            "prior_fantamedia": None, "front_matter": FrontMatter(date(2026, 8, 30), "7d", "medium", "x", {})}
    base.update(overrides)
    return PlayerNote(**base)


def project(inp, **kw):
    """The base fixture's line is season 20; with current_season 20 it is
    'this season' and weighs 1.0, which keeps the arithmetic below exact.
    Tests about recency pass current_season=21 explicitly."""
    kw.setdefault("cfg", CFG)
    kw.setdefault("prior", PRIOR_A)
    kw.setdefault("giornate_remaining", 36)
    kw.setdefault("current_season", 20)
    return project_player(inp, **kw)


def test_a_projection_is_a_distribution_over_remaining_fantapunti(bm):
    p = project(inputs(), bm=bm)
    assert isinstance(p, Projection) and p.player_id == 2764 and p.role_class == "Pc" and p.roles == ("Pc",)
    # 30 presenze in 38 giornate -> rate 0.789 -> 36 x 0.789 = 28.4 expected presenze
    assert p.exp_presenze == pytest.approx(36 * 30 / 38, rel=1e-6)
    # per-presenza events: 0.5 goals, 0.067 penalties, 0.2 assists -> 6.4 + 1.5 + 0.2 + 0.2 = 8.3, shrunk toward 6.5 with k = 8
    raw = 6.4 + 3 * 0.5 + 3 * 2 / 30 + 1 * 0.2
    assert p.explain["fantamedia_raw"] == pytest.approx(raw)
    assert p.exp_fantamedia == pytest.approx((30 * raw + 8 * 6.5) / 38)
    assert p.exp_voto == pytest.approx((30 * 6.4 + 8 * 6.0) / 38)
    assert p.value_p50 == pytest.approx(p.exp_presenze * p.exp_fantamedia)
    assert 0 <= p.value_p25 < p.value_p50 < p.value_p75
    assert p.explain["rate_source"] == "history" and p.explain["n_eff"] == pytest.approx(30.0)
    d = p.to_dict()
    assert d["value_p50"] == pytest.approx(p.value_p50) and d["explain"]["rate_source"] == "history"


def test_quotazione_is_not_in_the_value_path(bm):
    a = project(inputs(quotazione=35), bm=bm)
    b = project(inputs(quotazione=1), bm=bm)
    c = project(inputs(quotazione=99), bm=bm)
    for field in ("exp_presenze", "exp_fantamedia", "exp_voto", "value_p25", "value_p50", "value_p75"):
        assert getattr(a, field) == getattr(b, field) == getattr(c, field), field
    assert a.explain == b.explain == c.explain


def test_rotation_lowers_the_mean_and_widens_the_band(bm):
    still = project(inputs(rotation_factor=1.0), bm=bm)
    rotated = project(inputs(rotation_factor=0.8), bm=bm)
    assert rotated.exp_presenze == pytest.approx(still.exp_presenze * 0.8)
    assert rotated.value_p50 < still.value_p50
    assert rotated.value_p75 - rotated.value_p25 > still.value_p75 - still.value_p25
    # and for a squad player too, where fewer presenze would otherwise narrow a binomial band
    cover_still = project(inputs(lines=(line(20, 12),), rotation_factor=1.0), bm=bm)
    cover_rotated = project(inputs(lines=(line(20, 12),), rotation_factor=0.8), bm=bm)
    assert cover_rotated.value_p75 - cover_rotated.value_p25 > cover_still.value_p75 - cover_still.value_p25


def test_shrinkage_is_driven_by_presenze(bm):
    hot_streak = project(inputs(lines=(line(20, 3, voto=7.4),)), bm=bm)
    full_season = project(inputs(lines=(line(20, 33, voto=7.4),)), bm=bm)
    assert PRIOR_A.fantavoto_mean < hot_streak.exp_fantamedia < full_season.exp_fantamedia < 7.4
    assert hot_streak.explain["shrink_weight"] == pytest.approx(3 / 11)
    assert full_season.explain["shrink_weight"] == pytest.approx(33 / 41)
    assert hot_streak.explain["sigma_fantamedia"] > full_season.explain["sigma_fantamedia"]


def test_recent_seasons_weigh_more(bm):
    older_good = project(inputs(lines=(line(20, 30, voto=6.0), line(19, 30, voto=7.0))), bm=bm, current_season=21)
    recent_good = project(inputs(lines=(line(20, 30, voto=7.0), line(19, 30, voto=6.0))), bm=bm, current_season=21)
    assert recent_good.exp_fantamedia > older_good.exp_fantamedia
    assert recent_good.explain["n_eff"] == pytest.approx(30 * 0.6 + 30 * 0.35)          # offsets 1 and 2 from season 21
    # the current season counts fully, presenza for presenza
    with_current = project(inputs(lines=(line(21, 2, giornate=2, voto=8.0), line(20, 30, voto=6.0))), bm=bm,
                           current_season=21)
    assert with_current.explain["n_eff"] == pytest.approx(2 * 1.0 + 30 * 0.6)
    without_current = project(inputs(lines=(line(20, 30, voto=6.0),)), bm=bm, current_season=21)
    assert with_current.exp_fantamedia > without_current.exp_fantamedia
    # a season older than the weights reach is ignored
    ancient = project(inputs(lines=(line(20, 30, voto=6.0), line(15, 30, voto=9.0))), bm=bm, current_season=21)
    assert ancient.explain["n_eff"] == pytest.approx(30 * 0.6)


def test_luck_correction_moves_goals_toward_npxg_and_assists_toward_xa(bm):
    lucky = inputs(lines=(line(20, 30, events=Events(goals=15), xg=9.0, npxg=9.0, xa=2.0, games=30),))
    plain = inputs(lines=(line(20, 30, events=Events(goals=15)),))
    corrected = project(lucky, bm=bm)
    uncorrected = project(plain, bm=bm)
    assert corrected.exp_fantamedia < uncorrected.exp_fantamedia
    assert corrected.explain["goals_per_presenza"] == pytest.approx((0.5 * 15 + 0.5 * 9.0) / 30)
    assert uncorrected.explain["goals_per_presenza"] == pytest.approx(0.5)
    unlucky = project(inputs(lines=(line(20, 30, events=Events(goals=5, assists=1), npxg=9.0, xg=9.0, xa=4.0, games=30),)), bm=bm)
    assert unlucky.explain["goals_per_presenza"] == pytest.approx(7.0 / 30)
    assert unlucky.explain["assists_per_presenza"] == pytest.approx(2.5 / 30)


def test_a_note_depth_replaces_the_base_rate_and_availability_multiplies(bm):
    cover = project(inputs(note=note(depth="cover")), bm=bm)
    assert cover.explain["rate_source"] == "note" and cover.exp_presenze == pytest.approx(36 * 0.35)
    injured = project(inputs(note=note(availability=0.5)), bm=bm)
    assert injured.exp_presenze == pytest.approx(36 * 30 / 38 * 0.5)
    out = project(inputs(note=note(depth="out")), bm=bm)
    assert out.exp_presenze == 0.0 and out.value_p50 == 0.0 and out.value_p75 == 0.0
    assert CFG.depth_rate("starter") == 0.9 and CFG.depth_rate("contested") == 0.65


def test_a_newcomer_projects_from_the_note_prior_or_the_role_mean_with_a_wide_band(bm):
    unknown = project(inputs(lines=()), bm=bm)
    assert unknown.explain["rate_source"] == "newcomer" and unknown.exp_presenze == pytest.approx(36 * 0.5)
    assert unknown.exp_fantamedia == pytest.approx(PRIOR_A.fantavoto_mean) and unknown.explain["n_eff"] == 0
    known_starter = project(inputs(lines=(line(20, 30),)), bm=bm)
    assert (unknown.value_p75 - unknown.value_p25) / unknown.value_p50 > (known_starter.value_p75 - known_starter.value_p25) / known_starter.value_p50
    with_prior = project(inputs(lines=(), note=note(depth="starter", prior_fantamedia=7.2)), bm=bm)
    assert with_prior.exp_fantamedia == pytest.approx(7.2) and with_prior.exp_presenze == pytest.approx(36 * 0.9)
    assert with_prior.explain["shrink_target"] == 7.2
    no_prior_at_all = project(inputs(lines=()), bm=bm, prior=None)
    assert no_prior_at_all.exp_fantamedia == pytest.approx(CFG.fallback_fantamedia)


def test_penalties_follow_the_named_taker(bm):
    history = (line(20, 30, events=Events(goals=10, pen_scored=5)),)
    no_taker_named = project(inputs(lines=history), bm=bm)
    taker = project(inputs(lines=history, penalty_taker=True, club_has_taker=True, club_penalty_rate=0.2), bm=bm)
    demoted = project(inputs(lines=history, penalty_taker=False, club_has_taker=True, club_penalty_rate=0.2), bm=bm)
    assert demoted.explain["penalties_per_presenza"] == 0.0 and demoted.exp_fantamedia < no_taker_named.exp_fantamedia
    assert taker.explain["penalties_per_presenza"] == pytest.approx(0.2 * CFG.pen_conversion)
    assert taker.explain["penalties_missed_per_presenza"] == pytest.approx(0.2 * (1 - CFG.pen_conversion))
    assert taker.exp_fantamedia > demoted.exp_fantamedia
    # with nobody named, history stands: 5 penalties over 30 presenze
    assert no_taker_named.explain["penalties_per_presenza"] == pytest.approx(5 / 30)


def test_the_d_factor_uplift_applies_only_when_active_and_only_to_defensive_classes(bm):
    assert D_FACTOR_CLASSES == frozenset({"Dc", "Dd", "Ds", "E", "M"})
    dc = inputs(player_id=2120, classic_role="D", roles=frozenset({Role.Dc}), role_class="Dc",
                lines=(line(20, 34, voto=6.6, role="D", events=Events()),))
    off = project(dc, bm=bm, prior=PRIOR_D)
    on = project(dc, bm=bm, prior=PRIOR_D, d_factor=TABLE)
    assert off.explain["d_factor_uplift"] == 0.0 and on.explain["d_factor_uplift"] > 0
    # slope 4 points per voto unit around the 6.1 reference, a fifth of the excess voto, per presenza
    excess = on.exp_voto - CFG.d_factor_reference
    assert on.explain["d_factor_uplift"] == pytest.approx(on.exp_presenze * 4.0 * excess / 5)
    assert on.value_p50 == pytest.approx(off.value_p50 + on.explain["d_factor_uplift"])
    assert on.value_p25 - off.value_p25 == pytest.approx(on.explain["d_factor_uplift"])
    weak = replace(dc, lines=(line(20, 34, voto=5.8, role="D"),))
    assert project(weak, bm=bm, prior=PRIOR_D, d_factor=TABLE).explain["d_factor_uplift"] == 0.0     # never a penalty
    striker_on = project(inputs(), bm=bm, d_factor=TABLE)
    assert striker_on.explain["d_factor_uplift"] == 0.0
    empty = DFactorTable((), False, None, None)
    assert project(dc, bm=bm, prior=PRIOR_D, d_factor=empty).explain["d_factor_uplift"] == 0.0


def test_role_flexibility_has_option_value(bm):
    single = project(inputs(roles=frozenset({Role.Pc})), bm=bm)
    double = project(inputs(roles=frozenset({Role.A, Role.Pc})), bm=bm)
    assert double.value_p50 == pytest.approx(single.value_p50 * (1 + CFG.flex_bonus_per_role))
    assert double.explain["flex_bonus"] == pytest.approx(1 + CFG.flex_bonus_per_role)


def test_giornate_remaining_scale_the_value(bm):
    full = project(inputs(), bm=bm, giornate_remaining=36)
    half = project(inputs(), bm=bm, giornate_remaining=18)
    assert half.exp_presenze == pytest.approx(full.exp_presenze / 2) and half.exp_fantamedia == full.exp_fantamedia


def test_project_all_uses_each_players_role_prior(bm):
    rows = project_all([inputs(), inputs(player_id=2120, classic_role="D", roles=frozenset({Role.Dc}), role_class="Dc",
                                         lines=())],
                       cfg=CFG, priors={"A": PRIOR_A, "D": PRIOR_D}, bm=bm, giornate_remaining=36, current_season=21)
    assert [p.player_id for p in rows] == [2764, 2120]
    assert rows[1].exp_fantamedia == pytest.approx(PRIOR_D.fantavoto_mean)
    assert CFG.to_dict()["season_weights"] == [1.0, 0.6, 0.35, 0.2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_projection.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.analysis.projection`.

- [ ] **Step 3: Write the projection module**

Create `core/src/fantaclaude/analysis/projection.py`:

```python
"""Projecting a player: expected presenze and fantamedia, as a distribution.

In descending order of how much each part matters (spec, "Projecting a
player"): the fantavoto is recomputed under this league's bonus/malus
(history.py scored every row; the events here are re-applied per presenza
so a taker change or a luck correction goes through the same table); the
fantamedia is shrunk toward the role mean with a weight driven by presenze
(a 7.4 across three appearances is mostly noise); seasons are weighted with
the recent heavier, presenza for presenza; goals and assists are pulled
toward non-penalty xG and xA where Understat covers the season.

Expected presenze = giornate remaining x rate. The rate is the weighted
historical presenze rate, or the note's depth when there is one -- an
absolute statement about now, which last season's minutes cannot make --
times the club's rotation_factor times the note's availability. Rotation
widens the band as much as it lowers the mean: the presenze it removes are
themselves uncertain, so their loss is added to the variance rather than
only subtracted from the mean, which is what prices the uncertainty at the
quantiles.

The listone quotazione is carried through for the pricing stage and is
read nowhere in this module: a price is not a value, and seeding the value
with the market's price would make the whole apparatus compute nothing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from fantaclaude.analysis.history import RolePrior, SeasonLine
from fantaclaude.kb.notes import PlayerNote
from fantaclaude.model.d_factor import COUNTED, DFactorTable
from fantaclaude.model.roles import Role, sort_roles
from fantaclaude.model.scoring import BonusMalus, Events, event_points

D_FACTOR_CLASSES: frozenset[str] = frozenset({"Dc", "Dd", "Ds", "E", "M"})


@dataclass(frozen=True)
class ProjectionConfig:
    season_weights: tuple[float, ...] = (1.0, 0.6, 0.35, 0.2)   # this season, then one, two, three back
    prior_presenze: float = 8.0            # the role mean counts as this many presenze
    xg_weight: float = 0.5                 # share of npxG / xA in expected goals / assists
    depth_rates: tuple[tuple[str, float], ...] = (("starter", 0.9), ("contested", 0.65), ("cover", 0.35), ("out", 0.0))
    newcomer_rate: float = 0.5             # presenze rate with no history and no note
    newcomer_dispersion: float = 1.5       # the presenze band of a newcomer, relative to a known player's
    rotation_uncertainty: float = 1.0      # the rotation loss's own sigma, as a share of the loss
    quantile_z: float = 0.6745             # p25 / p75 of a normal
    flex_bonus_per_role: float = 0.03      # option value per extra Mantra role
    pen_conversion: float = 0.8
    d_factor_reference: float = 6.1        # the defensive five's average the uplift is measured against
    fallback_fantamedia: float = 6.0       # with no history for the role at all
    fallback_sd: float = 1.5

    def depth_rate(self, depth: str) -> float:
        return dict(self.depth_rates)[depth]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["season_weights"] = list(self.season_weights)
        d["depth_rates"] = dict(self.depth_rates)
        return d


@dataclass(frozen=True)
class PlayerInputs:
    player_id: int
    name: str
    team_short: str
    team_name: str
    classic_role: str
    roles: frozenset[Role]
    role_class: str
    quotazione: int
    age: int | None
    lines: tuple[SeasonLine, ...]          # newest first
    rotation_factor: float
    note: PlayerNote | None
    penalty_taker: bool
    club_has_taker: bool
    club_penalty_rate: float               # penalties (scored + missed) per giornata the club earns


@dataclass(frozen=True)
class Projection:
    player_id: int
    name: str
    team_short: str
    team_name: str
    classic_role: str
    role_class: str
    roles: tuple[str, ...]
    quotazione: int
    exp_presenze: float
    exp_fantamedia: float
    exp_voto: float
    value_p25: float
    value_p50: float
    value_p75: float
    explain: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _per_presenza(line: SeasonLine, cfg: ProjectionConfig, inp: PlayerInputs) -> tuple[Events, dict[str, float]]:
    """The line's events per presenza, luck-corrected and with penalties re-attributed."""
    ev = line.events
    n = line.presenze
    goals, assists = ev.goals, ev.assists
    if line.npxg is not None and line.understat_games:
        goals = (1 - cfg.xg_weight) * ev.goals + cfg.xg_weight * line.npxg
    if line.xa is not None and line.understat_games:
        assists = (1 - cfg.xg_weight) * ev.assists + cfg.xg_weight * line.xa
    pen_scored, pen_missed = ev.pen_scored / n, ev.pen_missed / n
    if inp.club_has_taker:
        pen_scored = inp.club_penalty_rate * cfg.pen_conversion if inp.penalty_taker else 0.0
        pen_missed = inp.club_penalty_rate * (1 - cfg.pen_conversion) if inp.penalty_taker else 0.0
    events = Events(goals=goals / n, pen_scored=pen_scored, assists=assists / n, goals_conceded=ev.goals_conceded / n,
                    pen_saved=ev.pen_saved / n, pen_missed=pen_missed, yellow=ev.yellow / n, red=ev.red / n,
                    own_goals=ev.own_goals / n)
    return events, {"goals_per_presenza": events.goals, "assists_per_presenza": events.assists,
                    "penalties_per_presenza": events.pen_scored, "penalties_missed_per_presenza": events.pen_missed}


def project_player(inp: PlayerInputs, *, cfg: ProjectionConfig, prior: RolePrior | None, bm: BonusMalus,
                   giornate_remaining: int, current_season: int, d_factor: DFactorTable | None = None) -> Projection:
    n_eff = fm_sum = voto_sum = var_sum = rate_num = rate_den = 0.0
    newest_parts: dict[str, float] | None = None
    for line in inp.lines:                                   # newest first
        offset = current_season - line.season_id
        if offset < 0 or offset >= len(cfg.season_weights) or line.presenze <= 0:
            continue
        w = cfg.season_weights[offset] * line.presenze
        events, parts = _per_presenza(line, cfg, inp)
        fm_line = line.voto_mean + event_points(events, bm)
        n_eff += w
        fm_sum += w * fm_line
        voto_sum += w * line.voto_mean
        var_sum += w * line.fantavoto_var
        rate_num += cfg.season_weights[offset] * line.presenze
        rate_den += cfg.season_weights[offset] * line.giornate
        if newest_parts is None:
            newest_parts = parts
    per_presenza = newest_parts or {"goals_per_presenza": 0.0, "assists_per_presenza": 0.0,
                                    "penalties_per_presenza": 0.0, "penalties_missed_per_presenza": 0.0}

    # Expected fantamedia: shrink toward the target -- the note's prior for a newcomer, else the role mean.
    note = inp.note
    if note is not None and note.prior_fantamedia is not None and n_eff == 0:
        target, target_voto = note.prior_fantamedia, prior.voto_mean if prior else cfg.fallback_fantamedia
    elif prior is not None:
        target, target_voto = prior.fantavoto_mean, prior.voto_mean
    else:
        target, target_voto = cfg.fallback_fantamedia, cfg.fallback_fantamedia
    k = cfg.prior_presenze
    fm_raw = fm_sum / n_eff if n_eff else target
    voto_raw = voto_sum / n_eff if n_eff else target_voto
    shrink = n_eff / (n_eff + k)
    exp_fm = shrink * fm_raw + (1 - shrink) * target
    exp_voto = shrink * voto_raw + (1 - shrink) * target_voto
    sd_match = math.sqrt(var_sum / n_eff) if n_eff else (prior.fantavoto_sd if prior else cfg.fallback_sd)
    if sd_match <= 0:
        sd_match = prior.fantavoto_sd if prior else cfg.fallback_sd
    sigma_fm = sd_match / math.sqrt(n_eff + k)

    # Expected presenze: the note's depth is an absolute statement; else the weighted history; else a newcomer.
    base_rate = rate_num / rate_den if rate_den else None
    if note is not None and note.depth is not None:
        rate0, source = cfg.depth_rate(note.depth), "note"
    elif base_rate is not None:
        rate0, source = base_rate, "history"
    else:
        rate0, source = cfg.newcomer_rate, "newcomer"
    availability = note.availability if note is not None else 1.0
    rate = min(1.0, max(0.0, rate0 * availability * inp.rotation_factor))
    g = giornate_remaining
    exp_presenze = g * rate
    loss = g * rate0 * availability * (1 - inp.rotation_factor)
    dispersion = cfg.newcomer_dispersion if source == "newcomer" else 1.0
    sigma_pres = math.sqrt(g * rate * (1 - rate) * dispersion ** 2 + (loss * cfg.rotation_uncertainty) ** 2)

    # The distribution of the remaining season's fantapunti.
    v50 = exp_presenze * exp_fm
    sigma_v = math.sqrt((exp_fm * sigma_pres) ** 2 + (exp_presenze * sigma_fm) ** 2)
    v25 = max(0.0, v50 - cfg.quantile_z * sigma_v)
    v75 = v50 + cfg.quantile_z * sigma_v

    uplift = 0.0
    if d_factor is not None and not d_factor.is_empty and inp.role_class in D_FACTOR_CLASSES:
        excess = max(0.0, exp_voto - cfg.d_factor_reference)
        uplift = exp_presenze * d_factor.slope(cfg.d_factor_reference) * excess / COUNTED
    flex = 1 + cfg.flex_bonus_per_role * (len(inp.roles) - 1)
    v25, v50, v75 = ((v25 + uplift) * flex, (v50 + uplift) * flex, (v75 + uplift) * flex)
    if exp_presenze == 0:
        v25 = v50 = v75 = 0.0

    explain = {"n_eff": n_eff, "shrink_weight": shrink, "shrink_target": target, "fantamedia_raw": fm_raw,
               "voto_raw": voto_raw, "sigma_fantamedia": sigma_fm, "sd_match": sd_match,
               "base_rate": base_rate, "rate_source": source, "rate": rate, "depth": note.depth if note else None,
               "availability": availability, "rotation_factor": inp.rotation_factor, "sigma_presenze": sigma_pres,
               "d_factor_uplift": uplift, "flex_bonus": flex, "giornate_remaining": g, **per_presenza}
    return Projection(player_id=inp.player_id, name=inp.name, team_short=inp.team_short, team_name=inp.team_name,
                      classic_role=inp.classic_role, role_class=inp.role_class,
                      roles=tuple(r.value for r in sort_roles(inp.roles)), quotazione=inp.quotazione,
                      exp_presenze=exp_presenze, exp_fantamedia=exp_fm, exp_voto=exp_voto,
                      value_p25=v25, value_p50=v50, value_p75=v75, explain=explain)


def project_all(inputs: Iterable[PlayerInputs], *, cfg: ProjectionConfig, priors: Mapping[str, RolePrior],
                bm: BonusMalus, giornate_remaining: int, current_season: int,
                d_factor: DFactorTable | None = None) -> list[Projection]:
    return [project_player(inp, cfg=cfg, prior=priors.get(inp.classic_role), bm=bm,
                           giornate_remaining=giornate_remaining, current_season=current_season, d_factor=d_factor)
            for inp in inputs]
```

One line deserves a word: the `*_per_presenza` entries in the explanation report the *newest* line's per-presenza events — a trace for the reader, not an input to the value; the value uses every line's own events through `fm_line`.

- [ ] **Step 4: Run the tests, lint, full suite, commit**

Run: `uv run pytest core/tests/test_projection.py -q && uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: 13 passed; ruff silent; core 262 passed. `test_shrinkage_is_driven_by_presenze` pins `shrink_weight = n_eff / (n_eff + 8)` and `test_a_projection_is_a_distribution...` pins the shrinkage arithmetic exactly; if either fails, the arithmetic in `project_player` drifted from the docstring, not the other way round.

```bash
git add core/src/fantaclaude/analysis/projection.py core/tests/test_projection.py
git commit -m "feat(analysis): project a player -- presenze and fantamedia as a p25/p50/p75 band, with rotation, notes, takers, xG and the D-Factor"
```

---
### Task 7: The pricing function — indifference against the best completion

**Files:**
- Create: `core/src/fantaclaude/asta/__init__.py` (empty), `core/src/fantaclaude/asta/pricing.py`, `core/src/fantaclaude/asta/pricing_config.py`, `pricing.yml` (repository root), `core/tests/test_pricing.py`
- Modify: `core/pyproject.toml` (`+ numpy>=2.5`), `uv.lock` (via `uv sync`), `core/src/fantaclaude/paths.py` (`+ pricing_yml_path()`, `exports_dir()`)

**Interfaces:**
- Consumes: `fantaclaude.model.demand.{rank_weights, module_demand, hard_minimums}` (tests only — pricing takes the weights as input and imports nothing from the model layer); numpy.
- Produces: `PricingConfig(candidates_per_class=30, max_per_class=6, max_goalkeepers=3, bench_weight=0.12, bench_decay=0.5, bench_slots_per_class=1, target_weight=0.8, inflation_floor=0.6, inflation_ceiling=2.5, replacement_price=1, tiers_per_class=5, tier_pool=30)` with `to_dict()`; `PoolPlayer(player_id, name, role_class, value_p25, value_p50, value_p75, quotazione)`; `OwnedPlayer(player_id, role_class, value_p50)`; `PoolState(credits, market_credits, pool, weights, hard_minimums, owned=(), excluded=frozenset(), roster_min=23, roster_max=40, min_goalkeepers=2, max_goalkeepers=6, targets={}, class_budget_share={})`; `Band(p25, p50, p75)`; `PlayerPrice(player_id, role_class, band, expected_price, rank_weight, walk_value, buy_value, exact)` with `to_dict()`; `BoardPricing(prices, inflation, expected_prices, composition, credits_by_class, completion_value, reserve, budget, slot_price, targets_departed)` with `to_dict()` (`slot_price` is the shadow price of a roster place, 0 unless the league's `roster_max` binds); `price_board(state, cfg, focus=None, *, exact=False) -> BoardPricing`; `explain(board, player_id) -> dict`; `PricingConfigError`, `load_pricing_config(path) -> PricingConfig`; `paths.pricing_yml_path()`, `paths.exports_dir()`.

- [ ] **Step 1: Add numpy and the two paths**

Run: `cd core && uv add "numpy>=2.5" && cd ..` — then check `git diff core/pyproject.toml uv.lock` shows numpy 2.5.x for cp314 and nothing else. Append to `core/src/fantaclaude/paths.py`:

```python
def exports_dir() -> Path:
    return data_dir() / "exports"


def pricing_yml_path() -> Path:
    return workspace_root() / "pricing.yml"
```

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_pricing.py`:

```python
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
        assert price.expected_price >= 1 and not price.exact
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
        prices.append(price_board(state(rest, owned=owned), CFG, focus=target.player_id).prices[target.player_id].band.p50)
    assert prices == sorted(prices), prices                     # shrinking the Dc pool never lowers his price
    # only he is left and one Dc is required: walking away is infeasible, so the price is every credit
    # not needed by the other hard slots -- the two cheapest goalkeepers at their expected prices
    last = price_board(state(tuple(p for p in pool if p.role_class != "Dc") + (target,), owned=owned), CFG,
                       focus=target.player_id)
    por_costs = sorted(last.expected_prices[p.player_id] for p in by_class(pool, "Por"))
    assert last.prices[target.player_id].band.p50 == 500 - sum(por_costs[:2])
    assert last.prices[target.player_id].walk_value == float("-inf") and last.prices[target.player_id].exact


def test_excluding_a_player_raises_everyone_else_at_his_class_and_removes_him():
    pool = small_pool()
    dc = by_class(pool, "Dc")
    before = price_board(state(), CFG, exact=True)
    after = price_board(state(excluded=frozenset({dc[0].player_id})), CFG, exact=True)
    assert dc[0].player_id not in after.prices
    for p in dc[1:]:
        assert after.prices[p.player_id].band.p50 >= before.prices[p.player_id].band.p50
    assert all(after.prices[p.player_id].band.p50 >= 0 for p in pool if p.role_class != "Dc")


def test_owned_players_consume_ranks_and_bounds():
    pool = small_pool()
    por = by_class(pool, "Por")
    full = price_board(state(owned=tuple(OwnedPlayer(i, "Por", 50.0) for i in range(CFG.max_goalkeepers))), CFG)
    assert all(full.prices[p.player_id].band == Band(0, 0, 0) for p in por)          # no goalkeeper slot left
    assert full.composition["Por"] == 0
    one = price_board(state(owned=(OwnedPlayer(1, "Por", 120.0),)), CFG, focus=por[1].player_id)
    assert one.prices[por[1].player_id].rank_weight == WEIGHTS["Por"][1]              # he would be my second keeper


def test_the_focused_player_is_exact_and_matches_the_exact_board():
    pool = small_pool()
    pc = by_class(pool, "Pc")[0]
    focused = price_board(state(), CFG, focus=pc.player_id)
    every = price_board(state(), CFG, exact=True)
    assert focused.prices[pc.player_id].exact and not focused.prices[by_class(pool, "A")[0].player_id].exact
    assert focused.prices[pc.player_id] == every.prices[pc.player_id]
    assert all(price.exact for price in every.prices.values())


def test_one_pricing_function_is_deterministic():
    a = price_board(state(), CFG, exact=True).to_dict()
    b = price_board(state(), CFG, exact=True).to_dict()
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
    board = price_board(state(roster_min=23), CFG)
    bought = sum(board.composition.values())
    assert board.reserve == max(0, 23 - bought) and board.budget == 500 - board.reserve
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


def test_explain_reads_back_the_trace():
    pool = small_pool()
    pc = by_class(pool, "Pc")[0]
    board = price_board(state(), CFG, focus=pc.player_id)
    trace = explain(board, pc.player_id)
    assert trace["player_id"] == pc.player_id and trace["band"] == board.prices[pc.player_id].band.to_dict()
    assert trace["exact"] and trace["inflation"] == board.inflation and trace["composition"] == board.composition
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


def test_a_full_board_re_prices_inside_the_latency_budget():
    """The spec's constraint that keeps the model out of the loop: with one
    player on the block, the whole 553-player board must re-price in under
    100 ms (the tables are rebuilt; only the focused player pays for exactness)."""
    st = state(big_pool(), roster_min=23)
    focus = 5
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        board = price_board(st, CFG, focus=focus)
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.1, timings
    assert len(board.prices) == 553 and board.prices[focus].exact


def test_pricing_yml_is_loaded_and_validated(tmp_path, monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import pricing_yml_path

    assert load_pricing_config(pricing_yml_path()) == PricingConfig()          # the committed file is the defaults
    path = tmp_path / "pricing.yml"
    path.write_text("bench_weight: 0.2\nmax_per_class: 5\n")
    cfg = load_pricing_config(path)
    assert cfg.bench_weight == 0.2 and cfg.max_per_class == 5 and cfg.inflation_ceiling == 2.5
    for bad in ("bench_weight: heavy\n", "unknown_knob: 1\n", "- a list\n", "max_per_class: 2.5\n"):
        path.write_text(bad)
        with pytest.raises(PricingConfigError):
            load_pricing_config(path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_pricing.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.asta`.

- [ ] **Step 4: Write the pricing module**

Create `core/src/fantaclaude/asta/__init__.py` empty, and `core/src/fantaclaude/asta/pricing.py`:

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
buy(x) = w * value(p) + V_{-p,-slot}(C - x) and walk = V_{-p}(C) -- in both
branches p leaves the pool: if I do not buy him, someone else does. The
max price is the largest x with buy(x) >= walk, found by binary search
since V is monotone in credits; solved at p25, p50 and p75 of value(p),
which is the band.

The machinery (spec, "The algorithm, concretely"): expected prices are
quotazione x inflation, inflation = credits still on the market over the
quotazioni of the credible pool, clamped; per class a knapsack over the
top candidates gives f_r(j, c), the best weighted value of exactly j
players for at most c credits, the j-th chosen (in value order) carrying
the j-th rank weight; the classes combine by max-plus convolution; a
class's curve without its first slot (weights shifted by one) is what the
buy branch completes from. Removing p from his class's curve is done
exactly for the player on the block (`focus`) and, with `exact=True`, for
every player of a pre-auction run; otherwise the board is priced from the
full-pool tables and says so (`PlayerPrice.exact`). Composition is a
decision variable: the DP chooses how many of each class within the ranks
the demand gives it; a target only raises weights (a soft prior), and a
departure from it is reported. A completion that cannot meet a hard
minimum is worth -inf, which is what drives the last needed Dc's price to
the credits available. One credit is reserved for every roster slot the
completion leaves unfilled; when the completion would exceed the roster
maximum, a slot price (the shadow price of a roster place, found by
bisection) is charged per player until it fits, and reported.

Pure: no I/O, no clock, numpy inside, frozen dataclasses at the edges.
Every tunable is in PricingConfig, loaded from pricing.yml elsewhere.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

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
    rank_weight: float
    walk_value: float
    buy_value: float          # w * value_p50 - the slot price + the completion at the p50 max price
    exact: bool

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "role_class": self.role_class, "band": self.band.to_dict(),
                "expected_price": self.expected_price, "rank_weight": self.rank_weight,
                "walk_value": self.walk_value, "buy_value": self.buy_value, "exact": self.exact}


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
        return {"prices": {str(k): v.to_dict() for k, v in self.prices.items()}, "inflation": self.inflation,
                "expected_prices": {str(k): v for k, v in self.expected_prices.items()},
                "composition": self.composition, "credits_by_class": self.credits_by_class,
                "completion_value": self.completion_value, "reserve": self.reserve, "budget": self.budget,
                "slot_price": self.slot_price, "targets_departed": list(self.targets_departed)}


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


def _curve(costs: np.ndarray, values: np.ndarray, weights: tuple[float, ...], budget: int,
           penalty: float = 0.0) -> np.ndarray:
    """dp[j, c]: the best weighted value of exactly j players for at most c credits, less the slot price each."""
    k = len(weights)
    dp = np.full((k + 1, budget + 1), NEG)
    dp[0, :] = 0.0
    for cost, value in zip(costs.tolist(), values.tolist()):
        if cost > budget:
            continue
        for j in range(k, 0, -1):
            gain = dp[j - 1, :budget + 1 - cost] + (weights[j - 1] * value - penalty)
            np.maximum(dp[j, cost:], gain, out=dp[j, cost:])
    return dp


def _best(dp: np.ndarray, j_min: int, j_max: int, cap: int | None) -> np.ndarray:
    j_max = min(j_max, dp.shape[0] - 1)
    if j_min > j_max:
        return np.full(dp.shape[1], NEG)
    best = dp[j_min:j_max + 1].max(axis=0)
    if cap is not None and cap < best.shape[0] - 1:
        best = best.copy()
        best[cap + 1:] = best[cap]
    return best


def _maxplus(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = a.shape[0]
    out = np.full(n, NEG)
    for k in np.flatnonzero(a > NEG).tolist():
        np.maximum(out[k:], a[k] + b[:n - k], out=out[k:])
    return out


def _at(a: np.ndarray, b: np.ndarray, c: int) -> float:
    return float((a[:c + 1] + b[:c + 1][::-1]).max())


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
    minus_one: dict[str, np.ndarray]     # others ⊕ the class curve without its first slot
    composition: dict[str, int]
    credits: dict[str, int]


def _solve(classes: list[_Class], budget: int, penalty: float = 0.0) -> _Solution:
    zero = np.zeros(budget + 1)
    dps = {c.name: _curve(c.costs, c.values, c.weights, budget, penalty) for c in classes}
    best = {c.name: _best(dps[c.name], c.j_min, c.j_max, c.cap) for c in classes}
    prefix = [zero]
    for c in classes:
        prefix.append(_maxplus(prefix[-1], best[c.name]))
    suffix = [zero]
    for c in reversed(classes):
        suffix.append(_maxplus(suffix[-1], best[c.name]))
    suffix.reverse()                                            # suffix[i] = every class from i on
    others = {c.name: _maxplus(prefix[i], suffix[i + 1]) for i, c in enumerate(classes)}
    minus_one = {}
    for c in classes:
        dp = _curve(c.costs, c.values, c.weights[1:], budget, penalty)
        minus_one[c.name] = _maxplus(others[c.name], _best(dp, max(0, c.j_min - 1), max(0, c.j_max - 1), c.cap))
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
    return _Solution(budget, penalty, prefix[-1], others, minus_one, composition, credits)


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


def _max_price(gain: float, curve: np.ndarray, walk: float, budget: int) -> int:
    """The largest x in [0, budget] with gain + curve[budget - x] >= walk;
    curve is non-decreasing, so the predicate is monotone in x."""
    if walk == NEG:                                             # no completion without him: every spare credit
        feasible = np.flatnonzero(curve[:budget + 1] > NEG)
        return int(budget - feasible.min()) if feasible.size else 0
    if gain + curve[budget] < walk:
        return 0
    lo, hi = 0, budget
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if gain + curve[budget - mid] >= walk:
            lo = mid
        else:
            hi = mid - 1
    return lo


def price_board(state: PoolState, cfg: PricingConfig, focus: int | None = None, *,
                exact: bool = False) -> BoardPricing:
    if state.credits < 0:
        raise ValueError("credits cannot be negative")
    inflation, expected = _expected_prices(state, cfg)
    slots = max(0, state.roster_max - len(state.owned))
    classes = _classes(state, cfg, expected, state.credits)
    solution = _fit_roster(classes, state.credits, slots)
    bought = sum(solution.composition.values())
    reserve = min(state.credits, max(0, state.roster_min - len(state.owned) - bought))
    budget = state.credits - reserve
    if reserve:
        classes = _classes(state, cfg, expected, budget)
        solution = _fit_roster(classes, budget, slots)
    penalty = solution.penalty
    by_class = {c.name: c for c in classes}
    candidate_of = {p.player_id: c.name for c in classes for p in c.players}
    prices: dict[int, PlayerPrice] = {}
    for p in state.pool:
        if p.player_id in state.excluded:
            continue
        c = by_class[p.role_class]
        if c.j_max == 0:
            prices[p.player_id] = PlayerPrice(p.player_id, c.name, Band(0, 0, 0), expected[p.player_id], 0.0,
                                              float(solution.total[budget]), NEG, True)
            continue
        weight = c.weights[0]
        wants_exact = exact or p.player_id == focus
        if wants_exact and p.player_id in candidate_of:
            keep = [i for i, q in enumerate(c.players) if q.player_id != p.player_id]
            costs, values = c.costs[keep], c.values[keep]
            walk = _at(solution.others[c.name],
                       _best(_curve(costs, values, c.weights, budget, penalty), c.j_min, c.j_max, c.cap), budget)
            curve = _maxplus(solution.others[c.name],
                             _best(_curve(costs, values, c.weights[1:], budget, penalty), max(0, c.j_min - 1),
                                   max(0, c.j_max - 1), c.cap))
        else:
            walk, curve = float(solution.total[budget]), solution.minus_one[c.name]
        band = Band(*(_max_price(weight * v - penalty, curve, walk, budget)
                      for v in (p.value_p25, p.value_p50, p.value_p75)))
        if c.cap is not None:                                   # a budget share caps the class, so it caps the price
            band = Band(*(min(x, c.cap) for x in (band.p25, band.p50, band.p75)))
        completion = float(curve[budget - band.p50])
        buy = weight * p.value_p50 - penalty + completion if completion > NEG else NEG
        prices[p.player_id] = PlayerPrice(p.player_id, c.name, band, expected[p.player_id], weight, walk, buy,
                                          wants_exact)
    owned = Counter(o.role_class for o in state.owned)
    departed = tuple(cls for cls, n in state.targets.items()
                     if solution.composition.get(cls, 0) + owned.get(cls, 0) < n)
    return BoardPricing(prices, inflation, expected, solution.composition, solution.credits,
                        float(solution.total[budget]), reserve, budget, penalty, departed)


def explain(board: BoardPricing, player_id: int) -> dict[str, Any]:
    """The trace behind one price, for the model to read: never a recomputation."""
    price = board.prices[player_id]
    return {"player_id": player_id, "role_class": price.role_class, "band": price.band.to_dict(),
            "expected_price": price.expected_price, "rank_weight": price.rank_weight,
            "walk_value": price.walk_value, "buy_value": price.buy_value, "exact": price.exact,
            "inflation": board.inflation, "composition": board.composition,
            "credits_by_class": board.credits_by_class, "completion_value": board.completion_value,
            "reserve": board.reserve, "budget": board.budget, "slot_price": board.slot_price,
            "targets_departed": list(board.targets_departed),
            "note": ("priced with him removed from the pool in both branches" if price.exact
                     else "board price: the walk-away plan still counts him as available; the lot on the block is exact")}
```

Create `core/src/fantaclaude/asta/pricing_config.py`:

```python
"""pricing.yml -> PricingConfig, so whoever tunes the numbers never opens
the algorithm and whoever changes the algorithm never hunts for numbers."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.asta.pricing import PricingConfig


class PricingConfigError(ValueError):
    """pricing.yml is malformed, names an unknown knob, or types one wrongly."""


def load_pricing_config(path: Path) -> PricingConfig:
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PricingConfigError(f"{path}: {exc}") from None
    if not isinstance(data, dict):
        raise PricingConfigError(f"{path}: the top level must be a mapping of knobs")
    known = {f.name: f.type for f in fields(PricingConfig)}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise PricingConfigError(f"{path}: unknown knob(s) {unknown}; known: {sorted(known)}")
    values: dict[str, Any] = {}
    for name, value in data.items():
        expected = known[name]
        if isinstance(value, bool) or (expected == "int" and not isinstance(value, int)) \
                or (expected == "float" and not isinstance(value, (int, float))):
            raise PricingConfigError(f"{path}: {name} must be {expected}, got {value!r}")
        values[name] = int(value) if expected == "int" else float(value)
    return PricingConfig(**values)
```

(`fields(...).type` is the annotation string because of `from __future__ import annotations` — `"int"` / `"float"` — which is what the comparisons use.)

Create `pricing.yml` at the repository root:

```yaml
# pricing.yml -- the knobs of core/src/fantaclaude/asta/pricing.py. Versioned
# because every value here changes a max price: it feeds model_hash. The
# algorithm is not here; whoever tunes these never opens it.
candidates_per_class: 30     # the DP values the top 30 by value and the top 30 by value per credit of each class
max_per_class: 6             # the most players of one class the completion may buy
max_goalkeepers: 3
bench_weight: 0.12           # the first bench rank of a class: the chance to start anyway
bench_decay: 0.5             # each further bench rank is worth this much of the previous
bench_slots_per_class: 1     # bench ranks beyond the peak demand of any module
target_weight: 0.8           # what a preferences.yml target raises a rank's weight to (soft, never a bound)
inflation_floor: 0.6         # clamps on credits-on-the-market / quotazioni-of-the-credible-pool
inflation_ceiling: 2.5
replacement_price: 1         # the price a replacement-level player is expected to cost
tiers_per_class: 5           # tiers by the largest gaps in value, per class
tier_pool: 30                # among the top N of the class; the rest is one tier below
```

- [ ] **Step 5: Run the tests, lint, full suite, commit**

Run: `uv run pytest core/tests/test_pricing.py -q && uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: 15 passed; ruff silent; core 277 passed. Two of these tests carry the spec's invariants and are the ones to believe if anything disagrees: `test_scarcity_never_lowers_the_price...` (monotone in the shrinking pool, and the exhausted case equal to every spare credit) and `test_a_full_board_re_prices_inside_the_latency_budget` (report the three timings in the task summary — the spec says the test, not the prose, owns the budget; if it fails on this machine, the first knob is `max_per_class`, the second the candidate count, and the docstring's approximation note must be updated to match whatever is changed). `test_excluding_a_player_raises_everyone_else...` is the exclusion invariant reached from the other direction. If `_maxplus` proves the hot spot, replace its loop with a 2-D broadcast (`a[:, None] + b[None, :]` over an index grid) before touching anything else.

```bash
git add core/pyproject.toml uv.lock core/src/fantaclaude/asta/__init__.py core/src/fantaclaude/asta/pricing.py core/src/fantaclaude/asta/pricing_config.py core/src/fantaclaude/paths.py pricing.yml core/tests/test_pricing.py
git commit -m "feat(asta): the pricing function -- per-class knapsacks, max-plus completion value, indifference max price at three quantiles"
```

---
### Task 8: The valuation run — VOR, tiers, divergence, the two hashes, the exports

**Files:**
- Create: `core/src/fantaclaude/analysis/valuation.py`, `core/src/fantaclaude/analysis/exports.py`, `core/tests/test_valuation.py`
- Modify: `preferences.yml` (the `scenarios` block), `records/README.md`

**Interfaces:**
- Consumes: everything from Tasks 2–7; `v_players_current`, `v_league_settings_current`, `listone_snapshots`, `v_voti_files_current`, `advanced_snapshots`, `fixture_snapshots`; `fantaclaude.ingest.names.{Candidate, Matcher}`; `fantaclaude.league.settings.canonical_json`; `fantaclaude.timeutil.to_db`; `fantaclaude.model.seasons.SERIE_A_GIORNATE`.
- Produces: `MODEL_VERSION`, `RISK_APPETITES`, `PreferencesError`, `ValuationError`, `Scenario(name, target_composition, risk_appetite, max_budget_share_per_role)` with `to_dict()` and `quantile` (`"p25" | "p50" | "p75"`), `load_scenarios(preferences) -> list[Scenario]`, `model_hash(projection_cfg, pricing_cfg, preferences, d_factor) -> str`, `inputs_hash(con, *, profiles, notes) -> str`, `RunContext`, `load_context(con)`, `build_inputs(con, history, profiles, notes, weights) -> tuple[list[PlayerInputs], list[str]]`, `build_pool(projections) -> tuple[PoolPlayer, ...]`, `replacement_levels(pool, expected_prices, cfg) -> dict[str, float]`, `assign_tiers(pool, cfg) -> dict[int, int]`, `divergence(pool) -> dict[int, tuple[float, float]]`, `ValuationRun`, `new_run_id(now, rules_hash, model_hash)`, `run_valuation(con, *, now, kb_dir, preferences, projection_cfg, pricing_cfg, d_factor, scenario_names=None) -> ValuationRun`, `record_run(con, run)`; `write_rankings(run, exports_dir) -> tuple[Path, Path]`, `write_asta_plan(run, exports_dir) -> Path`, `export_records(con, run_id, rules_hash, records_dir) -> list[Path]`.

- [ ] **Step 1: Add the scenarios to `preferences.yml`**

Append to `preferences.yml`:

```yaml
scenarios:                           # the asta plan's three plans; each overrides the keys above
  aggressive-attack:
    target_composition: {A: 2, Pc: 2, T: 1}
    risk_appetite: aggressive
  value-hunting:
    risk_appetite: cautious
    max_budget_share_per_role: {Pc: 0.25, A: 0.2}
```

`balanced` is the top-level keys themselves and is always the first scenario; `risk_appetite` chooses which quantile of the band the plan tells you to bid to (`cautious` p25, `balanced` p50, `aggressive` p75). The board always shows all three.

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_valuation.py`:

```python
import json
from datetime import UTC, datetime

import duckdb
import pytest
from conftest import seed_voti
from fantaclaude.analysis.projection import ProjectionConfig
from fantaclaude.analysis.valuation import (
    MODEL_VERSION,
    PreferencesError,
    Scenario,
    ValuationError,
    ValuationRun,
    assign_tiers,
    divergence,
    inputs_hash,
    load_scenarios,
    model_hash,
    new_run_id,
    record_run,
    replacement_levels,
    run_valuation,
)
from fantaclaude.asta.pricing import PoolPlayer, PricingConfig
from fantaclaude.db.connection import connect
from fantaclaude.kb.notes import load_player_notes
from fantaclaude.kb.profiles import load_profiles
from fantaclaude.model.d_factor import load_d_factor
from test_doctor import _ready_workspace
from test_kb_profiles import _write as write_profile

NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
PREFS = {"risk_appetite": "balanced", "max_budget_share_per_role": {}, "excluded_clubs": [],
         "target_composition": {"Por": 2}}


def seeded(tmp_path, fixture_json, mcp_fixture_json, *, profiles=True):
    """The doctor's ready workspace plus profiles for its 8 clubs and a back season for a few players."""
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    kb = tmp_path / "kb"
    if profiles:
        for name, short in (("Cagliari", "CAG"), ("Roma", "ROM"), ("Inter", "INT"), ("Milan", "MIL"), ("Fiorentina", "FIO"),
                            ("Napoli", "NAP"), ("Genoa", "GEN")):
            write_profile(kb, name, short, europe="none", rotation="1.0")
        write_profile(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85")
    con = connect(tmp_path / "data" / "fanta.duckdb")
    rows20 = [(2764, "Martinez L.", "Inter", "A", 6.5, {"goals": 1}), (6052, "Hojlund", "Napoli", "A", 6.0, {}),
              (2120, "Bastoni", "Inter", "D", 6.5, {}), (5841, "Svilar", "Roma", "P", 6.0, {"goals_conceded": 1}),
              (152, "Barella", "Inter", "C", 6.5, {"assists": 1}), (2423, "Pulisic", "Milan", "A", 7.0, {"goals": 1})]
    for giornata in range(1, 31):
        seed_voti(con, 20, giornata, rows20)
    con.close()
    return tmp_path


def run(tmp_path, **kw):
    con = connect(tmp_path / "data" / "fanta.duckdb")
    try:
        kw.setdefault("now", NOW)
        kw.setdefault("kb_dir", tmp_path / "kb")
        kw.setdefault("preferences", PREFS)
        kw.setdefault("projection_cfg", ProjectionConfig())
        kw.setdefault("pricing_cfg", PricingConfig())
        kw.setdefault("d_factor", load_d_factor())
        return run_valuation(con, **kw), con
    except Exception:
        con.close()
        raise


def test_scenarios_come_from_preferences_with_balanced_first():
    prefs = {**PREFS, "scenarios": {"aggressive-attack": {"target_composition": {"A": 2, "Pc": 2}, "risk_appetite": "aggressive"},
                                    "value-hunting": {"risk_appetite": "cautious", "max_budget_share_per_role": {"Pc": 0.25}}}}
    scenarios = load_scenarios(prefs)
    assert [s.name for s in scenarios] == ["balanced", "aggressive-attack", "value-hunting"]
    assert scenarios[0] == Scenario("balanced", {"Por": 2}, "balanced", {})
    assert scenarios[1].target_composition == {"Por": 2, "A": 2, "Pc": 2} and scenarios[1].quantile == "p75"
    assert scenarios[2].max_budget_share_per_role == {"Pc": 0.25} and scenarios[2].quantile == "p25"
    assert load_scenarios(PREFS) == [scenarios[0]]
    for bad in ({**PREFS, "risk_appetite": "wild"}, {**PREFS, "target_composition": {"Xy": 1}},
                {**PREFS, "scenarios": {"x": {"max_budget_share_per_role": {"Pc": 3}}}}, {**PREFS, "scenarios": [1]}):
        with pytest.raises(PreferencesError):
            load_scenarios(bad)


def test_replacement_tiers_and_divergence_on_a_synthetic_pool():
    pool = tuple(PoolPlayer(i, f"p{i}", "A", v * 0.8, v, v * 1.2, q)
                 for i, (v, q) in enumerate([(200, 30), (190, 25), (120, 12), (115, 14), (60, 3), (58, 2), (20, 1), (18, 1)]))
    expected = {p.player_id: max(1, p.quotazione) for p in pool}
    cfg = PricingConfig(tiers_per_class=3, tier_pool=6)
    assert replacement_levels(pool, expected, cfg) == {"A": 20.0}           # the best player expected to cost one credit
    tiers = assign_tiers(pool, cfg)
    assert tiers == {0: 1, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4}        # three tiers by the two largest gaps, the rest one below
    values = {p.player_id: p.value_p50 for p in pool}
    for a in pool:
        for b in pool:
            if values[a.player_id] > values[b.player_id]:
                assert tiers[a.player_id] <= tiers[b.player_id]           # tiers are monotone
    div = divergence(pool)
    assert div[3] == (pytest.approx(120.0), pytest.approx(-5.0))            # quotazione rank 2 implies 120; he is worth 115
    assert div[2] == (pytest.approx(115.0), pytest.approx(5.0))
    assert div[0] == (pytest.approx(200.0), pytest.approx(0.0))


def test_run_valuation_projects_prices_and_stamps(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path)
    try:
        assert isinstance(result, ValuationRun) and len(result.projections) == 17
        assert result.season_id == 21 and result.giornata == 1 and len(result.rules_hash) == 16
        assert result.settings_snapshot_id == 1 and result.listone_snapshot_id == 1
        assert [s.name for s in result.scenarios] == ["balanced"] and set(result.boards) == {"balanced"}
        assert len(result.run_id) == 25 and result.run_id.startswith("20260830T100000Z-")
        by_id = {p.player_id: p for p in result.projections}
        lautaro = by_id[2764]
        assert lautaro.role_class == "Pc" and lautaro.explain["rate_source"] == "history"
        assert lautaro.explain["rotation_factor"] == 1.0 and by_id[2640].explain["rotation_factor"] == 0.85
        assert all(result.vor[pid] >= 0 for pid in by_id)                                    # no negative VOR
        assert all(1 <= result.tiers[pid] <= PricingConfig().tiers_per_class + 1 for pid in by_id)
        board = result.boards["balanced"]
        assert set(board.prices) == set(by_id) and all(p.exact for p in board.prices.values())
        assert all(p.band.p75 <= board.budget for p in board.prices.values())
        assert board.composition["Por"] >= 2 and board.budget <= 500
        assert sum(board.credits_by_class.values()) <= 500                                  # max prices sum sanely
        assert result.implied[2764][0] > 0 and isinstance(result.implied[2764][1], float)
        # every club has a profile, so no "no profile" warning; the template's taker (Calhanoglu) is Inter's
        # alone and a taker is resolved among his own club's players, so the other seven clubs warn
        assert not any("no profile" in w for w in result.warnings)
        assert all("penalty taker" in w for w in result.warnings)
        assert result.summary["team_count"] == 8 and result.summary["market_credits"] == 4000
        assert result.summary["giornate_remaining"] == 37
    finally:
        con.close()


def test_the_run_is_deterministic_and_the_hashes_track_their_inputs(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    first, con = run(tmp_path)
    con.close()
    second, con = run(tmp_path)
    con.close()
    assert [p.to_dict() for p in first.projections] == [p.to_dict() for p in second.projections]
    assert first.boards["balanced"].to_dict() == second.boards["balanced"].to_dict()
    assert first.model_hash == second.model_hash and first.inputs_hash == second.inputs_hash

    tuned, con = run(tmp_path, pricing_cfg=PricingConfig(bench_weight=0.2))
    con.close()
    assert tuned.model_hash != first.model_hash and tuned.inputs_hash == first.inputs_hash
    prefs = {**PREFS, "target_composition": {"Por": 2, "W": 2}}
    nudged, con = run(tmp_path, preferences=prefs)
    con.close()
    assert nudged.model_hash != first.model_hash

    note_dir = tmp_path / "kb" / "serie-a" / "teams" / "inter" / "players"
    note_dir.mkdir(parents=True)
    (note_dir / "martinez-l.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                            "player_id: 2764\nname: Martinez L.\nteam_short: INT\ndepth: cover\n---\n# note\n")
    noted, con = run(tmp_path)
    con.close()
    assert noted.inputs_hash != first.inputs_hash and noted.model_hash == first.model_hash
    assert {p.player_id: p for p in noted.projections}[2764].explain["rate_source"] == "note"


def test_missing_profiles_and_unresolved_takers_are_warnings_not_refusals(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json, profiles=False)
    profile = write_profile(tmp_path / "kb", "Inter", "INT", europe="none", rotation="0.9")
    # the template's taker, Calhanoglu, is listone id 2194 and resolves; a name the listone cannot have does not
    profile.write_text(profile.read_text(encoding="utf-8").replace("penalties: Calhanoglu", "penalties: Nobody"), encoding="utf-8")
    result, con = run(tmp_path)
    con.close()
    assert any("no profile" in w and "Roma" in w for w in result.warnings)
    assert any("'Nobody'" in w and "Inter" in w for w in result.warnings)
    by_id = {p.player_id: p for p in result.projections}
    assert by_id[5841].explain["rotation_factor"] == 1.0
    assert by_id[2194].explain["penalties_per_presenza"] == 0.0                 # Inter's taker is unresolved: history stands, nobody gets the club's penalties


def test_an_unknown_modifier_or_an_empty_d_factor_table_refuses(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["smodf"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    with pytest.raises(ValuationError, match="smodf"):
        run(tmp_path)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload["calculate"]["smodf"] = None
    payload["calculate"]["smodd"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    with pytest.raises(ValuationError, match="d_factor.yml"):
        run(tmp_path)


def test_record_run_writes_immutable_rows_and_the_views_follow(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path)
    try:
        record_run(con, result)
        assert con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM valuations").fetchone()[0] == 17
        assert con.execute("SELECT count(*) FROM valuation_prices").fetchone()[0] == 17
        assert con.execute("SELECT run_id FROM v_valuations_current LIMIT 1").fetchone()[0] == result.run_id
        assert con.execute("SELECT superseded FROM v_valuation_runs").fetchone()[0] is False
        row = con.execute("SELECT v.role_class, v.tier, v.vor, p.max_p50 FROM v_valuations_current v JOIN v_valuation_prices_current p "
                          "USING (run_id, player_id) WHERE v.player_id = 2764").fetchone()
        assert row[0] == "Pc" and row[1] >= 1 and row[2] >= 0 and row[3] >= 0
        with pytest.raises(duckdb.Error):
            record_run(con, result)                                        # the same run twice is a constraint violation
        again = run_valuation(con, now=NOW, kb_dir=tmp_path / "kb", preferences=PREFS, projection_cfg=ProjectionConfig(),
                              pricing_cfg=PricingConfig(), d_factor=load_d_factor())
        assert again.run_id == result.run_id + "-2"                        # a second run in the same second is kept, not clobbered
        record_run(con, again)
        assert con.execute("SELECT run_id FROM v_valuations_current LIMIT 1").fetchone()[0] == again.run_id
        # the superseded run is still there, whole: a second run appends, it never edits the first
        assert con.execute("SELECT count(*) FROM valuations WHERE run_id = ?", [result.run_id]).fetchone()[0] == 17
        assert con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0] == 2
    finally:
        con.close()


def test_excluded_clubs_refuses_rather_than_quietly_restamping_the_run(tmp_path, fixture_json, mcp_fixture_json):
    """It is hashed into model_hash with the rest of preferences but excludes nobody:
    honouring it silently would spend the reproducibility chain to buy nothing."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    with pytest.raises(PreferencesError, match="excluded_clubs"):
        run(tmp_path, preferences={**PREFS, "excluded_clubs": ["Inter"]})
    assert PREFS["excluded_clubs"] == []            # the shipped default, and it must still run
    result, con = run(tmp_path)
    con.close()
    assert len(result.projections) == 17


def test_a_filtered_run_records_the_scenarios_it_actually_ran(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    prefs = {**PREFS, "scenarios": {"aggressive-attack": {"risk_appetite": "aggressive"},
                                    "value-hunting": {"risk_appetite": "cautious"}}}
    full, con = run(tmp_path, preferences=prefs)
    con.close()
    filtered, con = run(tmp_path, preferences=prefs, scenario_names=["value-hunting"])
    con.close()
    assert full.config["scenarios"] == ["balanced", "aggressive-attack", "value-hunting"] == list(full.boards)
    assert filtered.config["scenarios"] == ["value-hunting"] and set(filtered.boards) == {"value-hunting"}
    # the preferences that define all three are still recorded whole; only the model_hash
    # must not move, so a filtered run stays comparable to a full one of the same model
    assert filtered.config["preferences"] == full.config["preferences"]
    assert filtered.model_hash == full.model_hash and filtered.inputs_hash == full.inputs_hash
    # VOR, tiers and divergence are the pool's, not the filter's
    assert filtered.vor == full.vor and filtered.tiers == full.tiers and filtered.implied == full.implied
    with pytest.raises(PreferencesError, match="value-hunting"):
        run(tmp_path, preferences=prefs, scenario_names=["no-such-plan"])


def test_new_run_id_and_model_version():
    assert new_run_id(NOW, "bc74428832035639", "0123456789abcdef") == "20260830T100000Z-0123bc74"
    assert MODEL_VERSION and model_hash(ProjectionConfig(), PricingConfig(), PREFS, load_d_factor()) != \
        model_hash(ProjectionConfig(prior_presenze=9), PricingConfig(), PREFS, load_d_factor())


def test_inputs_hash_reads_the_snapshots(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    try:
        profiles, notes = load_profiles(tmp_path / "kb"), load_player_notes(tmp_path / "kb")
        a = inputs_hash(con, profiles=profiles, notes=notes)
        assert len(a) == 16 and a == inputs_hash(con, profiles=profiles, notes=notes)
        assert a != inputs_hash(con, profiles=profiles[1:], notes=notes)
    finally:
        con.close()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_valuation.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.analysis.valuation`.

- [ ] **Step 4: Write the valuation module**

Create `core/src/fantaclaude/analysis/valuation.py`:

```python
"""A valuation run: every listone player projected, pinned to a role class,
priced against the best completion of the roster, and stamped.

Two hashes, because there are two ways a run goes stale (spec, "Schema"):
rules_hash is the league_settings row in force; model_hash covers the
projection and pricing configuration, preferences.yml and the D-Factor
table -- what moved after I changed the minutes projection? -- and
inputs_hash covers the data and the knowledge base the run read, so a run
is reproducible from what it names. The permanent record is the run_id
(spec, "fanta-market"): the exports are renderings of these rows.

The stages, in the spec's order: project (Task 6), Mantra-adjust (the
flexibility bonus in the projection and the role pinning here), value
above replacement (against the best player expected to cost one credit at
the class), allocate (price_board with exact=True, once per scenario --
the composition is the DP's), tier (the largest gaps in value within the
class). The quotazione enters only as the expected price and, at the end,
as the divergence check: where we disagree most with the market is either
the edge or a bug, and it is the list worth reading by hand.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.history import History, load_history
from fantaclaude.analysis.projection import (
    PlayerInputs,
    Projection,
    ProjectionConfig,
    project_all,
)
from fantaclaude.asta.pricing import (
    BoardPricing,
    PoolPlayer,
    PoolState,
    PricingConfig,
    price_board,
)
from fantaclaude.ingest.names import Candidate, Matcher
from fantaclaude.kb.notes import PlayerNote, load_player_notes
from fantaclaude.kb.profiles import TeamProfile, load_profiles
from fantaclaude.league.settings import canonical_json
from fantaclaude.model.d_factor import DFactorTable
from fantaclaude.model.demand import (
    ROLE_CLASSES,
    hard_minimums,
    module_demand,
    pin_class,
    rank_weights,
)
from fantaclaude.model.roles import Role
from fantaclaude.model.scoring import BonusMalus, modifier_status, voto_sheet
from fantaclaude.model.seasons import SERIE_A_GIORNATE
from fantaclaude.timeutil import to_db

MODEL_VERSION = "1"
RISK_APPETITES = ("cautious", "balanced", "aggressive")
QUANTILE_OF = {"cautious": "p25", "balanced": "p50", "aggressive": "p75"}


class PreferencesError(ValueError):
    """preferences.yml is malformed."""


class ValuationError(RuntimeError):
    """The run cannot be made honestly: a rule this code does not model is active, or an input is missing."""


@dataclass(frozen=True)
class Scenario:
    name: str
    target_composition: dict[str, int]
    risk_appetite: str
    max_budget_share_per_role: dict[str, float]

    @property
    def quantile(self) -> str:
        return QUANTILE_OF[self.risk_appetite]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "target_composition": self.target_composition,
                "risk_appetite": self.risk_appetite, "max_budget_share_per_role": self.max_budget_share_per_role}


def _composition(value: Any, where: str) -> dict[str, int]:
    value = value or {}
    if not isinstance(value, dict) or any(k not in ROLE_CLASSES or isinstance(v, bool) or not isinstance(v, int) or v < 0
                                          for k, v in value.items()):
        raise PreferencesError(f"{where}: target_composition maps role classes ({ROLE_CLASSES}) to counts, got {value!r}")
    return dict(value)


def _shares(value: Any, where: str) -> dict[str, float]:
    value = value or {}
    if not isinstance(value, dict) or any(k not in ROLE_CLASSES or isinstance(v, bool) or not isinstance(v, (int, float))
                                          or not 0 < float(v) <= 1 for k, v in value.items()):
        raise PreferencesError(f"{where}: max_budget_share_per_role maps role classes to shares in (0, 1], got {value!r}")
    return {k: float(v) for k, v in value.items()}


def _risk(value: Any, where: str) -> str:
    if value not in RISK_APPETITES:
        raise PreferencesError(f"{where}: risk_appetite must be one of {RISK_APPETITES}, got {value!r}")
    return value


def load_scenarios(preferences: dict[str, Any]) -> list[Scenario]:
    base = Scenario("balanced", _composition(preferences.get("target_composition"), "preferences.yml"),
                    _risk(preferences.get("risk_appetite", "balanced"), "preferences.yml"),
                    _shares(preferences.get("max_budget_share_per_role"), "preferences.yml"))
    scenarios = [base]
    raw = preferences.get("scenarios") or {}
    if not isinstance(raw, dict):
        raise PreferencesError("preferences.yml: scenarios must be a mapping of name -> overrides")
    for name, over in raw.items():
        if name == base.name:
            continue
        if not isinstance(over, dict):
            raise PreferencesError(f"preferences.yml: scenario {name!r} must be a mapping of overrides")
        where = f"preferences.yml: scenarios.{name}"
        scenarios.append(Scenario(str(name), {**base.target_composition, **_composition(over.get("target_composition"), where)},
                                  _risk(over.get("risk_appetite", base.risk_appetite), where),
                                  {**base.max_budget_share_per_role, **_shares(over.get("max_budget_share_per_role"), where)}))
    return scenarios


def _digest(view: Any) -> str:
    return hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()[:16]


def _finite(value: Any) -> Any:
    """-inf / inf / nan are not JSON, and DuckDB's JSON column refuses them:
    stored as null in the JSON payloads (the DOUBLE columns keep the real value)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def model_hash(projection_cfg: ProjectionConfig, pricing_cfg: PricingConfig, preferences: dict[str, Any],
               d_factor: DFactorTable) -> str:
    return _digest({"model_version": MODEL_VERSION, "projection": projection_cfg.to_dict(),
                    "pricing": pricing_cfg.to_dict(), "preferences": preferences, "d_factor": d_factor.to_dict()})


def inputs_hash(con: duckdb.DuckDBPyConnection, *, profiles: list[TeamProfile], notes: dict[int, PlayerNote]) -> str:
    listone = con.execute("SELECT snapshot_id, sha256 FROM listone_snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    voti = con.execute("SELECT season_id, giornata, sha256 FROM v_voti_files_current ORDER BY 1, 2").fetchall()
    advanced = con.execute("SELECT season_id, snapshot_id FROM advanced_snapshots WHERE snapshot_id IN "
                           "(SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id) ORDER BY 1").fetchall()
    fixtures = con.execute("SELECT competition, season_id, max(snapshot_id) FROM fixture_snapshots GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    settings = con.execute("SELECT snapshot_id FROM v_league_settings_current").fetchone()
    kb = {"profiles": [{"team": p.team, "coach": p.coach, "module": p.module, "europe": p.europe,
                        "rotation_factor": p.rotation_factor, "takers": p.takers} for p in profiles],
          "notes": [notes[k].to_dict() for k in sorted(notes)]}
    return _digest({"listone": list(listone) if listone else None, "voti": [list(r) for r in voti],
                    "advanced": [list(r) for r in advanced], "fixtures": [list(r) for r in fixtures],
                    "settings": list(settings) if settings else None, "kb": kb})


@dataclass(frozen=True)
class RunContext:
    settings_snapshot_id: int
    rules_hash: str
    season_id: int
    team_count: int
    budget: int
    roster_min: int
    roster_max: int
    min_goalkeepers: int
    max_goalkeepers: int
    calculate: dict[str, Any]
    listone_snapshot_id: int


def load_context(con: duckdb.DuckDBPyConnection) -> RunContext:
    row = con.execute("SELECT snapshot_id, rules_hash, season_id, team_count, budget, roster_min, roster_max, payload "
                      "FROM v_league_settings_current").fetchone()
    if row is None:
        raise ValuationError("no league_settings snapshot -- run `fantaclaude sync-league` first")
    payload = row[7] if isinstance(row[7], dict) else json.loads(row[7])
    listone = con.execute("SELECT max(snapshot_id) FROM listone_snapshots").fetchone()[0]
    if listone is None:
        raise ValuationError("no listone snapshot -- run `fantaclaude ingest listone` first")
    missing = [name for name, value in (("season_id", row[2]), ("team_count", row[3]), ("budget", row[4]),
                                        ("roster_min", row[5]), ("roster_max", row[6])) if value is None]
    if missing:
        raise ValuationError(f"league_settings lacks {missing}; the money supply and the bounds are not known")
    rosters = payload.get("rosters") or {}
    minrl, maxrl = rosters.get("minrl") or [None, None], rosters.get("maxrl") or [None, None]
    if minrl[0] is None or maxrl[0] is None:
        raise ValuationError("league_settings.rosters lacks minrl/maxrl; the goalkeeper bounds are not known")
    return RunContext(int(row[0]), str(row[1]), int(row[2]), int(row[3]), int(row[4]), int(row[5]), int(row[6]),
                      int(minrl[0]), int(maxrl[0]), payload.get("calculate") or {}, int(listone))


def _resolve_taker(profile: TeamProfile, candidates: list[Candidate]) -> int | None:
    name = profile.takers.get("penalties")
    if not name:
        return None
    match = Matcher(candidates).match(name)
    return match.player_id


def build_inputs(con: duckdb.DuckDBPyConnection, history: History, profiles: list[TeamProfile],
                 notes: dict[int, PlayerNote], weights: dict[str, tuple[float, ...]]) -> tuple[list[PlayerInputs], list[str]]:
    rows = con.execute("SELECT player_id, name, team_name, team_short, classic_role, mantra_roles, quot_current_mantra, age "
                       "FROM v_players_current ORDER BY player_id").fetchall()
    by_short = {p.team_short: p for p in profiles}
    club_players: dict[str, list[Candidate]] = {}
    for player_id, name, team_name, team_short, *_ in rows:
        club_players.setdefault(team_short, []).append(Candidate(int(player_id), str(name), str(team_short), str(team_name)))
    warnings: list[str] = []
    takers: dict[str, int | None] = {}
    for short, candidates in sorted(club_players.items()):
        profile = by_short.get(short)
        if profile is None:
            warnings.append(f"no profile for {candidates[0].team_name} ({short}): rotation_factor 1.0 assumed")
            takers[short] = None
            continue
        taker = _resolve_taker(profile, candidates)
        if profile.takers.get("penalties") and taker is None:
            warnings.append(f"{profile.team}: penalty taker {profile.takers['penalties']!r} not found in the listone; "
                            f"history stands")
        takers[short] = taker
    inputs: list[PlayerInputs] = []
    for player_id, name, team_name, team_short, classic_role, mantra_roles, quot, age in rows:
        roles = frozenset(Role(r) for r in mantra_roles)
        profile = by_short.get(team_short)
        taker = takers.get(team_short)
        inputs.append(PlayerInputs(
            player_id=int(player_id), name=str(name), team_short=str(team_short), team_name=str(team_name),
            classic_role=str(classic_role), roles=roles, role_class=pin_class(roles, weights),
            quotazione=int(quot or 0), age=None if age is None else int(age), lines=history.lines_for(int(player_id)),
            rotation_factor=profile.rotation_factor if profile else 1.0, note=notes.get(int(player_id)),
            penalty_taker=taker == int(player_id), club_has_taker=taker is not None,
            club_penalty_rate=history.club_penalty_rate.get(str(team_name), 0.0)))
    return inputs, warnings


def build_pool(projections: list[Projection]) -> tuple[PoolPlayer, ...]:
    return tuple(PoolPlayer(p.player_id, p.name, p.role_class, p.value_p25, p.value_p50, p.value_p75, p.quotazione)
                 for p in projections)


def replacement_levels(pool: tuple[PoolPlayer, ...], expected_prices: dict[int, int],
                       cfg: PricingConfig) -> dict[str, float]:
    """Per class, the value of the best player expected to cost the replacement price (one credit);
    the class's weakest player when nobody is that cheap."""
    levels: dict[str, float] = {}
    for cls in {p.role_class for p in pool}:
        players = [p for p in pool if p.role_class == cls]
        cheap = [p.value_p50 for p in players if expected_prices.get(p.player_id, 1) <= cfg.replacement_price]
        levels[cls] = max(cheap) if cheap else min(p.value_p50 for p in players)
    return levels


def assign_tiers(pool: tuple[PoolPlayer, ...], cfg: PricingConfig) -> dict[int, int]:
    tiers: dict[int, int] = {}
    for cls in {p.role_class for p in pool}:
        ranked = sorted((p for p in pool if p.role_class == cls), key=lambda p: (-p.value_p50, p.player_id))
        top, rest = ranked[:cfg.tier_pool], ranked[cfg.tier_pool:]
        gaps = sorted(range(1, len(top)), key=lambda i: top[i - 1].value_p50 - top[i].value_p50, reverse=True)
        cuts = set(gaps[:max(0, cfg.tiers_per_class - 1)])
        tier = 1
        for i, p in enumerate(top):
            if i in cuts:
                tier += 1
            tiers[p.player_id] = tier
        for p in rest:
            tiers[p.player_id] = tier + 1
    return tiers


def divergence(pool: tuple[PoolPlayer, ...]) -> dict[int, tuple[float, float]]:
    """(the value implied by the quotazione, our value minus it): the player at
    quotazione rank i is implied to be worth what our i-th best is worth."""
    out: dict[int, tuple[float, float]] = {}
    for cls in {p.role_class for p in pool}:
        players = [p for p in pool if p.role_class == cls]
        by_quot = sorted(players, key=lambda p: (-p.quotazione, -p.value_p50, p.player_id))
        by_value = sorted(players, key=lambda p: (-p.value_p50, p.player_id))
        for market, ours in zip(by_quot, by_value):
            out[market.player_id] = (ours.value_p50, market.value_p50 - ours.value_p50)
    return out


def new_run_id(now: datetime, rules_hash: str, model_hash_: str) -> str:
    return f"{now:%Y%m%dT%H%M%SZ}-{model_hash_[:4]}{rules_hash[:4]}"


@dataclass(frozen=True)
class ValuationRun:
    run_id: str
    created_at: datetime
    rules_hash: str
    model_hash: str
    inputs_hash: str
    settings_snapshot_id: int
    listone_snapshot_id: int
    season_id: int
    giornata: int
    scenarios: list[Scenario]
    config: dict[str, Any]
    projections: list[Projection]
    pool: tuple[PoolPlayer, ...]
    replacement: dict[str, float]
    vor: dict[int, float]
    tiers: dict[int, int]
    implied: dict[int, tuple[float, float]]
    boards: dict[str, BoardPricing]
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def run_valuation(con: duckdb.DuckDBPyConnection, *, now: datetime, kb_dir: Path, preferences: dict[str, Any],
                  projection_cfg: ProjectionConfig, pricing_cfg: PricingConfig, d_factor: DFactorTable,
                  scenario_names: list[str] | None = None) -> ValuationRun:
    ctx = load_context(con)
    status = modifier_status(ctx.calculate)
    if status.unknown_active:
        raise ValuationError(f"modifier(s) {list(status.unknown_active)} are active in league_settings and this code does "
                             f"not model them -- see the Phase 1 plan, Task 10")
    if status.d_factor and d_factor.is_empty:
        raise ValuationError("the D-Factor is active (calculate.smodd) but core/src/fantaclaude/model/d_factor.yml has no "
                             "bands -- transcribe the league's table first (Phase 1 plan, Task 10)")
    bm = BonusMalus.from_calculate(ctx.calculate)
    sheet = voto_sheet(ctx.calculate)
    # excluded_clubs is hashed into model_hash with the rest of preferences, so a
    # non-empty list would mint a new model_hash, a new run_id and an immutable run
    # incomparable to every earlier one -- while still pricing every player of those
    # clubs, because dropping them from the pool is price_board's `excluded`, which
    # would leave board.prices no longer covering every projection. Refusing is the
    # honest answer until Phase 2 wires it through the exports too.
    excluded = preferences.get("excluded_clubs") or []
    if excluded:
        raise PreferencesError(f"preferences.yml: excluded_clubs {list(excluded)} is not honoured in Phase 1 -- it would "
                               f"change model_hash without changing a single price. Leave it empty; club exclusion lands "
                               f"with the live pool in Phase 2")
    scenarios = load_scenarios(preferences)
    if scenario_names:
        unknown = sorted(set(scenario_names) - {s.name for s in scenarios})
        if unknown:
            raise PreferencesError(f"unknown scenario(s) {unknown}; preferences.yml defines {[s.name for s in scenarios]}")
        scenarios = [s for s in scenarios if s.name in scenario_names]
    history = load_history(con, sheet=sheet, bm=bm, current_season=ctx.season_id)
    if not history.lines:
        raise ValuationError("no voti history at all -- run `fantaclaude ingest stats-web` first")
    giornate_remaining = max(0, SERIE_A_GIORNATE - history.giornate_played)
    profiles, notes = load_profiles(kb_dir), load_player_notes(kb_dir)
    demand = module_demand()
    max_rank = max(pricing_cfg.max_per_class, pricing_cfg.max_goalkeepers)
    base_weights = rank_weights(demand, max_rank=max_rank, bench_weight=pricing_cfg.bench_weight,
                                bench_decay=pricing_cfg.bench_decay, bench_slots=pricing_cfg.bench_slots_per_class)
    inputs, warnings = build_inputs(con, history, profiles, notes, base_weights)
    table = d_factor if status.d_factor else None
    projections = project_all(inputs, cfg=projection_cfg, priors=history.priors, bm=bm,
                              giornate_remaining=giornate_remaining, current_season=ctx.season_id, d_factor=table)
    pool = build_pool(projections)
    minimums = hard_minimums()
    boards: dict[str, BoardPricing] = {}
    for scenario in scenarios:
        weights = rank_weights(demand, max_rank=max_rank, bench_weight=pricing_cfg.bench_weight,
                               bench_decay=pricing_cfg.bench_decay, bench_slots=pricing_cfg.bench_slots_per_class,
                               targets=scenario.target_composition, target_weight=pricing_cfg.target_weight)
        state = PoolState(credits=ctx.budget, market_credits=ctx.team_count * ctx.budget, pool=pool, weights=weights,
                          hard_minimums=minimums, roster_min=ctx.roster_min, roster_max=ctx.roster_max,
                          min_goalkeepers=ctx.min_goalkeepers, max_goalkeepers=ctx.max_goalkeepers,
                          targets=scenario.target_composition, class_budget_share=scenario.max_budget_share_per_role)
        boards[scenario.name] = price_board(state, pricing_cfg, exact=True)
    reference = boards[scenarios[0].name]
    replacement = replacement_levels(pool, reference.expected_prices, pricing_cfg)
    vor = {p.player_id: max(0.0, p.value_p50 - replacement[p.role_class]) for p in pool}
    hashes = (model_hash(projection_cfg, pricing_cfg, preferences, d_factor), inputs_hash(con, profiles=profiles, notes=notes))
    # The scenarios actually run, beside the preferences that define them all: a
    # filtered run priced one board, and its immutable config must say so rather than
    # let preferences.scenarios imply three. It is deliberately not in model_hash --
    # the model is the same, so a filtered run stays comparable to a full one.
    config = {"projection": projection_cfg.to_dict(), "pricing": pricing_cfg.to_dict(), "preferences": preferences,
              "scenarios": [s.name for s in scenarios], "d_factor": d_factor.to_dict(),
              "model_version": MODEL_VERSION, "sheet": sheet, "bonus_malus": bm.to_dict(),
              "modifiers": status.to_dict()}
    summary = {"players": len(pool), "team_count": ctx.team_count, "budget": ctx.budget,
               "market_credits": ctx.team_count * ctx.budget, "giornate_played": history.giornate_played,
               "giornate_remaining": giornate_remaining, "sheet": sheet, "d_factor_active": status.d_factor,
               "scenarios": {name: {"inflation": b.inflation, "composition": b.composition,
                                    "credits_by_class": b.credits_by_class, "reserve": b.reserve,
                                    "targets_departed": list(b.targets_departed)} for name, b in boards.items()},
               "warnings": warnings}
    run_id = base = new_run_id(now, ctx.rules_hash, hashes[0])
    taken = {r[0] for r in con.execute("SELECT run_id FROM valuation_runs WHERE run_id LIKE ?", [base + "%"]).fetchall()}
    suffix = 2
    while run_id in taken:                     # the stamp has one-second resolution; two runs in a second are both kept
        run_id = f"{base}-{suffix}"
        suffix += 1
    return ValuationRun(run_id=run_id, created_at=now, rules_hash=ctx.rules_hash,
                        model_hash=hashes[0], inputs_hash=hashes[1], settings_snapshot_id=ctx.settings_snapshot_id,
                        listone_snapshot_id=ctx.listone_snapshot_id, season_id=ctx.season_id,
                        giornata=history.giornate_played, scenarios=scenarios, config=config, projections=projections,
                        pool=pool, replacement=replacement, vor=vor, tiers=assign_tiers(pool, pricing_cfg),
                        implied=divergence(pool), boards=boards, warnings=warnings, summary=summary)


def record_run(con: duckdb.DuckDBPyConnection, run: ValuationRun) -> None:
    """Append the run: runs, one valuation row per player, one price row per scenario and player. Never updates."""
    con.begin()
    try:
        con.execute("INSERT INTO valuation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON)",
                    [run.run_id, to_db(run.created_at), run.rules_hash, run.model_hash, run.inputs_hash,
                     run.settings_snapshot_id, run.listone_snapshot_id, run.season_id, run.giornata,
                     [s.name for s in run.scenarios], canonical_json(_finite(run.config)),
                     canonical_json(_finite(run.summary))])
        con.executemany(
            "INSERT INTO valuations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[run.run_id, p.player_id, p.name, p.team_short, p.classic_role, p.role_class, list(p.roles), p.exp_presenze,
              p.exp_fantamedia, p.exp_voto, p.value_p25, p.value_p50, p.value_p75, run.replacement[p.role_class],
              run.vor[p.player_id], run.tiers[p.player_id], p.quotazione, run.implied[p.player_id][0],
              run.implied[p.player_id][1], canonical_json(_finite(p.explain))] for p in run.projections])
        con.executemany(
            "INSERT INTO valuation_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[run.run_id, name, price.player_id, price.role_class, price.expected_price, price.band.p25, price.band.p50,
              price.band.p75, price.walk_value, price.exact, canonical_json(_finite(price.to_dict()))]
             for name, board in run.boards.items() for price in board.prices.values()])
    except Exception:
        con.rollback()
        raise
    con.commit()
```

`walk_value` can be `-inf` (no completion without him); the `DOUBLE` column stores it as is, and `_finite` turns it into `null` inside the JSON payloads, which DuckDB's JSON type would otherwise refuse.

- [ ] **Step 5: Run the valuation tests**

Run: `uv run pytest core/tests/test_valuation.py -q`
Expected: 11 passed. `test_run_valuation_projects_prices_and_stamps` asserts `giornate_remaining == 37` because `_ready_workspace` records one giornata of season 21; `test_missing_profiles...` rewrites `test_kb_profiles.PROFILE`'s penalty taker to `Nobody`, a name no club carries, hence the warning — `Calhanoglu` himself is listone id 2194 and resolves, but only within Inter's own players, so in `test_run_valuation...` the other seven clubs warn instead.

- [ ] **Step 6: Write the failing export tests**

Append to `core/tests/test_valuation.py`:

```python
def test_exports_render_the_run_and_records_keep_it(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.analysis.exports import (
        export_records,
        write_asta_plan,
        write_rankings,
    )

    seeded(tmp_path, fixture_json, mcp_fixture_json)
    prefs = {**PREFS, "scenarios": {"aggressive-attack": {"target_composition": {"A": 2, "Pc": 2}, "risk_appetite": "aggressive"},
                                    "value-hunting": {"risk_appetite": "cautious"}}}
    result, con = run(tmp_path, preferences=prefs)
    try:
        record_run(con, result)
        exports = tmp_path / "data" / "exports"
        md, csv = write_rankings(result, exports)
        plan = write_asta_plan(result, exports)
        assert md == exports / "rankings.md" and csv == exports / "rankings.csv" and plan == exports / "asta-plan.md"
        text = md.read_text(encoding="utf-8")
        assert result.run_id in text and "Martinez L." in text and "## Pc" in text and "rules " + result.rules_hash in text
        lines = csv.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("run_id,player_id,name,team,classic_role,role_class,roles,tier,")
        assert len(lines) == 18 and lines[1].startswith(result.run_id)
        plan_text = plan.read_text(encoding="utf-8")
        for name in ("balanced", "aggressive-attack", "value-hunting"):
            assert f"## {name}" in plan_text
        assert "bid to p75" in plan_text and "bid to p25" in plan_text and "Composition" in plan_text
        assert "We disagree with the market" in plan_text and "Cheap value" in plan_text and "If I lose him" in plan_text

        records = tmp_path / "records"
        written = export_records(con, result.run_id, result.rules_hash, records)
        names = sorted(p.relative_to(records).as_posix() for p in written)
        assert names == [f"league_settings/{result.rules_hash}.parquet", f"valuation_prices/{result.run_id}.parquet",
                         f"valuation_runs/{result.run_id}.parquet", f"valuations/{result.run_id}.parquet"]
        back = con.execute(f"SELECT count(*) FROM read_parquet('{records / 'valuations' / (result.run_id + '.parquet')}')").fetchone()[0]
        assert back == 17
        again = export_records(con, result.run_id, result.rules_hash, records)      # never rewritten
        assert again == []
    finally:
        con.close()
```

- [ ] **Step 7: Write the exports module**

Create `core/src/fantaclaude/analysis/exports.py`:

```python
"""Renderings of a run: rankings.md / rankings.csv and the asta plan under
data/exports/ (regenerable, rewritten by every rank), and the durable
parquet copies under records/ (committed, named by run_id / rules_hash,
never rewritten -- live-event requirement 5: a journal entry that links a
run_id nothing can resolve is worthless)."""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from fantaclaude.analysis.valuation import ValuationRun
from fantaclaude.model.demand import ROLE_CLASSES

CSV_COLUMNS = ("run_id", "player_id", "name", "team", "classic_role", "role_class", "roles", "tier", "exp_presenze",
               "exp_fantamedia", "value_p25", "value_p50", "value_p75", "vor", "quot_mantra", "expected_price",
               "max_p25", "max_p50", "max_p75", "implied_value", "divergence")


def _rows(run: ValuationRun, scenario: str) -> list[dict]:
    board = run.boards[scenario]
    rows = []
    for p in run.projections:
        price = board.prices[p.player_id]
        implied, div = run.implied[p.player_id]
        rows.append({"run_id": run.run_id, "player_id": p.player_id, "name": p.name, "team": p.team_short,
                     "classic_role": p.classic_role, "role_class": p.role_class, "roles": ";".join(p.roles),
                     "tier": run.tiers[p.player_id], "exp_presenze": round(p.exp_presenze, 1),
                     "exp_fantamedia": round(p.exp_fantamedia, 2), "value_p25": round(p.value_p25, 1),
                     "value_p50": round(p.value_p50, 1), "value_p75": round(p.value_p75, 1),
                     "vor": round(run.vor[p.player_id], 1), "quot_mantra": p.quotazione,
                     "expected_price": price.expected_price, "max_p25": price.band.p25, "max_p50": price.band.p50,
                     "max_p75": price.band.p75, "implied_value": round(implied, 1), "divergence": round(div, 1)})
    return rows


def _header(run: ValuationRun) -> list[str]:
    s = run.summary
    return [f"run `{run.run_id}` · rules {run.rules_hash} · model {run.model_hash} · inputs {run.inputs_hash}",
            f"{s['team_count']} teams × {s['budget']} credits = {s['market_credits']} on the market · "
            f"giornata {s['giornate_played']} played, {s['giornate_remaining']} remaining · voti sheet {s['sheet']}"
            + (" · D-Factor active" if s.get("d_factor_active") else ""),
            *(f"warning: {w}" for w in run.warnings)]


def write_rankings(run: ValuationRun, exports_dir: Path) -> tuple[Path, Path]:
    exports_dir.mkdir(parents=True, exist_ok=True)
    scenario = run.scenarios[0].name
    rows = _rows(run, scenario)
    board = run.boards[scenario]
    lines = ["# Rankings", "", *_header(run), f"inflation {board.inflation:.2f} · composition "
             + ", ".join(f"{cls} {n}" for cls, n in board.composition.items() if n) + f" · reserve {board.reserve}", ""]
    for cls in ROLE_CLASSES:
        ranked = sorted((r for r in rows if r["role_class"] == cls), key=lambda r: -r["value_p50"])
        if not ranked:
            continue
        lines += [f"## {cls}  (replacement {run.replacement.get(cls, 0.0):.0f})", "",
                  "| # | player | team | roles | tier | pres | fm | value p50 (p25–p75) | VOR | quot | exp | max p25/p50/p75 | Δ market |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for i, r in enumerate(ranked, 1):
            lines.append(f"| {i} | {r['name']} | {r['team']} | {r['roles']} | {r['tier']} | {r['exp_presenze']} | "
                         f"{r['exp_fantamedia']} | {r['value_p50']} ({r['value_p25']}–{r['value_p75']}) | {r['vor']} | "
                         f"{r['quot_mantra']} | {r['expected_price']} | {r['max_p25']}/{r['max_p50']}/{r['max_p75']} | "
                         f"{r['divergence']:+} |")
        lines.append("")
    md = exports_dir / "rankings.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    out = exports_dir / "rankings.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (ROLE_CLASSES.index(r["role_class"]), -r["value_p50"])))
    return md, out


def write_asta_plan(run: ValuationRun, exports_dir: Path) -> Path:
    exports_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Asta plan", "", *_header(run), ""]
    for scenario in run.scenarios:
        board = run.boards[scenario.name]
        q = scenario.quantile
        rows = _rows(run, scenario.name)
        lines += [f"## {scenario.name}", "",
                  f"Risk appetite {scenario.risk_appetite}: bid to {q}. Inflation {board.inflation:.2f}, reserve {board.reserve}."
                  + (f" Departed from the target at {', '.join(board.targets_departed)}." if board.targets_departed else ""),
                  "", "**Composition** (players · credits): "
                  + ", ".join(f"{cls} {n} · {board.credits_by_class.get(cls, 0)}" for cls, n in board.composition.items() if n),
                  "", "**Targets per class** (max price at the chosen quantile, tier):", ""]
        for cls in ROLE_CLASSES:
            ranked = sorted((r for r in rows if r["role_class"] == cls), key=lambda r: -r["value_p50"])[:3]
            if ranked:
                lines.append(f"- {cls}: " + ", ".join(f"{r['name']} {r['max_' + q]} (t{r['tier']})" for r in ranked))
        lines.append("")
    rows = _rows(run, run.scenarios[0].name)
    cheap = sorted((r for r in rows if r["expected_price"] <= 5 and r["vor"] > 0),
                   key=lambda r: -r["vor"] / r["expected_price"])[:10]
    lines += ["## Cheap value", "", *(f"- {r['name']} ({r['role_class']}, {r['team']}): VOR {r['vor']} at ~{r['expected_price']}"
                                       for r in cheap), ""]
    diverging = sorted(rows, key=lambda r: -abs(r["divergence"]))[:10]
    lines += ["## We disagree with the market", "",
              *(f"- {r['name']} ({r['role_class']}): we say {r['value_p50']}, the quotazione implies {r['implied_value']} "
                f"({r['divergence']:+})" for r in diverging), ""]
    lines += ["## If I lose him", ""]
    for cls in ROLE_CLASSES:
        ranked = sorted((r for r in rows if r["role_class"] == cls), key=lambda r: -r["value_p50"])
        if ranked:
            top = ranked[0]
            mates = [r["name"] for r in ranked[1:] if r["tier"] == top["tier"]][:3]
            lines.append(f"- {cls}: {top['name']} → " + (", ".join(mates) if mates else "nobody in his tier"))
    path = exports_dir / "asta-plan.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _literal(value: str) -> str:
    """A SQL string literal: COPY does not take bound parameters, so the two
    keys are inlined -- both are hex/timestamp identifiers, escaped anyway."""
    return "'" + value.replace("'", "''") + "'"


def export_records(con: duckdb.DuckDBPyConnection, run_id: str, rules_hash: str, records_dir: Path) -> list[Path]:
    """Parquet copies of the run's rows and of the settings row it used; a file that exists is left alone."""
    run, rules = _literal(run_id), _literal(rules_hash)
    targets = [
        (records_dir / "valuation_runs" / f"{run_id}.parquet", f"SELECT * FROM valuation_runs WHERE run_id = {run}"),
        (records_dir / "valuations" / f"{run_id}.parquet", f"SELECT * FROM valuations WHERE run_id = {run}"),
        (records_dir / "valuation_prices" / f"{run_id}.parquet", f"SELECT * FROM valuation_prices WHERE run_id = {run}"),
        (records_dir / "league_settings" / f"{rules_hash}.parquet",
         f"SELECT * FROM league_settings WHERE rules_hash = {rules} ORDER BY snapshot_id DESC LIMIT 1"),
    ]
    written: list[Path] = []
    for path, query in targets:
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY ({query}) TO {_literal(path.as_posix())} (FORMAT PARQUET)")
        written.append(path)
    return written
```

- [ ] **Step 8: Update `records/README.md`**

```markdown
# records/

Durable, committed exports — what a journal entry links to by `run_id` must
be resolvable from here even if `data/` is lost:

- `valuation_runs/<run_id>.parquet`, `valuations/<run_id>.parquet`,
  `valuation_prices/<run_id>.parquet` — one valuation run, written by
  `fantaclaude rank`, never rewritten.
- `league_settings/<rules_hash>.parquet` — the settings row a run used.
- the auction snapshot between the auction and the confirmed transfer into
  the lega (Phase 2).

Everything in `data/` is gitignored and rebuildable; commit this directory
after every `rank` you intend to keep. Read them back with
`fantaclaude query --sql "SELECT * FROM read_parquet('records/valuations/<run_id>.parquet')"`.
```

- [ ] **Step 9: Run the tests, lint, full suite, commit**

Run: `uv run pytest core/tests/test_valuation.py -q && uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: 12 passed; ruff silent; core 287 passed.

```bash
git add core/src/fantaclaude/analysis/valuation.py core/src/fantaclaude/analysis/exports.py core/tests/test_valuation.py preferences.yml records/README.md
git commit -m "feat(analysis): the valuation run -- VOR, tiers, the divergence check, two hashes, rankings and asta-plan exports, records/ parquet"
```

---
### Task 9: `fantaclaude rank`, supersession in `sync-league`, the doctor's five new checks, the docs

**Files:**
- Create: `core/src/fantaclaude/commands/rank.py`, `core/tests/test_rank_cli.py`
- Modify: `core/src/fantaclaude/cli/app.py`, `core/src/fantaclaude/commands/sync_league.py`, `core/src/fantaclaude/commands/doctor.py`, `core/tests/test_doctor.py`, `core/tests/test_sync_league.py`, `core/tests/test_kb_profiles.py:107-129` (the doctor call sites gain `pricing`), `core/README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `run_valuation`, `record_run`, `write_rankings`, `write_asta_plan`, `export_records`, `load_pricing_config`, `load_d_factor`, `load_scenarios`, `PreferencesError`, `ValuationError`, `load_league_yml`, `load_player_notes`, `misplaced_notes`, `load_participants`, `voto_sheet`, `BonusMalus`, `modifier_status`; `fantaclaude.commands.ingest.NotReady`; `prepare_sync`/`apply_sync`.
- Produces: `RankReport(run_id, created_at, rules_hash, model_hash, inputs_hash, season_id, giornata, scenarios, players, exports, records, warnings, summary, provisional)` with `to_dict()`; `provisional_note(entries, now, team_count) -> str`; `rank(con, *, now, kb_dir, preferences_path, pricing_path, exports_dir, records_dir, league_yml=None, scenarios=None) -> RankReport` (raises `NotReady`, `PreferencesError`); CLI `fantaclaude rank [--offline] [--scenario NAME]… [--json] [--league ALIAS]`; `SyncReport.superseded_runs: int`; `DoctorPaths.pricing`; doctor checks `kb_notes`, `kb_participants`, `scoring`, `pricing`, `valuations`.

- [ ] **Step 1: Write the failing rank tests**

Create `core/tests/test_rank_cli.py`:

```python
import json
from datetime import UTC, datetime

from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.rank import provisional_note
from fantaclaude.db.connection import connect
from fantaclaude.league.league_yml import load_league_yml
from test_valuation import seeded
from typer.testing import CliRunner

runner = CliRunner()


def _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    (tmp_path / "pricing.yml").write_text("bench_weight: 0.12\n")
    (tmp_path / "preferences.yml").write_text(
        "risk_appetite: balanced\nmax_budget_share_per_role: {}\nexcluded_clubs: []\ntarget_composition: {Por: 2}\n"
        "scenarios:\n  aggressive-attack: {target_composition: {A: 2, Pc: 2}, risk_appetite: aggressive}\n"
        "  value-hunting: {risk_appetite: cautious}\n")
    (tmp_path / "league.yml").write_text(
        "budget: {value: 500, source: admin, verified_on: 2026-08-24}\n"
        "auction: {date: {value: 2026-09-05, source: admin, verified_on: 2026-08-22, note: approximate}}\n")


def test_rank_offline_writes_a_run_renders_and_records(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["rank", "--offline", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["players"] == 17 and payload["scenarios"] == ["balanced", "aggressive-attack", "value-hunting"]
    assert payload["run_id"].endswith(payload["model_hash"][:4] + payload["rules_hash"][:4])
    assert sorted(p.rsplit("/", 1)[-1] for p in payload["exports"]) == ["asta-plan.md", "rankings.csv", "rankings.md"]
    assert len(payload["records"]) == 4 and all(p.endswith(".parquet") for p in payload["records"])
    assert payload["provisional"].startswith("provisional")
    assert (tmp_path / "data" / "exports" / "rankings.md").is_file()
    assert (tmp_path / "records" / "valuations" / f"{payload['run_id']}.parquet").is_file()
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM valuation_prices").fetchone()[0] == 17 * 3
    assert con.execute("SELECT run_id FROM v_valuations_current LIMIT 1").fetchone()[0] == payload["run_id"]
    con.close()

    plain = runner.invoke(app, ["rank", "--offline"])
    assert plain.exit_code == ExitCode.OK, plain.output
    assert "run " in plain.stdout and "balanced" in plain.stdout and "provisional" in plain.stdout
    assert "Martinez L." in plain.stdout

    one = runner.invoke(app, ["rank", "--offline", "--scenario", "value-hunting", "--json"])
    assert one.exit_code == ExitCode.OK and json.loads(one.stdout)["scenarios"] == ["value-hunting"]
    bad = runner.invoke(app, ["rank", "--offline", "--scenario", "nope"])
    assert bad.exit_code == ExitCode.USAGE and "nope" in bad.stderr


def test_rank_re_syncs_first_unless_offline(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    calls = []

    def fake_run_with_api(fn):
        import asyncio

        calls.append("sync")
        return asyncio.run(fn(fake_api()))

    monkeypatch.setattr("fantaclaude.api_client.run_with_api", fake_run_with_api)
    result = runner.invoke(app, ["rank", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    assert calls == ["sync"] and json.loads(result.stdout)["players"] == 17

    calls.clear()
    assert runner.invoke(app, ["rank", "--offline", "--json"]).exit_code == ExitCode.OK and calls == []

    # a league.yml that disagrees with the API refuses the whole command, before any run is written
    (tmp_path / "league.yml").write_text("budget: {value: 999, source: admin, verified_on: 2026-08-24}\n")
    conflict = runner.invoke(app, ["rank"])
    assert conflict.exit_code == ExitCode.CONFLICT and "CONFLICT budget" in conflict.stdout
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0] == 2
    con.close()


def test_rank_refuses_when_not_ready(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    assert runner.invoke(app, ["rank", "--offline"]).exit_code == ExitCode.NOT_READY

    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    (tmp_path / "pricing.yml").write_text("bench_weight: heavy\n")
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY and "pricing.yml" in result.stderr

    (tmp_path / "pricing.yml").write_text("bench_weight: 0.12\n")
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["smodf"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    result = runner.invoke(app, ["rank", "--offline"])
    assert result.exit_code == ExitCode.NOT_READY and "smodf" in result.stderr


def test_provisional_note_reads_the_auction_date(tmp_path):
    (tmp_path / "league.yml").write_text(
        "auction: {date: {value: 2026-09-05, source: admin, verified_on: 2026-08-22}}\n")
    entries = load_league_yml(tmp_path / "league.yml")
    early = provisional_note(entries, datetime(2026, 8, 30, tzinfo=UTC), 8)
    assert early.startswith("provisional") and "8 teams" in early and "6 days" in early
    late = provisional_note(entries, datetime(2026, 9, 4, 12, tzinfo=UTC), 10)
    assert late.startswith("final window") and "10 teams" in late
    assert provisional_note(None, datetime(2026, 8, 30, tzinfo=UTC), 8).startswith("provisional")
```

- [ ] **Step 2: Run the rank tests to verify they fail**

Run: `uv run pytest core/tests/test_rank_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.commands.rank`.

- [ ] **Step 3: Write the rank command and wire the CLI**

Create `core/src/fantaclaude/commands/rank.py`:

```python
"""fantaclaude rank: write a valuation run, render the exports, copy the records.

Importable on purpose -- the CLI and, later, the FastAPI server call this
function; the CLI adds only the re-sync, argument parsing and rendering.
Every run before the freeze is provisional (spec, open question 1): the
report says so, from league.yml's auction date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fantaclaude.analysis.exports import export_records, write_asta_plan, write_rankings
from fantaclaude.analysis.projection import ProjectionConfig
from fantaclaude.analysis.valuation import ValuationError, record_run, run_valuation
from fantaclaude.asta.pricing_config import PricingConfigError, load_pricing_config
from fantaclaude.commands.ingest import NotReady
from fantaclaude.league.league_yml import Provenanced
from fantaclaude.model.d_factor import DFactorTableError, load_d_factor

FINAL_WINDOW_DAYS = 2


@dataclass(frozen=True)
class RankReport:
    run_id: str
    created_at: datetime
    rules_hash: str
    model_hash: str
    inputs_hash: str
    season_id: int
    giornata: int
    scenarios: list[str]
    players: int
    exports: list[str]
    records: list[str]
    warnings: list[str]
    summary: dict[str, Any]
    provisional: str
    top: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "created_at": self.created_at.isoformat(), "rules_hash": self.rules_hash,
                "model_hash": self.model_hash, "inputs_hash": self.inputs_hash, "season_id": self.season_id,
                "giornata": self.giornata, "scenarios": self.scenarios, "players": self.players,
                "exports": self.exports, "records": self.records, "warnings": self.warnings,
                "summary": self.summary, "provisional": self.provisional, "top": self.top}


def provisional_note(entries: dict[str, Provenanced] | None, now: datetime, team_count: int) -> str:
    auction = entries.get("auction.date") if entries else None
    when = auction.value if auction is not None and isinstance(auction.value, date) else None
    if when is None:
        return f"provisional: {team_count} teams, auction date unknown -- the final run is the one after the freeze"
    days = (when - now.date()).days
    if days <= FINAL_WINDOW_DAYS:
        return f"final window: {team_count} teams, auction {when.isoformat()} in {days} days"
    return (f"provisional: {team_count} teams, auction {when.isoformat()} in {days} days -- "
            f"re-run after the freeze, when the rules and the teams have settled")


def _load_preferences(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise NotReady(f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise NotReady(f"{path} does not parse: {exc}") from None
    if not isinstance(data, dict):
        raise NotReady(f"{path}: the top level must be a mapping")
    return data


def rank(con: duckdb.DuckDBPyConnection, *, now: datetime, kb_dir: Path, preferences_path: Path, pricing_path: Path,
         exports_dir: Path, records_dir: Path, league_yml: dict[str, Provenanced] | None = None,
         scenarios: list[str] | None = None) -> RankReport:
    preferences = _load_preferences(preferences_path)
    try:
        pricing_cfg = load_pricing_config(pricing_path)
    except PricingConfigError as exc:
        raise NotReady(f"pricing.yml: {exc}") from None
    try:
        d_factor = load_d_factor()
    except DFactorTableError as exc:
        raise NotReady(str(exc)) from None
    try:
        run = run_valuation(con, now=now, kb_dir=kb_dir, preferences=preferences, projection_cfg=ProjectionConfig(),
                            pricing_cfg=pricing_cfg, d_factor=d_factor, scenario_names=scenarios)
    except ValuationError as exc:
        raise NotReady(str(exc)) from None
    record_run(con, run)
    md, csv = write_rankings(run, exports_dir)
    plan = write_asta_plan(run, exports_dir)
    records = export_records(con, run.run_id, run.rules_hash, records_dir)
    board = run.boards[run.scenarios[0].name]
    top: dict[str, list[dict[str, Any]]] = {}
    for p in sorted(run.projections, key=lambda p: -p.value_p50):
        entry = top.setdefault(p.role_class, [])
        if len(entry) < 3:
            entry.append({"name": p.name, "team": p.team_short, "value_p50": round(p.value_p50, 1),
                          "max_p50": board.prices[p.player_id].band.p50, "tier": run.tiers[p.player_id]})
    return RankReport(run_id=run.run_id, created_at=run.created_at, rules_hash=run.rules_hash,
                      model_hash=run.model_hash, inputs_hash=run.inputs_hash, season_id=run.season_id,
                      giornata=run.giornata, scenarios=[s.name for s in run.scenarios], players=len(run.projections),
                      exports=[str(md), str(csv), str(plan)], records=[str(p) for p in records],
                      warnings=list(run.warnings), summary=run.summary,
                      provisional=provisional_note(league_yml, now, run.summary["team_count"]), top=top)
```

In `core/src/fantaclaude/cli/app.py`, add after the `doctor` command:

```python
SCENARIO_OPTION = typer.Option(
    None, "--scenario", help="Only these scenarios from preferences.yml (repeatable). Default: all of them.")


def _render_rank(payload: dict) -> str:
    s = payload["summary"]
    lines = [(f"run {payload['run_id']} · rules {payload['rules_hash']} · model {payload['model_hash']} · "
              f"inputs {payload['inputs_hash']}"),
             (f"{payload['players']} players · {s['team_count']} teams × {s['budget']} credits · giornata "
              f"{s['giornate_played']} played · voti sheet {s['sheet']}"
              + (" · D-Factor active" if s.get("d_factor_active") else "")),
             payload["provisional"]]
    for name, sc in s["scenarios"].items():
        comp = ", ".join(f"{cls} {n}·{sc['credits_by_class'].get(cls, 0)}" for cls, n in sc["composition"].items() if n)
        departed = f" (departed from the target at {', '.join(sc['targets_departed'])})" if sc["targets_departed"] else ""
        lines.append(f"{name}: inflation {sc['inflation']:.2f}, reserve {sc['reserve']}, composition {comp}{departed}")
    for cls, entries in payload["top"].items():
        lines.append(f"  {cls}: " + ", ".join(f"{e['name']} ({e['team']}) {e['value_p50']} → max {e['max_p50']} t{e['tier']}"
                                             for e in entries))
    for w in payload["warnings"]:
        lines.append(f"warning: {w}")
    lines.append("exports: " + ", ".join(payload["exports"]))
    lines.append(("records: " + ", ".join(payload["records"]) + " -- commit records/") if payload["records"]
                 else "records: already present")
    return "\n".join(lines)


@app.command("rank")
def rank_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    offline: bool = typer.Option(False, "--offline", help="Do not re-sync league_settings from the league API first."),
    scenario: list[str] | None = SCENARIO_OPTION,
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Write a valuation run: project every listone player, price the board, render data/exports/ and records/. Re-syncs the league first unless --offline."""
    from fantaclaude.analysis.valuation import PreferencesError
    from fantaclaude.commands.ingest import NotReady
    from fantaclaude.commands.rank import rank
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
    from fantaclaude.paths import (
        exports_dir,
        kb_dir,
        league_yml_path,
        preferences_yml_path,
        pricing_yml_path,
        records_dir,
    )
    from fantaclaude.timeutil import utc_now

    try:
        entries = load_league_yml(league_yml_path()) if league_yml_path().is_file() else None
    except LeagueYmlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    snap = conflicts = None
    if not offline:
        from fantaclaude.api_client import run_with_api
        from fantaclaude.commands.sync_league import apply_sync, prepare_sync

        # Fetch before opening the database, as sync-league does: the write lock must not span the network.
        snap, conflicts = run_with_api(lambda api: prepare_sync(api, entries, league=league))
        if conflicts:
            emit(apply_sync(None, snap, conflicts).to_dict(), json_=json_, render=_render_sync)
            raise typer.Exit(code=ExitCode.CONFLICT)
    con = connect()
    try:
        apply_schema(con)
        if snap is not None:
            apply_sync(con, snap, [])
        try:
            report = rank(con, now=utc_now(), kb_dir=kb_dir(), preferences_path=preferences_yml_path(),
                          pricing_path=pricing_yml_path(), exports_dir=exports_dir(), records_dir=records_dir(),
                          league_yml=entries, scenarios=list(scenario) if scenario else None)
        except NotReady as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
        except PreferencesError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.USAGE) from None
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_rank)
```

Update the `doctor` command's help and `DoctorPaths` construction to pass `pricing=pricing_yml_path()` (Step 6 adds the field).

- [ ] **Step 4: Run the rank tests**

Run: `uv run pytest core/tests/test_rank_cli.py -q`
Expected: 4 passed. In `test_rank_re_syncs_first_unless_offline`, the re-sync records a snapshot whose `rules_hash` equals the seeded one (same fixtures), so `changed` is false and the run count stays consistent: two runs written before the conflict, none after.

- [ ] **Step 5: Supersession in `sync-league`**

In `core/src/fantaclaude/commands/sync_league.py`, add `superseded_runs: int = 0` to `SyncReport` (after `diff`), include `"superseded_runs": self.superseded_runs` in `to_dict()`, and in `apply_sync`, after `result = record_snapshot(...)`:

```python
    superseded = 0
    if result.changed:
        superseded = con.execute("SELECT count(*) FROM valuation_runs WHERE rules_hash <> ?",
                                 [snap.rules_hash]).fetchone()[0]
    return SyncReport(snap.league_id, snap.season_id, snap.team_count, snap.rules_hash,
                      changed=result.changed, snapshot_id=result.snapshot_id,
                      previous_hash=result.previous_hash, diff=result.diff, superseded_runs=int(superseded))
```

In `cli/app.py` `_render_sync`, after the diff lines inside `if payload["changed"]:`:

```python
        if payload.get("superseded_runs"):
            lines.append(f"{payload['superseded_runs']} valuation run(s) computed under the old rules are now superseded "
                         f"-- re-run `fantaclaude rank`")
```

Add to `core/tests/test_sync_league.py`:

```python
def test_a_rule_change_reports_the_runs_it_supersedes(db, mcp_fixture_json, fake_api):
    import asyncio

    from fantaclaude.commands.sync_league import sync_league

    first = asyncio.run(sync_league(fake_api(), db, None))
    assert first.changed and first.superseded_runs == 0
    db.execute("INSERT INTO valuation_runs VALUES ('r1', now(), ?, 'm', 'i', 1, 1, 21, 2, ['balanced'], '{}', '{}')",
               [first.rules_hash])
    unchanged = asyncio.run(sync_league(fake_api(), db, None))
    assert not unchanged.changed and unchanged.superseded_runs == 0
    rosters = mcp_fixture_json("roster_settings")
    rosters["budg"] = 600
    changed = asyncio.run(sync_league(fake_api({"roster_settings": rosters}), db, None))
    assert changed.changed and changed.superseded_runs == 1 and changed.to_dict()["superseded_runs"] == 1
    assert db.execute("SELECT superseded FROM v_valuation_runs WHERE run_id = 'r1'").fetchone()[0] is True
```

Run: `uv run pytest core/tests/test_sync_league.py -q` — expected: all pass.

- [ ] **Step 6: The doctor's five new checks**

In `core/tests/test_doctor.py`: extend `NAMES` to end with `"kb_profiles", "kb_notes", "kb_participants", "scoring", "pricing", "valuations"`; give `_paths` a `pricing=root / "pricing.yml"` argument; make `_ready_workspace` write `(root / "pricing.yml").write_text("bench_weight: 0.12\n")`; change the ready-workspace expectation to `assert [c.name for c in checks if not c.ok] == ["fixtures", "kb_profiles", "valuations"]`; and append:

```python
def test_the_phase_1_checks(tmp_path, fixture_json, mcp_fixture_json):
    from test_kb_participants import _write as write_dossier
    from test_kb_profiles import _write as write_profile
    from test_valuation import PREFS, run

    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["kb_notes"].ok and by["kb_notes"].detail == "0 notes"
    assert by["kb_participants"].ok and by["kb_participants"].detail == "0 dossiers; league.yml maps 0"
    assert by["scoring"].ok and "sheet Fantacalcio" in by["scoring"].detail and "no modifier active" in by["scoring"].detail
    assert by["pricing"].ok and "bench_weight 0.12" in by["pricing"].detail
    assert not by["valuations"].ok and "fantaclaude rank" in by["valuations"].detail

    kb = tmp_path / "kb"
    note_dir = kb / "serie-a" / "teams" / "napoli" / "players"
    note_dir.mkdir(parents=True)
    (note_dir / "martinez-l.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                            "player_id: 2764\nname: Martinez L.\nteam_short: INT\ndepth: starter\n---\n# n\n")
    write_dossier(kb, "Marco")
    (tmp_path / "league.yml").write_text("budget: {value: 500, source: admin, verified_on: 2026-08-24}\n"
                                         "participants:\n  Anna: {value: kb/league/participants/anna.md, source: interview, verified_on: 2026-09-01}\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["kb_notes"].ok and "napoli" in by["kb_notes"].detail and "inter" in by["kb_notes"].detail
    assert not by["kb_participants"].ok and "Anna" in by["kb_participants"].detail
    (tmp_path / "pricing.yml").write_text("bench_weight: heavy\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["pricing"].ok

    for name, short in (("Cagliari", "CAG"), ("Roma", "ROM"), ("Inter", "INT"), ("Milan", "MIL"), ("Fiorentina", "FIO"),
                        ("Napoli", "NAP"), ("Genoa", "GEN")):
        write_profile(kb, name, short, europe="none", rotation="1.0")
    write_profile(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85")
    (tmp_path / "pricing.yml").write_text("bench_weight: 0.12\n")
    (note_dir / "martinez-l.md").unlink()
    result, con = run(tmp_path, preferences=PREFS)
    from fantaclaude.analysis.valuation import record_run

    record_run(con, result)
    con.close()
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["valuations"].ok and result.run_id in by["valuations"].detail and "not superseded" in by["valuations"].detail

    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["smodf"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON, rules_hash = 'ffffffffffffffff' WHERE snapshot_id = 1",
                [json.dumps(payload)])
    con.close()
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["scoring"].ok and "smodf" in by["scoring"].detail
    assert not by["valuations"].ok and "superseded" in by["valuations"].detail
```

`test_valuation.run` closes nothing on success and returns the open connection, which this test uses for `record_run` and then closes. In `core/src/fantaclaude/commands/doctor.py`: add `pricing: Path` to `DoctorPaths`; import `load_player_notes`, `misplaced_notes`, `NoteError`, `load_participants`, `ParticipantError`, `load_pricing_config`, `PricingConfigError`, `BonusMalus`, `ScoringError`, `modifier_status`, `voto_sheet`, `load_d_factor`, `DFactorTableError`; add four functions and call them at the end of `run_doctor` (after `_profiles_check`), in this order: `_notes_check(paths.kb, paths.db)`, `_participants_check(paths.kb, paths.league_yml)`, `_scoring_check(paths.db)`, `_pricing_check(paths.pricing)`, `_valuations_check(paths.db, now)`.

```python
def _read_only(db: Path) -> duckdb.DuckDBPyConnection | None:
    if not db.is_file():
        return None
    try:
        return duckdb.connect(str(db), read_only=True)
    except duckdb.Error:
        return None


def _notes_check(kb: Path, db: Path) -> Check:
    try:
        notes = load_player_notes(kb)
    except NoteError as exc:
        return Check("kb_notes", False, str(exc))
    con = _read_only(db)
    teams: dict[int, str] = {}
    if con is not None:
        try:
            teams = {int(pid): str(name) for pid, name in con.execute(
                "SELECT player_id, team_name FROM v_players_current").fetchall()}
        except duckdb.Error:
            teams = {}
        finally:
            con.close()
    moved = misplaced_notes(notes, teams)
    if moved:
        detail = "; ".join(f"{n.name} sits under {n.path.parent.parent.name}, belongs under {slug}" for n, slug in moved)
        return Check("kb_notes", False, f"{len(notes)} notes; misplaced: {detail}")
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


def _scoring_check(db: Path) -> Check:
    con = _read_only(db)
    if con is None:
        return Check("scoring", False, "skipped: no database")
    try:
        row = con.execute("SELECT payload FROM v_league_settings_current").fetchone()
    except duckdb.Error as exc:
        return Check("scoring", False, f"skipped: {exc}")
    finally:
        con.close()
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


def _valuations_check(db: Path, now: datetime) -> Check:
    con = _read_only(db)
    if con is None:
        return Check("valuations", False, "skipped: no database")
    try:
        row = con.execute("SELECT run_id, created_at, superseded, scenarios FROM v_valuation_runs "
                          "ORDER BY created_at DESC, run_id DESC LIMIT 1").fetchone()
    except duckdb.Error as exc:
        return Check("valuations", False, f"skipped: {exc}")
    finally:
        con.close()
    if row is None:
        return Check("valuations", False, "no valuation run yet -- run `fantaclaude rank`")
    state = "superseded by a rules change -- re-run `fantaclaude rank`" if row[2] else "not superseded"
    return Check("valuations", not row[2], f"run {row[0]}, {_age(row[1], now)}, scenarios {', '.join(row[3])}; {state}")
```

`_pricing_check` needs `path.is_file()` guarded the same way as `_yaml_check` — `load_pricing_config` raises `PricingConfigError` on a missing file already (`OSError` is caught there), so the message names the path.

- [ ] **Step 7: Run the doctor and profile tests**

Run: `uv run pytest core/tests/test_doctor.py core/tests/test_kb_profiles.py -q`
Expected: all pass. `test_kb_profiles.test_doctor_kb_profiles_check` asserts `NAMES[-1] == "kb_profiles"` — change it to `"kb_profiles" in NAMES`.

- [ ] **Step 8: Documentation**

In `core/README.md`, add to the commands table after `fantaclaude kb audit`:

```markdown
| `fantaclaude rank [--offline] [--scenario NAME]…` | one valuation run: every listone player projected from his own history under the league's scoring, priced against the best completion of a roster whose composition the optimiser chooses; writes `valuation_runs`/`valuations`/`valuation_prices`, renders `data/exports/rankings.md`, `rankings.csv`, `asta-plan.md`, and copies the run to `records/` as parquet. Re-syncs `league_settings` first unless `--offline` |
```

Change the sentence "`sync-league` and `ingest` call the live league API" to "`sync-league`, `ingest` and `rank` (unless `--offline`) call the live league API", and extend "Layout" with: "`data/exports/` holds the regenerable renderings of the newest run; `records/` (committed) the parquet copies of every run; `pricing.yml` the pricing knobs (they feed `model_hash`); `core/src/fantaclaude/model/d_factor.yml` the D-Factor table, empty until the league activates the modifier and the account holder transcribes its bands from the league's settings page." In `CLAUDE.md`, "Workspace and tests", change "`fantaclaude sync-league` and `fantaclaude ingest …` call the live league API" to "`fantaclaude sync-league`, `fantaclaude ingest …` and `fantaclaude rank` (unless `--offline`) call the live league API", and add after that paragraph:

```markdown
`records/` is committed: `fantaclaude rank` writes parquet copies of every run
there, named by `run_id`, and they are never rewritten — commit them with the
run you intend to keep. `data/exports/` is a rendering and is gitignored.
`pricing.yml` and `preferences.yml` feed `model_hash`: a change there is a new
model, not a tweak. `core/src/fantaclaude/model/d_factor.yml` is league data
read off the league's own settings page — never fill it from memory.
```

- [ ] **Step 9: Lint, full suite, commit**

Run: `uv run ruff check --fix core && uv run ruff check core && uv run poe test`
Expected: ruff silent; MCP 111 passed; core 293 passed.

```bash
git add core/src/fantaclaude/commands/rank.py core/src/fantaclaude/cli/app.py core/src/fantaclaude/commands/sync_league.py core/src/fantaclaude/commands/doctor.py core/tests/test_rank_cli.py core/tests/test_doctor.py core/tests/test_sync_league.py core/tests/test_kb_profiles.py core/README.md CLAUDE.md
git commit -m "feat(cli): fantaclaude rank, supersession on a rules change, and the doctor's scoring, pricing, notes, dossiers and valuations checks"
```

---
### Task 10: The skills, the first real run, and what only the account holder can verify

**Files:**
- Create: `.claude/skills/fanta-market/SKILL.md`
- Modify: `.claude/skills/fanta-kb/SKILL.md` (the `interview` mode), `kb/rules/house-rules.md` (the D-Factor and the voto source), `records/` (the first run's parquet files), the spec (open questions 3 and 7)

**Interfaces:**
- Consumes: the CLI as shipped by Task 9 (`fantaclaude rank`, `query`, `doctor`, `kb audit`).
- Produces: the two skills; one committed valuation run under `records/`; the spec's open questions 3 and 7 updated with what this phase decided.

This task has no unit test: skills are not unit-testable (spec, "Testing"); each carries one worked example. Its proof is `fantaclaude doctor` and the committed run.

- [ ] **Step 1: Write `.claude/skills/fanta-market/SKILL.md`**

```markdown
---
name: fanta-market
description: Pre-auction analysis with fantaclaude — run `fantaclaude rank`, read the rankings and the asta plan, argue with the model on the user's behalf (a note, a taker, a rotation factor, a preference) and re-run under stated constraints. Use before the auction, whenever the listone, the rules or the knowledge base changed, and to draft the auction's journal entry.
---

# fanta-market

Python does the math; this skill does the judgment. It never computes a
value, a price or a tier itself — it runs `fantaclaude rank`, reads what the
run wrote, and changes *inputs* (a note, a profile, a preference) when it has
a reason to. Discover the CLI with `fantaclaude --help`; every read command
takes `--json`.

Three rules, defended hard:

- **The run_id is the record.** `data/exports/` is a rendering; `records/`
  holds the parquet copy; the journal links the run_id and restates no
  number. A run before the freeze is provisional and the report says so.
- **Change inputs, never outputs.** If the model likes a player the
  knowledge base doubts, write the doubt where the model reads it — a
  player note (`depth`, `availability`), a team profile (`rotation_factor`,
  `takers`), `preferences.yml` — and re-run. Never edit a ranking by hand.
- **The quotazione is a price.** The divergence list in `asta-plan.md` is
  where we disagree with the market: each line is either the edge or a bug,
  and it is read by hand before the auction.

## Modes

### `rank`

1. `fantaclaude doctor` — `scoring`, `pricing`, `kb_profiles`, `kb_notes`
   must be ok; `valuations` says whether a run exists and whether a rules
   change superseded it.
2. `fantaclaude rank` — re-syncs the league first (one API call set; pass
   `--offline` when re-running after an edit of your own, since the rules
   did not change). Read the status line: the composition per scenario,
   the inflation, the reserve, any `departed from the target`, every
   `warning:` (a club without a profile, a penalty taker the listone does
   not know — fix the profile's spelling to the listone's, then re-run).
3. Read `data/exports/rankings.md` by class and `asta-plan.md` by scenario.
   For any surprise, read the trace rather than guessing:
   `fantaclaude query --sql "SELECT name, explain FROM v_valuations_current WHERE player_id = <id>" --json`
   and
   `fantaclaude query --sql "SELECT scenario, explain FROM v_valuation_prices_current WHERE player_id = <id>" --json`.
4. Argue. "It likes him, but the profile says he is cover" → write the
   note (`kb/serie-a/teams/<slug>/players/<name>.md`, front-matter
   `player_id`, `name`, `team_short`, `depth`, `availability`; prose says
   why; `ttl: 7d`), re-run with `--offline`, compare the two run_ids.
5. Commit `records/` with the run you intend to keep.

### `plan`

Draft `kb/league/season-2026-27/giornata-00-asta.md` (front-matter as any
kb document; `ttl: never`): the run_id, the scenario chosen and why, the
three or four calls you expect to be close, what would change your mind.
No number tables — link the run_id and the query that reproduces any number.

## Worked example

**Ask:** "rank the listone; I think Scamacca is overrated this year."

**Good answer:** runs `doctor` (all ok, `valuations` not yet), runs
`fantaclaude rank`, reports "run 20260903T101500Z-…, 553 players, balanced:
inflation 1.18, composition Por 2·9, Dc 3·61, … , reserve 6; provisional,
auction in 2 days"; reads `rankings.md` for Pc and sees Scamacca tier 1 with
max 48/55/63; queries his `explain` — `rate_source history`, 31 presenze
weighted, `penalties_per_presenza 0.16` because Atalanta's profile names him
taker; asks what the doubt is; the user says a knee; writes
`kb/serie-a/teams/atalanta/players/scamacca.md` with `availability: 0.8`,
`depth: starter`, prose "knee flagged 2 Sep, two weeks of doubt", re-runs
with `--offline`, reports the new band (41/47/54) and both run_ids; commits
`records/`.

**Bad answer:** edits `rankings.md`; writes "Scamacca averaged 7.1" into a
kb document; re-runs without `--offline` five times "to check"; treats a
run made before the freeze as final.
```

- [ ] **Step 2: Add the `interview` mode to `.claude/skills/fanta-kb/SKILL.md`**

Replace the `### interview — Phase 1` stub with:

```markdown
### `interview`

Opponent dossiers, one per rival manager, elicited conversationally. Output
is `kb/league/participants/<nick>.md` in the fixed schema
`fantaclaude.kb.participants` validates, plus one line in `league.yml`.

1. `fantaclaude query --sql "SELECT payload->'teams' AS teams FROM v_league_settings_current" --json`
   — the league's team names and owner nicks (`n`, `nu`); never invent a
   nick, and never write an email address anywhere.
2. Ask, for one rival at a time, only what predicts auction behaviour: who
   they support; whether they spend early, steadily, or hoard; the roles
   they overpay and the ones they neglect; the biggest single buy you have
   seen them make, as a share of the budget; last year's regrets. Ten
   minutes per rival; stop when the answers repeat.
3. Write the dossier from the template below. Front-matter: `nick`, `team`
   (the league team name, or omit until the auction assigns one),
   `budget_style` (`early | steady | hoarder`), `favourite_clubs` (listone
   spellings), `overpays` / `avoids` (role classes: Por, Dd, Ds, Dc, E, M,
   C, W, T, A, Pc), `max_single_share` (optional, 0–1). `ttl: 90d`,
   `confidence: medium` when the user is sure, `low` when guessing.
4. Add to `league.yml` under `participants:` —
   `<nick>: {value: kb/league/participants/<nick>.md, source: interview, verified_on: <date>}`.
5. `fantaclaude kb audit` → 0 invalid; `fantaclaude doctor` → `kb_participants` ok. One commit per interview session.

Dossier template:

```markdown
---
updated: 2026-09-01
ttl: 90d
confidence: medium
source: "interview 2026-09-01"
nick: Marco
team: Sanzimippi FC
budget_style: early
favourite_clubs: [Juventus]
overpays: [Pc, A]
avoids: [Por]
max_single_share: 0.3
---

# Marco

## How he bids
Two to four sentences: when he spends, what he chases, what he never buys.

## Last year
The buys he regrets and the ones he brags about — prose, no prices.

## Watch
What would change this dossier.
```

**Ask:** "let's do the dossier for Marco." **Good answer:** lists the nicks
from the settings payload, asks the six questions in turn, writes the file
above, adds the `league.yml` line, runs `kb audit` and `doctor`, commits.
**Bad answer:** a dossier with a price table, an email address, a role
`avoids: [striker]`, or a nick the league does not have.
```

Update the skill's `description:` front-matter to mention `interview`: "… `refresh` renews what `fantaclaude kb audit` reports as expired, `interview` writes an opponent dossier. …".

- [ ] **Step 3: Record what this phase decided in `kb/rules/house-rules.md` and the spec**

In `kb/rules/house-rules.md`, "Scoring and modules", append:

```markdown
The voto source is `calculate.sourcev` in the settings payload; `fantaclaude
doctor` prints the sheet it resolves to (`1 → Fantacalcio` is the working
hypothesis, checked by the account holder against the league's calcolo page
— see "Watch"). The Mantra defence modifier is the **D-Factor**; its
thresholds are league data read off the league's settings page and kept in
`core/src/fantaclaude/model/d_factor.yml` with a date. While it is inactive
(every `smod*` field null) nothing is applied; if any other modifier is
switched on, `fantaclaude rank` refuses rather than price a rule it does not
model.
```

and to "Watch": "- The voto source mapping (`sourcev` 1 → Fantacalcio) and the D-Factor table: both confirmed only from the league's own settings page."

In the spec's open question 3, strike the title and record: "**~~Is the modificatore di difesa active?~~ Decided 2026-08-29.** Inactive (every modifier field null on every snapshot since 2026-08-22). In Mantra the modifier is the D-Factor — the five best voti among Dc/B/Dd/Ds/E/M with at least three true defenders, optionally the goalkeeper, averaged and mapped to points; its thresholds are not published and are customisable per league, so they live in `model/d_factor.yml` as data, empty until transcribed from the league's settings page. Phase 1 models the mechanism (`model/d_factor.py`) and applies a per-player uplift when `calculate.smodd` is non-null; any other modifier key turning non-null makes `rank` refuse." In open question 7, append: "Decided 2026-08-29: the optimiser proposes the composition; `preferences.yml` keeps `target_composition: {Por: 2}` as a soft prior (raised demand weights, never a bound), and `rank` prints the composition it chose per scenario."

- [ ] **Step 4: The first real run**

Run, once: `uv run fantaclaude doctor` (every check but `valuations` ok; `scoring` says `sheet Fantacalcio … no modifier active`), then `uv run fantaclaude rank` — **this calls the live league API once (the re-sync) and nothing else**. Then read the output against these expectations and record what you saw in the task summary:

- 553 players, 8 teams × 500 = 4000 on the market, giornata 2 played (or 3, if a giornata was ingested since), sheet `Fantacalcio`.
- Three scenarios; `balanced` composition with `Por 2`, `Dc` between 2 and 4, no class above 6; reserve small (≤ 12); inflation between 0.9 and 1.6.
- The top of `Pc`/`A` contains the top scorers of season 20 (`Martinez L.`, `Thuram`, `Hojlund`, `Douvikas`) with tier 1; a rotation-heavy club's squad players show a wider band than a fixed-eleven club's starters.
- The `warning:` lines: a penalty taker spelled differently from the listone → fix the profile (`kb/serie-a/teams/<slug>/profile.md`, `takers.penalties`) to the listone's spelling and re-run with `--offline`; a club without a profile → there should be none (doctor says 20/20).
- `records/` gained four parquet files; `data/exports/` has the three renderings; `fantaclaude doctor` now says `valuations` ok.

Commit the records with the run: `git add records && git commit -m "records: first Phase 1 valuation run (provisional, before the freeze)"`.

- [ ] **Step 5: What only the account holder can verify — ask, then record**

Two facts this plan could not observe, each recorded where the code reads it:

1. **The voto source.** In the league's web settings (Leghe → *fantabalotelli3* → Impostazioni → Calcolo, the "Fonte voti" field): confirm it reads **Fantacalcio** (the Redazione votes). If it reads Statistico or Italia, `VOTO_SOURCES` in `model/scoring.py` maps `1` wrongly — swap the mapping to what the page shows, note the date in the docstring, and re-run `rank`.
2. **The D-Factor.** On the same settings pages (Modificatori), confirm every modifier is off — `doctor`'s `scoring` line agrees. If the admin ever switches the D-Factor on: `sync-league` will show which `calculate.*` key moved (expected `smodd`; if a different key moves, set `D_FACTOR_KEY` in `model/scoring.py` to it and note the date); open the modifier's page, transcribe its table into `core/src/fantaclaude/model/d_factor.yml` (`bands`, `with_goalkeeper`, `source`, `verified_on`), run `uv run pytest core/tests/test_d_factor.py -q` (it accepts a filled table), then `rank`.

Record both answers in `kb/rules/house-rules.md` ("Watch") with the date.

- [ ] **Step 6: Final check and commit**

Run: `uv run poe test && uv run ruff check core && uv run fantaclaude kb audit && uv run fantaclaude doctor`
Expected: both suites green; `kb audit` 0 invalid; `doctor` `ready`.

```bash
git add .claude/skills/fanta-market/SKILL.md .claude/skills/fanta-kb/SKILL.md kb/rules/house-rules.md
git commit -m "feat(skills): fanta-market, the fanta-kb interview mode, and the Phase 1 decisions recorded in the house rules"
git add docs/superpowers/specs/2026-08-22-fantaclaude-design.md
git commit -m "docs(spec): record the D-Factor decision and the optimiser-proposed composition (open questions 3 and 7)"
```

---

## Self-Review

**Spec coverage, Phase 1 row and the sections it draws on:**

| spec requirement | task |
| --- | --- |
| "projection, VOR, allocation, tiers, max prices, asta plan; opponent dossiers via `fanta-kb interview`" | 6 (projection), 8 (VOR, tiers, asta plan), 7 (allocation and max prices), 4 + 10 (dossier contract and the interview mode) |
| Five stages of `fanta-market`: project, Mantra-adjust, VOR, allocate, tier; the listone quotazione is not an input | 6 (project; flexibility bonus), 3 + 8 (pinning, replacement), 7 (allocate — composition chosen by the DP), 8 (tiers); the perturbation test in 6 and the Global Constraint |
| "Output: a stamped run in `valuations`, rendered to `rankings.md` / `.csv` in `data/exports/`, plus a one-page asta plan with three scenarios" | 1 (tables), 8 (exports, scenarios from `preferences.yml`), 9 (`rank`) |
| "The permanent record is the `run_id`, and only the `run_id`"; durability via `records/` | 8 (`export_records`), 10 (the committed run), the `fanta-market` skill |
| Expected fantamedia: recomputed under this league's bonus/malus; shrunk toward the role mean by presenze; weighted across three seasons; luck-corrected via xG/xA | 2 (scoring), 5 (history under the scoring), 6 |
| Expected presenze = base × depth × rotation × availability; `depth_factor` from the knowledge base; `rotation_factor` from the team profile, applied per player; "widens the band as much as it lowers the mean"; rotation manufactures cheap value | 4 (notes), 6 (rate, band), 8 ("Cheap value" in the plan) |
| "Fantavoto is computed, never stored"; scoring is league-configurable | 2, 5 (the test `test_scoring_is_league_configurable`) |
| League configuration is data: money supply `n_teams × budget`, bounds, modules, voto source, modifiers all read at run time; `rank` re-syncs first unless `--offline`; a settings change flags runs as superseded | 8 (`load_context`), 9 (re-sync, `superseded_runs`, `v_valuation_runs.superseded` from Task 1) |
| Two hashes: `rules_hash` and `model_hash` (with `preferences.yml`) | 8 (`model_hash`, plus `inputs_hash` for the data and the kb) |
| The Mantra role model: role flexibility has option value; roles are sets, modules are slot multisets; module definitions are domain data | 3 (demand from `modules.yml`), 6 (`flex_bonus_per_role`) |
| Dynamic max price: indifference against the best completion; scarcity falls out of `V`; the player leaves the pool in both branches; the band at p25/p50/p75; three searches not three DPs; ~nine DPs and a binary search per player; composition is a decision variable; `target` is soft | 7 |
| "One pricing function": Phase 1 and Phase 2 share `price_board`; the pre-auction board is the `exact=True` call; the live board's focused lot is exact | 7 (`focus`, `exact`, the determinism and focus tests) |
| The pricing module: pure, bounded, `PricingConfig` from `pricing.yml`, `explain()` beside `price()` | 7 |
| Expected pool prices: Mantra quotazione × self-calibrating inflation, clamped, over the top-~30 per class | 7 (`_expected_prices`) |
| Testing — Projection (rotation lowers and widens; quotazione perturbation), Valuation (sums sane, tiers monotone, every player a role, no negative VOR), Scoring league-configurable, Dynamic max price (scarcity monotone, exhaustion → credits available, latency), One pricing function, CLI (`CliRunner`, exit codes, `--json`), Adjustments' `exclude` directional invariant, Skills' worked examples | 6, 8, 2, 7, 7, 9, 7 (`test_excluding_a_player_raises_everyone_else…`), 10 |
| Knowledge base: sparse player notes under the club with front-matter; participants dossiers in a fixed schema loaded at startup; `kb audit` validates them; prose never restates a number | 4, 9 (doctor), 10 |
| `league.yml` carries the participant-name → dossier mapping with provenance | 9 (`_participants_check`), 10 (the interview mode) |
| `fantaclaude doctor` grows with the spine | 1 (the dedupe key), 9 |
| The 0b leftover: a dedupe key covering the raw bytes, the aliases file and the listone snapshot | 1 |
| Open question 1 (runs before the freeze are provisional) | 9 (`provisional_note`) |
| Open question 3 (the modifier) — decided: model the D-Factor, refuse unknown modifiers | 2, 6, 8, 10 |
| Open question 7 (composition) — decided: the optimiser proposes | 3, 7, 8, 10 |

**Deliberately not in this plan** (each named in the spec as a later phase or a different concern): the auction state machine, the live feed, `adjustments.yml` and the dashboard (Phase 2a/2b — `PoolState.owned`/`excluded`/`targets` exist so the live state can be expressed without touching `pricing.py`); opponent pressure (Phase 2a; the dossiers it reads are contracted here); `market_prices` and `calibration` (they need the post-auction roster endpoint, open question 9, and results, Phase 3); `predictions`, `lineup_runs`, `lineup_submitted` and the lineup optimiser (Phase 3); `kb move-player` (a note carries `player_id`, so a misplaced file still loads and `doctor` names where it belongs — moving it is `git mv`); the journal entry `giornata-00-asta.md` (written by `fanta-market plan` at auction time, not by code); the interviews themselves (decision 2); FBref; a `records/` copy of the auction snapshot (Phase 2).

**Assumptions stated where the plan had to choose:** the `bnMls` pairs are read only when equal (refused otherwise); `sourcev 1 → Fantacalcio` (verified by the account holder in Task 10); `smodd` is the D-Factor key (any other key refuses); the D-Factor's per-player effect is the table's gradient at a reference average of 6.1 over a fifth of the excess voto, never negative; the demand weights average the eleven modules equally (a soft prior, sharpened by `target_composition`); the pool is pinned to one class per player (the spec's stated approximation), B folded into Dc; the fill reserve is one credit per unfilled roster slot after the DP's own composition; the league's roster maximum binds through a per-player slot price found by bisection, charged only when the free completion would exceed it; a class budget share caps both the class's spend and the printed price; the approximate board prices the non-focused players from full-pool tables (documented in `explain()`); tiers are the largest gaps among the top 30 of a class; divergence is rank-matched implied value. Each is one knob or one function, and each is named in a docstring.

**Placeholder scan:** no `TBD`, `TODO`, "implement later", "add validation", "handle edge cases", "similar to Task N"; every code step carries its code; the two steps that are not code (Task 10, Steps 4 and 5) name the commands, the expected observations and where to record the answers.

**Type consistency:** `record_advanced(con, season_id, rows, raw, *, candidates, teams, aliases, aliases_sha256, listone_snapshot_id, force=False)` and `advanced_key(con, aliases_path)` (Task 1, used in 1's tests and `commands/ingest.py`); `BonusMalus.from_calculate`, `Events`, `event_points`, `fantavoto`, `voto_sheet`, `modifier_status` (Task 2, used in 5, 6, 8, 9); `DFactorTable.{points, slope, is_empty, to_dict}`, `load_d_factor` (2, used in 6, 8, 9); `module_demand`, `rank_weights(demand, *, max_rank, bench_weight, bench_decay, bench_slots, targets, target_weight)`, `hard_minimums`, `pin_class` (3, used in 7's tests and 8); `PlayerNote`, `load_player_notes`, `misplaced_notes`, `Participant`, `load_participants` (4, used in 6, 8, 9); `SeasonLine` (with `npxg`), `RolePrior`, `History.{lines_for, giornate_played, priors, club_penalty_rate}`, `load_history(con, *, sheet, bm, current_season, back)` (5, used in 6, 8); `ProjectionConfig`, `PlayerInputs`, `Projection`, `project_all(inputs, *, cfg, priors, bm, giornate_remaining, current_season, d_factor)` (6, used in 8); `PricingConfig`, `PoolPlayer`, `OwnedPlayer`, `PoolState`, `Band`, `PlayerPrice`, `BoardPricing`, `price_board(state, cfg, focus=None, *, exact=False)`, `explain`, `load_pricing_config` (7, used in 8, 9); `Scenario.quantile`, `load_scenarios`, `run_valuation(con, *, now, kb_dir, preferences, projection_cfg, pricing_cfg, d_factor, scenario_names)`, `record_run`, `ValuationRun.{boards, tiers, vor, implied, replacement, summary, warnings}` (8, used in 8's exports, 9); `write_rankings`, `write_asta_plan`, `export_records(con, run_id, rules_hash, records_dir)` (8, used in 9); `rank(con, *, now, kb_dir, preferences_path, pricing_path, exports_dir, records_dir, league_yml, scenarios)`, `provisional_note`, `SyncReport.superseded_runs`, `DoctorPaths.pricing` (9). `conftest.seed_voti(con, season_id, giornata, rows, *, sheets)` / `seed_advanced(con, season_id, rows)` (5, used in 5, 8); `test_doctor._ready_workspace` / `_paths` (used by 8's and 9's tests, extended in 9); `test_kb_profiles._write` and `test_kb_participants._write` (used by 8, 9).

**Dry run:** every code block of Tasks 1–9 was placed into a detached scratch worktree from this document on 2026-08-29 (numpy 2.5.2 added there), ruff-fixed and run: `uv run poe test` → 111 passed (MCP) and 293 passed (core), `uv run ruff check core` silent. The per-task counts in the "Expected" lines are the measured ones. Three things the dry run changed in this document, so the executor does not rediscover them: the number of ranks a class has is derived from the module demand (peak slots plus one bench slot) with decaying bench weights, and the league's `roster_max` binds through a slot price — without this the DP bought sixty players; `run_id` gets a `-2`, `-3` suffix when two runs share a second; and two literals `== 2` in the pre-existing `test_ingest_all.py` become `SCHEMA_VERSION`. Measured on this machine: the focused 553-player board re-prices in 24–25 ms, the exact board in about 380 ms. Task 10 (the skills, the real run, the account holder's two verifications) has no code to dry-run.
