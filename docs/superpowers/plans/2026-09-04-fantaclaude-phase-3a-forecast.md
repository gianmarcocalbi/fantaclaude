# fantaclaude Phase 3a — Close-out and the First Forecast: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write an honest, immutable forecast for a giornata — the published
`p_start` of every player on fantacalcio.it's probabili page times the pinned
run's expected fantavoto — before that giornata's first kickoff; name the XI and
module that maximise expected points over my roster; close the auction out
(`ingest rosters`, `asta verify-transfer`, `asta market-prices`); and ship the
penalty-rate fallback as model 3.

**Architecture:** Two new adapters follow the existing `fetch()` → dated raw
file → `load()`/`record()` shape (`ingest/probabili.py` for the public page,
`ingest/rosters_api.py` for the `cal`/`cs` fields off the team objects
`sync_league.fetch_teams` already pages). One new analysis module,
`analysis/weekly.py`, owns the round (read off `fixtures`), the page-and-run
join, the refused-after-kickoff write into `lineup_runs`/`predictions`, and the
XI over my roster via a new exact max-weight solve, `modules.assign_weighted`,
beside the feasibility `assign`. Three CLI commands (`ingest probabili`,
`ingest rosters`, `lineup`) and two asta commands (`verify-transfer`,
`market-prices`). No server, no dashboard, no skill yet (3b).

**Tech Stack:** Python 3.14, DuckDB, Typer, httpx, stdlib `html.parser`
(as `ingest/calendar.py`), pytest + `CliRunner` + the `FakeAPI` in
`core/tests/conftest.py`. No new dependency. No test touches the network.

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` — sections
"Schema" (the Phase 3a rows), "Forecasts are immutable, and that is what makes
the model improve" (the `lineup_runs`/`predictions` columns, `v_market_prices`,
`asta market-prices`), "Ingestion adapters" (`probabili`, `rosters_api`),
"Succession, not reconciliation" and live-event requirement 5 (the records copy
is permanent, `--prune` removes the working file alone), "`fanta-manager` — the
weekly loop" (every subsection: what 3a ships, the news adapter, blending,
`p_start` means a voto, the optimiser, surface, closing the loop), "Testing"
(the forecast, the roster adapter, verify-transfer, the optimiser against brute
force, a prediction cannot be written late), "Failure modes" (the stale
`status.mday` row), "Phasing" (the 3a row and "Order within 3a"), open
questions 9, 11 and 17. The code on `feat/phase-3-manager` at `443533f` is the
truth where this plan and the spec differ from it.

## Global Constraints

- **The deadline is giornata 3's first kickoff: 2026-09-04 18:45 UTC (20:45 in
  Rome).** Tasks 1–5 are the forecast path and need neither the roster nor the
  solver; do them first, run Task 13's first two commands the moment Task 5 is
  green. A forecast written after 18:45 UTC is `--late` and excluded from
  calibration; write it anyway, marked. Giornata 4 (11 September) is then the
  first clean point.
- **No test touches the network.** Public pages are read from
  `core/tests/fixtures/`; the league API is `FakeAPI`. The only live calls in
  this phase are the three in Task 13, each run once because the data is needed.
- **Live discipline (CLAUDE.md):** `ingest rosters` calls the real account —
  one paged call plus the status read, never "to check". `ingest probabili`
  reads a public page through the polite client (one request, honest
  User-Agent, no retry loop). `rank` without `--offline` re-syncs the league;
  use `--offline` in Task 13 unless a re-sync is wanted.
- **Every row in `lineup_runs` and `predictions` is immutable.** No UPDATE or
  DELETE path anywhere in the code. Several runs before one deadline are
  several rows. `records/` is never rewritten: a parquet that exists is left alone.
- **Timestamps:** aware UTC in Python, naive UTC in DuckDB, through
  `timeutil.to_db`. `fixtures.kickoff` is UTC; the API's `mstr` is UTC too
  (giornata 1: `2026-08-22T16:30:00` = 18:30 Rome).
- **`model_hash` moves only with `MODEL_VERSION`.** Task 11 bumps it to `"3"`;
  do not change projection code before Task 11 without that bump.
- **Exit codes** (`cli/app.py::ExitCode`): 0 ok, 1 error, 2 usage (bad flag), 3
  not ready (missing input, nothing ingested), 4 conflict. A late forecast
  without `--late` and a `--prune` on a dirty diff are conflicts (4).
- **Commits:** one per task, message documents the change, **no session link,
  no Co-Authored-By** (CLAUDE.md overrides the harness default). Do not push.
- **Emails never reach a raw file or a tool result:** the rosters payload goes
  through `league.settings.without_emails` before it is written.
- **Fixtures are extracted, never hand-edited.** The probabili fixture comes
  from `captured/` via `_extract_probabili.py`; a test that needs a variant
  rewrites the sample in the test (as `test_calendar._page` does).
- The Schema DDL is additive (`CREATE ... IF NOT EXISTS`, `CREATE OR REPLACE
  VIEW`); `SCHEMA_VERSION` becomes 4 and the live database upgrades in place.

## File structure

| File | Responsibility |
| --- | --- |
| `captured/probabili-2026-27-giornata-3.html` | the page as fetched (gitignored) |
| `core/tests/fixtures/_extract_probabili.py`, `probabili_sample.html` | two matches of it, the golden fixture |
| `core/src/fantaclaude/db/schema.py` | version 4: `probabili_files`, `probabili`, `roster_snapshots`, `rosters`, `lineup_runs`, `predictions`, and the views |
| `core/src/fantaclaude/ingest/probabili.py` | parse the page, record a file and its rows |
| `core/src/fantaclaude/ingest/rosters_api.py` | parse `cal`/`cs`, record a roster snapshot |
| `core/src/fantaclaude/commands/ingest.py` | `fetch_rosters` (reuses `sync_league.fetch_teams`), `current_league_id` |
| `core/src/fantaclaude/analysis/weekly.py` | the round, the forecast, the write, the XI, the report |
| `core/src/fantaclaude/analysis/exports.py` | `write_parquet` shared by run and lineup records |
| `core/src/fantaclaude/model/modules.py` | `assign_weighted` |
| `core/src/fantaclaude/asta/transfer.py` | pure reconciliation of mirror vs lega |
| `core/src/fantaclaude/commands/asta.py` | `verify_transfer`, `market_prices` |
| `core/src/fantaclaude/analysis/history.py`, `projection.py`, `valuation.py` | the penalty-rate fallback, model 3 |
| `core/src/fantaclaude/cli/app.py` | `ingest probabili`, `ingest rosters`, `lineup`, `asta verify-transfer`, `asta market-prices` |
| `core/tests/conftest.py` | `seed_probabili`, `seed_fixtures`, `seed_rosters` |
| `README.md`, `records/README.md`, `.claude/skills/fanta-asta/SKILL.md`, `.claude/skills/fanta-market/SKILL.md`, `core/src/fantaclaude/paths.py` | docs |

Run tests with `uv run pytest core/tests/<file> -c core/pyproject.toml -q`
(one file) or `uv run poe test-core` (the suite). Lint with `uv run poe lint`.

---

### Task 1: Capture the probabili page and extract the golden fixture

**Files:**
- Create: `captured/probabili-2026-27-giornata-3.html` (gitignored)
- Create: `core/tests/fixtures/_extract_probabili.py`
- Create: `core/tests/fixtures/probabili_sample.html`

**Interfaces:**
- Produces: the fixture Task 3's tests read, and the four observed facts Task 3's
  module constants pin (`PLAYER_CLASS`, `BENCH_CLASS_RE`, `STAMP_BEFORE_LISTS`,
  the match container marker `MATCH_OPEN`).

- [ ] **Step 1: One polite request, saved whole**

Run from the workspace root (one request, the repo's own User-Agent, no retry):

```bash
uv run python - <<'EOF'
from pathlib import Path
import httpx
from fantaclaude.ingest.http import USER_AGENT
r = httpx.get("https://www.fantacalcio.it/probabili-formazioni-serie-a",
              headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=False)
print(r.status_code, len(r.content))
r.raise_for_status()
Path("captured/probabili-2026-27-giornata-3.html").write_bytes(r.content)
EOF
```

Expected: `200` and a few hundred KB. `captured/` is gitignored; nothing to commit here.

- [ ] **Step 2: Read the shape off the capture, and write it down**

```bash
F=captured/probabili-2026-27-giornata-3.html
grep -c 'player-item' $F
grep -o 'aria-valuenow="[0-9]*"' $F | sort | uniq -c | sort -rn | head
grep -o 'data-formation="[^"]*"' $F | head -20
grep -o 'Ultimo aggiornamento[^<]*' $F | head -12
grep -o 'href="/serie-a/squadre/[^"]*"' $F | head -5
grep -n -o '<[a-z]* class="[^"]*match[^"]*"' $F | head -12
grep -n -o '<[a-z]* class="[^"]*\(bench\|panch\|riserv\)[^"]*"' $F | head -5
grep -o '[0-9]*[ªa°] *giornata' $F | head -3
```

Answer, from the output, and record each answer as a comment in the extract
script's docstring (Step 3):

1. Is `aria-valuenow` on the `li.player-item` itself or on a child? (Task 3's
   parser accepts both; note which.)
2. What element opens one match card — tag and class? That string is `MATCH_OPEN`
   below and must occur exactly ten times.
3. Does each match's `Ultimo aggiornamento` come **before** its two player
   lists or after? That is `STAMP_BEFORE_LISTS` in Task 3.
4. What class marks the panchina list (the container of the bench `li`s)?
   That is `BENCH_CLASS_RE` in Task 3. If starters and bench are told apart
   some other way (a heading, a data attribute), note it: the parser's
   `bench` flag follows whatever the capture shows.
5. Does the page name its giornata in text (`3ª giornata`)? If not, Task 3's
   `page.giornata` is `None` and `ingest probabili` trusts the calendar.

- [ ] **Step 3: The extract script**

```python
"""One-shot: build probabili_sample.html from the capture.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_probabili.py

Keeps the document up to the first match card, the first two match cards
whole (four clubs, both lists each, their `Ultimo aggiornamento`), and the
document tail after the last card, so the fixture is a real page with two
matches instead of ten. Captured 2026-09-04 (Friday of giornata 3, every
match compiled); the "not yet compiled" case is produced in the tests by
rewriting this sample, until an early-week capture replaces it.

Observed on the capture (fill these in from Task 1 Step 2):
- aria-valuenow sits on: <li itself | child ...>
- one match card opens with: MATCH_OPEN below
- Ultimo aggiornamento comes: <before | after> the lists
- the bench list is marked by: <class ...>
- the page names its giornata as: <"3ª giornata" | not at all>

Public page, nothing to scrub.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "captured" / "probabili-2026-27-giornata-3.html"
OUT = Path(__file__).with_name("probabili_sample.html")

MATCH_OPEN = '<div class="match-card'      # REPLACE with the tag+class that opens one match (Step 2, question 2)
KEEP = 2


def main() -> None:
    html = PAGE.read_text(encoding="utf-8")
    starts = []
    i = html.find(MATCH_OPEN)
    while i != -1:
        starts.append(i)
        i = html.find(MATCH_OPEN, i + 1)
    assert len(starts) == 10, f"expected ten match cards, found {len(starts)} for {MATCH_OPEN!r}"
    head = html[:starts[0]]
    kept = html[starts[0]:starts[KEEP]]
    # everything after the last card: find where the last card's siblings end is
    # not knowable without a DOM, so keep the last 4000 characters of the
    # document -- the closing tags and scripts -- which the parser ignores.
    tail = html[-4000:]
    OUT.write_text(head + kept + tail, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {KEEP} matches)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run it and eyeball the fixture**

```bash
uv run python core/tests/fixtures/_extract_probabili.py
grep -c 'player-item' core/tests/fixtures/probabili_sample.html
grep -o 'Ultimo aggiornamento[^<]*' core/tests/fixtures/probabili_sample.html
```

Expected: roughly 40–60 player items, exactly two stamps, and a file well under 300 KB. If the tail cut lands inside a `<script>`, raise the tail to the last `</main>` or `</body>` — the point is a fixture the stdlib parser reads without error.

- [ ] **Step 5: Commit**

```bash
git add core/tests/fixtures/_extract_probabili.py core/tests/fixtures/probabili_sample.html
git commit -m "test(fixtures): the probabili page, two matches of giornata 3 2026-27"
```

---

### Task 2: Schema version 4

**Files:**
- Modify: `core/src/fantaclaude/db/schema.py` (docstring, `SCHEMA_VERSION`, the `DDL` string)
- Test: `core/tests/test_schema.py`

**Interfaces:**
- Produces: the six tables and seven views below, exactly these column names and orders; every later task's INSERT relies on them.

- [ ] **Step 1: The failing test**

Add to `core/tests/test_schema.py`, next to `V3_OBJECTS`:

```python
V4_OBJECTS = {"probabili_files", "probabili", "roster_snapshots", "rosters", "lineup_runs", "predictions",
              "v_probabili_files_current", "v_probabili_current", "v_rosters_current", "v_rosters_first",
              "v_market_prices", "v_lineup_runs_current"}


def test_version_4_adds_the_forecast_and_roster_layer(tmp_path):
    con = connect(tmp_path / "v4.duckdb")
    assert apply_schema(con) == 4 and SCHEMA_VERSION == 4
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
    assert V4_OBJECTS <= names
    assert _columns(con, "predictions") == ["lineup_run_id", "season_id", "giornata", "player_id", "p_start_published",
                                            "p_start", "fv_if_plays", "fv_sd", "expected_points", "source"]
    assert _columns(con, "lineup_runs")[:6] == ["lineup_run_id", "season_id", "giornata", "run_id", "model_hash",
                                                "probabili_file_id"]
    assert _columns(con, "rosters") == ["snapshot_id", "team_id", "team_name", "owner", "player_id", "cost", "position"]
    # a version-3 file upgrades in place: apply twice, version row once per level
    assert apply_schema(con) == 4
    assert con.execute("SELECT count(*) FROM schema_version WHERE version = 4").fetchone()[0] == 1
    con.close()
```

- [ ] **Step 2: Run it, expect failure**

`uv run pytest core/tests/test_schema.py::test_version_4_adds_the_forecast_and_roster_layer -c core/pyproject.toml -q`
Expected: FAIL on `SCHEMA_VERSION == 4`.

- [ ] **Step 3: The DDL**

In `schema.py`: `SCHEMA_VERSION = 4`; append a sentence to the module docstring
("Version 4 (Phase 3a) adds the observed roster and probabili layers and the
forecast layer — `lineup_runs`/`predictions`, immutable, refused after the first
kickoff by the writer, never by the schema"). Append to the `DDL` string, after
`valuation_prices` and before the views:

```sql
CREATE SEQUENCE IF NOT EXISTS seq_probabili_files START 1;
CREATE TABLE IF NOT EXISTS probabili_files (
    file_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_probabili_files'),
    season_id   INTEGER NOT NULL,
    giornata    INTEGER NOT NULL,
    fetched_at  TIMESTAMP NOT NULL,
    source      VARCHAR NOT NULL,
    raw_path    VARCHAR NOT NULL,
    sha256      VARCHAR NOT NULL,
    row_count   INTEGER NOT NULL,
    matches     INTEGER NOT NULL,
    uncompiled  INTEGER NOT NULL,
    UNIQUE (season_id, giornata, sha256)
);
CREATE TABLE IF NOT EXISTS probabili (
    file_id     INTEGER NOT NULL,
    season_id   INTEGER NOT NULL,
    giornata    INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    name        VARCHAR NOT NULL,
    club_slug   VARCHAR NOT NULL,
    team_short  VARCHAR,
    formation   VARCHAR,
    p_start     INTEGER NOT NULL,
    bench       BOOLEAN NOT NULL,
    updated_at  TIMESTAMP,
    raw         JSON NOT NULL,
    PRIMARY KEY (file_id, player_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_roster_snapshots START 1;
CREATE TABLE IF NOT EXISTS roster_snapshots (
    snapshot_id    INTEGER PRIMARY KEY DEFAULT nextval('seq_roster_snapshots'),
    league_id      INTEGER NOT NULL,
    season_id      INTEGER,
    fetched_at     TIMESTAMP NOT NULL,
    source         VARCHAR NOT NULL,
    raw_path       VARCHAR NOT NULL,
    sha256         VARCHAR NOT NULL,
    matchday       INTEGER,
    matchday_start TIMESTAMP,
    team_count     INTEGER NOT NULL,
    teams          JSON NOT NULL,
    row_count      INTEGER NOT NULL,
    UNIQUE (league_id, sha256)
);
CREATE TABLE IF NOT EXISTS rosters (
    snapshot_id INTEGER NOT NULL,
    team_id     INTEGER NOT NULL,
    team_name   VARCHAR NOT NULL,
    owner       VARCHAR,
    player_id   INTEGER NOT NULL,
    cost        INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, team_id, player_id)
);
CREATE SEQUENCE IF NOT EXISTS seq_lineup_runs START 1;
CREATE TABLE IF NOT EXISTS lineup_runs (
    lineup_run_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_lineup_runs'),
    season_id         INTEGER NOT NULL,
    giornata          INTEGER NOT NULL,
    run_id            VARCHAR NOT NULL,
    model_hash        VARCHAR NOT NULL,
    probabili_file_id INTEGER NOT NULL,
    deadline          TIMESTAMP NOT NULL,
    written_at        TIMESTAMP NOT NULL,
    late              BOOLEAN NOT NULL,
    my_team           INTEGER,
    module            VARCHAR,
    xi                JSON,
    module_scores     JSON,
    predictions       INTEGER NOT NULL
);
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
    PRIMARY KEY (lineup_run_id, player_id)
);
```

And these views, after `v_valuation_prices_current`:

```sql
CREATE OR REPLACE VIEW v_probabili_files_current AS
    SELECT f.* FROM probabili_files f
    WHERE f.file_id = (SELECT max(g.file_id) FROM probabili_files g
                       WHERE g.season_id = f.season_id AND g.giornata = f.giornata);
CREATE OR REPLACE VIEW v_probabili_current AS
    SELECT p.* FROM probabili p
    WHERE p.file_id IN (SELECT file_id FROM v_probabili_files_current);
CREATE OR REPLACE VIEW v_rosters_current AS
    SELECT r.*, s.league_id, s.season_id, s.fetched_at, s.matchday, s.matchday_start
    FROM rosters r JOIN roster_snapshots s USING (snapshot_id)
    WHERE r.snapshot_id = (SELECT max(snapshot_id) FROM roster_snapshots);
CREATE OR REPLACE VIEW v_rosters_first AS
    SELECT r.*, s.league_id, s.season_id, s.fetched_at
    FROM rosters r JOIN roster_snapshots s USING (snapshot_id)
    WHERE r.snapshot_id IN (SELECT min(snapshot_id) FROM roster_snapshots
                            WHERE row_count > 0 GROUP BY league_id, season_id);
CREATE OR REPLACE VIEW v_market_prices AS
    SELECT f.league_id, f.season_id, f.snapshot_id, f.team_id, f.team_name, f.player_id, f.cost AS paid,
           p.run_id, p.scenario, p.role_class, p.expected_price, p.max_p50,
           v.name, v.classic_role, v.quot_mantra
    FROM v_rosters_first f
    JOIN valuation_runs vr ON vr.season_id = f.season_id
    JOIN valuation_prices p ON p.run_id = vr.run_id AND p.player_id = f.player_id
    LEFT JOIN valuations v ON v.run_id = p.run_id AND v.player_id = f.player_id;
CREATE OR REPLACE VIEW v_lineup_runs_current AS
    SELECT l.* FROM lineup_runs l
    WHERE NOT l.late AND l.lineup_run_id = (SELECT max(m.lineup_run_id) FROM lineup_runs m
                                            WHERE m.season_id = l.season_id AND m.giornata = l.giornata
                                              AND NOT m.late);
```

- [ ] **Step 4: Run the schema suite**

`uv run pytest core/tests/test_schema.py -c core/pyproject.toml -q` — expected all PASS. Then `uv run poe test-core` — nothing else may break (the DDL is additive).

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/db/schema.py core/tests/test_schema.py
git commit -m "feat(schema): version 4 -- probabili, rosters, lineup_runs and predictions, with their views"
```

---

### Task 3: The probabili adapter — parse the page, record a file

**Files:**
- Create: `core/src/fantaclaude/ingest/probabili.py`
- Modify: `core/tests/conftest.py` (add `seed_probabili`)
- Test: `core/tests/test_probabili.py`

**Interfaces:**
- Consumes: `probabili_sample.html` (Task 1); `probabili_files`/`probabili` (Task 2); `RawStore`, `fetch_bytes` (`ingest/raw.py`, `ingest/http.py`).
- Produces:
  - `ProbabiliRow(player_id: int, name: str, club_slug: str, formation: str | None, p_start: int, bench: bool, updated_at: datetime | None, raw: dict)`
  - `ProbabiliPage(rows: list[ProbabiliRow], matches: int, uncompiled: int, giornata: int | None, duplicates: int)`
  - `parse_probabili_page(html_text: str) -> ProbabiliPage` — raises `ProbabiliShapeError` (a `ValueError`, so `_source_errors` maps it to exit 1)
  - `async fetch_probabili(http, store: RawStore, *, label: str) -> RawFile`
  - `record_probabili(con, season_id: int, giornata: int, page: ProbabiliPage, raw: RawFile) -> ProbabiliIngestResult` with `.to_dict()` keys `file_id, season_id, giornata, inserted, skipped_duplicate, matches, uncompiled, unknown_players, duplicates, sha256, raw_path`
  - conftest `seed_probabili(con, season_id, giornata, rows) -> file_id`, rows `(player_id, name, club_slug, p_start)`

- [ ] **Step 1: The failing tests**

`core/tests/test_probabili.py`. The three values marked `# from the fixture` are read off `probabili_sample.html` once (first player's id, name and percentage; the two stamps) — assert those literal values, they are what pins the parser to the page:

```python
import re
from datetime import UTC, datetime

import pytest
from conftest import FIXTURE_DIR
from fantaclaude.ingest.probabili import (
    SOURCE,
    ProbabiliShapeError,
    parse_probabili_page,
    record_probabili,
)
from fantaclaude.ingest.raw import RawFile

SAMPLE = (FIXTURE_DIR / "probabili_sample.html").read_text(encoding="utf-8")


def test_parse_reads_every_player_with_his_listone_id_and_percentage():
    page = parse_probabili_page(SAMPLE)
    assert page.matches == 2 and page.uncompiled == 0 and page.duplicates == 0
    clubs = {r.club_slug for r in page.rows}
    assert len(clubs) == 4
    assert all(0 <= r.p_start <= 100 for r in page.rows)
    assert all(isinstance(r.player_id, int) and r.name for r in page.rows)
    assert all(r.updated_at is not None and r.updated_at.tzinfo is UTC for r in page.rows)
    assert {r.bench for r in page.rows} == {True, False}          # starters and panchina both listed
    first = page.rows[0]
    assert (first.player_id, first.name, first.p_start) == (0, "", 0)   # from the fixture: replace with its first player
    assert sorted({r.updated_at for r in page.rows}) == [datetime(2026, 9, 4, 9, 5, tzinfo=UTC),  # from the fixture
                                                         datetime(2026, 9, 4, 9, 5, tzinfo=UTC)]  # from the fixture


def test_parse_carries_each_clubs_formation_as_context():
    page = parse_probabili_page(SAMPLE)
    by_club = {r.club_slug: r.formation for r in page.rows}
    assert all(f and re.fullmatch(r"\d{3,4}", f) for f in by_club.values())


def test_an_uncompiled_match_is_skipped_and_counted_not_fatal():
    # strip every player of the second match: the page still has two match headers
    page = parse_probabili_page(SAMPLE)
    second = {r.club_slug for r in page.rows if r.updated_at == max(x.updated_at for x in page.rows)}
    text = SAMPLE
    for slug in second:
        text = re.sub(rf'<li[^>]*player-item[^>]*>(?:(?!</li>).)*?/serie-a/squadre/{slug}/(?:(?!</li>).)*?</li>', "", text, flags=re.S)
    stripped = parse_probabili_page(text)
    assert stripped.matches == 1 and stripped.uncompiled == 1
    assert {r.club_slug for r in stripped.rows} == {r.club_slug for r in page.rows} - second


def test_a_page_without_players_fails_loud_and_names_the_selector():
    with pytest.raises(ProbabiliShapeError, match="player-item"):
        parse_probabili_page("<html><body><p>Probabili formazioni</p></body></html>")


def test_a_percentage_that_is_not_a_number_fails_loud():
    text = SAMPLE.replace('aria-valuenow="', 'aria-valuenow="x', 1)
    with pytest.raises(ProbabiliShapeError, match="aria-valuenow"):
        parse_probabili_page(text)


def _raw(tmp_path, text: str, stamp: str = "1") -> RawFile:
    path = tmp_path / f"probabili-{stamp}.html"
    path.write_text(text, encoding="utf-8")
    return RawFile(path, f"sha-{stamp}", datetime(2026, 9, 4, 12, 0, tzinfo=UTC), "probabili")


def test_record_appends_a_file_and_its_rows_and_dedupes_on_bytes(db, tmp_path):
    page = parse_probabili_page(SAMPLE)
    first = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE))
    assert not first.skipped_duplicate and first.inserted == len(page.rows) and first.matches == 2
    assert first.unknown_players == len(page.rows)               # no listone in this database: every id unknown
    assert db.execute("SELECT source, row_count FROM probabili_files").fetchone() == (SOURCE, len(page.rows))
    again = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE))
    assert again.skipped_duplicate and again.file_id == first.file_id and again.inserted == 0
    later = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE, stamp="2"))
    assert later.file_id != first.file_id                         # a Friday re-compilation is a later file
    assert db.execute("SELECT file_id FROM v_probabili_files_current WHERE giornata = 3").fetchone()[0] == later.file_id
    assert db.execute("SELECT count(*) FROM v_probabili_current").fetchone()[0] == len(page.rows)


def test_record_resolves_team_short_from_the_listone(db, tmp_path, fixture_json):
    from fantaclaude.ingest.listone_api import load_listone, record_listone
    from fantaclaude.ingest.raw import RawFile as RF
    listone = fixture_json("listone_sample")
    path = tmp_path / "listone.json"
    path.write_text(__import__("json").dumps(listone), encoding="utf-8")
    record_listone(db, load_listone(path), RF(path, "sha-listone", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    page = parse_probabili_page(SAMPLE)
    known = {r[0] for r in db.execute("SELECT player_id FROM v_players_current").fetchall()}
    result = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE))
    assert result.unknown_players == sum(1 for r in page.rows if r.player_id not in known)
    resolved = db.execute("SELECT count(*) FROM probabili WHERE team_short IS NOT NULL").fetchone()[0]
    assert resolved == len(page.rows) - result.unknown_players
```

If `record_listone`'s signature differs from what `test_listone.py` shows, follow `test_listone.py`.

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_probabili.py -c core/pyproject.toml -q` — expected: ImportError on `fantaclaude.ingest.probabili`.

- [ ] **Step 3: The module**

`core/src/fantaclaude/ingest/probabili.py`. Set the four constants from Task 1 Step 2 before running the tests; the defaults below are what the 2026-09-04 observation suggested and are guesses until the capture confirms them.

```python
"""The probabili formazioni page: every player's published probability of
playing, keyed by the listone id in his link (spec, "The news adapter").

Observed 2026-09-04 on one anonymous request: the page is public and carries
all ten matches of the next giornata. Each player is an `li.player-item`
whose `aria-valuenow` is the percentage (90, 55, 35, 5, 1 -- starters and
bench alike); his link is `/serie-a/squadre/<club>/<name>/<id>` and `<id>`
is the listone id; each club's predicted module rides on `data-formation`;
each match carries its own `Ultimo aggiornamento dd/mm/yyyy - HH:MM` in
Rome time. The constants below pin what the capture showed; a page that no
longer matches fails loud (`ProbabiliShapeError`), never silently.

A match that is not yet compiled -- a card with no player list -- is skipped
and counted, not fatal: Tuesday's page is legitimately half empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.timeutil import to_db

SOURCE = "fantacalcio.it:/probabili-formazioni-serie-a"
URL = "https://www.fantacalcio.it/probabili-formazioni-serie-a"
ROME = ZoneInfo("Europe/Rome")

# Pinned against captured/probabili-2026-27-giornata-3.html (Task 1). Change
# them only with a new capture and a regenerated fixture, never by guess.
PLAYER_CLASS = "player-item"                                   # the li that carries aria-valuenow
BENCH_CLASS_RE = re.compile(r"bench|panch|riserv", re.I)        # the container of the panchina list
STAMP_BEFORE_LISTS = True                                      # "Ultimo aggiornamento" precedes the two lists
PLAYER_HREF = re.compile(r"^/serie-a/squadre/(?P<club>[^/]+)/(?P<slug>[^/]+)/(?P<id>\d+)/?$")
CLUB_HREF = re.compile(r"^/serie-a/squadre/(?P<club>[^/]+)/?$")
STAMP_RE = re.compile(r"Ultimo aggiornamento\s*:?\s*(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{1,2}):(\d{2})")
GIORNATA_RE = re.compile(r"(\d{1,2})\s*[ªa°]\s*giornata", re.I)
VOID_TAGS = frozenset({"meta", "img", "br", "input", "link", "hr", "source"})


class ProbabiliShapeError(ValueError):
    """The page is not the probabili page this adapter was written against."""


@dataclass(frozen=True)
class ProbabiliRow:
    player_id: int
    name: str
    club_slug: str
    formation: str | None
    p_start: int
    bench: bool
    updated_at: datetime | None          # aware UTC
    raw: dict[str, Any]


@dataclass(frozen=True)
class ProbabiliPage:
    rows: list[ProbabiliRow]
    matches: int                         # compiled: at least one player listed
    uncompiled: int
    giornata: int | None                 # when the page names it in text
    duplicates: int                      # a player listed twice: the first stands


class _Parser(HTMLParser):
    """A flat event stream in document order: formation, club header, player, stamp.
    Grouping into matches is done afterwards, on the stream, not in the parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, Any]] = []
        self.text: list[str] = []
        self._stack: list[tuple[str, bool, bool]] = []      # (tag, marks_bench, is_player)
        self._player: dict[str, Any] | None = None
        self._buffer = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=True)

    def _open(self, tag: str, a: dict[str, str | None], *, void: bool) -> None:
        classes = str(a.get("class") or "").split()
        formation = a.get("data-formation")
        if formation:
            self.events.append(("formation", str(formation)))
        href = str(a.get("href") or "")
        club = CLUB_HREF.match(href)
        if club and self._player is None:
            self.events.append(("club", club.group("club")))
        is_player = PLAYER_CLASS in classes
        marks_bench = any(BENCH_CLASS_RE.search(c) for c in classes)
        if is_player:
            self._player = {"p": a.get("aria-valuenow"), "href": None, "name": "",
                            "bench": marks_bench or any(b for _, b, _ in self._stack)}
        elif self._player is not None:
            if self._player["p"] is None and a.get("aria-valuenow") is not None:
                self._player["p"] = a.get("aria-valuenow")
            if tag == "a" and PLAYER_HREF.match(href):
                self._player["href"] = href
        if not void:
            self._stack.append((tag, marks_bench, is_player))

    def handle_endtag(self, tag: str) -> None:
        while self._stack:
            open_tag, _, was_player = self._stack.pop()
            if was_player and self._player is not None:
                self.events.append(("player", self._player))
                self._player = None
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._player is not None:
            self._player["name"] += data
        self._buffer = (self._buffer + " " + data)[-160:]
        found = STAMP_RE.search(self._buffer)
        if found:
            day, month, year, hour, minute = (int(x) for x in found.groups())
            self.events.append(("stamp", datetime(year, month, day, hour, minute, tzinfo=ROME).astimezone(UTC)))
            self._buffer = ""


def parse_probabili_page(html_text: str) -> ProbabiliPage:
    parser = _Parser()
    parser.feed(html_text)
    if not any(kind == "player" for kind, _ in parser.events):
        raise ProbabiliShapeError(f"no li.{PLAYER_CLASS} on the page -- the probabili layout changed")
    header_clubs = {slug for kind, slug in parser.events if kind == "club"}
    matches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    formations: dict[str, str] = {}
    pending_formation: str | None = None

    def new_match(stamp: datetime | None) -> dict[str, Any]:
        match = {"stamp": stamp, "clubs": [], "players": []}
        matches.append(match)
        return match

    for kind, payload in parser.events:
        if kind == "formation":
            pending_formation = payload
        elif kind == "stamp":
            if STAMP_BEFORE_LISTS:
                if current is None or current["players"]:
                    current = new_match(payload)
                else:
                    current["stamp"] = payload
            else:
                if current is None:
                    current = new_match(payload)
                else:
                    current["stamp"] = payload
                    current = None
        elif kind == "player":
            href = payload["href"]
            if not href:
                raise ProbabiliShapeError(f"a {PLAYER_CLASS} without a player link ({payload['name'].strip()[:40]!r})")
            link = PLAYER_HREF.match(href)
            club = link.group("club")
            if current is None or (club not in current["clubs"] and len(current["clubs"]) == 2):
                current = new_match(None)
            if club not in current["clubs"]:
                current["clubs"].append(club)
                if pending_formation is not None:
                    formations[club] = pending_formation
                    pending_formation = None
            if payload["p"] is None:
                raise ProbabiliShapeError(f"player {href} carries no aria-valuenow")
            try:
                p_start = int(str(payload["p"]))
            except ValueError:
                raise ProbabiliShapeError(f"aria-valuenow {payload['p']!r} on {href} is not an integer") from None
            if not 0 <= p_start <= 100:
                raise ProbabiliShapeError(f"aria-valuenow {p_start} on {href} is not a percentage")
            current["players"].append((club, int(link.group("id")), " ".join(payload["name"].split()), p_start,
                                       bool(payload["bench"]), href))
    rows: list[ProbabiliRow] = []
    seen: set[int] = set()
    duplicates = 0
    for match in matches:
        stamp = match["stamp"]
        for club, player_id, name, p_start, bench, href in match["players"]:
            if player_id in seen:
                duplicates += 1
                continue
            seen.add(player_id)
            rows.append(ProbabiliRow(player_id, name, club, formations.get(club), p_start, bench, stamp,
                                     {"href": href, "clubs": list(match["clubs"]),
                                      "stamp": stamp.isoformat() if stamp else None}))
    compiled = sum(1 for m in matches if m["players"])
    total = max(len(header_clubs) // 2, compiled)
    named = GIORNATA_RE.search(" ".join(parser.text))
    return ProbabiliPage(rows, compiled, total - compiled, int(named.group(1)) if named else None, duplicates)


async def fetch_probabili(http: httpx.AsyncClient, store: RawStore, *, label: str) -> RawFile:
    data = await fetch_bytes(http, URL)
    return store.write_bytes("probabili", data, ext="html", label=label)


@dataclass(frozen=True)
class ProbabiliIngestResult:
    file_id: int
    season_id: int
    giornata: int
    inserted: int
    skipped_duplicate: bool
    matches: int
    uncompiled: int
    unknown_players: int
    duplicates: int
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"file_id": self.file_id, "season_id": self.season_id, "giornata": self.giornata,
                "inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate, "matches": self.matches,
                "uncompiled": self.uncompiled, "unknown_players": self.unknown_players,
                "duplicates": self.duplicates, "sha256": self.sha256, "raw_path": self.raw_path}


def record_probabili(con: duckdb.DuckDBPyConnection, season_id: int, giornata: int, page: ProbabiliPage,
                     raw: RawFile) -> ProbabiliIngestResult:
    """Append one file row and its player rows; the same bytes for the same
    giornata is a no-op. A later fetch is a later file: v_probabili_current
    picks the newest, and nothing is overwritten."""
    existing = con.execute("SELECT file_id FROM probabili_files WHERE season_id = ? AND giornata = ? AND sha256 = ?",
                           [season_id, giornata, raw.sha256]).fetchone()
    if existing is not None:
        return ProbabiliIngestResult(existing[0], season_id, giornata, 0, True, page.matches, page.uncompiled, 0,
                                     page.duplicates, raw.sha256, str(raw.path))
    known = {int(pid): short for pid, short in con.execute(
        "SELECT player_id, team_short FROM v_players_current").fetchall()}
    unknown = sum(1 for r in page.rows if r.player_id not in known)
    con.begin()
    try:
        file_id = con.execute(
            "INSERT INTO probabili_files (season_id, giornata, fetched_at, source, raw_path, sha256, row_count, matches, "
            "uncompiled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
            [season_id, giornata, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, len(page.rows),
             page.matches, page.uncompiled]).fetchone()[0]
        con.executemany(
            "INSERT INTO probabili VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[file_id, season_id, giornata, r.player_id, r.name, r.club_slug, known.get(r.player_id), r.formation,
              r.p_start, r.bench, to_db(r.updated_at) if r.updated_at else None, json.dumps(r.raw, ensure_ascii=False)]
             for r in page.rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return ProbabiliIngestResult(file_id, season_id, giornata, len(page.rows), False, page.matches, page.uncompiled,
                                 unknown, page.duplicates, raw.sha256, str(raw.path))
```

- [ ] **Step 4: The conftest seed**

Append to `core/tests/conftest.py`, after `seed_advanced`:

```python
def seed_probabili(con, season_id: int, giornata: int, rows) -> int:
    """One synthetic probabili file. `rows` are (player_id, name, club_slug, p_start)."""
    from uuid import uuid4
    file_id = con.execute(
        "INSERT INTO probabili_files (season_id, giornata, fetched_at, source, raw_path, sha256, row_count, matches, uncompiled) "
        "VALUES (?, ?, now(), 'seed', ?, ?, ?, 1, 0) RETURNING file_id",
        [season_id, giornata, f"seed/prob-{season_id}-{giornata}", f"seed-prob-{uuid4().hex[:8]}", len(rows)]).fetchone()[0]
    for player_id, name, club, p_start in rows:
        con.execute("INSERT INTO probabili VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, false, NULL, '{}')",
                    [file_id, season_id, giornata, player_id, name, club, p_start])
    return file_id
```

- [ ] **Step 5: Run, iterate against the capture, expect green**

`uv run pytest core/tests/test_probabili.py -c core/pyproject.toml -q`. If the first test fails on a structural assertion (four clubs, two stamps, both bench values), the constant it points at is wrong for this page: re-read the capture (Task 1 Step 2), fix the constant, re-run. Do not loosen the assertion.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/ingest/probabili.py core/tests/test_probabili.py core/tests/conftest.py
git commit -m "feat(ingest): the probabili adapter -- published p_start per player, keyed by the listone id"
```

---

### Task 4: `analysis/weekly.py` — the round, the forecast, the immutable write, the records

**Files:**
- Create: `core/src/fantaclaude/analysis/weekly.py`
- Modify: `core/src/fantaclaude/analysis/exports.py` (add `write_parquet`, use it in `export_records`)
- Modify: `core/tests/conftest.py` (add `seed_fixtures`)
- Test: `core/tests/test_weekly.py`

**Interfaces:**
- Consumes: `v_fixtures_current`, `valuations`, `probabili`, `lineup_runs`, `predictions` (Task 2); `seed_probabili` (Task 3).
- Produces:
  - `class ForecastError(RuntimeError)` (the CLI maps it to exit 3), `class LateForecast(ForecastError)` (exit 4)
  - `Round(season_id, giornata, first_kickoff: datetime, last_kickoff: datetime, matches: int)` — naive UTC, as stored; `.to_dict()`
  - `target_round(con, now, *, season_id, giornata=None) -> Round`
  - `ForecastRow(player_id, name, team_short, classic_role, roles: tuple[str, ...], p_start_published: int | None, p_start: float, fv_if_plays: float, fv_sd: float | None, expected_points: float, source: str)`; `.to_dict()`
  - `newest_probabili_file(con, season_id, giornata) -> tuple[int, datetime, int, int] | None` — `(file_id, fetched_at, row_count, matches)`
  - `forecast(con, *, run_id, probabili_file_id) -> list[ForecastRow]`
  - `write_lineup_run(con, *, round_, run_id, model_hash, probabili_file_id, rows, now, late, my_team=None, module=None, xi=None, module_scores=None) -> int`
  - `export_lineup_records(con, lineup_run_id, records_dir) -> list[Path]`
  - `exports.write_parquet(con, query: str, path: Path) -> bool` (False when the file already exists)
  - conftest `seed_fixtures(con, season_id, rounds: dict[int, list[datetime]]) -> snapshot_id` — one Serie A snapshot holding every giornata given

- [ ] **Step 1: The failing tests**

`core/tests/test_weekly.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from conftest import seed_fixtures, seed_probabili
from fantaclaude.analysis.weekly import (
    ForecastError,
    LateForecast,
    Round,
    export_lineup_records,
    forecast,
    newest_probabili_file,
    target_round,
    write_lineup_run,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
G3 = [datetime(2026, 9, 4, 18, 45, tzinfo=UTC), datetime(2026, 9, 5, 16, 0, tzinfo=UTC), datetime(2026, 9, 7, 18, 45, tzinfo=UTC)]
G4 = [datetime(2026, 9, 11, 18, 45, tzinfo=UTC), datetime(2026, 9, 14, 18, 45, tzinfo=UTC)]


def _run(db, run_id="20260904T090510Z-7694bd6a", players=((2764, "Martinez L.", "INT", "A", ["Pc"], 8.1),
                                                         (5841, "Svilar", "ROM", "P", ["Por"], 5.6),
                                                         (2640, "Kolasinac", "ATA", "D", ["Ds", "Dc"], 6.0))):
    db.execute("INSERT INTO valuation_runs VALUES (?, ?, 'r', 'm3', 'i', 1, 1, 21, 2, ['balanced'], '{}', '{}')",
               [run_id, datetime(2026, 9, 4, 9, 5)])
    for pid, name, short, role, roles, fm in players:
        db.execute("INSERT INTO valuations VALUES (?, ?, ?, ?, ?, ?, ?, 30.0, ?, 6.2, 10, 12, 14, 5.0, 7.0, 1, 20, NULL, NULL, '{}')",
                   [run_id, pid, name, short, role, roles[0], roles, fm])
    return run_id


def test_target_round_is_the_first_giornata_whose_last_kickoff_is_ahead(db):
    seed_fixtures(db, 21, {3: G3, 4: G4})
    r = target_round(db, NOW, season_id=21)
    assert r == Round(21, 3, datetime(2026, 9, 4, 18, 45), datetime(2026, 9, 7, 18, 45), 3)
    assert target_round(db, datetime(2026, 9, 5, 10, 0, tzinfo=UTC), season_id=21).giornata == 3   # in progress: still 3
    assert target_round(db, datetime(2026, 9, 8, 10, 0, tzinfo=UTC), season_id=21).giornata == 4
    assert target_round(db, NOW, season_id=21, giornata=4).giornata == 4
    with pytest.raises(ForecastError, match="giornata 9"):
        target_round(db, NOW, season_id=21, giornata=9)
    with pytest.raises(ForecastError, match="kicked off"):
        target_round(db, datetime(2026, 9, 20, tzinfo=UTC), season_id=21)


def test_target_round_needs_a_calendar(db):
    with pytest.raises(ForecastError, match="ingest calendar"):
        target_round(db, NOW, season_id=21)


def test_forecast_joins_the_page_to_the_run_for_every_listed_priced_player(db):
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90), (5841, "Svilar", "roma", 55), (777777, "Nobody", "roma", 5)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    assert [r.player_id for r in rows] == [2764, 5841]                # the unpriced id is not a row; Kolasinac unlisted is not a row
    lautaro = rows[0]
    assert lautaro.p_start_published == 90 and lautaro.p_start == pytest.approx(0.9)
    assert lautaro.fv_if_plays == pytest.approx(8.1) and lautaro.expected_points == pytest.approx(0.9 * 8.1)
    assert lautaro.fv_sd is None and lautaro.source == "published" and lautaro.roles == ("Pc",)
    assert newest_probabili_file(db, 21, 3)[0] == file_id and newest_probabili_file(db, 21, 4) is None


def test_write_refuses_after_the_first_kickoff_unless_late_and_marks_the_row(db, tmp_path):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    r = target_round(db, NOW, season_id=21)
    first = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    after = datetime(2026, 9, 4, 19, 0, tzinfo=UTC)
    with pytest.raises(LateForecast, match="--late"):
        write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=after, late=False)
    second = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=after, late=True)
    assert second != first
    assert db.execute("SELECT late, deadline FROM lineup_runs ORDER BY lineup_run_id").fetchall() == \
        [(False, datetime(2026, 9, 4, 18, 45)), (True, datetime(2026, 9, 4, 18, 45))]
    assert db.execute("SELECT lineup_run_id FROM v_lineup_runs_current").fetchall() == [(first,)]
    assert db.execute("SELECT p_start_published, p_start, expected_points, source FROM predictions WHERE lineup_run_id = ?",
                      [first]).fetchone() == (90, pytest.approx(0.9), pytest.approx(0.9 * 8.1), "published")
    # --late before the deadline is not late: the flag permits, the clock decides
    third = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=True)
    assert db.execute("SELECT late FROM lineup_runs WHERE lineup_run_id = ?", [third]).fetchone() == (False,)
    assert db.execute("SELECT lineup_run_id FROM v_lineup_runs_current").fetchall() == [(third,)]


def test_a_second_run_before_the_deadline_is_a_second_row_and_nothing_is_touched(db):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    r = target_round(db, NOW, season_id=21)
    a = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    b = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW + timedelta(hours=1), late=False)
    assert db.execute("SELECT count(*) FROM lineup_runs").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM predictions").fetchone()[0] == 2
    assert db.execute("SELECT written_at FROM lineup_runs WHERE lineup_run_id = ?", [a]).fetchone()[0] == datetime(2026, 9, 4, 12, 0)
    assert b > a


def test_write_refuses_an_empty_forecast(db):
    seed_fixtures(db, 21, {3: G3})
    r = target_round(db, NOW, season_id=21)
    with pytest.raises(ForecastError, match="nothing to forecast"):
        write_lineup_run(db, round_=r, run_id="x", model_hash="m", probabili_file_id=1, rows=[], now=NOW, late=False)


def test_records_are_exported_once_by_giornata_and_write_time(db, tmp_path):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    lineup_run_id = write_lineup_run(db, round_=target_round(db, NOW, season_id=21), run_id=run_id, model_hash="m3",
                                     probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    written = export_lineup_records(db, lineup_run_id, tmp_path / "records")
    assert [p.relative_to(tmp_path / "records").as_posix() for p in written] == \
        ["lineup_runs/21-03-20260904T120000Z.parquet", "predictions/21-03-20260904T120000Z.parquet"]
    assert export_lineup_records(db, lineup_run_id, tmp_path / "records") == []          # never rewritten
    assert db.execute("SELECT count(*) FROM read_parquet(?)", [str(written[1])]).fetchone()[0] == 1
```

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_weekly.py -c core/pyproject.toml -q` — ImportError.

- [ ] **Step 3: `write_parquet` in exports.py**

Replace the loop body of `export_records` with the helper, keeping its behaviour:

```python
def write_parquet(con: duckdb.DuckDBPyConnection, query: str, path: Path) -> bool:
    """COPY `query` to `path` as parquet unless the file exists; records are never rewritten."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({query}) TO {_literal(path.as_posix())} (FORMAT PARQUET)")
    return True
```

and in `export_records`: `written = [path for path, query in targets if write_parquet(con, query, path)]`.

- [ ] **Step 4: The module**

`core/src/fantaclaude/analysis/weekly.py`:

```python
"""The weekly forecast (spec, "`fanta-manager` -- the weekly loop", Phase 3a).

The round and its deadline are read off `fixtures`, never off the stored
`status.mday`, which only moves when the rules do. A forecast row is the
published `p_start` (a probability of receiving a voto) times the pinned
run's per-presenza `exp_fantamedia`, for every player the page lists and the
run prices. The write is refused once the giornata's first kickoff has
passed unless the caller says `late`, and then the row says so; several
writes before one deadline are several rows, and `v_lineup_runs_current`
is the latest non-late one. Nothing here updates or deletes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.exports import write_parquet
from fantaclaude.timeutil import to_db


class ForecastError(RuntimeError):
    """A forecast cannot be written from what is on disk (no calendar, no page, no run)."""


class LateForecast(ForecastError):
    """The giornata has kicked off; a forecast written now is not a forecast."""


@dataclass(frozen=True)
class Round:
    season_id: int
    giornata: int
    first_kickoff: datetime          # naive UTC, as fixtures stores it
    last_kickoff: datetime
    matches: int

    def to_dict(self) -> dict[str, Any]:
        return {"season_id": self.season_id, "giornata": self.giornata,
                "first_kickoff": self.first_kickoff.isoformat(sep=" ", timespec="minutes"),
                "last_kickoff": self.last_kickoff.isoformat(sep=" ", timespec="minutes"), "matches": self.matches}


def target_round(con: duckdb.DuckDBPyConnection, now: datetime, *, season_id: int,
                 giornata: int | None = None) -> Round:
    """The giornata to forecast: the first whose last kickoff is still ahead
    (a giornata in progress is still the target -- and late), or the one asked for."""
    rows = con.execute(
        "SELECT giornata, min(kickoff), max(kickoff), count(*) FROM v_fixtures_current "
        "WHERE competition = 'SA' AND season_id = ? AND giornata IS NOT NULL AND kickoff IS NOT NULL "
        "GROUP BY giornata ORDER BY giornata", [season_id]).fetchall()
    if not rows:
        raise ForecastError(f"no Serie A fixtures for season {season_id} -- run `fantaclaude ingest calendar`")
    rounds = [Round(season_id, int(g), first, last, int(n)) for g, first, last, n in rows]
    if giornata is not None:
        for r in rounds:
            if r.giornata == giornata:
                return r
        raise ForecastError(f"giornata {giornata} is not in the season {season_id} calendar")
    when = to_db(now)
    for r in rounds:
        if r.last_kickoff > when:
            return r
    raise ForecastError(f"every giornata of season {season_id} has kicked off -- pass --giornata to write one late")


@dataclass(frozen=True)
class ForecastRow:
    player_id: int
    name: str
    team_short: str | None
    classic_role: str
    roles: tuple[str, ...]
    p_start_published: int | None
    p_start: float
    fv_if_plays: float
    fv_sd: float | None
    expected_points: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short,
                "classic_role": self.classic_role, "roles": list(self.roles),
                "p_start_published": self.p_start_published, "p_start": self.p_start,
                "fv_if_plays": self.fv_if_plays, "fv_sd": self.fv_sd, "expected_points": self.expected_points,
                "source": self.source}


def newest_probabili_file(con: duckdb.DuckDBPyConnection, season_id: int,
                          giornata: int) -> tuple[int, datetime, int, int] | None:
    row = con.execute("SELECT file_id, fetched_at, row_count, matches FROM probabili_files "
                      "WHERE season_id = ? AND giornata = ? ORDER BY file_id DESC LIMIT 1", [season_id, giornata]).fetchone()
    return None if row is None else (int(row[0]), row[1], int(row[2]), int(row[3]))


def forecast(con: duckdb.DuckDBPyConnection, *, run_id: str, probabili_file_id: int) -> list[ForecastRow]:
    """Every player the page lists and the run prices. 3a: p_start is the
    published number alone (`source: published`), fv_sd is null."""
    rows = con.execute(
        "SELECT v.player_id, v.name, v.team_short, v.classic_role, v.roles, v.exp_fantamedia, p.p_start "
        "FROM valuations v JOIN probabili p ON p.player_id = v.player_id "
        "WHERE v.run_id = ? AND p.file_id = ? ORDER BY v.player_id", [run_id, probabili_file_id]).fetchall()
    out: list[ForecastRow] = []
    for pid, name, short, role, roles, fm, published in rows:
        p_start = int(published) / 100.0
        out.append(ForecastRow(int(pid), str(name), short, str(role), tuple(roles), int(published), p_start,
                               float(fm), None, p_start * float(fm), "published"))
    return out


def write_lineup_run(con: duckdb.DuckDBPyConnection, *, round_: Round, run_id: str, model_hash: str,
                     probabili_file_id: int, rows: list[ForecastRow], now: datetime, late: bool,
                     my_team: int | None = None, module: str | None = None,
                     xi: list[dict[str, Any]] | None = None,
                     module_scores: dict[str, float | None] | None = None) -> int:
    """One lineup_runs row and its predictions, appended; refused after the
    first kickoff unless `late`, and then marked as such by the clock, not the flag."""
    written_at = to_db(now)
    is_late = written_at >= round_.first_kickoff
    if is_late and not late:
        raise LateForecast(
            f"giornata {round_.giornata} kicked off at {round_.first_kickoff:%Y-%m-%d %H:%M} UTC; a forecast written "
            f"now is not a forecast -- pass --late to write it marked, and calibration will exclude it")
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
            "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [[lineup_run_id, round_.season_id, round_.giornata, r.player_id, r.p_start_published, r.p_start,
              r.fv_if_plays, r.fv_sd, r.expected_points, r.source] for r in rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return int(lineup_run_id)


def export_lineup_records(con: duckdb.DuckDBPyConnection, lineup_run_id: int, records_dir: Path) -> list[Path]:
    """records/lineup_runs/<season>-<giornata>-<written_at>.parquet and the same under predictions/, once."""
    season, giornata, written = con.execute(
        "SELECT season_id, giornata, written_at FROM lineup_runs WHERE lineup_run_id = ?", [lineup_run_id]).fetchone()
    stem = f"{season}-{giornata:02d}-{written:%Y%m%dT%H%M%SZ}"
    targets = [(records_dir / "lineup_runs" / f"{stem}.parquet",
                f"SELECT * FROM lineup_runs WHERE lineup_run_id = {int(lineup_run_id)}"),
               (records_dir / "predictions" / f"{stem}.parquet",
                f"SELECT * FROM predictions WHERE lineup_run_id = {int(lineup_run_id)}")]
    return [path for path, query in targets if write_parquet(con, query, path)]
```

- [ ] **Step 5: `seed_fixtures` in conftest**

```python
def seed_fixtures(con, season_id: int, rounds) -> int:
    """One Serie A calendar snapshot. `rounds` maps giornata -> list of kickoffs (aware UTC)."""
    from uuid import uuid4

    from fantaclaude.timeutil import to_db
    n = sum(len(k) for k in rounds.values())
    snapshot_id = con.execute(
        "INSERT INTO fixture_snapshots (competition, season_id, fetched_at, source, raw_paths, sha256, row_count) "
        "VALUES ('SA', ?, now(), 'seed', [], ?, ?) RETURNING snapshot_id",
        [season_id, f"seed-fix-{uuid4().hex[:8]}", n]).fetchone()[0]
    for giornata, kickoffs in rounds.items():
        for i, kickoff in enumerate(kickoffs):
            con.execute("INSERT INTO fixtures VALUES (?, 'SA', ?, ?, ?, ?, NULL, ?, 'Home', 'Away', NULL, NULL, '{}')",
                        [snapshot_id, season_id, f"seed-{giornata}-{i}", str(giornata), giornata, to_db(kickoff)])
    return snapshot_id
```

- [ ] **Step 6: Run, expect green; then the whole suite**

`uv run pytest core/tests/test_weekly.py core/tests/test_rank_cli.py -c core/pyproject.toml -q` (the second covers `export_records`).

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/analysis/weekly.py core/src/fantaclaude/analysis/exports.py core/tests/test_weekly.py core/tests/conftest.py
git commit -m "feat(weekly): the round off the calendar, the forecast join, the write refused after kickoff, records"
```

---

### Task 5: The CLI — `ingest probabili` and `lineup` (forecast path)

**Files:**
- Modify: `core/src/fantaclaude/analysis/weekly.py` (add `LineupReport`, `lineup()`)
- Modify: `core/src/fantaclaude/cli/app.py` (two commands, two renderers)
- Test: `core/tests/test_lineup_cli.py`

**Interfaces:**
- Consumes: Tasks 3 and 4; `newest_run_id` (`asta/pinned.py`); `_league_yml_or_exit`, `_seasons_or_exit`, `_source_errors`, `emit` (`cli/app.py`).
- Produces:
  - `weekly.lineup(con, *, now, season_id, giornata, run_id, late, my_team, records_dir) -> LineupReport` — in this task `my_team` is accepted and ignored except for the reason string; Task 8 fills the XI.
  - `LineupReport.to_dict()` keys: `round, run_id, model_hash, page {file_id, fetched_at, players, matches, uncompiled}, late, top {classic_role: [row dicts]}, xi (None here), no_xi_reason, my_team, lineup_run_id, predictions, records, warnings`
  - `fantaclaude ingest probabili [--giornata N] [--json]`, `fantaclaude lineup [--giornata N] [--run ID] [--late] [--json]`

- [ ] **Step 1: The failing CLI tests**

`core/tests/test_lineup_cli.py`. The workspace helper `_workspace` (from `test_rank_cli`) seeds the 17-player listone and the league settings; `rank --offline` then writes a run. Seeding the calendar and a page happens straight in the workspace database:

```python
import json
from datetime import UTC, datetime, timedelta

import httpx
import respx
from conftest import FIXTURE_DIR, seed_fixtures, seed_probabili
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.db.connection import connect
from test_rank_cli import _workspace
from typer.testing import CliRunner

runner = CliRunner()
SAMPLE = (FIXTURE_DIR / "probabili_sample.html").read_text(encoding="utf-8")
PAGE = [(2764, "Martinez L.", "inter", 90), (5841, "Svilar", "roma", 100), (2640, "Kolasinac", "atalanta", 55),
        (2120, "Bastoni", "inter", 90), (254, "Dimarco", "inter", 75), (309, "Dybala", "roma", 35)]


def _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["rank", "--offline", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    return json.loads(result.stdout)["run_id"]


def _calendar(tmp_path, *, first: datetime):
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_fixtures(con, 21, {3: [first, first + timedelta(days=3)], 4: [first + timedelta(days=7)]})
    con.close()


def _page(tmp_path):
    con = connect(tmp_path / "data" / "fanta.duckdb")
    file_id = seed_probabili(con, 21, 3, PAGE)
    con.close()
    return file_id


def test_lineup_writes_the_forecast_for_every_listed_priced_player(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    run_id = _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    _page(tmp_path)
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["round"]["giornata"] == 3 and payload["run_id"] == run_id and payload["late"] is False
    assert payload["predictions"] == 6 and payload["xi"] is None and "my_team" in payload["no_xi_reason"]
    assert set(payload["top"]) == {"P", "D", "C", "A"} and payload["top"]["A"][0]["player_id"] == 2764
    assert [p.rsplit("/", 2)[-2] for p in payload["records"]] == ["lineup_runs", "predictions"]
    plain = runner.invoke(app, ["lineup"])
    assert plain.exit_code == ExitCode.OK and "XI: none" in plain.stdout and "6 predictions" in plain.stdout


def test_lineup_is_refused_after_kickoff_and_marked_with_late(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) - timedelta(hours=1))
    _page(tmp_path)
    refused = runner.invoke(app, ["lineup"])
    assert refused.exit_code == ExitCode.CONFLICT and "--late" in refused.stderr
    late = runner.invoke(app, ["lineup", "--late", "--json"])
    assert late.exit_code == ExitCode.OK, late.output
    assert json.loads(late.stdout)["late"] is True


def test_lineup_says_what_is_missing(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    no_calendar = runner.invoke(app, ["lineup"])
    assert no_calendar.exit_code == ExitCode.NOT_READY and "ingest calendar" in no_calendar.stderr
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    no_page = runner.invoke(app, ["lineup"])
    assert no_page.exit_code == ExitCode.NOT_READY and "ingest probabili" in no_page.stderr


@respx.mock
def test_ingest_probabili_fetches_once_and_records_under_the_calendars_giornata(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    route = respx.get("https://www.fantacalcio.it/probabili-formazioni-serie-a").mock(return_value=httpx.Response(200, text=SAMPLE))
    result = runner.invoke(app, ["ingest", "probabili", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert route.call_count == 1 and payload["giornata"] == 3 and payload["matches"] == 2 and not payload["skipped_duplicate"]
    assert list((tmp_path / "data" / "raw" / "probabili").glob("*-probabili-21-03.html"))
    again = runner.invoke(app, ["ingest", "probabili", "--json"])
    assert json.loads(again.stdout)["skipped_duplicate"] is True and route.call_count == 2
    plain = runner.invoke(app, ["ingest", "probabili", "--giornata", "4"])
    assert plain.exit_code == ExitCode.OK and "giornata 4" in plain.stdout


@respx.mock
def test_ingest_probabili_maps_a_changed_page_to_exit_1(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    respx.get("https://www.fantacalcio.it/probabili-formazioni-serie-a").mock(return_value=httpx.Response(200, text="<html></html>"))
    result = runner.invoke(app, ["ingest", "probabili"])
    assert result.exit_code == ExitCode.ERROR and "player-item" in result.stderr
```

If the sample page names its giornata (Task 1, question 5) and it is not 3, the `--giornata 4` assertion changes to expect exit 4 with "the page is giornata 3" instead; see `record`'s cross-check below.

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_lineup_cli.py -c core/pyproject.toml -q` — the `lineup` command does not exist (exit 2).

- [ ] **Step 3: `lineup()` and `LineupReport` in weekly.py**

Append to `analysis/weekly.py`:

```python
from fantaclaude.asta.pinned import newest_run_id          # at the top of the module, with the other imports

TOP_PER_ROLE = 8


@dataclass(frozen=True)
class LineupReport:
    round_: Round
    run_id: str
    model_hash: str
    page: dict[str, Any]
    late: bool
    rows: list[ForecastRow]
    xi: dict[str, Any] | None
    no_xi_reason: str | None
    my_team: int | None
    lineup_run_id: int
    records: list[Path]
    warnings: list[str]

    def top(self) -> dict[str, list[ForecastRow]]:
        by_role: dict[str, list[ForecastRow]] = {}
        for row in sorted(self.rows, key=lambda r: -r.expected_points):
            by_role.setdefault(row.classic_role, [])
            if len(by_role[row.classic_role]) < TOP_PER_ROLE:
                by_role[row.classic_role].append(row)
        return {role: by_role[role] for role in ("P", "D", "C", "A") if role in by_role}

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round_.to_dict(), "run_id": self.run_id, "model_hash": self.model_hash,
                "page": self.page, "late": self.late,
                "top": {role: [r.to_dict() for r in rows] for role, rows in self.top().items()},
                "xi": self.xi, "no_xi_reason": self.no_xi_reason, "my_team": self.my_team,
                "lineup_run_id": self.lineup_run_id, "predictions": len(self.rows),
                "records": [str(p) for p in self.records], "warnings": list(self.warnings)}


def lineup(con: duckdb.DuckDBPyConnection, *, now: datetime, season_id: int, giornata: int | None, run_id: str | None,
           late: bool, my_team: int | None, records_dir: Path) -> LineupReport:
    round_ = target_round(con, now, season_id=season_id, giornata=giornata)
    run_id = run_id or newest_run_id(con)
    if run_id is None:
        raise ForecastError("no valuation run to read projections from -- run `fantaclaude rank`")
    hashed = con.execute("SELECT model_hash FROM valuation_runs WHERE run_id = ?", [run_id]).fetchone()
    if hashed is None:
        raise ForecastError(f"run {run_id!r} is not in valuation_runs")
    page = newest_probabili_file(con, season_id, round_.giornata)
    if page is None:
        raise ForecastError(f"no probabili page for giornata {round_.giornata} -- run `fantaclaude ingest probabili`")
    file_id, fetched_at, players, matches = page
    uncompiled = con.execute("SELECT uncompiled FROM probabili_files WHERE file_id = ?", [file_id]).fetchone()[0]
    rows = forecast(con, run_id=run_id, probabili_file_id=file_id)
    warnings: list[str] = []
    if uncompiled:
        warnings.append(f"{uncompiled} match(es) of giornata {round_.giornata} not yet compiled on the page fetched "
                        f"{fetched_at:%Y-%m-%d %H:%M} UTC")
    xi, no_xi_reason, module, xi_rows, scores = None, None, None, None, None
    if my_team is None:
        no_xi_reason = "league.yml has no my_team leaf (asta verify-transfer prints it)"
    else:
        no_xi_reason = "the XI lands with Task 8"          # replaced in Task 8
    lineup_run_id = write_lineup_run(con, round_=round_, run_id=run_id, model_hash=str(hashed[0]),
                                     probabili_file_id=file_id, rows=rows, now=now, late=late, my_team=my_team,
                                     module=module, xi=xi_rows, module_scores=scores)
    is_late = bool(con.execute("SELECT late FROM lineup_runs WHERE lineup_run_id = ?", [lineup_run_id]).fetchone()[0])
    records = export_lineup_records(con, lineup_run_id, records_dir)
    return LineupReport(round_, run_id, str(hashed[0]),
                        {"file_id": file_id, "fetched_at": fetched_at.isoformat(sep=" ", timespec="minutes"),
                         "players": players, "matches": matches, "uncompiled": int(uncompiled)},
                        is_late, rows, xi, no_xi_reason, my_team, lineup_run_id, records, warnings)
```

- [ ] **Step 4: The two commands in `cli/app.py`**

After `ingest_calendar_cmd`:

```python
def _render_probabili(payload: dict) -> str:
    head = f"probabili {payload['season_id']} giornata {payload['giornata']}"
    if payload["skipped_duplicate"]:
        return f"{head}: duplicate of file {payload['file_id']} -- nothing new ({payload['raw_path']})"
    line = f"{head}: file {payload['file_id']}, {payload['inserted']} players over {payload['matches']} compiled match(es)"
    if payload["uncompiled"]:
        line += f", {payload['uncompiled']} not yet compiled"
    if payload["unknown_players"]:
        line += f"; {payload['unknown_players']} player ids not in the current listone"
    if payload["duplicates"]:
        line += f"; {payload['duplicates']} listed twice (first kept)"
    return f"{line} ({payload['raw_path']})"


GIORNATA_ONE_OPTION = typer.Option(None, "--giornata", help="The giornata (default: the next one on the calendar).")


@ingest_app.command("probabili")
def ingest_probabili_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = GIORNATA_ONE_OPTION,
) -> None:
    """The probabili formazioni page (fantacalcio.it, public): every player's published p_start for the next giornata. One request."""
    from fantaclaude.analysis.weekly import ForecastError, target_round
    from fantaclaude.commands.ingest import ensure_schema
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.probabili import fetch_probabili, parse_probabili_page, record_probabili
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir
    from fantaclaude.timeutil import utc_now

    ensure_schema()
    season_id = _seasons_or_exit(None)[-1]
    con = connect(read_only=True)                 # the round is a pre-read; the write lock must not span the request
    try:
        round_ = target_round(con, utc_now(), season_id=season_id, giornata=giornata)
    except ForecastError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    finally:
        con.close()
    store = RawStore(raw_dir())
    with _source_errors():
        raw = run_web(lambda http: fetch_probabili(http, store, label=f"{season_id}-{round_.giornata:02d}"))
        page = parse_probabili_page(raw.path.read_text(encoding="utf-8"))
        if page.giornata is not None and page.giornata != round_.giornata:
            typer.echo(f"the page is giornata {page.giornata}, not {round_.giornata} -- pass --giornata {page.giornata} "
                       f"if that is the round you want recorded", err=True)
            raise typer.Exit(code=ExitCode.CONFLICT)
        con = connect()
        try:
            apply_schema(con)
            result = record_probabili(con, season_id, round_.giornata, page, raw)
        finally:
            con.close()
    emit(result.to_dict(), json_=json_, render=_render_probabili)
```

After `rank_cmd`:

```python
def _render_lineup(payload: dict) -> str:
    r, page = payload["round"], payload["page"]
    lines = [f"giornata {r['giornata']} · deadline {r['first_kickoff']} UTC · run {payload['run_id']} · page {page['fetched_at']} "
             f"({page['players']} players, {page['matches']} compiled)"]
    if payload["late"]:
        lines.append("LATE: written after the first kickoff -- marked, and calibration will exclude it")
    for role, rows in payload["top"].items():
        lines.append(f"  {role}: " + " · ".join(
            f"{x['name']} {x['p_start_published']}%×{x['fv_if_plays']:.2f}={x['expected_points']:.2f}" for x in rows))
    xi = payload.get("xi")
    if xi is None:
        lines.append(f"XI: none -- {payload['no_xi_reason']}")
    else:
        lines.append(f"XI: {xi['module']} · expected {xi['total']:.2f}")
        lines += [f"  {s['slot']:<6} {s['name']} ({s['fit']}, {s['expected_points']:.2f})" for s in xi["slots"]]
        others = " · ".join(f"{m} {v:.2f}" if v is not None else f"{m} -"
                            for m, v in xi["module_scores"].items() if m != xi["module"])
        lines.append(f"  other modules: {others}")
    lines.append(f"written: lineup_run {payload['lineup_run_id']}, {payload['predictions']} predictions"
                 + (" · " + ", ".join(payload["records"]) if payload["records"] else " · records already exist"))
    lines += [f"warning: {w}" for w in payload["warnings"]]
    return "\n".join(lines)


LINEUP_RUN_OPTION = typer.Option(None, "--run", help="Read projections from this valuation run (default: the newest not superseded).")


@app.command("lineup")
def lineup_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = GIORNATA_ONE_OPTION,
    run: str | None = LINEUP_RUN_OPTION,
    late: bool = typer.Option(False, "--late", help="Write even though the giornata has kicked off; the row is marked and calibration excludes it."),
) -> None:
    """Write the giornata's forecast -- p_start x expected fantavoto for every player the probabili page lists -- and, when league.yml names my team, the XI and module that maximise expected points. Local, no network."""
    from fantaclaude.analysis.weekly import ForecastError, LateForecast, lineup
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.paths import records_dir
    from fantaclaude.timeutil import utc_now

    entries = _league_yml_or_exit()
    my_team: int | None = None
    if entries and "my_team" in entries:
        try:
            my_team = int(entries["my_team"].value)
        except (TypeError, ValueError):
            typer.echo("league.yml: my_team.value must be the lega team id (an integer)", err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
    season_id = _seasons_or_exit(None)[-1]
    con = connect()
    try:
        apply_schema(con)
        try:
            report = lineup(con, now=utc_now(), season_id=season_id, giornata=giornata, run_id=run, late=late,
                            my_team=my_team, records_dir=records_dir())
        except LateForecast as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.CONFLICT) from None
        except ForecastError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_lineup)
```

- [ ] **Step 5: Run, expect green, then the suite and lint**

`uv run pytest core/tests/test_lineup_cli.py -c core/pyproject.toml -q`, then `uv run poe test-core && uv run poe lint`.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/analysis/weekly.py core/src/fantaclaude/cli/app.py core/tests/test_lineup_cli.py
git commit -m "feat(cli): ingest probabili and lineup -- the giornata's forecast, refused after kickoff unless --late"
```

**Now run Task 13 steps 1–2 if it is still before 18:45 UTC on 2026-09-04.**

---

### Task 6: `modules.assign_weighted` — the exact max-weight assignment

**Files:**
- Modify: `core/src/fantaclaude/model/modules.py`
- Test: `core/tests/test_modules.py`

**Interfaces:**
- Consumes: `Module`, `Slot`, `Fit`, `Role` (existing).
- Produces: `assign_weighted(module: Module, roster: Sequence[frozenset[Role]], natural: Sequence[float], adapted: Sequence[float]) -> tuple[float, list[int]] | None` — the total and, per slot, the roster index; `None` when the module cannot be fielded. A player fielded ADAPTED contributes `adapted[i]`, NATURAL `natural[i]`; FORCED_ONLY and NO are never fielded.

- [ ] **Step 1: The failing tests**

Append to `core/tests/test_modules.py`:

```python
import itertools
import random

from fantaclaude.model.modules import Module, Slot, assign_weighted


def _brute(module, roster, natural, adapted):
    best = None
    for perm in itertools.permutations(range(len(roster)), len(module.slots)):
        total = 0.0
        for slot, i in zip(module.slots, perm):
            fit = slot.fit(roster[i])
            if fit is Fit.NATURAL:
                total += natural[i]
            elif fit is Fit.ADAPTED:
                total += adapted[i]
            else:
                break
        else:
            if best is None or total > best:
                best = total
    return best


SMALL = Module(code="t", label="test", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R({Role.B}), R({Role.Ds})),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("A/Pc", R({Role.A, Role.Pc}), R({Role.W}), R({Role.T}))))
POOL = [R({Role.Por}), R({Role.Dc}), R({Role.B}), R({Role.Ds}), R({Role.M}), R({Role.C, Role.T}),
        R({Role.T}), R({Role.W}), R({Role.A}), R({Role.Pc}), R({Role.Dc, Role.M})]


def test_assign_weighted_agrees_with_brute_force_on_small_rosters():
    rng = random.Random(7)
    for _ in range(60):
        roster = rng.sample(POOL, k=rng.randint(4, 7))
        natural = [round(rng.uniform(0, 10), 2) for _ in roster]
        adapted = [max(n - rng.uniform(0.5, 1.5), 0.0) for n in natural]
        oracle = _brute(SMALL, roster, natural, adapted)
        result = assign_weighted(SMALL, roster, natural, adapted)
        if oracle is None:
            assert result is None
        else:
            total, chosen = result
            assert total == pytest.approx(oracle)
            assert len(set(chosen)) == len(SMALL.slots)
            assert all(SMALL.slots[k].fit(roster[i]) in (Fit.NATURAL, Fit.ADAPTED) for k, i in enumerate(chosen))


def test_assign_weighted_prefers_the_natural_fit_when_the_malus_outweighs_the_player():
    m = load_modules()["343"]
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}),
              R({Role.C}), R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A}), R({Role.Dd})]
    natural = [5.0] * 11 + [5.6]                 # the Dd is worth a little more than either E ...
    adapted = [4.0] * 11 + [4.6]                 # ... but not once the out-of-position malus is paid
    total, chosen = assign_weighted(m, roster, natural, adapted)
    assert 11 not in chosen and total == pytest.approx(55.0)
    natural[11], adapted[11] = 7.0, 6.0          # now he is worth fielding adapted at E
    total, chosen = assign_weighted(m, roster, natural, adapted)
    assert 11 in chosen and total == pytest.approx(56.0)


def test_assign_weighted_returns_none_when_no_legal_eleven_exists():
    m = load_modules()["343"]
    roster = [R({Role.Por})] * 3 + [R({Role.Dc})] * 8
    assert assign_weighted(m, roster, [1.0] * 11, [0.0] * 11) is None
    assert assign_weighted(m, roster[:10], [1.0] * 10, [0.0] * 10) is None
```

`R`, `Fit`, `Role`, `load_modules` and `pytest` are already imported at the top of the file — add `pytest` if not.

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_modules.py -c core/pyproject.toml -q` — ImportError on `assign_weighted`.

- [ ] **Step 3: The solve**

Append to `model/modules.py`:

```python
_FORBIDDEN = 1e9      # a pair the table forbids: dearer than any legal eleven can ever be


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment of every row to a distinct column (rows <= columns):
    per row, the column chosen. Potentials and shortest augmenting paths,
    O(rows^2 x columns) -- eleven slots against forty players is microseconds."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    matched = [0] * (m + 1)          # matched[j]: the row (1-based) holding column j, 0 = free
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        matched[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = matched[j0]
            delta, j1 = inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[matched[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if matched[j0] == 0:
                break
        while True:
            j1 = way[j0]
            matched[j0] = matched[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1] * n
    for j in range(1, m + 1):
        if matched[j]:
            result[matched[j] - 1] = j - 1
    return result


def assign_weighted(module: Module, roster: Sequence[frozenset[Role]], natural: Sequence[float],
                    adapted: Sequence[float]) -> tuple[float, list[int]] | None:
    """The eleven that maximise total weight: (total, per slot the roster index),
    or None when the roster cannot field the module. A player fielded ADAPTED
    contributes `adapted[i]` -- his expected points net of the out-of-position
    malus -- instead of `natural[i]`; FORCED_ONLY and NO are never fielded, the
    same rule `assign` keeps. Exact, like `assign`: the one thing eyeballing a
    multi-role roster gets wrong is exactly what this exists to prevent."""
    if not (len(roster) == len(natural) == len(adapted)):
        raise ValueError("roster, natural and adapted must be the same length")
    if len(roster) < len(module.slots):
        return None
    cost: list[list[float]] = []
    for slot in module.slots:
        row: list[float] = []
        for i, roles in enumerate(roster):
            fit = slot.fit(roles)
            if fit is Fit.NATURAL:
                row.append(-float(natural[i]))
            elif fit is Fit.ADAPTED:
                row.append(-float(adapted[i]))
            else:
                row.append(_FORBIDDEN)
        cost.append(row)
    chosen = _hungarian(cost)
    total = 0.0
    for slot_index, player in enumerate(chosen):
        if cost[slot_index][player] >= _FORBIDDEN:
            return None
        total -= cost[slot_index][player]
    return total, chosen
```

Update the module docstring's last sentence: "`assign_weighted` answers the weekly question beside it — which eleven, and where — exactly, by max-weight matching."

- [ ] **Step 4: Run, expect green**

`uv run pytest core/tests/test_modules.py -c core/pyproject.toml -q`

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/model/modules.py core/tests/test_modules.py
git commit -m "feat(modules): assign_weighted -- exact max-weight XI per module, checked against brute force"
```

---

### Task 7: The roster adapter — `ingest rosters`

**Files:**
- Create: `core/src/fantaclaude/ingest/rosters_api.py`
- Modify: `core/src/fantaclaude/commands/ingest.py` (add `fetch_rosters`, `current_league_id`)
- Modify: `core/src/fantaclaude/cli/app.py` (the command and its renderer)
- Modify: `core/tests/conftest.py` (add `seed_rosters`)
- Test: `core/tests/test_rosters.py`

**Interfaces:**
- Consumes: `sync_league.fetch_teams` (pages the team list, returns `(payload, warnings)`), `api.league_status`, `league.settings.without_emails`, `roster_snapshots`/`rosters` (Task 2), `FakeAPI` (conftest).
- Produces:
  - `RosterRow(team_id: int, team_name: str, owner: str | None, player_id: int, cost: int, position: int)`
  - `class RosterShapeError(ValueError)`
  - `parse_rosters(teams_payload: dict) -> tuple[list[RosterRow], list[str]]` — rows and warnings (`cs` not summing to `crs`)
  - `record_rosters(con, payload: dict, raw: RawFile, *, league_id: int) -> RosterIngestResult` with `.to_dict()` keys `snapshot_id, league_id, season_id, matchday, matchday_start, teams, inserted, skipped_duplicate, warnings, sha256, raw_path`
  - `commands.ingest.fetch_rosters(api, store, *, league=None) -> tuple[RawFile, dict]`; `commands.ingest.current_league_id(path=None) -> int`
  - conftest `seed_rosters(con, league_id, season_id, teams: dict[int, tuple[str, dict[int, int]]], *, matchday=None) -> snapshot_id` — `teams[team_id] = (name, {player_id: cost})`
  - `fantaclaude ingest rosters [--league] [--json]`

- [ ] **Step 1: The failing tests**

`core/tests/test_rosters.py`:

```python
import asyncio
import json
from datetime import UTC, datetime

import pytest
from conftest import seed_rosters
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import fetch_rosters
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.ingest.rosters_api import RosterShapeError, parse_rosters, record_rosters
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from typer.testing import CliRunner

runner = CliRunner()


def _teams(*teams):
    return {"nextPage": False, "prevPage": False, "page": 1, "item": len(teams), "pages": 1,
            "data": list(teams), "divisions": [{"division": "A", "count": len(teams)}]}


def _team(team_id, name, cal, cs, *, crs=None, owner="nick"):
    return {"id": team_id, "n": name, "nu": owner, "idu": 1, "cri": 500, "crs": crs if crs is not None else 0,
            "cr": 500, "cal": cal, "cs": cs, "pl": None, "r": {"p": 0, "d": 0, "c": 0, "a": 0}, "d": "A",
            "all": [{"id": 9, "n": "Coach", "e": "coach@example.com"}]}


def test_parse_reads_ids_and_costs_in_order_and_an_empty_roster_is_empty():
    rows, warnings = parse_rosters(_teams(_team(1, "A", "2764;5841;", "120;30;", crs=150),
                                          _team(2, "B", "", "", crs=0)))
    assert [(r.team_id, r.player_id, r.cost, r.position) for r in rows] == [(1, 2764, 120, 0), (1, 5841, 30, 1)]
    assert rows[0].team_name == "A" and rows[0].owner == "nick" and warnings == []


def test_parse_warns_when_cs_does_not_sum_to_crs_and_names_the_team():
    _, warnings = parse_rosters(_teams(_team(1, "A", "2764;5841", "120;30", crs=151)))
    assert warnings == ["team 'A': cs sums to 150 but crs says 151"]


def test_parse_fails_loud_on_a_shape_it_cannot_read():
    with pytest.raises(RosterShapeError, match="2 ids"):
        parse_rosters(_teams(_team(1, "A", "2764;5841", "120")))
    with pytest.raises(RosterShapeError, match="not an integer"):
        parse_rosters(_teams(_team(1, "A", "2764;x", "1;2")))
    with pytest.raises(RosterShapeError, match="no data list"):
        parse_rosters({"data": None})


def _raw(tmp_path, payload, stamp="1"):
    path = tmp_path / f"rosters-{stamp}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return RawFile(path, f"sha-{stamp}", datetime(2026, 9, 4, 12, 0, tzinfo=UTC), "rosters")


def test_record_appends_a_snapshot_with_the_status_read_and_dedupes_on_bytes(db, tmp_path):
    payload = {"teams": _teams(_team(1, "A", "2764;795", "120;1", crs=121), _team(2, "B", "", "")),
               "status": {"sId": 21, "mday": 3, "mstr": "2026-09-04T18:45:00", "activ": True}, "fetch_warnings": []}
    first = record_rosters(db, payload, _raw(tmp_path, payload), league_id=2578630)
    assert not first.skipped_duplicate and first.inserted == 2 and first.teams == 2
    assert first.matchday == 3 and first.season_id == 21
    assert db.execute("SELECT matchday, matchday_start, team_count, row_count FROM roster_snapshots").fetchone() == \
        (3, datetime(2026, 9, 4, 18, 45), 2, 2)
    teams = json.loads(db.execute("SELECT teams FROM roster_snapshots").fetchone()[0])
    assert teams == [{"id": 1, "name": "A", "owner": "nick", "size": 2}, {"id": 2, "name": "B", "owner": "nick", "size": 0}]
    assert db.execute("SELECT player_id, cost FROM v_rosters_current WHERE team_id = 1 ORDER BY position").fetchall() == \
        [(2764, 120), (795, 1)]                                     # 795 is not in any listone and is kept
    again = record_rosters(db, payload, _raw(tmp_path, payload), league_id=2578630)
    assert again.skipped_duplicate and again.snapshot_id == first.snapshot_id
    later = record_rosters(db, payload, _raw(tmp_path, payload, stamp="2"), league_id=2578630)
    assert later.snapshot_id != first.snapshot_id
    assert db.execute("SELECT snapshot_id FROM v_rosters_first").fetchone()[0] == first.snapshot_id


def test_an_empty_league_is_a_snapshot_with_no_rows(db, tmp_path):
    payload = {"teams": _teams(_team(1, "A", "", "")), "status": {"sId": 21, "mday": 1, "mstr": None}, "fetch_warnings": []}
    result = record_rosters(db, payload, _raw(tmp_path, payload), league_id=1)
    assert result.inserted == 0 and result.teams == 1
    assert db.execute("SELECT count(*) FROM v_rosters_first").fetchone()[0] == 0     # never the "earliest" for market prices


async def test_fetch_rosters_pages_the_teams_reads_the_status_and_scrubs_emails(tmp_path, fake_api):
    api = fake_api(overrides={"teams": _teams(_team(1, "A", "2764", "120", crs=120))})
    raw, payload = await fetch_rosters(api, RawStore(tmp_path / "raw"))
    assert api.calls == ["teams", "league_status"]
    assert raw.path.parent.name == "rosters" and raw.kind == "rosters"
    text = raw.path.read_text(encoding="utf-8")
    assert "@" not in text and "[email redacted]" in text
    assert payload["status"]["mday"] == 1 and payload["teams"]["data"][0]["cal"] == "2764"


def test_cli_ingest_rosters_needs_a_synced_league_and_records_once(monkeypatch, tmp_path, fake_api, mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    api = fake_api(overrides={"teams": _teams(_team(1, "A", "2764;5841", "120;30", crs=150))})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    result = runner.invoke(app, ["ingest", "rosters"])
    assert result.exit_code == ExitCode.NOT_READY and "sync-league" in result.stderr and api.calls == []
    assert runner.invoke(app, ["sync-league"]).exit_code == ExitCode.OK
    result = runner.invoke(app, ["ingest", "rosters", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["inserted"] == 2 and payload["teams"] == 1 and payload["warnings"] == []
    assert list((tmp_path / "data" / "raw" / "rosters").glob("*-rosters.json"))
    plain = runner.invoke(app, ["ingest", "rosters"])
    assert plain.exit_code == ExitCode.OK and "duplicate" in plain.stdout


def test_seed_rosters_matches_what_record_writes(db):
    seed_rosters(db, 1, 21, {10: ("Mine", {2764: 120, 5841: 30}), 11: ("Empty", {})}, matchday=3)
    assert db.execute("SELECT count(*), max(matchday) FROM v_rosters_current").fetchone() == (2, 3)
```

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_rosters.py -c core/pyproject.toml -q` — ImportError.

- [ ] **Step 3: The adapter**

`core/src/fantaclaude/ingest/rosters_api.py`:

```python
"""Rosters and purchase costs off the lega's team objects (spec, open question 9).

After the admin transfers the auction, every team object from
`/onboarding/v1/league/teams` carries `cal` -- the owned player ids,
semicolon-separated -- and `cs`, the price paid for each in the same order,
summing to `crs`. Before the transfer both are empty strings, which is an
empty roster and not an error. An id the listone never carried (795 on
2026-09-04) is kept: this is the lega's roster, not ours. The status read
rides along so every snapshot carries the platform's own `mday`/`mstr`,
which `league_settings` only refreshes on a rules change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from fantaclaude.ingest.raw import RawFile
from fantaclaude.timeutil import to_db

SOURCE = "apileague:GET /onboarding/v1/league/teams (cal/cs) + /league/status"


class RosterShapeError(ValueError):
    """The team objects do not carry rosters the way this adapter was written against."""


@dataclass(frozen=True)
class RosterRow:
    team_id: int
    team_name: str
    owner: str | None
    player_id: int
    cost: int
    position: int


def _split(value: Any, *, what: str, team: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        raise RosterShapeError(f"team {team!r}: {what} is {type(value).__name__}, expected a ';'-separated string")
    return [part.strip() for part in value.split(";") if part.strip()]


def parse_rosters(teams_payload: Any) -> tuple[list[RosterRow], list[str]]:
    data = teams_payload.get("data") if isinstance(teams_payload, dict) else None
    if not isinstance(data, list):
        raise RosterShapeError("the teams payload has no data list")
    rows: list[RosterRow] = []
    warnings: list[str] = []
    for team in data:
        name = str(team.get("n", ""))
        ids = _split(team.get("cal"), what="cal", team=name)
        costs = _split(team.get("cs"), what="cs", team=name)
        if len(ids) != len(costs):
            raise RosterShapeError(f"team {name!r}: {len(ids)} ids in cal but {len(costs)} prices in cs")
        total = 0
        for position, (pid, cost) in enumerate(zip(ids, costs)):
            try:
                player_id, credits = int(pid), int(cost)
            except ValueError:
                raise RosterShapeError(f"team {name!r}: cal/cs entry {pid!r}/{cost!r} is not an integer") from None
            total += credits
            rows.append(RosterRow(int(team["id"]), name, team.get("nu"), player_id, credits, position))
        crs = team.get("crs")
        if ids and isinstance(crs, int) and crs != total:
            warnings.append(f"team {name!r}: cs sums to {total} but crs says {crs}")
    return rows, warnings


def _matchday_start(value: Any) -> datetime | None:
    """`mstr` is an ISO instant without a zone and it is UTC (giornata 1:
    2026-08-22T16:30:00 against an 18:30 Rome kickoff)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


@dataclass(frozen=True)
class RosterIngestResult:
    snapshot_id: int
    league_id: int
    season_id: int | None
    matchday: int | None
    matchday_start: str | None
    teams: int
    inserted: int
    skipped_duplicate: bool
    warnings: list[str]
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "league_id": self.league_id, "season_id": self.season_id,
                "matchday": self.matchday, "matchday_start": self.matchday_start, "teams": self.teams,
                "inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate,
                "warnings": list(self.warnings), "sha256": self.sha256, "raw_path": self.raw_path}


def record_rosters(con: duckdb.DuckDBPyConnection, payload: dict[str, Any], raw: RawFile, *,
                   league_id: int) -> RosterIngestResult:
    """Append one snapshot and its rows; the same bytes for the same league is a no-op."""
    rows, warnings = parse_rosters(payload.get("teams"))
    warnings = [*payload.get("fetch_warnings", []), *warnings]
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    season_id = status.get("sId") if isinstance(status.get("sId"), int) else None
    matchday = status.get("mday") if isinstance(status.get("mday"), int) else None
    start = _matchday_start(status.get("mstr"))
    sizes: dict[int, int] = {}
    for r in rows:
        sizes[r.team_id] = sizes.get(r.team_id, 0) + 1
    team_list = [{"id": int(t["id"]), "name": str(t.get("n", "")), "owner": t.get("nu"), "size": sizes.get(int(t["id"]), 0)}
                 for t in payload["teams"]["data"]]           # every team, the empty ones included: rosters has no row for those
    teams = len(team_list)
    existing = con.execute("SELECT snapshot_id FROM roster_snapshots WHERE league_id = ? AND sha256 = ?",
                           [league_id, raw.sha256]).fetchone()
    if existing is not None:
        return RosterIngestResult(existing[0], league_id, season_id, matchday, status.get("mstr"), teams, 0, True,
                                  warnings, raw.sha256, str(raw.path))
    con.begin()
    try:
        snapshot_id = con.execute(
            "INSERT INTO roster_snapshots (league_id, season_id, fetched_at, source, raw_path, sha256, matchday, "
            "matchday_start, team_count, teams, row_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?) RETURNING snapshot_id",
            [league_id, season_id, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, matchday, start,
             teams, json.dumps(team_list, ensure_ascii=False), len(rows)]).fetchone()[0]
        con.executemany("INSERT INTO rosters VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [[snapshot_id, r.team_id, r.team_name, r.owner, r.player_id, r.cost, r.position] for r in rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return RosterIngestResult(snapshot_id, league_id, season_id, matchday, status.get("mstr"), teams, len(rows), False,
                              warnings, raw.sha256, str(raw.path))
```

- [ ] **Step 4: `fetch_rosters` and `current_league_id` in `commands/ingest.py`**

Next to `fetch_calendar`:

```python
async def fetch_rosters(api: FantacalcioAPI, store: RawStore, *, league: str | None = None) -> tuple[RawFile, dict[str, Any]]:
    """The team list (every page, via sync_league.fetch_teams) and the status
    read, scrubbed of emails and written as one raw file. Two reads against a
    real account: run when the rosters are needed, never to check."""
    from fantaclaude.commands.sync_league import fetch_teams
    from fantaclaude.league.settings import without_emails

    teams, warnings = await fetch_teams(api, league=league)
    status = await api.league_status(league=league)
    payload = {"teams": without_emails(teams), "status": without_emails(status), "fetch_warnings": list(warnings)}
    return store.write("rosters", payload), payload


def current_league_id(path: Path | None = None) -> int:
    """The league the settings snapshot names, read-only; NotReady before the first sync."""
    try:
        con = connect(path or db_path(), read_only=True)
    except DatabaseMissing:
        raise NotReady("no database yet -- run `fantaclaude sync-league` first") from None
    try:
        row = con.execute("SELECT league_id FROM v_league_settings_current").fetchone()
    except duckdb.Error:
        row = None
    finally:
        con.close()
    if row is None:
        raise NotReady("no league_settings snapshot -- run `fantaclaude sync-league` first")
    return int(row[0])
```

Use the same imports `current_season_id` in that file already uses for `connect`, `DatabaseMissing` and `db_path`.

- [ ] **Step 5: `seed_rosters` in conftest**

```python
def seed_rosters(con, league_id: int, season_id: int, teams, *, matchday=None) -> int:
    """One roster snapshot. `teams` maps team_id -> (name, {player_id: cost})."""
    from uuid import uuid4
    rows = [(tid, name, pid, cost, i) for tid, (name, roster) in teams.items() for i, (pid, cost) in enumerate(roster.items())]
    team_list = [{"id": tid, "name": name, "owner": None, "size": len(roster)} for tid, (name, roster) in teams.items()]
    snapshot_id = con.execute(
        "INSERT INTO roster_snapshots (league_id, season_id, fetched_at, source, raw_path, sha256, matchday, matchday_start, "
        "team_count, teams, row_count) VALUES (?, ?, now(), 'seed', 'seed/rosters', ?, ?, NULL, ?, ?::JSON, ?) RETURNING snapshot_id",
        [league_id, season_id, f"seed-rosters-{uuid4().hex[:8]}", matchday, len(teams), json.dumps(team_list), len(rows)]).fetchone()[0]
    for tid, name, pid, cost, position in rows:
        con.execute("INSERT INTO rosters VALUES (?, ?, ?, NULL, ?, ?, ?)", [snapshot_id, tid, name, pid, cost, position])
    return snapshot_id
```

- [ ] **Step 6: The command in `cli/app.py`**

After `ingest_probabili_cmd`:

```python
def _render_rosters(payload: dict) -> str:
    head = f"rosters league {payload['league_id']}"
    if payload["skipped_duplicate"]:
        line = f"{head}: duplicate of snapshot {payload['snapshot_id']} -- nothing new"
    else:
        line = (f"{head}: snapshot {payload['snapshot_id']}, {payload['inserted']} players over {payload['teams']} teams"
                f" · matchday {payload['matchday']} starts {payload['matchday_start']} UTC")
    return "\n".join([line + f" ({payload['raw_path']})", *(f"warning: {w}" for w in payload["warnings"])])


@ingest_app.command("rosters")
def ingest_rosters_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Every lega team's roster and what it paid (cal/cs on the team objects), with the status read's matchday. Two reads against the real account -- run when the rosters changed, never to check."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.ingest import NotReady, current_league_id, ensure_schema, fetch_rosters
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.ingest.rosters_api import record_rosters
    from fantaclaude.paths import raw_dir

    ensure_schema()
    try:
        league_id = current_league_id()
    except NotReady as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    store = RawStore(raw_dir())
    raw, payload = run_with_api(lambda api: fetch_rosters(api, store, league=league))
    with _source_errors():                      # RosterShapeError is a ValueError: exit 1
        con = connect()
        try:
            apply_schema(con)
            result = record_rosters(con, payload, raw, league_id=league_id)
        finally:
            con.close()
    emit(result.to_dict(), json_=json_, render=_render_rosters)
```

- [ ] **Step 7: Run, expect green; suite; lint**

`uv run pytest core/tests/test_rosters.py core/tests/test_sync_league.py -c core/pyproject.toml -q && uv run poe lint`

- [ ] **Step 8: Commit**

```bash
git add core/src/fantaclaude/ingest/rosters_api.py core/src/fantaclaude/commands/ingest.py core/src/fantaclaude/cli/app.py core/tests/test_rosters.py core/tests/conftest.py
git commit -m "feat(ingest): rosters -- cal/cs off the team objects, with the status read, appended per fetch"
```

---

### Task 8: `my_team` and the XI in `lineup`

**Files:**
- Modify: `core/src/fantaclaude/analysis/weekly.py` (add `RosterPlayer`, `my_roster`, `XiSlot`, `XiChoice`, `choose_xi`; fill the XI branch of `lineup()`)
- Test: `core/tests/test_weekly.py`, `core/tests/test_lineup_cli.py`, `core/tests/test_league_yml.py`

**Interfaces:**
- Consumes: `assign_weighted` (Task 6), `v_rosters_current` + `seed_rosters` (Task 7), `v_players_current.mantra_roles`, `v_league_settings_current.modules`, `load_modules`.
- Produces:
  - `RosterPlayer(player_id, name, roles: frozenset[Role], cost: int, in_listone: bool)`
  - `my_roster(con, team_id) -> list[RosterPlayer]`
  - `XiSlot(slot: str, player_id: int, name: str, fit: str, expected_points: float)`, `XiChoice(module: str, total: float, slots: list[XiSlot], module_scores: dict[str, float | None], unlisted: list[int])` with `.to_dict()`
  - `choose_xi(roster, forecast_by_id: dict[int, ForecastRow], modules: dict[str, Module], allowed: Sequence[str]) -> XiChoice`
  - `ADAPTED_MALUS = 1.0` (Mantra: out of position is voto minus one, so adapted weight = `expected_points - p_start * ADAPTED_MALUS`)
  - `matchday_cross_check(con, round_) -> str | None` — a warning when the freshest roster snapshot's `mday`/`mstr` disagree with the calendar
  - `lineup()` now fills `xi` when `my_team` is given, writes `my_team`, `module`, `xi`, `module_scores` into `lineup_runs`, and carries the cross-check warning

- [ ] **Step 1: The failing tests**

Append to `core/tests/test_weekly.py`:

```python
from conftest import seed_rosters
from fantaclaude.analysis.weekly import ADAPTED_MALUS, ForecastRow, RosterPlayer, choose_xi, my_roster
from fantaclaude.model.modules import load_modules
from fantaclaude.model.roles import Role

R = frozenset


def _row(pid, role, p, fv):
    return ForecastRow(pid, f"p{pid}", None, role, (), int(p * 100), p, fv, None, p * fv, "published")


def test_choose_xi_takes_the_best_module_and_scores_every_permitted_one():
    modules = load_modules()
    roles = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}), R({Role.C}),
             R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A}), R({Role.Dd})]
    roster = [RosterPlayer(100 + i, f"p{100 + i}", r, 1, True) for i, r in enumerate(roles)]
    forecast = {p.player_id: _row(p.player_id, "C", 0.9, 6.0) for p in roster}
    forecast[111] = _row(111, "D", 1.0, 8.0)                  # the Dd: worth 8 natural, 8 - 1.0 adapted at E
    choice = choose_xi(roster, forecast, modules, ["343", "442"])
    assert set(choice.module_scores) == {"343", "442"}
    assert choice.module in {"343", "442"} and choice.total == pytest.approx(max(v for v in choice.module_scores.values() if v is not None))
    assert len(choice.slots) == 11 and len({s.player_id for s in choice.slots}) == 11
    assert choice.unlisted == []
    fielded = {s.player_id: s for s in choice.slots}
    if 111 in fielded:
        assert fielded[111].fit == "adapted" and fielded[111].expected_points == pytest.approx(8.0 - 1.0 * ADAPTED_MALUS)


def test_choose_xi_counts_an_unlisted_player_as_zero_and_says_so():
    modules = load_modules()
    roles = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}), R({Role.C}),
             R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A})]
    roster = [RosterPlayer(200 + i, f"p{200 + i}", r, 1, True) for i, r in enumerate(roles)]
    forecast = {p.player_id: _row(p.player_id, "C", 0.9, 6.0) for p in roster[:-1]}    # the A is not on the page
    choice = choose_xi(roster, forecast, modules, ["343"])
    assert choice.unlisted == [210] and choice.module == "343"
    assert next(s for s in choice.slots if s.player_id == 210).expected_points == 0.0


def test_choose_xi_refuses_when_no_permitted_module_can_be_fielded():
    modules = load_modules()
    roster = [RosterPlayer(i, f"p{i}", R({Role.Dc}), 1, True) for i in range(12)]
    with pytest.raises(ForecastError, match="no permitted module"):
        choose_xi(roster, {}, modules, ["343"])
    with pytest.raises(ForecastError, match="not in modules.yml"):
        choose_xi(roster, {}, modules, ["999"])


def test_my_roster_reads_the_latest_snapshot_and_keeps_an_id_the_listone_lacks(db):
    db.execute("INSERT INTO listone_snapshots (season_id, fetched_at, source, raw_path, sha256, row_count) VALUES (21, now(), 'seed', 'seed', 'seed', 1)")
    db.execute("INSERT INTO players VALUES (1, 2764, 'Martinez L.', 1, 'Inter', 'INT', 'A', ['Pc'], [16], 30, 30, 40, 40, 100, 100, 29, 'ARG', false, '{}')")
    seed_rosters(db, 1, 21, {10: ("Mine", {2764: 120, 795: 1})})
    roster = my_roster(db, 10)
    assert [(p.player_id, p.name, p.roles, p.cost, p.in_listone) for p in roster] == \
        [(2764, "Martinez L.", R({Role.Pc}), 120, True), (795, "#795", R(), 1, False)]
    with pytest.raises(ForecastError, match="ingest rosters"):
        my_roster(db, 11)
```

If the `listone_snapshots` or `players` insert above does not match the columns in `schema.py`, use `record_listone` with `listone_sample.json` as `test_probabili.py` does.

Append to `core/tests/test_lineup_cli.py`:

```python
def test_lineup_names_the_xi_when_league_yml_names_my_team(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]     # the 17 can field 3-4-3
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone])
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone})})
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    xi = payload["xi"]
    assert payload["my_team"] == 4242 and xi["module"] in payload["xi"]["module_scores"] and len(xi["slots"]) == 11
    assert payload["predictions"] == 17
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT my_team, module FROM lineup_runs").fetchone() == (4242, xi["module"])
    con.close()
    plain = runner.invoke(app, ["lineup"])
    assert plain.exit_code == ExitCode.OK and f"XI: {xi['module']}" in plain.stdout


def test_lineup_with_my_team_but_no_roster_still_writes_the_forecast(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    _page(tmp_path)
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["xi"] is None and "ingest rosters" in payload["no_xi_reason"] and payload["predictions"] == 6
```

Add `seed_rosters` to that file's `conftest` import. And in `core/tests/test_league_yml.py`, one line in the cross-check test (or a new test): a `my_team` leaf produces no conflict —

```python
def test_my_team_is_not_comparable_to_anything_the_api_says(tmp_path, mcp_fixture_json):
    from fantaclaude.league.league_yml import cross_check, load_league_yml
    from fantaclaude.league.settings import snapshot_from_payloads
    path = tmp_path / "league.yml"
    path.write_text("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    snap = snapshot_from_payloads(profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
                                  rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
                                  calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams"))
    assert cross_check(load_league_yml(path), snap) == []
```

(`snapshot_from_payloads`'s keyword names are in `league/settings.py:119`; follow them.)

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_weekly.py core/tests/test_lineup_cli.py core/tests/test_league_yml.py -c core/pyproject.toml -q`

- [ ] **Step 3: The roster and the XI in `weekly.py`**

Imports to add: `from collections.abc import Sequence`, `from fantaclaude.model.modules import Module, assign_weighted, load_modules`, `from fantaclaude.model.roles import Role`.

```python
ADAPTED_MALUS = 1.0      # Mantra: a player out of position scores his voto minus one


@dataclass(frozen=True)
class RosterPlayer:
    player_id: int
    name: str
    roles: frozenset[Role]
    cost: int
    in_listone: bool


def my_roster(con: duckdb.DuckDBPyConnection, team_id: int) -> list[RosterPlayer]:
    """The team's roster in the latest snapshot, with the listone's roles; an id
    the listone lacks is kept with no roles (it can be fielded nowhere)."""
    rows = con.execute(
        "SELECT r.player_id, r.cost, p.name, p.mantra_roles FROM v_rosters_current r "
        "LEFT JOIN v_players_current p ON p.player_id = r.player_id WHERE r.team_id = ? ORDER BY r.position",
        [team_id]).fetchall()
    if not rows:
        raise ForecastError(f"team {team_id} has no roster in the latest snapshot -- run `fantaclaude ingest rosters`")
    return [RosterPlayer(int(pid), str(name) if name is not None else f"#{pid}",
                         frozenset(Role(r) for r in (roles or [])), int(cost), name is not None)
            for pid, cost, name, roles in rows]


@dataclass(frozen=True)
class XiSlot:
    slot: str
    player_id: int
    name: str
    fit: str
    expected_points: float

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "player_id": self.player_id, "name": self.name, "fit": self.fit,
                "expected_points": self.expected_points}


@dataclass(frozen=True)
class XiChoice:
    module: str
    total: float
    slots: list[XiSlot]
    module_scores: dict[str, float | None]
    unlisted: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "total": self.total, "slots": [s.to_dict() for s in self.slots],
                "module_scores": dict(self.module_scores), "unlisted": list(self.unlisted)}


def choose_xi(roster: list[RosterPlayer], forecast_by_id: dict[int, ForecastRow], modules: dict[str, Module],
              allowed: Sequence[str]) -> XiChoice:
    """One exact solve per permitted module; the best total wins. A roster
    player the page does not list is worth zero this week and is named."""
    natural: list[float] = []
    adapted: list[float] = []
    for p in roster:
        row = forecast_by_id.get(p.player_id)
        points = row.expected_points if row else 0.0
        natural.append(points)
        adapted.append(points - (row.p_start * ADAPTED_MALUS if row else 0.0))
    roles = [p.roles for p in roster]
    scores: dict[str, float | None] = {}
    best: tuple[str, float, list[int]] | None = None
    for code in allowed:
        module = modules.get(str(code))
        if module is None:
            raise ForecastError(f"the league permits module {code!r}, which is not in modules.yml")
        solved = assign_weighted(module, roles, natural, adapted)
        scores[str(code)] = None if solved is None else solved[0]
        if solved is not None and (best is None or solved[0] > best[1]):
            best = (str(code), solved[0], solved[1])
    if best is None:
        raise ForecastError("no permitted module can be fielded from this roster")
    code, total, chosen = best
    slots = []
    for k, i in enumerate(chosen):
        fit = modules[code].slots[k].fit(roster[i].roles)
        points = natural[i] if fit.value == "natural" else adapted[i]
        slots.append(XiSlot(modules[code].slots[k].label, roster[i].player_id, roster[i].name, fit.value, points))
    unlisted = [p.player_id for p in roster if p.player_id not in forecast_by_id]
    return XiChoice(code, total, slots, scores, unlisted)
```

In `lineup()`, replace the `else:` branch of the `my_team` check with:

```python
    else:
        try:
            roster = my_roster(con, my_team)
            allowed_row = con.execute("SELECT modules FROM v_league_settings_current").fetchone()
            if allowed_row is None or not allowed_row[0]:
                raise ForecastError("no league_settings snapshot names the permitted modules -- run `fantaclaude sync-league`")
            choice = choose_xi(roster, {r.player_id: r for r in rows}, load_modules(), list(allowed_row[0]))
            xi, module, scores = choice.to_dict(), choice.module, choice.module_scores
            xi_rows = [s.to_dict() for s in choice.slots]
            if choice.unlisted:
                warnings.append(f"{len(choice.unlisted)} roster player(s) not on the page, counted as 0: "
                                + ", ".join(next(p.name for p in roster if p.player_id == pid) for pid in choice.unlisted))
        except ForecastError as exc:
            no_xi_reason = str(exc)
```

and delete the placeholder line from Task 5. `no_xi_reason` stays `None` when an XI was named.

The spec's cross-check of the calendar against the platform's own round (the freshest `mday`/`mstr`, carried on every roster snapshot) lands here too. Add to `weekly.py`:

```python
def matchday_cross_check(con: duckdb.DuckDBPyConnection, round_: Round) -> str | None:
    """A warning when the freshest roster snapshot's mday/mstr disagree with
    the calendar's round; None when they agree or nothing has been fetched."""
    row = con.execute("SELECT matchday, matchday_start, fetched_at FROM roster_snapshots "
                      "WHERE matchday IS NOT NULL ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    matchday, start, fetched_at = row
    if int(matchday) == round_.giornata and (start is None or start == round_.first_kickoff):
        return None
    return (f"the league API's status read on {fetched_at:%Y-%m-%d %H:%M} UTC said matchday {matchday} starting "
            f"{start}; the calendar says giornata {round_.giornata} at {round_.first_kickoff} -- if the platform is "
            f"fresher, pass --giornata")
```

and in `lineup()`, right after `warnings: list[str] = []`: `if (mismatch := matchday_cross_check(con, round_)): warnings.append(mismatch)`. Its test, in `test_weekly.py`:

```python
def test_the_platforms_matchday_is_a_cross_check_on_the_calendar(db):
    seed_fixtures(db, 21, {3: G3})
    r = target_round(db, NOW, season_id=21)
    assert matchday_cross_check(db, r) is None                                   # nothing fetched yet
    seed_rosters(db, 1, 21, {10: ("Mine", {})}, matchday=3)
    db.execute("UPDATE roster_snapshots SET matchday_start = ? WHERE matchday = 3", [datetime(2026, 9, 4, 18, 45)])
    assert matchday_cross_check(db, r) is None                                   # agrees
    seed_rosters(db, 1, 21, {10: ("Mine", {})}, matchday=4)
    assert "matchday 4" in matchday_cross_check(db, r)                           # the platform moved on
```

(the `UPDATE` is test setup on a seed row, not a code path: `seed_rosters` writes `matchday_start` as NULL and NULL is read as "agrees" above). Import `matchday_cross_check` at the top of the test file.

- [ ] **Step 4: Run, expect green; suite; lint**

`uv run poe test-core && uv run poe lint`

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/analysis/weekly.py core/tests/test_weekly.py core/tests/test_lineup_cli.py core/tests/test_league_yml.py
git commit -m "feat(lineup): the XI -- my roster from league.yml's my_team, one exact solve per permitted module"
```

---

### Task 9: `asta verify-transfer`

**Files:**
- Create: `core/src/fantaclaude/asta/transfer.py` (pure reconciliation)
- Modify: `core/src/fantaclaude/commands/asta.py` (add `TransferMismatch`, `verify_transfer`)
- Modify: `core/src/fantaclaude/cli/app.py` (the command and its renderer)
- Test: `core/tests/test_transfer.py`, `core/tests/test_asta_cli.py`

**Interfaces:**
- Consumes: `_stored` and `AstaPaths` (`commands/asta.py`), `state_from_snapshot` (`asta/state.py`), `v_rosters_current` (Task 7), `v_players_current`.
- Produces:
  - `TeamDiff(mirror_team_id, mirror_label, lega_team_id, lega_team_name, overlap, mirror_size, lega_size, missing_in_lega: tuple[int, ...], cost_differences: tuple[tuple[int, int, int], ...], added_after_room: tuple[tuple[int, int], ...], extra_in_lega: tuple[tuple[int, int], ...])`, `.clean`
  - `Reconciliation(teams, lega_not_in_room: tuple[tuple[int, str, int], ...], mirror_unmatched: tuple[tuple[int, str], ...], ambiguous: tuple[str, ...], my_team: tuple[int, str] | None)`, `.clean`
  - `reconcile(mirror: dict[int, dict[int, int]], lega: dict[int, dict[int, int]], *, me: int, labels: dict[int, str], names: dict[int, str], min_bid: int = 1) -> Reconciliation`
  - `commands.asta.verify_transfer(con, *, paths, state_file=None, prune=False) -> VerifyReport` with `.to_dict()`; `class TransferMismatch(RuntimeError)` (exit 4)
  - `fantaclaude asta verify-transfer [--state FILE] [--prune] [--json]`

- [ ] **Step 1: The failing tests**

`core/tests/test_transfer.py`:

```python
from fantaclaude.asta.transfer import reconcile

LABELS = {0: "KingNazzario", 1: "G8 E CLAUDIO", 2: "random label"}
NAMES = {100: "KingKlavan FC", 101: "Sanzimippi FC", 102: "Claudio", 103: "Empty eleventh"}
MIRROR = {0: {1: 50, 2: 10, 3: 1}, 1: {4: 80, 5: 20}, 2: {6: 7, 7: 1}}


def test_teams_are_matched_by_overlap_never_by_name():
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}, 103: {}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.clean
    assert {(t.mirror_team_id, t.lega_team_id) for t in result.teams} == {(0, 101), (1, 102), (2, 100)}
    assert result.my_team == (102, "Claudio")
    assert result.lega_not_in_room == ((103, "Empty eleventh", 0),) and result.mirror_unmatched == ()


def test_post_room_additions_at_the_minimum_bid_are_tolerated_and_named():
    lega = {100: {6: 7, 7: 1, 99: 1}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    team = next(t for t in result.teams if t.lega_team_id == 100)
    assert team.added_after_room == ((99, 1),) and team.extra_in_lega == () and team.clean and result.clean


def test_a_cost_that_differs_a_missing_pick_or_a_dear_extra_fails_the_check():
    lega = {100: {6: 7, 7: 1, 98: 5}, 101: {1: 51, 2: 10}, 102: {4: 80, 5: 20}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    by_lega = {t.lega_team_id: t for t in result.teams}
    assert by_lega[100].extra_in_lega == ((98, 5),) and not by_lega[100].clean
    assert by_lega[101].cost_differences == ((1, 50, 51),) and by_lega[101].missing_in_lega == (3,)
    assert by_lega[102].clean and not result.clean


def test_a_lega_team_with_players_that_matches_nothing_is_not_clean():
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}, 104: {55: 9}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.lega_not_in_room == ((104, "104", 1),) and not result.clean


def test_an_equal_overlap_is_ambiguous_and_said():
    lega = {100: {6: 7}, 105: {6: 7}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.ambiguous and "2" in result.ambiguous[0] and not result.clean


def test_me_unmatched_gives_no_my_team():
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.my_team is None and result.mirror_unmatched == ((1, "G8 E CLAUDIO"),) and not result.clean
```

Append to `core/tests/test_asta_cli.py` (uses its existing `_ranked`, `FIXTURE`, `runner`):

```python
from conftest import seed_rosters


def _lega_from_state(state_file, *, added=None, price=None):
    """The lega rosters that would match the mirrored state exactly, plus optional perturbations."""
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    teams = {}
    for t in payload["teams"]:
        roster = {p["player_id"]: p["cost"] for p in t["picks"]}
        teams[1000 + int(t["id"])] = (f"lega {t['id']}", roster)
    if added:
        teams[added[0]][1][added[1]] = added[2]
    if price:
        teams[price[0]][1][price[1]] = price[2]
    teams[1999] = ("eleventh", {})
    return teams


def test_verify_transfer_reports_names_my_team_and_prunes_only_on_a_clean_diff(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "1", "--write-state"]).exit_code == ExitCode.OK
    state_file = tmp_path / "data" / "asta-state.json"
    nothing = runner.invoke(app, ["asta", "verify-transfer"])
    assert nothing.exit_code == ExitCode.NOT_READY and "ingest rosters" in nothing.stderr
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_rosters(con, 2578630, 21, _lega_from_state(state_file, added=(1001, 424242, 1)))
    con.close()
    result = runner.invoke(app, ["asta", "verify-transfer", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["clean"] is True and payload["my_team"]["lega_team_id"] == 1001
    assert "value: 1001" in payload["my_team"]["leaf"] and "source: verify-transfer" in payload["my_team"]["leaf"]
    assert any(t["added_after_room"] == [[424242, 1]] for t in payload["teams"])
    assert payload["lega_not_in_room"] == [[1999, "eleventh", 0]] and payload["pruned"] is False
    plain = runner.invoke(app, ["asta", "verify-transfer"])
    assert "my_team:" in plain.stdout and "clean" in plain.stdout

    # a changed price: not clean, --prune refuses (exit 4) and the file stays
    con = connect(tmp_path / "data" / "fanta.duckdb")
    first_pick = json.loads(state_file.read_text())["teams"][0]["picks"][0]
    seed_rosters(con, 2578630, 21, _lega_from_state(state_file, price=(1000 + json.loads(state_file.read_text())["teams"][0]["id"], first_pick["player_id"], first_pick["cost"] + 1)))
    con.close()
    dirty = runner.invoke(app, ["asta", "verify-transfer", "--prune"])
    assert dirty.exit_code == ExitCode.CONFLICT and state_file.is_file() and "cost" in dirty.stderr

    # clean again: --prune deletes the working file and nothing under records/
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_rosters(con, 2578630, 21, _lega_from_state(state_file))
    con.close()
    assert runner.invoke(app, ["asta", "close", "--session", "FA-test"]).exit_code == ExitCode.OK
    records = sorted((tmp_path / "records" / "asta").glob("*.json"))
    pruned = runner.invoke(app, ["asta", "verify-transfer", "--prune", "--json"])
    assert pruned.exit_code == ExitCode.OK, pruned.output
    assert json.loads(pruned.stdout)["pruned"] is True and not state_file.is_file()
    assert sorted((tmp_path / "records" / "asta").glob("*.json")) == records
    # --prune never applies to an explicit --state file
    kept = runner.invoke(app, ["asta", "verify-transfer", "--state", str(records[0]), "--prune"])
    assert kept.exit_code == ExitCode.USAGE and records[0].is_file()
```

The mirror's team 1 is `--me 1`, so its lega match is `1001`. `seed_rosters` (Task 7) writes the `teams` JSON for every team it is given, the empty `1999` included.

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_transfer.py -c core/pyproject.toml -q` — ImportError.

- [ ] **Step 3: The pure reconciliation**

`core/src/fantaclaude/asta/transfer.py`:

```python
"""The lega's rosters against the mirrored auction (spec, open question 9).

Teams are matched by roster overlap, never by name: four of ten FantaAstaLive
labels matched no lega owner on 2026-09-03. The diff is never literally
clean, so what is tolerated is named -- a lega team overlapping no mirror
roster is "not in the room" (the eleventh registered team) and fine when
empty; a player the lega added after the close at the session's minimum bid
is "added after the room"; an id the listone lacks reconciles by id. A cost
that differs, a mirror pick the lega lacks, or a dear extra fails the check.
The mirror's `me` reconciles with exactly one lega team: that is the
`my_team` leaf `league.yml` needs (open question 17).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeamDiff:
    mirror_team_id: int
    mirror_label: str
    lega_team_id: int
    lega_team_name: str
    overlap: int
    mirror_size: int
    lega_size: int
    missing_in_lega: tuple[int, ...]
    cost_differences: tuple[tuple[int, int, int], ...]     # (player_id, mirror cost, lega cost)
    added_after_room: tuple[tuple[int, int], ...]          # (player_id, cost) at or under the minimum bid
    extra_in_lega: tuple[tuple[int, int], ...]             # (player_id, cost) above it

    @property
    def clean(self) -> bool:
        return not (self.missing_in_lega or self.cost_differences or self.extra_in_lega)

    def to_dict(self) -> dict[str, Any]:
        return {"mirror_team_id": self.mirror_team_id, "mirror_label": self.mirror_label,
                "lega_team_id": self.lega_team_id, "lega_team_name": self.lega_team_name, "overlap": self.overlap,
                "mirror_size": self.mirror_size, "lega_size": self.lega_size,
                "missing_in_lega": list(self.missing_in_lega),
                "cost_differences": [list(c) for c in self.cost_differences],
                "added_after_room": [list(a) for a in self.added_after_room],
                "extra_in_lega": [list(e) for e in self.extra_in_lega], "clean": self.clean}


@dataclass(frozen=True)
class Reconciliation:
    teams: tuple[TeamDiff, ...]
    lega_not_in_room: tuple[tuple[int, str, int], ...]     # (team_id, name, roster size)
    mirror_unmatched: tuple[tuple[int, str], ...]
    ambiguous: tuple[str, ...]
    my_team: tuple[int, str] | None

    @property
    def clean(self) -> bool:
        return (all(t.clean for t in self.teams) and not self.mirror_unmatched and not self.ambiguous
                and all(size == 0 for _, _, size in self.lega_not_in_room))


def reconcile(mirror: dict[int, dict[int, int]], lega: dict[int, dict[int, int]], *, me: int,
              labels: dict[int, str], names: dict[int, str], min_bid: int = 1) -> Reconciliation:
    pairs = sorted(((len(set(mp) & set(lp)), mid, lid) for mid, mp in mirror.items() for lid, lp in lega.items()),
                   key=lambda p: (-p[0], p[1], p[2]))
    used_mirror: set[int] = set()
    used_lega: set[int] = set()
    chosen: dict[int, int] = {}
    ambiguous: list[str] = []
    for overlap, mid, lid in pairs:
        if overlap == 0:
            break
        if mid in used_mirror or lid in used_lega:
            continue
        ties = [l2 for o2, m2, l2 in pairs if m2 == mid and o2 == overlap and l2 != lid and l2 not in used_lega]
        if ties:
            ambiguous.append(f"mirror team {mid} ({labels.get(mid, mid)}) overlaps lega teams {lid} and "
                             f"{', '.join(str(t) for t in ties)} equally ({overlap} players)")
        chosen[mid] = lid
        used_mirror.add(mid)
        used_lega.add(lid)
    teams: list[TeamDiff] = []
    for mid, lid in sorted(chosen.items()):
        mp, lp = mirror[mid], lega[lid]
        extra = [(pid, cost) for pid, cost in lp.items() if pid not in mp]
        teams.append(TeamDiff(
            mid, labels.get(mid, str(mid)), lid, names.get(lid, str(lid)), len(set(mp) & set(lp)), len(mp), len(lp),
            tuple(sorted(pid for pid in mp if pid not in lp)),
            tuple(sorted((pid, mp[pid], lp[pid]) for pid in mp if pid in lp and mp[pid] != lp[pid])),
            tuple(sorted((pid, cost) for pid, cost in extra if cost <= min_bid)),
            tuple(sorted((pid, cost) for pid, cost in extra if cost > min_bid))))
    not_in_room = tuple(sorted((lid, names.get(lid, str(lid)), len(lp)) for lid, lp in lega.items() if lid not in used_lega))
    unmatched = tuple(sorted((mid, labels.get(mid, str(mid))) for mid in mirror if mid not in used_mirror))
    mine = (chosen[me], names.get(chosen[me], str(chosen[me]))) if me in chosen else None
    return Reconciliation(tuple(teams), not_in_room, unmatched, tuple(ambiguous), mine)
```

- [ ] **Step 4: `verify_transfer` in `commands/asta.py`**

```python
from fantaclaude.asta.transfer import Reconciliation, reconcile        # with the module's imports


class TransferMismatch(RuntimeError):
    """--prune asked for on a diff that is not clean."""


@dataclass(frozen=True)
class VerifyReport:
    state_path: Path
    snapshot_id: int
    fetched_at: datetime
    result: Reconciliation
    names: dict[int, str]
    my_team_leaf: str | None
    pruned: bool

    def to_dict(self) -> dict[str, Any]:
        r = self.result
        return {"state": str(self.state_path), "roster_snapshot": self.snapshot_id,
                "rosters_fetched_at": self.fetched_at.isoformat(sep=" ", timespec="minutes"),
                "teams": [t.to_dict() for t in r.teams],
                "lega_not_in_room": [list(x) for x in r.lega_not_in_room],
                "mirror_unmatched": [list(x) for x in r.mirror_unmatched], "ambiguous": list(r.ambiguous),
                "my_team": None if r.my_team is None else {"lega_team_id": r.my_team[0], "name": r.my_team[1],
                                                             "leaf": self.my_team_leaf},
                "player_names": {str(k): v for k, v in self.names.items()},
                "clean": r.clean, "pruned": self.pruned}


def verify_transfer(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, state_file: Path | None = None,
                    prune: bool = False) -> VerifyReport:
    """The lega's latest roster snapshot against the mirrored auction. Reports;
    `--prune` deletes data/asta-state.json alone, on a clean diff, never a
    `--state` file and never anything under records/."""
    if prune and state_file is not None:
        raise UsageError("--prune removes data/asta-state.json only; it does not apply to a --state file")
    stored, path = _stored(paths, state_file, fresh=False)
    if stored is None:
        raise NotReady(f"no state file at {path} -- nothing mirrored to verify; pass --state records/asta/<file>.json")
    state = state_from_snapshot(stored.snapshot)
    mirror: dict[int, dict[int, int]] = {t.team_id: {} for t in stored.snapshot.teams}
    for pick in state.picks.values():
        mirror.setdefault(pick.team_id, {})[pick.player_id] = pick.cost
    labels = {t.team_id: t.label for t in stored.snapshot.teams}
    labels.update(stored.mapping.nicks)
    snapshot = con.execute("SELECT snapshot_id, fetched_at, teams FROM roster_snapshots "
                           "ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    if snapshot is None:
        raise NotReady("no roster snapshot -- run `fantaclaude ingest rosters` once the admin has transferred the auction")
    snapshot_id, fetched_at, teams_json = snapshot
    teams = json.loads(teams_json) if isinstance(teams_json, str) else teams_json
    lega: dict[int, dict[int, int]] = {int(t["id"]): {} for t in teams}      # every team, the empty ones included
    names: dict[int, str] = {int(t["id"]): str(t["name"]) for t in teams}
    for team_id, player_id, cost in con.execute(
            "SELECT team_id, player_id, cost FROM v_rosters_current").fetchall():
        lega.setdefault(int(team_id), {})[int(player_id)] = int(cost)
    if not any(lega.values()):
        raise NotReady("the lega's rosters are all empty -- the admin has not transferred the auction yet")
    settings = stored.snapshot.settings or {}
    min_bid = settings.get("minimumBid") if isinstance(settings.get("minimumBid"), int) else 1
    result = reconcile(mirror, lega, me=stored.mapping.mine, labels=labels, names=names, min_bid=min_bid)
    player_names = {int(pid): str(name) for pid, name in con.execute(
        "SELECT player_id, name FROM v_players_current").fetchall()}
    leaf = None
    if result.my_team is not None:
        leaf = (f"my_team:\n  value: {result.my_team[0]}\n  source: verify-transfer\n"
                f"  verified_on: {utc_now():%Y-%m-%d}\n  note: {result.my_team[1]} -- the lega team the mirror's "
                f"'me' reconciled with, player for player")
    pruned = False
    if prune:
        if not result.clean:
            raise TransferMismatch("the diff is not clean (see `asta verify-transfer` without --prune); "
                                   "nothing deleted")
        path.unlink()
        pruned = True
    return VerifyReport(path, int(snapshot_id), fetched_at, result, player_names, leaf, pruned)
```

`import json` joins the module's imports. An empty lega team has no `rosters` row, which is why the team list comes from `roster_snapshots.teams` (Task 7 writes it) and not from the rows: the eleventh registered team must show up as "not in the room, 0 players", not vanish.

- [ ] **Step 5: The command in `cli/app.py`**

After `asta_close_cmd`:

```python
PRUNE_OPTION = typer.Option(False, "--prune", help="On a clean diff, delete data/asta-state.json (never records/).")


def _render_verify(payload: dict) -> str:
    names = payload["player_names"]
    who = lambda pid: names.get(str(pid), f"#{pid}")
    lines = [f"state {payload['state']} · rosters snapshot {payload['roster_snapshot']} ({payload['rosters_fetched_at']} UTC)"]
    for t in payload["teams"]:
        status = "ok" if t["clean"] else "DIFFERS"
        lines.append(f"{status:8} {t['mirror_label']} (room {t['mirror_team_id']}) = {t['lega_team_name']} (lega {t['lega_team_id']}) "
                     f"· {t['overlap']} shared of {t['mirror_size']}/{t['lega_size']}")
        lines += [f"         missing in the lega: {who(p)}" for p in t["missing_in_lega"]]
        lines += [f"         cost differs: {who(p)} room {a} lega {b}" for p, a, b in t["cost_differences"]]
        lines += [f"         added after the room: {who(p)} for {c}" for p, c in t["added_after_room"]]
        lines += [f"         extra in the lega: {who(p)} for {c}" for p, c in t["extra_in_lega"]]
    lines += [f"not in the room: {name} (lega {tid}, {size} players)" for tid, name, size in payload["lega_not_in_room"]]
    lines += [f"UNMATCHED room team {tid} ({label})" for tid, label in payload["mirror_unmatched"]]
    lines += [f"AMBIGUOUS {a}" for a in payload["ambiguous"]]
    if payload["my_team"]:
        lines.append(f"my team in the lega: {payload['my_team']['name']} ({payload['my_team']['lega_team_id']}) -- add to league.yml:")
        lines.append(payload["my_team"]["leaf"])
    lines.append("clean: the lega matches the room" if payload["clean"] else "NOT CLEAN: see above")
    if payload["pruned"]:
        lines.append("pruned data/asta-state.json; records/ untouched")
    return "\n".join(lines)


@asta_app.command("verify-transfer")
def asta_verify_transfer_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    state: Path | None = STATE_OPTION,
    prune: bool = PRUNE_OPTION,
) -> None:
    """Check the lega's rosters against the mirrored auction -- teams matched by roster overlap, never by name -- and name my lega team. Local; run `fantaclaude ingest rosters` first."""
    from fantaclaude.commands.asta import TransferMismatch, verify_transfer

    paths = _asta_paths()
    with _asta_errors():
        con = _open_read_only(paths.db)
        try:
            try:
                report = verify_transfer(con, paths=paths, state_file=state, prune=prune)
            except TransferMismatch as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=ExitCode.CONFLICT) from None
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_verify)
```

`_open_read_only` is the helper the other asta commands use to open `paths.db`; if its name differs in `app.py`, use theirs.

- [ ] **Step 6: Run, expect green; suite; lint**

`uv run pytest core/tests/test_transfer.py core/tests/test_asta_cli.py -c core/pyproject.toml -q && uv run poe lint`

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/asta/transfer.py core/src/fantaclaude/commands/asta.py core/src/fantaclaude/cli/app.py core/tests/test_transfer.py core/tests/test_asta_cli.py
git commit -m "feat(asta): verify-transfer -- the lega against the room by roster overlap, my_team named, --prune on clean"
```

---

### Task 10: `asta market-prices`

**Files:**
- Modify: `core/src/fantaclaude/commands/asta.py` (add `MarketReport`, `market_prices`)
- Modify: `core/src/fantaclaude/cli/app.py` (the command and its renderer)
- Test: `core/tests/test_asta_cli.py`

**Interfaces:**
- Consumes: `v_market_prices`, `v_rosters_first` (Task 2), `seed_rosters` (Task 7), `read_state` (`asta/snapshot.py`), `newest_run_id` (`asta/pinned.py`).
- Produces:
  - `market_prices(con, *, paths, run_id=None, scenario=None) -> MarketReport`; `.to_dict()` keys `run_id, scenario, source (how the pair was chosen), snapshot_id, classes: [{role_class, players, paid, expected, paid_over_expected, quotazione, paid_over_quotazione}], overall: {...same keys}, unpriced: {players, paid}`
  - `fantaclaude asta market-prices [--run ID] [--scenario NAME] [--json]`

- [ ] **Step 1: The failing test**

Append to `core/tests/test_asta_cli.py`:

```python
def test_market_prices_reports_paid_over_expected_per_class_for_the_run_the_night_was_priced_against(
        monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    run_id = _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    prices = {pid: (cls, exp) for pid, cls, exp in con.execute(
        "SELECT player_id, role_class, expected_price FROM valuation_prices WHERE run_id = ? AND scenario = 'balanced'", [run_id]).fetchall()}
    pids = sorted(prices)
    # the earliest non-empty snapshot is the auction; a later one (a mid-season swap) must not move the numbers
    seed_rosters(con, 2578630, 21, {1: ("A", {pids[0]: 100, pids[1]: 50, 795: 3}), 2: ("B", {pids[2]: 20})})
    seed_rosters(con, 2578630, 21, {1: ("A", {pids[0]: 100, pids[3]: 999}), 2: ("B", {pids[2]: 20})})
    con.close()
    result = runner.invoke(app, ["asta", "market-prices", "--run", run_id, "--scenario", "balanced", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == run_id and payload["scenario"] == "balanced" and payload["source"] == "--run/--scenario"
    assert payload["overall"]["players"] == 3 and payload["overall"]["paid"] == 170
    expected = sum(prices[p][1] for p in pids[:3])
    assert payload["overall"]["expected"] == expected
    assert payload["overall"]["paid_over_expected"] == pytest.approx(170 / expected) if expected else payload["overall"]["paid_over_expected"] is None
    assert payload["unpriced"] == {"players": 1, "paid": 3}
    assert {c["role_class"] for c in payload["classes"]} == {prices[p][0] for p in pids[:3]}
    # without flags: the pair the newest closing state under records/asta names
    assert runner.invoke(app, ["asta", "replay", str(FIXTURE), "--me", "1", "--write-state"]).exit_code == ExitCode.OK
    assert runner.invoke(app, ["asta", "close", "--session", "FA-test"]).exit_code == ExitCode.OK
    defaulted = json.loads(runner.invoke(app, ["asta", "market-prices", "--json"]).stdout)
    assert defaulted["run_id"] == run_id and defaulted["source"].startswith("records/asta/FA-test")
    plain = runner.invoke(app, ["asta", "market-prices"])
    assert plain.exit_code == ExitCode.OK and "paid/expected" in plain.stdout and "unpriced" in plain.stdout


def test_market_prices_needs_an_auction_in_the_rosters(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["asta", "market-prices"])
    assert result.exit_code == ExitCode.NOT_READY and "ingest rosters" in result.stderr
```

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_asta_cli.py -k market_prices -c core/pyproject.toml -q`

- [ ] **Step 3: `market_prices` in `commands/asta.py`**

```python
@dataclass(frozen=True)
class MarketReport:
    run_id: str
    scenario: str
    source: str
    snapshot_id: int
    classes: list[dict[str, Any]]
    overall: dict[str, Any]
    unpriced: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "scenario": self.scenario, "source": self.source, "snapshot_id": self.snapshot_id,
                "classes": list(self.classes), "overall": dict(self.overall), "unpriced": dict(self.unpriced)}


def _ratio(num: float, den: float) -> float | None:
    return None if not den else num / den


def _newest_closing_state(records_dir: Path) -> Path | None:
    files = sorted(p for p in (records_dir / "asta").glob("*.json") if not p.name.endswith("-bids.json"))
    return files[-1] if files else None


def market_prices(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, run_id: str | None = None,
                  scenario: str | None = None) -> MarketReport:
    """What the room paid over what the run expected, per class, off the
    earliest non-empty roster snapshot of the season (spec: `v_market_prices`).
    The run and scenario default to the pair the newest closing state under
    records/asta names -- the board the night was priced against."""
    source = "--run/--scenario"
    if run_id is None or scenario is None:
        record = _newest_closing_state(paths.records)
        if record is not None:
            stored = read_state(record)
            run_id, scenario = run_id or stored.run_id, scenario or stored.scenario
            source = record.relative_to(paths.records.parent).as_posix() if record.is_relative_to(paths.records.parent) else str(record)
    if run_id is None:
        run_id = newest_run_id(con)
        source = "the newest run"
        if run_id is None:
            raise NotReady("no valuation run -- run `fantaclaude rank`")
    if scenario is None:
        row = con.execute("SELECT scenarios[1] FROM valuation_runs WHERE run_id = ?", [run_id]).fetchone()
        if row is None:
            raise NotReady(f"run {run_id!r} is not in valuation_runs")
        scenario = str(row[0])
    first = con.execute("SELECT min(snapshot_id) FROM v_rosters_first").fetchone()[0]
    if first is None:
        raise NotReady("no roster snapshot with players -- run `fantaclaude ingest rosters` once the admin has transferred the auction")
    rows = con.execute(
        "SELECT role_class, count(*), sum(paid), sum(expected_price), sum(coalesce(quot_mantra, 0)) FROM v_market_prices "
        "WHERE run_id = ? AND scenario = ? GROUP BY role_class ORDER BY role_class", [run_id, scenario]).fetchall()
    classes = [{"role_class": cls, "players": int(n), "paid": int(paid), "expected": int(exp),
                "paid_over_expected": _ratio(paid, exp), "quotazione": int(quot),
                "paid_over_quotazione": _ratio(paid, quot)} for cls, n, paid, exp, quot in rows]
    n, paid, exp, quot = (sum(c[k] for c in classes) for k in ("players", "paid", "expected", "quotazione"))
    overall = {"players": n, "paid": paid, "expected": exp, "paid_over_expected": _ratio(paid, exp),
               "quotazione": quot, "paid_over_quotazione": _ratio(paid, quot)}
    unpriced = con.execute(
        "SELECT count(*), coalesce(sum(cost), 0) FROM v_rosters_first f WHERE f.player_id NOT IN "
        "(SELECT player_id FROM valuation_prices WHERE run_id = ? AND scenario = ?)", [run_id, scenario]).fetchone()
    return MarketReport(run_id, scenario, source, int(first), classes, overall,
                        {"players": int(unpriced[0]), "paid": int(unpriced[1])})
```

`read_state` and `newest_run_id` are already imported in `commands/asta.py`.

- [ ] **Step 4: The command in `cli/app.py`**

```python
def _render_market(payload: dict) -> str:
    def line(c: dict, label: str) -> str:
        pe = "-" if c["paid_over_expected"] is None else f"{c['paid_over_expected']:.2f}"
        pq = "-" if c["paid_over_quotazione"] is None else f"{c['paid_over_quotazione']:.2f}"
        return f"  {label:8} {c['players']:3} players · paid {c['paid']:5} · expected {c['expected']:5} · paid/expected {pe} · paid/quot {pq}"
    lines = [f"run {payload['run_id']} · scenario {payload['scenario']} · from {payload['source']} · roster snapshot {payload['snapshot_id']}"]
    lines += [line(c, c["role_class"]) for c in payload["classes"]]
    lines.append(line(payload["overall"], "all"))
    lines.append(f"  unpriced: {payload['unpriced']['players']} player(s) the run never priced, {payload['unpriced']['paid']} credits")
    lines.append("a per-class multiplier belongs in pricing.yml, by hand: that file feeds model_hash")
    return "\n".join(lines)


@asta_app.command("market-prices")
def asta_market_prices_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
) -> None:
    """What the room paid over what the run expected, per class, off the earliest roster snapshot of the season. Defaults to the run and scenario the newest closing state under records/asta names. Local."""
    from fantaclaude.commands.asta import market_prices

    paths = _asta_paths()
    with _asta_errors():
        con = _open_read_only(paths.db)
        try:
            report = market_prices(con, paths=paths, run_id=run, scenario=scenario)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_market)
```

- [ ] **Step 5: Run, expect green; lint**

`uv run pytest core/tests/test_asta_cli.py -c core/pyproject.toml -q && uv run poe lint`

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/commands/asta.py core/src/fantaclaude/cli/app.py core/tests/test_asta_cli.py
git commit -m "feat(asta): market-prices -- paid over expected per class, off the auction's roster snapshot"
```

---

### Task 11: The penalty-rate fallback, shipped as model 3

**Files:**
- Modify: `core/src/fantaclaude/analysis/history.py` (`History`, the tail of `load_history`)
- Modify: `core/src/fantaclaude/analysis/projection.py` (`PlayerInputs.club_penalty_rate_season`, the explain dict)
- Modify: `core/src/fantaclaude/analysis/valuation.py` (`MODEL_VERSION`, the warning in `build_inputs`, the `PlayerInputs` construction)
- Test: `core/tests/test_history.py`, `core/tests/test_valuation.py`

**Interfaces:**
- Produces:
  - `History.club_penalty_rate: dict[str, float]` now holds every club named in any completed back season, zeroes included, each at the rate of its **most recent** completed season; `History.penalty_rate_season: dict[str, int]`; `History.league_penalty_rate: float | None` (the mean over the clubs of `last_back`)
  - `History.penalty_rate(team) -> float | None` returns the club's own rate, else the league average, else None (no completed season at all); `History.penalty_rate_source(team) -> int | None` — the season, or None for the league average
  - `PlayerInputs.club_penalty_rate_season: int | None`; `Projection.explain["penalty_rate_season"]`
  - `valuation.MODEL_VERSION = "3"`

- [ ] **Step 1: The failing tests**

In `core/tests/test_history.py`, extend `_seed` with a season the history reads as older (season 19 exists in `back_seasons(21, 3)`) naming a club that season 20 does not:

```python
    # season 19: Venezia played it and took two penalties in two giornate; Roma took one
    seed_voti(db, 19, 1, [(4001, "Pohjanpalo", "Venezia", "A", 7.0, {"pen_scored": 1}),
                          (5841, "Svilar", "Roma", "P", 6.0, {})])
    seed_voti(db, 19, 2, [(4001, "Pohjanpalo", "Venezia", "A", 6.5, {"pen_missed": 1}),
                          (5841, "Svilar", "Roma", "P", 6.0, {"pen_saved": 1}),
                          (4002, "Dybala", "Roma", "A", 7.0, {"pen_scored": 1})])
```

and replace the penalty assertions of `test_role_priors_and_club_penalties_come_from_the_back_seasons` with:

```python
    # the most recent completed season a club appears in decides its rate (open question 11)
    assert history.club_penalty_rate == {"Inter": pytest.approx(1 / 3), "Atalanta": pytest.approx(1 / 3),
                                         "Roma": 0.0, "Lazio": 0.0, "Venezia": pytest.approx(1.0)}
    assert history.penalty_rate_season == {"Inter": 20, "Atalanta": 20, "Roma": 20, "Lazio": 20, "Venezia": 19}
    assert history.penalty_rate("Inter") == pytest.approx(1 / 3) and history.penalty_rate_source("Inter") == 20
    assert history.penalty_rate("Roma") == 0.0 and history.penalty_rate_source("Roma") == 20     # season 20 wins over 19
    assert history.penalty_rate("Venezia") == pytest.approx(1.0) and history.penalty_rate_source("Venezia") == 19
    # a club in no completed season at all: the league average over last_back's clubs, and no season
    assert history.league_penalty_rate == pytest.approx((1 / 3 + 1 / 3 + 0.0 + 0.0) / 4)
    assert history.penalty_rate("Frosinone") == pytest.approx(history.league_penalty_rate)
    assert history.penalty_rate_source("Frosinone") is None
```

Add to `test_an_empty_history_is_empty_not_broken`: `assert history.penalty_rate("Inter") is None and history.league_penalty_rate is None`.

Check the role-prior assertions in that test still hold with season 19 seeded (the `A` prior now has more rows: recompute the expected `rows`, means and `presenze_rate` from the seeded votes, or seed season 19 in a separate fixture used only by the penalty test — the second is simpler: a `_seed_with_19(db)` that calls `_seed(db)` then adds the two giornate, used by a new `test_penalty_rate_falls_back_to_the_clubs_own_older_season_then_the_league_average`).

In `core/tests/test_valuation.py::test_new_run_id_and_model_version` add `assert MODEL_VERSION == "3"`. And one explain assertion where a projection's explain dict is already inspected (search the file for `"rate_source"`): `assert "penalty_rate_season" in projection.explain`.

- [ ] **Step 2: Run, expect failure**

`uv run pytest core/tests/test_history.py core/tests/test_valuation.py -c core/pyproject.toml -q`

- [ ] **Step 3: `history.py`**

Replace the `History` fields `club_penalty_rate`/`penalty_rate_clubs` and the `penalty_rate` method with:

```python
    # Every club named in any completed back season, zeroes included, at the
    # rate of the most recent completed season naming it (open question 11): a
    # promoted club's own history is the closest evidence, and only a club in
    # no completed season at all falls back to the league average.
    club_penalty_rate: dict[str, float] = field(default_factory=dict)
    penalty_rate_season: dict[str, int] = field(default_factory=dict)
    league_penalty_rate: float | None = None

    def penalty_rate(self, team: str) -> float | None:
        """The club's own penalties per giornata, else the league average, else
        None when no completed season is ingested at all."""
        return self.club_penalty_rate.get(team, self.league_penalty_rate)

    def penalty_rate_source(self, team: str) -> int | None:
        """The season the rate was read from; None for the league average."""
        return self.penalty_rate_season.get(team)
```

`penalty_rate_clubs` is removed; `valuation.py` is its only reader (below). Replace the last block of `load_history`:

```python
    completed = sorted(s for s in seasons if s != current_season and giornate.get(s))
    club_rate: dict[str, float] = {}
    rate_season: dict[str, int] = {}
    for season in completed:                          # ascending: the most recent season naming a club wins
        for team, n in club_penalties[season].items():
            club_rate[team] = n / giornate[season]
            rate_season[team] = season
    last_back = completed[-1] if completed else None
    league_rate = (fmean(n / giornate[last_back] for n in club_penalties[last_back].values())
                   if last_back is not None and club_penalties[last_back] else None)
    return History(sheet=sheet, current_season=current_season, seasons=seasons, giornate=giornate,
                   lines={pid: tuple(ls) for pid, ls in lines.items()}, priors=priors, club_penalty_rate=club_rate,
                   penalty_rate_season=rate_season, league_penalty_rate=league_rate)
```

Note `club_penalties[season]` is a `defaultdict(int)` that names every club with a row that season, zero-penalty clubs included, because the `+=` runs before the senza-voto `continue`.

- [ ] **Step 4: `projection.py`**

Add the field after `club_penalty_rate`:

```python
    club_penalty_rate_season: int | None = None      # the season the rate came from; None = league average
```

and in the `explain` dict of `project_player`, next to `"rate_source": source`: `"penalty_rate_season": inp.club_penalty_rate_season,`.

- [ ] **Step 5: `valuation.py`**

`MODEL_VERSION = "3"` with the comment updated: `# "3" since 2026-09-04: the club penalty rate falls back to the club's own most recent completed season, then to the league average (open question 11). "2" carried the appearance-rate prior.`

In `build_inputs`, replace the `team_name not in history.penalty_rate_clubs` branch with:

```python
        if match.player_id is not None and history.penalty_rate_source(team_name) is None:
            rate = history.penalty_rate(team_name)
            warnings.append(f"{profile.team}: the voti history never names {team_name!r} (promoted, renamed, or spelled "
                            f"differently there); its penalty taker {name!r} is priced on the league-average rate "
                            f"{'-' if rate is None else f'{rate:.2f}'} per giornata. Fix the spelling if the club is only "
                            f"spelled differently")
```

and in the `PlayerInputs(...)` construction add `club_penalty_rate_season=history.penalty_rate_source(str(team_name))`.

- [ ] **Step 6: Run, expect green; the whole suite; lint**

`uv run poe test-core && uv run poe lint`. A test elsewhere that pinned the old warning text ("changes nothing") or `penalty_rate_clubs` moves to the new wording.

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/analysis/history.py core/src/fantaclaude/analysis/projection.py core/src/fantaclaude/analysis/valuation.py core/tests/test_history.py core/tests/test_valuation.py
git commit -m "feat(model): model 3 -- a club's penalty rate falls back to its own older season, then the league average"
```

---

### Task 12: Docs — README, records, the skills, the path docstring

**Files:**
- Modify: `README.md`, `records/README.md`, `.claude/skills/fanta-asta/SKILL.md`, `.claude/skills/fanta-market/SKILL.md`, `core/src/fantaclaude/paths.py`

- [ ] **Step 1: README.md**

In "Capabilities": extend the Ingestion bullet to end `…, per-giornata votes, the probabili formazioni page (public), the lega's rosters and purchase prices — all deduped and re-runnable`; in the Auction bullet's command list add `verify-transfer|market-prices` and the phrase `the lega checked against the room by roster overlap, and what the room paid over what the run expected, per class`; add a bullet:

```markdown
- **Weekly (lineup)** — `fantaclaude lineup`: the giornata's forecast for every player the probabili page lists (published p_start × the pinned run's expected fantavoto), written before the first kickoff and never revised (`--late` marks a late one and calibration drops it), and, once `league.yml` names `my_team`, the XI and module that maximise expected points across the league's Mantra modules — an exact solve per module
```

In "Layout": the `core/` line gains `lineup` after `rank`; the `records/` line becomes `committed exports — valuations, league_settings, lineup_runs, predictions, asta/ state files and bid ladders`; the `data/` block gains `raw/probabili and raw/rosters`.

- [ ] **Step 2: records/README.md**

Add after the `league_settings` bullet:

```markdown
- `lineup_runs/<season>-<giornata>-<UTC stamp>.parquet` and
  `predictions/<same stem>.parquet` — one `fantaclaude lineup` invocation:
  the forecast it wrote (published `p_start`, expected fantavoto if he
  plays, their product) for every player the probabili page listed and the
  run priced, the deadline it was written against, whether it was late, and
  the XI and module when one was named. Never rewritten; several
  invocations before one deadline are several files, and calibration reads
  the latest non-late one per giornata.
```

- [ ] **Step 3: `.claude/skills/fanta-asta/SKILL.md`**

After the `close` mode, two modes:

```markdown
### `verify-transfer`

`fantaclaude asta verify-transfer [--state records/asta/<file>.json] [--prune]`
— once the admin has transferred the auction into the lega and
`fantaclaude ingest rosters` has run once, the lega's rosters against the
mirrored room. Teams are matched by roster overlap, never by name (four of
ten labels lied on 2026-09-03). The report names what it tolerates — a lega
team in no room roster ("not in the room", fine when empty), a player added
after the close at the minimum bid ("added after the room") — and what fails
it: a cost that differs, a room pick the lega lacks, a dear extra. It prints
my lega team as the `my_team` leaf for `league.yml`; paste it there. `--prune`
deletes `data/asta-state.json` on a clean diff and nothing else, never a
`--state` file and never `records/`.

### `market-prices`

`fantaclaude asta market-prices [--run <id>] [--scenario <name>]` — what the
room paid over what the run expected, per class, off the earliest roster
snapshot of the season; defaults to the run and scenario the newest closing
state under `records/asta/` names. Read it, then write a per-class
multiplier into `pricing.yml` by hand: that file feeds `model_hash`, so the
command never does.
```

- [ ] **Step 4: `.claude/skills/fanta-market/SKILL.md`**

One paragraph under whichever section discusses re-running under stated constraints: "After an auction, `fantaclaude asta market-prices` reports paid over expected per class for the run the night was priced against (2026-27: Pc about 1.25, C near parity, A/M/Por 0.75–0.8, Dc/E/W about 0.63). A per-class multiplier goes into `pricing.yml` by hand and is a new model."

- [ ] **Step 5: `paths.py`**

`asta_state_path`'s docstring: `"""data/asta-state.json: the mirrored auction as last seen, written atomically; removed only by `asta verify-transfer --prune` on a clean diff (3a). The copy under records/asta/ is permanent."""`

- [ ] **Step 6: Commit**

```bash
git add README.md records/README.md .claude/skills/fanta-asta/SKILL.md .claude/skills/fanta-market/SKILL.md core/src/fantaclaude/paths.py
git commit -m "docs: lineup, ingest probabili/rosters, verify-transfer and market-prices in the README and the skills"
```

---

### Task 13: Field giornata 3 — the operational run

Not code: the commands, in order, each live one run once. Steps 1–2 are the
deadline path and are run as soon as Task 5 is green, even if Tasks 6–12 are
not started; the rest follow when their task has landed.

- [ ] **Step 1: The page (public, one request) — before 18:45 UTC on 2026-09-04**

```bash
uv run fantaclaude ingest probabili
```

Expected: `probabili 21 giornata 3: file 1, ~300 players over 10 compiled match(es) (...)`. If it reports matches not yet compiled on a Friday afternoon, that is the page, not a bug; the forecast covers what is compiled.

- [ ] **Step 2: The forecast — before 18:45 UTC**

```bash
uv run fantaclaude lineup
git add records/lineup_runs records/predictions && git commit -m "records: the giornata 3 forecast"
```

Expected: `giornata 3 · deadline 2026-09-04 18:45 UTC · run 20260904T091947Z-7694bd6a …`, the top rows per role, `XI: none -- league.yml has no my_team leaf`, `written: lineup_run 1, ~300 predictions`. If the clock has passed 18:45 UTC, run `uv run fantaclaude lineup --late` instead: the row is marked and giornata 4 is the first clean point. Compose the giornata 3 XI by hand from the per-role lines, on the platform.

- [ ] **Step 3: The rosters (live, once) and the transfer check — after Task 9**

```bash
uv run fantaclaude ingest rosters
uv run fantaclaude asta verify-transfer
```

Expected: ten matched teams, `not in the room: <the eleventh> (…, 0 players)`, two teams with one player each under "added after the room", `clean: the lega matches the room`, and the `my_team:` leaf. Paste the leaf into `league.yml` under the existing leaves. Then, and only if the report was clean:

```bash
uv run fantaclaude asta verify-transfer --prune
git status                       # records/asta/ untouched; data/asta-state.json gone
```

- [ ] **Step 4: The XI — after Task 8 and Step 3**

```bash
uv run fantaclaude lineup
```

Expected: the same forecast (a second `lineup_runs` row, late by now if it is past the deadline — pass `--late`) and `XI: <module> · expected <n>` with eleven lines. From giornata 4 on this is the Friday command.

- [ ] **Step 5: Model 3 and the market — after Tasks 10 and 11**

```bash
uv run fantaclaude rank --offline
git add records && git commit -m "records: model 3 -- the penalty-rate fallback"
uv run fantaclaude asta market-prices
```

Expected from `market-prices`: per-class paid/expected in the neighbourhood the spec quotes for 2026-27 (Pc ≈ 1.25, C ≈ 0.95, A/M/Por ≈ 0.75–0.8, Dc/E/W ≈ 0.63) and one unpriced player (795, 3 credits). Do not write a multiplier into `pricing.yml` in this phase; the number is now a query, which was the point.

- [ ] **Step 6: The early-week capture — Tuesday 8 September**

One more request, so the "not yet compiled" test runs against a real page rather than a rewritten one:

```bash
uv run fantaclaude ingest probabili            # giornata 4, Tuesday: some matches uncompiled
cp "$(ls -t data/raw/probabili/*-probabili-21-04.html | head -1)" captured/probabili-2026-27-giornata-4-tuesday.html
```

Then extend `_extract_probabili.py` to emit `probabili_uncompiled_sample.html` from it (one compiled card, one uncompiled), and point `test_an_uncompiled_match_is_skipped_and_counted_not_fatal` at that fixture instead of the rewritten sample. Commit as `test(fixtures): a probabili page with an uncompiled match`.

---

## Self-review

**Spec coverage.** Schema rows for 3a — Task 2. `probabili` adapter, capture, fixture, skip-uncompiled — Tasks 1, 3, 13.6. `lineup_runs`/`predictions` columns, published beside blend, several rows per deadline, refused after the first kickoff unless `--late`, `late` by the clock — Tasks 2, 4. Predictions for every listed priced player, not my roster — Task 4 (`forecast`), asserted in Task 5's CLI test. The round and deadline off `fixtures`, `mday`/`mstr` carried per roster snapshot and cross-checked by `lineup` — Tasks 4, 7, 8 (`matchday_cross_check`). `assign_weighted` exact, brute-force oracle — Task 6. `my_team` leaf, `verify-transfer` prints it, `lineup` reads it — Tasks 8, 9. `rosters_api` as its own command, empty strings, `crs` warning, emails scrubbed, id 795 kept — Task 7. Tolerances of `verify-transfer`, `--prune` on the working file only — Task 9. `v_market_prices` with `run_id`/`scenario` as columns, `asta market-prices` with defaults from the closing state — Tasks 2, 10. Open question 11 with `MODEL_VERSION` 3 and the season in explain — Task 11. Records for forecasts — Task 4. Docs and the permanent records copy — Task 12. The order within 3a and the deadline — Global Constraints and Task 13.

**Placeholders.** The three `# from the fixture` literals in Task 3's first test are the one deliberate blank, filled from the capture in Task 1 — a page nobody has parsed yet cannot have its first player's id typed in advance. Everything else is written out.

**Type consistency.** `ForecastRow` is defined in Task 4 and consumed by Tasks 5 and 8 with the same fields; `Round.first_kickoff` is naive UTC everywhere; `write_lineup_run(..., round_=...)` uses the trailing underscore in every call; `record_rosters(con, payload, raw, *, league_id)` in Task 7 is what Task 7's CLI calls; `reconcile(mirror, lega, *, me, labels, names, min_bid)` in Task 9 matches its tests; `seed_rosters(con, league_id, season_id, teams, *, matchday=None)` is the same in Tasks 7, 8, 9, 10; `roster_snapshots.teams` (added in Task 2's DDL) is written by Task 7 and read by Task 9.
