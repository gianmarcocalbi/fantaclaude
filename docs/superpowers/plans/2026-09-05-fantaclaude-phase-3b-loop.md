# fantaclaude Phase 3b — The Weekly Loop: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn 3a's forecast into a loop: the two news pages ingested and
matched by name, `p_start` blended by precedence (a note, else a squalifica,
else the page) with every other source a named check, each prediction honest
against its player's own kickoff, an ordered bench with contingencies and close
calls computed by re-solving, a matchup term and a spread, the XI actually
fielded recorded by hand and later read back from the platform, and the
`fanta-manager` skill that runs it — all before giornata 4 kicks off on
**Friday 11 September 2026 at 18:45 UTC (20:45 Rome)**.

**Architecture:** One new adapter, `ingest/news.py`, follows probabili's
`fetch()` → dated raw HTML → `parse` → `record()` shape over two public pages
that carry names, not ids, so it joins through the repo's name matcher within
each club card. `analysis/weekly.py` becomes the package `analysis/weekly/`
(`errors`, `rounds`, `forecast`, `blend`, `notes`, `xi`, `records`, `report`,
`config`, `submitted`), `lineup()` staying the facade the CLI calls. Schema
version 5 is additive: two news tables, `lineup_submitted`, four columns on
`predictions`, four on `lineup_runs`, and three views. `fantaclaude lineup`
becomes a command group whose bare call is unchanged and whose subcommands are
`note` and `record`; `ingest news` sits beside `ingest probabili`. No server,
no dashboard.

**Tech Stack:** Python 3.14, DuckDB, Typer, httpx, stdlib `html.parser` (as
`ingest/probabili.py`), PyYAML, pytest + `CliRunner` + `respx` + the `FakeAPI`
in `core/tests/conftest.py`. No new dependency. No test touches the network.

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` at
`de1a002` — sections "Schema" (the 3b rows), "Forecasts are immutable" (the 3b
columns, `v_predictions_current`), "Ingestion adapters" (`news`, no key),
"`fanta-manager` — the weekly loop" (every subsection: what 3b settled, the
news adapter as captured, blending by precedence and the three checks, the
matchup term / `fv_sd` / `weekly_hash`, the optimiser's three new outputs, the
override file, the surface and the skill's four modes, per-player deadlines,
`lineup_submitted` and the read-back), "Testing" (the eight 3b bullets),
"Failure modes" (the squalificato row), "Phasing" (the 3b row and "Order within
3b"), open questions 18 (resolved), 19 (deferred) and 20 (raised). The code on
`feat/phase-3-manager` at `de1a002` is the truth where this plan and the spec
differ from it.

## Global Constraints

- **The deadline is giornata 4's first kickoff: 2026-09-11 18:45 UTC (20:45
  Rome).** Tasks 1–8 are what the Friday XI needs; Tasks 9, 10 and 13 may slip
  past it without breaking the loop (Task 12 says what to run either way).
  Giornata 4 runs to Monday 14 September 18:45 UTC; giornata 5 starts Friday 18
  September.
- **No test touches the network.** Public pages are read from
  `core/tests/fixtures/`; the league API is `FakeAPI`. The live calls in this
  phase are the ones Task 12 and Task 13 name, each run once because the data
  is needed.
- **Live discipline (CLAUDE.md):** `ingest news` and `ingest probabili` read
  public pages through the polite client — one request per page, an honest
  User-Agent, no retry loop, never "to check". `ingest stats-web` sends the
  website cookie once per missing giornata. `ingest rosters` calls the real
  account and runs only when the lega changed. Nothing here writes to the
  platform (Non-goals: submitting lineups).
- **Every row in `lineup_runs`, `predictions`, `lineup_submitted`, `news_files`
  and `unavailable` is immutable.** No UPDATE or DELETE path anywhere. A later
  fetch is a later file; a later run is a later row. `records/` is never
  rewritten: a parquet that exists is left alone.
- **Timestamps:** aware UTC in Python, naive UTC in DuckDB, through
  `timeutil.to_db`. `fixtures.kickoff` is UTC.
- **`model_hash` does not move in this phase.** The weekly layer has its own
  `weekly_hash` (Task 7), covering `WEEKLY_VERSION` and every constant in
  `WeeklyConfig`; a changed constant is a new weekly model, and the run's hash
  must not pretend it changed.
- **Precedence, not product.** `p_start` is a note, else a squalifica, else the
  published number. The KB note, the infortunati list and the European week
  produce warnings and never touch the number. A test asserts the published
  value survives under each of them.
- **Names are matched, never guessed.** The news pages carry names the
  listone's way inside club cards: resolve the club through `resolve_team` and
  the `fantacalcio` team aliases, the player through `match_listone` against
  that club's candidates only; an unresolved name is written with a null
  `player_id` and counted, never dropped and never fuzzy-matched across clubs.
- **Exit codes** (`cli/app.py::ExitCode`): 0 ok, 1 error, 2 usage (bad flag, a
  name nobody resolves to, an illegal XI), 3 not ready (missing input), 4
  conflict (a forecast after every kickoff without `--late`; a page for a
  different giornata).
- **Commits:** one per task, message documents the change, **no session link,
  no Co-Authored-By** (CLAUDE.md overrides the harness default). Do not push.
- **Fixtures are extracted, never hand-edited.** The two news fixtures come
  from `captured/` via `_extract_news.py`; a test that needs a variant rewrites
  the sample in the test (as `test_probabili.py` does). The suspension entry's
  shape is inferred from the injuries page until Task 12's Tuesday capture
  confirms it.
- **Emails never reach a raw file or a tool result.** The read-back's capture
  (Task 13) is scrubbed with `league.settings.without_emails` before it is
  saved.
- The Schema DDL stays additive (`CREATE ... IF NOT EXISTS`, `ALTER TABLE ...
  ADD COLUMN IF NOT EXISTS`, `CREATE OR REPLACE VIEW`); `SCHEMA_VERSION`
  becomes 5 and the live database upgrades in place, its 3a rows keeping
  `late = false`, which is what they were.
- **Run the whole suite before every commit:** `uv run poe test` and `uv run
  poe lint`. Both must be green.

## File structure

| File | Responsibility |
| --- | --- |
| `captured/squalificati-2026-09-05.html`, `captured/infortunati-2026-09-05.html` | the two captures (gitignored), one anonymous request each, made 2026-09-05 during design |
| `core/tests/fixtures/_extract_news.py` | trims each capture to its first two club cards → `news_infortunati_sample.html`, `news_squalificati_sample.html` |
| `core/src/fantaclaude/db/schema.py` | version 5: `news_files`, `unavailable`, `lineup_submitted`; columns on `predictions` and `lineup_runs`; `v_news_files_current`, `v_unavailable_current`, `v_predictions_current`, `v_lineup_submitted_current` |
| `core/src/fantaclaude/ingest/news.py` | `parse_news_page`, `fetch_news`, `record_news`: the two pages, names matched within the club |
| `core/src/fantaclaude/analysis/weekly/__init__.py` | re-exports every public name 3a's `weekly.py` had, plus the 3b ones |
| `core/src/fantaclaude/analysis/weekly/errors.py` | `ForecastError`, `LateForecast` |
| `core/src/fantaclaude/analysis/weekly/rounds.py` | `Round`, `target_round`, `PlayerFixture`, `player_fixtures`, the two cross-checks, the staleness warning |
| `core/src/fantaclaude/analysis/weekly/forecast.py` | `ForecastRow`, `newest_probabili_file`, `forecast`, `scoring_in_force`, the matchup table and the spreads |
| `core/src/fantaclaude/analysis/weekly/config.py` | `WEEKLY_VERSION`, `WeeklyConfig`, `weekly_hash` |
| `core/src/fantaclaude/analysis/weekly/notes.py` | `data/lineup-notes.yml`: parse, append, resolve per giornata |
| `core/src/fantaclaude/analysis/weekly/blend.py` | `BlendLayer`, `load_layer`, `blend`: the precedence and the three checks |
| `core/src/fantaclaude/analysis/weekly/xi.py` | `RosterPlayer`, `my_roster`, `choose_xi`, `order_bench`, `contingencies`, `close_calls` |
| `core/src/fantaclaude/analysis/weekly/records.py` | `write_lineup_run` (per-row `late`), `export_lineup_records` |
| `core/src/fantaclaude/analysis/weekly/report.py` | `LineupReport`, `lineup()` — the facade |
| `core/src/fantaclaude/analysis/weekly/submitted.py` | `lineup_submitted`: the hand path, legality, records export |
| `core/src/fantaclaude/paths.py` | `lineup_notes_path()` |
| `core/src/fantaclaude/commands/doctor.py` | the `lineup_notes` check |
| `core/src/fantaclaude/cli/app.py` | `ingest news`; `lineup` as a group with `note` and `record`; `ingest lineup` (Task 13) |
| `core/tests/conftest.py` | `seed_news`, `seed_matches`; `seed_probabili` learns `team_short` |
| `core/tests/test_news.py`, `test_weekly_rounds.py`, `test_lineup_notes.py`, `test_weekly_blend.py`, `test_weekly_xi.py`, `test_weekly_terms.py`, `test_lineup_record.py` | the new suites; `test_lineup_cli.py`, `test_schema.py`, `test_doctor.py` extended |
| `.claude/skills/fanta-manager/SKILL.md` | the skill: `refresh`, `lineup`, `note`, `record` |
| `README.md`, `records/README.md`, `CLAUDE.md`, `site/docs/cli.md` | the docs that describe what moved |
| `mcp/fantacalcio/src/fantacalcio_mcp/api.py`, `core/src/fantaclaude/ingest/lineup_api.py` | Task 13: the lineup GET once captured, and `ingest lineup` |

---

### Task 1: Extract the news fixtures from the two captures

The captures already exist: `captured/squalificati-2026-09-05.html` and
`captured/infortunati-2026-09-05.html`, fetched once each through
`fantaclaude.ingest.http.build_http` on 2026-09-05 (the spec's news-adapter
paragraph records what they showed). This task turns them into fixtures and
records the shape, the way `_extract_probabili.py` did.

**Files:**
- Create: `core/tests/fixtures/_extract_news.py`
- Create: `core/tests/fixtures/news_infortunati_sample.html` (generated)
- Create: `core/tests/fixtures/news_squalificati_sample.html` (generated)

**Interfaces:**
- Produces: the two fixture files Task 3's tests read.

- [ ] **Step 1: Confirm the captures and the shape the extractor relies on**

```bash
ls -la captured/squalificati-2026-09-05.html captured/infortunati-2026-09-05.html
grep -c 'class="card team-card"' captured/infortunati-2026-09-05.html    # 20
grep -c 'class="card team-card"' captured/squalificati-2026-09-05.html   # 20
grep -c 'class="item-name"' captured/infortunati-2026-09-05.html         # 43
grep -c 'class="empty-list-message"' captured/squalificati-2026-09-05.html  # 40
```

If a file is missing, fetch it once with the snippet below (one request per
page, the polite client, no retry) and stop if either request fails:

```bash
uv run python - <<'EOF'
import asyncio
from pathlib import Path
from fantaclaude.ingest.http import build_http, fetch_bytes, polite_pause
PAGES = {"squalificati": "https://www.fantacalcio.it/squalificati-e-diffidati-campionato-serie-a",
         "infortunati": "https://www.fantacalcio.it/infortunati-serie-a"}
async def go():
    http = build_http()
    try:
        for i, (kind, url) in enumerate(PAGES.items()):
            if i:
                await polite_pause()
            Path(f"captured/{kind}-2026-09-05.html").write_bytes(await fetch_bytes(http, url))
    finally:
        await http.aclose()
asyncio.run(go())
EOF
```

- [ ] **Step 2: Write the extractor**

```python
"""One-shot: build the two news fixtures from the captures.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_news.py

Each page is twenty club cards, `<div id="team-N" class="card team-card">`,
in listone order; the fixture keeps the document head, the first two cards
whole (Atalanta and Bologna on both captures) and the last 4000 characters
of the document -- the closing tags and scripts, which the parser ignores --
so the fixture is a real page with two clubs instead of twenty.

Observed on the captures (2026-09-05, one anonymous request each):
- a club card opens with CARD_OPEN below and carries the club's name as
  `<span class="team-name">Atalanta</span>` inside `header.team-info` --
  the listone's spelling of the club, no slug, no id;
- the injuries page lists its entries as `<ul class="unstyled"><li><strong
  class="item-name">Sulemana K.</strong><div class="item-description"><p>...
  </p></div></li>`: the name written the listone's way (surname, then the
  initial), no link, no player id anywhere on the page; forty-three entries
  over seventeen clubs, three clubs with `<div class="empty-list-message">
  Nessuno</div>` instead;
- the suspensions page has two columns per club, each opened by
  `<header><strong class="label label-danger">Squalificati</strong></header>`
  or `<strong class="label label-warn">Diffidati</strong>`, and on this
  capture EVERY column is `<div class="empty-list-message">Nessuno</div>`
  (giornata 3 in progress, no Giudice Sportivo ruling yet, nobody on four
  yellows after two rounds). The shape of a suspension entry is therefore
  INFERRED to be the injuries page's `li > strong.item-name +
  div.item-description`; Task 12 captures the page again on Tuesday 8
  September and this docstring is corrected if the ruling shows otherwise.
- the team menu above the cards repeats every club as
  `<a href="#team-N" data-team="atalanta">` with a badge, and a match
  widget elsewhere on the page uses `team-name team-link` anchors: neither
  is a card, and the parser reads `team-name` only inside a card.

Public pages, nothing to scrub.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURES = {"infortunati": ROOT / "captured" / "infortunati-2026-09-05.html",
            "squalificati": ROOT / "captured" / "squalificati-2026-09-05.html"}
CARD_OPEN = 'class="card team-card"'
KEEP = 2


def _card_starts(html: str) -> list[int]:
    """The index of each card's `<div`, found from its class attribute."""
    starts = []
    i = html.find(CARD_OPEN)
    while i != -1:
        starts.append(html.rfind("<div", 0, i))
        i = html.find(CARD_OPEN, i + 1)
    return starts


def main() -> None:
    for page, capture in CAPTURES.items():
        html = capture.read_text(encoding="utf-8")
        starts = _card_starts(html)
        assert len(starts) == 20, f"{page}: expected twenty club cards, found {len(starts)} for {CARD_OPEN!r}"
        out = Path(__file__).with_name(f"news_{page}_sample.html")
        out.write_text(html[:starts[0]] + html[starts[0]:starts[KEEP]] + html[-4000:], encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size} bytes, {KEEP} clubs)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate and check the fixtures**

```bash
uv run python core/tests/fixtures/_extract_news.py
grep -c 'class="card team-card"' core/tests/fixtures/news_infortunati_sample.html   # 2
grep -o 'class="item-name">[^<]*' core/tests/fixtures/news_infortunati_sample.html  # Sulemana K., Hien, Orsolini, El Azzouzi O.
grep -c 'empty-list-message' core/tests/fixtures/news_squalificati_sample.html      # 4
grep -c 'label label-danger' core/tests/fixtures/news_squalificati_sample.html      # 2
```

- [ ] **Step 4: Commit**

```bash
git add core/tests/fixtures/_extract_news.py core/tests/fixtures/news_infortunati_sample.html core/tests/fixtures/news_squalificati_sample.html
git commit -m "test(fixtures): the two news pages, trimmed to two club cards each -- names, not ids, and an empty squalificati column"
```

---

### Task 2: Schema version 5

**Files:**
- Modify: `core/src/fantaclaude/db/schema.py` (the docstring, `SCHEMA_VERSION`, the DDL after `predictions`, the views after `v_lineup_runs_current`)
- Modify: `core/tests/test_schema.py`

**Interfaces:**
- Produces: tables `news_files`, `unavailable`, `lineup_submitted`; columns `predictions.kickoff/late/matchup/trace`, `lineup_runs.weekly_hash/bench/contingencies/close_calls`; views `v_news_files_current`, `v_unavailable_current`, `v_predictions_current`, `v_lineup_submitted_current`. Tasks 3, 5, 7, 8, 10 write to them.

- [ ] **Step 1: Write the failing test**

Append to `core/tests/test_schema.py`, after `test_version_4_adds_the_forecast_and_roster_layer`, and add the object set beside `V4_OBJECTS`:

```python
V5_OBJECTS = {"news_files", "unavailable", "lineup_submitted",
              "v_news_files_current", "v_unavailable_current", "v_predictions_current", "v_lineup_submitted_current"}
```

```python
def test_version_5_adds_the_news_layer_and_widens_the_forecast(tmp_path):
    con = connect(tmp_path / "v5.duckdb")
    assert apply_schema(con) == 5 and SCHEMA_VERSION == 5
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
    assert V4_OBJECTS | V5_OBJECTS <= names
    assert _columns(con, "predictions") == ["lineup_run_id", "season_id", "giornata", "player_id", "p_start_published",
                                            "p_start", "fv_if_plays", "fv_sd", "expected_points", "source",
                                            "kickoff", "late", "matchup", "trace"]
    assert _columns(con, "lineup_runs")[-4:] == ["weekly_hash", "bench", "contingencies", "close_calls"]
    assert _columns(con, "unavailable") == ["file_id", "season_id", "giornata", "kind", "team_name", "team_short", "name",
                                            "player_id", "match_status", "detail", "position", "raw"]
    assert _columns(con, "lineup_submitted") == ["submitted_id", "season_id", "giornata", "lineup_run_id", "my_team",
                                                 "module", "xi", "bench", "source", "recorded_at"]
    assert apply_schema(con) == 5
    assert con.execute("SELECT count(*) FROM schema_version WHERE version = 5").fetchone()[0] == 1
    con.close()


def test_a_version_4_file_gains_the_new_columns_and_its_rows_keep_late_false(tmp_path):
    """3a's live database has two giornata-3 runs written before the first
    kickoff; upgrading must leave them readable, with the new per-row
    `late` false, which is what they were."""
    con = connect(tmp_path / "v4.duckdb")
    apply_schema(con)
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (4)")
    con.execute("ALTER TABLE predictions DROP COLUMN trace")
    con.execute("ALTER TABLE predictions DROP COLUMN matchup")
    con.execute("ALTER TABLE predictions DROP COLUMN late")
    con.execute("ALTER TABLE predictions DROP COLUMN kickoff")
    con.execute("ALTER TABLE lineup_runs DROP COLUMN close_calls")
    con.execute("ALTER TABLE lineup_runs DROP COLUMN contingencies")
    con.execute("ALTER TABLE lineup_runs DROP COLUMN bench")
    con.execute("ALTER TABLE lineup_runs DROP COLUMN weekly_hash")
    con.execute("INSERT INTO lineup_runs (season_id, giornata, run_id, model_hash, probabili_file_id, deadline, written_at, "
                "late, predictions) VALUES (21, 3, 'r', 'm', 1, '2026-09-04 18:45', '2026-09-04 13:46', false, 1)")
    con.execute("INSERT INTO predictions VALUES (1, 21, 3, 2764, 90, 0.9, 7.0, NULL, 6.3, 'published')")
    assert apply_schema(con) == 5
    assert con.execute("SELECT late, kickoff, trace FROM predictions").fetchone() == (False, None, None)
    assert con.execute("SELECT weekly_hash, bench FROM lineup_runs").fetchone() == (None, None)
    assert con.execute("SELECT count(*) FROM v_predictions_current").fetchone()[0] == 1
    con.close()


def test_v_predictions_current_reads_the_newest_honest_row_per_player(db):
    for run_id, late_rows in ((1, {2764: False, 2120: False}), (2, {2764: False, 2120: True}), (3, {2764: True, 2120: True})):
        db.execute("INSERT INTO lineup_runs (season_id, giornata, run_id, model_hash, probabili_file_id, deadline, written_at, "
                   "late, predictions) VALUES (21, 3, 'r', 'm', 1, '2026-09-04 18:45', '2026-09-04 13:46', ?, 2)", [run_id > 1])
        for pid, late in late_rows.items():
            db.execute("INSERT INTO predictions (lineup_run_id, season_id, giornata, player_id, p_start_published, p_start, "
                       "fv_if_plays, expected_points, source, late) VALUES (?, 21, 3, ?, 90, 0.9, 7.0, 6.3, 'published', ?)",
                       [run_id, pid, late])
    current = dict(db.execute("SELECT player_id, lineup_run_id FROM v_predictions_current ORDER BY player_id").fetchall())
    assert current == {2120: 1, 2764: 2}        # Bastoni's run-2 row was late for him; Martinez's was not
    assert db.execute("SELECT lineup_run_id FROM v_lineup_runs_current").fetchone()[0] == 1
```

Also update the existing `test_version_4_adds_the_forecast_and_roster_layer`: its `apply_schema(con) == 4 and SCHEMA_VERSION == 4` becomes `apply_schema(con) == 5 and SCHEMA_VERSION == 5`, its `predictions` column list gains the four new names at the end, and the two `version = 4` assertions become `version = 5`. `test_a_version_1_file_is_migrated_forward_in_place` asserts `max(version) == 4`: make it 5.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_schema.py -c core/pyproject.toml -q`
Expected: FAIL — `SCHEMA_VERSION == 4`, `news_files` missing.

- [ ] **Step 3: Write the DDL**

In `core/src/fantaclaude/db/schema.py`: add to the docstring, after the version-4 sentence:

```python
Version 5 (Phase 3b) adds the news layer -- news_files/unavailable, the two
public lists matched by name within the club -- widens predictions with the
player's own kickoff and lateness, the matchup term and the trace, widens
lineup_runs with the weekly hash, the bench, the contingencies and the close
calls, and adds lineup_submitted, the XI actually fielded. The new columns
are ALTER TABLE ... ADD COLUMN IF NOT EXISTS so a version-4 file upgrades in
place; its rows keep late = false, which is what they were.
```

Set `SCHEMA_VERSION = 5`. Replace the `predictions` CREATE with the widened
shape and add the rest of the DDL immediately after it (before the first
`CREATE OR REPLACE VIEW`):

```sql
CREATE TABLE IF NOT EXISTS predictions (
    lineup_run_id     INTEGER NOT NULL,
    season_id         INTEGER NOT NULL,
    giornata          INTEGER NOT NULL,
    player_id         INTEGER NOT NULL,
    p_start_published INTEGER,
    p_start           DOUBLE NOT NULL,
    fv_if_plays       DOUBLE NOT NULL,
    fv_sd             DOUBLE,
    expected_points   DOUBLE NOT NULL,
    source            VARCHAR NOT NULL,
    kickoff           TIMESTAMP,
    late              BOOLEAN DEFAULT false,
    matchup           DOUBLE,
    trace             JSON,
    PRIMARY KEY (lineup_run_id, player_id)
);
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS kickoff TIMESTAMP;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS late BOOLEAN DEFAULT false;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS matchup DOUBLE;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS trace JSON;
ALTER TABLE lineup_runs ADD COLUMN IF NOT EXISTS weekly_hash VARCHAR;
ALTER TABLE lineup_runs ADD COLUMN IF NOT EXISTS bench JSON;
ALTER TABLE lineup_runs ADD COLUMN IF NOT EXISTS contingencies JSON;
ALTER TABLE lineup_runs ADD COLUMN IF NOT EXISTS close_calls JSON;
CREATE SEQUENCE IF NOT EXISTS seq_news_files START 1;
CREATE TABLE IF NOT EXISTS news_files (
    file_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_news_files'),
    kind        VARCHAR NOT NULL,
    season_id   INTEGER NOT NULL,
    giornata    INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_path    VARCHAR NOT NULL,
    sha256      VARCHAR NOT NULL,
    row_count   INTEGER NOT NULL,
    teams       INTEGER NOT NULL,
    unmatched   INTEGER NOT NULL,
    UNIQUE (kind, season_id, giornata, sha256)
);
CREATE TABLE IF NOT EXISTS unavailable (
    file_id      INTEGER NOT NULL,
    season_id    INTEGER NOT NULL,
    giornata     INTEGER NOT NULL,
    kind         VARCHAR NOT NULL,
    team_name    VARCHAR NOT NULL,
    team_short   VARCHAR,
    name         VARCHAR NOT NULL,
    player_id    INTEGER,
    match_status VARCHAR NOT NULL,
    detail       VARCHAR,
    position     INTEGER NOT NULL,
    raw          JSON NOT NULL,
    PRIMARY KEY (file_id, position)
);
CREATE SEQUENCE IF NOT EXISTS seq_lineup_submitted START 1;
CREATE TABLE IF NOT EXISTS lineup_submitted (
    submitted_id  INTEGER PRIMARY KEY DEFAULT nextval('seq_lineup_submitted'),
    season_id     INTEGER NOT NULL,
    giornata      INTEGER NOT NULL,
    lineup_run_id INTEGER,
    my_team       INTEGER,
    module        VARCHAR NOT NULL,
    xi            JSON NOT NULL,
    bench         JSON NOT NULL,
    source        VARCHAR NOT NULL,
    recorded_at   TIMESTAMP NOT NULL
);
```

Check the existing `lineup_runs` CREATE: the four new columns must also be
appended to it (after `predictions INTEGER NOT NULL`) so a fresh file and an
upgraded one agree on column order:

```sql
    predictions       INTEGER NOT NULL,
    weekly_hash       VARCHAR,
    bench             JSON,
    contingencies     JSON,
    close_calls       JSON
```

The 3a `predictions` table had no primary key; adding one to the CREATE only
affects fresh files (an upgraded file keeps its shape), which is fine — the
writer never inserts a duplicate. Then add the views after
`v_lineup_runs_current`:

```sql
CREATE OR REPLACE VIEW v_news_files_current AS
    SELECT f.* FROM news_files f
    WHERE f.file_id = (SELECT max(g.file_id) FROM news_files g
                       WHERE g.kind = f.kind AND g.season_id = f.season_id AND g.giornata = f.giornata);
CREATE OR REPLACE VIEW v_unavailable_current AS
    SELECT u.* FROM unavailable u
    WHERE u.file_id IN (SELECT file_id FROM v_news_files_current);
CREATE OR REPLACE VIEW v_predictions_current AS
    SELECT p.* FROM predictions p
    WHERE NOT coalesce(p.late, false)
      AND p.lineup_run_id = (SELECT max(q.lineup_run_id) FROM predictions q
                             WHERE q.season_id = p.season_id AND q.giornata = p.giornata
                               AND q.player_id = p.player_id AND NOT coalesce(q.late, false));
CREATE OR REPLACE VIEW v_lineup_submitted_current AS
    SELECT s.* FROM lineup_submitted s
    WHERE s.submitted_id = (SELECT max(t.submitted_id) FROM lineup_submitted t
                            WHERE t.season_id = s.season_id AND t.giornata = s.giornata);
```

`weekly.write_lineup_run` inserts into `predictions` positionally
(`INSERT INTO predictions VALUES (?, ...)` with ten values); with fourteen
columns that insert now fails. Change it to name its columns — this is the
one edit to `analysis/weekly.py` in this task:

```python
        con.executemany(
            "INSERT INTO predictions (lineup_run_id, season_id, giornata, player_id, p_start_published, p_start, "
            "fv_if_plays, fv_sd, expected_points, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_schema.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite and lint, then commit**

```bash
uv run poe test && uv run poe lint
git add core/src/fantaclaude/db/schema.py core/src/fantaclaude/analysis/weekly.py core/tests/test_schema.py
git commit -m "feat(db): schema 5 -- the news layer, per-row lateness and the trace on predictions, the bench on lineup_runs, lineup_submitted"
```

---

### Task 3: The news adapter — `ingest/news.py` and `ingest news`

**Files:**
- Create: `core/src/fantaclaude/ingest/news.py`
- Create: `core/tests/test_news.py`
- Modify: `core/src/fantaclaude/cli/app.py` (after `ingest_probabili_cmd`)
- Modify: `core/tests/conftest.py` (add `seed_news`)
- Modify: `core/tests/test_lineup_cli.py` (the CLI test)

**Interfaces:**
- Consumes: `fantaclaude.ingest.names.{load_aliases, load_candidates, load_teams, match_listone, resolve_team, Match, UNMATCHED, Candidate}`, `ingest.raw.{RawStore, RawFile}`, `ingest.http.{fetch_bytes, polite_pause, run_web}`, `analysis.weekly.target_round`.
- Produces: `parse_news_page(html: str, *, page: str) -> NewsPage`; `fetch_news(http, store, *, page: str, label: str) -> RawFile`; `record_news(con, season_id: int, giornata: int, page: NewsPage, raw: RawFile, *, aliases_path: Path) -> NewsIngestResult`; the constants `PAGES = ("squalificati", "infortunati")`, `URLS`, `NewsShapeError`; rows in `unavailable` with `kind` in `squalificato | diffidato | infortunato` that Task 7 reads through `v_unavailable_current`; `seed_news(con, season_id, giornata, page, rows)` for tests.

- [ ] **Step 1: Write the failing parser tests**

```python
# core/tests/test_news.py
import json
from datetime import UTC, datetime

import pytest
from conftest import FIXTURE_DIR
from fantaclaude.ingest.news import (
    PAGES,
    NewsShapeError,
    parse_news_page,
    record_news,
    source_of,
)
from fantaclaude.ingest.raw import RawFile

INJURIES = (FIXTURE_DIR / "news_infortunati_sample.html").read_text(encoding="utf-8")
SUSPENSIONS = (FIXTURE_DIR / "news_squalificati_sample.html").read_text(encoding="utf-8")
EMPTY = '<div class="empty-list-message">Nessuno</div>'
ENTRY = ('<ul class="unstyled"><li><strong class="item-name">{name}</strong>'
         '<div class="item-description"><p>{detail}</p></div></li></ul>')


def test_the_injuries_page_lists_every_entry_under_its_club():
    page = parse_news_page(INJURIES, page="infortunati")
    assert page.page == "infortunati" and page.teams == 2 and page.empty_lists == 0
    assert [(r.team_name, r.name, r.kind) for r in page.rows] == [
        ("Atalanta", "Sulemana K.", "infortunato"), ("Atalanta", "Hien", "infortunato"),
        ("Bologna", "Orsolini", "infortunato"), ("Bologna", "El Azzouzi O.", "infortunato")]
    assert [r.position for r in page.rows] == [0, 1, 2, 3]
    assert "ottobre" in page.rows[0].detail and "<p>" not in page.rows[0].detail      # text, tags stripped
    assert page.rows[0].raw == {"team": "Atalanta", "label": None}


def test_the_suspensions_page_with_empty_columns_is_a_page_with_no_rows():
    page = parse_news_page(SUSPENSIONS, page="squalificati")
    assert page.rows == [] and page.teams == 2 and page.empty_lists == 4


def test_a_suspension_and_a_diffida_are_read_under_their_column_labels():
    # the entry shape is INFERRED from the injuries page (the capture had none): Task 12 confirms it
    text = SUSPENSIONS.replace(EMPTY, ENTRY.format(name="Kolasinac", detail="Una giornata"), 1)
    text = text.replace(EMPTY, ENTRY.format(name="Hien", detail="Quarta ammonizione"), 1)
    page = parse_news_page(text, page="squalificati")
    assert [(r.team_name, r.name, r.kind, r.detail) for r in page.rows] == [
        ("Atalanta", "Kolasinac", "squalificato", "Una giornata"), ("Atalanta", "Hien", "diffidato", "Quarta ammonizione")]
    assert page.empty_lists == 2 and page.rows[0].raw["label"] == "Squalificati"


def test_a_page_without_club_cards_fails_loud_and_names_the_selector():
    with pytest.raises(NewsShapeError, match="team-card"):
        parse_news_page("<html><body><h1>Infortunati Serie A</h1></body></html>", page="infortunati")


def test_a_suspensions_page_without_labels_fails_loud():
    unlabelled = SUSPENSIONS.replace('class="label label-danger"', 'class="tag"').replace('class="label label-warn"', 'class="tag"')
    with pytest.raises(NewsShapeError, match="label"):
        parse_news_page(unlabelled, page="squalificati")


def test_an_unknown_label_fails_loud_rather_than_guessing_a_kind():
    with pytest.raises(NewsShapeError, match="Infortunati lunghi"):
        parse_news_page(SUSPENSIONS.replace(">Diffidati<", ">Infortunati lunghi<", 1), page="squalificati")


def test_an_entry_under_no_label_on_the_suspensions_page_is_refused():
    # strip the first column's header, leaving an entry under nothing
    text = SUSPENSIONS.replace('<header>\n                    <strong class="label label-danger">Squalificati</strong>\n                </header>', "", 1)
    text = text.replace(EMPTY, ENTRY.format(name="Kolasinac", detail="Una giornata"), 1)
    with pytest.raises(NewsShapeError, match="no label"):
        parse_news_page(text, page="squalificati")


def test_the_match_widget_outside_the_cards_is_not_a_club():
    # `team-name team-link` anchors in the matchweek widget must not become a twenty-first club
    page = parse_news_page(INJURIES, page="infortunati")
    assert page.teams == 2 and INJURIES.count("team-name team-link") > 0


def _raw(tmp_path, text: str, page: str, stamp: str = "1") -> RawFile:
    path = tmp_path / f"news-{page}-{stamp}.html"
    path.write_text(text, encoding="utf-8")
    return RawFile(path, f"sha-{page}-{stamp}", datetime(2026, 9, 5, 12, 0, tzinfo=UTC), "news")


def _aliases(tmp_path):
    path = tmp_path / "aliases.yml"
    path.write_text("understat: {}\nfantacalcio_teams: {}\n", encoding="utf-8")
    return path


def test_record_appends_a_file_and_its_rows_and_dedupes_on_bytes(db, tmp_path):
    page = parse_news_page(INJURIES, page="infortunati")
    first = record_news(db, 21, 4, page, _raw(tmp_path, INJURIES, "infortunati"), aliases_path=_aliases(tmp_path))
    assert not first.skipped_duplicate and first.inserted == 4 and first.teams == 2
    assert first.unmatched == 4 and first.unknown_teams == 2          # no listone: every club and name unknown
    assert db.execute("SELECT kind, source, row_count, unmatched FROM news_files").fetchone() == (
        "infortunati", source_of("infortunati"), 4, 4)
    assert db.execute("SELECT kind, team_name, team_short, name, player_id, match_status FROM unavailable ORDER BY position").fetchall()[0] == (
        "infortunato", "Atalanta", None, "Sulemana K.", None, "unmatched")
    again = record_news(db, 21, 4, page, _raw(tmp_path, INJURIES, "infortunati"), aliases_path=_aliases(tmp_path))
    assert again.skipped_duplicate and again.file_id == first.file_id and again.inserted == 0
    later = record_news(db, 21, 4, page, _raw(tmp_path, INJURIES, "infortunati", stamp="2"), aliases_path=_aliases(tmp_path))
    assert later.file_id != first.file_id
    assert db.execute("SELECT file_id FROM v_news_files_current WHERE kind = 'infortunati'").fetchone()[0] == later.file_id
    assert db.execute("SELECT count(*) FROM v_unavailable_current").fetchone()[0] == 4


def test_record_matches_names_within_the_club_and_flags_the_rest(db, tmp_path, fixture_json):
    from fantaclaude.ingest.listone_api import load_listone, record_listone
    listone = fixture_json("listone_sample")
    path = tmp_path / "listone.json"
    path.write_text(json.dumps(listone), encoding="utf-8")
    record_listone(db, load_listone(path), RawFile(path, "sha-listone", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    # Atalanta is in the fixture listone (Kolasinac 2640, Rossi F. * 2297); Bologna is not
    text = INJURIES.replace("Sulemana K.", "Kolasinac", 1)
    page = parse_news_page(text, page="infortunati")
    result = record_news(db, 21, 4, page, _raw(tmp_path, text, "infortunati"), aliases_path=_aliases(tmp_path))
    rows = db.execute("SELECT name, team_short, player_id, match_status FROM unavailable ORDER BY position").fetchall()
    assert rows == [("Kolasinac", "ATA", 2640, "matched"), ("Hien", "ATA", None, "unmatched"),
                    ("Orsolini", None, None, "unmatched"), ("El Azzouzi O.", None, None, "unmatched")]
    assert result.unmatched == 3 and result.unknown_teams == 1


def test_record_never_matches_a_name_across_clubs(db, tmp_path, fixture_json):
    """Kolasinac is Atalanta's in the listone; listed under Bologna he must
    stay unmatched rather than be found by surname across the league."""
    from fantaclaude.ingest.listone_api import load_listone, record_listone
    path = tmp_path / "listone.json"
    path.write_text(json.dumps(fixture_json("listone_sample")), encoding="utf-8")
    record_listone(db, load_listone(path), RawFile(path, "sha-listone", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    (tmp_path / "aliases.yml").write_text("understat: {}\nfantacalcio_teams: {Bologna: Atalanta}\n", encoding="utf-8")
    text = INJURIES.replace("Orsolini", "Kolasinac", 1)
    page = parse_news_page(text, page="infortunati")
    record_news(db, 21, 4, page, _raw(tmp_path, text, "infortunati"), aliases_path=tmp_path / "aliases.yml")
    # with the alias, "Bologna" resolves to ATA and Kolasinac matches there -- the alias is the operator's call, not the adapter's
    assert db.execute("SELECT team_short, player_id FROM unavailable WHERE name = 'Kolasinac'").fetchone() == ("ATA", 2640)
    (tmp_path / "aliases.yml").write_text("understat: {}\nfantacalcio_teams: {}\n", encoding="utf-8")
    record_news(db, 21, 4, page, _raw(tmp_path, text, "infortunati", stamp="2"), aliases_path=tmp_path / "aliases.yml")
    assert db.execute("SELECT team_short, player_id FROM v_unavailable_current WHERE name = 'Kolasinac'").fetchone() == (None, None)


def test_pages_are_the_two_the_spec_names():
    assert PAGES == ("squalificati", "infortunati")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_news.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.ingest.news`.

- [ ] **Step 3: Write the adapter**

```python
# core/src/fantaclaude/ingest/news.py
"""The two news lists: squalificati/diffidati and infortunati (spec, "The
news adapter, and what fantacalcio.it already publishes").

Captured 2026-09-05, one anonymous request each (`captured/
squalificati-2026-09-05.html`, `captured/infortunati-2026-09-05.html`; the
fixtures are the Atalanta and Bologna cards trimmed from them by
`_extract_news.py`). Both pages are twenty club cards, `div.card.team-card`,
each opened by `span.team-name` -- the club as the listone spells it -- and
holding plain entries: `strong.item-name` (the player written the listone's
way, "Sulemana K.") followed by `div.item-description` (the page's prose).
There is NO link and NO player id anywhere on either page, so the join is
the repo's name-matching rule, not the free one the probabili page gives:
the club through `resolve_team` and the `fantacalcio` team aliases, the
player through `match_listone` against that club's candidates alone, and a
name that resolves to nobody is written with a null player_id and counted,
never dropped and never matched across clubs.

The suspensions page has two columns per club, each headed by a
`strong.label` reading "Squalificati" or "Diffidati", and a column with
nobody in it is `div.empty-list-message`. On the capture every column was
empty -- giornata 3 in progress, no Giudice Sportivo ruling yet, nobody on
four yellows after two rounds -- so the shape of a suspension entry is
INFERRED to be the injuries page's, not observed; Task 12's Tuesday capture
confirms or corrects it. The injuries page has one unlabelled list per club,
whose kind is the page's. The team menu above the cards and the matchweek
widget elsewhere repeat every club as `team-name team-link` anchors: neither
is a card, and a club name is read only inside a card.

The constants below pin what the captures showed; a page that no longer
matches fails loud (`NewsShapeError`), never silently.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes
from fantaclaude.ingest.names import (
    UNMATCHED,
    Candidate,
    Match,
    load_aliases,
    load_candidates,
    load_teams,
    match_listone,
    resolve_team,
)
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.timeutil import to_db

ORIGIN = "https://www.fantacalcio.it"
URLS = {"squalificati": f"{ORIGIN}/squalificati-e-diffidati-campionato-serie-a",
        "infortunati": f"{ORIGIN}/infortunati-serie-a"}
PAGES = tuple(URLS)
ALIAS_SOURCE = "fantacalcio"                   # the team aliases the calendar already keeps for this host
KINDS = ("squalificato", "diffidato", "infortunato")

# Pinned against the 2026-09-05 captures and verified against the fixtures.
CARD_CLASS = "team-card"
TEAM_NAME_CLASS = "team-name"
LABEL_CLASS = "label"
ITEM_NAME_CLASS = "item-name"
ITEM_DESCRIPTION_CLASS = "item-description"
EMPTY_CLASS = "empty-list-message"
LABEL_KINDS = (("squalific", "squalificato"), ("diffid", "diffidato"))
PAGE_KIND = {"infortunati": "infortunato"}     # a page whose lists carry no label
VOID_TAGS = frozenset({"meta", "img", "br", "input", "link", "hr", "source"})


def source_of(page: str) -> str:
    return f"fantacalcio.it:{URLS[page].removeprefix(ORIGIN)}"


class NewsShapeError(ValueError):
    """The page is not the list this adapter was written against."""


@dataclass(frozen=True)
class NewsRow:
    kind: str
    team_name: str
    name: str
    detail: str
    position: int
    raw: dict[str, Any]


@dataclass(frozen=True)
class NewsPage:
    page: str
    rows: list[NewsRow]
    teams: int
    empty_lists: int


class _Parser(HTMLParser):
    """A flat event stream in document order: card, team, label, name,
    detail, empty. Grouping into rows happens afterwards, on the stream."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str]] = []
        self._stack: list[tuple[str, str | None, bool]] = []     # (tag, capture kind, opens a card)
        self._buffers: list[list[str]] = []

    @property
    def _in_card(self) -> bool:
        return any(is_card for _, _, is_card in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=True)

    def _open(self, tag: str, a: dict[str, str | None], *, void: bool) -> None:
        classes = str(a.get("class") or "").split()
        is_card = CARD_CLASS in classes
        if is_card:
            self.events.append(("card", ""))
        capture = None
        if is_card or self._in_card:
            if TEAM_NAME_CLASS in classes and tag == "span":
                capture = "team"
            elif LABEL_CLASS in classes and tag == "strong":
                capture = "label"
            elif ITEM_NAME_CLASS in classes:
                capture = "name"
            elif ITEM_DESCRIPTION_CLASS in classes:
                capture = "detail"
            elif EMPTY_CLASS in classes:
                self.events.append(("empty", ""))
        if void:
            return
        self._stack.append((tag, capture, is_card))
        if capture:
            self._buffers.append([])

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, *_ in self._stack):
            return          # a stray end tag closes nothing; draining past it would forget every open tag
        while self._stack:
            open_tag, capture, _ = self._stack.pop()
            if capture:
                self.events.append((capture, " ".join("".join(self._buffers.pop()).split())))
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._buffers:
            self._buffers[-1].append(data)


def _kind_of(label: str) -> str:
    lowered = label.lower()
    for prefix, kind in LABEL_KINDS:
        if lowered.startswith(prefix):
            return kind
    raise NewsShapeError(f"unknown list label {label!r} -- the page names a list this adapter does not know")


def parse_news_page(html_text: str, *, page: str) -> NewsPage:
    if page not in PAGES:
        raise ValueError(f"page must be one of {PAGES}, got {page!r}")
    parser = _Parser()
    parser.feed(html_text)
    if not any(kind == "card" for kind, _ in parser.events):
        raise NewsShapeError(f"no div.{CARD_CLASS} on the page -- the {page} layout changed")
    default_kind = PAGE_KIND.get(page)
    rows: list[NewsRow] = []
    teams = empty = 0
    team: str | None = None
    label: str | None = None
    kind = default_kind
    pending: str | None = None

    def flush(detail: str = "") -> None:
        nonlocal pending
        if pending is not None:
            rows.append(NewsRow(str(kind), str(team), pending, detail, len(rows), {"team": team, "label": label}))
            pending = None

    for event, text in parser.events:
        if event == "card":
            flush()
            team, label, kind = None, None, default_kind
        elif event == "team":
            team = text
            teams += 1
        elif event == "label":
            flush()
            label, kind = text, _kind_of(text)
        elif event == "name":
            flush()
            if team is None:
                raise NewsShapeError(f"{text!r} is listed before any club name -- the card layout changed")
            if kind is None:
                raise NewsShapeError(f"{text!r} is listed under no label on the {page} page")
            pending = text
        elif event == "detail":
            if pending is None:
                raise NewsShapeError(f"an item description with no name before it ({text[:40]!r})")
            flush(text)
        elif event == "empty":
            empty += 1
    flush()
    if page not in PAGE_KIND and not any(event == "label" for event, _ in parser.events):
        raise NewsShapeError(f"no strong.{LABEL_CLASS} on the page -- the {page} columns are no longer labelled")
    return NewsPage(page, rows, teams, empty)


async def fetch_news(http: httpx.AsyncClient, store: RawStore, *, page: str, label: str) -> RawFile:
    data = await fetch_bytes(http, URLS[page])
    return store.write_bytes("news", data, ext="html", label=f"{page}-{label}")


@dataclass(frozen=True)
class NewsIngestResult:
    page: str
    file_id: int
    season_id: int
    giornata: int
    inserted: int
    skipped_duplicate: bool
    teams: int
    empty_lists: int
    unmatched: int
    unknown_teams: int
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "file_id": self.file_id, "season_id": self.season_id, "giornata": self.giornata,
                "inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate, "teams": self.teams,
                "empty_lists": self.empty_lists, "unmatched": self.unmatched, "unknown_teams": self.unknown_teams,
                "sha256": self.sha256, "raw_path": self.raw_path}


def match_rows(page: NewsPage, *, teams: dict[str, str], team_aliases: dict[str, str],
               candidates: list[Candidate]) -> list[tuple[NewsRow, str | None, Match]]:
    """Every row with the club it resolves to and the listone match within
    that club -- a candidate of another club is never considered."""
    by_team: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_team[c.team_short].append(c)
    out = []
    for row in page.rows:
        short = resolve_team(row.team_name, teams, team_aliases)
        match = match_listone(row.name, by_team.get(short, [])) if short else Match(None, UNMATCHED)
        out.append((row, short, match))
    return out


def record_news(con: duckdb.DuckDBPyConnection, season_id: int, giornata: int, page: NewsPage, raw: RawFile, *,
                aliases_path: Path) -> NewsIngestResult:
    """Append one file row and its entries; the same bytes for the same page
    and giornata is a no-op. A later fetch is a later file: v_news_files_current
    picks the newest per page, and nothing is overwritten."""
    existing = con.execute("SELECT file_id, unmatched FROM news_files WHERE kind = ? AND season_id = ? AND giornata = ? "
                           "AND sha256 = ?", [page.page, season_id, giornata, raw.sha256]).fetchone()
    if existing is not None:
        return NewsIngestResult(page.page, int(existing[0]), season_id, giornata, 0, True, page.teams, page.empty_lists,
                                int(existing[1]), 0, raw.sha256, str(raw.path))
    matched = match_rows(page, teams=load_teams(con), team_aliases=load_aliases(aliases_path).teams_for(ALIAS_SOURCE),
                         candidates=load_candidates(con))
    unmatched = sum(1 for _, _, m in matched if m.player_id is None)
    unknown_teams = len({row.team_name for row, short, _ in matched if short is None})
    con.begin()
    try:
        file_id = con.execute(
            "INSERT INTO news_files (kind, season_id, giornata, fetched_at, source, raw_path, sha256, row_count, teams, "
            "unmatched) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
            [page.page, season_id, giornata, to_db(raw.fetched_at), source_of(page.page), str(raw.path), raw.sha256,
             len(page.rows), page.teams, unmatched]).fetchone()[0]
        con.executemany(
            "INSERT INTO unavailable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[file_id, season_id, giornata, row.kind, row.team_name, short, row.name, match.player_id, match.status,
              row.detail or None, row.position, json.dumps({**row.raw, "candidates": list(match.candidates)}, ensure_ascii=False)]
             for row, short, match in matched])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return NewsIngestResult(page.page, int(file_id), season_id, giornata, len(page.rows), False, page.teams,
                            page.empty_lists, unmatched, unknown_teams, raw.sha256, str(raw.path))
```

- [ ] **Step 4: Run the parser and record tests**

Run: `uv run pytest core/tests/test_news.py -c core/pyproject.toml -q`
Expected: PASS. If `test_an_entry_under_no_label_on_the_suspensions_page_is_refused` fails on the header replacement not matching, print the fixture's exact bytes around `label-danger` and adjust the replacement string in the test (the test rewrites the sample; the fixture is never edited).

- [ ] **Step 5: Add `seed_news` to conftest**

```python
def seed_news(con, season_id: int, giornata: int, page: str, rows) -> int:
    """One synthetic news file. `rows` are (kind, team_name, team_short, name, player_id, detail);
    a row with player_id None is written as unmatched."""
    from uuid import uuid4
    file_id = con.execute(
        "INSERT INTO news_files (kind, season_id, giornata, fetched_at, source, raw_path, sha256, row_count, teams, unmatched) "
        "VALUES (?, ?, ?, now(), 'seed', ?, ?, ?, 20, ?) RETURNING file_id",
        [page, season_id, giornata, f"seed/news-{page}-{season_id}-{giornata}", f"seed-news-{uuid4().hex[:8]}", len(rows),
         sum(1 for r in rows if r[4] is None)]).fetchone()[0]
    for position, (kind, team_name, team_short, name, player_id, detail) in enumerate(rows):
        con.execute("INSERT INTO unavailable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
                    [file_id, season_id, giornata, kind, team_name, team_short, name, player_id,
                     "matched" if player_id is not None else "unmatched", detail, position])
    return file_id
```

- [ ] **Step 6: Write the failing CLI test**

Append to `core/tests/test_lineup_cli.py`:

```python
INJURIES = (FIXTURE_DIR / "news_infortunati_sample.html").read_text(encoding="utf-8")
SUSPENSIONS = (FIXTURE_DIR / "news_squalificati_sample.html").read_text(encoding="utf-8")


@respx.mock
def test_ingest_news_fetches_each_page_once_and_records_under_the_calendars_giornata(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    suspensions = respx.get("https://www.fantacalcio.it/squalificati-e-diffidati-campionato-serie-a").mock(
        return_value=httpx.Response(200, text=SUSPENSIONS))
    injuries = respx.get("https://www.fantacalcio.it/infortunati-serie-a").mock(return_value=httpx.Response(200, text=INJURIES))
    result = runner.invoke(app, ["ingest", "news", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)["news"]
    assert [p["page"] for p in payload] == ["squalificati", "infortunati"]
    assert suspensions.call_count == 1 and injuries.call_count == 1
    # the seeded listone has Atalanta (Kolasinac, Rossi F. *) but none of the four injured names, and no Bologna
    assert payload[1]["giornata"] == 3 and payload[1]["inserted"] == 4
    assert payload[1]["unmatched"] == 4 and payload[1]["unknown_teams"] == 1
    assert list((tmp_path / "data" / "raw" / "news").glob("*-news-infortunati-21-03.html"))
    plain = runner.invoke(app, ["ingest", "news", "--page", "infortunati"])
    assert plain.exit_code == ExitCode.OK and "duplicate" in plain.stdout and injuries.call_count == 2 and suspensions.call_count == 1
    bad = runner.invoke(app, ["ingest", "news", "--page", "rumours"])
    assert bad.exit_code == ExitCode.USAGE and "squalificati" in bad.stderr
```

- [ ] **Step 7: Write the command**

In `core/src/fantaclaude/cli/app.py`, after `ingest_probabili_cmd`:

```python
def _render_news(payload: dict) -> str:
    lines = []
    for r in payload["news"]:
        head = f"news {r['page']} {r['season_id']} giornata {r['giornata']}"
        if r["skipped_duplicate"]:
            lines.append(f"{head}: duplicate of file {r['file_id']} -- nothing new ({r['raw_path']})")
            continue
        line = f"{head}: file {r['file_id']}, {r['inserted']} entries over {r['teams']} clubs"
        if r["empty_lists"]:
            line += f" ({r['empty_lists']} empty list(s))"
        if r["unmatched"]:
            line += f"; {r['unmatched']} name(s) unmatched -- `fantaclaude query --sql \"SELECT * FROM v_unavailable_current WHERE player_id IS NULL\"`"
        if r["unknown_teams"]:
            line += f"; {r['unknown_teams']} club(s) not in the listone (kb/rules/aliases.yml, fantacalcio_teams)"
        lines.append(f"{line} ({r['raw_path']})")
    return "\n".join(lines)


NEWS_PAGE_OPTION = typer.Option(None, "--page", help="squalificati or infortunati; repeatable (default: both, one request each).")


@ingest_app.command("news")
def ingest_news_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = GIORNATA_ONE_OPTION,
    page: list[str] | None = NEWS_PAGE_OPTION,
) -> None:
    """The squalificati/diffidati and infortunati lists (fantacalcio.it, public), matched by name within each club. One request per page."""
    from fantaclaude.analysis.weekly import ForecastError, target_round
    from fantaclaude.commands.ingest import ensure_schema
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import polite_pause, run_web
    from fantaclaude.ingest.news import PAGES, fetch_news, parse_news_page, record_news
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir
    from fantaclaude.timeutil import utc_now

    pages = list(dict.fromkeys(page)) if page else list(PAGES)
    bad = [p for p in pages if p not in PAGES]
    if bad:
        typer.echo(f"--page must be one of {', '.join(PAGES)}, got {bad}", err=True)
        raise typer.Exit(code=ExitCode.USAGE)
    ensure_schema()
    season_id = _seasons_or_exit(None)[-1]
    con = connect(read_only=True)
    try:
        round_ = target_round(con, utc_now(), season_id=season_id, giornata=giornata)
    except ForecastError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    finally:
        con.close()
    store = RawStore(raw_dir())
    label = f"{season_id}-{round_.giornata:02d}"

    async def go(http):
        raws = {}
        for i, p in enumerate(pages):
            if i:
                await polite_pause()
            raws[p] = await fetch_news(http, store, page=p, label=label)
        return raws

    with _source_errors():
        raws = run_web(go)
        parsed = {p: parse_news_page(raws[p].path.read_text(encoding="utf-8"), page=p) for p in pages}
        con = connect()
        try:
            apply_schema(con)
            results = [record_news(con, season_id, round_.giornata, parsed[p], raws[p], aliases_path=aliases_path())
                       for p in pages]
        finally:
            con.close()
    emit({"news": [r.to_dict() for r in results]}, json_=json_, render=_render_news)
```

- [ ] **Step 8: Run the tests, the suite and lint; commit**

```bash
uv run pytest core/tests/test_news.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q
uv run poe test && uv run poe lint
git add core/src/fantaclaude/ingest/news.py core/src/fantaclaude/cli/app.py core/tests/test_news.py core/tests/conftest.py core/tests/test_lineup_cli.py
git commit -m "feat(ingest): news -- squalificati, diffidati and infortunati off the two public lists, matched by name within the club, flagged when unresolved"
```

---

### Task 4: `analysis/weekly.py` becomes the package `analysis/weekly/` (pure refactor)

Nothing changes behaviour. Every public name 3a's module exported keeps
its import path (`from fantaclaude.analysis.weekly import lineup`), so no
test and no CLI import moves. The split is done now, before Tasks 5–10 grow
the code, and the whole suite is the proof.

**Files:**
- Delete: `core/src/fantaclaude/analysis/weekly.py`
- Create: `core/src/fantaclaude/analysis/weekly/__init__.py`, `errors.py`, `rounds.py`, `forecast.py`, `xi.py`, `records.py`, `report.py`

**Interfaces:**
- Produces: the same names, at the same import path, plus the module paths later tasks edit: `weekly.rounds`, `weekly.forecast`, `weekly.xi`, `weekly.records`, `weekly.report`, `weekly.errors`.

- [ ] **Step 1: Run the suite once, green, as the baseline**

Run: `uv run pytest core/tests -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 2: Create the package, moving bodies verbatim**

Move the code of `analysis/weekly.py` into the modules below. Function and
class bodies are pasted **unchanged**; only the module docstrings, the
imports and the file they live in change. The list per module is complete.

`errors.py`:

```python
"""What the weekly loop refuses to do, and why."""

from __future__ import annotations


class ForecastError(RuntimeError):
    """A forecast cannot be written from what is on disk (no calendar, no page, no run)."""


class LateForecast(ForecastError):
    """The giornata has kicked off; a forecast written now is not a forecast."""
```

`rounds.py` — `Round`, `target_round`, `MATCHDAY_READ_WINDOW`,
`matchday_cross_check`, `STALE_COMPILATION`, `compilation_staleness`,
`uncompiled_match_warning`:

```python
"""The round and its deadlines, read off `fixtures`, never off the stored
`status.mday` (spec, "The round and the deadline are read off the calendar;
`status` is the cross-check")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.timeutil import to_db
```

`forecast.py` — `ForecastRow`, `newest_probabili_file`, `forecast`:

```python
"""The forecast rows: every player the page lists and the run prices (spec,
"Predictions are written for every player the page lists and the run prices
-- not for my roster")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb
```

`xi.py` — `ADAPTED_MALUS`, `RosterPlayer`, `my_roster`, `XiSlot`,
`XiChoice`, `choose_xi`:

```python
"""The XI: my roster from the latest snapshot, one exact solve per permitted
module (spec, "The optimiser")."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.forecast import ForecastRow
from fantaclaude.model.modules import Module, assign_weighted
from fantaclaude.model.roles import Role
```

`records.py` — `write_lineup_run`, `export_lineup_records`:

```python
"""The immutable write: one lineup_runs row and its predictions, appended,
refused after the deadline unless late, and the parquet copies under
records/ (spec, "Forecasts are immutable")."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.exports import write_parquet
from fantaclaude.analysis.weekly.errors import ForecastError, LateForecast
from fantaclaude.analysis.weekly.forecast import ForecastRow
from fantaclaude.analysis.weekly.rounds import Round
from fantaclaude.timeutil import to_db
```

`report.py` — `TOP_PER_ROLE`, `LineupReport`, `lineup`:

```python
"""The facade the CLI calls: the round, the page, the forecast, the XI when
league.yml names my team, the write, the records, the warnings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.forecast import ForecastRow, forecast, newest_probabili_file
from fantaclaude.analysis.weekly.records import export_lineup_records, write_lineup_run
from fantaclaude.analysis.weekly.rounds import (
    Round,
    compilation_staleness,
    matchday_cross_check,
    target_round,
    uncompiled_match_warning,
)
from fantaclaude.analysis.weekly.xi import choose_xi, my_roster
from fantaclaude.asta.pinned import newest_run_id
from fantaclaude.model.modules import load_modules
```

`__init__.py`:

```python
"""The weekly forecast (spec, "`fanta-manager` -- the weekly loop").

3a's `analysis/weekly.py`, split by concern in 3b: `rounds` (the round and
its deadlines), `forecast` (the rows), `xi` (the solve), `records` (the
immutable write), `report` (the facade). Every public name is re-exported
here so callers keep their import path.
"""

from fantaclaude.analysis.weekly.errors import ForecastError, LateForecast
from fantaclaude.analysis.weekly.forecast import ForecastRow, forecast, newest_probabili_file
from fantaclaude.analysis.weekly.records import export_lineup_records, write_lineup_run
from fantaclaude.analysis.weekly.report import TOP_PER_ROLE, LineupReport, lineup
from fantaclaude.analysis.weekly.rounds import (
    MATCHDAY_READ_WINDOW,
    STALE_COMPILATION,
    Round,
    compilation_staleness,
    matchday_cross_check,
    target_round,
    uncompiled_match_warning,
)
from fantaclaude.analysis.weekly.xi import (
    ADAPTED_MALUS,
    RosterPlayer,
    XiChoice,
    XiSlot,
    choose_xi,
    my_roster,
)

__all__ = [
    "ADAPTED_MALUS", "MATCHDAY_READ_WINDOW", "STALE_COMPILATION", "TOP_PER_ROLE",
    "ForecastError", "ForecastRow", "LateForecast", "LineupReport", "RosterPlayer", "Round", "XiChoice", "XiSlot",
    "choose_xi", "compilation_staleness", "export_lineup_records", "forecast", "lineup", "matchday_cross_check",
    "my_roster", "newest_probabili_file", "target_round", "uncompiled_match_warning", "write_lineup_run",
]
```

Then `git rm core/src/fantaclaude/analysis/weekly.py`.

- [ ] **Step 3: Run the suite and lint**

Run: `uv run poe test && uv run poe lint`
Expected: PASS, no import errors. `ruff` may flag an unused import in a
module whose functions you did not paste — that is the signal a body landed
in the wrong file; fix the placement, never the import.

- [ ] **Step 4: Commit**

```bash
git add -A core/src/fantaclaude/analysis/weekly core/src/fantaclaude/analysis/weekly.py
git commit -m "refactor(weekly): the package split -- rounds, forecast, xi, records, report; every name keeps its import path"
```

---

### Task 5: Per-player deadlines

Open question 18, resolved: each prediction is late against its player's
own kickoff; the run's `late` keeps meaning the XI was named after the first
kickoff; the write is refused only once every match has started.

**Files:**
- Modify: `core/src/fantaclaude/analysis/weekly/rounds.py` (add `PlayerFixture`, `player_fixtures`)
- Modify: `core/src/fantaclaude/analysis/weekly/forecast.py` (`ForecastRow.kickoff`, `forecast(..., fixtures=)`)
- Modify: `core/src/fantaclaude/analysis/weekly/records.py` (per-row `late`, the refusal rule)
- Modify: `core/src/fantaclaude/analysis/weekly/report.py` (`late_predictions`, the wording)
- Modify: `core/src/fantaclaude/analysis/weekly/__init__.py` (export the two new names)
- Modify: `core/src/fantaclaude/cli/app.py` (`_render_lineup`, the `--late` help)
- Modify: `core/tests/conftest.py` (`seed_matches`; `seed_probabili` gains `team_short`)
- Create: `core/tests/test_weekly_rounds.py`
- Modify: `core/tests/test_lineup_cli.py`

**Interfaces:**
- Produces: `PlayerFixture(kickoff: datetime, home: bool, opponent_short: str | None)`; `player_fixtures(con, probabili_file_id: int) -> dict[int, PlayerFixture]`; `ForecastRow.kickoff: datetime | None`; `forecast(con, *, run_id, probabili_file_id, fixtures: dict[int, PlayerFixture] | None = None)`; `write_lineup_run(...)` unchanged signature, now writes `kickoff` and per-row `late`; `LineupReport.late_predictions: int`; payload key `late_predictions`.

- [ ] **Step 1: Extend the seeds**

In `core/tests/conftest.py`, let `seed_probabili` accept an optional fifth
element, the team short code, and add `seed_matches`:

```python
def seed_probabili(con, season_id: int, giornata: int, rows) -> int:
    """One synthetic probabili file. `rows` are (player_id, name, club_slug, p_start)
    or (player_id, name, club_slug, p_start, team_short)."""
    from uuid import uuid4
    file_id = con.execute(
        "INSERT INTO probabili_files (season_id, giornata, fetched_at, source, raw_path, sha256, row_count, matches, uncompiled) "
        "VALUES (?, ?, now(), 'seed', ?, ?, ?, 1, 0) RETURNING file_id",
        [season_id, giornata, f"seed/prob-{season_id}-{giornata}", f"seed-prob-{uuid4().hex[:8]}", len(rows)]).fetchone()[0]
    for row in rows:
        player_id, name, club, p_start = row[:4]
        short = row[4] if len(row) > 4 else None
        con.execute("INSERT INTO probabili VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, false, NULL, '{}')",
                    [file_id, season_id, giornata, player_id, name, club, short, p_start])
    return file_id


def seed_matches(con, season_id: int, rows) -> int:
    """One Serie A calendar snapshot with clubs. `rows` are (giornata, kickoff aware UTC, home_short, away_short)."""
    from uuid import uuid4

    from fantaclaude.timeutil import to_db
    snapshot_id = con.execute(
        "INSERT INTO fixture_snapshots (competition, season_id, fetched_at, source, raw_paths, sha256, row_count) "
        "VALUES ('SA', ?, now(), 'seed', [], ?, ?) RETURNING snapshot_id",
        [season_id, f"seed-fix-{uuid4().hex[:8]}", len(rows)]).fetchone()[0]
    for i, (giornata, kickoff, home, away) in enumerate(rows):
        con.execute("INSERT INTO fixtures VALUES (?, 'SA', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, '{}')",
                    [snapshot_id, season_id, f"seed-{giornata}-{i}", str(giornata), giornata, to_db(kickoff), home, away, home, away])
    return snapshot_id
```

- [ ] **Step 2: Write the failing tests**

```python
# core/tests/test_weekly_rounds.py
from datetime import UTC, datetime, timedelta

import pytest
from conftest import seed_matches, seed_probabili
from fantaclaude.analysis.weekly import ForecastRow, LateForecast, Round, player_fixtures, write_lineup_run

T0 = datetime(2026, 9, 11, 18, 45, tzinfo=UTC)          # Friday
SUNDAY = T0 + timedelta(days=2, hours=-4)                # 14:45 UTC Sunday
MONDAY = T0 + timedelta(days=3)


def _round():
    return Round(21, 4, T0.replace(tzinfo=None), MONDAY.replace(tzinfo=None), 3)


def _rows(kickoffs):
    return [ForecastRow(pid, f"p{pid}", short, "A", ("A",), 90, 0.9, 7.0, None, 6.3, "published", kickoff=k)
            for pid, short, k in kickoffs]


def _seed(db):
    seed_matches(db, 21, [(4, T0, "INT", "ROM"), (4, SUNDAY, "ATA", "GEN"), (4, MONDAY, "MIL", "NAP")])
    return seed_probabili(db, 21, 4, [(2764, "Martinez L.", "inter", 90, "INT"), (5841, "Svilar", "roma", 100, "ROM"),
                                      (2640, "Kolasinac", "atalanta", 55, "ATA"), (999, "Ghost", "nowhere", 50, None)])


def test_player_fixtures_join_by_team_short_and_say_home_and_opponent(db):
    file_id = _seed(db)
    fixtures = player_fixtures(db, file_id)
    assert set(fixtures) == {2764, 5841, 2640}                                   # the unmatched club has no fixture
    assert (fixtures[2764].kickoff, fixtures[2764].home, fixtures[2764].opponent_short) == (T0.replace(tzinfo=None), True, "ROM")
    assert (fixtures[5841].home, fixtures[5841].opponent_short) == (False, "INT")
    assert fixtures[2640].kickoff == SUNDAY.replace(tzinfo=None)


def test_a_run_between_the_first_and_last_kickoff_marks_rows_per_player_and_the_xi_late(db):
    file_id = _seed(db)
    rows = _rows([(2764, "INT", T0.replace(tzinfo=None)), (2640, "ATA", SUNDAY.replace(tzinfo=None)), (999, None, None)])
    now = T0 + timedelta(hours=3)                                                # Friday night: Inter played, Atalanta not yet
    run_id, is_late = write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id,
                                       rows=rows, now=now, late=False)
    assert is_late is True                                                       # the XI lock passed at the first kickoff
    got = dict(db.execute("SELECT player_id, late FROM predictions WHERE lineup_run_id = ?", [run_id]).fetchall())
    assert got == {2764: True, 2640: False, 999: True}                           # no fixture: the round's first kickoff rules
    assert db.execute("SELECT kickoff FROM predictions WHERE player_id = 999").fetchone()[0] is None
    assert db.execute("SELECT count(*) FROM v_predictions_current").fetchone()[0] == 1     # Kolasinac's row is the honest one


def test_a_run_before_the_first_kickoff_is_on_time_for_everyone(db):
    file_id = _seed(db)
    rows = _rows([(2764, "INT", T0.replace(tzinfo=None)), (2640, "ATA", SUNDAY.replace(tzinfo=None))])
    run_id, is_late = write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id,
                                       rows=rows, now=T0 - timedelta(hours=1), late=False)
    assert is_late is False
    assert {r[0] for r in db.execute("SELECT late FROM predictions").fetchall()} == {False}


def test_a_run_after_every_kickoff_is_refused_unless_late_and_then_every_row_is_late(db):
    file_id = _seed(db)
    rows = _rows([(2764, "INT", T0.replace(tzinfo=None)), (2640, "ATA", SUNDAY.replace(tzinfo=None))])
    with pytest.raises(LateForecast, match="every match"):
        write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id, rows=rows,
                         now=MONDAY + timedelta(minutes=1), late=False)
    run_id, is_late = write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id,
                                       rows=rows, now=MONDAY + timedelta(minutes=1), late=True)
    assert is_late and {r[0] for r in db.execute("SELECT late FROM predictions").fetchall()} == {True}
    assert db.execute("SELECT count(*) FROM v_predictions_current").fetchone()[0] == 0
```

Also rewrite `test_lineup_is_refused_after_kickoff_and_marked_with_late` in
`core/tests/test_lineup_cli.py` — the 3a test seeded a giornata with one
kickoff an hour ago and one three days ahead and expected a refusal; that is
now a legitimate write:

```python
def test_lineup_between_kickoffs_writes_and_marks_per_player_and_after_all_of_them_needs_late(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    now = datetime.now(UTC)
    seed_matches(con, 21, [(3, now - timedelta(hours=1), "INT", "ROM"), (3, now + timedelta(days=2), "ATA", "GEN"),
                           (4, now + timedelta(days=7), "MIL", "NAP")])
    seed_probabili(con, 21, 3, [(2764, "Martinez L.", "inter", 90, "INT"), (5841, "Svilar", "roma", 100, "ROM"),
                                (2640, "Kolasinac", "atalanta", 55, "ATA")])
    con.close()
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["late"] is True and payload["predictions"] == 3 and payload["late_predictions"] == 2
    plain = runner.invoke(app, ["lineup"])
    assert "LATE XI" in plain.stdout and "1 on time, 2 late" in plain.stdout
    # once every match of the round has started, the write needs --late
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_matches(con, 21, [(3, now - timedelta(days=3), "INT", "ROM"), (3, now - timedelta(hours=1), "ATA", "GEN"),
                           (4, now + timedelta(days=7), "MIL", "NAP")])
    con.close()
    refused = runner.invoke(app, ["lineup"])
    assert refused.exit_code == ExitCode.CONFLICT and "--late" in refused.stderr
    late = runner.invoke(app, ["lineup", "--late", "--json"])
    assert late.exit_code == ExitCode.OK and json.loads(late.stdout)["late_predictions"] == 3
```

Import `seed_matches` from `conftest` at the top of `test_lineup_cli.py`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_weekly_rounds.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q`
Expected: FAIL — `player_fixtures` not importable; `ForecastRow` has no `kickoff`.

- [ ] **Step 4: Implement**

`rounds.py` — add after `Round`:

```python
@dataclass(frozen=True)
class PlayerFixture:
    kickoff: datetime                # naive UTC, as fixtures stores it
    home: bool
    opponent_short: str | None


def player_fixtures(con: duckdb.DuckDBPyConnection, probabili_file_id: int) -> dict[int, PlayerFixture]:
    """Each listed player's own match, joined by `team_short` the way the
    staleness check already joins; a player whose club the page did not
    resolve, or whose match has no kickoff, is absent -- the caller falls
    back to the round's first kickoff and says so (open question 18)."""
    rows = con.execute(
        "SELECT p.player_id, f.kickoff, f.home_short = p.team_short, "
        "CASE WHEN f.home_short = p.team_short THEN f.away_short ELSE f.home_short END "
        "FROM probabili p JOIN v_fixtures_current f ON f.competition = 'SA' AND f.season_id = p.season_id "
        "AND f.giornata = p.giornata AND (f.home_short = p.team_short OR f.away_short = p.team_short) "
        "WHERE p.file_id = ? AND p.team_short IS NOT NULL AND f.kickoff IS NOT NULL", [probabili_file_id]).fetchall()
    return {int(pid): PlayerFixture(kickoff, bool(home), opponent) for pid, kickoff, home, opponent in rows}
```

`forecast.py` — `ForecastRow` gains `kickoff: datetime | None = None` as its
last field, `to_dict` emits it as `isoformat(sep=" ", timespec="minutes")`
or `None`, and `forecast` takes and threads the fixtures:

```python
def forecast(con: duckdb.DuckDBPyConnection, *, run_id: str, probabili_file_id: int,
             fixtures: dict[int, PlayerFixture] | None = None) -> list[ForecastRow]:
    """Every player the page lists and the run prices. p_start is the
    published number alone until Task 7 (`source: published`), fv_sd is null."""
    fixtures = fixtures or {}
    rows = con.execute(
        "SELECT v.player_id, v.name, v.team_short, v.classic_role, v.roles, v.exp_fantamedia, p.p_start "
        "FROM valuations v JOIN probabili p ON p.player_id = v.player_id "
        "WHERE v.run_id = ? AND p.file_id = ? ORDER BY v.player_id", [run_id, probabili_file_id]).fetchall()
    out: list[ForecastRow] = []
    for pid, name, short, role, roles, fm, published in rows:
        p_start = int(published) / 100.0
        fixture = fixtures.get(int(pid))
        out.append(ForecastRow(int(pid), str(name), short, str(role), tuple(roles), int(published), p_start,
                               float(fm), None, p_start * float(fm), "published",
                               kickoff=None if fixture is None else fixture.kickoff))
    return out
```

(`from fantaclaude.analysis.weekly.rounds import PlayerFixture` at the top.)

`records.py` — the refusal and the per-row lateness:

```python
def write_lineup_run(con: duckdb.DuckDBPyConnection, *, round_: Round, run_id: str, model_hash: str,
                     probabili_file_id: int, rows: list[ForecastRow], now: datetime, late: bool,
                     my_team: int | None = None, module: str | None = None,
                     xi: list[dict[str, Any]] | None = None,
                     module_scores: dict[str, float | None] | None = None) -> tuple[int, bool]:
    """One lineup_runs row and its predictions, appended. The run is late
    once the round's first kickoff has passed (the lega's lock on the XI);
    each prediction is late once ITS player's kickoff has passed -- the
    round's first when no fixture matched him. The write is refused only
    once every match of the round has started, unless `late`; between the
    first kickoff and the last it writes and marks (open question 18)."""
    written_at = to_db(now)
    is_late = written_at >= round_.first_kickoff
    if written_at >= round_.last_kickoff and not late:
        raise LateForecast(
            f"giornata {round_.giornata}: every match has kicked off (the last at {round_.last_kickoff:%Y-%m-%d %H:%M} UTC); "
            f"a forecast written now is not a forecast -- pass --late to write it marked, and calibration will exclude it")
    if not rows:
        raise ForecastError(f"nothing to forecast: no player on probabili file {probabili_file_id} is priced by run {run_id}")
    con.begin()
    try:
        lineup_run_id = con.execute(
            "INSERT INTO lineup_runs (season_id, giornata, run_id, model_hash, probabili_file_id, deadline, written_at, "
            "late, my_team, module, xi, module_scores, predictions) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?) "
            "RETURNING lineup_run_id",
            [round_.season_id, round_.giornata, run_id, model_hash, probabili_file_id, round_.first_kickoff, written_at,
             is_late, my_team, module, None if xi is None else json.dumps(xi, ensure_ascii=False),
             None if module_scores is None else json.dumps(module_scores), len(rows)]).fetchone()[0]
        con.executemany(
            "INSERT INTO predictions (lineup_run_id, season_id, giornata, player_id, p_start_published, p_start, "
            "fv_if_plays, fv_sd, expected_points, source, kickoff, late) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [[lineup_run_id, round_.season_id, round_.giornata, r.player_id, r.p_start_published, r.p_start,
              r.fv_if_plays, r.fv_sd, r.expected_points, r.source, r.kickoff,
              written_at >= (r.kickoff or round_.first_kickoff)] for r in rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return int(lineup_run_id), is_late
```

`report.py` — `lineup()` computes the fixtures once and passes them; the
report carries the count:

```python
    fixtures = player_fixtures(con, file_id)
    rows = forecast(con, run_id=run_id, probabili_file_id=file_id, fixtures=fixtures)
```

Add `late_predictions: int` to `LineupReport` (after `late`), computed after
the write as
`sum(1 for r in rows if to_db(now) >= (r.kickoff or round_.first_kickoff))`,
and emit it in `to_dict` as `"late_predictions"`. Import `player_fixtures`
from `rounds` and `to_db` from `timeutil`. Export `PlayerFixture` and
`player_fixtures` from `__init__.py`.

`cli/app.py` — in `_render_lineup`, replace the `LATE:` line:

```python
    if payload["late"]:
        on_time = payload["predictions"] - payload["late_predictions"]
        lines.append(f"LATE XI: the round's first kickoff has passed -- the XI cannot be fielded; "
                     f"predictions {on_time} on time, {payload['late_predictions']} late (their matches have started)")
```

and the `--late` help becomes: `"Write even though every match of the giornata has kicked off; every row is marked and calibration excludes them."`

- [ ] **Step 5: Run the tests, the suite and lint; commit**

```bash
uv run pytest core/tests/test_weekly_rounds.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q
uv run poe test && uv run poe lint
git add core/src/fantaclaude/analysis/weekly core/src/fantaclaude/cli/app.py core/tests/conftest.py core/tests/test_weekly_rounds.py core/tests/test_lineup_cli.py
git commit -m "feat(weekly): per-player deadlines -- a prediction is late against its own kickoff, the XI against the first, the write refused only after the last"
```

---

### Task 6: `data/lineup-notes.yml`, `fantaclaude lineup note`, the `lineup` group, the doctor check

**Files:**
- Create: `core/src/fantaclaude/analysis/weekly/notes.py`
- Modify: `core/src/fantaclaude/paths.py` (`lineup_notes_path`)
- Modify: `core/src/fantaclaude/cli/app.py` (`lineup` becomes a group; `lineup note`; `DoctorPaths(... lineup_notes=...)`)
- Modify: `core/src/fantaclaude/commands/doctor.py` (`DoctorPaths.lineup_notes`, `_lineup_notes_check`)
- Create: `core/tests/test_lineup_notes.py`
- Modify: `core/tests/test_doctor.py` (`NAMES`, `_paths`), `core/tests/test_lineup_cli.py`

**Interfaces:**
- Consumes: `asta.adjustments`'s shape (mirrored, not imported: the kinds differ), `ingest.names.{match_listone, load_candidates, Candidate, Match, AMBIGUOUS}`, `atomic.write_atomic`, `values.is_number`.
- Produces: `LineupNote(kind, giornata, reason, player=None, player_id=None, p_start=None, factor=None)` with `to_entry()` and `describe()`; `KINDS = ("p_start", "value", "exclude")`; `LineupNotesError`; `note_from_entry(raw, where) -> LineupNote`; `parse_lineup_notes(text, *, where) -> list[LineupNote]`; `load_lineup_notes(path) -> list[LineupNote]`; `append_lineup_note(path, note) -> list[LineupNote]`; `resolve_notes(notes, candidates, *, giornata: int | None) -> NotesLayer` where `NotesLayer(giornata, entries: tuple[ResolvedNote, ...], p_start: dict[int, tuple[float, str]], value_factor: dict[int, tuple[float, str]], excluded: dict[int, str], problems: tuple[str, ...], inert: int)`; `EMPTY_NOTES`; `paths.lineup_notes_path()`; the `lineup` Typer group with `note`.

- [ ] **Step 1: Write the failing unit tests**

```python
# core/tests/test_lineup_notes.py
import pytest
from fantaclaude.analysis.weekly.notes import (
    EMPTY_NOTES,
    LineupNote,
    LineupNotesError,
    append_lineup_note,
    load_lineup_notes,
    parse_lineup_notes,
    resolve_notes,
)
from fantaclaude.ingest.names import Candidate

EXAMPLE = """\
- player: Kean               # the listone's spelling, or player_id: 2097
  giornata: 4
  type: p_start
  p_start: 0.0               # 0..1: the probability of a voto, set outright
  reason: out, club statement on Thursday
- player: Bastoni
  giornata: 4
  type: value
  factor: 0.85               # (0, 2]: scales the expected fantavoto if he plays
  reason: carrying a knock, played through it in Europe
- player_id: 2764
  giornata: 3
  type: exclude
  reason: rested against my better judgement last week
"""

CANDIDATES = [Candidate(2764, "Martinez L.", "INT", "Inter"), Candidate(2120, "Bastoni", "INT", "Inter"),
              Candidate(2097, "Kean", "FIO", "Fiorentina"), Candidate(11, "Rossi", "GEN", "Genoa"),
              Candidate(12, "Rossi", "PAR", "Parma")]


def test_the_documented_file_parses_into_three_kinds():
    got = parse_lineup_notes(EXAMPLE)
    assert got == [LineupNote("p_start", 4, "out, club statement on Thursday", player="Kean", p_start=0.0),
                   LineupNote("value", 4, "carrying a knock, played through it in Europe", player="Bastoni", factor=0.85),
                   LineupNote("exclude", 3, "rested against my better judgement last week", player_id=2764)]
    assert [n.describe() for n in got] == ["p_start Kean -> 0.00 for giornata 4 (out, club statement on Thursday)",
                                           "value Bastoni x0.85 for giornata 4 (carrying a knock, played through it in Europe)",
                                           "exclude player_id 2764 for giornata 3 (rested against my better judgement last week)"]
    assert got[0].to_entry() == {"player": "Kean", "giornata": 4, "type": "p_start", "p_start": 0.0,
                                 "reason": "out, club statement on Thursday"}
    assert parse_lineup_notes("") == [] and parse_lineup_notes("# only a comment\n") == []


def test_every_malformed_entry_is_refused_by_name():
    for text, match in (("- {player: X, giornata: 4, type: bench, reason: r}", "type must be one of"),
                        ("- {player: X, type: exclude, reason: r}", "giornata"),
                        ("- {player: X, giornata: 0, type: exclude, reason: r}", "giornata"),
                        ("- {player: X, giornata: 4.5, type: exclude, reason: r}", "giornata"),
                        ("- {player: X, giornata: 4, type: exclude}", "reason"),
                        ("- {player: X, giornata: 4, type: p_start, reason: r}", "p_start must be"),
                        ("- {player: X, giornata: 4, type: p_start, p_start: 1.5, reason: r}", "p_start must be"),
                        ("- {player: X, giornata: 4, type: value, reason: r}", "factor must be"),
                        ("- {player: X, giornata: 4, type: value, factor: 0, reason: r}", "factor must be"),
                        ("- {player: X, giornata: 4, type: exclude, factor: 0.5, reason: r}", "factor belongs"),
                        ("- {player: X, giornata: 4, type: exclude, p_start: 0.5, reason: r}", "p_start belongs"),
                        ("- {player: X, giornata: 4, type: exclude, foo: 1, reason: r}", "unknown key"),
                        ("- {player: X, player_id: 3, giornata: 4, type: exclude, reason: r}", "name the player once"),
                        ("- {giornata: 4, type: exclude, reason: r}", "name the player once"),
                        ("- {player: '', giornata: 4, type: exclude, reason: r}", "spelling"),
                        ("- {player_id: -1, giornata: 4, type: exclude, reason: r}", "player_id"),
                        ("- 5", "must be a mapping"), ("player: X", "top level must be a list"),
                        ("- {player: X, type: [", "lineup-notes.yml")):
        with pytest.raises(LineupNotesError, match=match):
            parse_lineup_notes(text)
    with pytest.raises(LineupNotesError, match="entry 2"):
        parse_lineup_notes("- {player: X, giornata: 4, type: exclude, reason: r}\n- {player: Y, giornata: 4, type: nope, reason: r}\n")


def test_append_keeps_the_text_and_replaces_atomically(tmp_path):
    path = tmp_path / "data" / "lineup-notes.yml"
    assert load_lineup_notes(path) == []
    first = append_lineup_note(path, LineupNote("exclude", 4, "not this week", player="Kean"))
    assert first == [LineupNote("exclude", 4, "not this week", player="Kean")]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# lineup-notes.yml") and "- player: Kean\n  giornata: 4\n  type: exclude\n  reason: not this week\n" in text
    path.write_text(text + "# a hand-written note stays\n", encoding="utf-8")
    second = append_lineup_note(path, LineupNote("p_start", 4, "confirmed", player="Bastoni", p_start=1.0))
    assert len(second) == 2 and "# a hand-written note stays" in path.read_text(encoding="utf-8")
    path.write_text("- {player: X, giornata: 4, type: nope, reason: r}\n", encoding="utf-8")
    with pytest.raises(LineupNotesError, match="type must be one of"):
        append_lineup_note(path, LineupNote("exclude", 4, "r", player="Kean"))      # a broken file is not appended to


def test_resolve_binds_this_giornata_and_leaves_the_others_inert():
    notes = parse_lineup_notes(EXAMPLE) + [LineupNote("p_start", 4, "later word: fit", player="Kean", p_start=0.6),
                                           LineupNote("exclude", 4, "typo", player="Rossi"),
                                           LineupNote("value", 4, "gone", player="Nobody", factor=0.5)]
    layer = resolve_notes(notes, CANDIDATES, giornata=4)
    assert layer.giornata == 4 and layer.inert == 1                                     # the giornata-3 exclusion
    assert layer.p_start == {2097: (0.6, "later word: fit")}                             # the later entry wins
    assert layer.value_factor == {2120: (0.85, "carrying a knock, played through it in Europe")}
    assert layer.excluded == {}
    assert len(layer.problems) == 2
    assert "add the initial the listone uses" in layer.problems[0] and "'Nobody' is not in the listone" in layer.problems[1]
    everything = resolve_notes(notes, CANDIDATES, giornata=None)
    assert everything.inert == 0 and everything.excluded == {2764: "rested against my better judgement last week"}
    assert EMPTY_NOTES.p_start == {} and EMPTY_NOTES.inert == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_lineup_notes.py -c core/pyproject.toml -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the module and the path**

`paths.py`:

```python
def lineup_notes_path() -> Path:
    """data/lineup-notes.yml: my facts for the week -- mine, hand-editable, appended by `lineup note`, every entry with a giornata and a reason."""
    return data_dir() / "lineup-notes.yml"
```

```python
# core/src/fantaclaude/analysis/weekly/notes.py
"""The override file: my facts for the week, applied on top of the page and
never inside it (spec, "The override file").

adjustments.yml's shape and machinery, with three kinds of its own and a
giornata on every entry. `p_start` sets the probability of a voto outright
-- "confirmed in the press conference", "out, club statement", the two
facts the page is slowest to carry. `value` scales the expected fantavoto
if he plays -- playing out of position, carrying a knock. `exclude` keeps
him out of the XI and the bench this week. An entry for another giornata is
inert and stays in the file as the record; a later entry for the same
player, kind and giornata wins; every entry carries a reason, so the
week's record explains itself afterwards. Appending is text-first (a
hand-written comment survives) and atomic; a malformed file is a
LineupNotesError the caller reports; a player nobody resolves to is a
problem the layer names, never a silent no-op.

    - player: Kean               # the listone's spelling, or player_id: 2097
      giornata: 4
      type: p_start
      p_start: 0.0               # 0..1
      reason: out, club statement on Thursday
    - player: Bastoni
      giornata: 4
      type: value
      factor: 0.85               # (0, 2]
      reason: carrying a knock
    - player_id: 2764
      giornata: 4
      type: exclude
      reason: not this week
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.atomic import write_atomic
from fantaclaude.ingest.names import AMBIGUOUS, Candidate, Match, match_listone
from fantaclaude.values import is_number

KINDS = ("p_start", "value", "exclude")
FACTOR_RANGE = (0.0, 2.0)             # exclusive of 0
KEYS = frozenset({"player", "player_id", "giornata", "type", "p_start", "factor", "reason"})
HEADER = "# lineup-notes.yml -- my facts for the week (fantaclaude lineup note); one giornata and one reason per entry\n"


class LineupNotesError(ValueError):
    """lineup-notes.yml is malformed; the message names the entry."""


@dataclass(frozen=True)
class LineupNote:
    kind: str
    giornata: int
    reason: str
    player: str | None = None
    player_id: int | None = None
    p_start: float | None = None
    factor: float | None = None

    def to_entry(self) -> dict[str, Any]:
        """The file's own shape, keys in reading order."""
        entry: dict[str, Any] = {}
        if self.player is not None:
            entry["player"] = self.player
        if self.player_id is not None:
            entry["player_id"] = self.player_id
        entry["giornata"] = self.giornata
        entry["type"] = self.kind
        if self.kind == "p_start":
            entry["p_start"] = self.p_start
        if self.kind == "value":
            entry["factor"] = self.factor
        entry["reason"] = self.reason
        return entry

    def describe(self) -> str:
        who = self.player if self.player is not None else f"player_id {self.player_id}"
        if self.kind == "p_start":
            return f"p_start {who} -> {self.p_start:.2f} for giornata {self.giornata} ({self.reason})"
        if self.kind == "value":
            return f"value {who} x{self.factor:g} for giornata {self.giornata} ({self.reason})"
        return f"exclude {who} for giornata {self.giornata} ({self.reason})"


def note_from_entry(raw: Any, where: str) -> LineupNote:
    """One entry of the file (or of `lineup note`'s flags) validated into a LineupNote; the message names `where`."""
    if not isinstance(raw, dict):
        raise LineupNotesError(f"{where}: must be a mapping, got {raw!r}")
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise LineupNotesError(f"{where}: unknown key(s) {unknown}; known: {sorted(KEYS)}")
    kind = raw.get("type")
    if kind not in KINDS:
        raise LineupNotesError(f"{where}: type must be one of {KINDS}, got {kind!r}")
    giornata = raw.get("giornata")
    if isinstance(giornata, bool) or not isinstance(giornata, int) or giornata < 1:
        raise LineupNotesError(f"{where}: giornata must be the round the note is about (a whole number from 1), got {giornata!r}")
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise LineupNotesError(f"{where}: reason must say why -- the week's record explains itself afterwards")
    player, player_id = raw.get("player"), raw.get("player_id")
    if (player is None) == (player_id is None):
        raise LineupNotesError(f"{where}: name the player once -- `player` (the listone's spelling) or `player_id`")
    if player is not None and (not isinstance(player, str) or not player.strip()):
        raise LineupNotesError(f"{where}: player must be the listone's spelling, got {player!r}")
    if player_id is not None and (isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0):
        raise LineupNotesError(f"{where}: player_id must be the listone id, got {player_id!r}")
    p_start, factor = raw.get("p_start"), raw.get("factor")
    if kind == "p_start":
        if not is_number(p_start) or not 0.0 <= float(p_start) <= 1.0:
            raise LineupNotesError(f"{where}: p_start must be a number in [0, 1] -- the probability of a voto, got {p_start!r}")
        p_start = float(p_start)
    elif p_start is not None:
        raise LineupNotesError(f"{where}: p_start belongs to a p_start note")
    if kind == "value":
        if not is_number(factor) or not FACTOR_RANGE[0] < float(factor) <= FACTOR_RANGE[1]:
            raise LineupNotesError(f"{where}: factor must be a number in (0, {FACTOR_RANGE[1]:g}], got {factor!r}")
        factor = float(factor)
    elif factor is not None:
        raise LineupNotesError(f"{where}: factor belongs to a value note")
    return LineupNote(kind, int(giornata), reason.strip(), player=player.strip() if player else None,
                      player_id=player_id, p_start=p_start, factor=factor)


def parse_lineup_notes(text: str, *, where: str = "lineup-notes.yml") -> list[LineupNote]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LineupNotesError(f"{where}: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, list):
        raise LineupNotesError(f"{where}: the top level must be a list of notes")
    return [note_from_entry(raw, f"{where}: entry {i + 1}") for i, raw in enumerate(data)]


def load_lineup_notes(path: Path) -> list[LineupNote]:
    """The file's entries; no file is no notes."""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LineupNotesError(f"{path}: {exc}") from None
    return parse_lineup_notes(text, where=str(path))


def render_note(note: LineupNote) -> str:
    return yaml.safe_dump([note.to_entry()], sort_keys=False, allow_unicode=True, default_flow_style=False)


def append_lineup_note(path: Path, note: LineupNote) -> list[LineupNote]:
    """Reread, append, replace atomically -- text-first, so a hand-written
    comment survives, and re-parsed before it is written, so a file that is
    already malformed is not appended to (the hand edit that broke it is a
    person's to fix). Single-writer today, like adjustments.yml."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    parse_lineup_notes(existing, where=str(path))
    text = HEADER if not existing.strip() else existing if existing.endswith("\n") else existing + "\n"
    text += render_note(note)
    result = parse_lineup_notes(text, where=str(path))
    write_atomic(path, text.encode("utf-8"))
    return result


@dataclass(frozen=True)
class ResolvedNote:
    note: LineupNote
    player_id: int | None
    detail: str | None = None          # why the entry is inert or a problem, when it is


@dataclass(frozen=True)
class NotesLayer:
    giornata: int | None
    entries: tuple[ResolvedNote, ...]
    p_start: dict[int, tuple[float, str]]        # player_id -> (p_start, reason)
    value_factor: dict[int, tuple[float, str]]   # player_id -> (factor, reason)
    excluded: dict[int, str]                     # player_id -> reason
    problems: tuple[str, ...]
    inert: int                                   # entries for another giornata

    def to_dict(self) -> dict[str, Any]:
        return {"giornata": self.giornata, "count": len(self.entries), "inert": self.inert,
                "p_start": {str(k): v[0] for k, v in sorted(self.p_start.items())},
                "value_factor": {str(k): v[0] for k, v in sorted(self.value_factor.items())},
                "excluded": sorted(self.excluded), "problems": list(self.problems)}


EMPTY_NOTES = NotesLayer(None, (), {}, {}, {}, (), 0)


def _why(name: str, match: Match, candidates: list[Candidate]) -> str:
    named = {c.player_id: c.name for c in candidates}
    close = ", ".join(repr(named[i]) for i in match.candidates if i in named)
    if match.status == AMBIGUOUS:
        return f"{name!r} is {len(match.candidates)} players of the listone ({close}); add the initial the listone uses"
    if match.candidates:
        return f"{name!r} is not how the listone spells {close}; use the listone's spelling"
    return f"{name!r} is not in the listone; write him the listone's way -- surname first, then the initial"


def resolve_notes(notes: list[LineupNote], candidates: list[Candidate], *, giornata: int | None) -> NotesLayer:
    """Bind every entry to the listone. An entry for another giornata is
    inert and counted (`giornata=None` binds them all -- the doctor's
    read); an entry that resolves to nobody is a problem, named, never
    dropped. A later entry for the same player, kind and giornata wins."""
    known = {c.player_id for c in candidates}
    entries: list[ResolvedNote] = []
    p_start: dict[int, tuple[float, str]] = {}
    factors: dict[int, tuple[float, str]] = {}
    excluded: dict[int, str] = {}
    problems: list[str] = []
    inert = 0
    for n in notes:
        if giornata is not None and n.giornata != giornata:
            inert += 1
            entries.append(ResolvedNote(n, None, f"for giornata {n.giornata}, not {giornata}"))
            continue
        if n.player_id is not None:
            pid = n.player_id if n.player_id in known else None
            detail = None if pid is not None else f"player_id {n.player_id} is not in the listone"
        else:
            match = match_listone(n.player, candidates)
            pid = match.player_id
            detail = None if pid is not None else _why(n.player, match, candidates)
        if pid is None:
            problems.append(f"{n.describe()}: {detail}; the note is inert")
        elif n.kind == "p_start":
            p_start[pid] = (float(n.p_start), n.reason)
        elif n.kind == "value":
            factors[pid] = (float(n.factor), n.reason)
        else:
            excluded[pid] = n.reason
        entries.append(ResolvedNote(n, pid, detail))
    return NotesLayer(giornata, tuple(entries), p_start, factors, excluded, tuple(problems), inert)
```

- [ ] **Step 4: Run the unit tests**

Run: `uv run pytest core/tests/test_lineup_notes.py -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 5: Write the failing CLI and doctor tests**

Append to `core/tests/test_lineup_cli.py`:

```python
def test_lineup_note_appends_a_resolved_entry_for_the_target_giornata_and_refuses_the_rest(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    result = runner.invoke(app, ["lineup", "note", "--type", "p_start", "--player", "Kean", "--p-start", "0", "--reason",
                                 "out, club statement", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["player_id"] == 2097 and payload["giornata"] == 3 and payload["count"] == 1 and payload["active"] == 1
    path = tmp_path / "data" / "lineup-notes.yml"
    assert "- player: Kean\n  giornata: 3\n  type: p_start\n  p_start: 0.0\n  reason: out, club statement\n" in path.read_text(encoding="utf-8")
    plain = runner.invoke(app, ["lineup", "note", "--type", "value", "--player-id", "2120", "--factor", "0.85", "--reason", "knock",
                                "--giornata", "4"])
    assert plain.exit_code == ExitCode.OK and "appended to" in plain.stdout and "giornata 4" in plain.stdout
    for args, needle in ((["--type", "exclude", "--player", "Nobody", "--reason", "r"], "not in the listone"),
                         (["--type", "nope", "--player", "Kean", "--reason", "r"], "type must be one of"),
                         (["--type", "p_start", "--player", "Kean", "--reason", "r"], "p_start must be"),
                         (["--type", "exclude", "--player", "Kean", "--reason", "r", "--giornata", "99"], "not in the season"),
                         (["--type", "exclude", "--player", "Kean"], "Missing option '--reason'")):
        bad = runner.invoke(app, ["lineup", "note", *args])
        assert bad.exit_code == ExitCode.USAGE and needle in bad.stderr, (args, bad.output)
    assert path.read_text(encoding="utf-8").count("type:") == 2
    # the group's bare call is still the forecast
    _page(tmp_path)
    forecast = runner.invoke(app, ["lineup", "--json"])
    assert forecast.exit_code == ExitCode.OK and json.loads(forecast.stdout)["predictions"] == 6
```

In `core/tests/test_doctor.py`: insert `"lineup_notes"` after `"adjustments"`
in `NAMES`, add `lineup_notes=root / "data" / "lineup-notes.yml"` to
`_paths`, and add:

```python
def test_lineup_notes_check_parses_and_resolves_against_the_listone(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=NOW)}
    assert checks["lineup_notes"].ok and "none yet" in checks["lineup_notes"].detail
    (tmp_path / "data" / "lineup-notes.yml").write_text(
        "- {player: Kean, giornata: 4, type: exclude, reason: r}\n- {player: Nobody, giornata: 4, type: exclude, reason: r}\n")
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=NOW)}
    assert not checks["lineup_notes"].ok and "Nobody" in checks["lineup_notes"].detail
    (tmp_path / "data" / "lineup-notes.yml").write_text("- {player: Kean, giornata: 4, type: exclude, reason: r}\n")
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=NOW)}
    assert checks["lineup_notes"].ok and "1 note(s)" in checks["lineup_notes"].detail
```

(`NOW` is whatever the module already uses for its `run_doctor` calls; follow the existing tests.)

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest core/tests/test_lineup_cli.py core/tests/test_doctor.py -c core/pyproject.toml -q`
Expected: FAIL — `lineup note` unknown; `lineup_notes` not in the checks.

- [ ] **Step 7: The group, the command, the doctor check**

In `core/src/fantaclaude/cli/app.py`, replace `@app.command("lineup")` with a
group whose callback is the 3a command body:

```python
lineup_app = typer.Typer(name="lineup", invoke_without_command=True,
                         help="The giornata's forecast and the XI (bare call); `note` and `record` beside it. Local, no network.")
app.add_typer(lineup_app)


@lineup_app.callback()
def lineup_cmd(
    ctx: typer.Context,
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = GIORNATA_ONE_OPTION,
    run: str | None = LINEUP_RUN_OPTION,
    late: bool = typer.Option(False, "--late", help="Write even though every match of the giornata has kicked off; every row is marked and calibration excludes them."),
) -> None:
    """Write the giornata's forecast -- p_start x expected fantavoto for every player the probabili page lists -- and, when league.yml names my team, the XI and module that maximise expected points. Local, no network."""
    if ctx.invoked_subcommand is not None:
        return
    ...  # the 3a body, unchanged
```

Add the subcommand after it:

```python
NOTE_TYPE_OPTION = typer.Option(..., "--type", help="p_start | value | exclude.")
NOTE_PLAYER_OPTION = typer.Option(None, "--player", help="The listone's spelling (\"Martinez L.\").")
NOTE_PLAYER_ID_OPTION = typer.Option(None, "--player-id", help="The listone id, instead of --player.")
NOTE_P_START_OPTION = typer.Option(None, "--p-start", help="For p_start: the probability of a voto, 0..1, set outright.")
NOTE_FACTOR_OPTION = typer.Option(None, "--factor", help="For value: a factor on the expected fantavoto if he plays, (0, 2].")
NOTE_REASON_OPTION = typer.Option(..., "--reason", help="Why -- the week's record explains itself afterwards.")


def _render_note(payload: dict) -> str:
    lines = [f"appended to {payload['path']}: {payload['described']} · {payload['count']} note(s), {payload['active']} for "
             f"giornata {payload['giornata']} -- re-run `fantaclaude lineup`"]
    lines += [f"problem: {p}" for p in payload["problems"]]
    return "\n".join(lines)


@lineup_app.command("note")
def lineup_note_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    type_: str = NOTE_TYPE_OPTION,
    player: str | None = NOTE_PLAYER_OPTION,
    player_id: int | None = NOTE_PLAYER_ID_OPTION,
    p_start: float | None = NOTE_P_START_OPTION,
    factor: float | None = NOTE_FACTOR_OPTION,
    reason: str = NOTE_REASON_OPTION,
    giornata: int | None = GIORNATA_ONE_OPTION,
) -> None:
    """Append a fact about this giornata to data/lineup-notes.yml -- a p_start, a value factor or an exclusion, with its reason. Resolved against the listone; refused when nobody matches. Local, no network."""
    from fantaclaude.analysis.weekly import ForecastError, target_round
    from fantaclaude.analysis.weekly.notes import (
        LineupNotesError,
        append_lineup_note,
        note_from_entry,
        resolve_notes,
    )
    from fantaclaude.db.connection import connect
    from fantaclaude.ingest.names import load_candidates
    from fantaclaude.paths import lineup_notes_path
    from fantaclaude.timeutil import utc_now

    season_id = _seasons_or_exit(None)[-1]
    con = connect(read_only=True)
    try:
        try:
            round_ = target_round(con, utc_now(), season_id=season_id, giornata=giornata)
        except ForecastError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.USAGE if giornata is not None else ExitCode.NOT_READY) from None
        candidates = load_candidates(con)
    finally:
        con.close()
    raw = {k: v for k, v in (("player", player), ("player_id", player_id), ("giornata", round_.giornata), ("type", type_),
                             ("p_start", p_start), ("factor", factor), ("reason", reason)) if v is not None}
    try:
        note = note_from_entry(raw, "lineup note")
    except LineupNotesError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.USAGE) from None
    probe = resolve_notes([note], candidates, giornata=round_.giornata)
    if probe.problems:
        typer.echo(probe.problems[0], err=True)
        raise typer.Exit(code=ExitCode.USAGE)
    path = lineup_notes_path()
    try:
        notes = append_lineup_note(path, note)
    except LineupNotesError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    layer = resolve_notes(notes, candidates, giornata=round_.giornata)
    payload = {"note": note.to_entry(), "described": note.describe(), "player_id": probe.entries[0].player_id,
               "giornata": round_.giornata, "path": str(path), "count": len(notes),
               "active": len(layer.entries) - layer.inert - len(layer.problems), "problems": list(layer.problems)}
    emit(payload, json_=json_, render=_render_note)
```

Pass `lineup_notes=lineup_notes_path()` in the doctor command's
`DoctorPaths(...)` (import it beside `adjustments_path`).

In `core/src/fantaclaude/commands/doctor.py`: add `lineup_notes: Path` to
`DoctorPaths` after `adjustments`; import
`from fantaclaude.analysis.weekly.notes import LineupNotesError, load_lineup_notes, resolve_notes as resolve_lineup_notes`;
add the check and call it right after `_adjustments_check` in `run_doctor`:

```python
def _lineup_notes_check(path: Path, con: duckdb.DuckDBPyConnection | None, skip: str) -> Check:
    """Does data/lineup-notes.yml parse, and does every entry resolve against the listone -- every giornata's, since the doctor is not a forecast."""
    if not path.is_file():
        return Check("lineup_notes", True, f"none yet ({path} does not exist)")
    try:
        notes = load_lineup_notes(path)
    except LineupNotesError as exc:
        return Check("lineup_notes", False, str(exc))
    head = f"{len(notes)} note(s)"
    if con is None:
        return Check("lineup_notes", True, f"{head}, parse; {skip} -- not resolved against the listone")
    try:
        candidates = load_candidates(con)
    except duckdb.Error as exc:
        return Check("lineup_notes", True, f"{head}, parse; skipped: {exc}")
    layer = resolve_lineup_notes(notes, candidates, giornata=None)
    if layer.problems:
        return Check("lineup_notes", False, f"{head}, {len(layer.problems)} inert: " + "; ".join(layer.problems))
    kinds = {kind: sum(1 for e in layer.entries if e.note.kind == kind) for kind in ("p_start", "value", "exclude")}
    return Check("lineup_notes", True, f"{head} resolved against the listone: " + ", ".join(f"{n} {kind}" for kind, n in kinds.items() if n))
```

```python
        checks.append(_adjustments_check(paths.adjustments, con, run, skip))
        checks.append(_lineup_notes_check(paths.lineup_notes, con, skip))
```

- [ ] **Step 8: Run the tests, the suite and lint; commit**

```bash
uv run pytest core/tests/test_lineup_notes.py core/tests/test_lineup_cli.py core/tests/test_doctor.py -c core/pyproject.toml -q
uv run poe test && uv run poe lint
git add core/src/fantaclaude/analysis/weekly/notes.py core/src/fantaclaude/paths.py core/src/fantaclaude/cli/app.py core/src/fantaclaude/commands/doctor.py core/tests/test_lineup_notes.py core/tests/test_lineup_cli.py core/tests/test_doctor.py
git commit -m "feat(lineup): lineup-notes.yml and \`lineup note\` -- a p_start, a value factor or an exclusion per giornata, with a reason; \`lineup\` becomes a group"
```

---

### Task 7: The blend — precedence, the three checks, `WeeklyConfig` and `weekly_hash`

**Files:**
- Create: `core/src/fantaclaude/analysis/weekly/config.py`
- Create: `core/src/fantaclaude/analysis/weekly/blend.py`
- Modify: `core/src/fantaclaude/analysis/weekly/forecast.py` (`ForecastRow.trace/excluded`, `forecast()` returns `Forecast`)
- Modify: `core/src/fantaclaude/analysis/weekly/records.py` (`trace`, `weekly_hash`)
- Modify: `core/src/fantaclaude/analysis/weekly/report.py` (`load_layer`, the summary, `notes_path`/`kb_dir`/`cfg`)
- Modify: `core/src/fantaclaude/analysis/weekly/__init__.py`, `core/src/fantaclaude/cli/app.py`
- Create: `core/tests/test_weekly_blend.py`
- Modify: `core/tests/test_lineup_cli.py`

**Interfaces:**
- Consumes: `notes.{NotesLayer, EMPTY_NOTES, load_lineup_notes, resolve_notes, LineupNotesError}`, `kb.notes.{PlayerNote, load_player_notes, NoteError}`, `kb.profiles.{load_profiles, ProfileError}`, `v_unavailable_current`, `v_news_files_current`, `v_european_ties`, `valuation_runs.summary`.
- Produces: `WEEKLY_VERSION`, `WeeklyConfig` (frozen dataclass, every constant of the layer), `weekly_hash(cfg) -> str`; `BlendLayer`, `EMPTY_BLEND`, `load_layer(con, *, season_id, giornata, run_id, notes_path, kb_dir, cfg) -> tuple[BlendLayer, list[str]]`, `Blended(p_start, source, value_factor, excluded, trace, warnings)`, `blend(*, player_id, name, team_short, published, exp_presenze, kickoff, layer, cfg) -> Blended`, `SOURCE_PUBLISHED/SOURCE_NOTE/SOURCE_SQUALIFICATO`; `ForecastRow.trace: dict`, `ForecastRow.excluded: bool`; `forecast(...) -> Forecast(rows: list[ForecastRow], warnings: list[str])`; `write_lineup_run(..., weekly_hash: str | None = None)` writing `trace`; `lineup(..., notes_path=None, kb_dir=None, cfg=None)`; payload keys `weekly_hash`, `blend`.

- [ ] **Step 1: Write the failing unit tests**

```python
# core/tests/test_weekly_blend.py
from datetime import datetime, timedelta
from pathlib import Path

from conftest import seed_news
from fantaclaude.analysis.weekly.blend import (
    SOURCE_NOTE,
    SOURCE_PUBLISHED,
    SOURCE_SQUALIFICATO,
    BlendLayer,
    blend,
    load_layer,
)
from fantaclaude.analysis.weekly.config import WEEKLY_VERSION, WeeklyConfig, weekly_hash
from fantaclaude.analysis.weekly.notes import NotesLayer
from fantaclaude.kb.audit import FrontMatter
from fantaclaude.kb.notes import PlayerNote

CFG = WeeklyConfig()
KICKOFF = datetime(2026, 9, 13, 16, 0)


def _notes(**kw):
    return NotesLayer(4, (), kw.get("p_start", {}), kw.get("value_factor", {}), kw.get("excluded", {}), (), 0)


def _kb(player_id, *, depth=None, availability=1.0):
    return PlayerNote(Path("x.md"), player_id, "X", "INT", depth, availability, None,
                      FrontMatter(None, None, None, None, {}))


def _blend(layer, *, published=90, team="INT", exp_presenze=30.0, kickoff=KICKOFF):
    return blend(player_id=2764, name="Martinez L.", team_short=team, published=published, exp_presenze=exp_presenze,
                 kickoff=kickoff, layer=layer, cfg=CFG)


def test_the_page_is_the_base_and_the_trace_says_so():
    got = _blend(BlendLayer(4))
    assert (got.p_start, got.source, got.value_factor, got.excluded, got.warnings) == (0.9, SOURCE_PUBLISHED, 1.0, False, ())
    assert got.trace["published"] == 90 and got.trace["source"] == SOURCE_PUBLISHED and got.trace["checks"] == []


def test_a_squalifica_forces_zero_and_a_note_beats_it():
    layer = BlendLayer(4, squalificati={2764: "una giornata"})
    got = _blend(layer)
    assert (got.p_start, got.source) == (0.0, SOURCE_SQUALIFICATO) and got.trace["squalificato"] == "una giornata"
    overruled = _blend(BlendLayer(4, notes=_notes(p_start={2764: (0.5, "appeal accepted")}), squalificati={2764: "una giornata"}))
    assert (overruled.p_start, overruled.source) == (0.5, SOURCE_NOTE)
    assert overruled.trace["note"] == {"type": "p_start", "p_start": 0.5, "reason": "appeal accepted"}
    assert overruled.trace["squalificato"] == "una giornata"                     # carried, so the record says what was overruled


def test_a_value_note_and_an_exclusion_ride_in_the_trace_without_touching_p_start():
    got = _blend(BlendLayer(4, notes=_notes(value_factor={2764: (0.85, "knock")}, excluded={2764: "not this week"})))
    assert got.p_start == 0.9 and got.value_factor == 0.85 and got.excluded
    assert got.trace["value_factor"] == 0.85 and got.trace["value_note"] == "knock" and got.trace["excluded"] == "not this week"


def test_an_infortunato_the_page_still_prices_is_a_warning_and_the_number_survives():
    got = _blend(BlendLayer(4, infortunati={2764: "lesione al polpaccio, rientro a ottobre"}), published=55)
    assert got.p_start == 0.55 and got.source == SOURCE_PUBLISHED
    assert got.trace["checks"] == ["infortunato"] and "disagreement" in got.warnings[0] and "55%" in got.warnings[0]
    quiet = _blend(BlendLayer(4, infortunati={2764: "lesione"}), published=5)
    assert quiet.warnings == () and quiet.trace["infortunato"] == "lesione"          # below the threshold: carried, not argued


def test_a_kb_note_is_a_check_never_a_multiplier():
    out = _blend(BlendLayer(4, kb_notes={2764: _kb(2764, depth="out")}))
    assert out.p_start == 0.9 and out.trace["checks"] == ["kb_depth_out"] and "depth 'out'" in out.warnings[0]
    thin = _blend(BlendLayer(4, kb_notes={2764: _kb(2764, availability=0.6)}))
    assert thin.p_start == 0.9 and thin.trace["checks"] == ["kb_availability"] and "0.60" in thin.warnings[0]
    fine = _blend(BlendLayer(4, kb_notes={2764: _kb(2764, availability=0.8)}))
    assert fine.warnings == () and fine.p_start == 0.9


def test_a_european_tie_within_the_window_is_a_disagreement_not_a_fade():
    ties = (KICKOFF - timedelta(days=3), KICKOFF + timedelta(days=10))
    layer = BlendLayer(4, rotation={"INT": 0.7}, european={"INT": ties}, giornate_remaining=30)
    got = _blend(layer, published=90, exp_presenze=27.0)                            # season rate 0.9 x 0.7 = 0.63 vs 0.90
    assert got.p_start == 0.9 and got.trace["checks"] == ["european"] and "63%" in got.warnings[0]
    no_window = _blend(BlendLayer(4, rotation={"INT": 0.7}, european={"INT": (KICKOFF + timedelta(days=10),)},
                                  giornate_remaining=30), exp_presenze=27.0)
    assert no_window.warnings == ()
    not_rotating = _blend(BlendLayer(4, european={"INT": ties}, giornate_remaining=30), exp_presenze=27.0)
    assert not_rotating.warnings == ()
    low_published = _blend(layer, published=50, exp_presenze=27.0)
    assert low_published.warnings == ()


def test_checks_are_silent_once_a_note_or_a_squalifica_set_the_number():
    layer = BlendLayer(4, notes=_notes(p_start={2764: (1.0, "confirmed")}), infortunati={2764: "x"},
                       kb_notes={2764: _kb(2764, depth="out")})
    got = _blend(layer)
    assert got.warnings == () and got.trace["checks"] == [] and got.p_start == 1.0


def test_weekly_hash_moves_with_a_constant_and_not_otherwise():
    assert WEEKLY_VERSION == 1 and len(weekly_hash()) == 16 and weekly_hash() == weekly_hash(WeeklyConfig())
    assert weekly_hash(WeeklyConfig(european_gap=0.25)) != weekly_hash()


def test_load_layer_reads_the_news_the_notes_and_the_kb(db, tmp_path, fixture_json):
    import json
    from datetime import UTC

    from fantaclaude.ingest.listone_api import load_listone, record_listone
    from fantaclaude.ingest.raw import RawFile
    path = tmp_path / "listone.json"
    path.write_text(json.dumps(fixture_json("listone_sample")), encoding="utf-8")
    record_listone(db, load_listone(path), RawFile(path, "sha-l", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    seed_news(db, 21, 4, "squalificati", [("squalificato", "Inter", "INT", "Martinez L.", 2764, "una giornata"),
                                          ("diffidato", "Inter", "INT", "Bastoni", 2120, "4 ammonizioni"),
                                          ("squalificato", "Bologna", None, "Orsolini", None, "due giornate")])
    seed_news(db, 21, 4, "infortunati", [("infortunato", "Roma", "ROM", "Dybala", 309, "affaticamento")])
    db.execute("INSERT INTO valuation_runs VALUES ('r', now(), 'h', 'm', 'i', 1, 1, 21, 3, ['balanced'], '{}'::JSON, ?::JSON)",
               [json.dumps({"giornate_remaining": 35})])
    notes = tmp_path / "lineup-notes.yml"
    notes.write_text("- {player: Kean, giornata: 4, type: exclude, reason: r}\n- {player: Kean, giornata: 5, type: exclude, reason: later}\n"
                     "- {player: Nobody, giornata: 4, type: exclude, reason: r}\n", encoding="utf-8")
    layer, warnings = load_layer(db, season_id=21, giornata=4, run_id="r", notes_path=notes, kb_dir=None, cfg=CFG)
    assert layer.squalificati == {2764: "una giornata"} and layer.diffidati == {2120: "4 ammonizioni"} and layer.infortunati == {309: "affaticamento"}
    assert layer.unmatched_news == 1 and set(layer.news_fetched) == {"squalificati", "infortunati"}
    assert layer.notes.excluded == {2097: "r"} and layer.notes.inert == 1 and layer.giornate_remaining == 35
    assert len(warnings) == 2                                                    # the inert note, and the unmatched Orsolini
    assert any("Nobody" in w for w in warnings) and any("matched nobody" in w for w in warnings)
    empty, warned = load_layer(db, season_id=21, giornata=5, run_id="r", notes_path=None, kb_dir=None, cfg=CFG)
    assert empty.squalificati == {} and any("ingest news" in w for w in warned)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_weekly_blend.py -c core/pyproject.toml -q`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write `config.py`**

```python
# core/src/fantaclaude/analysis/weekly/config.py
"""The weekly layer's own version and constants, hashed beside the run's
model_hash (spec, "Two hashes here too"). Every threshold the blend, the
checks, the bench, the matchup term and the spread read lives here, so a
change to any of them is a new weekly model that calibration can split on,
and the run's hash does not pretend it changed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

WEEKLY_VERSION = 1


@dataclass(frozen=True)
class WeeklyConfig:
    # the blend's checks (Task 7)
    injured_page_threshold: int = 10       # an infortunato the page still prices at or above this % is a disagreement
    kb_depth_out_threshold: int = 10       # a KB `depth: out` under a page at or above this % is a disagreement
    kb_availability_gap: float = 0.3       # published/100 minus the KB availability at or above this is a disagreement
    european_window_days: int = 3          # a tie within this many days of the fixture makes it a European week
    european_gap: float = 0.2              # published/100 minus rate x rotation_factor at or above this is a disagreement
    european_min_published: int = 60       # below this % the site is already fading him; nothing to argue
    # the XI's outputs (Task 8)
    contingency_threshold: float = 0.75    # a starter below this p_start gets a re-solve without him
    close_call_margin: float = 0.5         # a slot whose best excluded fit is within this many points is a close call
    close_calls_max: int = 3
    # the forecast terms (Task 9)
    matchup_shrink_k: float = 60.0         # rows at which a matchup delta counts half
    matchup_cap: float = 0.5               # the most the matchup term may move fv_if_plays, either way
    spread_prior_k: float = 10.0           # rated matches at which a player's own dispersion counts half against the role prior
    spread_back_seasons: int = 3

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def weekly_hash(cfg: WeeklyConfig = WeeklyConfig()) -> str:
    """Sixteen hex characters over the version and every constant, sorted."""
    payload = json.dumps({"version": WEEKLY_VERSION, **cfg.to_dict()}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Write `blend.py`**

```python
# core/src/fantaclaude/analysis/weekly/blend.py
"""p_start by precedence, and the checks that never touch it (spec,
"Blending, and the rotation term that must not double-count").

A lineup-notes.yml entry for this giornata sets the number (source: note);
otherwise a squalifica in the current news file forces zero (source:
squalificato); otherwise the published number stands (source: published).
Every other source is a check: an infortunato the page still prices, a KB
note whose depth or availability disagrees with the page, a European tie
within the window at a rotating club -- each a named warning, none a term,
because the site's compilers already know what those sources know and
stacking fades a player twice. A diffida is carried into the trace and
named on the bench and contingency lines, because it prices next week.
Checks are silent once a note or a squalifica set the number: the
disagreement has been adjudicated.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.config import WeeklyConfig
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.notes import (
    EMPTY_NOTES,
    LineupNotesError,
    NotesLayer,
    load_lineup_notes,
    resolve_notes,
)
from fantaclaude.ingest.names import load_candidates
from fantaclaude.kb.notes import NoteError, PlayerNote, load_player_notes
from fantaclaude.kb.profiles import ProfileError, load_profiles

SOURCE_PUBLISHED = "published"
SOURCE_NOTE = "note"
SOURCE_SQUALIFICATO = "squalificato"


@dataclass(frozen=True)
class BlendLayer:
    giornata: int
    notes: NotesLayer = EMPTY_NOTES
    squalificati: dict[int, str] = field(default_factory=dict)          # player_id -> the page's words
    infortunati: dict[int, str] = field(default_factory=dict)
    diffidati: dict[int, str] = field(default_factory=dict)
    kb_notes: dict[int, PlayerNote] = field(default_factory=dict)
    rotation: dict[str, float] = field(default_factory=dict)            # team_short -> rotation_factor, below 1.0 only
    european: dict[str, tuple[datetime, ...]] = field(default_factory=dict)   # team_short -> tie kickoffs, naive UTC
    giornate_remaining: int | None = None                               # of the run, for the season rate
    news_fetched: dict[str, str] = field(default_factory=dict)          # page -> fetched_at, for the report
    unmatched_news: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"giornata": self.giornata, "notes": self.notes.to_dict(), "squalificati": len(self.squalificati),
                "infortunati": len(self.infortunati), "diffidati": len(self.diffidati), "kb_notes": len(self.kb_notes),
                "rotating_clubs": sorted(self.rotation), "news_fetched": dict(self.news_fetched),
                "unmatched_news": self.unmatched_news, "giornate_remaining": self.giornate_remaining}


EMPTY_BLEND = BlendLayer(0)


def load_layer(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int, run_id: str,
               notes_path: Path | None, kb_dir: Path | None, cfg: WeeklyConfig) -> tuple[BlendLayer, list[str]]:
    """Everything the blend reads besides the page, and the notices about
    what could not be read. A malformed notes file refuses the forecast (it
    would corrupt this week's answer); a malformed KB document skips its
    check with a notice (it only makes the answer poorer)."""
    warnings: list[str] = []
    notes = EMPTY_NOTES
    if notes_path is not None:
        try:
            notes = resolve_notes(load_lineup_notes(notes_path), load_candidates(con), giornata=giornata)
        except LineupNotesError as exc:
            raise ForecastError(f"{exc} -- fix the file; a forecast under a malformed override file is not a forecast") from None
        warnings += list(notes.problems)
    listed = con.execute("SELECT kind, player_id, coalesce(detail, '') FROM v_unavailable_current "
                         "WHERE season_id = ? AND giornata = ? ORDER BY file_id, position", [season_id, giornata]).fetchall()
    by_kind: dict[str, dict[int, str]] = defaultdict(dict)
    for kind, pid, detail in listed:
        if pid is not None:
            by_kind[str(kind)][int(pid)] = str(detail)
    unmatched = sum(1 for _, pid, _ in listed if pid is None)
    fetched = {str(kind): stamp.isoformat(sep=" ", timespec="minutes") for kind, stamp in con.execute(
        "SELECT kind, fetched_at FROM v_news_files_current WHERE season_id = ? AND giornata = ?", [season_id, giornata]).fetchall()}
    if not fetched:
        warnings.append(f"no news pages for giornata {giornata} -- run `fantaclaude ingest news`; no squalifica can force a zero")
    if unmatched:
        warnings.append(f"{unmatched} news entr{'y' if unmatched == 1 else 'ies'} for giornata {giornata} matched nobody in the "
                        f"listone -- `fantaclaude query --sql \"SELECT * FROM v_unavailable_current WHERE player_id IS NULL\"`")
    kb_notes: dict[int, PlayerNote] = {}
    rotation: dict[str, float] = {}
    if kb_dir is not None:
        try:
            kb_notes = load_player_notes(kb_dir)
        except NoteError as exc:
            warnings.append(f"KB notes not read, their check skipped: {exc}")
        try:
            rotation = {p.team_short: p.rotation_factor for p in load_profiles(kb_dir) if p.rotation_factor < 1.0}
        except ProfileError as exc:
            warnings.append(f"KB profiles not read, the European check skipped: {exc}")
    european: dict[str, list[datetime]] = defaultdict(list)
    for short, kickoff in con.execute("SELECT team_short, kickoff FROM v_european_ties WHERE season_id = ? AND kickoff IS NOT NULL",
                                      [season_id]).fetchall():
        european[str(short)].append(kickoff)
    summary = con.execute("SELECT summary FROM valuation_runs WHERE run_id = ?", [run_id]).fetchone()
    remaining = None
    if summary is not None:
        parsed = summary[0] if isinstance(summary[0], dict) else json.loads(summary[0])
        remaining = parsed.get("giornate_remaining")
    return BlendLayer(giornata, notes, dict(by_kind.get("squalificato", {})), dict(by_kind.get("infortunato", {})),
                      dict(by_kind.get("diffidato", {})), kb_notes, rotation,
                      {k: tuple(sorted(v)) for k, v in european.items()},
                      None if remaining is None else int(remaining), fetched, unmatched), warnings


@dataclass(frozen=True)
class Blended:
    p_start: float
    source: str
    value_factor: float
    excluded: bool
    trace: dict[str, Any]
    warnings: tuple[str, ...]


def blend(*, player_id: int, name: str, team_short: str | None, published: int, exp_presenze: float | None,
          kickoff: datetime | None, layer: BlendLayer, cfg: WeeklyConfig) -> Blended:
    label = f"{name} ({team_short or '?'})"
    warnings: list[str] = []
    trace: dict[str, Any] = {"published": published, "source": SOURCE_PUBLISHED, "note": None, "squalificato": None,
                             "infortunato": None, "diffidato": None, "value_factor": 1.0, "checks": []}
    p_start, source = published / 100.0, SOURCE_PUBLISHED
    note = layer.notes.p_start.get(player_id)
    if note is not None:
        p_start, source = note[0], SOURCE_NOTE
        trace["note"] = {"type": "p_start", "p_start": note[0], "reason": note[1]}
    elif player_id in layer.squalificati:
        p_start, source = 0.0, SOURCE_SQUALIFICATO
    if player_id in layer.squalificati:
        trace["squalificato"] = layer.squalificati[player_id]
    trace["source"] = source
    factor = layer.notes.value_factor.get(player_id)
    if factor is not None:
        trace["value_factor"], trace["value_note"] = factor
    excluded = player_id in layer.notes.excluded
    if excluded:
        trace["excluded"] = layer.notes.excluded[player_id]
    # From here on the number is never touched: everything below is a check.
    if player_id in layer.infortunati:
        detail = layer.infortunati[player_id]
        trace["infortunato"] = detail
        if source == SOURCE_PUBLISHED and published >= cfg.injured_page_threshold:
            trace["checks"].append("infortunato")
            warnings.append(f"disagreement: {label} is listed infortunato ({detail[:70]}) but the page has him at {published}%")
    if player_id in layer.diffidati:
        trace["diffidato"] = layer.diffidati[player_id]
    kb = layer.kb_notes.get(player_id)
    if kb is not None and source == SOURCE_PUBLISHED:
        if kb.depth == "out" and published >= cfg.kb_depth_out_threshold:
            trace["checks"].append("kb_depth_out")
            warnings.append(f"disagreement: {label} has depth 'out' in the KB note ({kb.path.name}) but the page has him at {published}%")
        elif published / 100.0 - kb.availability >= cfg.kb_availability_gap:
            trace["checks"].append("kb_availability")
            warnings.append(f"disagreement: {label} has availability {kb.availability:.2f} in the KB note ({kb.path.name}) "
                            f"but the page has him at {published}%")
    if (team_short in layer.rotation and kickoff is not None and source == SOURCE_PUBLISHED
            and published >= cfg.european_min_published and exp_presenze is not None and layer.giornate_remaining):
        window = timedelta(days=cfg.european_window_days)
        ties = [t for t in layer.european.get(team_short, ()) if abs(t - kickoff) <= window]
        if ties:
            rate = min(1.0, exp_presenze / layer.giornate_remaining)
            model_p = rate * layer.rotation[team_short]
            trace["european"] = {"tie": ties[0].isoformat(sep=" ", timespec="minutes"), "rate": round(rate, 3),
                                 "rotation_factor": layer.rotation[team_short], "model_p": round(model_p, 3)}
            if published / 100.0 - model_p >= cfg.european_gap:
                trace["checks"].append("european")
                warnings.append(f"disagreement: {label} at {published}% with a European tie on {ties[0]:%a %d %b}; the season rate "
                                f"under rotation {layer.rotation[team_short]:.2f} expects {model_p:.0%} -- adjudicate, never fade twice")
    return Blended(p_start, source, factor[0] if factor is not None else 1.0, excluded, trace, tuple(warnings))
```

- [ ] **Step 5: Thread the blend through the forecast, the write and the report**

`forecast.py` — `ForecastRow` gains `trace: dict[str, Any] = field(default_factory=dict)`
and `excluded: bool = False` after `kickoff` (import `field`); `to_dict`
emits both. `forecast` returns a `Forecast`:

```python
@dataclass(frozen=True)
class Forecast:
    rows: list[ForecastRow]
    warnings: list[str]


def forecast(con: duckdb.DuckDBPyConnection, *, run_id: str, probabili_file_id: int,
             fixtures: dict[int, PlayerFixture] | None = None, layer: BlendLayer = EMPTY_BLEND,
             cfg: WeeklyConfig = WeeklyConfig()) -> Forecast:
    """Every player the page lists and the run prices, blended by precedence
    (blend.py); fv_sd is null until Task 9."""
    fixtures = fixtures or {}
    rows = con.execute(
        "SELECT v.player_id, v.name, v.team_short, v.classic_role, v.roles, v.exp_fantamedia, v.exp_presenze, p.p_start "
        "FROM valuations v JOIN probabili p ON p.player_id = v.player_id "
        "WHERE v.run_id = ? AND p.file_id = ? ORDER BY v.player_id", [run_id, probabili_file_id]).fetchall()
    out: list[ForecastRow] = []
    warnings: list[str] = []
    for pid, name, short, role, roles, fm, presenze, published in rows:
        fixture = fixtures.get(int(pid))
        kickoff = None if fixture is None else fixture.kickoff
        b = blend(player_id=int(pid), name=str(name), team_short=short, published=int(published),
                  exp_presenze=float(presenze), kickoff=kickoff, layer=layer, cfg=cfg)
        fv_if_plays = float(fm) * b.value_factor
        b.trace["kickoff"] = None if kickoff is None else kickoff.isoformat(sep=" ", timespec="minutes")
        b.trace["deadline"] = "player" if kickoff is not None else "round"
        out.append(ForecastRow(int(pid), str(name), short, str(role), tuple(roles), int(published), b.p_start,
                               fv_if_plays, None, b.p_start * fv_if_plays, b.source, kickoff=kickoff,
                               trace=b.trace, excluded=b.excluded))
        warnings += list(b.warnings)
    return Forecast(out, warnings)
```

(`from fantaclaude.analysis.weekly.blend import EMPTY_BLEND, BlendLayer, blend` and
`from fantaclaude.analysis.weekly.config import WeeklyConfig` at the top; the
`blend` module imports nothing from `forecast`, so there is no cycle.)

`records.py` — `write_lineup_run` gains `weekly_hash: str | None = None`,
writes it into `lineup_runs` (`..., predictions, weekly_hash) VALUES (..., ?, ?)`)
and writes each row's trace:

```python
            "fv_if_plays, fv_sd, expected_points, source, kickoff, late, trace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[..., written_at >= (r.kickoff or round_.first_kickoff), json.dumps(r.trace, ensure_ascii=False)] for r in rows])
```

`report.py` — `lineup()` takes `notes_path: Path | None = None, kb_dir: Path | None = None, cfg: WeeklyConfig | None = None`;
after the run is known and before the forecast:

```python
    cfg = cfg or WeeklyConfig()
    layer, layer_warnings = load_layer(con, season_id=season_id, giornata=round_.giornata, run_id=run_id,
                                       notes_path=notes_path, kb_dir=kb_dir, cfg=cfg)
    fixtures = player_fixtures(con, file_id)
    forecasted = forecast(con, run_id=run_id, probabili_file_id=file_id, fixtures=fixtures, layer=layer, cfg=cfg)
    rows = forecasted.rows
    warnings: list[str] = [*layer_warnings, *forecasted.warnings]
```

`choose_xi(..., excluded=frozenset(r.player_id for r in rows if r.excluded))` (the
parameter lands in `xi.py` here — add `excluded: frozenset[int] = frozenset()`
to `choose_xi` and filter `roster = [p for p in roster if p.player_id not in excluded]`
at its top, before the solve). The write passes `weekly_hash=weekly_hash(cfg)`.
`LineupReport` gains `weekly_hash: str` and `blend: dict[str, Any]`, emitted as
`"weekly_hash"` and `"blend"`, where `blend` is
`{**layer.to_dict(), "sources": {s: n for each source in rows}, "disagreements": sum(1 for w in warnings if w.startswith("disagreement:"))}`.

`cli/app.py` — the group callback passes `notes_path=lineup_notes_path(), kb_dir=kb_dir()`
to `lineup(...)`, and `_render_lineup` prints, right after the header line:

```python
    b = payload.get("blend") or {}
    if b:
        sources = " · ".join(f"{k} {v}" for k, v in b.get("sources", {}).items())
        fetched = ", ".join(f"{k} {v}" for k, v in b.get("news_fetched", {}).items()) or "none"
        lines.append(f"blend: {sources} · notes {b['notes']['count'] - b['notes']['inert']} active · news {fetched} · "
                     f"weekly {payload['weekly_hash']}")
```

- [ ] **Step 6: Write the failing CLI test and run everything**

Append to `core/tests/test_lineup_cli.py`:

```python
def test_lineup_blends_by_precedence_and_writes_the_trace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    _page(tmp_path)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_news(con, 21, 3, "squalificati", [("squalificato", "Inter", "INT", "Martinez L.", 2764, "una giornata"),
                                          ("squalificato", "Inter", "INT", "Bastoni", 2120, "una giornata")])
    seed_news(con, 21, 3, "infortunati", [("infortunato", "Inter", "INT", "Dimarco", 254, "affaticamento")])
    con.close()
    (tmp_path / "data" / "lineup-notes.yml").write_text("- {player: Bastoni, giornata: 3, type: p_start, p_start: 0.5, reason: appeal}\n"
                                                        "- {player: Svilar, giornata: 3, type: value, factor: 0.5, reason: knock}\n", encoding="utf-8")
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["blend"]["sources"] == {"published": 4, "note": 1, "squalificato": 1}
    assert len(payload["weekly_hash"]) == 16 and payload["blend"]["disagreements"] == 1
    assert any("Dimarco" in w and "disagreement" in w for w in payload["warnings"])
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    rows = {pid: (p, src, json.loads(trace)) for pid, p, src, trace in con.execute(
        "SELECT player_id, p_start, source, trace FROM predictions").fetchall()}
    assert rows[2764][:2] == (0.0, "squalificato") and rows[2120][:2] == (0.5, "note")
    assert rows[254][1] == "published" and rows[254][2]["checks"] == ["infortunato"]
    assert rows[5841][2]["value_factor"] == 0.5
    assert con.execute("SELECT weekly_hash FROM lineup_runs").fetchone()[0] == payload["weekly_hash"]
    con.close()
    plain = runner.invoke(app, ["lineup"])
    assert "blend: " in plain.stdout and "warning: disagreement: Dimarco" in plain.stdout
```

Import `seed_news` from `conftest` in that file.

```bash
uv run pytest core/tests/test_weekly_blend.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q
uv run poe test && uv run poe lint
git add core/src/fantaclaude/analysis/weekly core/src/fantaclaude/cli/app.py core/tests/test_weekly_blend.py core/tests/test_lineup_cli.py
git commit -m "feat(weekly): the blend -- a note, else a squalifica, else the page; infortunati, the KB and European weeks as named checks; weekly_hash"
```

---

### Task 8: The ordered bench, the contingencies, the close calls

**Files:**
- Modify: `core/src/fantaclaude/analysis/weekly/xi.py`
- Modify: `core/src/fantaclaude/analysis/weekly/records.py` (three JSON columns)
- Modify: `core/src/fantaclaude/analysis/weekly/report.py`, `__init__.py`
- Modify: `core/src/fantaclaude/cli/app.py` (`_render_lineup`)
- Create: `core/tests/test_weekly_xi.py`
- Modify: `core/tests/test_lineup_cli.py`

**Interfaces:**
- Consumes: `XiChoice`, `RosterPlayer`, `ForecastRow` (with `trace["diffidato"]`), `Module.slots[k].fit`, `ADAPTED_MALUS`, `WeeklyConfig.{contingency_threshold, close_call_margin, close_calls_max}`, `v_league_settings_current.bench_size`.
- Produces: `BenchEntry(player_id, name, roles, expected_points, coverage, covers, diffidato)`, `Bench(order: list[BenchEntry], uncovered: tuple[str, ...], size: int)`, `order_bench(roster, xi, forecast_by_id, module, *, bench_size, excluded=frozenset()) -> Bench`; `Contingency(player_id, name, p_start, module, module_changes, enters, leaves, points_lost, note)`, `contingencies(roster, forecast_by_id, modules, allowed, xi, *, threshold, excluded=frozenset()) -> list[Contingency]`; `CloseCall(slot, player_in, player_out, gap)`, `close_calls(roster, xi, forecast_by_id, module, *, margin, limit, excluded=frozenset()) -> list[CloseCall]`; `write_lineup_run(..., bench=None, contingencies=None, close_calls=None)`; payload keys `bench`, `contingencies`, `close_calls`.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/test_weekly_xi.py
import itertools
import random

import pytest
from fantaclaude.analysis.weekly import ADAPTED_MALUS, ForecastError, ForecastRow, RosterPlayer, choose_xi
from fantaclaude.analysis.weekly.xi import close_calls, contingencies, order_bench
from fantaclaude.model.modules import Fit, Module, Slot, load_modules
from fantaclaude.model.roles import Role

R = frozenset
SMALL = Module(code="t", label="test", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R({Role.B}), R({Role.Ds})),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("A/Pc", R({Role.A, Role.Pc}), R({Role.W}), R({Role.T}))))
MODULES = {"t": SMALL}


def _row(pid, p_start, fv, *, diffidato=False):
    return ForecastRow(pid, f"p{pid}", "INT", "A", ("A",), int(p_start * 100), p_start, fv, None, p_start * fv, "published",
                       trace={"diffidato": "4 gialli" if diffidato else None})


def _roster(spec):
    return [RosterPlayer(pid, f"p{pid}", R(roles), 1, True) for pid, roles in spec]


ROSTER = _roster([(1, {Role.Por}), (2, {Role.Por}), (3, {Role.Dc}), (4, {Role.B}), (5, {Role.M}), (6, {Role.C, Role.T}),
                  (7, {Role.A}), (8, {Role.W}), (9, {Role.Pc}), (10, {Role.Ds})])
ROWS = {1: _row(1, 0.9, 6.0), 2: _row(2, 0.1, 6.0), 3: _row(3, 0.9, 6.5), 4: _row(4, 0.8, 6.2, diffidato=True),
        5: _row(5, 0.5, 6.4), 6: _row(6, 0.9, 6.3), 7: _row(7, 0.9, 7.5), 8: _row(8, 0.7, 7.0), 9: _row(9, 0.6, 7.2),
        10: _row(10, 0.9, 5.5)}


def test_the_bench_starts_with_the_goalkeeper_and_orders_the_rest_by_coverage():
    xi = choose_xi(ROSTER, ROWS, MODULES, ["t"])
    assert [s.player_id for s in xi.slots] == [1, 3, 6, 7]
    bench = order_bench(ROSTER, xi, ROWS, SMALL, bench_size=4)
    ids = [e.player_id for e in bench.order]
    assert ids[0] == 2 and len(ids) == 4 and bench.size == 4
    # p4 (B) is the only outfielder who fits Dc, adapted: his coverage is the Dc starter's miss (0.1) x (ep - p x malus)
    p4 = next(e for e in bench.order if e.player_id == 4)
    assert p4.covers == ("Dc",) and p4.coverage == pytest.approx(0.1 * (0.8 * 6.2 - 0.8 * ADAPTED_MALUS))
    assert p4.diffidato is True
    assert bench.uncovered == ("M/C",)                                  # p5 (M) is fifth by coverage and the bench holds four
    assert order_bench(ROSTER, xi, ROWS, SMALL, bench_size=5).uncovered == ()
    # ordering: coverage descending, then expected points
    assert [e.coverage for e in bench.order[1:]] == sorted((e.coverage for e in bench.order[1:]), reverse=True)


def test_an_uncovered_slot_is_named_and_forced_only_never_counts_as_cover():
    roster = _roster([(1, {Role.Por}), (3, {Role.Dc}), (5, {Role.M}), (7, {Role.A}), (10, {Role.Ds}), (11, {Role.T})])
    rows = {pid: _row(pid, 0.9, 6.0) for pid in (1, 3, 5, 7, 10, 11)}
    xi = choose_xi(roster, rows, MODULES, ["t"])
    bench = order_bench(roster, xi, rows, SMALL, bench_size=5)
    assert [e.player_id for e in bench.order] == [11, 10] or [e.player_id for e in bench.order] == [10, 11]
    ds = next(e for e in bench.order if e.player_id == 10)
    assert ds.covers == () and ds.coverage == 0.0                       # Ds fits Dc only through a forced substitution
    assert bench.uncovered == ("Por", "Dc", "A/Pc")                     # the T covers M/C adapted and nothing else


def test_an_excluded_player_is_on_neither_list_and_the_bench_respects_its_size():
    xi = choose_xi(ROSTER, ROWS, MODULES, ["t"], excluded=frozenset({7}))
    assert 7 not in {s.player_id for s in xi.slots}
    bench = order_bench(ROSTER, xi, ROWS, SMALL, bench_size=2, excluded=frozenset({7}))
    assert 7 not in {e.player_id for e in bench.order} and len(bench.order) == 2


def _brute(module, roster, natural, adapted, banned):
    best = None
    indexes = [i for i in range(len(roster)) if roster[i].player_id not in banned]
    for perm in itertools.permutations(indexes, len(module.slots)):
        total = 0.0
        for slot, i in zip(module.slots, perm):
            fit = slot.fit(roster[i].roles)
            if fit is Fit.NATURAL:
                total += natural[i]
            elif fit is Fit.ADAPTED:
                total += adapted[i]
            else:
                break
        else:
            best = total if best is None or total > best else best
    return best


def test_contingencies_are_re_solves_and_agree_with_brute_force():
    rng = random.Random(11)
    for _ in range(40):
        roster = rng.sample(ROSTER, k=rng.randint(5, 8))
        rows = {p.player_id: _row(p.player_id, round(rng.uniform(0.3, 1.0), 2), round(rng.uniform(5, 8), 2)) for p in roster}
        try:
            xi = choose_xi(roster, rows, MODULES, ["t"])
        except ForecastError:
            continue
        plans = contingencies(roster, rows, MODULES, ["t"], xi, threshold=1.01)      # every starter gets a plan
        assert [c.player_id for c in plans] == [s.player_id for s in xi.slots]
        natural = [rows[p.player_id].expected_points for p in roster]
        adapted = [rows[p.player_id].expected_points - rows[p.player_id].p_start * ADAPTED_MALUS for p in roster]
        for c in plans:
            oracle = _brute(SMALL, roster, natural, adapted, {c.player_id})
            if oracle is None:
                assert c.note is not None and c.points_lost is None
            else:
                assert c.points_lost == pytest.approx(xi.total - oracle)
                assert c.player_id in {s.player_id for s in c.leaves}


def test_contingencies_only_for_doubtful_starters_and_they_name_who_enters():
    xi = choose_xi(ROSTER, ROWS, MODULES, ["t"])
    plans = contingencies(ROSTER, ROWS, MODULES, ["t"], xi, threshold=0.75)
    assert plans == []                                                  # every starter is at 0.9
    rows = {**ROWS, 7: _row(7, 0.7, 7.5)}                                # 5.25 still beats the Pc's 4.32: he starts, doubtfully
    xi = choose_xi(ROSTER, rows, MODULES, ["t"])
    [plan] = contingencies(ROSTER, rows, MODULES, ["t"], xi, threshold=0.75)
    assert plan.player_id == 7 and plan.p_start == 0.7 and plan.module == "t" and plan.module_changes is False
    assert [s.player_id for s in plan.enters] == [9] and [s.player_id for s in plan.leaves] == [7]
    assert plan.points_lost == pytest.approx(rows[7].expected_points - rows[9].expected_points)


def test_close_calls_name_the_best_excluded_fit_per_slot_within_the_margin():
    rows = {**ROWS, 8: _row(8, 0.9, 8.0)}                                # W at 7.2 - 0.9 malus = 6.3 net vs A p7 at 6.75
    xi = choose_xi(ROSTER, rows, MODULES, ["t"])
    calls = close_calls(ROSTER, xi, rows, SMALL, margin=0.5, limit=3)
    assert [c.slot for c in calls] == ["A/Pc"]                           # every other slot's best alternative is over a point away
    call = calls[0]
    assert call.player_in["player_id"] == 7 and call.player_out["player_id"] == 8
    assert call.gap == pytest.approx(6.75 - (0.9 * 8.0 - 0.9 * ADAPTED_MALUS))
    assert call.player_out["source"] == "published"
    assert close_calls(ROSTER, xi, rows, SMALL, margin=0.5, limit=0) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_weekly_xi.py -c core/pyproject.toml -q`
Expected: FAIL — `order_bench` not importable.

- [ ] **Step 3: Implement in `xi.py`**

Append after `choose_xi` (which gained `excluded` in Task 7):

```python
@dataclass(frozen=True)
class BenchEntry:
    player_id: int
    name: str
    roles: tuple[str, ...]
    expected_points: float
    coverage: float
    covers: tuple[str, ...]
    diffidato: bool

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "roles": list(self.roles),
                "expected_points": self.expected_points, "coverage": self.coverage, "covers": list(self.covers),
                "diffidato": self.diffidato}


@dataclass(frozen=True)
class Bench:
    order: list[BenchEntry]
    uncovered: tuple[str, ...]
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"order": [e.to_dict() for e in self.order], "uncovered": list(self.uncovered), "size": self.size}


def _net(row: ForecastRow | None, fit: Fit) -> float:
    if row is None:
        return 0.0
    return row.expected_points - (row.p_start * ADAPTED_MALUS if fit is Fit.ADAPTED else 0.0)


def order_bench(roster: list[RosterPlayer], xi: XiChoice, forecast_by_id: dict[int, ForecastRow], module: Module, *,
                bench_size: int, excluded: frozenset[int] = frozenset()) -> Bench:
    """The bench in the order the platform will read it (spec, "The ordered
    bench"). The goalkeeper first -- the best remaining Por -- because the
    platform substitutes him first and separately. Then coverage value:
    for each candidate, the sum over the starters of that starter's
    probability of no voto, times whether the candidate legally fits the
    starter's slot (natural or adapted, never forced-only), times the
    candidate's expected points net of the malus where adapted. Built for a
    substitution that keeps the module (open question 20). A slot no bench
    player can legally fill is named."""
    fielded = {s.player_id for s in xi.slots}
    starters = [(module.slots[k], forecast_by_id.get(s.player_id)) for k, s in enumerate(xi.slots)]
    candidates = [p for p in roster if p.player_id not in fielded and p.player_id not in excluded]
    entries: list[BenchEntry] = []
    for p in candidates:
        row = forecast_by_id.get(p.player_id)
        coverage, covers = 0.0, []
        for slot, starter in starters:
            fit = slot.fit(p.roles)
            if fit not in (Fit.NATURAL, Fit.ADAPTED):
                continue
            miss = 1.0 - (starter.p_start if starter is not None else 0.0)
            coverage += miss * _net(row, fit)
            if slot.label not in covers:
                covers.append(slot.label)
        entries.append(BenchEntry(p.player_id, p.name, tuple(r.value for r in sort_roles(p.roles)),
                                  row.expected_points if row else 0.0, coverage, tuple(covers),
                                  bool(row and row.trace.get("diffidato"))))
    keepers = sorted((e for e in entries if Role.Por in roster_roles(roster, e.player_id)), key=lambda e: (-e.expected_points, e.name))
    rest = sorted((e for e in entries if e not in keepers[:1]), key=lambda e: (-e.coverage, -e.expected_points, e.name))
    order = (keepers[:1] + rest)[:max(bench_size, 0)]
    covered = {label for e in order for label in e.covers}
    uncovered = tuple(dict.fromkeys(slot.label for slot in module.slots if slot.label not in covered))
    return Bench(order, uncovered, bench_size)


def roster_roles(roster: list[RosterPlayer], player_id: int) -> frozenset[Role]:
    return next((p.roles for p in roster if p.player_id == player_id), frozenset())


@dataclass(frozen=True)
class Contingency:
    player_id: int
    name: str
    p_start: float
    module: str | None
    module_changes: bool
    enters: tuple[XiSlot, ...]
    leaves: tuple[XiSlot, ...]
    points_lost: float | None
    note: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "p_start": self.p_start, "module": self.module,
                "module_changes": self.module_changes, "enters": [s.to_dict() for s in self.enters],
                "leaves": [s.to_dict() for s in self.leaves], "points_lost": self.points_lost, "note": self.note}


def contingencies(roster: list[RosterPlayer], forecast_by_id: dict[int, ForecastRow], modules: dict[str, Module],
                  allowed: Sequence[str], xi: XiChoice, *, threshold: float,
                  excluded: frozenset[int] = frozenset()) -> list[Contingency]:
    """"If he doesn't start, do this", by computation: for each starter
    whose p_start is below the threshold, one re-solve with him at zero,
    reported as the diff (spec, "The contingencies")."""
    out: list[Contingency] = []
    fielded = {s.player_id for s in xi.slots}
    for s in xi.slots:
        row = forecast_by_id.get(s.player_id)
        p = row.p_start if row is not None else 0.0
        if p >= threshold:
            continue
        try:
            alt = choose_xi(roster, forecast_by_id, modules, allowed, excluded=excluded | {s.player_id})
        except ForecastError as exc:
            out.append(Contingency(s.player_id, s.name, p, None, False, (), (), None, str(exc)))
            continue
        alt_ids = {a.player_id for a in alt.slots}
        enters = tuple(a for a in alt.slots if a.player_id not in fielded)
        leaves = tuple(o for o in xi.slots if o.player_id not in alt_ids)
        out.append(Contingency(s.player_id, s.name, p, alt.module, alt.module != xi.module, enters, leaves,
                               xi.total - alt.total, None))
    return out


@dataclass(frozen=True)
class CloseCall:
    slot: str
    player_in: dict[str, Any]
    player_out: dict[str, Any]
    gap: float

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "in": self.player_in, "out": self.player_out, "gap": self.gap}


def _call_side(row: ForecastRow | None, player: RosterPlayer, net: float) -> dict[str, Any]:
    return {"player_id": player.player_id, "name": player.name, "expected_points": net,
            "fv_sd": row.fv_sd if row else None, "source": row.source if row else None,
            "matchup": row.matchup if row else None}


def close_calls(roster: list[RosterPlayer], xi: XiChoice, forecast_by_id: dict[int, ForecastRow], module: Module, *,
                margin: float, limit: int, excluded: frozenset[int] = frozenset()) -> list[CloseCall]:
    """Per slot, the chosen player against the best excluded player who
    fits it, when the gap is inside the margin; the smallest gaps first,
    at most `limit` (spec, "The close calls")."""
    fielded = {s.player_id for s in xi.slots}
    by_id = {p.player_id: p for p in roster}
    outside = [p for p in roster if p.player_id not in fielded and p.player_id not in excluded]
    calls: list[CloseCall] = []
    for k, s in enumerate(xi.slots):
        slot = module.slots[k]
        best: tuple[float, RosterPlayer] | None = None
        for p in outside:
            fit = slot.fit(p.roles)
            if fit not in (Fit.NATURAL, Fit.ADAPTED):
                continue
            net = _net(forecast_by_id.get(p.player_id), fit)
            if best is None or net > best[0]:
                best = (net, p)
        if best is None:
            continue
        gap = s.expected_points - best[0]
        if gap < margin:
            calls.append(CloseCall(slot.label, _call_side(forecast_by_id.get(s.player_id), by_id[s.player_id], s.expected_points),
                                   _call_side(forecast_by_id.get(best[1].player_id), best[1], best[0]), gap))
    return sorted(calls, key=lambda c: c.gap)[:max(limit, 0)]
```

Imports at the top of `xi.py`: `from fantaclaude.model.modules import Fit, Module, assign_weighted` and
`from fantaclaude.model.roles import Role, sort_roles`. `ForecastRow.matchup`
does not exist until Task 9: until then `_call_side` reads
`getattr(row, "matchup", None)` — replace it with `row.matchup` in Task 9.

- [ ] **Step 4: Thread the outputs through the write, the report and the render**

`records.py` — `write_lineup_run` gains `bench: dict[str, Any] | None = None`,
`contingencies: list[dict[str, Any]] | None = None`,
`close_calls: list[dict[str, Any]] | None = None`, written as `?::JSON` into
the three columns (`json.dumps(..., ensure_ascii=False)`, `None` when None).

`report.py` — after `choose_xi`:

```python
            settings = con.execute("SELECT modules, bench_size FROM v_league_settings_current").fetchone()
            ...
            bench = order_bench(roster, choice, forecast_by_id, modules[choice.module],
                                bench_size=int(settings[1] or 0), excluded=excluded)
            plans = contingencies(roster, forecast_by_id, modules, allowed, choice, threshold=cfg.contingency_threshold,
                                  excluded=excluded)
            calls = close_calls(roster, choice, forecast_by_id, modules[choice.module], margin=cfg.close_call_margin,
                                limit=cfg.close_calls_max, excluded=excluded)
            if bench.uncovered:
                warnings.append(f"bench covers no {', '.join(bench.uncovered)} slot: a starter there who misses is replaced by the "
                                f"platform's own algorithm, changing the module or adapting someone unasked")
```

(`modules = load_modules()`, `allowed = list(settings[0])`, `excluded` from
Task 7.) `LineupReport` gains `bench: dict | None`, `contingencies: list[dict]`,
`close_calls: list[dict]`, emitted under those keys; the write passes them.
When `bench_size` is null in the settings row, the bench is built with size
0 and a warning names it: `"league_settings carries no bench size -- run
fantaclaude sync-league; no bench ordered"`.

`cli/app.py` — `_render_lineup`, after the `other modules:` line:

```python
        bench = payload.get("bench")
        if bench and bench["order"]:
            lines.append("bench: " + " · ".join(
                f"{e['name']}{'!' if e['diffidato'] else ''} [{'/'.join(e['roles'])}] {e['coverage']:.2f}" for e in bench["order"]))
            if bench["uncovered"]:
                lines.append(f"  uncovered: {', '.join(bench['uncovered'])}")
        for c in payload.get("contingencies") or []:
            if c["note"]:
                lines.append(f"if out: {c['name']} ({c['p_start']:.0%}) -- {c['note']}")
                continue
            enters = ", ".join(f"{s['name']} at {s['slot']}" for s in c["enters"]) or "nobody"
            module = f", module {c['module']}" if c["module_changes"] else ""
            lines.append(f"if out: {c['name']} ({c['p_start']:.0%}) -> {enters}{module}, -{c['points_lost']:.2f}")
        for c in payload.get("close_calls") or []:
            a, b = c["in"], c["out"]
            sd = lambda x: f"±{x['fv_sd']:.1f}" if x.get("fv_sd") is not None else ""
            lines.append(f"close: {c['slot']} {a['name']} {a['expected_points']:.2f}{sd(a)} over {b['name']} "
                         f"{b['expected_points']:.2f}{sd(b)} (gap {c['gap']:.2f}; {a['source']} vs {b['source']})")
```

(`!` after a name marks a diffidato — say so in the skill.)

- [ ] **Step 5: Extend the CLI test and run everything**

In `test_lineup_names_the_xi_when_league_yml_names_my_team`
(`core/tests/test_lineup_cli.py`) add, after the `predictions == 17` assertion:

```python
    assert payload["bench"]["size"] == 12 and 1 <= len(payload["bench"]["order"]) <= 6      # 17 players, 11 fielded
    assert all(e["player_id"] not in {s["player_id"] for s in xi["slots"]} for e in payload["bench"]["order"])
    assert payload["contingencies"] == [] and isinstance(payload["close_calls"], list)      # everyone at 90%
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT bench IS NOT NULL, contingencies IS NOT NULL FROM lineup_runs").fetchone() == (True, True)
    con.close()
    assert "bench: " in plain.stdout
```

(The MCP `lineup_settings` fixture carries `tbench: 12`, which
`league.settings` stores as `bench_size`.)

```bash
uv run pytest core/tests/test_weekly_xi.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q
uv run poe test && uv run poe lint
git add core/src/fantaclaude/analysis/weekly core/src/fantaclaude/cli/app.py core/tests/test_weekly_xi.py core/tests/test_lineup_cli.py
git commit -m "feat(weekly): the ordered bench by coverage, the contingencies by re-solve, the close calls per slot"
```

---

### Task 9: The matchup term and the spread

**Files:**
- Modify: `core/src/fantaclaude/analysis/weekly/forecast.py`
- Modify: `core/src/fantaclaude/analysis/weekly/records.py` (`matchup`), `report.py`, `xi.py` (`_call_side`), `__init__.py`
- Modify: `core/src/fantaclaude/cli/app.py` (the top-per-role line shows the matchup)
- Create: `core/tests/test_weekly_terms.py`

**Interfaces:**
- Consumes: `v_player_match_current`, `v_fixtures_current`, `v_teams_current`, `model.scoring.{BonusMalus, Events, fantavoto, voto_sheet}`, `model.seasons.back_seasons`, `analysis.history.{COACH_ROLE, EVENT_COLUMNS}`, `PlayerFixture.{home, opponent_short}`, `WeeklyConfig.{matchup_shrink_k, matchup_cap, spread_prior_k, spread_back_seasons}`.
- Produces: `scoring_in_force(con) -> tuple[str, BonusMalus]`; `MatchupTable(venue, conceded, rows, season_id)`, `load_matchups(con, *, season_id, sheet, bm, cfg) -> MatchupTable`, `matchup_term(table, *, classic_role, fixture, cfg) -> tuple[float, dict]`; `SpreadTable(player, role_prior)`, `load_spreads(con, *, current_season, sheet, bm, cfg) -> SpreadTable`, `spread_for(table, *, player_id, classic_role, cfg) -> tuple[float | None, dict]`; `Terms(matchups, spreads)`, `load_terms(con, *, season_id, cfg) -> Terms`; `ForecastRow.matchup: float`; `forecast(..., terms: Terms | None = None)`; `predictions.matchup` and `fv_sd` written.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/test_weekly_terms.py
from datetime import UTC, datetime

import pytest
from conftest import seed_matches, seed_voti
from fantaclaude.analysis.weekly.config import WeeklyConfig
from fantaclaude.analysis.weekly.forecast import (
    Terms,
    load_matchups,
    load_spreads,
    load_terms,
    matchup_term,
    spread_for,
)
from fantaclaude.analysis.weekly.rounds import PlayerFixture
from fantaclaude.model.scoring import BonusMalus

BM = BonusMalus(goal=3, penalty_goal=3, assist=1, goal_conceded=-1, penalty_saved=3, penalty_missed=-3, yellow=-0.5, red=-1, own_goal=-2)
CFG = WeeklyConfig(matchup_shrink_k=2.0, matchup_cap=1.0, spread_prior_k=2.0)
KO = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)


def _teams(db):
    db.execute("INSERT INTO listone_snapshots (fetched_at, source, raw_path, sha256, player_count) VALUES (now(), 'seed', 'x', 'seed-teams', 0)")
    sid = db.execute("SELECT max(snapshot_id) FROM listone_snapshots").fetchone()[0]
    for tid, name, short in ((1, "Inter", "INT"), (2, "Roma", "ROM"), (3, "Atalanta", "ATA"), (4, "Genoa", "GEN")):
        db.execute("INSERT INTO teams VALUES (?, ?, ?, ?)", [sid, tid, name, short])


def _season(db):
    _teams(db)
    # giornata 1: Inter home to Roma, Atalanta home to Genoa; giornata 2: Roma home to Atalanta, Genoa home to Inter
    seed_matches(db, 21, [(1, KO, "INT", "ROM"), (1, KO, "ATA", "GEN"), (2, KO, "ROM", "ATA"), (2, KO, "GEN", "INT")])
    seed_voti(db, 21, 1, [(1, "a", "Inter", "A", 7.0, {}), (2, "b", "Roma", "A", 5.0, {}), (3, "c", "Atalanta", "D", 6.0, {}),
                          (4, "d", "Inter", "D", 6.0, {})])
    seed_voti(db, 21, 2, [(1, "a", "Inter", "A", 6.0, {}), (2, "b", "Roma", "A", 6.0, {}), (3, "c", "Atalanta", "D", 5.0, {}),
                          (4, "d", "Inter", "D", 7.0, {}), (5, "e", "Roma", "A", None, {})])


def test_matchups_read_this_seasons_rows_and_shrink_toward_zero(db):
    _season(db)
    table = load_matchups(db, season_id=21, sheet="Fantacalcio", bm=BM, cfg=CFG)
    assert table.rows == 8 and table.season_id == 21                                    # the senza voto row is not a rating
    # attackers: Inter home 7.0 (g1), Roma home 6.0 (g2); Roma away 5.0 (g1), Inter away 6.0 (g2): role mean 6.0
    delta, n = table.venue[("A", True)]
    assert n == 2 and delta == pytest.approx((6.5 - 6.0) * 2 / (2 + 2.0))                 # shrunk by n / (n + k)
    # conceded to attackers by Roma: the attackers who faced Roma (Inter's a, g1, 7.0) against the role mean 6.0
    delta, n = table.conceded[("ROM", "A")]
    assert n == 1 and delta == pytest.approx((7.0 - 6.0) * 1 / 3)
    assert table.conceded[("GEN", "A")] == (pytest.approx(0.0), 1)                        # Inter's a, g2, 6.0: at the mean


def test_the_term_is_the_two_shrunk_deltas_capped_and_traced(db):
    _season(db)
    table = load_matchups(db, season_id=21, sheet="Fantacalcio", bm=BM, cfg=CFG)
    term, trace = matchup_term(table, classic_role="A", fixture=PlayerFixture(KO.replace(tzinfo=None), True, "ROM"), cfg=CFG)
    assert term == pytest.approx(table.venue[("A", True)][0] + table.conceded[("ROM", "A")][0])
    assert trace["home"] is True and trace["opponent"] == "ROM" and trace["n_venue"] == 3 and trace["n_conceded"] == 1
    capped, _ = matchup_term(table, classic_role="A", fixture=PlayerFixture(KO.replace(tzinfo=None), True, "ROM"),
                             cfg=WeeklyConfig(matchup_cap=0.1))
    assert capped == pytest.approx(0.1)                                                     # 0.25 + 0.33 held at the cap
    nothing, trace = matchup_term(table, classic_role="A", fixture=None, cfg=CFG)
    assert nothing == 0.0 and trace == {"reason": "no fixture"}
    unknown, trace = matchup_term(table, classic_role="P", fixture=PlayerFixture(KO.replace(tzinfo=None), False, "XXX"), cfg=CFG)
    assert unknown == 0.0 and trace["n_venue"] == 0 and trace["n_conceded"] == 0


def test_spreads_pool_the_players_own_dispersion_with_the_role_prior(db):
    _teams(db)
    for g, votes in enumerate(((6.0, 5.0), (8.0, 5.0), (7.0, 5.0)), start=1):                   # back season 20: a swings, b is flat
        seed_voti(db, 20, g, [(1, "a", "Inter", "A", votes[0], {}), (2, "b", "Roma", "A", votes[1], {})])
    seed_voti(db, 21, 1, [(1, "a", "Inter", "A", 6.5, {}), (3, "c", "Atalanta", "A", 6.0, {})])
    table = load_spreads(db, current_season=21, sheet="Fantacalcio", bm=BM, cfg=CFG)
    prior = table.role_prior["A"]
    assert prior == pytest.approx((sum((v - 6.0) ** 2 for v in (6.0, 8.0, 7.0, 5.0, 5.0, 5.0)) / 6) ** 0.5)  # pstdev of the back rows
    own, n = table.player[1]
    assert n == 4
    sd, trace = spread_for(table, player_id=1, classic_role="A", cfg=CFG)
    assert sd == pytest.approx(((n * own ** 2 + 2.0 * prior ** 2) / (n + 2.0)) ** 0.5) and trace["n"] == 4
    thin, trace = spread_for(table, player_id=3, classic_role="A", cfg=CFG)                        # one rating: the prior nearly alone
    assert trace["n"] == 1 and thin == pytest.approx(((1 * 0.0 + 2.0 * prior ** 2) / 3.0) ** 0.5)
    none, trace = spread_for(table, player_id=99, classic_role="A", cfg=CFG)
    assert none == pytest.approx(prior) and trace["n"] == 0
    missing, trace = spread_for(table, player_id=1, classic_role="X", cfg=CFG)
    assert missing is None and trace == {"reason": "no role prior"}


def test_load_terms_reads_the_scoring_in_force(db, mcp_fixture_json):
    from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
    record_snapshot(db, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    terms = load_terms(db, season_id=21, cfg=CFG)
    assert isinstance(terms, Terms) and terms.matchups.rows == 0 and terms.spreads.role_prior == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_weekly_terms.py -c core/pyproject.toml -q`
Expected: FAIL — names not importable.

- [ ] **Step 3: Implement in `forecast.py`**

```python
from collections import defaultdict
from statistics import fmean, pstdev

from fantaclaude.analysis.history import COACH_ROLE, EVENT_COLUMNS
from fantaclaude.model.scoring import BonusMalus, Events, fantavoto, voto_sheet
from fantaclaude.model.seasons import back_seasons


def scoring_in_force(con: duckdb.DuckDBPyConnection) -> tuple[str, BonusMalus]:
    """The voto sheet and the bonus/malus of the current league_settings row -- what the run itself scored under."""
    row = con.execute("SELECT payload FROM v_league_settings_current").fetchone()
    if row is None:
        raise ForecastError("no league_settings snapshot -- run `fantaclaude sync-league` first")
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    calculate = payload.get("calculate") or {}
    return voto_sheet(calculate), BonusMalus.from_calculate(calculate)


def _shrunk(values: list[float], mean: float, k: float) -> tuple[float, int]:
    n = len(values)
    if n == 0:
        return 0.0, 0
    return (fmean(values) - mean) * n / (n + k), n


@dataclass(frozen=True)
class MatchupTable:
    venue: dict[tuple[str, bool], tuple[float, int]]        # (classic_role, home) -> (shrunk delta, rows)
    conceded: dict[tuple[str, str], tuple[float, int]]      # (opponent_short, classic_role) -> (shrunk delta, rows)
    rows: int
    season_id: int


def load_matchups(con: duckdb.DuckDBPyConnection, *, season_id: int, sheet: str, bm: BonusMalus,
                  cfg: WeeklyConfig) -> MatchupTable:
    """This season's rated rows joined to this season's fixtures -- the only
    season with fixtures, since the voti workbooks carry no opponent and no
    venue (spec, "The matchup term"). Two deltas per role against the
    role's season mean, each shrunk toward zero by n / (n + k)."""
    rows = con.execute(
        "SELECT m.classic_role, m.voto, " + ", ".join(f"m.{c}" for c in EVENT_COLUMNS) + ", t.short, f.home_short, f.away_short "
        "FROM v_player_match_current m "
        "JOIN v_teams_current t ON lower(t.name) = lower(m.team) "
        "JOIN v_fixtures_current f ON f.competition = 'SA' AND f.season_id = m.season_id AND f.giornata = m.giornata "
        "AND (f.home_short = t.short OR f.away_short = t.short) "
        "WHERE m.sheet = ? AND m.season_id = ? AND NOT m.senza_voto AND m.voto IS NOT NULL AND m.classic_role <> ?",
        [sheet, season_id, COACH_ROLE]).fetchall()
    by_role: dict[str, list[float]] = defaultdict(list)
    by_venue: dict[tuple[str, bool], list[float]] = defaultdict(list)
    by_opponent: dict[tuple[str, str], list[float]] = defaultdict(list)
    for role, voto, *counts, short, home_short, away_short in rows:
        fv = fantavoto(float(voto), Events(**{name: float(v) for name, v in zip(EVENT_COLUMNS, counts)}), bm)
        home = short == home_short
        by_role[str(role)].append(fv)
        by_venue[(str(role), home)].append(fv)
        by_opponent[(str(away_short if home else home_short), str(role))].append(fv)
    means = {role: fmean(v) for role, v in by_role.items()}
    venue = {key: _shrunk(v, means[key[0]], cfg.matchup_shrink_k) for key, v in by_venue.items()}
    conceded = {key: _shrunk(v, means[key[1]], cfg.matchup_shrink_k) for key, v in by_opponent.items()}
    return MatchupTable(venue, conceded, len(rows), season_id)


def matchup_term(table: MatchupTable, *, classic_role: str, fixture: PlayerFixture | None,
                 cfg: WeeklyConfig) -> tuple[float, dict[str, Any]]:
    """Venue plus conceded, capped at +-matchup_cap; zero with no fixture."""
    if fixture is None:
        return 0.0, {"reason": "no fixture"}
    venue, n_venue = table.venue.get((classic_role, fixture.home), (0.0, 0))
    conceded, n_conceded = table.conceded.get((fixture.opponent_short or "", classic_role), (0.0, 0))
    term = max(-cfg.matchup_cap, min(cfg.matchup_cap, venue + conceded))
    return term, {"home": fixture.home, "opponent": fixture.opponent_short, "venue": round(venue, 4), "n_venue": n_venue,
                  "conceded": round(conceded, 4), "n_conceded": n_conceded, "term": round(term, 4)}


@dataclass(frozen=True)
class SpreadTable:
    player: dict[int, tuple[float, int]]      # player_id -> (own dispersion, rated matches)
    role_prior: dict[str, float]              # classic_role -> pstdev of the back seasons' fantavoti


def load_spreads(con: duckdb.DuckDBPyConnection, *, current_season: int, sheet: str, bm: BonusMalus,
                 cfg: WeeklyConfig) -> SpreadTable:
    """Every player's fantavoto dispersion over his rated matches in the
    stored seasons, scored under the current bonus/malus, and the role
    prior from the back seasons alone."""
    seasons = [*back_seasons(current_season, cfg.spread_back_seasons), current_season]
    rows = con.execute(
        "SELECT season_id, player_id, classic_role, voto, " + ", ".join(EVENT_COLUMNS) + " FROM v_player_match_current "
        "WHERE sheet = ? AND NOT senza_voto AND voto IS NOT NULL AND classic_role <> ? AND season_id = ANY(?)",
        [sheet, COACH_ROLE, seasons]).fetchall()
    own: dict[int, list[float]] = defaultdict(list)
    prior_rows: dict[str, list[float]] = defaultdict(list)
    for season_id, player_id, role, voto, *counts in rows:
        fv = fantavoto(float(voto), Events(**{name: float(v) for name, v in zip(EVENT_COLUMNS, counts)}), bm)
        own[int(player_id)].append(fv)
        if int(season_id) != current_season:
            prior_rows[str(role)].append(fv)
    player = {pid: (pstdev(v) if len(v) > 1 else 0.0, len(v)) for pid, v in own.items()}
    prior = {role: pstdev(v) if len(v) > 1 else 0.0 for role, v in prior_rows.items()}
    return SpreadTable(player, prior)


def spread_for(table: SpreadTable, *, player_id: int, classic_role: str, cfg: WeeklyConfig) -> tuple[float | None, dict[str, Any]]:
    """sd^2 = (n s^2 + k prior^2) / (n + k); None when the role has no prior."""
    prior = table.role_prior.get(classic_role)
    if prior is None:
        return None, {"reason": "no role prior"}
    own, n = table.player.get(player_id, (0.0, 0))
    pooled = ((n * own ** 2 + cfg.spread_prior_k * prior ** 2) / (n + cfg.spread_prior_k)) ** 0.5
    return pooled, {"n": n, "own": round(own, 4), "prior": round(prior, 4), "k": cfg.spread_prior_k}


@dataclass(frozen=True)
class Terms:
    matchups: MatchupTable
    spreads: SpreadTable


def load_terms(con: duckdb.DuckDBPyConnection, *, season_id: int, cfg: WeeklyConfig) -> Terms:
    sheet, bm = scoring_in_force(con)
    return Terms(load_matchups(con, season_id=season_id, sheet=sheet, bm=bm, cfg=cfg),
                 load_spreads(con, current_season=season_id, sheet=sheet, bm=bm, cfg=cfg))
```

`ForecastRow` gains `matchup: float = 0.0` (after `excluded`; `to_dict` emits
it). `forecast()` takes `terms: Terms | None = None` and, per row:

```python
        matchup, matchup_trace = (0.0, {"reason": "no terms"}) if terms is None else matchup_term(
            terms.matchups, classic_role=str(role), fixture=fixture, cfg=cfg)
        fv_sd, sd_trace = (None, {"reason": "no terms"}) if terms is None else spread_for(
            terms.spreads, player_id=int(pid), classic_role=str(role), cfg=cfg)
        fv_if_plays = (float(fm) + matchup) * b.value_factor
        b.trace["matchup"], b.trace["spread"] = matchup_trace, sd_trace
```

and passes `fv_sd` and `matchup=matchup` into the row. `records.py` writes
`matchup` (`..., late, matchup, trace) VALUES (...)` with `r.matchup`).
`report.py` loads `terms = load_terms(con, season_id=season_id, cfg=cfg)`
before the forecast and passes it; `xi._call_side` reads `row.matchup`.
Export `Terms`, `load_terms`, `scoring_in_force` from `__init__.py`.

`cli/app.py` — the per-role top line shows the term when it is non-zero:

```python
        lines.append(f"  {role}: " + " · ".join(
            f"{x['name']} {x['p_start_published']}%×{x['fv_if_plays']:.2f}"
            + (f"({x['matchup']:+.2f})" if x.get("matchup") else "") + f"={x['expected_points']:.2f}" for x in rows))
```

- [ ] **Step 4: Run the tests, the suite and lint; commit**

Two giornate of voti and this season's fixtures are in the live database,
so `lineup` now writes a non-null `fv_sd` for every player with a role prior
and a matchup term that is shrunk to nearly nothing — which is the design.

```bash
uv run pytest core/tests/test_weekly_terms.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q
uv run poe test && uv run poe lint
git add core/src/fantaclaude/analysis/weekly core/src/fantaclaude/cli/app.py core/tests/test_weekly_terms.py
git commit -m "feat(weekly): the matchup term off this season's fixtures, shrunk and capped, and fv_sd pooled with the role prior"
```

---

### Task 10: `lineup_submitted` and `fantaclaude lineup record`

**Files:**
- Create: `core/src/fantaclaude/analysis/weekly/submitted.py`
- Modify: `core/src/fantaclaude/analysis/weekly/__init__.py`, `core/src/fantaclaude/cli/app.py`
- Create: `core/tests/test_lineup_record.py`
- Modify: `core/tests/test_lineup_cli.py`, `records/README.md`

**Interfaces:**
- Consumes: `xi.{RosterPlayer, my_roster}`, `model.modules.{assign, Module, load_modules}`, `ingest.names.{Candidate, match_listone}`, `v_lineup_runs_current`, `v_league_settings_current.modules`, `analysis.exports.write_parquet`.
- Produces: `SubmissionError`; `RunXi(lineup_run_id, module, xi: list[dict], bench: list[dict], my_team, late)`; `load_run_xi(con, *, season_id, giornata, lineup_run_id) -> RunXi`; `Submission(module, xi: list[dict], bench: list[dict], lineup_run_id)`; `build_submission(*, roster, run, modules, allowed, module=None, swaps=(), xi_names=None, bench_names=None) -> Submission`; `record_submitted(con, *, season_id, giornata, submission, my_team, source, now) -> int`; `export_submitted_record(con, submitted_id, records_dir) -> list[Path]`; `fantaclaude lineup record`. Task 13 calls `record_submitted` with `source="platform"`.

- [ ] **Step 1: Write the failing unit tests**

```python
# core/tests/test_lineup_record.py
from datetime import UTC, datetime

import pytest
from fantaclaude.analysis.weekly import RosterPlayer
from fantaclaude.analysis.weekly.submitted import (
    RunXi,
    SubmissionError,
    build_submission,
    export_submitted_record,
    record_submitted,
)
from fantaclaude.model.modules import Module, Slot
from fantaclaude.model.roles import Role

R = frozenset
SMALL = Module(code="t", label="test", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R({Role.B}), R({Role.Ds})),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("A/Pc", R({Role.A, Role.Pc}), R({Role.W}), R({Role.T}))))
MODULES = {"t": SMALL}
ROSTER = [RosterPlayer(1, "Svilar", R({Role.Por}), 1, True), RosterPlayer(2, "Radunovic", R({Role.Por}), 1, True),
          RosterPlayer(3, "Bastoni", R({Role.Dc}), 1, True), RosterPlayer(4, "Kolasinac", R({Role.B}), 1, True),
          RosterPlayer(5, "Zielinski", R({Role.M}), 1, True), RosterPlayer(6, "Calhanoglu", R({Role.C, Role.T}), 1, True),
          RosterPlayer(7, "Martinez L.", R({Role.A}), 1, True), RosterPlayer(8, "Politano", R({Role.W}), 1, True),
          RosterPlayer(9, "Kean", R({Role.A}), 1, True), RosterPlayer(10, "Sabelli", R({Role.Ds}), 1, True)]
RUN = RunXi(7, "t", [{"slot": "Por", "player_id": 1, "name": "Svilar"}, {"slot": "Dc", "player_id": 3, "name": "Bastoni"},
                     {"slot": "M/C", "player_id": 6, "name": "Calhanoglu"}, {"slot": "A/Pc", "player_id": 7, "name": "Martinez L."}],
            [{"player_id": 2, "name": "Radunovic"}, {"player_id": 9, "name": "Kean"}, {"player_id": 4, "name": "Kolasinac"}], 4242, False)


def test_the_runs_xi_is_recorded_as_it_stood():
    s = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"])
    assert s.module == "t" and s.lineup_run_id == 7
    assert [(x["slot"], x["player_id"]) for x in s.xi] == [("Por", 1), ("Dc", 3), ("M/C", 6), ("A/Pc", 7)]
    assert [b["player_id"] for b in s.bench] == [2, 9, 4]


def test_a_swap_replaces_the_starter_and_sends_him_to_the_bench_place_of_the_man_who_came_in():
    s = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("Martinez L.", "Kean")])
    assert [x["player_id"] for x in s.xi] == [1, 3, 6, 9] and [b["player_id"] for b in s.bench] == [2, 7, 4]
    by_id = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("7", "9")])
    assert [x["player_id"] for x in by_id.xi] == [1, 3, 6, 9]
    adapted = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("Bastoni", "Kolasinac")])
    assert [x["player_id"] for x in adapted.xi] == [1, 4, 6, 7]                     # B at Dc is an adapted, legal fit
    assert [b["player_id"] for b in adapted.bench] == [2, 9, 3]


def test_every_illegal_submission_is_refused_by_name():
    for kw, match in ((dict(swaps=[("Kean", "Martinez L.")]), "is not in run 7's XI"),
                      (dict(swaps=[("Martinez L.", "Bastoni")]), "already in the XI"),
                      (dict(swaps=[("Martinez L.", "Nobody")]), "not on my roster"),
                      (dict(swaps=[("Martinez L.", "Radunovic")]), "cannot field"),          # a second Por at A/Pc: no fit
                      (dict(swaps=[("Bastoni", "Sabelli")]), "cannot field"),                # Ds at Dc is forced-only
                      (dict(module="352"), "not permitted"),
                      (dict(xi_names=["Svilar", "Bastoni", "Calhanoglu", "Martinez L."]), "--xi needs --module"),
                      (dict(module="t", xi_names=["Svilar", "Bastoni", "Calhanoglu"]), "distinct players"),
                      (dict(module="t", xi_names=["Svilar", "Bastoni", "Calhanoglu", "Martinez L."], bench_names=["Bastoni"]), "both in the XI and on the bench")):
        with pytest.raises(SubmissionError, match=match):
            build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], **kw)
    with pytest.raises(SubmissionError, match="no lineup run"):
        build_submission(roster=ROSTER, run=None, modules=MODULES, allowed=["t"])


def test_a_full_xi_needs_no_run_and_takes_its_slots_from_the_module():
    s = build_submission(roster=ROSTER, run=None, modules=MODULES, allowed=["t"], module="t",
                         xi_names=["Kean", "Svilar", "Kolasinac", "Zielinski"], bench_names=["Radunovic"])
    assert s.lineup_run_id is None and [(x["slot"], x["name"]) for x in s.xi] == [("Por", "Svilar"), ("Dc", "Kolasinac"),
                                                                                    ("M/C", "Zielinski"), ("A/Pc", "Kean")]


def test_record_appends_and_the_newest_is_current(db, tmp_path):
    s = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"])
    first = record_submitted(db, season_id=21, giornata=4, submission=s, my_team=4242, source="hand",
                             now=datetime(2026, 9, 11, 17, 0, tzinfo=UTC))
    swapped = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("Martinez L.", "Kean")])
    second = record_submitted(db, season_id=21, giornata=4, submission=swapped, my_team=4242, source="hand",
                              now=datetime(2026, 9, 11, 18, 0, tzinfo=UTC))
    assert second == first + 1 and db.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 2
    current = db.execute("SELECT submitted_id, module, source, lineup_run_id FROM v_lineup_submitted_current").fetchone()
    assert current == (second, "t", "hand", 7)
    paths = export_submitted_record(db, second, tmp_path / "records")
    assert [p.parent.name for p in paths] == ["lineup_submitted"] and paths[0].name.endswith(f"-{second}.parquet")
    assert export_submitted_record(db, second, tmp_path / "records") == []                     # never rewritten
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_lineup_record.py -c core/pyproject.toml -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `submitted.py`**

```python
# core/src/fantaclaude/analysis/weekly/submitted.py
"""lineup_submitted: the XI actually fielded (spec, "Closing the loop").

Read back from the platform, never written to it; the hand path first.
`fantaclaude lineup record` defaults to the newest run before the lock, takes
`--swap Out=In` for the deviations and `--module`, or `--xi` and `--bench` in
full, and writes source `hand`; `ingest lineup` (Task 13) writes source
`platform` once the GET is mapped. A submission is checked the way the
platform would check it -- a permitted module, eleven distinct roster
players, every one of them a natural or adapted fit somewhere in it -- and
refused otherwise, because a record of an XI nobody could field is not a
record. Appended, never edited; the newest per giornata is current.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.exports import write_parquet
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.xi import RosterPlayer
from fantaclaude.ingest.names import AMBIGUOUS, Candidate, match_listone
from fantaclaude.model.modules import Module, assign
from fantaclaude.timeutil import to_db

SOURCES = ("hand", "platform")


class SubmissionError(ValueError):
    """The XI to record is not one the platform would accept, or names nobody on my roster."""


@dataclass(frozen=True)
class RunXi:
    lineup_run_id: int
    module: str
    xi: list[dict[str, Any]]
    bench: list[dict[str, Any]]
    my_team: int | None
    late: bool


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def load_run_xi(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int,
                lineup_run_id: int | None) -> RunXi:
    """The run whose XI was fielded: the one asked for, else the newest
    non-late run of the giornata that named one."""
    if lineup_run_id is None:
        row = con.execute("SELECT lineup_run_id, module, xi, bench, my_team, late FROM v_lineup_runs_current "
                          "WHERE season_id = ? AND giornata = ? AND xi IS NOT NULL", [season_id, giornata]).fetchone()
        if row is None:
            raise ForecastError(f"no lineup run with an XI for giornata {giornata} before the lock -- pass --lineup-run <id>, "
                                f"or --xi and --bench in full")
    else:
        row = con.execute("SELECT lineup_run_id, module, xi, bench, my_team, late FROM lineup_runs WHERE lineup_run_id = ?",
                          [lineup_run_id]).fetchone()
        if row is None:
            raise ForecastError(f"lineup run {lineup_run_id} is not in lineup_runs")
        if row[2] is None:
            raise ForecastError(f"lineup run {lineup_run_id} named no XI")
    bench = _json(row[3]) or {}
    return RunXi(int(row[0]), str(row[1]), list(_json(row[2])), list(bench.get("order", [])), row[4], bool(row[5]))


@dataclass(frozen=True)
class Submission:
    module: str
    xi: list[dict[str, Any]]           # [{slot, player_id, name}] in the module's slot order
    bench: list[dict[str, Any]]        # [{player_id, name}] in bench order
    lineup_run_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "xi": list(self.xi), "bench": list(self.bench), "lineup_run_id": self.lineup_run_id}


def _resolve(name: str, roster: list[RosterPlayer]) -> RosterPlayer:
    """A roster player by the listone's spelling or by id; refused, never guessed."""
    by_id = {p.player_id: p for p in roster}
    if name.strip().isdigit():
        pid = int(name.strip())
        if pid not in by_id:
            raise SubmissionError(f"player_id {pid} is not on my roster")
        return by_id[pid]
    match = match_listone(name, [Candidate(p.player_id, p.name, "", "") for p in roster])
    if match.player_id is not None:
        return by_id[match.player_id]
    if match.status == AMBIGUOUS:
        close = ", ".join(repr(by_id[i].name) for i in match.candidates if i in by_id)
        raise SubmissionError(f"{name!r} is {len(match.candidates)} players of my roster ({close}); add the initial the listone uses")
    raise SubmissionError(f"{name!r} is not on my roster; write him the listone's way, or by id")


def build_submission(*, roster: list[RosterPlayer], run: RunXi | None, modules: dict[str, Module], allowed: Sequence[str],
                     module: str | None = None, swaps: Sequence[tuple[str, str]] = (),
                     xi_names: Sequence[str] | None = None, bench_names: Sequence[str] | None = None) -> Submission:
    by_id = {p.player_id: p for p in roster}
    if xi_names is not None:
        if module is None:
            raise SubmissionError("--xi needs --module: the module fielded is part of the record")
        xi_ids = [_resolve(n, roster).player_id for n in xi_names]
        bench_ids = [_resolve(n, roster).player_id for n in (bench_names or [])]
        run_id = None if run is None else run.lineup_run_id
    else:
        if run is None:
            raise SubmissionError("no lineup run to record from -- pass --xi and --bench in full")
        module = module or run.module
        xi_ids = [int(s["player_id"]) for s in run.xi]
        bench_ids = [int(b["player_id"]) for b in run.bench]
        for out_name, in_name in swaps:
            out_p, in_p = _resolve(out_name, roster), _resolve(in_name, roster)
            if out_p.player_id not in xi_ids:
                raise SubmissionError(f"{out_p.name} is not in run {run.lineup_run_id}'s XI")
            if in_p.player_id in xi_ids:
                raise SubmissionError(f"{in_p.name} is already in the XI")
            xi_ids[xi_ids.index(out_p.player_id)] = in_p.player_id
            bench_ids = [out_p.player_id if b == in_p.player_id else b for b in bench_ids]
        run_id = run.lineup_run_id
    if module not in allowed or module not in modules:
        raise SubmissionError(f"module {module!r} is not permitted (league_settings.modules: {list(allowed)})")
    chosen = modules[str(module)]
    if len(xi_ids) != len(chosen.slots) or len(set(xi_ids)) != len(chosen.slots):
        raise SubmissionError(f"an XI is {len(chosen.slots)} distinct players, got {len(xi_ids)}")
    both = sorted(set(xi_ids) & set(bench_ids))
    if both:
        raise SubmissionError(f"{', '.join(by_id[i].name for i in both)}: both in the XI and on the bench")
    legal = assign(chosen, [by_id[i].roles for i in xi_ids], allow_adapted=True)
    if legal is None:
        raise SubmissionError(f"those {len(chosen.slots)} cannot field {chosen.label} legally (natural or adapted fits only) -- "
                              f"the platform would refuse it too")
    xi = [{"slot": chosen.slots[k].label, "player_id": xi_ids[i], "name": by_id[xi_ids[i]].name} for k, i in enumerate(legal)]
    bench = [{"player_id": b, "name": by_id[b].name} for b in bench_ids]
    return Submission(str(module), xi, bench, run_id)


def record_submitted(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int, submission: Submission,
                     my_team: int | None, source: str, now: datetime) -> int:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    return int(con.execute(
        "INSERT INTO lineup_submitted (season_id, giornata, lineup_run_id, my_team, module, xi, bench, source, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?) RETURNING submitted_id",
        [season_id, giornata, submission.lineup_run_id, my_team, submission.module,
         json.dumps(submission.xi, ensure_ascii=False), json.dumps(submission.bench, ensure_ascii=False), source,
         to_db(now)]).fetchone()[0])


def export_submitted_record(con: duckdb.DuckDBPyConnection, submitted_id: int, records_dir: Path) -> list[Path]:
    """records/lineup_submitted/<season>-<giornata>-<recorded_at>-<submitted_id>.parquet, once."""
    season, giornata, recorded = con.execute(
        "SELECT season_id, giornata, recorded_at FROM lineup_submitted WHERE submitted_id = ?", [submitted_id]).fetchone()
    path = records_dir / "lineup_submitted" / f"{season}-{giornata:02d}-{recorded:%Y%m%dT%H%M%SZ}-{submitted_id}.parquet"
    return [path] if write_parquet(con, f"SELECT * FROM lineup_submitted WHERE submitted_id = {int(submitted_id)}", path) else []
```

Export `SubmissionError`, `RunXi`, `Submission`, `build_submission`,
`load_run_xi`, `record_submitted`, `export_submitted_record` from `__init__.py`.

- [ ] **Step 4: Run the unit tests**

Run: `uv run pytest core/tests/test_lineup_record.py -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 5: Write the failing CLI test, then the command**

Append to `core/tests/test_lineup_cli.py`:

```python
def test_lineup_record_writes_the_fielded_xi_by_hand(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone])
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone})})
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    forecast = json.loads(runner.invoke(app, ["lineup", "--json"]).stdout)
    xi_names = [s["name"] for s in forecast["xi"]["slots"]]
    result = runner.invoke(app, ["lineup", "record", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["lineup_run_id"] == forecast["lineup_run_id"] and payload["module"] == forecast["xi"]["module"]
    assert [x["name"] for x in payload["xi"]] == xi_names and payload["source"] == "hand" and payload["giornata"] == 3
    assert [p.rsplit("/", 2)[-2] for p in payload["records"]] == ["lineup_submitted"]
    # in full: the same eleven under the same module, a bench of two
    bench_names = [e["name"] for e in forecast["bench"]["order"]][:2]
    full = runner.invoke(app, ["lineup", "record", "--module", forecast["xi"]["module"], "--xi", ",".join(xi_names),
                               "--bench", ",".join(bench_names), "--json"])
    assert full.exit_code == ExitCode.OK, full.output
    assert json.loads(full.stdout)["lineup_run_id"] is None and [b["name"] for b in json.loads(full.stdout)["bench"]] == bench_names
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 2
    assert con.execute("SELECT lineup_run_id FROM v_lineup_submitted_current").fetchone()[0] is None
    con.close()
    for args, needle, code in (([ "--swap", "Nobody=" + bench_names[0]], "not on my roster", ExitCode.USAGE),
                               (["--swap", "malformed"], "Out=In", ExitCode.USAGE),
                               (["--xi", ",".join(xi_names)], "--xi needs --module", ExitCode.USAGE),
                               (["--giornata", "99"], "not in the season", ExitCode.USAGE)):
        bad = runner.invoke(app, ["lineup", "record", *args])
        assert bad.exit_code == code and needle in bad.stderr, (args, bad.output)
    plain = runner.invoke(app, ["lineup", "record"])
    assert plain.exit_code == ExitCode.OK and "recorded: giornata 3" in plain.stdout
```

In `core/src/fantaclaude/cli/app.py`, after `lineup_note_cmd`:

```python
RECORD_RUN_OPTION = typer.Option(None, "--lineup-run", help="The lineup run whose XI was fielded (default: the newest before the lock for the giornata).")
RECORD_SWAP_OPTION = typer.Option(None, "--swap", help="Out=In -- a deviation from the run's XI, by the listone's spelling or id; repeatable.")
RECORD_MODULE_OPTION = typer.Option(None, "--module", help="The module fielded (default: the run's).")
RECORD_XI_OPTION = typer.Option(None, "--xi", help="The eleven, comma-separated, in full (needs --module).")
RECORD_BENCH_OPTION = typer.Option(None, "--bench", help="The bench in order, comma-separated (with --xi; default none).")


def _render_record(payload: dict) -> str:
    origin = f"from run {payload['lineup_run_id']}" if payload["lineup_run_id"] is not None else "in full"
    lines = [f"recorded: giornata {payload['giornata']} · {payload['module']} · {origin} · source {payload['source']} · "
             f"lineup_submitted {payload['submitted_id']}" + (" · " + ", ".join(payload["records"]) if payload["records"] else "")]
    lines += [f"  {x['slot']:<6} {x['name']}" for x in payload["xi"]]
    if payload["bench"]:
        lines.append("  bench: " + " · ".join(b["name"] for b in payload["bench"]))
    return "\n".join(lines)


@lineup_app.command("record")
def lineup_record_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = GIORNATA_ONE_OPTION,
    lineup_run: int | None = RECORD_RUN_OPTION,
    swap: list[str] | None = RECORD_SWAP_OPTION,
    module: str | None = RECORD_MODULE_OPTION,
    xi: str | None = RECORD_XI_OPTION,
    bench: str | None = RECORD_BENCH_OPTION,
) -> None:
    """Record the XI actually fielded on the platform -- the run's XI, with --swap for the deviations, or --xi and --bench in full. Appended, never edited. Local, no network."""
    from fantaclaude.analysis.weekly import ForecastError, target_round
    from fantaclaude.analysis.weekly.submitted import (
        SubmissionError,
        build_submission,
        export_submitted_record,
        load_run_xi,
        record_submitted,
    )
    from fantaclaude.analysis.weekly.xi import my_roster
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.model.modules import load_modules
    from fantaclaude.paths import records_dir
    from fantaclaude.timeutil import utc_now

    entries = _league_yml_or_exit()
    if not entries or "my_team" not in entries:
        typer.echo("league.yml has no my_team leaf (asta verify-transfer prints it) -- nothing to record a roster against", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY)
    my_team = int(entries["my_team"].value)
    swaps: list[tuple[str, str]] = []
    for s in swap or []:
        out_name, sep, in_name = s.partition("=")
        if not sep or not out_name.strip() or not in_name.strip():
            typer.echo(f"--swap takes Out=In, got {s!r}", err=True)
            raise typer.Exit(code=ExitCode.USAGE)
        swaps.append((out_name.strip(), in_name.strip()))
    season_id = _seasons_or_exit(None)[-1]
    con = connect()
    try:
        apply_schema(con)
        try:
            round_ = target_round(con, utc_now(), season_id=season_id, giornata=giornata)
        except ForecastError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.USAGE if giornata is not None else ExitCode.NOT_READY) from None
        allowed_row = con.execute("SELECT modules FROM v_league_settings_current").fetchone()
        try:
            roster = my_roster(con, my_team)
            run = None if xi is not None and lineup_run is None else load_run_xi(
                con, season_id=season_id, giornata=round_.giornata, lineup_run_id=lineup_run)
            submission = build_submission(roster=roster, run=run, modules=load_modules(), allowed=list((allowed_row or [[]])[0] or []),
                                          module=module, swaps=swaps,
                                          xi_names=None if xi is None else [n.strip() for n in xi.split(",") if n.strip()],
                                          bench_names=None if bench is None else [n.strip() for n in bench.split(",") if n.strip()])
        except ForecastError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
        except SubmissionError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.USAGE) from None
        submitted_id = record_submitted(con, season_id=season_id, giornata=round_.giornata, submission=submission,
                                        my_team=my_team, source="hand", now=utc_now())
        records = export_submitted_record(con, submitted_id, records_dir())
    finally:
        con.close()
    payload = {"submitted_id": submitted_id, "season_id": season_id, "giornata": round_.giornata, "my_team": my_team,
               "source": "hand", **submission.to_dict(), "records": [str(p) for p in records]}
    emit(payload, json_=json_, render=_render_record)
```

- [ ] **Step 6: The records README, the suite, lint, commit**

Add to `records/README.md`, after the `lineup_runs`/`predictions` bullet:

```markdown
- `lineup_submitted/<season>-<giornata>-<UTC stamp>-<submitted_id>.parquet` — the
  XI actually fielded for that giornata, as `fantaclaude lineup record` wrote
  it by hand (source `hand`) or `fantaclaude ingest lineup` read it back from
  the platform (source `platform`), with the run it came from where one
  applies. Never rewritten; the newest per giornata is the one calibration
  scores my own week against.
```

```bash
uv run pytest core/tests/test_lineup_record.py core/tests/test_lineup_cli.py -c core/pyproject.toml -q
uv run poe test && uv run poe lint
git add core/src/fantaclaude/analysis/weekly core/src/fantaclaude/cli/app.py core/tests/test_lineup_record.py core/tests/test_lineup_cli.py records/README.md
git commit -m "feat(lineup): lineup_submitted and \`lineup record\` -- the fielded XI by hand, from the run with swaps or in full, checked as the platform would"
```

---

### Task 11: The `fanta-manager` skill and the docs

**Files:**
- Create: `.claude/skills/fanta-manager/SKILL.md`
- Modify: `README.md` (Capabilities, Layout), `CLAUDE.md` (the `data/` paragraph), `site/docs/cli.md`, `kb/README.md` (one line under the journal), `.claude/skills/fanta-asta/SKILL.md` (one sentence in `verify-transfer`)

**Interfaces:**
- Consumes: every command the earlier tasks shipped, by its `--help`.
- Produces: the skill the operator invokes on Tuesday and Friday.

- [ ] **Step 1: Write the skill**

```markdown
---
name: fanta-manager
description: The weekly loop with fantaclaude — `refresh` early in the week (the finished giornata's voti, the probabili and news pages), `lineup` before the lock (`fantaclaude lineup`, read top to bottom, argue with a `lineup note`, re-run), `note` for a fact from the week, `record` for the XI actually fielded. Use every giornata, from the Tuesday refresh to the Friday XI; never to submit, never to fetch "to check".
---

# fanta-manager

Python does the math; this skill does the judgment. It never computes a
p_start, a bench order or an expected score: it runs `fantaclaude lineup`,
reads what the run wrote, changes *inputs* (a note with a reason) and reads
again. Discover the CLI with `fantaclaude lineup --help` and
`fantaclaude ingest --help`; every command takes `--json`; `lineup`, `lineup
note` and `lineup record` are local (no network), the `ingest` commands are
the only fetches and each one is a single polite request per page.

Four rules, defended hard:

- **Change inputs, never outputs.** The number is a precedence the code
  applies — a note, else a squalifica, else the page — and everything else
  is a check that names a disagreement. To move a number, write the fact
  where the code reads it: `fantaclaude lineup note --type p_start --player
  "Kean" --p-start 0 --reason "out, club statement"`; `--type value --factor
  0.85` for a knock or a position change; `--type exclude` to keep him off
  the XI and the bench this week. Every note carries the giornata and a
  reason; `data/lineup-notes.yml` is the record.
- **A disagreement is adjudicated, never faded twice.** `warning:
  disagreement: …` lines are the infortunati list, the KB note or a European
  tie disagreeing with the page. The page's compilers usually already know
  what those sources know. Decide — a note, or nothing — and say which in the
  conversation; never lower a number because two sources hint the same way.
- **Never submit, never write to the platform.** The XI goes on the
  platform by hand (Non-goals): ninety seconds of typing, against a bug at
  18:44 on a Friday. Then `fantaclaude lineup record` writes what was
  fielded, and that record is what calibration scores.
- **Fetch at the two moments, not "to check".** `ingest probabili` and
  `ingest news` run in `refresh` and in `lineup`, and at most once more
  before a later kickoff day of the same round. `ingest stats-web` runs once,
  for the finished giornata. `ingest rosters` runs only when the operator
  says the lega changed. Never during a match.

## Modes

### `refresh` — early in the week (Tuesday)

1. `fantaclaude ingest stats-web --giornata <the finished giornata>` — the
   voti; needs `FANTACALCIO_WEB_COOKIE`. If it reports "not yet rated", stop
   and try again later in the day; do not loop.
2. `fantaclaude ingest probabili` then `fantaclaude ingest news` — one request
   each (news is two). Read the `unmatched` count: a name the listone does not
   resolve is `fantaclaude query --sql "SELECT * FROM v_unavailable_current
   WHERE player_id IS NULL"`, and the fix is an alias in
   `kb/rules/aliases.yml` under `fantacalcio_teams` (a club) or a spelling the
   listone uses (a player) — never a guess in the adapter.
3. `fantaclaude lineup` — Tuesday's forecast, so calibration has an early
   point per player (each prediction is honest against its own kickoff).
   Read every `warning:` and every `disagreement:`; write the notes that are
   already known (a suspension the page still prices, a confirmed absence).
4. `fantaclaude kb audit` and `fantaclaude doctor` — expired profiles and
   notes, the `lineup_notes` check. An unwritten journal entry for the
   finished giornata is a notice, not a refusal (the draft is 3c's).
5. `fantaclaude ingest rosters` only if told the lega changed (a trade, a
   free agent). Never to check.

### `lineup` — before the lock (Friday)

1. `fantaclaude ingest probabili` and `fantaclaude ingest news` once more.
2. `fantaclaude lineup`. Read it top to bottom:
   - the header: the deadline, the run, the page's stamp and how many
     matches are compiled; `LATE XI` means the lock has passed and only the
     rows for matches not yet started are honest;
   - `UNCOMPILED` and the per-match staleness warnings: a Tuesday
     compilation for a Sunday match is a number to distrust, not to use;
   - `blend:` how many p_start came from the page, a note, a squalifica; the
     news pages' stamps; the weekly hash;
   - every `warning: disagreement:` — adjudicate;
   - `XI:` the module and the eleven, `other modules:` what the rejected
     ones scored;
   - `bench:` in the platform's order, `[roles]` and the coverage value; `!`
     after a name is a diffidato (a yellow this week is a suspension next
     week — his call, not the model's); `uncovered:` a slot the bench cannot
     legally fill, which the platform's own algorithm will then fill by
     changing the module or adapting someone;
   - `if out:` for each doubtful starter, who enters and what it costs — the
     re-solve, ready before the news lands;
   - `close:` the slots decided by less than the margin, with each side's
     spread and where its number came from (`published vs note` says the
     call turned on something the operator wrote).
3. Argue with it through notes, re-run, read again. Then the operator
   submits on the platform by hand.
4. `fantaclaude lineup record` — the XI as fielded: the run's, with
   `--swap "Out=In"` for every deviation, or `--xi` and `--bench` in full.
   Run it right after submitting, while the round is the target.

### `note`

`fantaclaude lineup note --type p_start|value|exclude --player "<listone
spelling>" [--p-start 0..1 | --factor (0,2]] --reason "<why>" [--giornata N]`
— resolved against the listone, refused when nobody matches (add the
initial the listone uses). A note is for one giornata; next week it is
inert and stays in the file. The command prints the entry and the count;
re-run `fantaclaude lineup` to see what moved.

### `record`

`fantaclaude lineup record [--lineup-run <id>] [--swap Out=In ...] [--module
<code>] [--xi "a,b,..." --bench "c,d,..."] [--giornata N]` — appended, never
edited; the newest per giornata is current. After the round, pass
`--giornata` (the target has moved on). The read-back from the platform
(`fantaclaude ingest lineup`) replaces the hand record once it exists.

## Worked example

**Ask:** "Friday, giornata 4 — what do I field?"

**Good answer:** runs `ingest probabili` and `ingest news` once each, then
`fantaclaude lineup --json`; reads: page compiled 10/10 at 11:05, blend
published 471 · squalificato 2, one disagreement (Ederson at 90% in a
Conference week, the season rate under rotation expects 63%); asks the
operator, who knows Gasperini rested him on Thursday — no note; XI 3-5-1-1,
bench Svilar first, uncovered none; `if out: Kean (55%) -> Hojlund at Pc,
-1.4`; close call at W/A by 0.2 with a wider spread on the man left out.
Tells the operator the eleven, the bench order, and what to do if Kean is
out; the operator submits; runs `fantaclaude lineup record`.

**Bad answer:** multiplies Ederson's 90% by the rotation factor; edits
`records/`; fetches the probabili page again "to see if it changed";
submits anything anywhere.
```

- [ ] **Step 2: The docs that describe what moved**

`README.md` — replace the `Weekly (lineup)` capability bullet with:

```markdown
- **Weekly (lineup)** — `fantaclaude lineup`: the giornata's forecast for every player the probabili page lists — p_start by precedence (a `lineup note`, else a squalifica from the news pages, else the published number; the KB, the infortunati list and a European week only ever disagree out loud), a small matchup term and a spread, each prediction honest against its player's own kickoff and never revised — and, once `league.yml` names `my_team`, the XI and module that maximise expected points (an exact solve per permitted module), the bench in the platform's order with what it cannot cover, a re-solve for every doubtful starter and the close calls. `lineup note` writes a fact with its reason; `lineup record` writes the XI actually fielded; `ingest news` reads the two public lists, matched by name within the club
```

and in `Layout`, the `data/` lines become:

```
└── data/                 gitignored — fanta.duckdb, raw dated snapshots
                          (raw/probabili, raw/news and raw/rosters among them),
                          adjustments.yml (my auction beliefs) and lineup-notes.yml
                          (my facts for the week), both hand-editable,
                          and asta-state.json (the mirrored auction)
```

and `records/` gains `lineup_submitted` in its line. `CLAUDE.md` — after the
`data/adjustments.yml` sentence in the "Workspace and tests" section, add:

```markdown
`data/lineup-notes.yml` is the week's override file — mine, hand-editable,
appended by `fantaclaude lineup note`; every entry carries a `giornata` and a
`reason`, and an entry for another giornata is inert, never deleted.
`fantaclaude lineup`, `lineup note` and `lineup record` are local. `fantaclaude
ingest news` reads two public pages, one request each, under the same rules as
`ingest probabili`: never "to check", never during a match.
```

`site/docs/cli.md` — add before `## \`fantaclaude asta\``:

```markdown
## `fantaclaude lineup`

The weekly loop. `fantaclaude lineup` writes the giornata's forecast — every
player the probabili page lists, p_start by precedence, an XI when
`league.yml` names my team, the bench, the contingencies, the close calls —
immutably, each prediction against its player's own kickoff. `lineup note`
appends a fact for the week with its reason; `lineup record` appends the XI
actually fielded. `ingest news` reads the squalificati/diffidati and
infortunati lists beside `ingest probabili`. All local except the two ingests,
which are one polite request per page.
```

`kb/README.md` — under the tree, one line after `season-2026-27/`:
`# the weekly loop's own file is data/lineup-notes.yml, not here: a note is a fact for one giornata, not knowledge`.
`.claude/skills/fanta-asta/SKILL.md` — in `verify-transfer`, after "ready to
paste in": `(the weekly loop — \`fanta-manager\` — reads that leaf for the XI, the bench and the record)`.

- [ ] **Step 3: Lint the docs build and commit**

```bash
uv run poe docs-build
uv run poe test && uv run poe lint
git add .claude/skills/fanta-manager/SKILL.md .claude/skills/fanta-asta/SKILL.md README.md CLAUDE.md site/docs/cli.md kb/README.md
git commit -m "docs: the fanta-manager skill -- refresh, lineup, note, record -- and the README, CLAUDE.md, site and kb notes that describe the loop"
```

---

### Task 12: Field giornata 4 — the operational run

Not code: the commands, in order, each live one run once. Steps 1–3 are
Tuesday 8 September; Steps 4–6 are Friday 11 September, before 18:45 UTC;
Step 7 is the weekend. Whatever has not landed by the Friday is skipped for
that step and the loop still runs: Tasks 1–8 are the floor.

- [ ] **Step 1: Tuesday — the finished giornata's voti and the early-week pages**

```bash
uv run fantaclaude ingest stats-web --giornata 3
uv run fantaclaude ingest probabili            # giornata 4, Tuesday: some matches uncompiled
uv run fantaclaude ingest news                 # the Giudice Sportivo has ruled: squalificati may be non-empty
```

Expected: `stats_web` records giornata 3 (or says not yet rated — then the
afternoon, once); `probabili 21 giornata 4: file N, … over M compiled
match(es), K not yet compiled`; `news squalificati 21 giornata 4: file N, E
entries over 20 clubs …` and the infortunati line.

- [ ] **Step 2: Tuesday — the two captures 3a and 3b still owe**

```bash
cp "$(ls -t data/raw/probabili/*-probabili-21-04.html | head -1)" captured/probabili-2026-27-giornata-4-tuesday.html
cp "$(ls -t data/raw/news/*-news-squalificati-21-04.html | head -1)" captured/squalificati-2026-09-08.html
grep -c 'class="item-name"' captured/squalificati-2026-09-08.html
```

If the squalificati capture has entries: compare one against the inferred
shape in `_extract_news.py`'s docstring (`ul.unstyled > li > strong.item-name
+ div.item-description` under the labelled column). If it matches, update the
docstrings in `_extract_news.py` and `ingest/news.py` from "inferred" to
"observed 2026-09-08" and point `CAPTURES["squalificati"]` at the new file;
regenerate the fixture and point `test_a_suspension_and_a_diffida_are_read_under_their_column_labels`
at the real entries instead of the synthesised ones. If it does not match,
fix the parser against the capture first (the constants at the top of
`news.py`), then the fixture, then the tests — and re-run `ingest news`,
which dedupes on bytes and so re-reads the same file into the same rows
only if the parse changed. For the probabili capture: extend
`_extract_probabili.py` to emit `probabili_uncompiled_sample.html` from it
(one compiled card, one uncompiled) and point
`test_an_uncompiled_match_is_skipped_and_counted_not_fatal` at that fixture
(3a's Task 13, step 6). Commit as
`test(fixtures): the Tuesday pages -- an uncompiled probabili card and the squalificati entry shape, observed`.

- [ ] **Step 3: Tuesday — the early forecast**

```bash
uv run fantaclaude lineup
git add records/lineup_runs records/predictions && git commit -m "records: the giornata 4 Tuesday forecast"
```

Expected: `giornata 4 · deadline 2026-09-11 18:45 UTC …`, `UNCOMPILED: …`,
`blend: published … · news squalificati <stamp>, infortunati <stamp> · weekly <hash>`,
disagreements as warnings, the XI and the bench. Write the notes that are
already known. Do not fetch again until Friday.

- [ ] **Step 4: Friday — the pages, once each**

```bash
uv run fantaclaude ingest probabili
uv run fantaclaude ingest news
```

- [ ] **Step 5: Friday — the XI, before 18:45 UTC**

```bash
uv run fantaclaude lineup
# argue: uv run fantaclaude lineup note --type ... --player "..." --reason "..."   (then lineup again)
git add records/lineup_runs records/predictions && git commit -m "records: the giornata 4 XI"
```

Submit the XI and the bench on the platform by hand, in the order printed.

- [ ] **Step 6: Friday — the record**

```bash
uv run fantaclaude lineup record            # or with --swap "Out=In" for every deviation
git add records/lineup_submitted && git commit -m "records: the giornata 4 XI as fielded"
```

- [ ] **Step 7: The weekend — one more forecast per later kickoff day, if wanted**

Before Sunday's first kickoff, at most once: `ingest probabili`, `ingest
news`, `lineup` (the XI is `LATE`, the Sunday and Monday rows are on time —
that is the point). Commit the records. Nothing else is fetched until the
next Tuesday.

---

### Task 13: The read-back — capture the lineup GET from the browser, then `ingest lineup`

The last task, blocking nothing: `lineup record` is the record until this
lands. The request is **captured from the site**, never guessed against the
API, and the account whose session is used is the operator's own in the
browser — the API account in `.env` is used only afterwards, once the path
is known, to read a lineup after the lock (open question 17).

**Files:**
- Create: `captured/lineup-<giornata>-<date>.json` (gitignored; scrubbed)
- Modify: `mcp/fantacalcio/src/fantacalcio_mcp/api.py` (one GET)
- Create: `core/src/fantaclaude/ingest/lineup_api.py`, `core/tests/fixtures/_extract_lineup.py`, `core/tests/fixtures/lineup_sample.json`, `core/tests/test_lineup_api.py`
- Modify: `core/src/fantaclaude/cli/app.py` (`ingest lineup`), `core/tests/conftest.py` (`FakeAPI.lineup`), `.claude/skills/fanta-manager/SKILL.md`, `README.md`

**Interfaces:**
- Consumes: `submitted.{Submission, record_submitted, export_submitted_record}`, `xi.my_roster`, `league.settings.without_emails`, `api_client.run_with_api`.
- Produces: `FantacalcioAPI.lineup(team_id, matchday, league=None)`; `fetch_lineup(api, store, *, team_id, giornata, league) -> tuple[RawFile, dict]`; `load_lineup(payload, *, roster, modules, allowed) -> Submission`; `fantaclaude ingest lineup [--giornata]` writing `lineup_submitted` with `source: platform`.

- [ ] **Step 1: Capture the request the site makes (one browser session, the operator logged in)**

With the Playwright MCP: open `https://leghe.fantacalcio.it/`, hand the
browser to the operator to log in (the skill never types a password), then
navigate to the lega's *formazioni* page for a giornata whose lock has
passed (giornata 4 after Friday 18:45 UTC) and my team. Call
`browser_network_requests` and note every request to
`apileague.fantacalcio.it` made while that page loaded. The one that carries
the XI is the target: record its **method, path, query parameters and
headers besides the token**, and save its response body — scrubbed with
`league.settings.without_emails` — to `captured/lineup-04-2026-09-11.json`.
Do not click anything that saves, and do not repeat the load. If the page
renders the lineup from a different host or from HTML rather than a JSON
call, stop here: record what was seen in open question 20's neighbourhood
as a new open question and leave the hand path as the record.

- [ ] **Step 2: Extract the fixture and pin the shape**

Write `core/tests/fixtures/_extract_lineup.py` in the shape of
`_extract_asta.py`: read the capture, keep the object for my team alone,
assert the three keys below exist, write `lineup_sample.json`. The three
things this plan cannot type in advance, and the only deliberate blanks in
it, are read from the capture and written once into `lineup_api.py`'s
constants:

```python
# core/src/fantaclaude/ingest/lineup_api.py -- constants, from the capture (Task 13, Step 1)
PATH = "/…"                 # the GET the formazioni page made, e.g. "/…/v1/league/lineups"
PARAMS = ("…", "…")         # the query parameter names for the team and the matchday
MODULE_KEY, XI_KEY, BENCH_KEY, PLAYER_ID_KEY = "…", "…", "…", "…"   # where the module, the eleven, the bench and each id live
```

- [ ] **Step 3: Write the failing tests**

```python
# core/tests/test_lineup_api.py
import json
from datetime import UTC, datetime

from conftest import FIXTURE_DIR
from fantaclaude.analysis.weekly import RosterPlayer
from fantaclaude.ingest.lineup_api import load_lineup
from fantaclaude.model.modules import load_modules

SAMPLE = json.loads((FIXTURE_DIR / "lineup_sample.json").read_text(encoding="utf-8"))


def test_load_lineup_reads_the_module_the_eleven_and_the_bench_from_the_capture():
    modules = load_modules()
    # from the fixture: every id the capture lists is on the roster it was captured for
    ids = [/* the eleven's ids, from the fixture */]
    bench = [/* the bench ids, from the fixture */]
    roster = [RosterPlayer(pid, f"p{pid}", frozenset(), 1, True) for pid in ids + bench]
    submission = load_lineup(SAMPLE, roster=roster, modules=modules, allowed=list(modules))
    assert submission.module in modules and [x["player_id"] for x in submission.xi] == ids
    assert [b["player_id"] for b in submission.bench] == bench and submission.lineup_run_id is None
```

Fill the two lists from the fixture before running — they are the fixture's
own numbers, the way `test_probabili.py` pins `7332, "Bijlow", 90`. The
roles are empty because the platform's record is authoritative:
`load_lineup` does not re-check legality (the platform fielded it), it only
maps ids onto slots in the order the response gives them.

- [ ] **Step 4: Implement the GET, the adapter and the command**

`api.py`:

```python
    async def lineup(self, team_id: int, matchday: int, league: str | None = None) -> Any:
        """The XI a team fielded for a matchday, as the formazioni page reads it (Phase 3b, Task 13; captured, not guessed)."""
        return await self._get(PATH, params={PARAMS[0]: team_id, PARAMS[1]: matchday}, league=league)
```

(with `PATH`/`PARAMS` as the capture pinned them — in the MCP the path is a
literal, as every other method's is.) `lineup_api.py`:

```python
"""The XI actually fielded, read back from the platform (spec, "Closing
the loop"): one GET for the team league.yml names, never the account's
own, after the lock. Raw JSON scrubbed of emails under data/raw/lineup/."""

from __future__ import annotations

from typing import Any

from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.analysis.weekly.submitted import Submission
from fantaclaude.analysis.weekly.xi import RosterPlayer
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.league.settings import without_emails
from fantaclaude.model.modules import Module

PATH = "…"
PARAMS = ("…", "…")
MODULE_KEY, XI_KEY, BENCH_KEY, PLAYER_ID_KEY = "…", "…", "…", "…"


class LineupShapeError(ValueError):
    """The response is not the lineup object this adapter was written against."""


async def fetch_lineup(api: FantacalcioAPI, store: RawStore, *, team_id: int, giornata: int,
                       league: str | None = None) -> tuple[RawFile, dict[str, Any]]:
    payload = without_emails(await api.lineup(team_id, giornata, league=league))
    return store.write("lineup", payload, label=f"{team_id}-{giornata:02d}"), payload


def load_lineup(payload: dict[str, Any], *, roster: list[RosterPlayer], modules: dict[str, Module],
                allowed: list[str]) -> Submission:
    by_id = {p.player_id: p for p in roster}
    module = str(payload.get(MODULE_KEY) or "")
    if module not in modules:
        raise LineupShapeError(f"{MODULE_KEY}={module!r} is not a module this repo knows")
    chosen = modules[module]
    eleven = [int(entry[PLAYER_ID_KEY]) for entry in payload.get(XI_KEY) or []]
    bench = [int(entry[PLAYER_ID_KEY]) for entry in payload.get(BENCH_KEY) or []]
    if len(eleven) != len(chosen.slots):
        raise LineupShapeError(f"{XI_KEY} carries {len(eleven)} players, the module has {len(chosen.slots)} slots")
    name = lambda pid: by_id[pid].name if pid in by_id else f"#{pid}"
    return Submission(module, [{"slot": chosen.slots[k].label, "player_id": pid, "name": name(pid)} for k, pid in enumerate(eleven)],
                      [{"player_id": pid, "name": name(pid)} for pid in bench], None)
```

`ingest lineup` in `cli/app.py`, beside `ingest rosters`: reads `my_team`
from `league.yml` (refuse without it), the giornata from `--giornata` or the
newest *finished* round (`target_round` minus one — the read-back is after
the lock), fetches once through `run_with_api`, loads against `my_roster`,
and calls `record_submitted(..., source="platform")` and
`export_submitted_record`. Add `async def lineup(self, team_id, matchday, league=None)`
to `FakeAPI` answering `"lineup"` from `lineup_sample.json`, and a CLI test
in `test_lineup_cli.py` that runs `ingest lineup --giornata 3` and asserts
one `lineup_submitted` row with `source = 'platform'` and a raw file under
`data/raw/lineup/`.

- [ ] **Step 5: Run it once for real, document, commit**

```bash
uv run fantaclaude ingest lineup --giornata 4          # after Friday's lock, one call
git add records/lineup_submitted && git commit -m "records: giornata 4's XI read back from the platform"
```

Update the skill's `record` mode and the README's weekly bullet to say the
read-back exists; then:

```bash
uv run poe test && uv run poe lint
git add mcp/fantacalcio/src/fantacalcio_mcp/api.py core/src/fantaclaude/ingest/lineup_api.py core/src/fantaclaude/cli/app.py core/tests core/tests/fixtures/_extract_lineup.py core/tests/fixtures/lineup_sample.json .claude/skills/fanta-manager/SKILL.md README.md
git commit -m "feat(ingest): lineup -- the fielded XI read back from the platform through the GET the formazioni page makes"
```

---

## Self-review

**Spec coverage.** Schema rows for 3b (`news_files`/`unavailable`,
`lineup_submitted`, the four columns on each of `predictions` and
`lineup_runs`, `v_unavailable_current`, `v_predictions_current`) — Task 2.
The news adapter as captured: one adapter over two pages, names matched
within the club, flagged never dropped, the squalificati entry shape
inferred until the Tuesday capture — Tasks 1, 3, 12. Precedence, not
product, and the three checks; a diffida carried into the trace — Task 7.
`lineup-notes.yml` with three kinds, a giornata on every entry, the
adjustments machinery, `lineup note` — Task 6. Per-player deadlines, the
refusal only after the last kickoff, `lineup_runs.late` unchanged,
`v_predictions_current` as calibration's read (open question 18) — Tasks 2, 5.
The ordered bench with the goalkeeper first, coverage value, the uncovered
warning, the module-keeping assumption (open question 20); the
contingencies by re-solve; the close calls with spreads — Task 8. The
matchup term off this season's fixtures, shrunk and capped; `fv_sd` pooled
with the role prior; `weekly_hash` over the version and the constants —
Tasks 7, 9. `lineup_submitted`'s columns and the hand path with `--swap` —
Task 10. The `lineup` group with `note` and `record`, `ingest news` beside
`ingest probabili`, no server and no dashboard — Tasks 3, 6, 10. The skill's
four modes and its fetch cadence — Task 11. The order within 3b and the
giornata 4 deadline — Global Constraints and Task 12. The read-back
captured from the browser, never guessed, `ingest lineup` with source
`platform`, blocking nothing — Task 13. Open question 19 is deferred and has
no task, by decision. The Testing section's eight 3b bullets map to Tasks
3, 7, 5, 8, 8, 6, 10 and 7 respectively. The Failure-modes row for a
squalificato the page still prices is Task 7's precedence and Task 3's
`kind`.

**Where the plan departs from the spec's ordering.** The spec's 3b row lists
`weekly_hash` beside the matchup term and `fv_sd` (Task 9); this plan lands
it in Task 7, because the blend's thresholds are the first constants the
hash must cover and a `lineup_runs` row written without it between the two
tasks would be a row without its model. Nothing in the spec forbids the
earlier landing.

**Placeholders.** Task 13's `PATH`, `PARAMS`, the four key names and the two
id lists in its test are the deliberate blanks: a request nobody has
captured yet cannot have its path typed in advance, exactly as 3a's Task 3
left `# from the fixture` literals until Task 1 had run. Task 12's Tuesday
step names what to change if the squalificati capture disagrees with the
inferred shape, rather than pretending the shape is known. Everything else
is written out.

**Type consistency.** `ForecastRow`'s positional order is the 3a order
(`player_id, name, team_short, classic_role, roles, p_start_published,
p_start, fv_if_plays, fv_sd, expected_points, source`) followed by the
keyword fields added in order — `kickoff` (Task 5), `trace`, `excluded`
(Task 7), `matchup` (Task 9) — and every constructor call in the tests uses
keywords for those. `forecast()` returns `list[ForecastRow]` in Tasks 4–5
and `Forecast(rows, warnings)` from Task 7 on; its only caller is
`report.lineup()`, changed in the same task. `write_lineup_run` keeps its 3a
keyword signature and gains `weekly_hash` (Task 7) and `bench`,
`contingencies`, `close_calls` (Task 8), all defaulting to `None`.
`choose_xi(..., excluded=frozenset())` is added in Task 7 and consumed by
Task 8's three functions and by `contingencies`' re-solve. `PlayerFixture`
is defined in Task 5 and read by Task 9's `matchup_term`. `NotesLayer`'s
fields are the ones `blend.py` reads (`p_start`, `value_factor`, `excluded`,
`problems`, `inert`). `Submission` (Task 10) is what `load_lineup` (Task 13)
returns and what `record_submitted` consumes. `seed_probabili`'s optional
fifth element and `seed_matches` (Task 5) are what Tasks 7 and 9's tests
call. `_call_side` reads `row.matchup` from Task 9 and `getattr(row,
"matchup", None)` before it, as Task 8 says.
