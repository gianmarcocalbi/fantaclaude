# Phase 3c — Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every finished giornata on read — my week as the platform calculated it beside the best eleven my roster had and the model's XI, the `p_start` reliability curve, the fantavoto bias, and the platform's own scores checked against the voti — and draft the journal entry from it.

**Architecture:** The lineup read-back (`ingest lineup`) already carries the platform's calculated scoring of my match; schema 6 records it (`match_files`, `match_scores`) from the same single read, and `--from-disk` records it from raw files already on disk. `fantaclaude calibrate` is a new local, read-only command over a new `analysis/calibration/` package that computes everything from immutable inputs on every call and stores nothing. `doctor` gains the platform check on `scoring` and a never-failing `journal` notice; the `fanta-manager` refresh runs the read-back, `calibrate`, and drafts the entry.

**Tech Stack:** Python 3.12, DuckDB, Typer, pytest; the uv workspace (`uv run poe test`, `uv run poe lint`, `uv run poe docs-build`).

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` — "Calibration: what 3c ships" (under `fanta-manager`), the schema table's "Observed (Phase 3c)" and "Derived" rows, the Testing bullets marked (3c), the Phasing row for 3c, open questions 19 and 20.

## Global Constraints

- **No network, anywhere in this plan's code paths under test.** Tests use `FakeAPI` and seeded tables. `calibrate` and `ingest lineup --from-disk` make no request. Do not run `ingest lineup` (without `--from-disk`), `ingest stats-web`, `ingest probabili`, `ingest news`, `sync-league` or `rank` without `--offline` while implementing — they hit a real account or public hosts (CLAUDE.md).
- **`calibrate` opens the database read-only** (`_open_read_only`) and writes nothing — no table, no parquet, no file.
- **Fixtures are regenerated, never hand-edited:** `core/tests/fixtures/_extract_lineup.py` builds them from `captured/` (gitignored).
- **Secret-scanning checks assert shapes, never values:** no `@`, no `eyJhbGci` — never a literal credential.
- **Commit messages carry no Claude session link, no `Co-Authored-By: Claude`, no "Generated with Claude Code"** (CLAUDE.md overrides any harness default).
- **Match the surrounding code:** a module docstring that cites the spec section it implements, frozen dataclasses with `to_dict`, `from __future__ import annotations`, the repo's long-line style (ruff runs only its default rule set; there is no line-length gate).
- **Exit codes:** `0` ok, `1` error, `2` usage, `3` not ready (`ExitCode` in `core/src/fantaclaude/cli/app.py`).
- **The platform's sentinels, verbatim:** `scr` 56 with `cscr` 100 is a player absent from the voti sheet; `scr` 55 with `cscr` 100 a senza voto. A malus `m` is one point each (`ADAPTED_MALUS = 1.0`).
- Run tests with `uv run pytest core/tests/<file> -c core/pyproject.toml -q` (the core suite's own config); the whole suite is `uv run poe test`.

## File Structure

| File | Responsibility |
| --- | --- |
| `core/src/fantaclaude/db/schema.py` (modify) | Schema 6: `match_files`, `match_scores`, `v_match_files_current`, `v_match_scores_current` |
| `core/src/fantaclaude/ingest/raw.py` (modify) | `RawStore.on_disk(path, kind)` — a `RawFile` for a file already written |
| `core/src/fantaclaude/commands/ingest.py` (modify) | `_raw_file_from_disk` delegates to `RawStore.on_disk` |
| `core/src/fantaclaude/ingest/match_scores.py` (create) | Parse the calculated read-back; record it once per raw file; sweep `data/raw/lineup/` |
| `core/tests/fixtures/_extract_lineup.py` (modify) | Also extract `lineup_calculated_sample.json` from `captured/lineup-03-2026-09-22.json` |
| `core/src/fantaclaude/cli/app.py` (modify) | `ingest lineup` records the score and gains `--from-disk`; new `calibrate` command and its renderer |
| `core/src/fantaclaude/analysis/calibration/__init__.py` (create) | The facade: `calibrate()`, `CalibrationReport`, `calibration_giornate()` |
| `core/src/fantaclaude/analysis/calibration/errors.py` (create) | `CalibrationError`, `NothingToCalibrate` |
| `core/src/fantaclaude/analysis/calibration/actuals.py` (create) | `Actual`, `Scored`, `load_actuals`, `clubs_with_voti`, `load_scored` |
| `core/src/fantaclaude/analysis/calibration/pstart.py` (create) | `wilson`, `bin_index`, `reliability` → `PStartReport` |
| `core/src/fantaclaude/analysis/calibration/fantavoto.py` (create) | `fantavoto_bias` → `ModelBias`, `surprises` → `Surprise` |
| `core/src/fantaclaude/analysis/calibration/weeks.py` (create) | `best_xi`, `score_run_xi`, `roster_before`, `week` → `Week` |
| `core/src/fantaclaude/analysis/calibration/scoring_check.py` (create) | `check_scoring` → `ScoringCheck` (used by `calibrate` and `doctor`) |
| `core/src/fantaclaude/kb/journal.py` (create) | `season_dir`, `entry_path` — the journal's file names |
| `core/src/fantaclaude/commands/doctor.py` (modify) | `scoring` verified against the platform; new `journal` check |
| `core/tests/conftest.py` (modify) | `seed_listone`, `seed_lineup_run`, `events_for`, `seed_voti_matching` |
| `core/tests/test_schema.py`, `test_match_scores.py`, `test_lineup_cli.py`, `test_calibration_players.py`, `test_calibration_weeks.py`, `test_calibration_scoring.py`, `test_calibration.py`, `test_calibrate_cli.py`, `test_doctor.py` | Tests, one per unit |
| `.claude/skills/fanta-manager/SKILL.md`, `README.md`, `CLAUDE.md`, `site/docs/tools/cli.md`, `site/docs/using/the-week.md`, `site/docs/architecture/weekly.md` (modify) | The refresh reordered; the new command documented |
| `kb/league/season-2026-27/giornata-03.md`, `-04.md`, `-05.md` (create, Task 10) | The backlog's journal entries, drafted from `calibrate` |

---

### Task 1: Schema 6 — the platform's own scores

**Files:**
- Modify: `core/src/fantaclaude/db/schema.py` (docstring, `SCHEMA_VERSION`, the `DDL` string)
- Test: `core/tests/test_schema.py`

**Interfaces:**
- Produces: tables `match_files(file_id, season_id, giornata, competition_id, matchday, fetched_at, raw_path, sha256 UNIQUE, home_team, away_team, home_module, away_module, home_total, away_total, home_points, away_points, result, sign)` and `match_scores(file_id, team_id, player_id, part, position, status, voto, fantavoto, malus, events, raw)`; views `v_match_files_current` (newest file per season, giornata, competition, matchday, home, away) and `v_match_scores_current` (`season_id, giornata, ` then every `match_scores` column); `SCHEMA_VERSION == 6`.

- [ ] **Step 1: Bump the version assertions and write the failing tests**

Bump every schema-version literal in the existing tests (they assert what `apply_schema` returns, which becomes 6):

```bash
sed -i '' -e 's/apply_schema(con) == 5/apply_schema(con) == 6/g' \
          -e 's/SCHEMA_VERSION == 5/SCHEMA_VERSION == 6/g' \
          -e 's/WHERE version = 5"/WHERE version = 6"/g' \
          -e 's/fetchone()\[0\] == 5$/fetchone()[0] == 6/' core/tests/test_schema.py
grep -n "== 5\|version = 5" core/tests/test_schema.py    # expect: no output
```

Then, in `core/tests/test_schema.py`, add beside `V5_OBJECTS`:

```python
V6_OBJECTS = {"match_files", "match_scores", "v_match_files_current", "v_match_scores_current"}
```

and append these tests:

```python
def test_version_6_adds_the_platforms_own_scores(tmp_path):
    con = connect(tmp_path / "v6.duckdb")
    assert apply_schema(con) == 6 and SCHEMA_VERSION == 6
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
    assert V5_OBJECTS | V6_OBJECTS <= names
    assert _columns(con, "match_files") == ["file_id", "season_id", "giornata", "competition_id", "matchday", "fetched_at",
                                            "raw_path", "sha256", "home_team", "away_team", "home_module", "away_module",
                                            "home_total", "away_total", "home_points", "away_points", "result", "sign"]
    assert _columns(con, "match_scores") == ["file_id", "team_id", "player_id", "part", "position", "status", "voto",
                                             "fantavoto", "malus", "events", "raw"]
    assert _columns(con, "v_match_scores_current")[:3] == ["season_id", "giornata", "file_id"]
    assert apply_schema(con) == 6
    assert con.execute("SELECT count(*) FROM schema_version WHERE version = 6").fetchone()[0] == 1
    con.close()


def test_a_version_5_file_upgrades_in_place_and_keeps_its_rows(tmp_path):
    """The live database is at schema 5 with three platform read-backs in
    lineup_submitted; upgrading adds the two tables and touches nothing else."""
    con = connect(tmp_path / "v5.duckdb")
    apply_schema(con)
    for statement in ("DROP VIEW v_match_scores_current", "DROP VIEW v_match_files_current", "DROP TABLE match_scores",
                      "DROP TABLE match_files", "DROP SEQUENCE seq_match_files", "DELETE FROM schema_version",
                      "INSERT INTO schema_version (version) VALUES (5)"):
        con.execute(statement)
    con.execute("INSERT INTO lineup_submitted (season_id, giornata, module, xi, bench, source, recorded_at) "
                "VALUES (21, 3, '3421', '[]', '[]', 'platform', now())")
    assert apply_schema(con) == 6
    assert con.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM match_files").fetchone()[0] == 0
    assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 6
    con.close()


def test_v_match_files_current_keeps_the_newest_file_per_match(db):
    for sha, total in (("a", 60.0), ("b", 67.0)):
        db.execute("INSERT INTO match_files (season_id, giornata, competition_id, matchday, fetched_at, raw_path, sha256, "
                   "home_team, away_team, home_total, away_total, home_points, away_points) "
                   "VALUES (21, 3, 539860, 1, now(), ?, ?, 1, 2, 80.0, ?, 3, 0)", [f"raw/{sha}", sha, total])
    assert db.execute("SELECT away_total FROM v_match_files_current").fetchall() == [(67.0,)]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest core/tests/test_schema.py -c core/pyproject.toml -q`
Expected: FAIL — `apply_schema` returns 5, and `match_files` does not exist.

- [ ] **Step 3: Implement schema 6**

In `core/src/fantaclaude/db/schema.py`, append to the module docstring's version history (after the "Version 5 (Phase 3b)…" paragraph, before "The DDL is additive…"):

```
Version 6 (Phase 3c) adds the platform's own scoring of a lega match, read
back with the XI from the same response: match_files, one row per calculated
read-back (unique by the raw file's sha256), and match_scores, one row per
listed player per side -- voto, fantavoto and malus as the platform
calculated them, a missing voto as a status. Additive, like every version
before it.
```

Set `SCHEMA_VERSION = 6`.

In `DDL`, directly after the `CREATE TABLE IF NOT EXISTS lineup_submitted (...);` statement, add:

```sql
CREATE SEQUENCE IF NOT EXISTS seq_match_files START 1;
CREATE TABLE IF NOT EXISTS match_files (
    file_id        INTEGER PRIMARY KEY DEFAULT nextval('seq_match_files'),
    season_id      INTEGER NOT NULL,
    giornata       INTEGER NOT NULL,
    competition_id INTEGER NOT NULL,
    matchday       INTEGER NOT NULL,
    fetched_at     TIMESTAMP NOT NULL,
    raw_path       VARCHAR NOT NULL,
    sha256         VARCHAR NOT NULL UNIQUE,
    home_team      INTEGER NOT NULL,
    away_team      INTEGER NOT NULL,
    home_module    VARCHAR,
    away_module    VARCHAR,
    home_total     DOUBLE NOT NULL,
    away_total     DOUBLE NOT NULL,
    home_points    INTEGER NOT NULL,
    away_points    INTEGER NOT NULL,
    result         VARCHAR,
    sign           VARCHAR
);
CREATE TABLE IF NOT EXISTS match_scores (
    file_id    INTEGER NOT NULL,
    team_id    INTEGER NOT NULL,
    player_id  INTEGER NOT NULL,
    part       VARCHAR NOT NULL,
    position   INTEGER NOT NULL,
    status     VARCHAR NOT NULL,
    voto       DOUBLE,
    fantavoto  DOUBLE,
    malus      INTEGER NOT NULL,
    events     VARCHAR,
    raw        JSON NOT NULL,
    PRIMARY KEY (file_id, team_id, part, position)
);
```

and at the very end of `DDL`, after `v_lineup_submitted_current` and before the closing `"""`:

```sql
CREATE OR REPLACE VIEW v_match_files_current AS
    SELECT f.* FROM match_files f
    WHERE f.file_id = (SELECT max(g.file_id) FROM match_files g
                       WHERE g.season_id = f.season_id AND g.giornata = f.giornata
                         AND g.competition_id = f.competition_id AND g.matchday = f.matchday
                         AND g.home_team = f.home_team AND g.away_team = f.away_team);
CREATE OR REPLACE VIEW v_match_scores_current AS
    SELECT f.season_id, f.giornata, s.* FROM match_scores s JOIN v_match_files_current f USING (file_id);
```

(Keep the final statement's trailing `;` — `apply_schema` splits on `;` and skips empty pieces.)

- [ ] **Step 4: Run the schema tests, then the whole core suite**

Run: `uv run pytest core/tests/test_schema.py -c core/pyproject.toml -q` — Expected: PASS.
Run: `uv run pytest core/tests -c core/pyproject.toml -q` — Expected: PASS (the doctor's `database` check prints the version dynamically).

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/db/schema.py core/tests/test_schema.py
git commit -m "feat(db): schema 6 -- match_files and match_scores, the platform's own scoring of my match"
```

---

### Task 2: The calculated fixture and the match-scores parser

**Files:**
- Create: `captured/lineup-03-2026-09-22.json` (gitignored; a copy of a raw read-back)
- Modify: `core/tests/fixtures/_extract_lineup.py`
- Create: `core/tests/fixtures/lineup_calculated_sample.json` (generated)
- Modify: `core/src/fantaclaude/ingest/raw.py`, `core/src/fantaclaude/commands/ingest.py:282-288`
- Create: `core/src/fantaclaude/ingest/match_scores.py`
- Test: `core/tests/test_match_scores.py`

**Interfaces:**
- Consumes: schema 6 (Task 1); `RawFile`, `RawStore` (`ingest/raw.py`); `is_number` (`values.py`); `to_db` (`timeutil.py`).
- Produces (`fantaclaude.ingest.match_scores`): constants `ABSENT_SCR = 56`, `SV_SCR = 55`, `NO_CSCR = 100`, `STATUS_VOTO = "voto"`, `STATUS_SV = "sv"`, `STATUS_ABSENT = "absent"`; `class MatchScoresShapeError(ValueError)`; `class NoSeasonCalendar(RuntimeError)`; frozen dataclasses `PlayerScore(team_id, player_id, part, position, status, voto, fantavoto, malus, events, raw)`, `MatchScores(giornata, competition_id, matchday, home_team, away_team, home_module, away_module, home_total, away_total, home_points, away_points, result, sign, players)`, `RecordedMatch(raw_path, giornata, calculated, file_id, duplicate, players, home_team=None, away_team=None, home_total=None, away_total=None, result=None)` with `to_dict()`, `DiskSweep(files, before_season)` with `to_dict()`; functions `parse_match(payload) -> MatchScores | None`, `record_match(con, raw, payload, *, season_id) -> RecordedMatch`, `record_from_disk(con, store, *, season_id) -> DiskSweep`, `oriented_result(result: str | None, mine_home: bool) -> str | None` (the platform's `res`, home first, turned to my goals first — used by Tasks 3 and 5). `RawStore.on_disk(path: Path, kind: str) -> RawFile` (staticmethod).

- [ ] **Step 1: Capture the calculated read-back and extend the extractor**

```bash
cp data/raw/lineup/20260922T063456578004Z-lineup-19717181-03.json captured/lineup-03-2026-09-22.json
```

Replace `core/tests/fixtures/_extract_lineup.py` with (the first capture's handling is unchanged; the second is new):

```python
"""One-shot: build the two lineup fixtures from their captures in captured/.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_lineup.py

lineup_sample.json, from captured/lineup-03-2026-09-05.json: one teamLineup
response for giornata 3 taken mid-round (Phase 3b, Task 13, Step 1) -- `cal`
false, every `scr` 56, `b` null, a partial `tot`: the response a read-back
made before the platform calculates the round.

lineup_calculated_sample.json, from captured/lineup-03-2026-09-22.json: the
same match read back on 2026-09-22, after the round was calculated (Phase
3c) -- `cal` true, every listed player's `scr`/`cscr`/`m`/`b`, both sides'
`tot` and `points`, the match's `res` and `sign`. It is a raw file
`fantaclaude ingest lineup` wrote, copied as-is: already scrubbed with
`without_emails`.

Both keep the whole match, not only my own side: `load_lineup` and the
match-scores parser resolve which side is mine by team id, and a fixture
carrying only one side could never catch a version that instead assumed a
fixed position (Task 13's Ruling 2) -- my team being `away` in both is
exactly what makes that mistake visible.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
MY_TEAM = 19717181                # league.yml's my_team leaf
FIXTURES = (
    (ROOT / "captured" / "lineup-03-2026-09-05.json", HERE / "lineup_sample.json", False),
    (ROOT / "captured" / "lineup-03-2026-09-22.json", HERE / "lineup_calculated_sample.json", True),
)


def check(payload: dict, *, calculated: bool) -> None:
    for side in ("home", "away"):
        for key in ("tid", "mdl", "starts", "bench"):
            assert key in payload[side], f"{side}.{key} missing from the capture"
        for entry in payload[side]["starts"] + payload[side]["bench"]:
            assert "pid" in entry, f"{side}: an entry is missing pid: {entry!r}"
    assert payload["away"]["tid"] == MY_TEAM and payload["home"]["tid"] != MY_TEAM, (
        "the capture's own match must keep my team on the away side -- see the module docstring")
    assert bool(payload.get("cal")) is calculated, f"expected cal={calculated}, the capture says {payload.get('cal')!r}"
    text = json.dumps(payload)
    assert "@" not in text, "an email-shaped string survived the scrub"
    assert "eyJhbGci" not in text, "a JWT-shaped string is in the capture"


def main() -> None:
    for capture, out, calculated in FIXTURES:
        payload = json.loads(capture.read_text(encoding="utf-8"))
        check(payload, calculated=calculated)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {out.name}: idcomp {payload['idcomp']} mday {payload['mday']} cmday {payload['cmday']} "
              f"cal {payload.get('cal')} -- home {payload['home']['tid']} ({payload['home']['mdl']}), "
              f"away {payload['away']['tid']} ({payload['away']['mdl']})")


if __name__ == "__main__":
    main()
```

Run: `uv run python core/tests/fixtures/_extract_lineup.py && git status --short core/tests/fixtures/`
Expected: two "wrote" lines; `lineup_sample.json` unchanged (no diff), `lineup_calculated_sample.json` new.

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_match_scores.py`:

```python
import copy
import json
from datetime import UTC, datetime

import pytest
from conftest import FIXTURE_DIR, seed_fixtures
from fantaclaude.ingest.match_scores import (
    STATUS_ABSENT,
    STATUS_SV,
    STATUS_VOTO,
    MatchScoresShapeError,
    NoSeasonCalendar,
    oriented_result,
    parse_match,
    record_from_disk,
    record_match,
)
from fantaclaude.ingest.raw import RawStore

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))
MID_ROUND = json.loads((FIXTURE_DIR / "lineup_sample.json").read_text(encoding="utf-8"))
HOME_TID, AWAY_TID = 11560187, 19717181           # my team is away


def _statuses(match, team_id):
    counts = {STATUS_VOTO: 0, STATUS_SV: 0, STATUS_ABSENT: 0}
    for p in match.players:
        if p.team_id == team_id:
            counts[p.status] += 1
    return counts


def test_parse_match_reads_both_sides_of_the_calculated_round():
    m = parse_match(CALCULATED)
    assert (m.giornata, m.competition_id, m.matchday) == (3, 539860, 1)
    assert (m.home_team, m.away_team, m.home_module, m.away_module) == (HOME_TID, AWAY_TID, "343", "3421")
    assert (m.home_total, m.away_total, m.home_points, m.away_points) == (82.5, 67.0, 3, 0)
    assert (m.result, m.sign) == ("4-1", "1")
    assert len(m.players) == 46
    assert _statuses(m, AWAY_TID) == {STATUS_VOTO: 20, STATUS_SV: 1, STATUS_ABSENT: 2}
    assert _statuses(m, HOME_TID) == {STATUS_VOTO: 20, STATUS_SV: 0, STATUS_ABSENT: 3}
    by_id = {(p.team_id, p.player_id): p for p in m.players}
    bertola, rowe, zaccagni = by_id[(AWAY_TID, 5820)], by_id[(AWAY_TID, 6844)], by_id[(AWAY_TID, 632)]
    assert (bertola.status, bertola.part, bertola.voto, bertola.fantavoto) == (STATUS_SV, "bench", None, None)
    assert (rowe.status, rowe.part, rowe.position) == (STATUS_ABSENT, "xi", 7)
    assert (zaccagni.voto, zaccagni.fantavoto, zaccagni.malus) == (6.5, 7.5, 0)
    assert sum(p.fantavoto for p in m.players if p.team_id == AWAY_TID and p.part == "xi" and p.status == STATUS_VOTO) == 57.0


def test_parse_match_returns_none_for_a_round_not_yet_calculated():
    assert parse_match(MID_ROUND) is None


def test_oriented_result_puts_my_goals_first():
    assert (oriented_result("4-1", True), oriented_result("4-1", False), oriented_result(None, False)) == ("4-1", "1-4", None)


def _with(entry_changes, *, part="starts", index=0):
    payload = copy.deepcopy(CALCULATED)
    payload["away"][part][index].update(entry_changes)
    return payload


def test_parse_match_refuses_an_unknown_sentinel_by_name():
    with pytest.raises(MatchScoresShapeError, match="57.*sentinel"):
        parse_match(_with({"scr": 57, "cscr": 100}))


def test_parse_match_refuses_a_sentinel_beside_a_real_fantavoto():
    with pytest.raises(MatchScoresShapeError, match="sentinel"):
        parse_match(_with({"scr": 56, "cscr": 6}))


def test_parse_match_refuses_a_voto_beside_the_missing_fantavoto():
    with pytest.raises(MatchScoresShapeError, match="cscr 100"):
        parse_match(_with({"scr": 6, "cscr": 100}))


def test_parse_match_keeps_the_malus():
    payload = _with({"m": 1, "cscr": 4.5, "scr": 5.5}, part="bench", index=6)      # Gallo, 4502
    gallo = next(p for p in parse_match(payload).players if p.player_id == 4502)
    assert (gallo.voto, gallo.fantavoto, gallo.malus) == (5.5, 4.5, 1)


def test_record_match_writes_once_per_raw_file(db, tmp_path):
    raw = RawStore(tmp_path / "raw").write("lineup", CALCULATED, label=f"{AWAY_TID}-03")
    first = record_match(db, raw, CALCULATED, season_id=21)
    again = record_match(db, raw, CALCULATED, season_id=21)
    assert first.calculated and not first.duplicate and first.players == 46 and first.giornata == 3
    assert again.duplicate and again.file_id == first.file_id and again.players == 0
    assert db.execute("SELECT count(*) FROM match_files").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM match_scores").fetchone()[0] == 46
    assert db.execute("SELECT DISTINCT season_id, giornata FROM v_match_scores_current").fetchall() == [(21, 3)]
    assert db.execute("SELECT home_total, away_total, result FROM v_match_files_current").fetchone() == (82.5, 67.0, "4-1")


def test_record_match_skips_a_round_not_yet_calculated(db, tmp_path):
    raw = RawStore(tmp_path / "raw").write("lineup", MID_ROUND, label=f"{AWAY_TID}-03")
    result = record_match(db, raw, MID_ROUND, season_id=21)
    assert (result.calculated, result.file_id, result.giornata) == (False, None, 3)
    assert db.execute("SELECT count(*) FROM match_files").fetchone()[0] == 0


def test_record_from_disk_walks_the_raw_directory_and_skips_what_predates_the_season(db, tmp_path):
    seed_fixtures(db, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    store = RawStore(tmp_path / "raw")
    store.write("lineup", CALCULATED, label=f"{AWAY_TID}-03", fetched_at=datetime(2026, 9, 22, 6, 34, tzinfo=UTC))
    store.write("lineup", MID_ROUND, label=f"{AWAY_TID}-03", fetched_at=datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    store.write("lineup", MID_ROUND, label=f"{AWAY_TID}-03", fetched_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC))
    sweep = record_from_disk(db, store, season_id=21)
    assert [f.calculated for f in sweep.files] == [False, True]          # name order: 5 Sep, then 22 Sep
    assert sweep.before_season == 1
    assert sweep.to_dict()["recorded"] == 1 and sweep.to_dict()["not_calculated"] == 1
    assert record_from_disk(db, store, season_id=21).to_dict()["duplicates"] == 1
    assert db.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 0


def test_record_from_disk_needs_the_seasons_calendar(db, tmp_path):
    with pytest.raises(NoSeasonCalendar, match="ingest calendar"):
        record_from_disk(db, RawStore(tmp_path / "raw"), season_id=21)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest core/tests/test_match_scores.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.ingest.match_scores'`.

- [ ] **Step 4: Add `RawStore.on_disk` and delegate the existing helper to it**

In `core/src/fantaclaude/ingest/raw.py`, change `from datetime import datetime` to `from datetime import UTC, datetime`, and add to `class RawStore`, after `sha256_of`:

```python
    @staticmethod
    def on_disk(path: Path, kind: str) -> RawFile:
        """The RawFile a prior write() returned, for a file already on disk: the
        fetch stamp is the name's own prefix, and the hash is cheap to recompute
        -- nothing about a raw file is ever mutable."""
        stamp, _, _ = path.name.partition("-")
        fetched_at = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
        return RawFile(path, RawStore.sha256_of(path), fetched_at, kind)
```

In `core/src/fantaclaude/commands/ingest.py`, replace the body of `_raw_file_from_disk` (keep its docstring) with:

```python
    return RawStore.on_disk(path, kind)
```

That was the module's only use of `from datetime import UTC, datetime` (line 8): delete the import, then confirm with `uv run ruff check core/src/fantaclaude/commands/ingest.py`.

- [ ] **Step 5: Implement the parser and the recorder**

Create `core/src/fantaclaude/ingest/match_scores.py`:

```python
"""The platform's own scoring of one lega match, read back with the XI (spec,
"Calibration: what 3c ships").

The match GET `ingest lineup` makes answers, once the round is calculated
(`cal` true), every listed player's voto (`scr`), fantavoto (`cscr`), malus
count (`m`) and sixteen-count event string (`b`), and per side the total
(`tot`) and the points. Checked on 2026-09-22 against the voti, all 138 rows
of giornate 3-5 agree: `scr` is the Fantacalcio sheet's voto and `cscr` is
`scoring.fantavoto` less one point per `m`. Two sentinels stand for a missing
voto, each beside `cscr` 100: `scr` 56, a player absent from the voti sheet,
and `scr` 55, a senza voto. Anything else outside 0-10 is refused by name --
a new sentinel must fail loud, never land as a voto of 57.

A response for a round not yet calculated (`cal` false: 56 everywhere, `b`
null, a partial `tot`) is not recorded: its numbers are not the round's.
Recording is keyed by the raw file's sha256, so the same bytes twice are one
row and `record_from_disk` can walk data/raw/lineup/ at any time. `b` is kept
verbatim and read by nothing: seven of its sixteen positions are identified,
the rest are not.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.timeutil import to_db
from fantaclaude.values import is_number

ABSENT_SCR, SV_SCR, NO_CSCR = 56, 55, 100
STATUS_VOTO, STATUS_SV, STATUS_ABSENT = "voto", "sv", "absent"
PARTS = (("starts", "xi"), ("bench", "bench"))          # the platform's key -> ours


class MatchScoresShapeError(ValueError):
    """The response is not the calculated match this parser was written against."""


class NoSeasonCalendar(RuntimeError):
    """The season's Serie A calendar is missing, so a raw file cannot be placed in it."""


@dataclass(frozen=True)
class PlayerScore:
    team_id: int
    player_id: int
    part: str
    position: int
    status: str
    voto: float | None
    fantavoto: float | None
    malus: int
    events: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class MatchScores:
    giornata: int
    competition_id: int
    matchday: int
    home_team: int
    away_team: int
    home_module: str | None
    away_module: str | None
    home_total: float
    away_total: float
    home_points: int
    away_points: int
    result: str | None
    sign: str | None
    players: tuple[PlayerScore, ...]


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MatchScoresShapeError(f"{what} is not an integer: {value!r}")
    return value


def _number(value: Any, what: str) -> float:
    if not is_number(value):
        raise MatchScoresShapeError(f"{what} is not a number: {value!r}")
    return float(value)


def _text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _player(entry: Any, *, team_id: int, part: str, position: int) -> PlayerScore:
    if not isinstance(entry, dict):
        raise MatchScoresShapeError(f"team {team_id} {part}[{position}] is not an object: {entry!r}")
    pid = _int(entry.get("pid"), f"team {team_id} {part}[{position}].pid")
    scr = _number(entry.get("scr"), f"player {pid} scr")
    cscr = _number(entry.get("cscr"), f"player {pid} cscr")
    malus = _int(entry.get("m") or 0, f"player {pid} m")
    if malus < 0:
        raise MatchScoresShapeError(f"player {pid}: a negative malus count {malus}")
    events = entry.get("b")
    if events is not None and not isinstance(events, str):
        raise MatchScoresShapeError(f"player {pid}: b is not a string: {events!r}")
    if scr in (ABSENT_SCR, SV_SCR):
        if cscr != NO_CSCR:
            raise MatchScoresShapeError(f"player {pid}: scr {scr:g} is a missing-voto sentinel but cscr is {cscr:g}, "
                                        f"not {NO_CSCR}")
        status = STATUS_ABSENT if scr == ABSENT_SCR else STATUS_SV
        return PlayerScore(team_id, pid, part, position, status, None, None, malus, events, entry)
    if not 0 <= scr <= 10:
        raise MatchScoresShapeError(f"player {pid}: scr {scr:g} is neither a voto nor a known sentinel "
                                    f"({SV_SCR} senza voto, {ABSENT_SCR} absent)")
    if cscr == NO_CSCR:
        raise MatchScoresShapeError(f"player {pid}: a voto of {scr:g} beside cscr {NO_CSCR}, the missing-voto sentinel")
    return PlayerScore(team_id, pid, part, position, STATUS_VOTO, scr, cscr, malus, events, entry)


def oriented_result(result: str | None, mine_home: bool) -> str | None:
    """The platform's `res` ('4-1', home first) with my goals first."""
    if result is None:
        return None
    home, sep, away = result.partition("-")
    return result if mine_home or not sep else f"{away}-{home}"


def _side(payload: dict[str, Any], key: str) -> dict[str, Any]:
    side = payload.get(key)
    if not isinstance(side, dict):
        raise MatchScoresShapeError(f"{key} is missing or not an object")
    return side


def parse_match(payload: dict[str, Any]) -> MatchScores | None:
    """The calculated match, or None while `cal` says the round is not calculated yet."""
    if payload.get("cal") is not True:
        return None
    home, away = _side(payload, "home"), _side(payload, "away")
    players: list[PlayerScore] = []
    for side in (home, away):
        tid = _int(side.get("tid"), "a side's tid")
        for key, part in PARTS:
            entries = side.get(key)
            if not isinstance(entries, list):
                raise MatchScoresShapeError(f"team {tid} {key} is not a list")
            players += [_player(entry, team_id=tid, part=part, position=i) for i, entry in enumerate(entries)]
    return MatchScores(
        giornata=_int(payload.get("cmday"), "cmday"), competition_id=_int(payload.get("idcomp"), "idcomp"),
        matchday=_int(payload.get("mday"), "mday"), home_team=home["tid"], away_team=away["tid"],
        home_module=_text(home.get("mdl")), away_module=_text(away.get("mdl")),
        home_total=_number(home.get("tot"), "home tot"), away_total=_number(away.get("tot"), "away tot"),
        home_points=_int(home.get("points"), "home points"), away_points=_int(away.get("points"), "away points"),
        result=_text(payload.get("res")), sign=_text(payload.get("sign")), players=tuple(players))


@dataclass(frozen=True)
class RecordedMatch:
    raw_path: str
    giornata: int | None
    calculated: bool
    file_id: int | None
    duplicate: bool
    players: int
    home_team: int | None = None
    away_team: int | None = None
    home_total: float | None = None
    away_total: float | None = None
    result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_match(con: duckdb.DuckDBPyConnection, raw: RawFile, payload: dict[str, Any], *,
                 season_id: int) -> RecordedMatch:
    """One match_files row and its match_scores, appended once per raw file.
    A round not yet calculated records nothing and says so; the same bytes
    recorded before are named as a duplicate, with the file they became."""
    match = parse_match(payload)
    if match is None:
        cmday = payload.get("cmday")
        giornata = cmday if isinstance(cmday, int) and not isinstance(cmday, bool) else None
        return RecordedMatch(str(raw.path), giornata, False, None, False, 0)
    common = {"home_team": match.home_team, "away_team": match.away_team, "home_total": match.home_total,
              "away_total": match.away_total, "result": match.result}
    existing = con.execute("SELECT file_id FROM match_files WHERE sha256 = ?", [raw.sha256]).fetchone()
    if existing is not None:
        return RecordedMatch(str(raw.path), match.giornata, True, int(existing[0]), True, 0, **common)
    con.begin()
    try:
        file_id = con.execute(
            "INSERT INTO match_files (season_id, giornata, competition_id, matchday, fetched_at, raw_path, sha256, "
            "home_team, away_team, home_module, away_module, home_total, away_total, home_points, away_points, "
            "result, sign) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
            [season_id, match.giornata, match.competition_id, match.matchday, to_db(raw.fetched_at), str(raw.path),
             raw.sha256, match.home_team, match.away_team, match.home_module, match.away_module, match.home_total,
             match.away_total, match.home_points, match.away_points, match.result, match.sign]).fetchone()[0]
        con.executemany(
            "INSERT INTO match_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[file_id, p.team_id, p.player_id, p.part, p.position, p.status, p.voto, p.fantavoto, p.malus, p.events,
              json.dumps(p.raw, ensure_ascii=False)] for p in match.players])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return RecordedMatch(str(raw.path), match.giornata, True, int(file_id), False, len(match.players), **common)


@dataclass(frozen=True)
class DiskSweep:
    files: list[RecordedMatch]
    before_season: int

    def to_dict(self) -> dict[str, Any]:
        return {"files": [f.to_dict() for f in self.files], "before_season": self.before_season,
                "recorded": sum(1 for f in self.files if f.calculated and not f.duplicate),
                "duplicates": sum(1 for f in self.files if f.duplicate),
                "not_calculated": sum(1 for f in self.files if not f.calculated)}


def record_from_disk(con: duckdb.DuckDBPyConnection, store: RawStore, *, season_id: int) -> DiskSweep:
    """Record the scores of every raw read-back already under data/raw/lineup/,
    no request made: the backlog, and `data/` rebuilt from `data/raw/`. A file
    fetched before the season's first Serie A kickoff cannot be this season's
    and is only counted. Never touches lineup_submitted -- the XI was recorded
    when the file was fetched."""
    first = con.execute("SELECT min(kickoff) FROM v_fixtures_current WHERE competition = 'SA' AND season_id = ?",
                        [season_id]).fetchone()[0]
    if first is None:
        raise NoSeasonCalendar(f"no Serie A calendar for season {season_id} -- run `fantaclaude ingest calendar`")
    files: list[RecordedMatch] = []
    before = 0
    for path in store.list("lineup"):
        raw = RawStore.on_disk(path, "lineup")
        if to_db(raw.fetched_at) < first:
            before += 1
            continue
        files.append(record_match(con, raw, json.loads(path.read_text(encoding="utf-8")), season_id=season_id))
    return DiskSweep(files, before)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest core/tests/test_match_scores.py core/tests/test_stats_web.py core/tests/test_ingest_all.py -c core/pyproject.toml -q`
Expected: PASS (the last two exercise `_raw_file_from_disk`).

- [ ] **Step 7: Commit**

```bash
git add core/tests/fixtures/_extract_lineup.py core/tests/fixtures/lineup_calculated_sample.json \
        core/src/fantaclaude/ingest/match_scores.py core/src/fantaclaude/ingest/raw.py \
        core/src/fantaclaude/commands/ingest.py core/tests/test_match_scores.py
git commit -m "feat(ingest): the platform's own match scores -- parsed from the calculated read-back, recorded once per raw file"
```

---

### Task 3: `ingest lineup` records the score; `--from-disk`

**Files:**
- Modify: `core/src/fantaclaude/cli/app.py` (`INGEST_LINEUP_GIORNATA_OPTION`, `ingest_lineup_cmd`, two new renderers, one new helper)
- Test: `core/tests/test_lineup_cli.py`

**Interfaces:**
- Consumes: `record_match`, `record_from_disk`, `MatchScoresShapeError`, `NoSeasonCalendar` (Task 2).
- Produces: `ingest lineup --json` gains a `"match"` key (`RecordedMatch.to_dict()`); `ingest lineup --from-disk --json` prints `{"season_id", "files", "before_season", "recorded", "duplicates", "not_calculated"}`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_lineup_cli.py`, add near the other lineup constants (after `LINEUP_CALENDAR`):

```python
LINEUP_CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))
```

and append:

```python
def test_ingest_lineup_records_the_platforms_score_once_the_round_is_calculated(monkeypatch, tmp_path, fixture_json,
                                                                                 mcp_fixture_json, fake_api):
    _ingest_lineup_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    api = fake_api(overrides={"competition_calendar": LINEUP_CALENDAR, "lineup": LINEUP_CALCULATED})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    result = runner.invoke(app, ["ingest", "lineup", "--giornata", "3", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    match = json.loads(result.stdout)["match"]
    assert match["calculated"] and not match["duplicate"] and match["players"] == 46
    assert (match["home_total"], match["away_total"], match["result"]) == (82.5, 67.0, "4-1")
    assert api.calls == ["competitions", "competition_calendar", "lineup"]          # still three reads
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM match_files").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 1
    con.close()
    plain = runner.invoke(app, ["ingest", "lineup", "--giornata", "3"])
    assert plain.exit_code == ExitCode.OK and "score: 67 – 82.5 (1-4)" in plain.stdout


def test_ingest_lineup_records_no_score_for_a_round_not_yet_calculated(monkeypatch, tmp_path, fixture_json,
                                                                        mcp_fixture_json, fake_api):
    _ingest_lineup_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    api = fake_api(overrides={"competition_calendar": LINEUP_CALENDAR, "lineup": LINEUP_SAMPLE})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    result = runner.invoke(app, ["ingest", "lineup", "--giornata", "3"])
    assert result.exit_code == ExitCode.OK, result.output
    assert "not calculated" in result.stdout and "source platform" in result.stdout
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM match_files").fetchone()[0] == 0
    con.close()


def test_ingest_lineup_from_disk_makes_no_request_and_records_no_xi(monkeypatch, tmp_path, fixture_json,
                                                                    mcp_fixture_json):
    from fantaclaude.ingest.raw import RawStore

    _ingest_lineup_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_fixtures(con, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    con.close()
    RawStore(tmp_path / "data" / "raw").write("lineup", LINEUP_CALCULATED, label=f"{AWAY_TID}-03")

    def no_network(fn):
        raise AssertionError("--from-disk must not reach the API")

    monkeypatch.setattr("fantaclaude.api_client.run_with_api", no_network)
    result = runner.invoke(app, ["ingest", "lineup", "--from-disk", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert (payload["recorded"], payload["duplicates"], payload["not_calculated"]) == (1, 0, 0)
    again = runner.invoke(app, ["ingest", "lineup", "--from-disk"])
    assert again.exit_code == ExitCode.OK and "1 already recorded" in again.stdout
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM match_files").fetchone()[0] == 1
    con.close()


def test_ingest_lineup_from_disk_refuses_the_network_options(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ingest_lineup_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["ingest", "lineup", "--from-disk", "--giornata", "3"])
    assert result.exit_code == ExitCode.USAGE and "--from-disk" in result.stderr


def test_ingest_lineup_from_disk_needs_the_calendar(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ingest_lineup_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["ingest", "lineup", "--from-disk"])
    assert result.exit_code == ExitCode.NOT_READY and "ingest calendar" in result.stderr
```

(`UTC`, `datetime`, `seed_fixtures`, `AWAY_TID`, `FIXTURE_DIR` are already imported or defined in this module.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest core/tests/test_lineup_cli.py -c core/pyproject.toml -q -k "score or from_disk"`
Expected: FAIL — no `"match"` key; `--from-disk` is an unknown option (exit 2).

- [ ] **Step 3: Implement**

In `core/src/fantaclaude/cli/app.py`:

Change `INGEST_LINEUP_GIORNATA_OPTION`'s help to `"Giornata number (default: the newest one fully finished -- the read-back is after the round)."` and add below the two existing option singletons:

```python
INGEST_LINEUP_FROM_DISK_OPTION = typer.Option(
    False, "--from-disk", help="No network: record the platform's scores from the read-backs already under "
                               "data/raw/lineup/ (never the XI again).")


def _match_line(match: dict, my_team: int) -> str:
    from fantaclaude.ingest.match_scores import oriented_result

    if not match["calculated"]:
        return (f"score: giornata {match['giornata']} is not calculated on the platform yet -- nothing recorded; "
                f"read it back once it is")
    mine_home = match["home_team"] == my_team
    mine, theirs = (match["home_total"], match["away_total"]) if mine_home else (match["away_total"], match["home_total"])
    where = (f"already recorded as match_file {match['file_id']}" if match["duplicate"]
             else f"match_file {match['file_id']}, {match['players']} player rows")
    return f"score: {mine:g} – {theirs:g} ({oriented_result(match['result'], mine_home)}) · {where}"


def _render_ingest_lineup(payload: dict) -> str:
    return _render_record(payload) + "\n" + _match_line(payload["match"], payload["my_team"])


def _render_lineup_from_disk(payload: dict) -> str:
    lines = []
    for f in payload["files"]:
        name = f["raw_path"].rsplit("/", 1)[-1]
        if not f["calculated"]:
            state = "not calculated -- skipped"
        elif f["duplicate"]:
            state = f"already recorded (match_file {f['file_id']})"
        else:
            state = f"recorded as match_file {f['file_id']} ({f['players']} player rows)"
        lines.append(f"giornata {f['giornata']}: {name} -- {state}")
    tail = (f", {payload['before_season']} fetched before season {payload['season_id']} began (ignored)"
            if payload["before_season"] else "")
    lines.append(f"{payload['recorded']} recorded, {payload['duplicates']} already recorded, "
                 f"{payload['not_calculated']} not calculated{tail}")
    return "\n".join(lines)


def _ingest_lineup_from_disk(*, json_: bool) -> None:
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.match_scores import MatchScoresShapeError, NoSeasonCalendar, record_from_disk
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir

    season_id = _seasons_or_exit(None)[-1]
    con = connect()
    try:
        apply_schema(con)
        try:
            sweep = record_from_disk(con, RawStore(raw_dir()), season_id=season_id)
        except NoSeasonCalendar as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
        except MatchScoresShapeError as exc:
            typer.echo(f"source shape unexpected: {exc}", err=True)
            raise typer.Exit(code=ExitCode.ERROR) from None
    finally:
        con.close()
    emit({"season_id": season_id, **sweep.to_dict()}, json_=json_, render=_render_lineup_from_disk)
```

(`_render_record` is defined later in the module; that is fine — it is looked up when `_render_ingest_lineup` runs.)

Change `ingest_lineup_cmd`'s signature and docstring, and the head of its body:

```python
@ingest_app.command("lineup")
def ingest_lineup_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = INGEST_LINEUP_GIORNATA_OPTION,
    competition: int | None = INGEST_LINEUP_COMPETITION_OPTION,
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
    from_disk: bool = INGEST_LINEUP_FROM_DISK_OPTION,
) -> None:
    """Read the XI actually fielded back from the platform -- the GET the lega's own formazioni page makes for one match -- and record it as source `platform`; once the round is calculated, record the same response's scores too (match_files, match_scores). The competition id and its own giornata range are read live from the league API, never guessed. Appended, never edited. Network: the account in .env, three reads, once for the finished giornata in Tuesday's refresh. --from-disk: no network, the scores of the read-backs already on disk."""
    if from_disk:
        if giornata is not None or competition is not None or league is not None:
            typer.echo("--from-disk reads what is already on disk -- it takes no --giornata, --competition or --league",
                       err=True)
            raise typer.Exit(code=ExitCode.USAGE)
        _ingest_lineup_from_disk(json_=json_)
        return
```

(the existing local imports and body follow unchanged), then add `from fantaclaude.ingest.match_scores import record_match` to the command's local imports, rename `_raw` to `raw` in the `run_with_api` unpacking, and replace the tail of the command — from `submitted_id = record_submitted(...)` to the final `emit(...)` — with:

```python
        submitted_id = record_submitted(con, season_id=season_id, giornata=resolved, submission=submission,
                                        my_team=my_team, source="platform", now=utc_now())
        records = export_submitted_record(con, submitted_id, records_dir())
        with _source_errors():                      # MatchScoresShapeError is a ValueError: exit 1, the XI already kept
            recorded = record_match(con, raw, payload, season_id=season_id)
    finally:
        con.close()
    payload_out = {"submitted_id": submitted_id, "season_id": season_id, "giornata": resolved, "my_team": my_team,
                   "source": "platform", **submission.to_dict(), "records": [str(p) for p in records],
                   "match": recorded.to_dict()}
    emit(payload_out, json_=json_, render=_render_ingest_lineup)
```

- [ ] **Step 4: Run the lineup CLI tests**

Run: `uv run pytest core/tests/test_lineup_cli.py -c core/pyproject.toml -q`
Expected: PASS — including the existing `test_ingest_lineup_help_states_the_true_network_cost` ("three reads" is still in the help).

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/cli/app.py core/tests/test_lineup_cli.py
git commit -m "feat(ingest): ingest lineup records the platform's score from the same read, and --from-disk records the backlog"
```

---

### Task 4: Calibration, per player — actuals, the `p_start` curve, the fantavoto bias

**Files:**
- Create: `core/src/fantaclaude/analysis/calibration/__init__.py` (a docstring only in this task), `errors.py`, `actuals.py`, `pstart.py`, `fantavoto.py`
- Modify: `core/tests/conftest.py` (add `seed_listone`, `seed_lineup_run`)
- Test: `core/tests/test_calibration_players.py`

**Interfaces:**
- Consumes: `BonusMalus`, `Events`, `fantavoto` (`model/scoring.py`); `EVENT_COLUMNS`, `COACH_ROLE` (`analysis/history.py`); `v_predictions_current`, `lineup_runs`, `v_player_match_current`, `v_players_current`.
- Produces:
  - `errors.py`: `class CalibrationError(RuntimeError)`, `class NothingToCalibrate(CalibrationError)`.
  - `actuals.py`: `Actual(giornata, player_id, team, classic_role, voto, fantavoto)` with property `voted`; `Scored(giornata, player_id, name, club, lineup_run_id, model_hash, weekly_hash, p_start_published, p_start, fv_if_plays, fv_sd, actual)` with properties `voted`, `error`; `load_actuals(con, *, season_id, giornate, sheet, bm) -> dict[tuple[int, int], Actual]`; `clubs_with_voti(con, *, season_id, giornate, sheet) -> dict[int, frozenset[str]]`; `load_scored(con, *, season_id, giornate, actuals, clubs) -> tuple[list[Scored], int]`.
  - `pstart.py`: `BIN_WIDTH = 10`, `TOP_BIN = 9`, `Z95`; `Bin(low, high, n, mean_predicted, observed, ci_low, ci_high)`; `PStartReport(n, bins, base_rate, brier_published, brier_blend, brier_base_rate)` with `to_dict()`; `wilson(k, n, z=Z95) -> tuple[float, float]`; `bin_index(published) -> int`; `reliability(rows) -> PStartReport`.
  - `fantavoto.py`: `ROLE_ORDER`, `CONFIDENT = 80`, `LONG_SHOT = 20`, `LIST_LIMIT = 10`, `MY_MISSES = 5`; `Bias(group, n, mean_error, se, mae)`; `ModelBias(model_hash, weekly_hash, groups, spread_n, within_1sd, within_2sd)` with `to_dict()`; `Surprise(giornata, player_id, name, club, p_start_published, fv_if_plays, fantavoto, error)`; `fantavoto_bias(rows) -> list[ModelBias]`; `surprises(rows, *, my_roster=frozenset()) -> dict[str, list[Surprise]]` with keys `no_shows`, `long_shots`, `my_misses`.
  - `conftest.py`: `seed_listone(con, rows) -> int` with rows `(player_id, name, team_name, classic_role, mantra_roles)`; `seed_lineup_run(con, season_id, giornata, rows, *, late=False, model_hash="m1", weekly_hash=None, run_id="r1", module=None, xi=None, my_team=None) -> int` with rows `(player_id, p_start_published, p_start, fv_if_plays, fv_sd)`.

- [ ] **Step 1: Add the two seeding helpers to `core/tests/conftest.py`**

Append:

```python
def seed_listone(con, rows) -> int:
    """A fresh listone snapshot -- `v_players_current` follows the newest.
    `rows` are (player_id, name, team_name, classic_role, mantra_roles), the
    roles an iterable of role strings ("Dc", "Pc", ...)."""
    from uuid import uuid4
    snapshot_id = con.execute(
        "INSERT INTO listone_snapshots (fetched_at, source, raw_path, sha256, player_count) "
        "VALUES (now(), 'seed', 'seed/listone', ?, ?) RETURNING snapshot_id",
        [f"seed-listone-{uuid4().hex[:8]}", len(rows)]).fetchone()[0]
    con.executemany(
        "INSERT INTO players VALUES (?, ?, ?, NULL, ?, NULL, ?, ?, [], 1, 1, 1, 1, 1, 1, NULL, NULL, false, '{}')",
        [[snapshot_id, pid, name, team, role, list(roles)] for pid, name, team, role, roles in rows])
    return snapshot_id


def seed_lineup_run(con, season_id: int, giornata: int, rows, *, late=False, model_hash="m1", weekly_hash=None,
                    run_id="r1", module=None, xi=None, my_team=None) -> int:
    """One lineup_runs row and its predictions. `rows` are (player_id,
    p_start_published, p_start, fv_if_plays, fv_sd); every prediction carries
    the run's own `late`."""
    lineup_run_id = con.execute(
        "INSERT INTO lineup_runs (season_id, giornata, run_id, model_hash, probabili_file_id, deadline, written_at, "
        "late, my_team, module, xi, predictions, weekly_hash) "
        "VALUES (?, ?, ?, ?, 1, '2026-09-04 18:45', '2026-09-04 13:46', ?, ?, ?, ?::JSON, ?, ?) RETURNING lineup_run_id",
        [season_id, giornata, run_id, model_hash, late, my_team, module, None if xi is None else json.dumps(xi),
         len(rows), weekly_hash]).fetchone()[0]
    for pid, published, p_start, fv, fv_sd in rows:
        con.execute(
            "INSERT INTO predictions (lineup_run_id, season_id, giornata, player_id, p_start_published, p_start, "
            "fv_if_plays, fv_sd, expected_points, source, late) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', ?)",
            [lineup_run_id, season_id, giornata, pid, published, p_start, fv, fv_sd, p_start * fv, late])
    return lineup_run_id
```

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_calibration_players.py`:

```python
import pytest
from conftest import seed_lineup_run, seed_listone, seed_voti
from fantaclaude.analysis.calibration.actuals import Actual, Scored, clubs_with_voti, load_actuals, load_scored
from fantaclaude.analysis.calibration.fantavoto import fantavoto_bias, surprises
from fantaclaude.analysis.calibration.pstart import bin_index, reliability, wilson
from fantaclaude.model.scoring import BonusMalus


def _row(pid, published, blend, *, voto=None, fantavoto=None, fv=6.0, fv_sd=None, role="C", model="m1", weekly=None,
         giornata=3, absent=False):
    actual = None if absent else Actual(giornata, pid, "Inter", role, voto, fantavoto)
    return Scored(giornata, pid, f"p{pid}", "Inter", 1, model, weekly, published, blend, fv, fv_sd, actual)


# Five predictions, hand-scored: three published at 90 (two got a voto; the
# third was noted out, blend 0, and did not play), one at 15, one at 5.
FIVE = [_row(1, 90, 0.9, voto=6.5, fantavoto=7.5), _row(2, 90, 0.9, voto=6.0, fantavoto=6.0),
        _row(3, 90, 0.0, absent=True), _row(4, 15, 0.15, absent=True), _row(5, 5, 0.05)]


def test_wilson_matches_the_closed_form():
    assert wilson(2, 3) == pytest.approx((0.2077, 0.9385), abs=1e-4)
    assert wilson(0, 1) == pytest.approx((0.0, 0.7935), abs=1e-4)
    assert wilson(0, 0) == (0.0, 1.0)


def test_a_published_100_joins_the_nineties():
    assert [bin_index(p) for p in (0, 5, 9, 10, 55, 90, 100)] == [0, 0, 0, 1, 5, 9, 9]


def test_reliability_bins_and_brier_scores_are_the_hand_computed_ones():
    report = reliability(FIVE)
    assert report.n == 5
    assert [(b.low, b.high, b.n) for b in report.bins] == [(0, 9, 1), (10, 19, 1), (90, 100, 3)]
    top = report.bins[-1]
    assert top.mean_predicted == pytest.approx(0.9) and top.observed == pytest.approx(2 / 3)
    assert (top.ci_low, top.ci_high) == pytest.approx((0.2077, 0.9385), abs=1e-4)
    assert report.base_rate == pytest.approx(0.4)
    assert report.brier_published == pytest.approx(0.171)
    assert report.brier_blend == pytest.approx(0.009)
    assert report.brier_base_rate == pytest.approx(0.24)


def test_reliability_scores_only_rows_with_a_published_number():
    report = reliability([*FIVE, _row(6, None, 0.0, absent=True)])
    assert report.n == 5 and report.brier_published == pytest.approx(0.171)
    assert reliability([]).n == 0 and reliability([]).bins == []


def test_fantavoto_bias_by_role_overall_and_spread():
    rows = [_row(1, 90, 0.9, voto=6.5, fantavoto=7.5, fv=6.0, fv_sd=1.0, role="C"),
            _row(2, 90, 0.9, voto=6.0, fantavoto=6.0, fv=7.0, fv_sd=2.0, role="A"),
            _row(3, 90, 0.9, absent=True)]
    [model] = fantavoto_bias(rows)
    assert (model.model_hash, model.weekly_hash) == ("m1", None)
    groups = {g.group: g for g in model.groups}
    assert [g.group for g in model.groups] == ["C", "A", "all"]
    assert (groups["C"].n, groups["C"].mean_error, groups["C"].se, groups["C"].mae) == (1, 1.5, None, 1.5)
    assert (groups["A"].n, groups["A"].mean_error, groups["A"].mae) == (1, -1.0, 1.0)
    assert groups["all"].n == 2 and groups["all"].mean_error == pytest.approx(0.25)
    assert groups["all"].se == pytest.approx(1.25) and groups["all"].mae == pytest.approx(1.25)
    assert (model.spread_n, model.within_1sd, model.within_2sd) == (2, 0.5, 1.0)


def test_fantavoto_bias_splits_by_model_and_weekly_hash():
    rows = [_row(1, 90, 0.9, voto=6.0, fantavoto=6.0, model="m1"),
            _row(2, 90, 0.9, voto=6.0, fantavoto=6.0, model="m1", weekly="w1"),
            _row(3, 90, 0.9, voto=6.0, fantavoto=6.0, model="m2")]
    assert [(m.model_hash, m.weekly_hash) for m in fantavoto_bias(rows)] == [("m1", None), ("m1", "w1"), ("m2", None)]
    assert fantavoto_bias([_row(1, 90, 0.9, absent=True)]) == []


def test_surprises_name_the_confident_no_shows_the_long_shots_and_my_misses():
    rows = [_row(1, 90, 0.9, absent=True), _row(2, 85, 0.85, voto=None, fantavoto=None),
            _row(3, 15, 0.15, voto=7.0, fantavoto=10.0), _row(4, 60, 0.6, voto=6.0, fantavoto=4.0, fv=6.5),
            _row(5, 60, 0.6, voto=6.0, fantavoto=6.0, fv=6.2)]
    found = surprises(rows, my_roster=frozenset({4, 5}))
    assert [s.player_id for s in found["no_shows"]] == [1, 2]
    assert [(s.player_id, s.fantavoto) for s in found["long_shots"]] == [(3, 10.0)]
    assert [(s.player_id, s.error) for s in found["my_misses"]] == [(4, -2.5), (5, pytest.approx(-0.2))]


def test_load_scored_reads_the_honest_rows_and_drops_a_postponed_club(db, mcp_fixture_json):
    bm = BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))
    seed_listone(db, [(1, "Uno", "Inter", "C", ["C"]), (2, "Due", "Inter", "C", ["C"]),
                      (3, "Tre", "Inter", "A", ["A"]), (4, "Quattro", "Genoa", "D", ["Dc"])])
    seed_voti(db, 21, 3, [(1, "Uno", "Inter", "C", 6.5, {"assists": 1}), (2, "Due", "Inter", "C", None, {})])
    seed_lineup_run(db, 21, 3, [(1, 90, 0.9, 6.0, None), (2, 60, 0.6, 6.0, None), (3, 55, 0.55, 6.5, None),
                                (4, 70, 0.7, 6.0, None)])
    seed_lineup_run(db, 21, 3, [(1, 90, 0.1, 6.0, None)], late=True, run_id="r2")          # late: never read
    actuals = load_actuals(db, season_id=21, giornate=[3], sheet="Fantacalcio", bm=bm)
    assert actuals[(3, 1)].fantavoto == 7.5 and not actuals[(3, 2)].voted
    clubs = clubs_with_voti(db, season_id=21, giornate=[3], sheet="Fantacalcio")
    assert clubs == {3: frozenset({"Inter"})}
    scored, dropped = load_scored(db, season_id=21, giornate=[3], actuals=actuals, clubs=clubs)
    assert dropped == 1                                       # Genoa has no voti at all: a postponed match
    by = {s.player_id: s for s in scored}
    assert set(by) == {1, 2, 3}
    assert by[1].voted and by[1].p_start == 0.9 and by[1].error == pytest.approx(1.5)
    assert not by[2].voted and by[2].actual is not None       # senza voto: in the sheet, no voto
    assert not by[3].voted and by[3].actual is None and by[3].error is None     # absent from the sheet
    assert by[1].name == "Uno" and by[1].model_hash == "m1"
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest core/tests/test_calibration_players.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.analysis.calibration'`.

- [ ] **Step 4: Implement the four modules**

Create `core/src/fantaclaude/analysis/calibration/__init__.py`:

```python
"""Calibration (spec, "Calibration: what 3c ships"): predicted against actual,
computed on read and never stored. The facade lands with the command."""
```

Create `core/src/fantaclaude/analysis/calibration/errors.py`:

```python
"""What calibration refuses, and why."""

from __future__ import annotations


class CalibrationError(RuntimeError):
    """Calibration cannot be computed from what is on disk: an old schema, no settings, a module the table lacks."""


class NothingToCalibrate(CalibrationError):
    """No giornata asked has voti and something to score against them."""
```

Create `core/src/fantaclaude/analysis/calibration/actuals.py`:

```python
"""What happened, joined to what was predicted (spec, "Calibration: what 3c
ships").

An actual is one row of the league's own voti sheet, scored under the
bonus/malus in force -- `history`'s rule, "fantavoto is computed, never
stored". A player absent from the sheet got no voto; so did a senza voto.
The predictions are `v_predictions_current`: per player, the newest row that
was not late for him, so a forecast written after its kickoff is never read.
A prediction without an actual is scored as a no-show only when his club has
voti that giornata: a club with none did not play (a postponed match), and
its rows are dropped and counted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import duckdb

from fantaclaude.analysis.history import COACH_ROLE, EVENT_COLUMNS
from fantaclaude.model.scoring import BonusMalus, Events, fantavoto


@dataclass(frozen=True)
class Actual:
    giornata: int
    player_id: int
    team: str
    classic_role: str
    voto: float | None               # None: senza voto
    fantavoto: float | None

    @property
    def voted(self) -> bool:
        return self.voto is not None


@dataclass(frozen=True)
class Scored:
    giornata: int
    player_id: int
    name: str
    club: str | None
    lineup_run_id: int
    model_hash: str
    weekly_hash: str | None
    p_start_published: int | None
    p_start: float
    fv_if_plays: float
    fv_sd: float | None
    actual: Actual | None            # None: absent from the voti sheet

    @property
    def voted(self) -> bool:
        return self.actual is not None and self.actual.voted

    @property
    def error(self) -> float | None:
        """Actual fantavoto minus the predicted one, when he got a voto."""
        return self.actual.fantavoto - self.fv_if_plays if self.voted else None


def load_actuals(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int], sheet: str,
                 bm: BonusMalus) -> dict[tuple[int, int], Actual]:
    rows = con.execute(
        "SELECT giornata, player_id, team, classic_role, voto, senza_voto, " + ", ".join(EVENT_COLUMNS) +
        " FROM v_player_match_current WHERE season_id = ? AND sheet = ? AND giornata = ANY(?) "
        "AND player_id IS NOT NULL AND classic_role <> ?",
        [season_id, sheet, list(giornate), COACH_ROLE]).fetchall()
    actuals: dict[tuple[int, int], Actual] = {}
    for giornata, pid, team, role, voto, senza, *events in rows:
        scored = None if senza or voto is None else float(voto)
        value = None if scored is None else fantavoto(scored, Events(*(float(e or 0) for e in events)), bm)
        actuals[(int(giornata), int(pid))] = Actual(int(giornata), int(pid), str(team), str(role), scored, value)
    return actuals


def clubs_with_voti(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int],
                    sheet: str) -> dict[int, frozenset[str]]:
    rows = con.execute(
        "SELECT giornata, list(DISTINCT team) FROM v_player_match_current "
        "WHERE season_id = ? AND sheet = ? AND giornata = ANY(?) GROUP BY giornata",
        [season_id, sheet, list(giornate)]).fetchall()
    return {int(giornata): frozenset(teams) for giornata, teams in rows}


def load_scored(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int],
                actuals: dict[tuple[int, int], Actual],
                clubs: dict[int, frozenset[str]]) -> tuple[list[Scored], int]:
    rows = con.execute(
        "SELECT p.giornata, p.player_id, pl.name, pl.team_name, p.lineup_run_id, l.model_hash, l.weekly_hash, "
        "p.p_start_published, p.p_start, p.fv_if_plays, p.fv_sd "
        "FROM v_predictions_current p JOIN lineup_runs l ON l.lineup_run_id = p.lineup_run_id "
        "LEFT JOIN v_players_current pl ON pl.player_id = p.player_id "
        "WHERE p.season_id = ? AND p.giornata = ANY(?) ORDER BY p.giornata, p.player_id",
        [season_id, list(giornate)]).fetchall()
    scored: list[Scored] = []
    dropped = 0
    for giornata, pid, name, club, run, model, weekly, published, p_start, fv, fv_sd in rows:
        actual = actuals.get((int(giornata), int(pid)))
        if actual is None and (club is None or club not in clubs.get(int(giornata), frozenset())):
            dropped += 1
            continue
        scored.append(Scored(int(giornata), int(pid), str(name) if name is not None else f"#{pid}", club, int(run),
                             str(model), weekly, None if published is None else int(published), float(p_start),
                             float(fv), None if fv_sd is None else float(fv_sd), actual))
    return scored, dropped
```

Create `core/src/fantaclaude/analysis/calibration/pstart.py`:

```python
"""The reliability curve on the published p_start (spec, "Calibration: what
3c ships").

The outcome is "got a voto", not "started": a substitute who plays half an
hour gets one, so the low bins read above their percentages by construction
-- and it is still the right outcome, because it is what `expected_points =
p_start x fv_if_plays` assumes p_start means. Bins of ten points on the
page's own values, each with a 95% Wilson interval; beside them the Brier
score of the published number, of the blend and of the base rate, over the
same rows, so "does the page beat knowing nothing, and does the blend beat
the page" is one line.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any

from fantaclaude.analysis.calibration.actuals import Scored

BIN_WIDTH = 10
TOP_BIN = 9                      # 90-100: a published 100 joins the nineties
Z95 = 1.959963984540054


@dataclass(frozen=True)
class Bin:
    low: int
    high: int
    n: int
    mean_predicted: float
    observed: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class PStartReport:
    n: int
    bins: list[Bin]
    base_rate: float | None
    brier_published: float | None
    brier_blend: float | None
    brier_base_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"n": self.n, "bins": [asdict(b) for b in self.bins], "base_rate": self.base_rate,
                "brier_published": self.brier_published, "brier_blend": self.brier_blend,
                "brier_base_rate": self.brier_base_rate}


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for k successes in n trials; (0, 1) for none."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def bin_index(published: int) -> int:
    return min(max(published, 0) // BIN_WIDTH, TOP_BIN)


def reliability(rows: Sequence[Scored]) -> PStartReport:
    usable = [r for r in rows if r.p_start_published is not None]
    if not usable:
        return PStartReport(0, [], None, None, None, None)
    outcomes = [1.0 if r.voted else 0.0 for r in usable]
    grouped: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for row, outcome in zip(usable, outcomes, strict=True):
        grouped[bin_index(row.p_start_published)].append((row.p_start_published / 100, outcome))
    bins = []
    for index in sorted(grouped):
        pairs = grouped[index]
        k, n = int(sum(y for _, y in pairs)), len(pairs)
        low, high = wilson(k, n)
        bins.append(Bin(index * BIN_WIDTH, 100 if index == TOP_BIN else index * BIN_WIDTH + BIN_WIDTH - 1, n,
                        fmean(p for p, _ in pairs), k / n, low, high))
    base = fmean(outcomes)
    return PStartReport(
        len(usable), bins, base,
        fmean((r.p_start_published / 100 - y) ** 2 for r, y in zip(usable, outcomes, strict=True)),
        fmean((r.p_start - y) ** 2 for r, y in zip(usable, outcomes, strict=True)),
        fmean((base - y) ** 2 for y in outcomes))
```

Create `core/src/fantaclaude/analysis/calibration/fantavoto.py`:

```python
"""The fantavoto bias, the spread check and the surprises (spec, "Calibration:
what 3c ships").

Among predictions that got a voto, actual fantavoto minus `fv_if_plays`, per
classic role and overall, per `model_hash` and `weekly_hash` -- a bias is a
property of a model, never of the season. Where `fv_sd` is set (from 3b),
the share of errors inside one and two spreads, against 68% and 95%. Nothing
here corrects anything: a bias that holds up is written into the model by
hand, where it feeds `model_hash`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import fmean, stdev
from typing import Any

from fantaclaude.analysis.calibration.actuals import Scored

ROLE_ORDER = ("P", "D", "C", "A")
CONFIDENT, LONG_SHOT = 80, 20            # published p_start, the page's own scale
LIST_LIMIT, MY_MISSES = 10, 5


@dataclass(frozen=True)
class Bias:
    group: str
    n: int
    mean_error: float
    se: float | None                    # None with a single row
    mae: float


@dataclass(frozen=True)
class ModelBias:
    model_hash: str
    weekly_hash: str | None
    groups: list[Bias]
    spread_n: int
    within_1sd: float | None
    within_2sd: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"model_hash": self.model_hash, "weekly_hash": self.weekly_hash,
                "groups": [asdict(g) for g in self.groups], "spread_n": self.spread_n,
                "within_1sd": self.within_1sd, "within_2sd": self.within_2sd}


@dataclass(frozen=True)
class Surprise:
    giornata: int
    player_id: int
    name: str
    club: str | None
    p_start_published: int | None
    fv_if_plays: float
    fantavoto: float | None
    error: float | None


def _bias(group: str, errors: list[float]) -> Bias:
    n = len(errors)
    return Bias(group, n, fmean(errors), stdev(errors) / math.sqrt(n) if n > 1 else None, fmean(abs(e) for e in errors))


def fantavoto_bias(rows: Sequence[Scored]) -> list[ModelBias]:
    by_model: dict[tuple[str, str | None], list[Scored]] = defaultdict(list)
    for row in rows:
        if row.voted:
            by_model[(row.model_hash, row.weekly_hash)].append(row)
    out = []
    for (model, weekly), group in sorted(by_model.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        by_role: dict[str, list[float]] = defaultdict(list)
        for row in group:
            by_role[row.actual.classic_role].append(row.error)
        roles = [r for r in ROLE_ORDER if r in by_role] + sorted(set(by_role) - set(ROLE_ORDER))
        groups = [_bias(role, by_role[role]) for role in roles] + [_bias("all", [r.error for r in group])]
        spread = [r for r in group if r.fv_sd is not None and r.fv_sd > 0]
        within_1 = fmean(1.0 if abs(r.error) <= r.fv_sd else 0.0 for r in spread) if spread else None
        within_2 = fmean(1.0 if abs(r.error) <= 2 * r.fv_sd else 0.0 for r in spread) if spread else None
        out.append(ModelBias(model, weekly, groups, len(spread), within_1, within_2))
    return out


def _surprise(row: Scored) -> Surprise:
    return Surprise(row.giornata, row.player_id, row.name, row.club, row.p_start_published, row.fv_if_plays,
                    row.actual.fantavoto if row.voted else None, row.error)


def surprises(rows: Sequence[Scored], *, my_roster: frozenset[int] = frozenset()) -> dict[str, list[Surprise]]:
    """The page's confident no-shows, its long shots who played, and the
    largest fantavoto misses on my own roster -- what a journal entry names."""
    no_shows = sorted((r for r in rows if r.p_start_published is not None and r.p_start_published >= CONFIDENT
                       and not r.voted), key=lambda r: (-r.p_start_published, r.giornata, r.name))
    long_shots = sorted((r for r in rows if r.p_start_published is not None and r.p_start_published <= LONG_SHOT
                         and r.voted), key=lambda r: (-r.actual.fantavoto, r.giornata, r.name))
    misses = sorted((r for r in rows if r.player_id in my_roster and r.voted),
                    key=lambda r: (-abs(r.error), r.giornata, r.name))
    return {"no_shows": [_surprise(r) for r in no_shows[:LIST_LIMIT]],
            "long_shots": [_surprise(r) for r in long_shots[:LIST_LIMIT]],
            "my_misses": [_surprise(r) for r in misses[:MY_MISSES]]}
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest core/tests/test_calibration_players.py -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/analysis/calibration core/tests/conftest.py core/tests/test_calibration_players.py
git commit -m "feat(calibration): per player -- actuals joined to the honest predictions, the p_start curve, the fantavoto bias"
```

---

### Task 5: Calibration, per week — the platform score, the best eleven, the model's XI

**Files:**
- Create: `core/src/fantaclaude/analysis/calibration/weeks.py`
- Test: `core/tests/test_calibration_weeks.py`

**Interfaces:**
- Consumes: `CalibrationError` (Task 4); `oriented_result` (Task 2); `RosterPlayer`, `ADAPTED_MALUS` (`analysis/weekly/xi.py`); `load_run_xi` (`analysis/weekly/submitted.py`); `ForecastError` (`analysis/weekly/errors.py`); `Fit`, `Module`, `assign_weighted` (`model/modules.py`); `Role` (`model/roles.py`); `v_match_files_current`, `match_scores` (Task 1); `record_match` (Task 2, in tests); `seed_listone` (Task 4, in tests).
- Produces: `SlotScore(slot, player_id, name, fit, fantavoto)`; `XiScore(module, total, exact, missing, slots)` with `to_dict()`; `Week(...)` with `to_dict()` (fields below); `best_xi(roster, fantavoti, modules, allowed) -> XiScore | None`; `score_run_xi(xi, fantavoti, module) -> XiScore`; `roster_before(con, team_id, before) -> tuple[list[RosterPlayer], str]`; `week(con, *, season_id, giornata, my_team, fantavoti, modules, allowed, refusal) -> Week | None`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_calibration_weeks.py`:

```python
import itertools
import json
from datetime import UTC, datetime

import pytest
from conftest import FIXTURE_DIR, seed_fixtures, seed_lineup_run, seed_listone, seed_rosters
from fantaclaude.analysis.calibration.errors import CalibrationError
from fantaclaude.analysis.calibration.weeks import best_xi, score_run_xi, week
from fantaclaude.analysis.weekly.xi import RosterPlayer
from fantaclaude.ingest.match_scores import STATUS_VOTO, parse_match, record_match
from fantaclaude.ingest.raw import RawStore
from fantaclaude.model.modules import Fit, Module, Slot, load_modules
from fantaclaude.model.roles import Role
from test_lineup_api import AWAY_BENCH, AWAY_TID, AWAY_XI, HOME_TID, ROLES

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))
R = frozenset
TINY = Module("t", "tiny", (Slot("Por", R({Role.Por}), R(), R()), Slot("Dc", R({Role.Dc}), R({Role.Ds}), R()),
                            Slot("A", R({Role.A}), R({Role.Pc}), R())))


def _player(pid, *roles):
    return RosterPlayer(pid, f"p{pid}", frozenset(roles), 1, True)


def _brute_force(roster, fantavoti, module):
    available = [p for p in roster if p.player_id in fantavoti]
    best = None
    for chosen in itertools.permutations(available, len(module.slots)):
        total = 0.0
        for slot, p in zip(module.slots, chosen, strict=True):
            fit = slot.fit(p.roles)
            if fit is Fit.NATURAL:
                total += fantavoti[p.player_id]
            elif fit is Fit.ADAPTED:
                total += fantavoti[p.player_id] - 1.0
            else:
                break
        else:
            best = total if best is None else max(best, total)
    return best


def test_best_xi_agrees_with_brute_force_on_a_small_roster():
    roster = [_player(1, Role.Por), _player(2, Role.Por), _player(3, Role.Dc), _player(4, Role.Ds),
              _player(5, Role.A), _player(6, Role.Pc)]
    fantavoti = {1: 6.0, 3: 5.5, 4: 8.0, 5: 6.0, 6: 7.5}              # 2 got no voto
    best = best_xi(roster, fantavoti, {"t": TINY}, ["t"])
    assert best.total == pytest.approx(_brute_force(roster, fantavoti, TINY)) == pytest.approx(19.5)
    assert [(s.player_id, s.fit) for s in best.slots] == [(1, "natural"), (4, "adapted"), (6, "adapted")]
    assert best.exact and best.missing == []


def test_best_xi_is_none_when_the_players_who_played_cannot_fill_a_module():
    roster = [_player(3, Role.Dc), _player(5, Role.A), _player(1, Role.Por)]
    assert best_xi(roster, {3: 6.0, 5: 6.0}, {"t": TINY}, ["t"]) is None


def test_best_xi_refuses_a_permitted_module_the_table_lacks():
    with pytest.raises(CalibrationError, match="zz"):
        best_xi([_player(1, Role.Por)], {1: 6.0}, {"t": TINY}, ["zz"])


def test_score_run_xi_is_exact_with_every_voto_and_a_lower_bound_otherwise():
    xi = [{"slot": "Por", "player_id": 1, "name": "Uno", "fit": "natural"},
          {"slot": "Dc", "player_id": 4, "name": "Quattro", "fit": "adapted"},
          {"slot": "A", "player_id": 5, "name": "Cinque", "fit": "natural"}]
    full = score_run_xi(xi, {1: 6.0, 4: 8.0, 5: 6.0}, "t")
    assert full.exact and full.total == pytest.approx(19.0) and full.missing == []
    short = score_run_xi(xi, {1: 6.0, 4: 8.0}, "t")
    assert not short.exact and short.total == pytest.approx(13.0) and short.missing == ["Cinque"]
    assert short.slots[2].fantavoto is None


def _my_week(db, tmp_path, *, refusal=None):
    seed_listone(db, [(pid, f"p{pid}", "Club", "C", [r.value for r in ROLES[pid]]) for pid in ROLES])
    seed_rosters(db, 2578630, 21, {AWAY_TID: ("Mine", {pid: 1 for pid in AWAY_XI + AWAY_BENCH}),
                                   HOME_TID: ("Theirs", {5116: 1})})
    seed_fixtures(db, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    raw = RawStore(tmp_path / "raw").write("lineup", CALCULATED, label=f"{AWAY_TID}-03")
    record_match(db, raw, CALCULATED, season_id=21)
    fantavoti = {p.player_id: p.fantavoto for p in parse_match(CALCULATED).players
                 if p.team_id == AWAY_TID and p.status == STATUS_VOTO}
    modules = load_modules()
    return week(db, season_id=21, giornata=3, my_team=AWAY_TID, fantavoti=fantavoti, modules=modules,
                allowed=sorted(modules), refusal=refusal)


def test_week_reads_my_side_orients_the_result_and_simulates_no_substitution(db, tmp_path):
    w = _my_week(db, tmp_path)
    assert (w.my_total, w.opponent_total, w.result, w.points) == (67.0, 82.5, "1-4", 0)
    assert (w.opponent, w.opponent_name, w.module) == (HOME_TID, "Theirs", "3421")
    assert w.eleven_total == 57.0 and w.eleven_missing == ["p6844"] and w.bench_added == 10.0
    assert w.best is not None and w.best.total >= w.my_total           # what the platform fielded was one legal eleven
    assert w.left_on_bench == pytest.approx(w.best.total - 67.0)
    assert w.model_xi is None and "no forecast" in w.model_note
    assert "earliest" in w.roster_note                                 # the seeded snapshot postdates the kickoff


def test_week_scores_the_models_xi_from_the_newest_honest_run(db, tmp_path):
    xi = [{"slot": "X", "player_id": pid, "name": f"p{pid}", "fit": "natural"} for pid in AWAY_XI]
    seed_lineup_run(db, 21, 3, [], module="3421", xi=xi, my_team=AWAY_TID)
    w = _my_week(db, tmp_path)
    assert w.model_xi.module == "3421" and not w.model_xi.exact
    assert w.model_xi.missing == ["p6844"] and w.model_xi.total == pytest.approx(57.0)
    assert w.lineup_run_id == 1


def test_week_refuses_the_best_and_the_model_under_a_modifier(db, tmp_path):
    w = _my_week(db, tmp_path, refusal="a scoring modifier is active (D-Factor)")
    assert w.best is None and w.best_note == "a scoring modifier is active (D-Factor)"
    assert w.model_xi is None and w.model_note == w.best_note and w.my_total == 67.0


def test_week_is_none_without_a_recorded_match(db):
    assert week(db, season_id=21, giornata=3, my_team=AWAY_TID, fantavoti={}, modules={}, allowed=[],
                refusal=None) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest core/tests/test_calibration_weeks.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.analysis.calibration.weeks'`.

- [ ] **Step 3: Implement**

Create `core/src/fantaclaude/analysis/calibration/weeks.py`:

```python
"""The week's verdict (spec, "Calibration: what 3c ships").

My score is the platform's `tot`, never a recomputation: its substitutions
and the adaptation malus are already in it, and reimplementing the
platform's Mantra substitution is a non-goal. Beside it, the best eleven my
roster could have fielded knowing the fantavoti -- the exact solve per
permitted module over the players who got a voto, a player fielded adapted
worth his fantavoto less the malus -- and the model's XI scored on its own
eleven: exact when all eleven got a voto, because then the platform would
have made no substitution, otherwise a lower bound that names who had none.
Never completed by a guessed substitution. Under an active scoring modifier
a per-slot sum no longer scores an eleven, so both are refused with the
reason and the platform's own numbers stand.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import duckdb

from fantaclaude.analysis.calibration.errors import CalibrationError
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.submitted import load_run_xi
from fantaclaude.analysis.weekly.xi import ADAPTED_MALUS, RosterPlayer
from fantaclaude.ingest.match_scores import oriented_result
from fantaclaude.model.modules import Fit, Module, assign_weighted
from fantaclaude.model.roles import Role


@dataclass(frozen=True)
class SlotScore:
    slot: str
    player_id: int
    name: str
    fit: str
    fantavoto: float | None          # None: no voto


@dataclass(frozen=True)
class XiScore:
    module: str
    total: float
    exact: bool
    missing: list[str]
    slots: list[SlotScore]

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "total": self.total, "exact": self.exact, "missing": list(self.missing),
                "slots": [asdict(s) for s in self.slots]}


@dataclass(frozen=True)
class Week:
    giornata: int
    match_file: int
    my_team: int
    opponent: int
    opponent_name: str | None
    my_total: float
    opponent_total: float
    result: str | None               # my goals first
    points: int
    module: str | None
    eleven_total: float
    eleven_missing: list[str]
    bench_added: float
    best: XiScore | None
    best_note: str | None
    left_on_bench: float | None
    model_xi: XiScore | None
    model_note: str | None
    lineup_run_id: int | None
    roster_note: str

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["best"] = None if self.best is None else self.best.to_dict()
        out["model_xi"] = None if self.model_xi is None else self.model_xi.to_dict()
        return out


def best_xi(roster: Sequence[RosterPlayer], fantavoti: dict[int, float], modules: dict[str, Module],
            allowed: Sequence[str]) -> XiScore | None:
    """The eleven that would have scored most, knowing every fantavoto; None
    when no permitted module can be filled from the players who got one."""
    available = [p for p in roster if p.player_id in fantavoti]
    natural = [fantavoti[p.player_id] for p in available]
    adapted = [value - ADAPTED_MALUS for value in natural]
    roles = [p.roles for p in available]
    best: tuple[str, float, list[int]] | None = None
    for code in allowed:
        module = modules.get(str(code))
        if module is None:
            raise CalibrationError(f"the league permits module {code!r}, which is not in modules.yml")
        solved = assign_weighted(module, roles, natural, adapted)
        if solved is not None and (best is None or solved[0] > best[1]):
            best = (str(code), solved[0], solved[1])
    if best is None:
        return None
    code, total, chosen = best
    slots = []
    for k, i in enumerate(chosen):
        slot = modules[code].slots[k]
        fit = slot.fit(available[i].roles)
        slots.append(SlotScore(slot.label, available[i].player_id, available[i].name, fit.value,
                               natural[i] if fit is Fit.NATURAL else adapted[i]))
    return XiScore(code, total, True, [], slots)


def score_run_xi(xi: Sequence[dict[str, Any]], fantavoti: dict[int, float], module: str) -> XiScore:
    """A named XI on its own eleven: exact when every one got a voto."""
    slots: list[SlotScore] = []
    missing: list[str] = []
    total = 0.0
    for entry in xi:
        pid = int(entry["player_id"])
        name = str(entry.get("name") or f"#{pid}")
        fit = str(entry.get("fit") or Fit.NATURAL.value)
        value = fantavoti.get(pid)
        if value is None:
            missing.append(name)
        else:
            value -= ADAPTED_MALUS if fit == Fit.ADAPTED.value else 0.0
            total += value
        slots.append(SlotScore(str(entry.get("slot")), pid, name, fit, value))
    return XiScore(module, total, not missing, missing, slots)


def roster_before(con: duckdb.DuckDBPyConnection, team_id: int,
                  before: datetime | None) -> tuple[list[RosterPlayer], str]:
    """My roster as it stood: the newest snapshot naming the team fetched
    before `before` (the round's first kickoff), else the earliest -- and a
    note saying which."""
    snapshot = None
    if before is not None:
        snapshot = con.execute(
            "SELECT max(s.snapshot_id) FROM roster_snapshots s WHERE s.fetched_at < ? "
            "AND s.snapshot_id IN (SELECT snapshot_id FROM rosters WHERE team_id = ?)", [before, team_id]).fetchone()[0]
    if snapshot is not None:
        note = f"roster snapshot {snapshot}, fetched before the round's first kickoff"
    else:
        snapshot = con.execute("SELECT min(snapshot_id) FROM rosters WHERE team_id = ?", [team_id]).fetchone()[0]
        if snapshot is None:
            return [], f"no roster snapshot names team {team_id} -- run `fantaclaude ingest rosters`"
        note = f"roster snapshot {snapshot}, the earliest -- none was fetched before the round's first kickoff"
    rows = con.execute(
        "SELECT r.player_id, r.cost, p.name, p.mantra_roles FROM rosters r "
        "LEFT JOIN v_players_current p ON p.player_id = r.player_id "
        "WHERE r.snapshot_id = ? AND r.team_id = ? ORDER BY r.position", [snapshot, team_id]).fetchall()
    roster = [RosterPlayer(int(pid), str(name) if name is not None else f"#{pid}",
                           frozenset(Role(r) for r in (roles or [])), int(cost), name is not None)
              for pid, cost, name, roles in rows]
    return roster, note


def week(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int, my_team: int,
         fantavoti: dict[int, float], modules: dict[str, Module], allowed: Sequence[str],
         refusal: str | None) -> Week | None:
    """The verdict for one giornata, or None when no match of mine is recorded for it."""
    row = con.execute(
        "SELECT file_id, home_team, away_team, home_module, away_module, home_total, away_total, home_points, "
        "away_points, result FROM v_match_files_current WHERE season_id = ? AND giornata = ? "
        "AND (home_team = ? OR away_team = ?) ORDER BY file_id DESC LIMIT 1",
        [season_id, giornata, my_team, my_team]).fetchone()
    if row is None:
        return None
    file_id, home, away, home_module, away_module, home_total, away_total, home_points, away_points, result = row
    mine_home = home == my_team
    opponent = away if mine_home else home
    my_total, opponent_total = (home_total, away_total) if mine_home else (away_total, home_total)
    eleven = con.execute(
        "SELECT s.player_id, s.status, s.fantavoto, p.name FROM match_scores s "
        "LEFT JOIN v_players_current p ON p.player_id = s.player_id "
        "WHERE s.file_id = ? AND s.team_id = ? AND s.part = 'xi' ORDER BY s.position", [file_id, my_team]).fetchall()
    eleven_total = sum(value for _, status, value, _ in eleven if status == "voto")
    eleven_missing = [name or f"#{pid}" for pid, status, _, name in eleven if status != "voto"]
    opponent_name = con.execute("SELECT any_value(team_name) FROM rosters WHERE team_id = ?", [opponent]).fetchone()[0]
    first = con.execute("SELECT min(kickoff) FROM v_fixtures_current WHERE competition = 'SA' AND season_id = ? "
                        "AND giornata = ?", [season_id, giornata]).fetchone()[0]
    roster, roster_note = roster_before(con, my_team, first)
    best = model = None
    best_note = model_note = None
    lineup_run_id = None
    if refusal is not None:
        best_note = model_note = refusal
    else:
        best = best_xi(roster, fantavoti, modules, allowed)
        if best is None:
            best_note = "no permitted module can be filled from the players who got a voto"
        try:
            run = load_run_xi(con, season_id=season_id, giornata=giornata, lineup_run_id=None)
        except ForecastError:
            model_note = "no forecast named an XI for this giornata before the lock"
        else:
            model, lineup_run_id = score_run_xi(run.xi, fantavoti, run.module), run.lineup_run_id
    return Week(giornata, int(file_id), my_team, int(opponent), opponent_name, float(my_total), float(opponent_total),
                oriented_result(result, mine_home), int(home_points if mine_home else away_points),
                home_module if mine_home else away_module, float(eleven_total), eleven_missing,
                float(my_total) - float(eleven_total), best, best_note,
                None if best is None else best.total - float(my_total), model, model_note, lineup_run_id, roster_note)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest core/tests/test_calibration_weeks.py -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/analysis/calibration/weeks.py core/tests/test_calibration_weeks.py
git commit -m "feat(calibration): the week -- the platform's score, the best eleven by the exact solve, the model's XI exact or flagged"
```

---

### Task 6: The platform check — every recorded score against the voti

**Files:**
- Create: `core/src/fantaclaude/analysis/calibration/scoring_check.py`
- Modify: `core/tests/conftest.py` (add `events_for`, `seed_voti_matching`)
- Test: `core/tests/test_calibration_scoring.py`

**Interfaces:**
- Consumes: `v_match_scores_current` (Task 1); `parse_match`, `STATUS_*` (Task 2, in the conftest helper); `EVENT_COLUMNS`; `BonusMalus`, `Events`, `fantavoto`; `ADAPTED_MALUS`.
- Produces: `Disagreement(season_id, giornata, team_id, player_id, field, platform, ours)` with `describe() -> str` and `to_dict()`; `ScoringCheck(checked, skipped, disagreements)` with property `ok` and `to_dict()`; `check_scoring(con, *, sheet, bm, season_id=None, giornate=None) -> ScoringCheck`. Conftest: `events_for(delta) -> dict`, `seed_voti_matching(con, season_id, payload, *, overrides=None) -> int`.

- [ ] **Step 1: Add the seeding helpers to `core/tests/conftest.py`**

Append:

```python
def events_for(delta: float) -> dict:
    """Event counts whose bonus/malus under the fixtures' own table (goal +3,
    assist +1, yellow -0.5, goal conceded -1) add up to `delta`: a half point
    is a yellow, the rest goals and assists, or goals conceded."""
    yellow = 1 if round(delta * 2) % 2 else 0
    rest = round(delta + 0.5 * yellow)
    if rest >= 0:
        goals, assists = divmod(rest, 3)
        return {"yellow": yellow, "goals": goals, "assists": assists}
    return {"yellow": yellow, "goals_conceded": -rest}


def seed_voti_matching(con, season_id: int, payload, *, overrides=None) -> int:
    """One voti file agreeing, row for row, with the calculated match `payload`:
    a voto where the platform has one (events chosen so the fantavoto, less
    the malus, is the platform's), a senza voto for 55, no row for 56.
    `overrides` maps player_id to a (voto, events) pair that replaces the
    agreeing one -- how a test seeds a disagreement."""
    from fantaclaude.ingest.match_scores import STATUS_SV, STATUS_VOTO, parse_match

    match = parse_match(payload)
    rows = []
    for p in match.players:
        if p.status == STATUS_VOTO:
            voto, events = p.voto, events_for(p.fantavoto + p.malus - p.voto)
        elif p.status == STATUS_SV:
            voto, events = None, {}
        else:
            continue
        voto, events = (overrides or {}).get(p.player_id, (voto, events))
        rows.append((p.player_id, f"p{p.player_id}", f"club{p.team_id}", "C", voto, events))
    return seed_voti(con, season_id, match.giornata, rows)
```

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_calibration_scoring.py`:

```python
import copy
import json

from conftest import FIXTURE_DIR, seed_voti_matching
from fantaclaude.analysis.calibration.scoring_check import check_scoring
from fantaclaude.ingest.match_scores import record_match
from fantaclaude.ingest.raw import RawStore
from fantaclaude.model.scoring import BonusMalus

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))


def _record(db, tmp_path, payload):
    raw = RawStore(tmp_path / "raw").write("lineup", payload, label="19717181-03")
    record_match(db, raw, payload, season_id=21)


def _check(db, mcp_fixture_json):
    return check_scoring(db, sheet="Fantacalcio", bm=BonusMalus.from_calculate(mcp_fixture_json("calculation_settings")),
                         season_id=21)


def test_check_scoring_agrees_with_a_voti_sheet_that_matches_the_platform(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED)
    check = _check(db, mcp_fixture_json)
    assert (check.checked, check.skipped, check.disagreements, check.ok) == (46, 0, [], True)


def test_check_scoring_names_a_voto_the_sheet_disagrees_with(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED, overrides={632: (7.0, {"assists": 1})})     # Zaccagni: the platform says 6.5
    [d] = _check(db, mcp_fixture_json).disagreements
    assert (d.player_id, d.field, d.platform, d.ours) == (632, "voto", 6.5, 7.0)
    assert "player 632" in d.describe() and "voto" in d.describe()


def test_check_scoring_names_a_fantavoto_the_bonus_table_disagrees_with(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED, overrides={632: (6.5, {"goals": 1})})       # the platform scored an assist
    [d] = _check(db, mcp_fixture_json).disagreements
    assert (d.player_id, d.field, d.platform, d.ours) == (632, "fantavoto", 7.5, 9.5)


def test_check_scoring_applies_the_malus(db, tmp_path, mcp_fixture_json):
    payload = copy.deepcopy(CALCULATED)
    payload["away"]["bench"][6].update({"m": 1, "scr": 5.5, "cscr": 4.5})            # Gallo, adapted
    _record(db, tmp_path, payload)
    seed_voti_matching(db, 21, payload)
    assert _check(db, mcp_fixture_json).ok


def test_check_scoring_names_a_status_mismatch(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED, overrides={5820: (6.0, {})})              # Bertola: senza voto on the platform
    [d] = _check(db, mcp_fixture_json).disagreements
    assert (d.player_id, d.field, d.platform, d.ours) == (5820, "status", "sv", "voto")


def test_check_scoring_skips_a_giornata_without_voti(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    check = _check(db, mcp_fixture_json)
    assert (check.checked, check.skipped, check.ok) == (0, 46, True)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest core/tests/test_calibration_scoring.py -c core/pyproject.toml -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'fantaclaude.analysis.calibration.scoring_check'`.

- [ ] **Step 4: Implement**

Create `core/src/fantaclaude/analysis/calibration/scoring_check.py`:

```python
"""The platform's scores checked against the voti (spec, "Calibration: what 3c
ships").

Every recorded `match_scores` row is a check of the voto source and of the
bonus/malus table at once: its status against the league's sheet (absent, a
senza voto, a voto), its voto against the sheet's, its fantavoto against
`scoring.fantavoto` less one point per malus. A disagreement means a wrong
voto source or bonus table -- every projection's, not only calibration's --
so `doctor` fails on one. Rows of a giornata whose voti are not ingested yet
are skipped and counted, never read as "absent".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from fantaclaude.analysis.history import EVENT_COLUMNS
from fantaclaude.analysis.weekly.xi import ADAPTED_MALUS
from fantaclaude.model.scoring import BonusMalus, Events, fantavoto

TOLERANCE = 1e-9


@dataclass(frozen=True)
class Disagreement:
    season_id: int
    giornata: int
    team_id: int
    player_id: int
    field: str                      # status | voto | fantavoto
    platform: Any
    ours: Any

    def describe(self) -> str:
        return (f"giornata {self.giornata}, player {self.player_id} (team {self.team_id}): {self.field} "
                f"platform {self.platform!r}, ours {self.ours!r}")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "describe": self.describe()}


@dataclass(frozen=True)
class ScoringCheck:
    checked: int
    skipped: int
    disagreements: list[Disagreement]

    @property
    def ok(self) -> bool:
        return not self.disagreements

    def to_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "skipped": self.skipped, "ok": self.ok,
                "disagreements": [d.to_dict() for d in self.disagreements]}


def check_scoring(con: duckdb.DuckDBPyConnection, *, sheet: str, bm: BonusMalus, season_id: int | None = None,
                  giornate: Sequence[int] | None = None) -> ScoringCheck:
    where, params = ["true"], []
    if season_id is not None:
        where.append("s.season_id = ?")
        params.append(season_id)
    if giornate is not None:
        where.append("s.giornata = ANY(?)")
        params.append(list(giornate))
    rows = con.execute(
        "SELECT s.season_id, s.giornata, s.team_id, s.player_id, s.status, s.voto, s.fantavoto, s.malus, "
        "EXISTS (SELECT 1 FROM v_voti_files_current f WHERE f.season_id = s.season_id AND f.giornata = s.giornata), "
        "m.voto, m.senza_voto, " + ", ".join(f"m.{c}" for c in EVENT_COLUMNS) +
        " FROM v_match_scores_current s LEFT JOIN v_player_match_current m ON m.season_id = s.season_id "
        "AND m.giornata = s.giornata AND m.player_id = s.player_id AND m.sheet = ? "
        "WHERE " + " AND ".join(where) + " ORDER BY s.season_id, s.giornata, s.team_id, s.part, s.position",
        [sheet, *params]).fetchall()
    checked = skipped = 0
    found: list[Disagreement] = []
    for season, giornata, team, pid, status, voto, value, malus, rated, sheet_voto, senza, *events in rows:
        if not rated:
            skipped += 1
            continue
        checked += 1
        key = (int(season), int(giornata), int(team), int(pid))
        ours_status = "absent" if senza is None else ("sv" if senza or sheet_voto is None else "voto")
        if ours_status != status:
            found.append(Disagreement(*key, "status", status, ours_status))
            continue
        if status != "voto":
            continue
        if abs(float(sheet_voto) - voto) > TOLERANCE:
            found.append(Disagreement(*key, "voto", voto, float(sheet_voto)))
            continue
        ours = fantavoto(float(sheet_voto), Events(*(float(e or 0) for e in events)), bm) - malus * ADAPTED_MALUS
        if abs(ours - value) > TOLERANCE:
            found.append(Disagreement(*key, "fantavoto", value, ours))
    return ScoringCheck(checked, skipped, found)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest core/tests/test_calibration_scoring.py -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/src/fantaclaude/analysis/calibration/scoring_check.py core/tests/conftest.py core/tests/test_calibration_scoring.py
git commit -m "feat(calibration): the platform check -- every recorded score against the voti sheet and the bonus table"
```

---

### Task 7: The facade and `fantaclaude calibrate`

**Files:**
- Modify: `core/src/fantaclaude/analysis/calibration/__init__.py`
- Modify: `core/src/fantaclaude/cli/app.py` (new command, option singleton, renderer)
- Test: `core/tests/test_calibration.py`, `core/tests/test_calibrate_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 4–6; `scoring_in_force` (`analysis/weekly/forecast.py`); `ForecastError`; `ScoringError`, `modifier_status` (`model/scoring.py`); `load_modules`; `SCHEMA_VERSION`; `_open_read_only`, `_seasons_or_exit`, `_league_yml_or_exit`, `_ranges`, `emit`, `ExitCode` (`cli/app.py`).
- Produces: `calibrate(con, *, season_id, giornate=None, my_team=None) -> CalibrationReport`; `calibration_giornate(con, season_id) -> list[int]`; `CalibrationReport(season_id, giornate, weeks, p_start, fantavoto, surprises, scoring, predictions, dropped, warnings)` with `to_dict()`; re-exports `CalibrationError`, `NothingToCalibrate`. CLI: `fantaclaude calibrate [--giornata N ...] [--json]` — exit 0, or 3 on `CalibrationError`.

- [ ] **Step 1: Write the failing facade tests**

Create `core/tests/test_calibration.py`:

```python
import json
from datetime import UTC, datetime

import pytest
from conftest import (
    FIXTURE_DIR,
    seed_fixtures,
    seed_lineup_run,
    seed_listone,
    seed_rosters,
    seed_voti_matching,
)
from fantaclaude.analysis.calibration import CalibrationError, NothingToCalibrate, calibrate
from fantaclaude.db.connection import connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.match_scores import record_match
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from test_lineup_api import AWAY_BENCH, AWAY_TID, AWAY_XI, ROLES

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))


def _settings(con, mcp_fixture_json, *, calculate=None):
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=calculate or mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))


def _database(tmp_path, mcp_fixture_json, *, with_run=True, calculate=None):
    """Giornata 3 as it happened: the calculated match recorded, voti agreeing
    with it, my roster, and -- unless not `with_run` -- a forecast naming an
    XI and pricing three players: Zaccagni (got a voto), Rowe (absent from
    the sheet, his club played) and a Genoa player whose club has no voti."""
    path = tmp_path / "c.duckdb"
    con = connect(path)
    apply_schema(con)
    _settings(con, mcp_fixture_json, calculate=calculate)
    seed_listone(con, [(pid, f"p{pid}", "club19717181", "C", [r.value for r in ROLES[pid]])
                       for pid in AWAY_XI + AWAY_BENCH] + [(9999, "Nove", "Genoa", "D", ["Dc"])])
    seed_rosters(con, 2578630, 21, {AWAY_TID: ("Mine", {pid: 1 for pid in AWAY_XI + AWAY_BENCH})})
    seed_fixtures(con, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    record_match(con, RawStore(tmp_path / "raw").write("lineup", CALCULATED, label=f"{AWAY_TID}-03"), CALCULATED,
                 season_id=21)
    seed_voti_matching(con, 21, CALCULATED)
    if with_run:
        xi = [{"slot": "X", "player_id": pid, "name": f"p{pid}", "fit": "natural"} for pid in AWAY_XI]
        seed_lineup_run(con, 21, 3, [(632, 90, 0.9, 6.5, 1.0), (6844, 60, 0.6, 6.0, 1.0), (9999, 70, 0.7, 6.0, 1.0)],
                        module="3421", xi=xi, my_team=AWAY_TID)
    con.close()
    return connect(path, read_only=True)          # calibrate must work on a read-only handle: it writes nothing


def test_calibrate_scores_the_giornata_on_a_read_only_handle(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    report = calibrate(con, season_id=21, my_team=AWAY_TID)
    con.close()
    assert report.giornate == [3] and report.predictions == 2 and report.dropped == 1
    assert report.p_start.n == 2 and report.p_start.base_rate == pytest.approx(0.5)
    [w] = report.weeks
    assert (w.my_total, w.result, w.eleven_total) == (67.0, "1-4", 57.0)
    assert not w.model_xi.exact and w.model_xi.missing == ["p6844"]
    assert report.scoring.checked == 46 and report.scoring.ok
    assert [s.player_id for s in report.surprises["my_misses"]] == [632]
    assert report.warnings == []
    payload = report.to_dict()
    assert json.loads(json.dumps(payload, default=str))["weeks"][0]["result"] == "1-4"


def test_calibrate_warns_for_a_giornata_without_voti_and_scores_the_rest(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    report = calibrate(con, season_id=21, giornate=[3, 4], my_team=AWAY_TID)
    con.close()
    assert report.giornate == [3] and any("giornata 4 has no voti yet" in w for w in report.warnings)


def test_calibrate_without_my_team_still_scores_the_page(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    report = calibrate(con, season_id=21)
    con.close()
    assert report.weeks == [] and report.p_start.n == 2 and any("my_team" in w for w in report.warnings)


def test_calibrate_refuses_the_best_and_the_model_under_a_modifier(tmp_path, mcp_fixture_json):
    calculate = {**mcp_fixture_json("calculation_settings"), "smodd": 1}
    con = _database(tmp_path, mcp_fixture_json, calculate=calculate)
    [w] = calibrate(con, season_id=21, my_team=AWAY_TID).weeks
    con.close()
    assert w.best is None and "modifier" in w.best_note and w.my_total == 67.0


def test_calibrate_has_nothing_to_score_without_voti(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    with pytest.raises(NothingToCalibrate, match="giornata 5"):
        calibrate(con, season_id=21, giornate=[5], my_team=AWAY_TID)
    con.close()


def test_calibrate_refuses_a_database_at_an_older_schema(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    con.close()
    writer = connect(tmp_path / "c.duckdb")
    writer.execute("DELETE FROM schema_version")
    writer.execute("INSERT INTO schema_version (version) VALUES (5)")
    writer.close()
    con = connect(tmp_path / "c.duckdb", read_only=True)
    with pytest.raises(CalibrationError, match="schema 5"):
        calibrate(con, season_id=21, my_team=AWAY_TID)
    con.close()
```

- [ ] **Step 2: Write the failing CLI tests**

Create `core/tests/test_calibrate_cli.py`:

```python
import asyncio
import json
from datetime import UTC, datetime

from conftest import seed_fixtures, seed_lineup_run, seed_voti_matching
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.db.connection import connect
from test_lineup_cli import LINEUP_CALCULATED, LINEUP_CALENDAR, _ingest_lineup_workspace, _ranked
from typer.testing import CliRunner

runner = CliRunner()


def _scored_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api):
    _ingest_lineup_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    api = fake_api(overrides={"competition_calendar": LINEUP_CALENDAR, "lineup": LINEUP_CALCULATED})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    assert runner.invoke(app, ["ingest", "lineup", "--giornata", "3"]).exit_code == ExitCode.OK
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_voti_matching(con, 21, LINEUP_CALCULATED)
    seed_fixtures(con, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    seed_lineup_run(con, 21, 3, [(632, 90, 0.9, 6.5, 1.0), (7017, 85, 0.85, 6.0, 1.0)])
    con.close()


def test_calibrate_reports_the_week_the_page_and_the_platform_check(monkeypatch, tmp_path, fixture_json,
                                                                      mcp_fixture_json, fake_api):
    _scored_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api)
    result = runner.invoke(app, ["calibrate", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["giornate"] == [3] and payload["weeks"][0]["result"] == "1-4"
    assert payload["p_start"]["n"] == 2 and payload["scoring"]["checked"] == 46 and payload["scoring"]["ok"]
    plain = runner.invoke(app, ["calibrate"])
    assert plain.exit_code == ExitCode.OK, plain.output
    for phrase in ("giornata 3: 67 – 82.5", "lost 1-4", "best possible", "no forecast named an XI",
                   "p_start (published, 2 rows", "46 platform rows agree with the voti"):
        assert phrase in plain.stdout, phrase


def test_calibrate_opens_the_database_read_only(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api):
    import fantaclaude.db.connection as connection

    _scored_workspace(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fake_api)
    seen, real = [], connection.connect
    monkeypatch.setattr(connection, "connect", lambda *a, **kw: seen.append(kw.get("read_only", False)) or real(*a, **kw))
    assert runner.invoke(app, ["calibrate", "--json"]).exit_code == ExitCode.OK
    assert seen and all(seen)


def test_calibrate_is_not_ready_with_nothing_to_score(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    result = runner.invoke(app, ["calibrate"])
    assert result.exit_code == ExitCode.NOT_READY and "no giornata" in result.stderr
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest core/tests/test_calibration.py core/tests/test_calibrate_cli.py -c core/pyproject.toml -q`
Expected: FAIL — `ImportError: cannot import name 'calibrate'`; `No such command 'calibrate'`.

- [ ] **Step 4: Implement the facade**

Replace `core/src/fantaclaude/analysis/calibration/__init__.py` with:

```python
"""Calibration (spec, "Calibration: what 3c ships"): predicted against actual,
computed on read and never stored.

`calibrate` reads immutable inputs -- `v_predictions_current`, the voti, the
platform's own `match_scores` -- and writes nothing: a stored copy would go
stale the first time fantacalcio.it corrects a voto, which is
`v_market_prices`'s argument. `actuals` joins, `pstart` draws the reliability
curve, `fantavoto` measures the bias and names the surprises, `weeks` gives
the week's verdict, `scoring_check` holds the platform's scores against the
voti. Actual fantavoti are scored under the rules in force -- what `lineup`
scores under -- and a giornata predicted under other rules is named.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from fantaclaude.analysis.calibration.actuals import clubs_with_voti, load_actuals, load_scored
from fantaclaude.analysis.calibration.errors import CalibrationError, NothingToCalibrate
from fantaclaude.analysis.calibration.fantavoto import ModelBias, Surprise, fantavoto_bias, surprises
from fantaclaude.analysis.calibration.pstart import PStartReport, reliability
from fantaclaude.analysis.calibration.scoring_check import ScoringCheck, check_scoring
from fantaclaude.analysis.calibration.weeks import Week, week
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.forecast import scoring_in_force
from fantaclaude.db.schema import SCHEMA_VERSION
from fantaclaude.model.modules import load_modules
from fantaclaude.model.scoring import ScoringError, modifier_status

__all__ = ["CalibrationError", "CalibrationReport", "NothingToCalibrate", "calibrate", "calibration_giornate"]


@dataclass(frozen=True)
class CalibrationReport:
    season_id: int
    giornate: list[int]
    weeks: list[Week]
    p_start: PStartReport
    fantavoto: list[ModelBias]
    surprises: dict[str, list[Surprise]]
    scoring: ScoringCheck
    predictions: int
    dropped: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"season_id": self.season_id, "giornate": list(self.giornate),
                "weeks": [w.to_dict() for w in self.weeks], "p_start": self.p_start.to_dict(),
                "fantavoto": [m.to_dict() for m in self.fantavoto],
                "surprises": {k: [asdict(s) for s in v] for k, v in self.surprises.items()},
                "scoring": self.scoring.to_dict(), "predictions": self.predictions, "dropped": self.dropped,
                "warnings": list(self.warnings)}


def calibration_giornate(con: duckdb.DuckDBPyConnection, season_id: int) -> list[int]:
    """Every giornata of the season with voti and either predictions or a recorded match."""
    rows = con.execute(
        "SELECT DISTINCT giornata FROM v_voti_files_current WHERE season_id = ? AND ("
        "giornata IN (SELECT giornata FROM v_predictions_current WHERE season_id = ?) OR "
        "giornata IN (SELECT giornata FROM v_match_files_current WHERE season_id = ?)) ORDER BY giornata",
        [season_id, season_id, season_id]).fetchall()
    return [int(r[0]) for r in rows]


def _refusal(calculate: dict[str, Any]) -> str | None:
    status = modifier_status(calculate)
    if not status.any_active:
        return None
    active = (["D-Factor"] if status.d_factor else []) + list(status.unknown_active)
    return f"a scoring modifier is active ({', '.join(active)}) -- a per-slot sum no longer scores an eleven"


def calibrate(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int] | None = None,
              my_team: int | None = None) -> CalibrationReport:
    stored = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    if stored is None or stored < SCHEMA_VERSION:
        raise CalibrationError(f"database at schema {stored}, code expects {SCHEMA_VERSION} -- any "
                               f"`fantaclaude ingest` migrates it")
    asked = sorted(set(giornate)) if giornate else calibration_giornate(con, season_id)
    if not asked:
        raise NothingToCalibrate(f"no giornata of season {season_id} has voti and either predictions or a recorded "
                                 f"match -- `fantaclaude ingest stats-web`, then `fantaclaude ingest lineup`")
    rated = {int(r[0]) for r in con.execute(
        "SELECT giornata FROM v_voti_files_current WHERE season_id = ? AND giornata = ANY(?)",
        [season_id, asked]).fetchall()}
    warnings = [f"giornata {g} has no voti yet -- skipped (`fantaclaude ingest stats-web --giornata {g}`)"
                for g in asked if g not in rated]
    scored_giornate = [g for g in asked if g in rated]
    if not scored_giornate:
        raise NothingToCalibrate(f"giornata {', '.join(map(str, asked))}: no voti yet -- "
                                 f"`fantaclaude ingest stats-web` once the round is rated")
    try:
        sheet, bm = scoring_in_force(con)
    except (ForecastError, ScoringError) as exc:
        raise CalibrationError(str(exc)) from None
    payload, allowed, rules_hash = con.execute(
        "SELECT payload, modules, rules_hash FROM v_league_settings_current").fetchone()
    payload = payload if isinstance(payload, dict) else json.loads(payload)
    refusal = _refusal(payload.get("calculate") or {})

    actuals = load_actuals(con, season_id=season_id, giornate=scored_giornate, sheet=sheet, bm=bm)
    clubs = clubs_with_voti(con, season_id=season_id, giornate=scored_giornate, sheet=sheet)
    scored, dropped = load_scored(con, season_id=season_id, giornate=scored_giornate, actuals=actuals, clubs=clubs)
    for giornata, rules in con.execute(
            "SELECT DISTINCT p.giornata, v.rules_hash FROM v_predictions_current p "
            "JOIN lineup_runs l ON l.lineup_run_id = p.lineup_run_id JOIN valuation_runs v ON v.run_id = l.run_id "
            "WHERE p.season_id = ? AND p.giornata = ANY(?) ORDER BY 1", [season_id, scored_giornate]).fetchall():
        if rules != rules_hash:
            warnings.append(f"giornata {giornata} was predicted under rules {rules}; the voti are scored under "
                            f"{rules_hash} -- its bias mixes a rule change with model error")

    weeks: list[Week] = []
    my_roster: frozenset[int] = frozenset()
    if my_team is None:
        warnings.append("league.yml has no my_team leaf -- no weekly verdict, and no roster to name the misses on")
    else:
        my_roster = frozenset(int(r[0]) for r in con.execute(
            "SELECT player_id FROM v_rosters_current WHERE team_id = ?", [my_team]).fetchall())
        modules = load_modules()
        for giornata in scored_giornate:
            fantavoti = {pid: a.fantavoto for (g, pid), a in actuals.items() if g == giornata and a.voted}
            verdict = week(con, season_id=season_id, giornata=giornata, my_team=my_team, fantavoti=fantavoti,
                           modules=modules, allowed=list(allowed or []), refusal=refusal)
            if verdict is not None:
                weeks.append(verdict)
    if not scored and not weeks:
        raise NothingToCalibrate(f"giornata {', '.join(map(str, scored_giornate))}: neither a prediction nor a "
                                 f"recorded match to score -- `fantaclaude lineup` before the lock, "
                                 f"`fantaclaude ingest lineup` after the round")
    return CalibrationReport(season_id, scored_giornate, weeks, reliability(scored), fantavoto_bias(scored),
                             surprises(scored, my_roster=my_roster),
                             check_scoring(con, sheet=sheet, bm=bm, season_id=season_id, giornate=scored_giornate),
                             len(scored), dropped, warnings)
```

- [ ] **Step 5: Implement the command**

In `core/src/fantaclaude/cli/app.py`, after the `lineup` command group's last command (`lineup_record_cmd`), add:

```python
CALIBRATE_GIORNATA_OPTION = typer.Option(
    None, "--giornata", help="A giornata to calibrate; repeatable. Default: every giornata of the season with voti "
                             "and either predictions or a recorded match.")


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.0f}%"


def _render_calibrate(payload: dict) -> str:
    lines = [f"calibration · season {payload['season_id']} · giornate {_ranges(payload['giornate'])} · "
             f"computed on read, nothing stored"]
    for w in payload["weeks"]:
        opponent = w["opponent_name"] or f"team {w['opponent']}"
        verdict = {3: "won", 1: "drew", 0: "lost"}.get(w["points"], f"{w['points']} pts")
        lines.append(f"giornata {w['giornata']}: {w['my_total']:g} – {w['opponent_total']:g} vs {opponent} · "
                     f"{verdict} {w['result'] or ''} · {w['points']} pts")
        missing = (f", {len(w['eleven_missing'])} without a voto ({', '.join(w['eleven_missing'])})"
                   if w["eleven_missing"] else "")
        lines.append(f"  fielded {w['module'] or '?'}: the eleven {w['eleven_total']:g}{missing}; "
                     f"the bench and the malus added {w['bench_added']:+g}")
        if w["best"]:
            lines.append(f"  best possible {w['best']['module']}: {w['best']['total']:g} -- "
                         f"{w['left_on_bench']:g} left on the bench")
        else:
            lines.append(f"  best possible: {w['best_note']}")
        model = w["model_xi"]
        if model is None:
            lines.append(f"  model's XI: {w['model_note']}")
        elif model["exact"]:
            lines.append(f"  model's XI {model['module']} (run {w['lineup_run_id']}): {model['total']:g}, exact -- "
                         f"all eleven got a voto")
        else:
            lines.append(f"  model's XI {model['module']} (run {w['lineup_run_id']}): at least {model['total']:g} -- "
                         f"{len(model['missing'])} starter(s) without a voto ({', '.join(model['missing'])}), "
                         f"the bench would have decided")
        lines.append(f"  {w['roster_note']}")
    p = payload["p_start"]
    if p["n"]:
        lines.append(f"p_start (published, {p['n']} rows, {payload['dropped']} dropped): brier "
                     f"{p['brier_published']:.3f} page · {p['brier_blend']:.3f} blend · "
                     f"{p['brier_base_rate']:.3f} base rate ({_pct(p['base_rate'])} got a voto)")
        for b in p["bins"]:
            lines.append(f"  {b['low']:>3}-{b['high']:<3} n {b['n']:>4}  predicted {_pct(b['mean_predicted']):>4}  "
                         f"got a voto {_pct(b['observed']):>4}  [{_pct(b['ci_low'])}–{_pct(b['ci_high'])}]")
    else:
        lines.append("p_start: no prediction to score")
    for m in payload["fantavoto"]:
        groups = " · ".join(f"{g['group']} n {g['n']} {g['mean_error']:+.2f}"
                            + (f" ±{g['se']:.2f}" if g["se"] is not None else "") + f" mae {g['mae']:.2f}"
                            for g in m["groups"])
        lines.append(f"fantavoto (model {m['model_hash'][:8]}, weekly {(m['weekly_hash'] or '—')[:8]}): {groups}")
        lines.append(f"  spread: within 1 sd {_pct(m['within_1sd'])}, 2 sd {_pct(m['within_2sd'])} (n {m['spread_n']})"
                     if m["spread_n"] else "  spread: no fv_sd on these rows (written before 3b)")
    s = payload["surprises"]
    lines.append("confident no-shows (≥80): " + (", ".join(
        f"{i['name']} {i['p_start_published']} (g{i['giornata']})" for i in s["no_shows"]) or "none"))
    lines.append("long shots who played (≤20): " + (", ".join(
        f"{i['name']} {i['p_start_published']} → {i['fantavoto']:g} (g{i['giornata']})" for i in s["long_shots"])
        or "none"))
    if s["my_misses"]:
        lines.append("my biggest misses: " + ", ".join(f"{i['name']} {i['error']:+.1f} (g{i['giornata']})"
                                                       for i in s["my_misses"]))
    check = payload["scoring"]
    if check["disagreements"]:
        lines.append(f"scoring: {len(check['disagreements'])} of {check['checked']} platform rows DISAGREE "
                     f"with the voti -- the voto source or the bonus table is wrong")
        lines += [f"  {d['describe']}" for d in check["disagreements"]]
    else:
        skipped = f" ({check['skipped']} skipped: no voti yet)" if check["skipped"] else ""
        lines.append(f"scoring: {check['checked']} platform rows agree with the voti{skipped}")
    lines += [f"warning: {w}" for w in payload["warnings"]]
    return "\n".join(lines)


@app.command("calibrate")
def calibrate_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: list[int] | None = CALIBRATE_GIORNATA_OPTION,
) -> None:
    """Predicted against actual, computed on read: my week as the platform scored it beside the best eleven and the model's, the p_start reliability curve, the fantavoto bias, and the platform's scores checked against the voti. Local and read-only: no network, nothing written."""
    from fantaclaude.analysis.calibration import CalibrationError, calibrate

    entries = _league_yml_or_exit()
    my_team = int(entries["my_team"].value) if entries and "my_team" in entries else None
    season_id = _seasons_or_exit(None)[-1]
    con = _open_read_only()
    try:
        report = calibrate(con, season_id=season_id, giornate=giornata, my_team=my_team)
    except CalibrationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_calibrate)
```

Also add `calibrate` to the module docstring's list if it enumerates commands (it does not today — leave it).

- [ ] **Step 6: Run the tests**

Run: `uv run pytest core/tests/test_calibration.py core/tests/test_calibrate_cli.py -c core/pyproject.toml -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/analysis/calibration/__init__.py core/src/fantaclaude/cli/app.py \
        core/tests/test_calibration.py core/tests/test_calibrate_cli.py
git commit -m "feat(calibrate): fantaclaude calibrate -- the week, the page and the platform check, computed on read, read-only"
```

---

### Task 8: `doctor` — `scoring` verified against the platform, and the `journal` notice

**Files:**
- Create: `core/src/fantaclaude/kb/journal.py`
- Modify: `core/src/fantaclaude/commands/doctor.py` (`_scoring_check`, new `_journal_check`, `run_doctor`)
- Modify: `core/src/fantaclaude/cli/app.py` (`doctor_cmd`'s docstring lists the new check)
- Test: `core/tests/test_doctor.py`

**Interfaces:**
- Consumes: `check_scoring` (Task 6); `season_label` (`model/seasons.py`); `v_match_files_current` (Task 1).
- Produces: `fantaclaude.kb.journal.season_dir(kb, season_id) -> Path`, `entry_path(kb, season_id, giornata) -> Path` (`kb/league/season-2026-27/giornata-03.md`); doctor check names gain `"journal"` right after `"lineup_notes"`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_doctor.py`, change `NAMES` so `"journal"` follows `"lineup_notes"`:

```python
NAMES = ["env", "credentials", "token_cache", "database", "extensions", "league_settings",
         "listone", "league_yml", "preferences", "kb", "modules",
         "web_session", "player_match", "advanced", "fixtures", "aliases",
         "kb_profiles", "kb_takers", "kb_notes", "kb_participants", "kb_favourite_clubs", "scoring", "pricing", "valuations",
         "pinned_run", "adjustments", "lineup_notes", "journal", "asta_state", "dashboard"]
```

and append:

```python
def _record_calculated(root, *, overrides=None):
    from conftest import seed_voti_matching
    from fantaclaude.ingest.match_scores import record_match

    payload = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))
    con = connect(root / "data" / "fanta.duckdb")
    record_match(con, RawStore(root / "data" / "raw").write("lineup", payload, label="19717181-03"), payload,
                 season_id=21)
    seed_voti_matching(con, 21, payload, overrides=overrides)
    con.close()


def test_the_scoring_check_is_verified_against_the_platform(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    before = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert before["scoring"].ok and "unverified" in before["scoring"].detail
    _record_calculated(tmp_path)
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["scoring"].ok and "verified against the platform on 46 rows" in by["scoring"].detail
    assert "sheet Fantacalcio" in by["scoring"].detail and "no modifier active" in by["scoring"].detail


def test_the_scoring_check_fails_on_a_platform_disagreement(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    _record_calculated(tmp_path, overrides={632: (7.0, {"assists": 1})})
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["scoring"].ok and "disagree" in by["scoring"].detail and "player 632" in by["scoring"].detail


def test_the_journal_check_names_a_recorded_giornata_without_an_entry_and_never_fails(tmp_path, fixture_json,
                                                                                       mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["journal"].ok and by["journal"].detail == "no recorded match yet"
    _record_calculated(tmp_path)
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["journal"].ok and "notice" in by["journal"].detail and "giornata 3" in by["journal"].detail
    entry = tmp_path / "kb" / "league" / "season-2026-27" / "giornata-03.md"
    entry.parent.mkdir(parents=True)
    entry.write_text("---\nttl: never\n---\n# Giornata 3\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["journal"].ok and by["journal"].detail == "entries through giornata 3"


def test_journal_entry_paths_follow_entry_zero():
    from pathlib import Path

    from fantaclaude.kb.journal import entry_path

    assert entry_path(Path("kb"), 21, 3) == Path("kb/league/season-2026-27/giornata-03.md")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest core/tests/test_doctor.py -c core/pyproject.toml -q`
Expected: FAIL — no `journal` check; `scoring` detail lacks "verified against the platform"; `fantaclaude.kb.journal` missing.

- [ ] **Step 3: Implement**

Create `core/src/fantaclaude/kb/journal.py`:

```python
"""The season journal's file names (spec, "The season journal"): one entry per
giornata beside entry zero, the auction's `giornata-00-asta.md`."""

from __future__ import annotations

from pathlib import Path

from fantaclaude.model.seasons import season_label


def season_dir(kb: Path, season_id: int) -> Path:
    return kb / "league" / f"season-{season_label(season_id)}"


def entry_path(kb: Path, season_id: int, giornata: int) -> Path:
    return season_dir(kb, season_id) / f"giornata-{giornata:02d}.md"
```

In `core/src/fantaclaude/commands/doctor.py`, add to the imports:

```python
from fantaclaude.analysis.calibration.scoring_check import check_scoring
from fantaclaude.kb.journal import entry_path as journal_entry_path
```

Replace `_scoring_check` with:

```python
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
        bm = BonusMalus.from_calculate(calculate)
    except ScoringError as exc:
        return Check("scoring", False, str(exc))
    source = f"voto source {calculate.get('sourcev')} -> sheet {sheet}"
    try:
        platform = check_scoring(con, sheet=sheet, bm=bm)
    except duckdb.Error:
        platform = None                           # an older schema: no match_scores yet
    if platform is not None and platform.disagreements:
        first = "; ".join(d.describe() for d in platform.disagreements[:3])
        return Check("scoring", False, f"{source}; {len(platform.disagreements)} of {platform.checked} platform row(s) "
                                       f"disagree with the voti: {first} -- a wrong voto source or bonus table "
                                       f"corrupts every projection")
    if platform is not None and platform.checked:
        head = f"{source}, verified against the platform on {platform.checked} rows"
    else:
        head = f"{source} (mapping unverified until `fantaclaude ingest lineup` records a calculated round)"
    status = modifier_status(calculate)
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


def _journal_check(kb: Path, con: duckdb.DuckDBPyConnection | None, skip: str) -> Check:
    """The unwritten-journal notice (spec, "The season journal"): a giornata
    with a recorded match and no entry is named. Never a failure -- a missing
    entry makes the future poorer, not this week's answer wrong."""
    if con is None:
        return Check("journal", True, skip)
    try:
        rows = con.execute("SELECT DISTINCT season_id, giornata FROM v_match_files_current ORDER BY 1, 2").fetchall()
    except duckdb.Error:
        return Check("journal", True, "no recorded match yet")
    if not rows:
        return Check("journal", True, "no recorded match yet")
    missing = [giornata for season_id, giornata in rows if not journal_entry_path(kb, season_id, giornata).is_file()]
    if missing:
        return Check("journal", True, f"notice: no entry for giornata {', '.join(map(str, missing))} -- "
                                      f"the fanta-manager refresh drafts it")
    return Check("journal", True, f"entries through giornata {rows[-1][1]}")
```

In `run_doctor`, right after `checks.append(_lineup_notes_check(paths.lineup_notes, con, skip))`, add:

```python
        checks.append(_journal_check(paths.kb, con, skip))
```

In `core/src/fantaclaude/cli/app.py`, change `doctor_cmd`'s docstring's "…, adjustments.yml, lineup-notes.yml, the auction state file, the dashboard bundle." to "…, adjustments.yml, lineup-notes.yml, the journal, the auction state file, the dashboard bundle." (and the `scoring` wording stays).

- [ ] **Step 4: Run the doctor tests and the whole core suite**

Run: `uv run pytest core/tests/test_doctor.py -c core/pyproject.toml -q` — Expected: PASS.
Run: `uv run pytest core/tests -c core/pyproject.toml -q` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/src/fantaclaude/kb/journal.py core/src/fantaclaude/commands/doctor.py core/src/fantaclaude/cli/app.py \
        core/tests/test_doctor.py
git commit -m "feat(doctor): scoring verified against the platform's own scores, and the unwritten-journal notice"
```

---

### Task 9: The refresh reordered — the skill, the README, CLAUDE.md, the site

**Files:**
- Modify: `.claude/skills/fanta-manager/SKILL.md`, `README.md`, `CLAUDE.md`, `site/docs/tools/cli.md`, `site/docs/using/the-week.md`, `site/docs/architecture/weekly.md`

**Interfaces:**
- Consumes: the commands as Tasks 3, 7 and 8 shipped them (`fantaclaude calibrate --help`, `fantaclaude ingest lineup --help`).
- Produces: documentation only.

- [ ] **Step 1: The skill**

In `.claude/skills/fanta-manager/SKILL.md`:

(a) In the front-matter `description`, replace "`refresh` early in the week (the finished giornata's voti, the probabili and news pages)" with "`refresh` early in the week (the finished giornata's voti, its read-back and calibration, the journal draft, the probabili and news pages)".

(b) In the opening paragraph, replace "Discover the CLI with `fantaclaude lineup --help` and `fantaclaude ingest --help`; every command takes `--json`; `lineup`, `lineup note` and `lineup record` are local (no network), the `ingest` commands are the only fetches and each one is a single polite request per page." with "Discover the CLI with `fantaclaude lineup --help`, `fantaclaude calibrate --help` and `fantaclaude ingest --help`; every command takes `--json`; `lineup`, `lineup note`, `lineup record` and `calibrate` are local (no network — `calibrate` read-only on the database), the `ingest` commands are the only fetches and each one is a single polite request per page."

(c) In the third rule ("Never submit, never write to the platform."), replace "Once the lock has passed, `fantaclaude ingest lineup` reads the same fact back from the platform itself (source `platform`) — the same `lineup_submitted` table, append-only either way; run it once after the round, never in place of watching what was actually submitted." with "In Tuesday's refresh, `fantaclaude ingest lineup` reads the same fact back from the platform itself (source `platform`) — the same `lineup_submitted` table, append-only either way — and, from the same single read, the platform's own score of the match once the round is calculated; run it once per round, never in place of watching what was actually submitted."

(d) In the fourth rule, append after "`ingest stats-web` runs once, for the finished giornata.": " So does `ingest lineup`, in the same refresh (it defaults to the newest finished giornata); `--from-disk` makes no request and may run any time."

(e) Replace the whole `### \`refresh\` — early in the week (Tuesday)` section (its five numbered steps) with:

```markdown
### `refresh` — early in the week (Tuesday)

1. `fantaclaude ingest stats-web --giornata <the finished giornata>` — the
   voti; needs `FANTACALCIO_WEB_COOKIE`. If it reports "not yet rated", stop
   and try again later in the day; do not loop.
2. `fantaclaude ingest lineup` — the read-back for the finished giornata (the
   default), three reads: the XI as the platform shows it (source
   `platform`) and, once the platform has calculated the round, its own
   score of the match. If it says the round is not calculated yet, run it
   once more later in the week — never in a loop.
3. `fantaclaude calibrate --giornata <the finished giornata>` — local and
   read-only. Read it top to bottom: the week (my score as the platform
   calculated it, what the bench added, the best eleven my roster had, the
   model's XI — `exact`, or `at least` with the starters who had no voto:
   never say "the model would have won" off a lower bound); the `p_start`
   curve and its Brier line; the fantavoto bias per role (a mean error
   inside its ± is noise, and one week is never a trend); the surprises;
   and `scoring` — a disagreement there is a stop: the voto source or the
   bonus table is wrong, and every projection with it.
4. The journal entry, when `kb/league/season-<label>/giornata-NN.md` does not
   exist yet — draft it from `fantaclaude calibrate --giornata N --json`.
   Front-matter: `updated`, `ttl: never`, `confidence`, and `source:` naming
   the lineup run, the valuation run and the command. Then prose, **no
   number tables**: the result; what was fielded against what the model
   named and what was possible; what the page got wrong that is worth
   remembering; and a last section, `## What I learned`, left for the
   operator. Every number the prose cites is the command's, never
   recomputed; a lesson that outlives the week is promoted to a team
   profile or a dossier, not left in the journal.
5. `fantaclaude ingest probabili` then `fantaclaude ingest news` — one request
   each (news is two). Read the `unmatched` count: a name the listone does not
   resolve is `fantaclaude query --sql "SELECT * FROM v_unavailable_current
   WHERE player_id IS NULL"`, and the fix is an alias in
   `kb/rules/aliases.yml` under `fantacalcio_teams` (a club) or a spelling the
   listone uses (a player) — never a guess in the adapter.
6. `fantaclaude lineup` — Tuesday's forecast, so calibration has an early
   point per player (each prediction is honest against its own kickoff).
   Read every `warning:` and every `disagreement:`; write the notes that are
   already known (a suspension the page still prices, a confirmed absence).
7. `fantaclaude kb audit` and `fantaclaude doctor` — expired profiles and
   notes, the `lineup_notes` check, `scoring` (verified against the
   platform's own scores once a round is recorded) and the `journal` notice.
8. `fantaclaude ingest rosters` only if told the lega changed (a trade, a
   free agent). Never to check.
```

(f) In `### \`record\``, replace the last paragraph (from "`fantaclaude ingest lineup [--giornata N] [--competition ID]` is the read-back:" to the end of that paragraph) with:

```markdown
`fantaclaude ingest lineup [--giornata N] [--competition ID]` is the
read-back: one GET reads the XI the platform actually shows for that
giornata and records it the same way, with source `platform` instead of
`hand`, and — once the round is calculated — the platform's own score of
the match (`match_files`, `match_scores`). Needs `league.yml`'s `my_team`
leaf; the competition id and its own giornata range come from the league
API itself (`--competition` disambiguates only if the account runs more
than one). Defaults to the newest giornata fully finished, clamped to the
competition's own start. A network call against the real account — run it
once per giornata, in `refresh`, not "to check" the hand record.
`fantaclaude ingest lineup --from-disk` records the scores of read-backs
already on disk and makes no request.
```

- [ ] **Step 2: README, CLAUDE.md**

In `README.md`, in the **Weekly (lineup)** bullet, replace "`fantaclaude ingest lineup` closes the loop, reading the same fact back from the platform after the lock (source `platform` beside `hand`, same append-only `lineup_submitted`)" with "`fantaclaude ingest lineup` closes the loop in Tuesday's refresh, reading the same fact back from the platform (source `platform` beside `hand`, same append-only `lineup_submitted`) and, from the same read, the platform's own score of the match once the round is calculated (`--from-disk` records what is already on disk, no request)". Add a new bullet after it:

```markdown
- **Calibration** — `fantaclaude calibrate`: every finished giornata scored on read and never stored — my score as the platform calculated it beside the best eleven my roster had and the model's XI (exact when all eleven got a voto, a named lower bound otherwise), the reliability curve on the published `p_start` with its Brier scores, the fantavoto bias per role and model, the page's surprises, and the platform's own scores checked against the voti. Local, read-only; the refresh drafts the journal entry from it
```

In the Layout block, change the `core/` line's command list to `sync, ingest, query, kb audit, rank, lineup, calibrate, asta, doctor`.

In `CLAUDE.md`, replace "`fantaclaude lineup`, `lineup note` and `lineup record` are local." with "`fantaclaude lineup`, `lineup note`, `lineup record` and `calibrate` are local — `calibrate` read-only on the database — and so is `fantaclaude ingest lineup --from-disk`, which records the platform's scores from read-backs already under `data/raw/lineup/`; plain `ingest lineup` is networked and runs once per giornata, in the Tuesday refresh."

- [ ] **Step 3: The site**

In `site/docs/tools/cli.md`:
- In the `ingest` table, change the `ingest lineup` row to: `| \`ingest lineup\` | The XI actually fielded, read back from the platform — and, once the round is calculated, the platform's own score of the match. \`--from-disk\` records the scores of read-backs already on disk. See below. | networked (\`--from-disk\`: local) |`
- Replace the paragraph under the table ("`ingest lineup` refuses (exit 3) … after a round locks and plays.") with: "`ingest lineup` refuses (exit 3) without `my_team` in `league.yml`, and reads the competition id and its own giornata range live rather than assuming they match the Serie A calendar. Run it once per round, in Tuesday's refresh, when the platform has calculated the round: one read records both the XI and the score."
- After the `## lineup` table, add:

```markdown
## calibrate

| Command | What it does | Network |
| --- | --- | --- |
| `calibrate` | Every finished giornata scored on read: the platform's score of my match beside the best eleven my roster had and the model's XI, the published start probability's reliability curve and Brier scores, the fantavoto bias per role, the page's surprises, and the platform's scores checked against the voti. `--giornata` to pick; nothing is stored. | local |
```

- In "What touches the network", change the Local list to begin "`schema`, `query`, `kb audit`, `doctor`, `lineup`, `lineup note`, `lineup record`, `calibrate`, `ingest lineup --from-disk`, and every `asta` subcommand except `serve` —" (keep the rest).

In `site/docs/using/the-week.md`:
- Replace the first paragraph under `## Tuesday — refresh` ("Say "refresh the week" and three things run: …") and the "Worth being precise about: …" paragraph with:

```markdown
Say "refresh the week" and the finished giornata comes first: its voti,
then the platform's read-back — the XI you fielded and, once the platform
has calculated the round, its own score of your match, from one read — then
`calibrate`, which is entirely local. Then the probabili and news pages —
each a single, polite read of a public web page — and an early forecast, so
a prediction exists for every player while the week is still young. Each
prediction is written honestly against that player's own kickoff and is
never revised afterward.

`calibrate` is where the forecast meets what happened: your score as the
platform calculated it, the best eleven your roster had that week, the
model's XI scored on its own eleven — exact when all eleven got a voto,
otherwise a lower bound that names who did not — the published start
probability's reliability curve, the fantavoto bias per role, and the
platform's own scores checked against the voti. From it the refresh drafts
the giornata's journal entry, in prose, with the last section left for you.
```

- In `## And record it`, replace the sentence "Once the lock for the round has passed, `fantaclaude ingest lineup` calls the live league API to read the same fact back off the platform itself." with "In Tuesday's refresh, `fantaclaude ingest lineup` calls the live league API to read the same fact back off the platform itself, together with the platform's score."
- In the "what ran" block, replace its command list with:

```
fantaclaude ingest stats-web --giornata <finished>
fantaclaude ingest lineup            # the finished giornata: the XI and the score
fantaclaude calibrate --giornata <finished>
fantaclaude ingest probabili
fantaclaude ingest news
fantaclaude lineup
fantaclaude lineup note --type p_start --player "<name>" --p-start 0 --reason "<why>"
fantaclaude lineup record --swap "Out=In"
```

In `site/docs/architecture/weekly.md`, append after the last section:

```markdown
## Scoring the week

The read-back is the round's scoring, not only its lineup: once the round is
calculated, the same response carries every listed player's voto and
fantavoto as the platform computed them, the adaptation malus, both sides'
totals and the result. They are recorded as observed data, and every row is
checked against the voti — the voto source and the bonus table verified
weekly, for free. The week's score is the platform's own total, never a
recomputation: its substitutions are already in it, and reimplementing them
is out of scope.

`fantaclaude calibrate` computes everything else on read and stores nothing:
the best eleven the roster could have fielded knowing the fantavoti (the
same exact solve the XI uses), the model's XI on its own eleven — exact when
all eleven got a voto, a named lower bound otherwise, never completed by a
guessed substitution — the reliability curve on the published start
probability, with the Brier scores of the page, the blend and the base
rate, and the fantavoto bias per role and per model. A bias that holds up
is written into the model by hand, as a new model; calibration itself never
corrects anything.
```

- [ ] **Step 4: Build the site and run the whole suite**

Run: `uv run poe docs-build` — Expected: the build succeeds under `--strict` (if `mkdocs` is not installed in the workspace, say so in the task report and skip; do not install anything).
Run: `uv run poe test && uv run poe lint` — Expected: PASS, "All checks passed!".

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/fanta-manager/SKILL.md README.md CLAUDE.md site/docs/tools/cli.md \
        site/docs/using/the-week.md site/docs/architecture/weekly.md
git commit -m "docs: the refresh reads the round back, calibrates it and drafts the journal -- the skill, the README, the site"
```

---

### Task 10: The backlog, live — giornate 3–5 recorded and written up

This task runs against the real `data/fanta.duckdb` and is done by the controller, not a subagent: every command here is local.

**Files:**
- Create: `kb/league/season-2026-27/giornata-03.md`, `giornata-04.md`, `giornata-05.md`

- [ ] **Step 1: Record the three read-backs already on disk**

Run: `uv run fantaclaude ingest lineup --from-disk`
Expected: three `recorded as match_file N (46 player rows)` lines (giornate 3, 4, 5), `3 recorded, 0 already recorded, 0 not calculated`. The database moves to schema 6 on the way.

- [ ] **Step 2: Calibrate and check**

Run: `uv run fantaclaude calibrate` and `uv run fantaclaude calibrate --json > <scratchpad>/calibrate-3-5.json`
Expected: giornate 3–5; week 3 `67 – 82.5 … lost 1-4`, week 4 `67 – … won 1-0`, week 5 `67.5 – … lost 1-3`; weeks 4 and 5 `model's XI: no forecast named an XI…`; `scoring: 138 platform rows agree with the voti`.

Run: `uv run fantaclaude doctor`
Expected: `scoring … verified against the platform on 138 rows`; `journal … notice: no entry for giornata 3, 4, 5`.

- [ ] **Step 3: Draft the three entries**

Follow the `fanta-manager` skill's refresh step 4 for each giornata, from `calibrate --giornata N --json`, in the register of `giornata-00-asta.md`: front-matter (`updated: 2026-09-22`, `ttl: never`, `confidence`, `source:` the lineup run where there is one, the valuation run `20260904T091947Z-7694bd6a` for giornata 3, and `fantaclaude calibrate --giornata N`), prose without number tables, and a closing `## What I learned` section left for the operator. Giornate 4 and 5 say plainly that no forecast was written, so there is no model XI to compare against — only the result, the fielded eleven, the best eleven and the bench's share.

- [ ] **Step 4: Verify and commit**

Run: `uv run fantaclaude doctor` — Expected: `journal … entries through giornata 5`.

```bash
git add kb/league/season-2026-27/giornata-03.md kb/league/season-2026-27/giornata-04.md kb/league/season-2026-27/giornata-05.md
git commit -m "kb: the journal for giornate 3-5, drafted from calibrate"
```
