# fantaclaude Phase 0b — history — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the spine its history — three back seasons plus the current one of per-giornata voti and event counts (`player_match`, with `player_season` derived), Understat xG/xA/minutes matched onto the listone (`advanced_stats`), the Serie A calendar with every European midweek tie per club (`fixtures`) — and bootstrap the knowledge base through a `fanta-kb` skill, so Phase 1 can project a player from data rather than from the listone quotazione.

**Architecture:** Three new ingestion adapters follow the Phase 0a shape exactly — `fetch()` writes an immutable dated file into `data/raw/`, `load()` parses it into frozen rows with a schema assertion that fails loud, `record()` appends a snapshot to DuckDB and dedupes on content — and every one of them lands behind `fantaclaude ingest <source>` with `--json`. The voti come from fantacalcio.it's per-giornata XLSX export (behind the **website** session, captured once from a browser by the account holder — no login code exists, so nothing can hammer the account); Understat's season table comes from the JSON endpoint its own page calls; the Serie A calendar comes from fantacalcio.it's public schema.org microdata, and the European ties from UEFA's public match API. A name matcher (`ingest/names.py`) with a human alias file joins Understat onto listone ids and flags what it cannot decide. The schema moves to version 2 with an additive forward migration, so the live Phase 0a database is upgraded in place rather than rebuilt with more live-API calls.

**Tech Stack:** Python 3.14.7, uv 0.12.5 (workspace), duckdb 1.5.5, typer 0.27.1, pyyaml 6.0.3, httpx 0.28.1, pydantic 2.13.4, **openpyxl 3.1.5 (new)**, stdlib `html.parser` and `zoneinfo`, poethepoet 0.48.0, pytest 9.1.1, pytest-asyncio 1.4.0, respx 0.23.1, ruff 0.16.4.

**Spec:** `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` — sections "Schema" (Observed and Reference layers), "Ingestion adapters" (the `stats_web`, `advanced`, `calendar` rows, the backfill note and the switchover protocol), "Name matching", "Knowledge base" (the four trees, front-matter, `fanta-kb`), "Projecting a player" (what `rotation_factor` and `depth_factor` need from `kb/`), "European competition and rotation", "Testing" (Ingestion golden files), "Phasing" row 0b, open question 5. The Phase 0a plan (`docs/superpowers/plans/2026-08-24-fantaclaude-phase-0a-spine.md`) defines every interface this plan consumes.

## Global Constraints

- **Python is 3.14.7**, uv ≥ 0.12.5, workspace root `/Users/grimid3v/Workspace/fantaclaudio`; `fantaclaude.paths` derives every path from the MCP's `workspace_root()` (honours `FANTACALCIO_HOME`). Tests set `FANTACALCIO_HOME` to a `tmp_path` whenever a CLI command touches the filesystem.
- **No test performs network I/O.** HTTP is mocked with `respx`; every adapter is tested against a committed golden fixture extracted from a file in `captured/` by an `_extract_*.py` script — never hand-written. `polite_pause` is monkeypatched to a no-op in tests.
- **The live league API is called exactly where this plan says and nowhere else** (Task 8, Step 6 runs `ingest all` once). Nothing here adds a login of any kind. The fantacalcio.it **website** session is a cookie the account holder copies from their own browser into `.env` (Task 6); code sends it and never obtains it.
- **Public web sources are read politely:** one request at a time, `POLITE_DELAY_SECONDS = 1.0` between pages of the same host, an honest `User-Agent` (`fantaclaude/<version> …`), no retries on failure, no fetching in a loop "to check". Verified on 2026-08-28 that all three hosts (`www.fantacalcio.it`, `understat.com`, `match.uefa.com`) answer a non-browser User-Agent.
- **Secrets never enter fixtures, tests, tool output or git.** `FANTACALCIO_WEB_COOKIE` is a secret: no code path prints it, `doctor` reports only "set"/"not set", the secret scan asserts on key names (`cookie` joins the list) and shapes. `.env`, `.auth/`, `captured/`, `data/` stay gitignored; `.claude/settings.local.json` joins `.gitignore` (Task 9).
- **Email addresses never reach a tool result or a stored payload.** None of the three sources carries one; the secret scan keeps checking.
- **League rules are never hardcoded.** Seasons are not either: `model/seasons.py` anchors on one verified pair (`season_id 21 ↔ 2026-27`) and derives every other identifier. `SERIE_A_GIORNATE = 38` is the competition's format, not a league rule.
- **Field-naming rule** (inherited from the MCP): a column gets a friendly name only for a field whose meaning is confirmed by observation — the observations are listed under "Source facts" below and in each adapter's docstring. Everything else stays inside the `raw` JSON column.
- **Nothing is overwritten.** New files are `O_EXCL`; every adapter appends a snapshot row and a `v_*_current` view picks the latest; identical content is a no-op reported as `skipped_duplicate`/`skipped_unchanged`.
- **Unmatched rows are flagged loudly, never silently dropped**: they are stored with `player_id NULL` and a `match_status`, counted in the ingest report, listed by `v_advanced_unmatched`, and surfaced by `doctor`. A Serie A club the listone does not know is an *error*, not a flag.
- **DuckDB is single-process for writes**; a read-only and a read-write handle cannot coexist in one process. Every command reads what it needs (current season, existing files) read-only, closes, fetches from the network, and only then opens read-write. **Schema changes are additive and forward-migrating**: `apply_schema` upgrades a version-1 file in place; only a *newer* stored version raises.
- **Exit codes are the contract**: `0` ok, `1` unexpected error, `2` usage, `3` not ready (no database / no `league_settings` / website session missing or rejected / a source skipped by `ingest all`), `4` conflict. `ruff check core` is clean on `main` and must stay clean; the 13 pre-existing findings are all under `mcp/fantacalcio/` and are not this plan's to fix. Import blocks longer than the line limit are wrapped by ruff's isort: after writing a task's files run `uv run ruff check --fix core` once (it only reorders and wraps imports), then `uv run ruff check core` must be silent. A `typer.Option` default on a `list[...]` parameter trips B008 (ruff exempts only immutable annotations), so list-valued options are module-level singletons (`SEASON_OPTION`, …), never inline calls.
- **Commit messages document the change, never the tool.** No `Claude-Session:` trailer, no `Co-Authored-By: Claude`, no "Generated with Claude Code". One commit per task; the spec revision in Task 6 is one further deliberate `docs(spec):` commit, as CLAUDE.md allows for a revision.
- **This plan lives on the branch `feat/phase-0b-history`** (created 2026-08-28 from `main` at `90c7eac`). It is committed once, when finished; nothing is pushed until the phase is done or the user says so.

## Source facts observed on 2026-08-28

Recorded here because every parser below is written against them; each adapter's docstring repeats the part it depends on. The captures the fixtures are extracted from are in gitignored `captured/`.

**fantacalcio.it voti XLSX** — `GET https://www.fantacalcio.it/api/v1/Excel/votes/<season_id>/<giornata>` answers `401` (empty body) without the website session, for any `User-Agent`; `…/Excel/prices/…` the same. The public voti page `https://www.fantacalcio.it/voti-fantacalcio-serie-a/2026-27/1` links exactly that URL (`/api/v1/Excel/votes/21/1`), which confirms `season_id 21 = 2026-27`. The page itself is public and renders, per player, the fantacalcio.it player id (in the player link, e.g. `…/atalanta/carnesecchi/4431` — the listone's `id`), the Classic role (`data-value="p|d|c|a"`), three voto sources in this order — *Redazione Fantacalcio*, *Voto Statistico*, *Voto Italia* — and bonus cells titled `Gol segnati`, `Gol subiti`, `Rigori parati`, `Rigori sbagliati`, `Rigori segnati`, `Autoreti`, `Assist`, `Player of the match`; a booking is a `yellow-card` class on the voto. **A senza-voto is encoded as the sentinel `55`** (Elmas, giornata 1, all three sources). Reference rows from that page, giornata 1 of 2026-27, Atalanta: Carnesecchi `4431` P voto 6,5 (all three sources), gol subiti 1, assist 1; Zappacosta `554` D 6,5; Kolasinac `2640` D 6; Scalvini `5526` D 6 / 5,5 / 6; Gaetano `4364` C 6,5, assist 1; Elmas `4479` C senza voto; Raspadori `4371` A 7, gol 1; Krstovic `6435` A 7, gol 1. The workbook's sheet names, header row and s.v. spelling are **not yet observed** — Task 6 observes them; Task 7's `VOTI_HEADER` is the expected header and Task 6 corrects it before Task 7 runs.

**Understat** — `POST https://understat.com/main/getPlayersStats/` with form body `league=Serie_A&season=<start year>` and header `X-Requested-With: XMLHttpRequest` answers `200`, `Content-Type: text/javascript`, gzip, body `{"success": true, "players": [...]}`. Every row carries exactly these keys, all as strings: `id, player_name, games, time, goals, assists, xG, xA, shots, key_passes, yellow_cards, red_cards, position, team_title, npg, npxG, xGChain, xGBuildup`. `team_title` is `"Bologna,Cagliari"` for a mid-season mover; `player_name` is HTML-escaped (`M&#039;Bala Nzola`); clubs are spelled `AC Milan`, `Parma Calcio 1913`, otherwise as the listone (`Inter`, `Napoli`, `Frosinone`…). `season=2025` (2025-26) returned 586 rows; `season=2026` (2026-27, two giornate in) 319 rows. Reference rows, 2025-26: `Lautaro Martínez` id `7006` Inter games 30 time 2205 goals 17 assists 6; `Josep Martínez` `9052` Inter; `Marcus Thuram` `5992` Inter; `Rasmus Højlund` `11055` Napoli games 33 time 2784; `Kevin De Bruyne` `447` Napoli; `Christian Pulisic` `2662` AC Milan; `Sead Kolasinac` `342` Atalanta games 19 time 1233; `Sulemana` `10985` Bologna,Cagliari; `Pietro Terracciano` `6977` AC Milan; `Jamie Vardy` Cremonese. The league page (`/league/Serie_A/<year>`) no longer embeds the tables inline — the POST is the only source.

**fantacalcio.it calendar** — `GET https://www.fantacalcio.it/serie-a/calendario/<giornata>` (1–38) is public and renders the *current* season only; each match appears twice (a `size-large` and a `size-compact` pill), both as schema.org microdata: `div[itemtype$=SportsEvent][data-match-status]` containing `div.matchweek` (the giornata), `label[itemprop=homeTeam] > meta[itemprop=name]`, the same for `awayTeam`, `a.match-score[href=…/calendario/<giornata>/<season label>/<slug>/<match id>]`, `meta[itemprop=startDate]` (ISO date), `span.hours` (`20:45`, Europe/Rome), `span.stadium[itemprop=location]`, and `meta[itemprop=name]` (`Serie A 2026-27 - 2° giornata - milan-venezia`). Team names are spelled exactly as the listone's `tname`. Giornata 2 of 2026-27, captured to `captured/calendario-2026-27-giornata-2.html`: `17971` Milan–Venezia 2026-08-28 20:45 Giuseppe Meazza; `17967` Fiorentina–Frosinone 2026-08-29 18:30 Artemio Franchi; `17972` Monza–Udinese 2026-08-29 18:30 U-Power Stadium; `17974` Sassuolo–Torino 2026-08-29 18:30; `17968` Juventus–Parma 2026-08-29 20:45; `17973` Napoli–Como 2026-08-30 18:30; `17966` Cagliari–Inter 2026-08-30 20:45; `17969` Lazio–Genoa 2026-08-30 20:45; `17970` Lecce–Roma 2026-08-31 18:30; `17965` Atalanta–Bologna 2026-08-31 20:45. Giornata 38 already carries dates (2027-05-30 15:00). A past-season URL (`/calendario/1/2025-26`) redirects to a single match page — past seasons are not available here and are not ingested.

**UEFA** — `GET https://match.uefa.com/v5/matches?competitionId=<id>&seasonYear=<ending year>&offset=<n>&limit=200` is public JSON (a list; page with `offset` until a page has fewer than 200 rows). `competitionId` `1` = UCL, `14` = UEL, `2019` = UECL; `seasonYear=2027` is 2026-27. Each match carries `id`, `kickOffTime.dateTime` (UTC, `Z`), `homeTeam`/`awayTeam` with `internationalName`, `countryCode` (`ITA`), `teamCode`, `id`, `isPlaceHolder`; `matchday.name` (`MD1`…`MD17` in the tournament, `MD1 - PO` in qualifying), `round.phase` (`QUALIFYING` | `TOURNAMENT`), `competition.code` (`UCL`), `status` (`UPCOMING` | `FINISHED`), `score.total`, and large `translations`, `playerEvents`, `referees`, `relatedMatches` sub-objects. Italian clubs seen in 2025-26 and 2026-27: `Atalanta`, `Bologna`, `Fiorentina`, `Inter`, `Juventus`, `Napoli`, `Roma` — spelled as the listone. Captures: `captured/uefa-ucl-2026-page0.json` (2025-26, 200 rows, 40 with an Italian side, e.g. `2048058` Bayern München–Atalanta MD12 2026-03-18T20:00:00Z, `2047770` Juventus–Galatasaray MD10, `2047772` Atalanta–B. Dortmund MD10, `2047774` Inter–Bodø/Glimt MD10; first row `2047742` Paris–Arsenal MD17) and `captured/uefa-uecl-2027-page0.json` (2026-27 qualifying, `2049260` Atalanta–H. Tel-Aviv MD1 - PO 2026-08-20T18:30:00Z, `2049284` H. Tel-Aviv–Atalanta MD2 - PO 2026-08-27T18:00:00Z). The 2026-27 league phases are not drawn yet on 2026-08-28; the live run picks up whatever is scheduled when it runs, and re-runs append a new snapshot only when the schedule changed.

---

## File Structure

| file | responsibility |
| --- | --- |
| `core/pyproject.toml`, `uv.lock` | `+ openpyxl>=3.1.5` |
| `core/src/fantaclaude/model/seasons.py` | season id ↔ label / Understat year / UEFA year, `back_seasons`, `SERIE_A_GIORNATE` |
| `core/src/fantaclaude/db/schema.py` | `SCHEMA_VERSION = 2`, the new tables and views, forward migration in `apply_schema` |
| `core/src/fantaclaude/paths.py` | `+ aliases_path()` |
| `core/src/fantaclaude/config.py` | `.env` for the web sources: `load_env()`, `web_cookie()` |
| `core/src/fantaclaude/ingest/raw.py` | `+ RawStore.write_bytes(kind, data, *, ext, label)`, `list(kind, *, ext, label)`; `write` gains `label` |
| `core/src/fantaclaude/ingest/http.py` | `USER_AGENT`, `build_http`, `fetch_bytes` (401/403/redirect-to-login → `WebSessionExpired`, 404 → `NotPublished`), `polite_pause`, `run_web` |
| `core/src/fantaclaude/ingest/names.py` | `normalise`, `split_listone_name`, `Candidate`, `Matcher`, `resolve_team`, `load_candidates`, `load_teams`; `Aliases`, `load_aliases` |
| `core/src/fantaclaude/ingest/advanced.py` | Understat: `fetch_advanced`, `load_advanced`, `record_advanced` |
| `core/src/fantaclaude/ingest/calendar.py` | Serie A page parser + fetch, UEFA feed + parse, `record_fixtures` |
| `core/src/fantaclaude/ingest/stats_web.py` | voti XLSX: `fetch_voti`, `fetch_voti_range`, `parse_voti`, `parse_voto`, `record_voti` |
| `core/src/fantaclaude/commands/ingest.py` | `current_season_id`, `default_seasons`, per-source `fetch_*`/`record_*` orchestration, `ingest_all` |
| `core/src/fantaclaude/commands/doctor.py` | `+ web_session, player_match, advanced, fixtures, aliases, kb_profiles` checks |
| `core/src/fantaclaude/kb/profiles.py` | `TeamProfile`, `load_profile(s)`, `team_slug` — the structured front-matter Phase 1 reads |
| `core/src/fantaclaude/kb/audit.py` | profiles validated during the audit |
| `core/src/fantaclaude/cli/app.py` | `ingest advanced|calendar|stats-web|all`, `_source_errors`, renderers |
| `core/scripts/probe_web_session.py` | the one-shot discovery of the website session and the first voti capture (Task 6) |
| `core/tests/fixtures/_extract_understat.py` → `understat_sample.json` | 10 Understat rows chosen to exercise every match outcome |
| `core/tests/fixtures/_extract_calendar.py` → `calendario_sample.html`, `uefa_sample.json` | 3 Serie A pills; 7 UEFA matches over two pages/competitions |
| `core/tests/fixtures/_extract_voti.py` → `voti_sample.xlsx` | every sheet, the header, the Atalanta and Bologna blocks of giornata 1, 2026-27 |
| `core/tests/test_seasons.py`, `test_schema.py`, `test_raw_http.py`, `test_names.py`, `test_advanced.py`, `test_calendar.py`, `test_stats_web.py`, `test_ingest_all.py`, `test_doctor.py`, `test_kb_profiles.py`, `test_fixtures.py` | one module per source module |
| `kb/rules/aliases.yml` | `understat`, `understat_teams`, `uefa_teams` sections with the two known team spellings |
| `kb/rules/mantra.md`, `kb/rules/house-rules.md`, `kb/serie-a/teams/<slug>/profile.md` × 20 | the bootstrapped knowledge base (Task 9) |
| `.claude/skills/fanta-kb/SKILL.md` | the `fanta-kb` skill: `bootstrap`, `refresh` (`interview` is Phase 1) |
| `core/README.md`, `CLAUDE.md`, the spec (open question 5) | documentation and the recorded discovery |

Baseline on `main` (`90c7eac`): `uv run poe test` → 111 passed (MCP) and 86 passed (core); `uv run ruff check core` → clean. Every task's final step states the expected core count after it.

---

### Task 1: Seasons model and schema version 2 with a forward migration

**Files:**
- Create: `core/src/fantaclaude/model/seasons.py`, `core/tests/test_seasons.py`
- Modify: `core/src/fantaclaude/db/schema.py`, `core/tests/test_schema.py`, `core/tests/test_query_schema_cli.py`

**Interfaces:**
- Consumes: `fantaclaude.db.connection.connect`, the Phase 0a DDL (unchanged, still in `DDL`).
- Produces: `fantaclaude.model.seasons.{SEASON_ID_ANCHOR, START_YEAR_ANCHOR, SERIE_A_GIORNATE, start_year, season_label, season_id_from_label, understat_season, uefa_season_year, back_seasons}`; `SCHEMA_VERSION == 2`; tables `voti_files`, `player_match`, `advanced_snapshots`, `advanced_stats`, `fixture_snapshots`, `fixtures`; views `v_voti_files_current`, `v_player_match_current`, `v_player_season`, `v_player_form`, `v_advanced_current`, `v_advanced_unmatched`, `v_fixtures_current`, `v_european_ties`; `apply_schema(con)` migrates a version-1 file forward and raises `SchemaVersionMismatch` only when the stored version is newer than the code.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_seasons.py`:

```python
import pytest
from fantaclaude.model.seasons import (
    SERIE_A_GIORNATE,
    back_seasons,
    season_id_from_label,
    season_label,
    start_year,
    uefa_season_year,
    understat_season,
)


def test_anchor_and_offsets():
    assert start_year(21) == 2026 and start_year(18) == 2023
    assert season_label(21) == "2026-27" and season_label(18) == "2023-24"
    assert understat_season(21) == 2026 and understat_season(20) == 2025
    assert uefa_season_year(21) == 2027 and uefa_season_year(20) == 2026
    assert back_seasons(21) == [18, 19, 20] and back_seasons(21, 1) == [20]
    assert SERIE_A_GIORNATE == 38


def test_label_round_trips_and_rejects_garbage():
    for season_id in (17, 21, 25):
        assert season_id_from_label(season_label(season_id)) == season_id
    for bad in ("2026", "2026-28", "26-27", "banana", "2026/27"):
        with pytest.raises(ValueError):
            season_id_from_label(bad)
```

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


def test_apply_schema_is_idempotent(tmp_path):
    con = connect(tmp_path / "x.duckdb")
    assert apply_schema(con) == SCHEMA_VERSION == 2
    assert apply_schema(con) == SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
    con.close()


def test_schema_report_lists_tables_and_views(db):
    report = schema_report(db)
    kinds = {t.name: t.kind for t in report.tables}
    assert kinds["players"] == "table" and kinds["v_players_current"] == "view"
    assert {"league_settings", "listone_snapshots", "teams", "player_aliases",
            "v_league_settings_current", "v_teams_current"} <= set(kinds)
    assert V2_OBJECTS <= set(kinds)
    assert kinds["player_match"] == "table" and kinds["v_player_season"] == "view"
    players = next(t for t in report.tables if t.name == "players")
    assert [c.name for c in players.columns][:3] == ["snapshot_id", "player_id", "name"]
    assert players.rows == 0
    assert report.version == SCHEMA_VERSION
    assert report.to_dict()["version"] == SCHEMA_VERSION


def test_a_version_1_file_is_migrated_forward_in_place(tmp_path):
    """The Phase 0a database must not be rebuilt with more live-API calls:
    the v2 DDL is additive, so apply_schema upgrades it and keeps its rows."""
    path = tmp_path / "x.duckdb"
    con = connect(path)
    apply_schema(con)
    # Turn the file back into a Phase 0a one: drop everything v2 added, stamp version 1.
    for view in sorted(v for v in V2_OBJECTS if v.startswith("v_")):
        con.execute(f"DROP VIEW {view}")
    for table in ("player_match", "voti_files", "advanced_stats", "advanced_snapshots", "fixtures", "fixture_snapshots"):
        con.execute(f"DROP TABLE {table}")
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (1)")
    con.execute("INSERT INTO teams VALUES (1, 15, 'Roma', 'ROM')")
    con.close()

    con = connect(path)
    assert apply_schema(con) == 2
    assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 2      # history of versions kept
    assert con.execute("SELECT name FROM teams").fetchone()[0] == "Roma"               # v1 rows survive
    assert con.execute("SELECT count(*) FROM v_player_season").fetchone()[0] == 0
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
    con.close()                      # one mode per process: close before reopening read-only
    ro = connect(path, read_only=True)
    with pytest.raises(duckdb.Error):
        ro.execute("INSERT INTO teams VALUES (1, 1, 'x', 'X')")
    ro.close()


def test_write_connection_creates_the_parent_directory(tmp_path):
    con = connect(tmp_path / "nested" / "x.duckdb")
    con.close()
    assert (tmp_path / "nested" / "x.duckdb").is_file()


def test_views_over_empty_history_are_queryable(db):
    for view in sorted(v for v in V2_OBJECTS if v.startswith("v_")):
        assert db.execute(f"SELECT count(*) FROM {view}").fetchone()[0] == 0, view
```

In `core/tests/test_query_schema_cli.py`, add `from fantaclaude.db.schema import SCHEMA_VERSION, apply_schema` in place of `from fantaclaude.db.schema import apply_schema`, and change `assert payload["version"] == 1` to `assert payload["version"] == SCHEMA_VERSION`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_seasons.py core/tests/test_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.model.seasons`, `ImportError: SchemaVersionMismatch` is importable but `SCHEMA_VERSION == 2` fails, `V2_OBJECTS` missing.

- [ ] **Step 3: Write `model/seasons.py`**

```python
"""Season identifiers across the sources, anchored on one verified pair.

The league API numbers seasons: season_id 21 is 2026-27 -- observed in the
league status (sId 21, 2026-08-22) and on the public voti page, whose title
says "stagione 2026/27" and whose Excel link is /api/v1/Excel/votes/21/1
(2026-08-28). Understat names a season by its starting year (2026), UEFA by
its ending year (seasonYear=2027). One anchor and an offset, so no season is
hardcoded anywhere else.
"""

from __future__ import annotations

SEASON_ID_ANCHOR = 21
START_YEAR_ANCHOR = 2026
SERIE_A_GIORNATE = 38           # the competition's format, not a league rule


def start_year(season_id: int) -> int:
    return START_YEAR_ANCHOR + (season_id - SEASON_ID_ANCHOR)


def season_label(season_id: int) -> str:
    """'2026-27' -- the spelling fantacalcio.it uses in URLs and titles."""
    year = start_year(season_id)
    return f"{year}-{(year + 1) % 100:02d}"


def season_id_from_label(label: str) -> int:
    """Inverse of season_label; ValueError on anything else."""
    head, sep, tail = label.partition("-")
    if not sep or len(head) != 4 or len(tail) != 2 or not (head + tail).isdigit():
        raise ValueError(f"not a season label like '2026-27': {label!r}")
    year = int(head)
    if (year + 1) % 100 != int(tail):
        raise ValueError(f"season label years do not follow each other: {label!r}")
    return SEASON_ID_ANCHOR + (year - START_YEAR_ANCHOR)


def understat_season(season_id: int) -> int:
    return start_year(season_id)


def uefa_season_year(season_id: int) -> int:
    return start_year(season_id) + 1


def back_seasons(current: int, n: int = 3) -> list[int]:
    """The n seasons before `current`, oldest first: back_seasons(21) == [18, 19, 20]."""
    return [current - i for i in range(n, 0, -1)]
```

- [ ] **Step 4: Extend the schema**

In `core/src/fantaclaude/db/schema.py`: set `SCHEMA_VERSION = 2`, replace the module docstring's last sentence with `Version 2 (Phase 0b) adds the observed history -- player_match from the voti workbooks, advanced_stats from Understat, fixtures from the Serie A calendar and UEFA -- and the views over them. The DDL is additive: apply_schema upgrades an older file in place and refuses only a newer one.`, and append the following to `DDL` **before** the closing `"""` (after the `v_teams_current` view; keep every existing statement unchanged; no semicolons inside comments):

```sql
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
CREATE TABLE IF NOT EXISTS advanced_snapshots (
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
);
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
```

`v_player_form` uses `dense_rank()` on purpose: with `row_number() … WHERE rn <= 5` (or `QUALIFY`) DuckDB 1.5.5's TopN-window-elimination optimizer fails with `INTERNAL Error: Attempted to access index 7 within vector of size 7` (reproduced 2026-08-28). `giornata` is unique per (season, sheet, player) in the current view, so the two rank functions agree.

Then replace `apply_schema` with:

```python
def apply_schema(con: duckdb.DuckDBPyConnection) -> int:
    """Create what is missing, then reconcile the version row.

    The DDL is additive (CREATE ... IF NOT EXISTS, CREATE OR REPLACE VIEW),
    so running it against an older file upgrades it in place -- the Phase 0a
    database keeps its league_settings and listone rows instead of being
    rebuilt with more live-API calls. A stored version *newer* than the code
    is the one case that is refused: the code cannot know what that file holds.
    """
    for statement in DDL.split(";"):
        if statement.strip():
            con.execute(statement)
    stored = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    if stored is not None and stored > SCHEMA_VERSION:
        raise SchemaVersionMismatch(f"database is at schema {stored}, code expects {SCHEMA_VERSION}")
    if stored is None or stored < SCHEMA_VERSION:
        con.execute("INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION])
    return SCHEMA_VERSION
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_seasons.py core/tests/test_schema.py -q`
Expected: 10 passed.

- [ ] **Step 6: Run the whole suite and lint**

Run: `uv run poe test-core && uv run ruff check core`
Expected: 91 passed (86 − 5 old schema tests + 8 schema + 2 seasons); ruff clean. `test_doctor.py` still passes: it reads `SCHEMA_VERSION` from the module.

- [ ] **Step 7: Commit**

```bash
git add core/src/fantaclaude/model/seasons.py core/src/fantaclaude/db/schema.py core/tests/test_seasons.py core/tests/test_schema.py core/tests/test_query_schema_cli.py
git commit -m "feat(schema): version 2 -- history tables, derived views, forward migration; season identifiers"
```

---

### Task 2: Raw bytes, the polite HTTP helper, and the website-cookie setting

**Files:**
- Modify: `core/pyproject.toml` (+ `openpyxl`), `uv.lock`, `core/src/fantaclaude/ingest/raw.py`, `core/src/fantaclaude/paths.py`
- Create: `core/src/fantaclaude/ingest/http.py`, `core/src/fantaclaude/config.py`, `core/tests/test_raw_http.py`

**Interfaces:**
- Consumes: `fantacalcio_mcp.config.{env_path, load_dotenv}`, `fantaclaude.timeutil.utc_now`, `fantaclaude.__version__`.
- Produces: `RawStore.write(kind, payload, *, label=None, fetched_at=None) -> RawFile` (unchanged for existing callers), `RawStore.write_bytes(kind, data: bytes, *, ext: str, label: str | None = None, fetched_at=None) -> RawFile`, `RawStore.list(kind, *, ext="json", label=None) -> list[Path]`; `fantaclaude.ingest.http.{USER_AGENT, POLITE_DELAY_SECONDS, SourceError(url, status), WebSessionExpired, NotPublished, build_http(*, timeout=30.0) -> httpx.AsyncClient, async fetch_bytes(http, url, *, method="GET", headers=None, params=None, data=None) -> bytes, async polite_pause(seconds=POLITE_DELAY_SECONDS), run_web(fn) -> T}`; `fantaclaude.config.{WEB_COOKIE_KEY, load_env() -> dict[str, str], web_cookie(env=None) -> str | None}`; `fantaclaude.paths.aliases_path() -> Path`.

- [ ] **Step 1: Add openpyxl**

Run: `uv add --package fantaclaude "openpyxl>=3.1.5"`
Expected: `core/pyproject.toml` lists `"openpyxl>=3.1.5"` under `dependencies`; `uv.lock` gains `openpyxl` (pure Python, plus `et-xmlfile`). `uv run python -c "import openpyxl; print(openpyxl.__version__)"` prints `3.1.5` or newer.

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_raw_http.py`:

```python
import asyncio
from datetime import UTC, datetime

import httpx
import pytest
import respx
from fantaclaude.config import WEB_COOKIE_KEY, load_env, web_cookie
from fantaclaude.ingest.http import (
    USER_AGENT,
    NotPublished,
    SourceError,
    WebSessionExpired,
    build_http,
    fetch_bytes,
    run_web,
)
from fantaclaude.ingest.raw import RawStore


def test_write_bytes_names_and_lists_like_write(tmp_path):
    store = RawStore(tmp_path)
    when = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
    raw = store.write_bytes("voti", b"PK\x03\x04binary", ext="xlsx", label="21-01", fetched_at=when)
    assert raw.path.name == "20260828T100000000000Z-voti-21-01.xlsx" and raw.path.read_bytes() == b"PK\x03\x04binary"
    assert raw.kind == "voti" and raw.sha256 == RawStore.sha256_of(raw.path)
    with pytest.raises(FileExistsError):
        store.write_bytes("voti", b"x", ext="xlsx", label="21-01", fetched_at=when)   # never overwritten
    other = store.write_bytes("voti", b"y", ext="xlsx", label="21-02", fetched_at=when)
    assert store.list("voti", ext="xlsx") == sorted([raw.path, other.path])
    assert store.list("voti", ext="xlsx", label="21-01") == [raw.path]
    assert store.list("voti") == []                                     # json by default, as before
    json_raw = store.write("advanced", {"a": 1}, label="20", fetched_at=when)
    assert json_raw.path.name == "20260828T100000000000Z-advanced-20.json"
    assert store.list("advanced", label="20") == [json_raw.path]
    plain = store.write("listone", {"a": 1}, fetched_at=when)
    assert plain.path.name == "20260828T100000000000Z-listone.json"    # Phase 0a naming unchanged


@respx.mock
async def test_fetch_bytes_maps_statuses_to_the_three_errors():
    respx.get("https://example.test/ok").mock(return_value=httpx.Response(200, content=b"body"))
    respx.get("https://example.test/gone").mock(return_value=httpx.Response(404))
    respx.get("https://example.test/expired").mock(return_value=httpx.Response(401))
    respx.get("https://example.test/forbidden").mock(return_value=httpx.Response(403))
    respx.get("https://example.test/to-login").mock(
        return_value=httpx.Response(302, headers={"location": "https://example.test/login?from=x"}))
    respx.get("https://example.test/elsewhere").mock(
        return_value=httpx.Response(302, headers={"location": "https://example.test/other"}))
    respx.get("https://example.test/boom").mock(return_value=httpx.Response(500, text="server says no"))
    respx.post("https://example.test/form").mock(return_value=httpx.Response(200, content=b"posted"))
    async with build_http() as http:
        assert await fetch_bytes(http, "https://example.test/ok") == b"body"
        assert await fetch_bytes(http, "https://example.test/form", method="POST",
                                 data={"league": "Serie_A"}) == b"posted"
        with pytest.raises(NotPublished):
            await fetch_bytes(http, "https://example.test/gone")
        for path in ("expired", "forbidden", "to-login"):
            with pytest.raises(WebSessionExpired):
                await fetch_bytes(http, f"https://example.test/{path}")
        with pytest.raises(SourceError) as excinfo:
            await fetch_bytes(http, "https://example.test/elsewhere")
        assert excinfo.value.status == 302 and not isinstance(excinfo.value, WebSessionExpired)
        with pytest.raises(SourceError, match="server says no"):
            await fetch_bytes(http, "https://example.test/boom")
    sent = respx.calls[0].request
    assert sent.headers["user-agent"] == USER_AGENT and USER_AGENT.startswith("fantaclaude/")
    form = respx.calls[1].request
    assert b"league=Serie_A" in form.content


@respx.mock
def test_run_web_runs_a_coroutine_with_one_client_and_closes_it():
    respx.get("https://example.test/ok").mock(return_value=httpx.Response(200, content=b"1"))

    async def go(http):
        return await fetch_bytes(http, "https://example.test/ok", params={"q": "z"})

    assert run_web(go) == b"1"
    assert str(respx.calls[0].request.url) == "https://example.test/ok?q=z"


def test_web_cookie_reads_env_over_dotenv_and_never_returns_blank(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.delenv(WEB_COOKIE_KEY, raising=False)
    assert web_cookie() is None
    (tmp_path / ".env").write_text('FANTACALCIO_WEB_COOKIE="a=1; b=2"\n')
    assert web_cookie() == "a=1; b=2" and load_env()[WEB_COOKIE_KEY] == "a=1; b=2"
    monkeypatch.setenv(WEB_COOKIE_KEY, "   ")
    assert web_cookie() is None
    monkeypatch.setenv(WEB_COOKIE_KEY, "c=3")
    assert web_cookie() == "c=3"
    assert web_cookie({"FANTACALCIO_WEB_COOKIE": "d=4"}) == "d=4"


def test_aliases_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    from fantaclaude.paths import aliases_path

    assert aliases_path() == tmp_path.resolve() / "kb" / "rules" / "aliases.yml"


def test_polite_pause_is_a_real_sleep(monkeypatch):
    from fantaclaude.ingest import http as http_module

    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(http_module.asyncio, "sleep", fake_sleep)
    asyncio.run(http_module.polite_pause())
    asyncio.run(http_module.polite_pause(0.2))
    assert slept == [http_module.POLITE_DELAY_SECONDS, 0.2] and http_module.POLITE_DELAY_SECONDS >= 1.0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_raw_http.py -q`
Expected: FAIL — `ImportError` on `fantaclaude.config` / `fantaclaude.ingest.http`; `write_bytes` missing.

- [ ] **Step 4: Extend `RawStore`**

Replace the `write` and `list` methods in `core/src/fantaclaude/ingest/raw.py` with:

```python
    def write(self, kind: str, payload: Any, *, label: str | None = None,
              fetched_at: datetime | None = None) -> RawFile:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        return self.write_bytes(kind, data, ext="json", label=label, fetched_at=fetched_at)

    def write_bytes(self, kind: str, data: bytes, *, ext: str, label: str | None = None,
                    fetched_at: datetime | None = None) -> RawFile:
        """data/raw/<kind>/<UTC stamp>-<kind>[-<label>].<ext>, O_EXCL and fsynced.

        `label` names what the file is *of* -- a season, a giornata, a page --
        so a directory listing reads without opening anything; the stamp keeps
        two fetches of the same thing apart.
        """
        fetched_at = fetched_at or utc_now()
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        stamp = fetched_at.strftime("%Y%m%dT%H%M%S%fZ")    # microseconds keep two writes apart
        suffix = f"-{label}" if label else ""
        path = folder / f"{stamp}-{kind}{suffix}.{ext}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        return RawFile(path, hashlib.sha256(data).hexdigest(), fetched_at, kind)

    def list(self, kind: str, *, ext: str = "json", label: str | None = None) -> list[Path]:
        """Every file of `kind` and `ext`, or only those of one `label`."""
        folder = self.root / kind
        pattern = f"*-{kind}-{label}.{ext}" if label else f"*-{kind}*.{ext}"
        return sorted(folder.glob(pattern)) if folder.is_dir() else []
```

Update the module docstring's first line to `data/raw/<kind>/<UTC stamp>-<kind>[-<label>].<ext>, created O_EXCL so nothing is ever`.

- [ ] **Step 5: Write `ingest/http.py`**

```python
"""HTTP for the web sources: one client, one User-Agent, one error vocabulary.

fantacalcio.it, Understat and UEFA are public hosts read politely -- an
honest User-Agent, one request at a time, a pause between pages of the same
host, never a retry. Errors map to three classes the callers act on
differently: an expired website session (stop and ask for a new cookie), a
resource that does not exist yet (stop this loop, not the run), and anything
else (fail loud). Verified 2026-08-28 that all three hosts answer this
User-Agent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from fantaclaude import __version__

USER_AGENT = f"fantaclaude/{__version__} (personal Fantacalcio assistant; one request at a time)"
POLITE_DELAY_SECONDS = 1.0


class SourceError(RuntimeError):
    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class WebSessionExpired(SourceError):
    """401/403, or a redirect to a login page: the session no longer authenticates."""


class NotPublished(SourceError):
    """404: the resource is not there (yet)."""


def build_http(*, timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT},
                             follow_redirects=False)


async def fetch_bytes(http: httpx.AsyncClient, url: str, *, method: str = "GET",
                      headers: dict[str, str] | None = None,
                      params: dict[str, Any] | None = None,
                      data: dict[str, Any] | None = None) -> bytes:
    response = await http.request(method, url, headers=headers, params=params, data=data)
    status = response.status_code
    if status in (401, 403):
        raise WebSessionExpired(f"{url} -> HTTP {status}", url=url, status=status)
    if 300 <= status < 400:
        target = response.headers.get("location", "")
        if "login" in target.lower():
            raise WebSessionExpired(f"{url} -> HTTP {status} to {target}", url=url, status=status)
        raise SourceError(f"{url} -> unexpected redirect to {target!r}", url=url, status=status)
    if status == 404:
        raise NotPublished(f"{url} -> HTTP 404", url=url, status=status)
    if status >= 400:
        raise SourceError(f"{url} -> HTTP {status}: {response.text[:200]}", url=url, status=status)
    return response.content


async def polite_pause(seconds: float = POLITE_DELAY_SECONDS) -> None:
    await asyncio.sleep(seconds)


def run_web[T](fn: Callable[[httpx.AsyncClient], Awaitable[T]]) -> T:
    """Run `fn(http)` to completion on one event loop and close the client on
    that same loop -- the sync bridge the CLI uses, mirroring run_with_api."""
    async def go() -> T:
        http = build_http()
        try:
            return await fn(http)
        finally:
            await http.aclose()
    return asyncio.run(go())
```

- [ ] **Step 6: Write `config.py` and `aliases_path`**

Create `core/src/fantaclaude/config.py`:

```python
"""Environment for the web sources -- the same .env the MCP reads.

FANTACALCIO_WEB_COOKIE is the fantacalcio.it *website* session, a different
login from the league API's (spec, open question 5). It is captured from a
browser by the account holder and pasted into .env; no code obtains it, so
there is no login here to hammer and nothing to lock. It is a secret: it is
read, sent, and never printed.
"""

from __future__ import annotations

import os

from fantacalcio_mcp.config import env_path, load_dotenv

WEB_COOKIE_KEY = "FANTACALCIO_WEB_COOKIE"


def load_env() -> dict[str, str]:
    """.env merged under the process environment, exactly as load_settings does."""
    return {**load_dotenv(env_path()), **os.environ}


def web_cookie(env: dict[str, str] | None = None) -> str | None:
    env = load_env() if env is None else env
    value = (env.get(WEB_COOKIE_KEY) or "").strip()
    return value or None
```

Append to `core/src/fantaclaude/paths.py`:

```python


def aliases_path() -> Path:
    return kb_dir() / "rules" / "aliases.yml"
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_raw_http.py core/tests/test_listone.py -q`
Expected: 15 passed (6 new; `test_raw_store_writes_immutable_dated_files` still green — the listone naming is unchanged).

- [ ] **Step 8: Run the whole suite and lint, then commit**

Run: `uv run poe test-core && uv run ruff check core`
Expected: 97 passed; ruff clean.

```bash
git add core/pyproject.toml uv.lock core/src/fantaclaude/ingest/raw.py core/src/fantaclaude/ingest/http.py core/src/fantaclaude/config.py core/src/fantaclaude/paths.py core/tests/test_raw_http.py
git commit -m "feat(ingest): raw bytes with labels, a polite HTTP helper, and the website-cookie setting"
```

---

### Task 3: Name matching onto the listone, and `kb/rules/aliases.yml`

**Files:**
- Create: `core/src/fantaclaude/ingest/names.py`, `core/tests/test_names.py`
- Modify: `kb/rules/aliases.yml`

**Interfaces:**
- Consumes: `v_players_current`, `v_teams_current` (Phase 0a schema).
- Produces: `fantaclaude.ingest.names.{normalise(text) -> list[str], split_listone_name(name) -> tuple[list[str], str | None], Candidate(player_id, name, team_short, team_name) with .surname/.initial, Match(player_id, status, candidates), MATCHED/ALIAS/AMBIGUOUS/UNMATCHED, Matcher(candidates, aliases=None).match(source_name, source_teams=()) -> Match, AliasError, resolve_team(source_name, teams, aliases) -> str | None, load_candidates(con) -> list[Candidate], load_teams(con) -> dict[str, str], Aliases(players, teams), load_aliases(path) -> Aliases}`.

Matching rule, in order — a human alias wins; else the longest suffix of the source name that equals a listone surname; among several, keep those whose listone initial (`Lo.`, `F.P.`) is compatible with the source's given name(s); if the given name contradicts every initial, stop and ask (`ambiguous`); if more than one survives, the source's club decides; otherwise `ambiguous` with the candidates listed. No surname hit at all is `unmatched`. Measured on 2026-08-28 against the captured Understat seasons: 2025-26 → 365 matched / 7 ambiguous / 214 unmatched (the unmatched are almost all players no longer in Serie A); 2026-27 → 300 / 1 / 18. The initial check applies to a lone candidate too: without it "Alberto Moreno", "Marius Marin" and "Woyo Coulibaly" matched three different listone players who merely share their surnames.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_names.py`:

```python
import pytest
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.names import (
    ALIAS,
    AMBIGUOUS,
    MATCHED,
    UNMATCHED,
    AliasError,
    Candidate,
    Matcher,
    load_aliases,
    load_candidates,
    load_teams,
    normalise,
    resolve_team,
    split_listone_name,
)
from fantaclaude.ingest.raw import RawStore


def test_normalise_strips_accents_and_punctuation():
    assert normalise("Rasmus Højlund") == ["rasmus", "hojlund"]
    assert normalise("Lautaro Martínez") == ["lautaro", "martinez"]
    assert normalise("M'Bala Nzola") == ["m", "bala", "nzola"]
    assert normalise("Bodø/Glimt") == ["bodo", "glimt"]
    assert normalise("Konè M.") == ["kone", "m"]
    assert normalise("  Łukasz  Skorupski ") == ["lukasz", "skorupski"]
    assert normalise("") == []


def test_split_listone_name():
    assert split_listone_name("Martinez L.") == (["martinez"], "l")
    assert split_listone_name("Pellegrini Lo.") == (["pellegrini"], "lo")
    assert split_listone_name("Esposito F.P.") == (["esposito"], "fp")
    assert split_listone_name("Ederson D.S.") == (["ederson"], "ds")
    assert split_listone_name("Thuram") == (["thuram"], None)
    assert split_listone_name("Rossi F. *") == (["rossi"], "f")
    assert split_listone_name("Carlos Augusto") == (["carlos", "augusto"], None)
    assert split_listone_name("De Bruyne") == (["de", "bruyne"], None)


CANDIDATES = [
    Candidate(2764, "Martinez L.", "INT", "Inter"),
    Candidate(5116, "Martinez Jo.", "INT", "Inter"),
    Candidate(4871, "Thuram", "INT", "Inter"),
    Candidate(5562, "Thuram K.", "JUV", "Juventus"),
    Candidate(6052, "Hojlund", "NAP", "Napoli"),
    Candidate(530, "Pellegrini Lo.", "ROM", "Roma"),
    Candidate(2728, "Pellegrini Lu.", "LAZ", "Lazio"),
    Candidate(6024, "Sulemana I.", "ATA", "Atalanta"),
    Candidate(5918, "Sulemana K.", "ATA", "Atalanta"),
    Candidate(2815, "Terracciano", "MIL", "Milan"),
    Candidate(5812, "Terracciano F.", "MIL", "Milan"),
    Candidate(7000, "Konè M.", "ROM", "Roma"),
    Candidate(7001, "Kone B.", "ATA", "Atalanta"),
    Candidate(7002, "Konè I.", "ROM", "Roma"),
    Candidate(2517, "De Bruyne", "NAP", "Napoli"),
    Candidate(5877, "Carlos Augusto", "INT", "Inter"),
    Candidate(5792, "Ederson D.S.", "ATA", "Atalanta"),
    Candidate(7003, "Esposito Se.", "CAG", "Cagliari"),
    Candidate(7004, "Esposito F.P.", "INT", "Inter"),
    Candidate(7005, "Dumfries", "INT", "Inter"),
    Candidate(2120, "Bastoni A.", "INT", "Inter"),
]


@pytest.mark.parametrize("source, teams, status, player_id", [
    ("Lautaro Martínez", ("INT",), MATCHED, 2764),        # initial decides
    ("Josep Martínez", ("INT",), MATCHED, 5116),          # two-letter initial is a prefix of the given name
    ("Marcus Thuram", ("INT",), MATCHED, 4871),           # bare surname is compatible; K. is not
    ("Khephren Thuram", ("JUV",), MATCHED, 5562),
    ("Rasmus Højlund", ("NAP",), MATCHED, 6052),          # accent folding
    ("Lorenzo Pellegrini", ("ROM",), MATCHED, 530),
    ("Sulemana", ("BOL", "CAG"), AMBIGUOUS, None),        # no given name, club does not help
    ("Ibrahim Sulemana", ("ATA",), MATCHED, 6024),
    ("Pietro Terracciano", ("MIL",), MATCHED, 2815),      # F. excluded, bare surname stays
    ("Filippo Terracciano", (), AMBIGUOUS, None),         # F. and the bare surname both fit; no club
    ("Kouadio Kone", ("ROM",), AMBIGUOUS, None),          # the given name contradicts every initial
    ("Kevin De Bruyne", ("NAP",), MATCHED, 2517),         # multi-token surname
    ("Carlos Augusto", ("INT",), MATCHED, 5877),          # the whole source name is the surname
    ("Ederson", ("ATA",), MATCHED, 5792),                 # mononym, initials ignored
    ("Francesco Pio Esposito", ("INT",), MATCHED, 7004),  # F.P. = initials of two given names
    ("Sebastiano Esposito", ("CAG",), MATCHED, 7003),
    ("Denzel Dumfries", ("INT",), MATCHED, 7005),
    ("Jamie Vardy", ("CRE",), UNMATCHED, None),
    ("Khvicha Hojlund", ("NAP",), MATCHED, 6052),      # a lone candidate without an initial fits any given name
    ("Josep Bastoni", ("INT",), AMBIGUOUS, None),       # a lone candidate whose initial contradicts the given name does not
    ("", (), UNMATCHED, None),
])
def test_matcher_cases(source, teams, status, player_id):
    result = Matcher(CANDIDATES).match(source, teams)
    assert (result.status, result.player_id) == (status, player_id), result


def test_matcher_reports_candidates_and_honours_aliases():
    matcher = Matcher(CANDIDATES, aliases={"Sulemana": 5918, "Kouadio Kone": 7000})
    ambiguous = Matcher(CANDIDATES).match("Sulemana", ("BOL",))
    assert ambiguous.status == AMBIGUOUS and set(ambiguous.candidates) == {6024, 5918}
    assert matcher.match("Sulemana", ("BOL",)) == Matcher(CANDIDATES, {"Sulemana": 5918}).match("Sulemana")
    assert matcher.match("Sulemana").status == ALIAS and matcher.match("Sulemana").player_id == 5918
    assert matcher.match("Kouadio Kone").player_id == 7000
    with pytest.raises(AliasError, match="999999"):
        Matcher(CANDIDATES, aliases={"Nobody": 999999})           # an alias must point at a listone id


def test_resolve_team_is_case_insensitive_and_alias_aware():
    teams = {"milan": "MIL", "parma": "PAR", "inter": "INT"}
    aliases = {"AC Milan": "Milan", "Parma Calcio 1913": "Parma"}
    assert resolve_team("Inter", teams, aliases) == "INT"
    assert resolve_team("inter ", teams, aliases) == "INT"
    assert resolve_team("AC Milan", teams, aliases) == "MIL"
    assert resolve_team("Parma Calcio 1913", teams, aliases) == "PAR"
    assert resolve_team("Cremonese", teams, aliases) is None


def test_load_aliases_validates_shapes(tmp_path):
    path = tmp_path / "aliases.yml"
    path.write_text("understat:\n  Marcus Thuram: 4871\nunderstat_teams:\n  AC Milan: Milan\nuefa_teams: {}\n")
    aliases = load_aliases(path)
    assert aliases.players == {"understat": {"Marcus Thuram": 4871}}
    assert aliases.teams == {"understat": {"AC Milan": "Milan"}, "uefa": {}}
    path.write_text("understat:\n  Marcus Thuram: Thuram\n")
    with pytest.raises(AliasError, match="listone id"):
        load_aliases(path)
    path.write_text("understat_teams:\n  AC Milan: 12\n")
    with pytest.raises(AliasError, match="team name"):
        load_aliases(path)
    path.write_text("- not a mapping\n")
    with pytest.raises(AliasError):
        load_aliases(path)
    path.write_text("")
    assert load_aliases(path).players == {} and load_aliases(path).teams == {}


def test_committed_aliases_file_parses(monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import aliases_path

    aliases = load_aliases(aliases_path())
    assert aliases.teams["understat"] == {"AC Milan": "Milan", "Parma Calcio 1913": "Parma"}
    assert "understat" in aliases.players and {"uefa", "fantacalcio"} <= set(aliases.teams)


def test_candidates_and_teams_come_from_the_current_listone(db, tmp_path, fixture_json):
    store = RawStore(tmp_path / "raw")
    raw = store.write("listone", fixture_json("listone_sample"))
    record_listone(db, load_listone(raw.path), raw)
    candidates = {c.player_id: c for c in load_candidates(db)}
    assert len(candidates) == 17 and candidates[2764].name == "Martinez L."
    assert candidates[2764].surname == "martinez" and candidates[2764].initial == "l"
    assert candidates[2764].team_short == "INT" and candidates[2764].team_name == "Inter"
    teams = load_teams(db)
    assert teams["inter"] == "INT" and teams["atalanta"] == "ATA"
    assert Matcher(load_candidates(db)).match("Lautaro Martínez", ("INT",)).player_id == 2764
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_names.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.ingest.names`.

- [ ] **Step 3: Write `ingest/names.py`**

```python
"""Name matching across sources, and the aliases that override it.

fantacalcio.it writes "Martinez L." and "Pellegrini Lo."; Understat writes
"Lautaro Martínez" and "Lorenzo Pellegrini". The listone is the identity
(player_id); every other source is matched onto it -- surname first, then
the initial, then the club -- and a human alias in kb/rules/aliases.yml
beats all three. A row that cannot be decided is flagged with its
candidates, never dropped and never guessed: a wrong join is worse than a
missing one, because nothing downstream would notice it.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import yaml

MATCHED, ALIAS, AMBIGUOUS, UNMATCHED = "matched", "alias", "ambiguous", "unmatched"

# Letters NFKD does not decompose, plus the punctuation that splits a name.
_EXTRA = str.maketrans({"ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
                        "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
                        "'": " ", "’": " ", "-": " ", "/": " "})


def normalise(text: str) -> list[str]:
    """Lower-case ASCII tokens: accents stripped, punctuation to spaces."""
    text = unicodedata.normalize("NFKD", text.translate(_EXTRA))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch if ch.isalpha() else " " for ch in text.lower()).split()


def split_listone_name(name: str) -> tuple[list[str], str | None]:
    """"Pellegrini Lo." -> (["pellegrini"], "lo"); "Thuram" -> (["thuram"], None).

    A part ending in "." is an initial (the listone's way of telling two
    surnames apart); "*" is the transfer flag, not a name."""
    surname: list[str] = []
    initials: list[str] = []
    for part in name.replace("*", " ").split():
        (initials if part.endswith(".") else surname).extend(normalise(part))
    return surname, ("".join(initials) or None)


@dataclass(frozen=True)
class Candidate:
    player_id: int
    name: str                    # as the listone writes it
    team_short: str
    team_name: str

    @property
    def surname(self) -> str:
        return " ".join(split_listone_name(self.name)[0])

    @property
    def initial(self) -> str | None:
        return split_listone_name(self.name)[1]


@dataclass(frozen=True)
class Match:
    player_id: int | None
    status: str                          # matched | alias | ambiguous | unmatched
    candidates: tuple[int, ...] = ()     # listone ids that share the surname


class AliasError(ValueError):
    """aliases.yml is malformed or names an id the listone does not have."""


def _compatible(candidate: Candidate, given: list[str]) -> bool:
    """Does the listone initial fit the source's given name(s)?"""
    initial = candidate.initial
    if initial is None or not given:
        return True
    acronym = "".join(token[0] for token in given)
    return given[0].startswith(initial) or acronym.startswith(initial)


class Matcher:
    def __init__(self, candidates: list[Candidate], aliases: dict[str, int] | None = None) -> None:
        self._by_surname: dict[str, list[Candidate]] = {}
        for candidate in candidates:
            self._by_surname.setdefault(candidate.surname, []).append(candidate)
        ids = {c.player_id for c in candidates}
        self._aliases = dict(aliases or {})
        unknown = sorted(str(v) for v in self._aliases.values() if v not in ids)
        if unknown:
            raise AliasError(f"aliases name listone ids that do not exist: {', '.join(unknown)}")

    def match(self, source_name: str, source_teams: tuple[str, ...] = ()) -> Match:
        alias = self._aliases.get(source_name)
        if alias is not None:
            return Match(alias, ALIAS, (alias,))
        tokens = normalise(source_name)
        found: list[Candidate] = []
        split_at = 0
        for split_at in range(len(tokens)):
            found = self._by_surname.get(" ".join(tokens[split_at:]), [])
            if found:
                break
        if not found:
            return Match(None, UNMATCHED)
        ids = tuple(c.player_id for c in found)
        # The initial is checked even for a lone candidate: with a partial
        # listone, "Josep Martínez" must not silently become "Martinez L.".
        given = tokens[:split_at]
        narrowed = [c for c in found if _compatible(c, given)]
        if given and not narrowed:
            return Match(None, AMBIGUOUS, ids)          # the given name contradicts every initial
        if len(narrowed) == 1:
            return Match(narrowed[0].player_id, MATCHED, ids)
        by_club = [c for c in narrowed if c.team_short in set(source_teams)]
        if len(by_club) == 1:
            return Match(by_club[0].player_id, MATCHED, ids)
        return Match(None, AMBIGUOUS, ids)


def resolve_team(source_name: str, teams: dict[str, str], aliases: dict[str, str]) -> str | None:
    """`teams`: lower-cased listone team name -> short code; `aliases`: the
    source's spelling -> the listone's name. None when the club is not in
    the listone (a relegated side in a back season, a foreign club)."""
    name = aliases.get(source_name.strip(), source_name)
    return teams.get(name.strip().lower())


def load_candidates(con: duckdb.DuckDBPyConnection) -> list[Candidate]:
    rows = con.execute(
        "SELECT player_id, name, team_short, team_name FROM v_players_current ORDER BY player_id").fetchall()
    return [Candidate(int(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]


def load_teams(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return {str(name).lower(): str(short)
            for name, short in con.execute("SELECT name, short FROM v_teams_current").fetchall()}


@dataclass(frozen=True)
class Aliases:
    players: dict[str, dict[str, int]] = field(default_factory=dict)   # source -> spelling -> player_id
    teams: dict[str, dict[str, str]] = field(default_factory=dict)     # source -> spelling -> listone name

    def players_for(self, source: str) -> dict[str, int]:
        return self.players.get(source, {})

    def teams_for(self, source: str) -> dict[str, str]:
        return self.teams.get(source, {})


def load_aliases(path: Path) -> Aliases:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise AliasError(f"{path}: the top level must be a mapping of sources")
    players: dict[str, dict[str, int]] = {}
    teams: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        value = value or {}
        if not isinstance(value, dict):
            raise AliasError(f"{path}: {key} must be a mapping")
        if str(key).endswith("_teams"):
            bad = [k for k, v in value.items() if not isinstance(v, str)]
            if bad:
                raise AliasError(f"{path}: {key}: a team alias maps to a listone team name, not {bad}")
            teams[str(key).removesuffix("_teams")] = {str(k): v for k, v in value.items()}
        else:
            bad = [k for k, v in value.items() if isinstance(v, bool) or not isinstance(v, int)]
            if bad:
                raise AliasError(f"{path}: {key}: a player alias maps to a listone id, not {bad}")
            players[str(key)] = {str(k): v for k, v in value.items()}
    return Aliases(players, teams)
```

- [ ] **Step 4: Rewrite `kb/rules/aliases.yml`**

```yaml
# Human overrides for name matching across sources, keyed by source. A player
# alias maps the source's spelling to the listone player id; a `<source>_teams`
# alias maps the source's club spelling to the listone team name. Filled by hand
# when `fantaclaude ingest advanced` / `ingest calendar` report an ambiguous or
# unresolved name (`fantaclaude query --sql "SELECT * FROM v_advanced_unmatched"`
# lists them). The listone and FantaAstaLive share ids and need none.
understat: {}
understat_teams:
  AC Milan: Milan
  Parma Calcio 1913: Parma
uefa_teams: {}
fantacalcio_teams: {}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_names.py -q`
Expected: 28 passed (21 parametrised cases + 7).

- [ ] **Step 6: Run the whole suite and lint, then commit**

Run: `uv run poe test-core && uv run ruff check core`
Expected: 125 passed; ruff clean. (`test_doctor` still passes: the `kb` check only requires `aliases.yml` to exist.)

```bash
git add core/src/fantaclaude/ingest/names.py core/tests/test_names.py kb/rules/aliases.yml
git commit -m "feat(ingest): match source names onto listone ids, with a human alias file"
```

---

### Task 4: The `advanced` adapter — Understat season totals, matched onto the listone

**Files:**
- Create: `core/src/fantaclaude/ingest/advanced.py`, `core/tests/fixtures/_extract_understat.py`, `core/tests/fixtures/understat_sample.json`, `core/tests/test_advanced.py`
- Modify: `core/src/fantaclaude/commands/ingest.py`, `core/src/fantaclaude/cli/app.py`, `core/tests/test_fixtures.py`

**Interfaces:**
- Consumes: `RawStore.write(kind, payload, *, label)`, `fetch_bytes`, `polite_pause`, `run_web`, `Matcher`, `resolve_team`, `load_candidates`, `load_teams`, `load_aliases`, `Aliases.players_for/teams_for`, `understat_season`, `back_seasons`, `to_db`, the schema's `advanced_snapshots`/`advanced_stats`.
- Produces: `fantaclaude.ingest.advanced.{SOURCE, URL, AdvancedShapeError, AdvancedRow, async fetch_advanced(http, store, *, season_id) -> RawFile, load_advanced(path) -> tuple[int, list[AdvancedRow]], AdvancedIngestResult(...).to_dict(), record_advanced(con, season_id, rows, raw, *, candidates, teams, aliases) -> AdvancedIngestResult}`; `fantaclaude.commands.ingest.{NotReady, current_season_id(path=None) -> int, default_seasons(*, back=3) -> list[int], async fetch_advanced_seasons(http, store, seasons) -> dict[int, RawFile], record_advanced_seasons(con, raws, aliases_path) -> list[AdvancedIngestResult]}`; CLI `fantaclaude ingest advanced [--season N]... [--json]`; `cli.app._source_errors()` context manager.

- [ ] **Step 1: Build the Understat fixture from the capture**

Create `core/tests/fixtures/_extract_understat.py`:

```python
"""One-shot: build understat_sample.json from captured/understat-serie-a-2025.json.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_understat.py

Ten rows of the 2025-26 season chosen so that, matched against the
17-player listone_sample, every outcome appears: five matches (an initial
decides one, an accent another, a multi-token surname a third, a club alias
resolves Pulisic's "AC Milan"), one ambiguous (Josep Martínez against a
listone that only has Martinez L.), and four with no candidate at all
(Sulemana is also a mid-season mover, "Bologna,Cagliari"). The wrapper is
what fetch_advanced writes. Public statistics, nothing to scrub.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "understat-serie-a-2025.json"
OUT = Path(__file__).with_name("understat_sample.json")

NAMES = ["Lautaro Martínez", "Josep Martínez", "Rasmus Højlund", "Kevin De Bruyne", "Christian Pulisic",
         "Sead Kolasinac", "Sulemana", "Pietro Terracciano", "Jamie Vardy", "M&#039;Bala Nzola"]


def main() -> None:
    players = {p["player_name"]: p for p in json.loads(CAPTURE.read_text(encoding="utf-8"))["players"]}
    rows = [players[name] for name in NAMES]
    doc = {"season_id": 20, "understat_season": 2025, "payload": {"success": True, "players": rows}}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} players: {[r['id'] for r in rows]}")


if __name__ == "__main__":
    main()
```

Run: `uv run python core/tests/fixtures/_extract_understat.py`
Expected: `wrote 10 players: ['7006', '9052', '11055', '447', '2662', '342', '10985', '6977', <Vardy's id>, <Nzola's id>]`.

- [ ] **Step 2: Write the failing tests**

In `core/tests/test_fixtures.py`, change `SECRET_KEYS` to `{"parola", "password", "token", "jwt", "email", "app_key", "cookie"}` and `test_expected_fixtures_exist` to:

```python
def test_expected_fixtures_exist():
    for name in ("listone_sample.json", "understat_sample.json"):
        assert (FIXTURE_DIR / name).is_file(), name
```

Create `core/tests/test_advanced.py`:

```python
import json
from pathlib import Path

import httpx
import pytest
import respx
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import NotReady, current_season_id, default_seasons, fetch_advanced_seasons
from fantaclaude.ingest.advanced import (
    URL,
    AdvancedShapeError,
    fetch_advanced,
    load_advanced,
    record_advanced,
)
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.names import Aliases, load_candidates, load_teams
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from typer.testing import CliRunner


def _listone(db, tmp_path, fixture_json):
    raw = RawStore(tmp_path / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(db, load_listone(raw.path), raw)


def _league(db, mcp_fixture_json):
    record_snapshot(db, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))


def test_load_advanced_reads_the_wrapper_and_the_rows(fixture_path):
    season_id, rows = load_advanced(fixture_path("understat_sample"))
    assert season_id == 20 and len(rows) == 10
    by = {r.source_id: r for r in rows}
    lautaro = by["7006"]
    assert lautaro.player_name == "Lautaro Martínez" and lautaro.teams == ("Inter",)
    assert (lautaro.games, lautaro.minutes, lautaro.goals, lautaro.assists) == (30, 2205, 17, 6)
    assert 17.0 < lautaro.xg < 17.3 and 6.2 < lautaro.xa < 6.4 and lautaro.position == "F S"
    assert by["10985"].teams == ("Bologna", "Cagliari")                    # a mid-season mover
    assert any(r.player_name == "M'Bala Nzola" for r in rows)              # HTML entities decoded
    assert by["7006"].raw["xGChain"].startswith("27.")                     # every source field survives in raw


def test_load_advanced_fails_loud_on_shape(tmp_path, fixture_json):
    doc = fixture_json("understat_sample")
    del doc["payload"]["players"][0]["xG"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(AdvancedShapeError, match="xG"):
        load_advanced(path)
    path.write_text(json.dumps({"season_id": 20, "payload": {"success": True, "players": []}}))
    with pytest.raises(AdvancedShapeError):
        load_advanced(path)
    doc = fixture_json("understat_sample")
    doc["payload"]["players"].append(dict(doc["payload"]["players"][0]))
    path.write_text(json.dumps(doc))
    with pytest.raises(AdvancedShapeError, match="duplicate"):
        load_advanced(path)


def test_record_advanced_matches_flags_and_dedupes(db, tmp_path, fixture_json):
    _listone(db, tmp_path, fixture_json)
    store = RawStore(tmp_path / "raw")
    raw = store.write("advanced", fixture_json("understat_sample"), label="20")
    season_id, rows = load_advanced(raw.path)
    aliases = Aliases(players={"understat": {"Pietro Terracciano": 3}},        # any listone id: the mechanism is what is tested
                      teams={"understat": {"AC Milan": "Milan"}})
    result = record_advanced(db, season_id, rows, raw, candidates=load_candidates(db),
                             teams=load_teams(db), aliases=aliases)
    assert result.snapshot_id == 1 and result.inserted == 10 and not result.skipped_duplicate
    assert (result.matched, result.alias, result.ambiguous, result.unmatched) == (5, 1, 1, 3)
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
                            teams=load_teams(db), aliases=aliases)
    assert again.skipped_duplicate and again.snapshot_id == 1 and again.inserted == 0
    assert (again.matched, again.ambiguous, again.unmatched) == (5, 1, 3)

    changed = fixture_json("understat_sample")
    changed["payload"]["players"][0]["goals"] = "18"
    raw2 = store.write("advanced", changed, label="20")
    second = record_advanced(db, *load_advanced(raw2.path), raw2, candidates=load_candidates(db),
                             teams=load_teams(db), aliases=aliases)
    assert second.snapshot_id == 2
    assert db.execute("SELECT count(*) FROM advanced_stats").fetchone()[0] == 20         # history kept
    assert db.execute("SELECT goals FROM v_advanced_current WHERE source_id = '7006'").fetchone()[0] == 18


@respx.mock
async def test_fetch_advanced_posts_the_form_and_wraps_the_payload(tmp_path, fixture_json):
    payload = fixture_json("understat_sample")["payload"]
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as http:
        raw = await fetch_advanced(http, RawStore(tmp_path / "raw"), season_id=20)
    assert raw.path.name.endswith("-advanced-20.json")
    sent = route.calls[0].request
    assert sent.headers["x-requested-with"] == "XMLHttpRequest"
    assert b"league=Serie_A" in sent.content and b"season=2025" in sent.content
    season_id, rows = load_advanced(raw.path)
    assert season_id == 20 and len(rows) == 10
    respx.post(URL).mock(return_value=httpx.Response(200, json={"success": False}))
    async with httpx.AsyncClient() as http:
        with pytest.raises(AdvancedShapeError):
            await fetch_advanced(http, RawStore(tmp_path / "raw"), season_id=20)


@respx.mock
async def test_fetch_advanced_seasons_pauses_between_seasons(monkeypatch, tmp_path, fixture_json):
    payload = fixture_json("understat_sample")["payload"]
    respx.post(URL).mock(return_value=httpx.Response(200, json=payload))
    pauses = []

    async def fake_pause(seconds=None):
        pauses.append(seconds)

    monkeypatch.setattr("fantaclaude.commands.ingest.polite_pause", fake_pause)
    async with httpx.AsyncClient() as http:
        raws = await fetch_advanced_seasons(http, RawStore(tmp_path / "raw"), [19, 20, 21])
    assert sorted(raws) == [19, 20, 21] and len(pauses) == 2
    assert [Path(r.path).name[-8:] for r in raws.values()] == ["-19.json", "-20.json", "-21.json"]


def test_default_seasons_need_a_synced_league(tmp_path, db, mcp_fixture_json):
    path = tmp_path / "test.duckdb"
    with pytest.raises(NotReady, match="sync-league"):
        current_season_id(tmp_path / "missing.duckdb")
    _league(db, mcp_fixture_json)
    db.close()                              # one mode per process: the writer closes before the read-only peek
    assert current_season_id(path) == 21
    assert default_seasons(path=path) == [18, 19, 20, 21]


@respx.mock
def test_cli_ingest_advanced(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    (tmp_path / "kb" / "rules").mkdir(parents=True)
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("understat: {}\nunderstat_teams:\n  AC Milan: Milan\n")
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    _listone(con, tmp_path, fixture_json)
    _league(con, mcp_fixture_json)
    con.close()
    respx.post(URL).mock(return_value=httpx.Response(200, json=fixture_json("understat_sample")["payload"]))

    async def no_pause(seconds=None):
        pass

    monkeypatch.setattr("fantaclaude.commands.ingest.polite_pause", no_pause)
    result = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)["advanced"]
    assert [r["season_id"] for r in payload] == [20] and payload[0]["matched"] == 5
    assert list((tmp_path / "data" / "raw" / "advanced").glob("*-advanced-20.json"))

    plain = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20"])
    assert plain.exit_code == ExitCode.OK and "duplicate" in plain.stdout

    everything = CliRunner().invoke(app, ["ingest", "advanced", "--json"])            # default: 18..21
    assert everything.exit_code == ExitCode.OK, everything.output
    assert [r["season_id"] for r in json.loads(everything.stdout)["advanced"]] == [18, 19, 20, 21]

    respx.post(URL).mock(return_value=httpx.Response(503, text="down"))
    failed = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20"])
    assert failed.exit_code == ExitCode.ERROR and "503" in failed.stderr


def test_cli_ingest_advanced_without_a_database_is_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["ingest", "advanced"])
    assert result.exit_code == ExitCode.NOT_READY and "sync-league" in result.stderr
    assert not (tmp_path / "data" / "fanta.duckdb").exists()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_advanced.py core/tests/test_fixtures.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.ingest.advanced`; `ImportError: NotReady`.

- [ ] **Step 4: Write `ingest/advanced.py`**

```python
"""Understat season totals: fetch, load, match, record.

One POST per season to the endpoint Understat's own league page calls
(the page no longer embeds the tables), answering
{"success": true, "players": [...]} -- games, minutes ("time"), goals,
assists, xG, xA, shots, key passes, cards, per player per season: the
luck-correction inputs and the minutes the voti do not carry. Observed
2026-08-28; every field is a string, `team_title` is "A,B" for a mid-season
mover, `player_name` is HTML-escaped. Names are matched onto the listone by
ingest.names; unmatched and ambiguous rows are stored with player_id NULL
and reported, never dropped.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes
from fantaclaude.ingest.names import AMBIGUOUS, Aliases, Candidate, Matcher, resolve_team
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.model.seasons import understat_season
from fantaclaude.timeutil import to_db

SOURCE = "understat:POST /main/getPlayersStats/"
URL = "https://understat.com/main/getPlayersStats/"
REQUIRED = ("id", "player_name", "games", "time", "goals", "assists", "xG", "xA", "npg", "npxG",
            "shots", "key_passes", "yellow_cards", "red_cards", "position", "team_title",
            "xGChain", "xGBuildup")


class AdvancedShapeError(ValueError):
    """The payload is not the Understat table this adapter was written against."""


@dataclass(frozen=True)
class AdvancedRow:
    source_id: str
    player_name: str
    teams: tuple[str, ...]
    games: int
    minutes: int
    goals: int
    assists: int
    xg: float
    xa: float
    npg: int
    npxg: float
    shots: int
    key_passes: int
    yellow: int
    red: int
    xg_chain: float
    xg_buildup: float
    position: str
    raw: dict[str, Any]


async def fetch_advanced(http: httpx.AsyncClient, store: RawStore, *, season_id: int) -> RawFile:
    data = await fetch_bytes(http, URL, method="POST", headers={"X-Requested-With": "XMLHttpRequest"},
                             data={"league": "Serie_A", "season": str(understat_season(season_id))})
    try:
        payload = json.loads(data)
    except ValueError:
        raise AdvancedShapeError("Understat answered something that is not JSON") from None
    if not (isinstance(payload, dict) and payload.get("success") is True
            and isinstance(payload.get("players"), list)):
        raise AdvancedShapeError('Understat payload is not {"success": true, "players": [...]}')
    # The response does not say which season it is for, so the wrapper does.
    return store.write("advanced", {"season_id": season_id, "understat_season": understat_season(season_id),
                                    "payload": payload}, label=str(season_id))


def load_advanced(path: Path) -> tuple[int, list[AdvancedRow]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    players = doc.get("payload", {}).get("players") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or not isinstance(doc.get("season_id"), int) \
            or not isinstance(players, list) or not players:
        raise AdvancedShapeError(f"{path}: no season_id or no players")
    rows: list[AdvancedRow] = []
    for entry in players:
        missing = [k for k in REQUIRED if k not in entry]
        if missing:
            raise AdvancedShapeError(
                f"{path}: player {entry.get('id')} ({entry.get('player_name')}) lacks {missing}")
        rows.append(AdvancedRow(
            source_id=str(entry["id"]),
            player_name=html.unescape(str(entry["player_name"])).strip(),
            teams=tuple(t.strip() for t in str(entry["team_title"]).split(",") if t.strip()),
            games=int(entry["games"]), minutes=int(entry["time"]), goals=int(entry["goals"]),
            assists=int(entry["assists"]), xg=float(entry["xG"]), xa=float(entry["xA"]),
            npg=int(entry["npg"]), npxg=float(entry["npxG"]), shots=int(entry["shots"]),
            key_passes=int(entry["key_passes"]), yellow=int(entry["yellow_cards"]),
            red=int(entry["red_cards"]), xg_chain=float(entry["xGChain"]),
            xg_buildup=float(entry["xGBuildup"]), position=str(entry["position"]), raw=entry))
    ids = [r.source_id for r in rows]
    if len(set(ids)) != len(ids):
        raise AdvancedShapeError(f"{path}: duplicate Understat ids")
    return int(doc["season_id"]), rows


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

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "season_id": self.season_id, "inserted": self.inserted,
                "skipped_duplicate": self.skipped_duplicate, "matched": self.matched, "alias": self.alias,
                "ambiguous": self.ambiguous, "unmatched": self.unmatched,
                "ambiguous_names": self.ambiguous_names, "unresolved_teams": self.unresolved_teams,
                "sha256": self.sha256, "raw_path": self.raw_path}


def record_advanced(con: duckdb.DuckDBPyConnection, season_id: int, rows: list[AdvancedRow],
                    raw: RawFile, *, candidates: list[Candidate], teams: dict[str, str],
                    aliases: Aliases) -> AdvancedIngestResult:
    """Append one snapshot per distinct raw file; the same bytes twice is a no-op.

    Matching happens here, at record time, against the *current* listone: a
    re-record after the listone moved (a January transfer) re-matches from the
    same immutable file -- which is what "rebuildable from raw" means.
    """
    existing = con.execute(
        "SELECT snapshot_id, matched, ambiguous, unmatched FROM advanced_snapshots WHERE sha256 = ?",
        [raw.sha256]).fetchone()
    if existing is not None:
        alias_count = con.execute(
            "SELECT count(*) FROM advanced_stats WHERE snapshot_id = ? AND match_status = 'alias'",
            [existing[0]]).fetchone()[0]
        return AdvancedIngestResult(existing[0], season_id, 0, True, existing[1], alias_count,
                                    existing[2], existing[3], [], [], raw.sha256, str(raw.path))
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
        snapshot_id = con.execute(
            "INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, row_count, "
            "matched, ambiguous, unmatched) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING snapshot_id",
            [season_id, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, len(rows),
             counts["matched"], counts["ambiguous"], counts["unmatched"]]).fetchone()[0]
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
                                sorted(unresolved), raw.sha256, str(raw.path))
```

- [ ] **Step 5: Extend `commands/ingest.py`**

Replace the import block of `core/src/fantaclaude/commands/ingest.py` (everything between the module docstring and `async def fetch_all`) with:

```python
from __future__ import annotations

from pathlib import Path

import duckdb
import httpx
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.db.connection import DatabaseMissing, connect
from fantaclaude.ingest.advanced import (
    AdvancedIngestResult,
    fetch_advanced,
    load_advanced,
    record_advanced,
)
from fantaclaude.ingest.http import polite_pause
from fantaclaude.ingest.listone_api import (
    IngestResult,
    fetch_listone,
    load_listone,
    record_listone,
)
from fantaclaude.ingest.names import load_aliases, load_candidates, load_teams
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.model.seasons import back_seasons
```

and append to the module:

```python
class NotReady(RuntimeError):
    """No database, or no league_settings snapshot: the season is unknown."""


def current_season_id(path: Path | None = None) -> int:
    """The season the league is in, from the latest league_settings snapshot.

    Read-only and closed before returning: the caller fetches from the network
    next and opens read-write only to record, so no lock spans a request.
    """
    try:
        con = connect(path, read_only=True)
    except DatabaseMissing:
        raise NotReady("no database -- run `fantaclaude sync-league` first") from None
    try:
        row = con.execute("SELECT season_id FROM v_league_settings_current").fetchone()
    finally:
        con.close()
    if row is None or row[0] is None:
        raise NotReady("no league_settings snapshot -- run `fantaclaude sync-league` first")
    return int(row[0])


def default_seasons(*, back: int = 3, path: Path | None = None) -> list[int]:
    """The current season and the `back` before it, oldest first."""
    current = current_season_id(path)
    return [*back_seasons(current, back), current]


async def fetch_advanced_seasons(http: httpx.AsyncClient, store: RawStore,
                                 seasons: list[int]) -> dict[int, RawFile]:
    raws: dict[int, RawFile] = {}
    for index, season_id in enumerate(seasons):
        if index:
            await polite_pause()
        raws[season_id] = await fetch_advanced(http, store, season_id=season_id)
    return raws


def record_advanced_seasons(con: duckdb.DuckDBPyConnection, raws: dict[int, RawFile],
                            aliases_path: Path) -> list[AdvancedIngestResult]:
    aliases = load_aliases(aliases_path)
    candidates, teams = load_candidates(con), load_teams(con)
    results = []
    for season_id in sorted(raws):
        loaded_season, rows = load_advanced(raws[season_id].path)
        results.append(record_advanced(con, loaded_season, rows, raws[season_id],
                                       candidates=candidates, teams=teams, aliases=aliases))
    return results
```

- [ ] **Step 6: Add the CLI command**

In `core/src/fantaclaude/cli/app.py`, add `from contextlib import contextmanager` to the imports, then insert after `ingest_all_cmd`:

```python
# Module-level singletons for list-valued options: ruff's B008 exempts only
# immutable annotations, and `list[int] | None` is not one.
SEASON_OPTION = typer.Option(
    None, "--season", help="Season id(s), e.g. 20; default: the current season and the three before it.")


@contextmanager
def _source_errors():
    """Map the web sources' errors to the exit-code contract.

    An expired website session is "not ready" (3): the fix is a new cookie,
    not a bug. Anything else a source does wrong is an error (1).
    """
    from fantaclaude.ingest.http import SourceError, WebSessionExpired

    try:
        yield
    except WebSessionExpired as exc:
        typer.echo(f"website session rejected: {exc} -- re-capture FANTACALCIO_WEB_COOKIE "
                   f"(core/README.md, 'The website session')", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    except SourceError as exc:
        typer.echo(f"source failed: {exc}", err=True)
        raise typer.Exit(code=ExitCode.ERROR) from None


def _seasons_or_exit(season: list[int] | None) -> list[int]:
    from fantaclaude.commands.ingest import NotReady, default_seasons

    try:
        return list(season) if season else default_seasons()
    except NotReady as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None


def _render_advanced(payload: dict) -> str:
    lines = []
    for r in payload["advanced"]:
        if r["skipped_duplicate"]:
            lines.append(f"advanced {r['season_id']}: duplicate of snapshot {r['snapshot_id']} -- nothing new "
                         f"({r['matched']} matched, {r['ambiguous']} ambiguous, {r['unmatched']} unmatched)")
            continue
        lines.append(f"advanced {r['season_id']}: snapshot {r['snapshot_id']}, {r['inserted']} rows -- "
                     f"{r['matched']} matched, {r['alias']} alias, {r['ambiguous']} ambiguous, "
                     f"{r['unmatched']} unmatched ({r['raw_path']})")
        for a in r["ambiguous_names"]:
            options = ", ".join(f"{c['player_id']} {c['name']}" for c in a["candidates"])
            lines.append(f"  ambiguous: {a['name']} ({', '.join(a['teams'])}) -> {options}")
        if r["unresolved_teams"]:
            lines.append(f"  clubs not in the listone: {', '.join(r['unresolved_teams'])}")
    return "\n".join(lines)


@ingest_app.command("advanced")
def ingest_advanced_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    season: list[int] | None = SEASON_OPTION,
) -> None:
    """Understat season totals (games, minutes, xG, xA) for Serie A, matched onto the listone."""
    from fantaclaude.commands.ingest import fetch_advanced_seasons, record_advanced_seasons
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    seasons = _seasons_or_exit(season)
    store = RawStore(raw_dir())
    with _source_errors():
        raws = run_web(lambda http: fetch_advanced_seasons(http, store, seasons))
    con = connect()
    try:
        apply_schema(con)
        results = record_advanced_seasons(con, raws, aliases_path())
    finally:
        con.close()
    emit({"advanced": [r.to_dict() for r in results]}, json_=json_, render=_render_advanced)
```

Also change the `ingest all` help string from `"Refresh every source (only the listone in Phase 0a)."` to `"Refresh every source (listone; advanced, calendar and stats-web join in Task 8)."` — Task 8 replaces it again.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest core/tests/test_advanced.py core/tests/test_fixtures.py -q`
Expected: 10 passed.

- [ ] **Step 8: Run the whole suite and lint, then commit**

Run: `uv run poe test-core && uv run ruff check core`
Expected: 133 passed; ruff clean.

```bash
git add core/src/fantaclaude/ingest/advanced.py core/src/fantaclaude/commands/ingest.py core/src/fantaclaude/cli/app.py core/tests/fixtures/_extract_understat.py core/tests/fixtures/understat_sample.json core/tests/test_advanced.py core/tests/test_fixtures.py
git commit -m "feat(ingest): advanced -- Understat season totals matched onto the listone"
```

---

### Task 5: The `calendar` adapter — Serie A giornate and every European tie of an Italian club

**Files:**
- Create: `core/src/fantaclaude/ingest/calendar.py`, `core/tests/fixtures/_extract_calendar.py`, `core/tests/fixtures/calendario_sample.html`, `core/tests/fixtures/uefa_sample.json`, `core/tests/test_calendar.py`
- Modify: `core/src/fantaclaude/commands/ingest.py`, `core/src/fantaclaude/cli/app.py`, `core/tests/test_fixtures.py`

**Interfaces:**
- Consumes: `RawStore.write/write_bytes`, `fetch_bytes`, `polite_pause`, `run_web`, `resolve_team`, `load_teams`, `load_aliases`, `Aliases.teams_for`, `season_id_from_label`, `uefa_season_year`, `SERIE_A_GIORNATE`, `to_db`, `canonical_json` (from `league.settings`), the schema's `fixture_snapshots`/`fixtures`, `_seasons_or_exit`, `_source_errors`.
- Produces: `fantaclaude.ingest.calendar.{SOURCE_SERIE_A, SOURCE_UEFA, SERIE_A_URL, UEFA_URL, UEFA_COMPETITIONS, COMPETITIONS, UEFA_PAGE, CalendarShapeError, FixtureRow(...).canonical(), kickoff_rome(start_date, hours) -> datetime | None, parse_serie_a_page(html_text, *, season_id) -> list[FixtureRow], async fetch_serie_a(http, store, *, season_id, giornate) -> list[RawFile], load_serie_a(paths, *, season_id) -> list[FixtureRow], async fetch_uefa(http, store, *, season_id, competition) -> list[RawFile], load_uefa(paths) -> list[FixtureRow], schedule_hash(rows) -> str, FixtureIngestResult(...).to_dict(), record_fixtures(con, competition, season_id, rows, raws, *, teams, team_aliases) -> FixtureIngestResult}`; `fantaclaude.commands.ingest.{async fetch_calendar(http, store, season_id, competitions) -> dict[str, list[RawFile]], record_calendar(con, season_id, raws, aliases_path) -> list[FixtureIngestResult]}`; CLI `fantaclaude ingest calendar [--competition SA|UCL|UEL|UECL]... [--json]`; `cli.app.COMPETITION_OPTION`.

Scores are not modelled: `results` is Phase 3. A fixture row is the schedule — competition, round, kickoff (UTC), the two clubs and, for Serie A clubs, their listone short code — and a snapshot is appended only when the schedule changed (hash over the parsed rows, not over the pages, which carry ads and timestamps).

- [ ] **Step 1: Build the two fixtures from the captures**

Create `core/tests/fixtures/_extract_calendar.py`:

```python
"""One-shot: build calendario_sample.html and uefa_sample.json from the captures.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_calendar.py

calendario_sample.html keeps the three large pills of giornata 2, 2026-27
(Milan-Venezia 17971, Fiorentina-Frosinone 17967, Monza-Udinese 17972)
inside a minimal document; feeding it twice exercises the dedupe the page's
compact pills need. uefa_sample.json is what fetch_uefa writes, for two
pages: UCL 2025-26 (two Italian league-phase matches, one Juventus match to
trip the unresolved-club error against the 17-player listone, one Paris-
Arsenal match to be filtered out) and UECL 2026-27 (Atalanta's qualifying
play-off, both legs). Matches are slimmed the way the raw column is
(translations, player events, referees, related matches and logo URLs
dropped) so the fixture stays small. Public schedules, nothing to scrub.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "captured" / "calendario-2026-27-giornata-2.html"
UCL = ROOT / "captured" / "uefa-ucl-2026-page0.json"
UECL = ROOT / "captured" / "uefa-uecl-2027-page0.json"
OUT_HTML = Path(__file__).with_name("calendario_sample.html")
OUT_JSON = Path(__file__).with_name("uefa_sample.json")

SERIE_A_IDS = ("17971", "17967", "17972")
UCL_IDS = ("2048058", "2047774", "2047742", "2047770")
UECL_IDS = ("2049260", "2049284")
DROP = {"playerEvents", "referees", "relatedMatches", "translations"}


def slim(value):
    if isinstance(value, dict):
        return {k: slim(v) for k, v in value.items() if k not in DROP and not k.endswith("LogoUrl")}
    if isinstance(value, list):
        return [slim(v) for v in value]
    return value


def main() -> None:
    html = PAGE.read_text(encoding="utf-8")
    blocks = []
    for match_id in SERIE_A_IDS:
        anchor = html.index(f"/{match_id}\"")
        start = html.rfind('<li class="match', 0, anchor)
        end = html.index("</li>", anchor) + len("</li>")
        block = html[start:end]
        assert block.count("SportsEvent") == 1 and "size-large" in block, match_id
        blocks.append(block)
    OUT_HTML.write_text('<!doctype html>\n<html><body>\n<ul class="match-list">\n' + "\n".join(blocks)
                        + "\n</ul>\n</body></html>\n", encoding="utf-8")
    pages = []
    for path, competition, season_id, ids in ((UCL, "UCL", 20, UCL_IDS), (UECL, "UECL", 21, UECL_IDS)):
        matches = {str(m["id"]): m for m in json.loads(path.read_text(encoding="utf-8"))}
        pages.append({"competition": competition, "season_id": season_id, "offset": 0,
                      "matches": [slim(matches[i]) for i in ids]})
    OUT_JSON.write_text(json.dumps(pages, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(blocks)} pills ({OUT_HTML.stat().st_size} bytes) and "
          f"{sum(len(p['matches']) for p in pages)} UEFA matches ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
```

Run: `uv run python core/tests/fixtures/_extract_calendar.py`
Expected: `wrote 3 pills (8537 bytes) and 6 UEFA matches (<under 60000> bytes)`.

- [ ] **Step 2: Write the failing tests**

In `core/tests/test_fixtures.py`, extend `test_expected_fixtures_exist` to `for name in ("listone_sample.json", "understat_sample.json", "calendario_sample.html", "uefa_sample.json"):`.

Create `core/tests/test_calendar.py`:

```python
import json
import re
from datetime import UTC, datetime

import httpx
import pytest
import respx
from conftest import FIXTURE_DIR
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import fetch_calendar
from fantaclaude.ingest.calendar import (
    SERIE_A_URL,
    UEFA_URL,
    CalendarShapeError,
    fetch_serie_a,
    fetch_uefa,
    kickoff_rome,
    load_serie_a,
    load_uefa,
    parse_serie_a_page,
    record_fixtures,
    schedule_hash,
)
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from fantaclaude.timeutil import to_db
from typer.testing import CliRunner

SAMPLE = (FIXTURE_DIR / "calendario_sample.html").read_text(encoding="utf-8")
TEAMS = {"milan": "MIL", "venezia": "VEN", "fiorentina": "FIO", "frosinone": "FRO", "monza": "MON",
         "udinese": "UDI", "atalanta": "ATA", "inter": "INT", "juventus": "JUV"}


def _page(giornata: int, *, renamed: bool = False) -> str:
    """The sample rewritten as another giornata with its own match ids."""
    text = SAMPLE.replace("calendario/2/", f"calendario/{giornata}/")
    text = re.sub(r'(class="matchweek">\s*)2(\s*<)', rf"\g<1>{giornata}\2", text)
    for match_id in ("17971", "17967", "17972"):
        text = text.replace(f"/{match_id}\"", f"/{giornata:02d}{match_id}\"")
    if renamed:   # clubs the 17-player listone knows, so record_fixtures can resolve them
        for foreign, known in (("Venezia", "Inter"), ("Frosinone", "Napoli"), ("Monza", "Roma"), ("Udinese", "Genoa")):
            text = text.replace(foreign, known)
    return text


@pytest.fixture
def no_pause(monkeypatch):
    async def fake(seconds=None):
        pass

    monkeypatch.setattr("fantaclaude.ingest.calendar.polite_pause", fake)
    monkeypatch.setattr("fantaclaude.commands.ingest.polite_pause", fake)


def test_kickoff_rome_converts_to_utc_or_none():
    assert kickoff_rome("2026-08-28", "20:45") == datetime(2026, 8, 28, 18, 45, tzinfo=UTC)   # CEST
    assert kickoff_rome("2027-01-10", "15:00") == datetime(2027, 1, 10, 14, 0, tzinfo=UTC)    # CET
    assert kickoff_rome("2026-08-28", "--:--") is None and kickoff_rome("2026-08-28", "") is None
    assert kickoff_rome(None, "20:45") is None


def test_parse_serie_a_page_reads_the_microdata_and_dedupes():
    rows = parse_serie_a_page(SAMPLE, season_id=21)
    assert [r.source_id for r in rows] == ["17971", "17967", "17972"]           # by kickoff, then id
    milan = rows[0]
    assert (milan.competition, milan.season_id, milan.round, milan.giornata, milan.phase) == ("SA", 21, "2", 2, None)
    assert (milan.home, milan.away) == ("Milan", "Venezia") and milan.home_domestic and milan.away_domestic
    assert milan.kickoff == datetime(2026, 8, 28, 18, 45, tzinfo=UTC)
    assert milan.raw["stadium"] == "Giuseppe Meazza" and milan.raw["start_date"] == "2026-08-28"
    assert milan.raw["name"] == "Serie A 2026-27 - 2° giornata - milan-venezia"
    assert rows[1].kickoff == rows[2].kickoff == datetime(2026, 8, 29, 16, 30, tzinfo=UTC)
    assert len(parse_serie_a_page(SAMPLE + SAMPLE, season_id=21)) == 3          # the compact pills repeat the large ones
    assert milan.canonical() == {"competition": "SA", "season_id": 21, "source_id": "17971", "round": "2",
                                 "giornata": 2, "phase": None, "kickoff": "2026-08-28T18:45:00+00:00",
                                 "home": "Milan", "away": "Venezia"}


def test_parse_serie_a_page_fails_loud():
    with pytest.raises(CalendarShapeError, match="2026-27"):
        parse_serie_a_page(SAMPLE, season_id=20)                                # the site serves the current season only
    with pytest.raises(CalendarShapeError, match="no SportsEvent"):
        parse_serie_a_page("<html><body>nothing here</body></html>", season_id=21)
    broken = re.sub(r'(class="matchweek">\s*)2', r"\g<1>7", SAMPLE, count=1)
    with pytest.raises(CalendarShapeError, match="matchweek"):
        parse_serie_a_page(broken, season_id=21)
    with pytest.raises(CalendarShapeError, match="match link"):
        parse_serie_a_page(SAMPLE.replace('class="match-score unstyled"', 'class="score"'), season_id=21)


def test_load_uefa_keeps_matches_with_an_italian_side(fixture_path):
    rows = load_uefa([fixture_path("uefa_sample")])              # the fixture bundles two pages in one file
    by = {r.source_id: r for r in rows}
    assert set(by) == {"2048058", "2047774", "2047770", "2049260", "2049284"}   # Paris-Arsenal is out
    bayern = by["2048058"]
    assert (bayern.competition, bayern.season_id, bayern.round, bayern.phase) == ("UCL", 20, "MD12", "TOURNAMENT")
    assert (bayern.home, bayern.away) == ("Bayern München", "Atalanta")
    assert (bayern.home_domestic, bayern.away_domestic) == (False, True) and bayern.giornata is None
    assert bayern.kickoff == datetime(2026, 3, 18, 20, 0, tzinfo=UTC)
    first_leg = by["2049260"]
    assert (first_leg.competition, first_leg.season_id, first_leg.round, first_leg.phase) == ("UECL", 21, "MD1 - PO", "QUALIFYING")
    assert first_leg.kickoff == datetime(2026, 8, 20, 18, 30, tzinfo=UTC) and first_leg.home == "Atalanta"
    assert first_leg.raw["status"] == "FINISHED" and "translations" not in first_leg.raw["homeTeam"]


def test_load_uefa_fails_loud_on_shape(tmp_path, fixture_json):
    pages = fixture_json("uefa_sample")
    del pages[0]["matches"][0]["matchday"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(pages))
    with pytest.raises(CalendarShapeError, match="matchday"):
        load_uefa([path])
    path.write_text(json.dumps({"not": "a wrapper"}))
    with pytest.raises(CalendarShapeError):
        load_uefa([path])


def test_record_fixtures_snapshots_only_when_the_schedule_moves(db, tmp_path):
    store = RawStore(tmp_path / "raw")
    raw = store.write_bytes("calendar", SAMPLE.encode(), ext="html", label="sa-21-02")
    rows = parse_serie_a_page(SAMPLE, season_id=21)
    result = record_fixtures(db, "SA", 21, rows, [raw], teams=TEAMS, team_aliases={})
    assert result.snapshot_id == 1 and result.inserted == 3 and not result.skipped_unchanged
    assert result.sha256 == schedule_hash(rows) and result.raw_paths == [str(raw.path)]
    current = db.execute("SELECT source_id, home_short, away_short, giornata, kickoff FROM v_fixtures_current ORDER BY source_id").fetchall()
    assert current[0] == ("17967", "FIO", "FRO", 2, to_db(datetime(2026, 8, 29, 16, 30, tzinfo=UTC)))   # naive UTC in DuckDB
    assert current[1][1:3] == ("MIL", "VEN")

    again = record_fixtures(db, "SA", 21, rows, [raw], teams=TEAMS, team_aliases={})
    assert again.skipped_unchanged and again.snapshot_id == 1 and again.inserted == 0

    moved = parse_serie_a_page(SAMPLE.replace('class="hours">20:45', 'class="hours">18:00'), season_id=21)
    third = record_fixtures(db, "SA", 21, moved, [raw], teams=TEAMS, team_aliases={})
    assert third.snapshot_id == 2 and third.inserted == 3
    assert db.execute("SELECT count(*) FROM fixtures").fetchone()[0] == 6                    # history kept
    assert db.execute("SELECT kickoff FROM v_fixtures_current WHERE source_id = '17971'").fetchone()[0] == to_db(datetime(2026, 8, 28, 16, 0, tzinfo=UTC))

    with pytest.raises(CalendarShapeError, match="Venezia.*fantacalcio_teams"):
        record_fixtures(db, "SA", 21, rows, [raw], teams={"milan": "MIL"}, team_aliases={})
    aliased = record_fixtures(db, "SA", 21, rows, [raw], teams={"milan": "MIL", "venezia calcio": "VEN", "fiorentina": "FIO",
                                                                 "frosinone": "FRO", "monza": "MON", "udinese": "UDI"},
                              team_aliases={"Venezia": "Venezia Calcio"})
    assert aliased.inserted == 3


def test_record_uefa_rows_and_the_european_ties_view(db, tmp_path, fixture_path):
    store = RawStore(tmp_path / "raw")
    pages = json.loads(fixture_path("uefa_sample").read_text(encoding="utf-8"))
    raws = [store.write("calendar", page, label=f"{page['competition'].lower()}-{page['season_id']}-00") for page in pages]
    rows = load_uefa([raws[1].path])                                              # UECL 2026-27, Atalanta
    result = record_fixtures(db, "UECL", 21, rows, [raws[1]], teams=TEAMS, team_aliases={})
    assert result.inserted == 2
    ties = db.execute("SELECT competition, round, team_short, home, away FROM v_european_ties ORDER BY kickoff").fetchall()
    assert ties == [("UECL", "MD1 - PO", "ATA", "Atalanta", "H. Tel-Aviv"), ("UECL", "MD2 - PO", "ATA", "H. Tel-Aviv", "Atalanta")]
    assert db.execute("SELECT home_short FROM v_fixtures_current WHERE source_id = '2049284'").fetchone()[0] is None

    ucl = load_uefa([raws[0].path])
    with pytest.raises(CalendarShapeError, match="Juventus.*uefa_teams"):
        record_fixtures(db, "UCL", 20, ucl, [raws[0]], teams={"atalanta": "ATA", "inter": "INT"}, team_aliases={})
    ok = record_fixtures(db, "UCL", 20, ucl, [raws[0]], teams=TEAMS, team_aliases={})
    assert ok.inserted == 3
    assert db.execute("SELECT count(*) FROM v_european_ties WHERE competition = 'UCL'").fetchone()[0] == 3
    empty = record_fixtures(db, "UEL", 21, [], [raws[0]], teams=TEAMS, team_aliases={})
    assert empty.inserted == 0 and not empty.skipped_unchanged                    # "nothing scheduled" is a fact worth a snapshot
    assert record_fixtures(db, "UEL", 21, [], [raws[0]], teams=TEAMS, team_aliases={}).skipped_unchanged


@respx.mock
async def test_fetch_serie_a_writes_one_page_per_giornata(tmp_path, no_pause):
    respx.get(SERIE_A_URL.format(giornata=2)).mock(return_value=httpx.Response(200, text=_page(2)))
    respx.get(SERIE_A_URL.format(giornata=3)).mock(return_value=httpx.Response(200, text=_page(3)))
    store = RawStore(tmp_path / "raw")
    async with httpx.AsyncClient() as http:
        raws = await fetch_serie_a(http, store, season_id=21, giornate=[2, 3])
    assert raws[0].path.name.endswith("-sa-21-02.html") and raws[1].path.name.endswith("-sa-21-03.html")
    rows = load_serie_a([r.path for r in raws], season_id=21)
    assert len(rows) == 6 and {r.giornata for r in rows} == {2, 3}
    with pytest.raises(CalendarShapeError, match="giornata 2 twice"):
        load_serie_a([raws[0].path, raws[0].path], season_id=21)


@respx.mock
async def test_fetch_uefa_pages_by_offset(tmp_path, no_pause):
    def page(request):
        offset = int(request.url.params["offset"])
        assert request.url.params["competitionId"] == "1" and request.url.params["seasonYear"] == "2027"
        return httpx.Response(200, json=[{"id": str(offset + i)} for i in range(200 if offset == 0 else 3)])

    respx.get(UEFA_URL).mock(side_effect=page)
    store = RawStore(tmp_path / "raw")
    async with httpx.AsyncClient() as http:
        raws = await fetch_uefa(http, store, season_id=21, competition="UCL")
    assert raws[0].path.name.endswith("-ucl-21-00.json") and raws[1].path.name.endswith("-ucl-21-01.json")
    assert json.loads(raws[1].path.read_text())["offset"] == 200
    respx.get(UEFA_URL).mock(return_value=httpx.Response(200, json={"error": "x"}))
    async with httpx.AsyncClient() as http:
        with pytest.raises(CalendarShapeError):
            await fetch_uefa(http, store, season_id=21, competition="UEL")


def _seeded(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    (tmp_path / "kb" / "rules").mkdir(parents=True)
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("uefa_teams: {}\nfantacalcio_teams: {}\n")
    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    raw = RawStore(tmp_path / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    con.close()


@respx.mock
def test_cli_ingest_calendar(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, no_pause):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    _seeded(tmp_path, fixture_json, mcp_fixture_json)
    respx.get(url__regex=r"https://www\.fantacalcio\.it/serie-a/calendario/(?P<giornata>\d+)$").mock(
        side_effect=lambda request, giornata: httpx.Response(200, text=_page(int(giornata), renamed=True)))
    uecl = fixture_json("uefa_sample")[1]["matches"]
    respx.get(UEFA_URL).mock(side_effect=lambda request: httpx.Response(
        200, json=uecl if request.url.params["competitionId"] == "2019" else []))

    result = CliRunner().invoke(app, ["ingest", "calendar", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = {r["competition"]: r for r in json.loads(result.stdout)["calendar"]}
    assert set(payload) == {"SA", "UCL", "UEL", "UECL"}
    assert payload["SA"]["inserted"] == 114 and payload["UECL"]["inserted"] == 2 and payload["UCL"]["inserted"] == 0
    assert len(list((tmp_path / "data" / "raw" / "calendar").glob("*-sa-21-*.html"))) == 38

    again = CliRunner().invoke(app, ["ingest", "calendar", "--competition", "uecl", "--competition", "SA"])
    assert again.exit_code == ExitCode.OK, again.output
    assert again.stdout.count("unchanged") == 2 and "UCL" not in again.stdout

    bad = CliRunner().invoke(app, ["ingest", "calendar", "--competition", "NBA"])
    assert bad.exit_code == ExitCode.USAGE and "NBA" in bad.stderr

    respx.get(UEFA_URL).mock(return_value=httpx.Response(500, text="down"))
    failed = CliRunner().invoke(app, ["ingest", "calendar", "--competition", "UCL"])
    assert failed.exit_code == ExitCode.ERROR and "500" in failed.stderr


def test_cli_ingest_calendar_needs_a_synced_league(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["ingest", "calendar"])
    assert result.exit_code == ExitCode.NOT_READY and "sync-league" in result.stderr


@respx.mock
async def test_fetch_calendar_runs_the_requested_competitions(tmp_path, no_pause):
    respx.get(url__regex=r".*/serie-a/calendario/\d+$").mock(side_effect=lambda request: httpx.Response(
        200, text=_page(int(str(request.url).rsplit("/", 1)[1]))))
    respx.get(UEFA_URL).mock(return_value=httpx.Response(200, json=[]))
    async with httpx.AsyncClient() as http:
        raws = await fetch_calendar(http, RawStore(tmp_path / "raw"), 21, ["UEL", "SA"])
    assert list(raws) == ["UEL", "SA"] and len(raws["SA"]) == 38 and len(raws["UEL"]) == 1
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_calendar.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.ingest.calendar`.

- [ ] **Step 4: Write `ingest/calendar.py`**

```python
"""Fixtures: the Serie A calendar and every European midweek tie of an Italian club.

Serie A comes from fantacalcio.it's public calendario pages, one per
giornata, read as schema.org microdata -- observed 2026-08-28: each match is
a SportsEvent carrying homeTeam/awayTeam names spelled as the listone, an
ISO startDate, the kick-off hour in Europe/Rome, the stadium and a match
link .../calendario/<giornata>/<season label>/<slug>/<id>; every match is
rendered twice (large and compact pill) and deduped on the id; only the
current season is served. Europe comes from UEFA's public match API, paged
by offset and filtered to matches with an ITA side: competition ids 1 (UCL),
14 (UEL), 2019 (UECL); seasonYear is the season's ending year.

Scores are not modelled (`results` is Phase 3): a fixture row is the
schedule, and a snapshot is appended only when the schedule changed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes, polite_pause
from fantaclaude.ingest.names import resolve_team
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.league.settings import canonical_json
from fantaclaude.model.seasons import season_id_from_label, uefa_season_year
from fantaclaude.timeutil import to_db

SOURCE_SERIE_A = "fantacalcio.it:/serie-a/calendario/<giornata>"
SOURCE_UEFA = "uefa:GET match.uefa.com/v5/matches"
SERIE_A_URL = "https://www.fantacalcio.it/serie-a/calendario/{giornata}"
UEFA_URL = "https://match.uefa.com/v5/matches"
UEFA_COMPETITIONS = {"UCL": "1", "UEL": "14", "UECL": "2019"}
COMPETITIONS = ("SA", *UEFA_COMPETITIONS)
UEFA_PAGE = 200
ROME = ZoneInfo("Europe/Rome")
VOID_TAGS = frozenset({"meta", "img", "br", "input", "link", "hr", "source"})
UEFA_REQUIRED = ("id", "homeTeam", "awayTeam", "matchday", "round")
_DROP = frozenset({"playerEvents", "referees", "relatedMatches", "translations"})
_HOURS = re.compile(r"(\d{1,2}):(\d{2})")


class CalendarShapeError(ValueError):
    """A page or payload is not the calendar this adapter was written against."""


@dataclass(frozen=True)
class FixtureRow:
    competition: str
    season_id: int
    source_id: str
    round: str                       # "2" for a giornata; "MD3", "MD1 - PO" for UEFA
    giornata: int | None
    phase: str | None                # UEFA: QUALIFYING | TOURNAMENT
    kickoff: datetime | None         # aware UTC; None when unscheduled
    home: str
    away: str
    home_domestic: bool              # a Serie A club, which must resolve to a listone short code
    away_domestic: bool
    raw: dict[str, Any]

    def canonical(self) -> dict[str, Any]:
        return {"competition": self.competition, "season_id": self.season_id, "source_id": self.source_id,
                "round": self.round, "giornata": self.giornata, "phase": self.phase,
                "kickoff": self.kickoff.isoformat() if self.kickoff else None,
                "home": self.home, "away": self.away}


def kickoff_rome(start_date: str | None, hours: str | None) -> datetime | None:
    """An ISO date and an "HH:MM" in Europe/Rome -> aware UTC; None when either is missing."""
    if not start_date:
        return None
    match = _HOURS.fullmatch((hours or "").strip())
    if not match:
        return None
    day = datetime.fromisoformat(start_date)
    return day.replace(hour=int(match.group(1)), minute=int(match.group(2)), tzinfo=ROME).astimezone(UTC)


class _SerieAPageParser(HTMLParser):
    """Collects every schema.org SportsEvent on a calendario page.

    Team names come from the meta[itemprop=name] inside the homeTeam/awayTeam
    labels, so the parser tracks which label it is inside by element depth.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, Any]] = []
        self._event: dict[str, Any] | None = None
        self._depth = 0
        self._side: str | None = None
        self._side_depth = 0
        self._text_target: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=True)

    def _open(self, tag: str, a: dict[str, str | None], *, void: bool) -> None:
        if str(a.get("itemtype") or "").endswith("SportsEvent"):
            self._event = {"status": a.get("data-match-status"), "matchweek": None, "home": None,
                           "away": None, "url": None, "start_date": None, "hours": None,
                           "stadium": None, "name": None}
            self._depth = 0
            self._side = None
        if self._event is None:
            return
        if not void:
            self._depth += 1
        prop = a.get("itemprop")
        classes = str(a.get("class") or "").split()
        if prop in ("homeTeam", "awayTeam") and not void:
            self._side = "home" if prop == "homeTeam" else "away"
            self._side_depth = self._depth
        elif tag == "meta" and prop == "name":
            if self._side:
                self._event[self._side] = a.get("content")
            elif self._event["name"] is None:
                self._event["name"] = a.get("content")
        elif tag == "meta" and prop == "startDate":
            self._event["start_date"] = a.get("content")
        elif tag == "a" and "match-score" in classes:
            self._event["url"] = a.get("href")
        elif tag == "span" and "hours" in classes:
            self._text_target = "hours"
        elif tag == "span" and prop == "location":
            self._text_target = "stadium"
        elif tag == "div" and "matchweek" in classes:
            self._text_target = "matchweek"

    def handle_endtag(self, tag: str) -> None:
        if self._event is None or tag in VOID_TAGS:
            return
        if self._side and self._depth == self._side_depth:
            self._side = None
        self._text_target = None
        self._depth -= 1
        if self._depth == 0:
            self.events.append(self._event)
            self._event = None

    def handle_data(self, data: str) -> None:
        if self._event is not None and self._text_target:
            key = self._text_target
            self._event[key] = ((self._event[key] or "") + data).strip()


def parse_serie_a_page(html_text: str, *, season_id: int) -> list[FixtureRow]:
    parser = _SerieAPageParser()
    parser.feed(html_text)
    if not parser.events:
        raise CalendarShapeError("no SportsEvent on the page -- the calendario layout changed")
    rows: dict[str, FixtureRow] = {}
    for event in parser.events:
        url = event["url"]
        if not url:
            raise CalendarShapeError("a SportsEvent without a match link")
        parts = url.rstrip("/").split("/")
        if len(parts) < 4 or not parts[-1].isdigit() or not parts[-4].isdigit():
            raise CalendarShapeError(f"unexpected match link {url!r}")
        source_id, label, giornata = parts[-1], parts[-3], parts[-4]
        try:
            page_season = season_id_from_label(label)
        except ValueError:
            raise CalendarShapeError(f"unexpected season label in {url!r}") from None
        if page_season != season_id:
            raise CalendarShapeError(
                f"the page is season {label}, not {season_id} -- fantacalcio.it serves the current season only")
        if event["matchweek"] != giornata:
            raise CalendarShapeError(f"matchweek {event['matchweek']!r} disagrees with the link's giornata {giornata}")
        if not event["home"] or not event["away"]:
            raise CalendarShapeError(f"match {source_id}: missing a team name")
        rows[source_id] = FixtureRow(
            competition="SA", season_id=season_id, source_id=source_id, round=giornata,
            giornata=int(giornata), phase=None, kickoff=kickoff_rome(event["start_date"], event["hours"]),
            home=event["home"], away=event["away"], home_domestic=True, away_domestic=True, raw=dict(event))
    return sorted(rows.values(), key=lambda r: (r.kickoff or datetime.max.replace(tzinfo=UTC), r.source_id))


async def fetch_serie_a(http: httpx.AsyncClient, store: RawStore, *, season_id: int,
                        giornate: Any) -> list[RawFile]:
    raws: list[RawFile] = []
    for index, giornata in enumerate(giornate):
        if index:
            await polite_pause()
        data = await fetch_bytes(http, SERIE_A_URL.format(giornata=giornata))
        raws.append(store.write_bytes("calendar", data, ext="html", label=f"sa-{season_id}-{giornata:02d}"))
    return raws


def load_serie_a(paths: list[Path], *, season_id: int) -> list[FixtureRow]:
    rows: list[FixtureRow] = []
    seen: set[int] = set()
    for path in paths:
        page = parse_serie_a_page(path.read_text(encoding="utf-8"), season_id=season_id)
        giornate = {r.giornata for r in page}
        if len(giornate) != 1:
            raise CalendarShapeError(f"{path}: one page must be one giornata, found {sorted(giornate)}")
        giornata = giornate.pop()
        if giornata in seen:
            raise CalendarShapeError(f"{path}: giornata {giornata} twice in one load")
        seen.add(giornata)
        rows.extend(page)
    return rows


async def fetch_uefa(http: httpx.AsyncClient, store: RawStore, *, season_id: int,
                     competition: str) -> list[RawFile]:
    raws: list[RawFile] = []
    offset = 0
    while True:
        if raws:
            await polite_pause()
        data = await fetch_bytes(http, UEFA_URL, params={
            "competitionId": UEFA_COMPETITIONS[competition], "seasonYear": str(uefa_season_year(season_id)),
            "offset": str(offset), "limit": str(UEFA_PAGE)})
        try:
            payload = json.loads(data)
        except ValueError:
            raise CalendarShapeError("UEFA answered something that is not JSON") from None
        if not isinstance(payload, list):
            raise CalendarShapeError("UEFA payload is not a list of matches")
        raws.append(store.write("calendar", {"competition": competition, "season_id": season_id,
                                             "offset": offset, "matches": payload},
                                label=f"{competition.lower()}-{season_id}-{len(raws):02d}"))
        if len(payload) < UEFA_PAGE:
            return raws
        offset += UEFA_PAGE


def _slim(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _slim(v) for k, v in value.items() if k not in _DROP and not str(k).endswith("LogoUrl")}
    if isinstance(value, list):
        return [_slim(v) for v in value]
    return value


def load_uefa(paths: list[Path]) -> list[FixtureRow]:
    """Pages as fetch_uefa writes them; a file may also bundle several pages in a list."""
    rows: dict[str, FixtureRow] = {}
    for path in paths:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        for doc in (loaded if isinstance(loaded, list) else [loaded]):
            if not isinstance(doc, dict) or not isinstance(doc.get("matches"), list) \
                    or doc.get("competition") not in UEFA_COMPETITIONS or not isinstance(doc.get("season_id"), int):
                raise CalendarShapeError(f"{path}: not a UEFA page written by fetch_uefa")
            rows.update(_uefa_rows(doc, path))
    return sorted(rows.values(), key=lambda r: (r.kickoff or datetime.max.replace(tzinfo=UTC), r.source_id))


def _uefa_rows(doc: dict[str, Any], path: Path) -> dict[str, FixtureRow]:
    rows: dict[str, FixtureRow] = {}
    for match in doc["matches"]:
        missing = [k for k in UEFA_REQUIRED if k not in match]
        if missing:
            raise CalendarShapeError(f"{path}: match {match.get('id')} lacks {missing}")
        home, away = match["homeTeam"], match["awayTeam"]
        domestic = (home.get("countryCode") == "ITA", away.get("countryCode") == "ITA")
        if not any(domestic):
            continue
        when = (match.get("kickOffTime") or {}).get("dateTime")
        kickoff = datetime.fromisoformat(when).astimezone(UTC) if when else None
        rows[str(match["id"])] = FixtureRow(
            competition=doc["competition"], season_id=doc["season_id"], source_id=str(match["id"]),
            round=str(match["matchday"].get("name") or ""), giornata=None,
            phase=match["round"].get("phase"), kickoff=kickoff,
            home=str(home.get("internationalName") or ""), away=str(away.get("internationalName") or ""),
            home_domestic=domestic[0], away_domestic=domestic[1], raw=_slim(match))
    return rows


def schedule_hash(rows: list[FixtureRow]) -> str:
    payload = canonical_json(sorted((r.canonical() for r in rows), key=lambda c: c["source_id"]))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FixtureIngestResult:
    snapshot_id: int | None
    competition: str
    season_id: int
    inserted: int
    skipped_unchanged: bool
    sha256: str
    raw_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "competition": self.competition, "season_id": self.season_id,
                "inserted": self.inserted, "skipped_unchanged": self.skipped_unchanged,
                "sha256": self.sha256, "raw_paths": self.raw_paths}


def record_fixtures(con: duckdb.DuckDBPyConnection, competition: str, season_id: int,
                    rows: list[FixtureRow], raws: list[RawFile], *, teams: dict[str, str],
                    team_aliases: dict[str, str]) -> FixtureIngestResult:
    """Append a snapshot when the schedule differs from the latest one.

    A Serie A club the listone cannot resolve is an error, not a flag: it is
    a spelling drift (alias it) or a listone that needs re-ingesting, and
    either way every row for that club would silently fall out of
    v_european_ties.
    """
    digest = schedule_hash(rows)
    latest = con.execute(
        "SELECT snapshot_id, sha256 FROM fixture_snapshots WHERE competition = ? AND season_id = ? "
        "ORDER BY snapshot_id DESC LIMIT 1", [competition, season_id]).fetchone()
    paths = [str(r.path) for r in raws]
    if latest is not None and latest[1] == digest:
        return FixtureIngestResult(latest[0], competition, season_id, 0, True, digest, paths)
    section = "fantacalcio_teams" if competition == "SA" else "uefa_teams"
    records: list[list[Any]] = []
    for row in rows:
        shorts: list[str | None] = []
        for name, domestic in ((row.home, row.home_domestic), (row.away, row.away_domestic)):
            short = resolve_team(name, teams, team_aliases) if domestic else None
            if domestic and short is None:
                raise CalendarShapeError(
                    f"{competition} {season_id}: club {name!r} is not in the listone -- if it is a spelling, "
                    f"add `{section}: {{{name}: <listone name>}}` to kb/rules/aliases.yml")
            shorts.append(short)
        records.append([None, competition, season_id, row.source_id, row.round, row.giornata, row.phase,
                        to_db(row.kickoff) if row.kickoff else None, row.home, row.away, shorts[0], shorts[1],
                        json.dumps(row.raw, ensure_ascii=False)])
    fetched_at = max(r.fetched_at for r in raws)
    source = SOURCE_SERIE_A if competition == "SA" else SOURCE_UEFA
    con.begin()
    try:
        snapshot_id = con.execute(
            "INSERT INTO fixture_snapshots (competition, season_id, fetched_at, source, raw_paths, sha256, row_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING snapshot_id",
            [competition, season_id, to_db(fetched_at), source, paths, digest, len(rows)]).fetchone()[0]
        for record in records:
            record[0] = snapshot_id
        if records:
            con.executemany("INSERT INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)", records)
    except Exception:
        con.rollback()
        raise
    con.commit()
    return FixtureIngestResult(snapshot_id, competition, season_id, len(rows), False, digest, paths)
```

- [ ] **Step 5: Extend `commands/ingest.py`**

Add to its import block (ruff will place them): `from fantaclaude.ingest.calendar import (FixtureIngestResult, fetch_serie_a, fetch_uefa, load_serie_a, load_uefa, record_fixtures)` and `from fantaclaude.model.seasons import SERIE_A_GIORNATE, back_seasons` (replacing the existing `back_seasons` import). Append:

```python
async def fetch_calendar(http: httpx.AsyncClient, store: RawStore, season_id: int,
                         competitions: list[str]) -> dict[str, list[RawFile]]:
    """Every requested competition, in the order given, one host at a time."""
    raws: dict[str, list[RawFile]] = {}
    for index, competition in enumerate(competitions):
        if index:
            await polite_pause()
        if competition == "SA":
            raws[competition] = await fetch_serie_a(http, store, season_id=season_id,
                                                    giornate=range(1, SERIE_A_GIORNATE + 1))
        else:
            raws[competition] = await fetch_uefa(http, store, season_id=season_id, competition=competition)
    return raws


def record_calendar(con: duckdb.DuckDBPyConnection, season_id: int, raws: dict[str, list[RawFile]],
                    aliases_path: Path) -> list[FixtureIngestResult]:
    aliases = load_aliases(aliases_path)
    teams = load_teams(con)
    results = []
    for competition, files in raws.items():
        paths = [f.path for f in files]
        if competition == "SA":
            rows, team_aliases = load_serie_a(paths, season_id=season_id), aliases.teams_for("fantacalcio")
        else:
            rows, team_aliases = load_uefa(paths), aliases.teams_for("uefa")
        results.append(record_fixtures(con, competition, season_id, rows, files,
                                       teams=teams, team_aliases=team_aliases))
    return results
```

- [ ] **Step 6: Add the CLI command**

In `core/src/fantaclaude/cli/app.py`: extend `_source_errors` so a shape error is an error too — add a third clause after the `SourceError` one:

```python
    except ValueError as exc:                      # *ShapeError: the source changed under us
        typer.echo(f"source shape unexpected: {exc}", err=True)
        raise typer.Exit(code=ExitCode.ERROR) from None
```

and move `ingest_advanced_cmd`'s `con = connect()` … `emit(...)` block *inside* its `with _source_errors():` so record-time shape errors get the same treatment. Then add, after `SEASON_OPTION`:

```python
COMPETITION_OPTION = typer.Option(
    None, "--competition", help="SA, UCL, UEL or UECL; repeatable. Default: all four.")
```

and after `ingest_advanced_cmd`:

```python
def _render_calendar(payload: dict) -> str:
    lines = []
    for r in payload["calendar"]:
        if r["skipped_unchanged"]:
            lines.append(f"calendar {r['competition']} {r['season_id']}: unchanged (snapshot {r['snapshot_id']})")
        else:
            lines.append(f"calendar {r['competition']} {r['season_id']}: snapshot {r['snapshot_id']}, "
                         f"{r['inserted']} fixtures ({len(r['raw_paths'])} raw files)")
    return "\n".join(lines)


@ingest_app.command("calendar")
def ingest_calendar_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    competition: list[str] | None = COMPETITION_OPTION,
) -> None:
    """The current season's Serie A calendar (fantacalcio.it) and every UEFA tie of an Italian club."""
    from fantaclaude.commands.ingest import fetch_calendar, record_calendar
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.calendar import COMPETITIONS
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    competitions = [c.upper() for c in competition] if competition else list(COMPETITIONS)
    unknown = [c for c in competitions if c not in COMPETITIONS]
    if unknown:
        typer.echo(f"unknown competition {unknown}; choose from {', '.join(COMPETITIONS)}", err=True)
        raise typer.Exit(code=ExitCode.USAGE)
    season_id = _seasons_or_exit(None)[-1]           # the season the league is in
    store = RawStore(raw_dir())
    with _source_errors():
        raws = run_web(lambda http: fetch_calendar(http, store, season_id, competitions))
        con = connect()
        try:
            apply_schema(con)
            results = record_calendar(con, season_id, raws, aliases_path())
        finally:
            con.close()
    emit({"calendar": [r.to_dict() for r in results]}, json_=json_, render=_render_calendar)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run ruff check --fix core -q; uv run pytest core/tests/test_calendar.py core/tests/test_fixtures.py -q`
Expected: 14 passed.

- [ ] **Step 8: Run the whole suite and lint, then commit**

Run: `uv run poe test-core && uv run ruff check core`
Expected: 145 passed; ruff clean.

```bash
git add core/src/fantaclaude/ingest/calendar.py core/src/fantaclaude/commands/ingest.py core/src/fantaclaude/cli/app.py core/tests/fixtures/_extract_calendar.py core/tests/fixtures/calendario_sample.html core/tests/fixtures/uefa_sample.json core/tests/test_calendar.py core/tests/test_fixtures.py
git commit -m "feat(ingest): calendar -- Serie A giornate and the European ties of Italian clubs"
```

---

### Task 6: Website-session discovery and the first voti capture (needs the account holder)

**Files:**
- Create: `core/scripts/probe_web_session.py`
- Modify: `docs/superpowers/specs/2026-08-22-fantaclaude-design.md` (open question 5, the `stats_web` row of the adapter table), `.env` (by hand, never committed)
- Produces in gitignored `captured/`: `voti-21-01.xlsx` and whichever of `voti-20-01.xlsx`, `voti-18-01.xlsx` the site serves

**Interfaces:**
- Consumes: `fantaclaude.config.web_cookie`, `fantaclaude.ingest.http.{build_http, fetch_bytes, polite_pause, WebSessionExpired, NotPublished, SourceError}`, `fantaclaude.paths.{db_path, workspace_root}`, `openpyxl`.
- Produces: the observations Task 7 is written against — the session mechanism, which seasons are served, what an unplayed giornata answers, and the workbook layout (sheet names, header row, team-row shape, the senza-voto spelling). **Task 7's `VOTI_HEADER`, `COLUMNS` and `parse_voto` are reconciled with them in the working tree before Task 7 starts** (CLAUDE.md: a plan defect found during implementation is fixed in the working tree and rides with that task's commit).

This task is the only one that cannot run unattended: the website login is the account holder's to do, in their own browser, and the cookie is theirs to paste. Nothing here logs in programmatically — there is no login code to write, so nothing can lock the account. If the account holder is not available, execute Tasks 8 and 9 first (neither needs the voti) and return to Tasks 6–7.

- [ ] **Step 1: Capture the session and the first workbook (account holder, own browser)**

1. Log in at `https://www.fantacalcio.it/login` (the *website*, not Leghe).
2. Open `https://www.fantacalcio.it/voti-fantacalcio-serie-a/2026-27/1`, open the browser's developer tools on the **Network** tab, then click the page's Excel download (it links `/api/v1/Excel/votes/21/1`). Save the downloaded file as `captured/voti-21-01.xlsx`.
3. In the Network tab, select that request and copy the value of its `Cookie` **request** header — the whole string, `name1=value1; name2=value2; …`.
4. Add one line to `.env`, quoted because the value carries `;` and spaces: `FANTACALCIO_WEB_COOKIE="<pasted value>"`. `.env` is gitignored and `load_dotenv` strips the quotes.
5. Note, for the spec, the *names* of the cookies (never the values) and their expiry as the browser shows them (Application → Cookies → `www.fantacalcio.it`). The lifetime decides how often step 3 has to be repeated.

- [ ] **Step 2: Write the probe**

Create `core/scripts/probe_web_session.py`:

```python
"""One-shot discovery of the fantacalcio.it website session and the voti workbook.

Run from the workspace root, once, with FANTACALCIO_WEB_COOKIE in .env:

    uv run python core/scripts/probe_web_session.py

Four GETs against www.fantacalcio.it -- the current season's giornata 1, two
back seasons' giornata 1, and a giornata not played yet -- one second apart,
then a read-only look at whatever came back: status and size per URL, sheet
names, the first rows of every sheet, and the share of player codes the
current listone knows. It never prints the cookie. Not a test and not an
adapter: ingest/stats_web.py is written against what this prints, and the
spec's open question 5 records it.
"""

from __future__ import annotations

import asyncio
import sys

import duckdb
import openpyxl

from fantaclaude.config import web_cookie
from fantaclaude.ingest.http import (
    NotPublished,
    SourceError,
    WebSessionExpired,
    build_http,
    fetch_bytes,
    polite_pause,
)
from fantaclaude.paths import db_path, workspace_root

VOTES = "https://www.fantacalcio.it/api/v1/Excel/votes/{season}/{giornata}"
PROBES = [(21, 1), (20, 1), (18, 1), (21, 38)]      # season ids: 21 is 2026-27 (model/seasons.py)
XLSX_MAGIC = b"PK\x03\x04"


async def main() -> int:
    cookie = web_cookie()
    if cookie is None:
        print("FANTACALCIO_WEB_COOKIE is not set in .env -- capture it first (plan, Task 6, Step 1)")
        return 3
    captured = workspace_root() / "captured"
    captured.mkdir(exist_ok=True)
    saved = []
    async with build_http() as http:
        for index, (season, giornata) in enumerate(PROBES):
            if index:
                await polite_pause()
            url = VOTES.format(season=season, giornata=giornata)
            try:
                data = await fetch_bytes(http, url, headers={"Cookie": cookie})
            except WebSessionExpired as exc:
                print(f"{url}: session rejected (HTTP {exc.status}) -- the cookie does not authenticate; re-capture it")
                return 3
            except NotPublished:
                print(f"{url}: HTTP 404 -- not published")
                continue
            except SourceError as exc:
                print(f"{url}: {exc}")
                continue
            head = data[:2000].lower()
            kind = "xlsx" if data[:4] == XLSX_MAGIC else ("html" if b"<html" in head else "unknown")
            print(f"{url}: HTTP 200, {len(data)} bytes, {kind}")
            if kind == "xlsx":
                path = captured / f"voti-{season}-{giornata:02d}.xlsx"
                path.write_bytes(data)
                saved.append(path)
    known: set[int] = set()
    if db_path().is_file():
        con = duckdb.connect(str(db_path()), read_only=True)
        known = {int(r[0]) for r in con.execute("SELECT player_id FROM v_players_current").fetchall()}
        con.close()
    for path in saved:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        print(f"\n== {path.name}: sheets {workbook.sheetnames}")
        for sheet in workbook.worksheets:
            print(f"-- {sheet.title}")
            codes: list[int] = []
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                if index < 8:
                    print("  ", [cell for cell in row if cell is not None])
                if row and isinstance(row[0], (int, float)) and not isinstance(row[0], bool):
                    codes.append(int(row[0]))
            if codes:
                share = (sum(code in known for code in codes) / len(codes)) if known else 0.0
                print(f"   {len(codes)} player rows; {share:.0%} of the codes are in the current listone")
        workbook.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 3: Run the probe once**

Run: `uv run python core/scripts/probe_web_session.py`
Expected: `HTTP 200 … xlsx` for `votes/21/1`; a `200 xlsx` or a `401/404` for `20/1` and `18/1` (this decides whether back seasons are served); a `404` or a `200` with an empty table for `21/38`; then, per saved workbook, the sheet names and the first eight rows of every sheet, and a share of known codes near 100% for the current season. **Do not re-run it to "check"** — if the session is rejected, fix the cookie and run it once more; that is the only expected second run.

- [ ] **Step 4: Record the observations in the spec and reconcile Task 7**

In `docs/superpowers/specs/2026-08-22-fantaclaude-design.md`:

- Open question 5: strike the title (`**~~Are per-giornata voti available as XLSX?~~ Resolved <date>.**`) and replace the paragraph from "What remains is a check only the account holder can run" to the end of the item with a paragraph stating, in this order: the session mechanism (the cookie *names* and their lifetime, kept in `.env` as `FANTACALCIO_WEB_COOKIE`, captured from a browser, never obtained by code); which seasons answered `200` (and so whether the three back seasons are served); what an unplayed giornata answers; the workbook layout — sheet names and their order, the header row and its row number, how a team block starts, how a senza-voto is spelled; and the share of `Cod.` values found in the current listone (the identity join `stats_web` relies on). Add one sentence recording the 2026-08-28 observation that the voti *HTML* page is public and carries the same data with player ids and the `55` senza-voto sentinel — the spec's "premium HTML" premise was wrong, and it is the fallback should the workbook ever go away.
- Adapter table: change the `stats_web` row's source cell to `fantacalcio.it voti XLSX, /api/v1/Excel/votes/<season>/<giornata>, sent the **website** cookie from .env` and its status cell to `Phase 0b`.

Then reconcile Task 7 in this plan file (working tree, uncommitted): if the observed header differs from `VOTI_HEADER`, edit `VOTI_HEADER` and `COLUMNS` in Task 7's code and the extractor's expectations; if a senza-voto is spelled other than `6*`, `s.v.` or `55`, extend `parse_voto`; if a team block is not "a row with only the first cell filled", edit `_iter_rows`. Everything else in Task 7 is layout-independent.

- [ ] **Step 5: Verify nothing secret is staged, then commit**

Run: `git status --short && git diff --cached --stat`
Expected: only `core/scripts/probe_web_session.py` and the spec are staged; `.env` and `captured/` do not appear (gitignored). Run `uv run ruff check core` — clean.

```bash
git add core/scripts/probe_web_session.py docs/superpowers/specs/2026-08-22-fantaclaude-design.md
git commit -m "docs(spec): record the fantacalcio.it website session and the voti workbook layout"
```

---

### Task 7: The `stats_web` adapter — per-giornata voti and event counts from the XLSX export

**Files:**
- Create: `core/src/fantaclaude/ingest/stats_web.py`, `core/tests/fixtures/_extract_voti.py`, `core/tests/fixtures/voti_sample.xlsx`, `core/tests/test_stats_web.py`
- Modify: `core/src/fantaclaude/commands/ingest.py`, `core/src/fantaclaude/cli/app.py`, `core/tests/test_fixtures.py`, `core/tests/conftest.py`

**Interfaces:**
- Consumes: Task 6's observations (reconciled into `VOTI_HEADER`, `COLUMNS`, `parse_voto` and `_parse_sheet` before this task starts), `RawStore.write_bytes`, `fetch_bytes`, `polite_pause`, `run_web`, `web_cookie`, `SERIE_A_GIORNATE`, `to_db`, the schema's `voti_files`/`player_match` and the views over them, `SEASON_OPTION`, `_seasons_or_exit`, `_source_errors`.
- Produces: `fantaclaude.ingest.stats_web.{SOURCE, VOTES_URL, VOTI_HEADER, COLUMNS, VotiShapeError, VotoRow, VotiWorkbook(sheets).rows, parse_voto(value) -> tuple[Decimal | None, bool], parse_voti(path) -> VotiWorkbook, async fetch_voti(http, store, *, cookie, season_id, giornata) -> RawFile, VotiFetch(raws, skipped, not_published_from), async fetch_voti_range(http, store, *, cookie, season_id, giornate, existing, refetch=False) -> VotiFetch, VotiIngestResult(...).to_dict(), record_voti(con, season_id, giornata, workbook, raw, *, known_ids) -> VotiIngestResult}`; `fantaclaude.commands.ingest.{existing_giornate(path, seasons) -> dict[int, set[int]], async fetch_voti_seasons(http, store, *, cookie, seasons, giornate, existing, refetch) -> dict[int, VotiFetch], record_voti_files(con, fetched) -> list[VotiIngestResult]}`; CLI `fantaclaude ingest stats-web [--season N]... [--giornata N]... [--refetch] [--json]`; `cli.app.GIORNATA_OPTION`; conftest fixture `fixture_file(name) -> Path` (any extension).

The identity join is the file's `Cod.` column — the fantacalcio.it player id, the listone's `id` (Task 6 measured the share). Nothing here is matched by name. Only the base voto and the event counts are stored; the fantavoto is computed at projection time under the league's own bonus/malus and never stored (spec, "Fantavoto is computed, never stored"). Every sheet of the workbook is a voto source and is kept under its sheet name; which one this league scores with is a `league_settings` question for Phase 1 (`calculate.sourcev` is the candidate key, observed `1`).

- [ ] **Step 1: Build the workbook fixture from the capture**

Create `core/tests/fixtures/_extract_voti.py`:

```python
"""One-shot: build voti_sample.xlsx from captured/voti-21-01.xlsx (giornata 1, 2026-27).

Run from the workspace root:  uv run python core/tests/fixtures/_extract_voti.py

Every sheet is kept, with everything above and including its header row and
then only the Atalanta and Bologna blocks (a team row followed by its player
rows), so the layout the parser locks -- title rows, header, team rows,
senza-voto cells -- is exactly the site's. The reference values the tests
assert (Carnesecchi 6,5 with a goal conceded and an assist, Elmas senza
voto, Raspadori and Krstovic 7 with a goal, Scalvini 6 / 5,5 / 6 across the
sources) were read off the public voti page on 2026-08-28. Values only: no
styles, no formulas. Public voti, nothing to scrub.
"""

from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "voti-21-01.xlsx"
OUT = Path(__file__).with_name("voti_sample.xlsx")
TEAMS = {"atalanta", "bologna"}
HEADER_FIRST = "Cod."


def main() -> None:
    source = openpyxl.load_workbook(CAPTURE, read_only=True, data_only=True)
    out = openpyxl.Workbook()
    out.remove(out.active)
    kept = 0
    for sheet in source.worksheets:
        target = out.create_sheet(sheet.title)
        header_seen = False
        keep_block = False
        for row in sheet.iter_rows(values_only=True):
            cells = list(row)
            if not header_seen:
                target.append(cells)
                header_seen = str(cells[0]).strip() == HEADER_FIRST if cells else False
                continue
            first, rest = cells[0] if cells else None, cells[1:] if cells else []
            blank_rest = all(c is None or (isinstance(c, str) and not c.strip()) for c in rest)
            if isinstance(first, str) and first.strip() and blank_rest:      # a team row
                keep_block = first.strip().lower() in TEAMS
            if keep_block and not (first is None and blank_rest):
                target.append(cells)
                kept += 1
        if not header_seen:
            out.remove(target)
    out.save(OUT)
    print(f"wrote {len(out.sheetnames)} sheet(s) {out.sheetnames}, {kept} rows, {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
```

Run: `uv run python core/tests/fixtures/_extract_voti.py`
Expected: `wrote N sheet(s) [...], M rows, <under 30000> bytes` with every sheet Task 6 listed.

- [ ] **Step 2: Write the failing tests**

Append to `core/tests/conftest.py`:

```python
@pytest.fixture
def fixture_file():
    def _path(name: str) -> Path:
        return FIXTURE_DIR / name
    return _path
```

In `core/tests/test_fixtures.py`, add `"voti_sample.xlsx"` to the names in `test_expected_fixtures_exist`.

Create `core/tests/test_stats_web.py`:

```python
import json
from decimal import Decimal

import httpx
import openpyxl
import pytest
import respx
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import existing_giornate
from fantaclaude.ingest.http import NotPublished, WebSessionExpired
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from fantaclaude.ingest.stats_web import (
    VOTES_URL,
    VOTI_HEADER,
    VotiShapeError,
    fetch_voti,
    fetch_voti_range,
    parse_voti,
    parse_voto,
    record_voti,
)
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from typer.testing import CliRunner

COOKIE = "session=synthetic-value-for-tests; other=1"


@pytest.fixture
def no_pause(monkeypatch):
    async def fake(seconds=None):
        pass

    monkeypatch.setattr("fantaclaude.ingest.stats_web.polite_pause", fake)
    monkeypatch.setattr("fantaclaude.commands.ingest.polite_pause", fake)


@pytest.fixture
def sample_bytes(fixture_file):
    return fixture_file("voti_sample.xlsx").read_bytes()


def test_parse_voto_conventions():
    assert parse_voto(6.5) == (Decimal("6.5"), False)
    assert parse_voto(7) == (Decimal("7"), False)
    assert parse_voto("6,5") == (Decimal("6.5"), False)
    assert parse_voto("6*") == (None, True)                 # voto d'ufficio: played, not rated
    assert parse_voto("s.v.") == (None, True) and parse_voto("S.V.") == (None, True)
    assert parse_voto(55) == (None, True) and parse_voto("55") == (None, True)   # fantacalcio.it's sentinel
    assert parse_voto(None) == (None, True) and parse_voto("  ") == (None, True)
    with pytest.raises(VotiShapeError):
        parse_voto("sette")


def test_parse_voti_reads_every_sheet_and_the_reference_players(fixture_file):
    workbook = parse_voti(fixture_file("voti_sample.xlsx"))
    assert workbook.sheets and all(rows for rows in workbook.sheets.values())
    scalvini_votes = set()
    for sheet, rows in workbook.sheets.items():
        by = {r.player_id: r for r in rows}
        assert {r.team.lower() for r in rows} == {"atalanta", "bologna"}
        assert all(r.sheet == sheet for r in rows)
        carnesecchi = by[4431]
        assert carnesecchi.name.lower().startswith("carnesecchi") and carnesecchi.classic_role.upper() == "P"
        assert (carnesecchi.voto, carnesecchi.senza_voto) == (Decimal("6.5"), False)
        assert (carnesecchi.goals_conceded, carnesecchi.assists, carnesecchi.goals) == (1, 1, 0)
        assert (by[4479].voto, by[4479].senza_voto) == (None, True)              # Elmas
        assert by[4371].voto == Decimal("7") and by[4371].goals == 1              # Raspadori
        assert by[6435].voto == Decimal("7") and by[6435].goals == 1              # Krstovic
        assert by[2640].voto == Decimal("6") and by[2640].classic_role.upper() == "D"   # Kolasinac
        assert set(by[4431].raw) == set(VOTI_HEADER)                              # the source row, as read
        scalvini_votes.add(by[5526].voto)
    assert scalvini_votes == {Decimal("6"), Decimal("5.5")}
    assert len(workbook.rows) == sum(len(rows) for rows in workbook.sheets.values())


def test_parse_voti_fails_loud_on_layout_drift(tmp_path, fixture_file):
    wb = openpyxl.load_workbook(fixture_file("voti_sample.xlsx"))
    sheet = wb.worksheets[0]
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value == "Gf":
                cell.value = "Goal"
    renamed = tmp_path / "renamed.xlsx"
    wb.save(renamed)
    with pytest.raises(VotiShapeError, match="Goal"):
        parse_voti(renamed)
    empty = openpyxl.Workbook()
    empty.active.append(["not", "a", "voti", "table"])
    path = tmp_path / "empty.xlsx"
    empty.save(path)
    with pytest.raises(VotiShapeError, match="no sheet"):
        parse_voti(path)


def _known(db, tmp_path, fixture_json) -> set[int]:
    raw = RawStore(tmp_path / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(db, load_listone(raw.path), raw)
    return {r[0] for r in db.execute("SELECT player_id FROM v_players_current").fetchall()}


def test_record_voti_and_the_views(db, tmp_path, fixture_json, sample_bytes, fixture_file):
    known = _known(db, tmp_path, fixture_json)
    store = RawStore(tmp_path / "raw")
    raw = store.write_bytes("voti", sample_bytes, ext="xlsx", label="21-01")
    workbook = parse_voti(raw.path)
    result = record_voti(db, 21, 1, workbook, raw, known_ids=known)
    assert result.file_id == 1 and result.inserted == len(workbook.rows) and not result.skipped_duplicate
    assert result.sheets == list(workbook.sheets)
    assert result.unknown_players == len({r.player_id for r in workbook.rows} - known) > 0
    assert db.execute("SELECT count(*) FROM v_player_match_current").fetchone()[0] == len(workbook.rows)
    season = db.execute("SELECT sheet, presenze, appearances, media_voto, goals FROM v_player_season "
                        "WHERE player_id = 2640 ORDER BY sheet").fetchall()
    assert len(season) == len(workbook.sheets) and all(row[1:] == (1, 1, Decimal("6.00"), 0) for row in season)
    form = db.execute("SELECT n, media_voto, last_giornata FROM v_player_form WHERE player_id = 2640").fetchall()
    assert form and form[0] == (1, Decimal("6.00"), 1)
    assert db.execute("SELECT senza_voto, voto FROM v_player_match_current WHERE player_id = 4479 LIMIT 1").fetchone() == (True, None)

    again = record_voti(db, 21, 1, workbook, raw, known_ids=known)
    assert again.skipped_duplicate and again.file_id == 1 and again.inserted == 0

    wb = openpyxl.load_workbook(fixture_file("voti_sample.xlsx"))
    wb.worksheets[0]["A1"] = "revised"
    revised = tmp_path / "revised.xlsx"
    wb.save(revised)
    raw2 = store.write_bytes("voti", revised.read_bytes(), ext="xlsx", label="21-01")
    second = record_voti(db, 21, 1, parse_voti(raw2.path), raw2, known_ids=known)
    assert second.file_id == 2
    assert db.execute("SELECT file_id FROM v_voti_files_current").fetchall() == [(2,)]
    assert db.execute("SELECT count(*) FROM player_match").fetchone()[0] == 2 * len(workbook.rows)   # history kept
    assert db.execute("SELECT count(*) FROM v_player_match_current").fetchone()[0] == len(workbook.rows)


@respx.mock
async def test_fetch_voti_sends_the_cookie_and_wants_a_workbook(tmp_path, sample_bytes):
    url = VOTES_URL.format(season_id=21, giornata=1)
    route = respx.get(url).mock(return_value=httpx.Response(200, content=sample_bytes))
    async with httpx.AsyncClient() as http:
        raw = await fetch_voti(http, RawStore(tmp_path / "raw"), cookie=COOKIE, season_id=21, giornata=1)
    assert raw.path.name.endswith("-voti-21-01.xlsx") and raw.path.read_bytes() == sample_bytes
    assert route.calls[0].request.headers["cookie"] == COOKIE
    respx.get(url).mock(return_value=httpx.Response(200, text="<html><body>Accedi</body></html>"))
    async with httpx.AsyncClient() as http:
        with pytest.raises(WebSessionExpired):
            await fetch_voti(http, RawStore(tmp_path / "raw"), cookie=COOKIE, season_id=21, giornata=1)
    respx.get(url).mock(return_value=httpx.Response(200, content=b"garbage"))
    async with httpx.AsyncClient() as http:
        with pytest.raises(VotiShapeError):
            await fetch_voti(http, RawStore(tmp_path / "raw"), cookie=COOKIE, season_id=21, giornata=1)
    respx.get(url).mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http:
        with pytest.raises(NotPublished):
            await fetch_voti(http, RawStore(tmp_path / "raw"), cookie=COOKIE, season_id=21, giornata=1)


@respx.mock
async def test_fetch_voti_range_skips_existing_and_stops_at_the_first_404(tmp_path, sample_bytes, monkeypatch):
    pauses = []

    async def count(seconds=None):
        pauses.append(seconds)

    monkeypatch.setattr("fantaclaude.ingest.stats_web.polite_pause", count)
    respx.get(url__regex=r".*/votes/21/(?P<g>\d+)$").mock(side_effect=lambda request, g: httpx.Response(
        200 if int(g) <= 2 else 404, content=sample_bytes if int(g) <= 2 else b""))
    store = RawStore(tmp_path / "raw")
    async with httpx.AsyncClient() as http:
        fetched = await fetch_voti_range(http, store, cookie=COOKIE, season_id=21, giornate=range(1, 39),
                                         existing={2}, refetch=False)
    assert sorted(fetched.raws) == [1] and fetched.skipped == [2] and fetched.not_published_from == 3
    assert len(pauses) == 1                                   # giornata 1, pause, giornata 3 (404)
    async with httpx.AsyncClient() as http:
        again = await fetch_voti_range(http, store, cookie=COOKIE, season_id=21, giornate=[1, 2],
                                       existing={1, 2}, refetch=True)
    assert sorted(again.raws) == [1, 2] and again.skipped == [] and again.not_published_from is None


def _seeded(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    raw = RawStore(tmp_path / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    con.close()


@respx.mock
def test_cli_ingest_stats_web(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, sample_bytes, no_pause):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.setenv("FANTACALCIO_WEB_COOKIE", COOKIE)
    _seeded(tmp_path, fixture_json, mcp_fixture_json)
    route = respx.get(url__regex=r".*/votes/(?P<s>\d+)/(?P<g>\d+)$").mock(side_effect=lambda request, s, g: httpx.Response(
        200 if int(g) <= 2 else 404, content=sample_bytes if int(g) <= 2 else b""))

    result = CliRunner().invoke(app, ["ingest", "stats-web", "--season", "21", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)["stats_web"]
    assert [(f["season_id"], f["giornata"], f["skipped_duplicate"]) for f in payload["files"]] == [(21, 1, False), (21, 2, False)]
    assert payload["skipped"] == {"21": []} and payload["not_published_from"] == {"21": 3}
    assert len(list((tmp_path / "data" / "raw" / "voti").glob("*-voti-21-*.xlsx"))) == 2
    assert existing_giornate(tmp_path / "data" / "fanta.duckdb", [21]) == {21: {1, 2}}

    again = CliRunner().invoke(app, ["ingest", "stats-web", "--season", "21"])
    assert again.exit_code == ExitCode.OK and "skipped 1-2" in again.stdout and "not published from 3" in again.stdout

    refetch = CliRunner().invoke(app, ["ingest", "stats-web", "--season", "21", "--giornata", "1", "--refetch", "--json"])
    assert refetch.exit_code == ExitCode.OK
    assert json.loads(refetch.stdout)["stats_web"]["files"][0]["skipped_duplicate"] is True

    bad = CliRunner().invoke(app, ["ingest", "stats-web", "--giornata", "40"])
    assert bad.exit_code == ExitCode.USAGE and "40" in bad.stderr

    route.mock(return_value=httpx.Response(401))                    # the same route: respx answers the first match
    expired = CliRunner().invoke(app, ["ingest", "stats-web", "--season", "20"])
    assert expired.exit_code == ExitCode.NOT_READY and "re-capture" in expired.stderr
    assert COOKIE not in expired.stderr and COOKIE not in expired.stdout

    monkeypatch.delenv("FANTACALCIO_WEB_COOKIE")
    missing = CliRunner().invoke(app, ["ingest", "stats-web"])
    assert missing.exit_code == ExitCode.NOT_READY and "FANTACALCIO_WEB_COOKIE" in missing.stderr
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_stats_web.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.ingest.stats_web`.

- [ ] **Step 4: Write `ingest/stats_web.py`**

```python
"""Per-giornata voti and event counts from fantacalcio.it's XLSX export.

GET /api/v1/Excel/votes/<season_id>/<giornata>, sent the *website* cookie
from .env (captured by the account holder, never obtained by code). One
workbook per giornata; every sheet is one voto source (Redazione
Fantacalcio, Statistico, Italia) and is kept under its sheet name; rows are
grouped by club, each block opened by a row that carries only the club
name; a senza-voto is "6*" / "s.v." / the sentinel 55. `Cod.` is the
fantacalcio.it player id -- the listone's `id` -- so nothing here is
matched by name. The layout constants below are what Task 6 of the
Phase 0b plan observed; a header that differs is a red ingest, never a
silently-null column. Base voto and event counts only: the fantavoto is
computed at projection time under the league's own bonus/malus.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb
import httpx
import openpyxl

from fantaclaude.ingest.http import NotPublished, WebSessionExpired, fetch_bytes, polite_pause
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.timeutil import to_db

SOURCE = "fantacalcio.it:/api/v1/Excel/votes"
VOTES_URL = "https://www.fantacalcio.it/api/v1/Excel/votes/{season_id}/{giornata}"
XLSX_MAGIC = b"PK\x03\x04"
ACCEPT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, */*"
# The header row of every sheet, as observed in Task 6 -- fail loud on anything else.
VOTI_HEADER = ("Cod.", "Ruolo", "Nome", "Voto", "Gf", "Gs", "Rp", "Rs", "Rf", "Au", "Amm", "Esp", "Ass")
COLUMNS = {"Gf": "goals", "Gs": "goals_conceded", "Rp": "pen_saved", "Rs": "pen_missed", "Rf": "pen_scored",
           "Au": "own_goals", "Amm": "yellow", "Esp": "red", "Ass": "assists"}
SENZA_VOTO_TEXT = frozenset({"s.v.", "s.v", "sv", "-", ""})
SENZA_VOTO_SENTINEL = Decimal(55)          # the voti page's data-value for a player without a voto
HEADER_SEARCH_ROWS = 20


class VotiShapeError(ValueError):
    """The workbook is not the voti export this adapter was written against."""


@dataclass(frozen=True)
class VotoRow:
    sheet: str
    player_id: int
    name: str
    team: str
    classic_role: str
    voto: Decimal | None
    senza_voto: bool
    goals: int
    goals_conceded: int
    pen_saved: int
    pen_missed: int
    pen_scored: int
    own_goals: int
    yellow: int
    red: int
    assists: int
    raw: dict[str, Any]


@dataclass(frozen=True)
class VotiWorkbook:
    sheets: dict[str, list[VotoRow]]

    @property
    def rows(self) -> list[VotoRow]:
        return [row for rows in self.sheets.values() for row in rows]


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def parse_voto(value: Any) -> tuple[Decimal | None, bool]:
    """(voto, senza_voto): a number, or None with the flag set for an unrated player."""
    if _blank(value):
        return None, True
    if isinstance(value, bool):
        raise VotiShapeError(f"unreadable voto {value!r}")
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        text = str(value).strip().replace(",", ".")
        if text.endswith("*") or text.lower() in SENZA_VOTO_TEXT:
            return None, True
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise VotiShapeError(f"unreadable voto {value!r}") from None
    if number == SENZA_VOTO_SENTINEL:
        return None, True
    return number, False


def _count(value: Any) -> int:
    if _blank(value):
        return 0
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except ValueError:
        raise VotiShapeError(f"unreadable event count {value!r}") from None


def _parse_sheet(sheet: Any, path: Path) -> list[VotoRow] | None:
    """The sheet's player rows, or None when it carries no voti table at all."""
    rows: list[VotoRow] = []
    header_seen = False
    team: str | None = None
    width = len(VOTI_HEADER)
    for index, values in enumerate(sheet.iter_rows(values_only=True)):
        cells = list(values)
        if not header_seen:
            texts = [_text(c) for c in cells]
            if texts[:1] == [VOTI_HEADER[0]] and "Nome" in texts and "Voto" in texts:
                observed = tuple(t for t in texts if t)
                if observed != VOTI_HEADER:
                    raise VotiShapeError(f"{path}: sheet {sheet.title!r}: header {observed} is not {VOTI_HEADER}")
                header_seen = True
            elif index >= HEADER_SEARCH_ROWS:
                return None
            continue
        cells = (cells + [None] * width)[:width]
        first, rest = cells[0], cells[1:]
        rest_blank = all(_blank(c) for c in rest)
        if _blank(first) and rest_blank:
            continue
        if isinstance(first, str) and rest_blank:
            team = first.strip()
            continue
        try:
            player_id = int(first)
        except (TypeError, ValueError):
            raise VotiShapeError(f"{path}: sheet {sheet.title!r}: row {index + 1} is neither a club nor a player: {cells!r}") from None
        if team is None:
            raise VotiShapeError(f"{path}: sheet {sheet.title!r}: a player row before any club row")
        record = dict(zip(VOTI_HEADER, cells, strict=True))
        voto, senza_voto = parse_voto(record["Voto"])
        counts = {column: _count(record[header]) for header, column in COLUMNS.items()}
        rows.append(VotoRow(sheet=sheet.title, player_id=player_id, name=_text(record["Nome"]), team=team,
                            classic_role=_text(record["Ruolo"]), voto=voto, senza_voto=senza_voto,
                            raw={k: _jsonable(v) for k, v in record.items()}, **counts))
    return rows if header_seen else None


def parse_voti(path: Path) -> VotiWorkbook:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = {sheet.title: rows for sheet in workbook.worksheets
                  if (rows := _parse_sheet(sheet, path)) is not None}
    finally:
        workbook.close()
    if not sheets:
        raise VotiShapeError(f"{path}: no sheet carries the voti table (header {VOTI_HEADER})")
    return VotiWorkbook(sheets)


async def fetch_voti(http: httpx.AsyncClient, store: RawStore, *, cookie: str, season_id: int,
                     giornata: int) -> RawFile:
    url = VOTES_URL.format(season_id=season_id, giornata=giornata)
    data = await fetch_bytes(http, url, headers={"Cookie": cookie, "Accept": ACCEPT})
    if data[:4] != XLSX_MAGIC:
        if b"<html" in data[:2000].lower():
            # A login page with a 200 is the other way a dead session can look.
            raise WebSessionExpired(f"{url} -> HTTP 200 but an HTML page, not a workbook", url=url, status=200)
        raise VotiShapeError(f"{url}: not an xlsx ({len(data)} bytes)")
    return store.write_bytes("voti", data, ext="xlsx", label=f"{season_id}-{giornata:02d}")


@dataclass(frozen=True)
class VotiFetch:
    raws: dict[int, RawFile]
    skipped: list[int]                  # already on disk and not --refetch
    not_published_from: int | None      # the first giornata that answered 404; the loop stopped there


async def fetch_voti_range(http: httpx.AsyncClient, store: RawStore, *, cookie: str, season_id: int,
                           giornate: Iterable[int], existing: set[int], refetch: bool = False) -> VotiFetch:
    """One season's workbooks, in order, one second apart, stopping at the first 404.

    A giornata already on disk is skipped unless `refetch`: the files are
    immutable and the site republishes a giornata only to correct it, which
    is exactly what --refetch is for.
    """
    raws: dict[int, RawFile] = {}
    skipped: list[int] = []
    downloaded = 0
    for giornata in giornate:
        if giornata in existing and not refetch:
            skipped.append(giornata)
            continue
        if downloaded:
            await polite_pause()
        downloaded += 1
        try:
            raws[giornata] = await fetch_voti(http, store, cookie=cookie, season_id=season_id, giornata=giornata)
        except NotPublished:
            return VotiFetch(raws, skipped, giornata)
    return VotiFetch(raws, skipped, None)


@dataclass(frozen=True)
class VotiIngestResult:
    file_id: int | None
    season_id: int
    giornata: int
    inserted: int
    skipped_duplicate: bool
    sheets: list[str]
    unknown_players: int
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"file_id": self.file_id, "season_id": self.season_id, "giornata": self.giornata,
                "inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate, "sheets": self.sheets,
                "unknown_players": self.unknown_players, "sha256": self.sha256, "raw_path": self.raw_path}


def record_voti(con: duckdb.DuckDBPyConnection, season_id: int, giornata: int, workbook: VotiWorkbook,
                raw: RawFile, *, known_ids: set[int]) -> VotiIngestResult:
    """Append one file row and its player rows; the same bytes twice for the
    same giornata is a no-op (the key is season, giornata *and* content: two
    giornate whose workbooks happen to be byte-identical are two files).

    `unknown_players` counts ids the current listone does not carry -- in a
    back season that is every player who has since left Serie A, so it is a
    count in the report rather than a row-by-row warning.
    """
    existing = con.execute(
        "SELECT file_id, sheets FROM voti_files WHERE season_id = ? AND giornata = ? AND sha256 = ?",
        [season_id, giornata, raw.sha256]).fetchone()
    if existing is not None:
        return VotiIngestResult(existing[0], season_id, giornata, 0, True, list(existing[1]), 0,
                                raw.sha256, str(raw.path))
    rows = workbook.rows
    unknown = {r.player_id for r in rows} - known_ids
    con.begin()
    try:
        file_id = con.execute(
            "INSERT INTO voti_files (season_id, giornata, fetched_at, source, raw_path, sha256, sheets, row_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
            [season_id, giornata, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256,
             list(workbook.sheets), len(rows)]).fetchone()[0]
        con.executemany(
            "INSERT INTO player_match VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[file_id, season_id, giornata, r.sheet, r.player_id, r.name, r.team, r.classic_role, r.voto,
              r.senza_voto, r.goals, r.goals_conceded, r.pen_saved, r.pen_missed, r.pen_scored, r.own_goals,
              r.yellow, r.red, r.assists, json.dumps(r.raw, ensure_ascii=False)] for r in rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return VotiIngestResult(file_id, season_id, giornata, len(rows), False, list(workbook.sheets),
                            len(unknown), raw.sha256, str(raw.path))
```

- [ ] **Step 5: Extend `commands/ingest.py`**

Add to the import block: `from fantaclaude.ingest.stats_web import (VotiFetch, VotiIngestResult, fetch_voti_range, parse_voti, record_voti)`. Append:

```python
def existing_giornate(path: Path | None, seasons: list[int]) -> dict[int, set[int]]:
    """Which giornate of each season are already on disk (read-only, closed before returning)."""
    try:
        con = connect(path, read_only=True)
    except DatabaseMissing:
        return {season: set() for season in seasons}
    try:
        rows = con.execute("SELECT season_id, giornata FROM voti_files WHERE season_id IN "
                           f"({', '.join('?' for _ in seasons)})", seasons).fetchall() if seasons else []
    finally:
        con.close()
    found: dict[int, set[int]] = {season: set() for season in seasons}
    for season_id, giornata in rows:
        found[int(season_id)].add(int(giornata))
    return found


async def fetch_voti_seasons(http: httpx.AsyncClient, store: RawStore, *, cookie: str, seasons: list[int],
                             giornate: list[int], existing: dict[int, set[int]],
                             refetch: bool) -> dict[int, VotiFetch]:
    fetched: dict[int, VotiFetch] = {}
    for index, season_id in enumerate(seasons):
        if index:
            await polite_pause()
        fetched[season_id] = await fetch_voti_range(http, store, cookie=cookie, season_id=season_id,
                                                    giornate=giornate, existing=existing.get(season_id, set()),
                                                    refetch=refetch)
    return fetched


def record_voti_files(con: duckdb.DuckDBPyConnection, fetched: dict[int, VotiFetch]) -> list[VotiIngestResult]:
    known = {int(r[0]) for r in con.execute("SELECT player_id FROM v_players_current").fetchall()}
    results: list[VotiIngestResult] = []
    for season_id in sorted(fetched):
        for giornata in sorted(fetched[season_id].raws):
            raw = fetched[season_id].raws[giornata]
            results.append(record_voti(con, season_id, giornata, parse_voti(raw.path), raw, known_ids=known))
    return results
```

- [ ] **Step 6: Add the CLI command**

In `core/src/fantaclaude/cli/app.py`, after `COMPETITION_OPTION`:

```python
GIORNATA_OPTION = typer.Option(
    None, "--giornata", help="Giornata number(s), 1-38; repeatable. Default: every giornata.")
```

and after `ingest_calendar_cmd`:

```python
def _ranges(values: list[int]) -> str:
    """[1, 2, 3, 7] -> '1-3, 7'"""
    parts: list[str] = []
    for value in sorted(values):
        if parts and value == parts[-1][1] + 1:
            parts[-1] = (parts[-1][0], value)
        else:
            parts.append((value, value))
    return ", ".join(f"{a}-{b}" if a != b else f"{a}" for a, b in parts)


def _render_stats_web(payload: dict) -> str:
    data = payload["stats_web"]
    lines = []
    for season in sorted({f["season_id"] for f in data["files"]} | {int(s) for s in data["skipped"]}):
        files = [f for f in data["files"] if f["season_id"] == season]
        new = [f for f in files if not f["skipped_duplicate"]]
        dupes = [f for f in files if f["skipped_duplicate"]]
        bits = [f"{len(new)} new file(s)" + (f" (giornate {_ranges([f['giornata'] for f in new])})" if new else "")]
        if dupes:
            bits.append(f"{len(dupes)} duplicate(s)")
        skipped = data["skipped"].get(str(season), [])
        if skipped:
            bits.append(f"skipped {_ranges(skipped)} (already on disk)")
        stop = data["not_published_from"].get(str(season))
        if stop is not None:
            bits.append(f"not published from {stop}")
        lines.append(f"voti {season}: " + ", ".join(bits))
        if new:
            rows = sum(f["inserted"] for f in new)
            unknown = sum(f["unknown_players"] for f in new)
            lines.append(f"  sheets {', '.join(new[0]['sheets'])}; {rows} rows; "
                         f"{unknown} player ids not in the current listone")
    return "\n".join(lines) or "nothing to do"


@ingest_app.command("stats-web")
def ingest_stats_web_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    season: list[int] | None = SEASON_OPTION,
    giornata: list[int] | None = GIORNATA_OPTION,
    refetch: bool = typer.Option(False, "--refetch", help="Download again what is already on disk."),
) -> None:
    """Per-giornata voti and event counts from fantacalcio.it's XLSX export (needs FANTACALCIO_WEB_COOKIE)."""
    from fantaclaude.commands.ingest import existing_giornate, fetch_voti_seasons, record_voti_files
    from fantaclaude.config import web_cookie
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.model.seasons import SERIE_A_GIORNATE
    from fantaclaude.paths import raw_dir

    cookie = web_cookie()
    if cookie is None:
        typer.echo("FANTACALCIO_WEB_COOKIE is not set -- capture the website session first "
                   "(core/README.md, 'The website session')", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY)
    giornate = sorted(set(giornata)) if giornata else list(range(1, SERIE_A_GIORNATE + 1))
    bad = [g for g in giornate if not 1 <= g <= SERIE_A_GIORNATE]
    if bad:
        typer.echo(f"--giornata must be between 1 and {SERIE_A_GIORNATE}, got {bad}", err=True)
        raise typer.Exit(code=ExitCode.USAGE)
    seasons = _seasons_or_exit(season)
    existing = existing_giornate(None, seasons)
    store = RawStore(raw_dir())
    with _source_errors():
        fetched = run_web(lambda http: fetch_voti_seasons(
            http, store, cookie=cookie, seasons=seasons, giornate=giornate, existing=existing, refetch=refetch))
        con = connect()
        try:
            apply_schema(con)
            results = record_voti_files(con, fetched)
        finally:
            con.close()
    payload = {"stats_web": {
        "files": [r.to_dict() for r in results],
        "skipped": {str(s): sorted(f.skipped) for s, f in fetched.items()},
        "not_published_from": {str(s): f.not_published_from for s, f in fetched.items()
                               if f.not_published_from is not None},
    }}
    emit(payload, json_=json_, render=_render_stats_web)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run ruff check --fix core -q; uv run pytest core/tests/test_stats_web.py core/tests/test_fixtures.py -q`
Expected: 9 passed.

- [ ] **Step 8: Run the whole suite and lint, then commit**

Run: `uv run poe test-core && uv run ruff check core`
Expected: 152 passed; ruff clean.

```bash
git add core/src/fantaclaude/ingest/stats_web.py core/src/fantaclaude/commands/ingest.py core/src/fantaclaude/cli/app.py core/tests/fixtures/_extract_voti.py core/tests/fixtures/voti_sample.xlsx core/tests/test_stats_web.py core/tests/test_fixtures.py core/tests/conftest.py
git commit -m "feat(ingest): stats-web -- per-giornata voti and event counts from the XLSX export"
```

---

### Task 8: `ingest all`, the new `doctor` checks, documentation, and the exactly-once live run

**Files:**
- Modify: `core/src/fantaclaude/commands/ingest.py`, `core/src/fantaclaude/commands/doctor.py`, `core/src/fantaclaude/cli/app.py`, `core/tests/test_doctor.py`, `core/tests/test_listone.py`, `core/README.md`, `CLAUDE.md`
- Create: `core/tests/test_ingest_all.py`

**Interfaces:**
- Consumes: every `fetch_*`/`record_*` above, `web_cookie`, `default_seasons`, `existing_giornate`, `run_with_api`, `run_web`, `SCHEMA_VERSION`, `load_aliases`, the views.
- Produces: `fantaclaude.commands.ingest.{AllFetched(listone, advanced, calendar, stats_web, skipped), async fetch_everything(api, http, store, *, seasons, cookie, existing_voti, league=None) -> AllFetched, record_everything(con, fetched, aliases_path) -> dict[str, Any]}`; `fantaclaude.commands.doctor.run_doctor` reporting seventeen checks — the Phase 0a eleven plus `web_session`, `player_match`, `advanced`, `fixtures`, `aliases` (Task 9 adds `kb_profiles`); CLI `fantaclaude ingest all` covering every source, exit `3` when a source had to be skipped; the README section "The website session".

`ingest all` is idempotent and complete: it runs every source whose prerequisites are met, records everything it fetched, reports what it had to skip and why, and exits `3` if anything was skipped — so a skill sees "not everything is fresh" without parsing prose. The only skippable source is `stats_web` (no cookie); a rejected cookie is an error the run stops on, after the other sources are already recorded.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_ingest_all.py`:

```python
import json
import re

import httpx
import pytest
import respx
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import fetch_everything, record_everything
from fantaclaude.ingest.advanced import URL as UNDERSTAT_URL
from fantaclaude.ingest.calendar import UEFA_URL
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from test_calendar import _page
from typer.testing import CliRunner

COOKIE = "session=synthetic-value-for-tests"


@pytest.fixture
def no_pause(monkeypatch):
    async def fake(seconds=None):
        pass

    for target in ("fantaclaude.ingest.calendar.polite_pause", "fantaclaude.ingest.stats_web.polite_pause",
                   "fantaclaude.commands.ingest.polite_pause"):
        monkeypatch.setattr(target, fake)


def _seed(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    (tmp_path / "kb" / "rules").mkdir(parents=True)
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text(
        "understat: {}\nunderstat_teams:\n  AC Milan: Milan\nuefa_teams: {}\nfantacalcio_teams: {}\n")
    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    raw = RawStore(tmp_path / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    con.close()


def _mock_web(fixture_json, sample_xlsx):
    respx.post(UNDERSTAT_URL).mock(return_value=httpx.Response(200, json=fixture_json("understat_sample")["payload"]))
    respx.get(url__regex=r"https://www\.fantacalcio\.it/serie-a/calendario/(?P<giornata>\d+)$").mock(
        side_effect=lambda request, giornata: httpx.Response(200, text=_page(int(giornata), renamed=True)))
    uecl = fixture_json("uefa_sample")[1]["matches"]
    respx.get(UEFA_URL).mock(side_effect=lambda request: httpx.Response(
        200, json=uecl if request.url.params["competitionId"] == "2019" else []))
    respx.get(url__regex=r".*/api/v1/Excel/votes/(?P<s>\d+)/(?P<g>\d+)$").mock(
        side_effect=lambda request, s, g: httpx.Response(200 if int(g) <= 1 else 404,
                                                         content=sample_xlsx if int(g) <= 1 else b""))


@respx.mock
def test_cli_ingest_all_runs_every_source(monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fixture_file,
                                          fake_api, no_pause):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.setenv("FANTACALCIO_WEB_COOKIE", COOKIE)
    _seed(tmp_path, fixture_json, mcp_fixture_json)
    _mock_web(fixture_json, fixture_file("voti_sample.xlsx").read_bytes())
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: __import__("asyncio").run(fn(api)))

    result = CliRunner().invoke(app, ["ingest", "all", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {"listone", "advanced", "calendar", "stats_web", "skipped"}
    assert payload["listone"]["skipped_duplicate"] is True                       # same listone bytes as the seed
    assert [r["season_id"] for r in payload["advanced"]] == [18, 19, 20, 21]
    assert {r["competition"] for r in payload["calendar"]} == {"SA", "UCL", "UEL", "UECL"}
    assert [(f["season_id"], f["giornata"]) for f in payload["stats_web"]["files"]] == [(18, 1), (19, 1), (20, 1), (21, 1)]
    assert payload["skipped"] == []
    assert api.calls == ["players"]                                               # one live call, the listone

    again = CliRunner().invoke(app, ["ingest", "all"])
    assert again.exit_code == ExitCode.OK, again.output
    assert "duplicate" in again.stdout and "unchanged" in again.stdout and "skipped 1" in again.stdout


@respx.mock
def test_cli_ingest_all_without_the_cookie_skips_stats_web_and_exits_3(monkeypatch, tmp_path, fixture_json,
                                                                      mcp_fixture_json, fixture_file, fake_api, no_pause):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.delenv("FANTACALCIO_WEB_COOKIE", raising=False)
    _seed(tmp_path, fixture_json, mcp_fixture_json)
    _mock_web(fixture_json, fixture_file("voti_sample.xlsx").read_bytes())
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: __import__("asyncio").run(fn(api)))

    result = CliRunner().invoke(app, ["ingest", "all", "--json"])
    assert result.exit_code == ExitCode.NOT_READY, result.output
    payload = json.loads(result.stdout)
    assert payload["skipped"] == ["stats_web: FANTACALCIO_WEB_COOKIE is not set"]
    assert payload["stats_web"] is None and len(payload["advanced"]) == 4        # everything else still ran
    assert not any(re.search(r"votes/\d+/\d+", str(c.request.url)) for c in respx.calls)


@respx.mock
async def test_fetch_and_record_everything_directly(db, tmp_path, fixture_json, mcp_fixture_json, fixture_file,
                                                    fake_api, no_pause):
    from fantaclaude.ingest.listone_api import load_listone, record_listone

    raw = RawStore(tmp_path / "seed").write("listone", fixture_json("listone_sample"))
    record_listone(db, load_listone(raw.path), raw)
    record_snapshot(db, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    _mock_web(fixture_json, fixture_file("voti_sample.xlsx").read_bytes())
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    aliases = tmp_path / "aliases.yml"
    aliases.write_text("understat_teams:\n  AC Milan: Milan\nuefa_teams: {}\nfantacalcio_teams: {}\n")
    async with httpx.AsyncClient() as http:
        fetched = await fetch_everything(api, http, RawStore(tmp_path / "raw"), seasons=[20, 21], cookie=None,
                                         existing_voti={20: set(), 21: set()})
    assert fetched.stats_web is None and fetched.skipped == ["stats_web: FANTACALCIO_WEB_COOKIE is not set"]
    assert sorted(fetched.advanced) == [20, 21] and set(fetched.calendar) == {"SA", "UCL", "UEL", "UECL"}
    recorded = record_everything(db, fetched, aliases)
    assert recorded["listone"]["skipped_duplicate"] and recorded["stats_web"] is None
    assert db.execute("SELECT count(*) FROM v_advanced_current").fetchone()[0] == 20
    assert db.execute("SELECT count(*) FROM v_fixtures_current WHERE competition = 'SA'").fetchone()[0] == 114
```

Replace `core/tests/test_doctor.py`'s `NAMES`, `_paths` and `_ready_workspace` with (keep every test function as it is):

```python
NAMES = ["env", "credentials", "token_cache", "database", "extensions", "league_settings",
         "listone", "league_yml", "preferences", "kb", "modules",
         "web_session", "player_match", "advanced", "fixtures", "aliases"]


def _paths(root):
    return DoctorPaths(env=root / ".env", token_cache=root / ".auth" / "tokens.json",
                       db=root / "data" / "fanta.duckdb", league_yml=root / "league.yml",
                       preferences=root / "preferences.yml", kb=root / "kb")


def _ready_workspace(root, fixture_json, mcp_fixture_json, *, token_exp_offset=31_536_000):
    from fantaclaude.ingest.advanced import load_advanced, record_advanced
    from fantaclaude.ingest.calendar import load_uefa, record_fixtures
    from fantaclaude.ingest.names import Aliases, load_candidates, load_teams
    from fantaclaude.ingest.stats_web import parse_voti, record_voti

    token = make_jwt(user_id="1", l_id="2578630", t_id="1", role="user_league",
                     exp=int(time.time()) + token_exp_offset)
    (root / ".env").write_text("FANTACALCIO_APP_KEY=K\nFANTACALCIO_USERNAME=u\nFANTACALCIO_PASSWORD=synthetic\n"
                               "FANTACALCIO_WEB_COOKIE=\"session=synthetic\"\n")
    (root / ".auth").mkdir()
    (root / ".auth" / "tokens.json").write_text(json.dumps({
        "account": None, "user_id": None, "username": "u",
        "leagues": {"fantabalotelli3": {"alias": "fantabalotelli3", "league_id": "2578630",
                                        "team_id": "1", "name": "F3", "jwt": token}}}))
    (root / "league.yml").write_text("budget: {value: 500, source: admin, verified_on: 2026-08-24}\n")
    (root / "preferences.yml").write_text("target_composition: {Por: 2}\n")
    (root / "kb" / "rules").mkdir(parents=True)
    (root / "kb" / "README.md").write_text("# kb\n")
    (root / "kb" / "rules" / "aliases.yml").write_text("understat: {}\nuefa_teams: {}\n")
    con = connect(root / "data" / "fanta.duckdb")
    apply_schema(con)
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    store = RawStore(root / "data" / "raw")
    raw = store.write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    known = {r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()}
    voti = store.write_bytes("voti", (FIXTURE_DIR / "voti_sample.xlsx").read_bytes(), ext="xlsx", label="21-01")
    record_voti(con, 21, 1, parse_voti(voti.path), voti, known_ids=known)
    advanced = store.write("advanced", fixture_json("understat_sample"), label="20")
    season_id, rows = load_advanced(advanced.path)
    record_advanced(con, season_id, rows, advanced, candidates=load_candidates(con), teams=load_teams(con),
                    aliases=Aliases(teams={"understat": {"AC Milan": "Milan"}}))
    uefa = store.write("calendar", fixture_json("uefa_sample")[1], label="uecl-21-00")
    record_fixtures(con, "UECL", 21, load_uefa([uefa.path]), [uefa], teams=load_teams(con), team_aliases={})
    con.close()
```

Add `from conftest import FIXTURE_DIR, make_jwt` in place of `from conftest import make_jwt`, and append these tests:

```python
def test_history_checks_describe_coverage(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["web_session"].ok and by["web_session"].detail == "FANTACALCIO_WEB_COOKIE set"
    assert "synthetic" not in by["web_session"].detail
    assert by["player_match"].ok and "season 21: giornate 1" in by["player_match"].detail
    assert by["advanced"].ok and "season 20" in by["advanced"].detail and "ambiguous" in by["advanced"].detail
    assert by["fixtures"].ok is False and "no Serie A calendar" in by["fixtures"].detail   # UECL only, no SA yet
    assert by["aliases"].ok and "2 sections" in by["aliases"].detail


def test_history_checks_on_an_empty_database(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    for table in ("player_match", "voti_files", "advanced_stats", "advanced_snapshots", "fixtures", "fixture_snapshots"):
        con.execute(f"DELETE FROM {table}")
    con.close()
    (tmp_path / ".env").write_text("FANTACALCIO_APP_KEY=K\nFANTACALCIO_USERNAME=u\nFANTACALCIO_PASSWORD=synthetic\n")
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("understat: [1, 2\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["web_session"].ok and "not set" in by["web_session"].detail
    assert not by["player_match"].ok and "ingest stats-web" in by["player_match"].detail
    assert not by["advanced"].ok and "ingest advanced" in by["advanced"].detail
    assert not by["fixtures"].ok and "ingest calendar" in by["fixtures"].detail
    assert not by["aliases"].ok
```

In `test_every_check_passes_on_a_ready_workspace`, change `assert all(c.ok for c in checks), [...]` to `assert [c.name for c in checks if not c.ok] == ["fixtures"]` (the ready workspace above has no Serie A calendar on purpose, so `fixtures` reports it), and in `test_doctor_cli_exit_codes` change the final two assertions to `assert result.exit_code == ExitCode.NOT_READY` and `assert "FAIL  fixtures" in result.stdout and "listone" in result.stdout`. In `cli/app.py`, change `doctor_cmd`'s docstring to `"""Readiness check: credentials, token cache, website session, database, every snapshot's coverage, league.yml, kb, aliases, module table."""`.

In `core/tests/test_listone.py`, change the import to `from fantaclaude.commands.ingest import ingest_listone`; `test_ingest_listone_command_end_to_end` still calls `ingest_all(api, db, store)` — replace that call and its assertion with:

```python
    twice = await ingest_listone(api, db, RawStore(tmp_path / "raw"))
    assert twice.skipped_duplicate
```

and in `test_cli_ingest_listone_json` drop the two lines that invoke `["ingest", "all"]` (Task 8's own test covers it).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_ingest_all.py core/tests/test_doctor.py core/tests/test_listone.py -q`
Expected: FAIL — `ImportError: fetch_everything`; doctor's `NAMES` mismatch.

- [ ] **Step 3: Rewrite `ingest all` in `commands/ingest.py`**

Delete `fetch_all`, `record_all` and `ingest_all` from `core/src/fantaclaude/commands/ingest.py` (keep `ingest_listone`) and append:

```python
@dataclass(frozen=True)
class AllFetched:
    season_id: int                              # the season the league is in; the calendar's season
    listone: RawFile
    advanced: dict[int, RawFile]
    calendar: dict[str, list[RawFile]]
    stats_web: dict[int, VotiFetch] | None      # None when skipped
    skipped: list[str]


async def fetch_everything(api: FantacalcioAPI, http: httpx.AsyncClient, store: RawStore, *,
                           seasons: list[int], cookie: str | None, existing_voti: dict[int, set[int]],
                           league: str | None = None) -> AllFetched:
    """The network half of `ingest all`: one league-API call, then the web sources.

    A source whose prerequisite is missing is skipped and named; nothing
    else is. The listone goes first because every other source is matched
    against it at record time.
    """
    skipped: list[str] = []
    listone = await fetch_listone(api, store, league=league)
    advanced = await fetch_advanced_seasons(http, store, seasons)
    await polite_pause()
    calendar = await fetch_calendar(http, store, seasons[-1], list(COMPETITIONS))
    stats_web: dict[int, VotiFetch] | None = None
    if cookie is None:
        skipped.append("stats_web: FANTACALCIO_WEB_COOKIE is not set")
    else:
        await polite_pause()
        stats_web = await fetch_voti_seasons(http, store, cookie=cookie, seasons=seasons,
                                             giornate=list(range(1, SERIE_A_GIORNATE + 1)),
                                             existing=existing_voti, refetch=False)
    return AllFetched(seasons[-1], listone, advanced, calendar, stats_web, skipped)


def record_everything(con: duckdb.DuckDBPyConnection, fetched: AllFetched, aliases_path: Path) -> dict[str, Any]:
    """The database half: listone first (the identity every join needs), then the rest."""
    listone = record_listone(con, load_listone(fetched.listone.path), fetched.listone)
    advanced = record_advanced_seasons(con, fetched.advanced, aliases_path)
    calendar = record_calendar(con, fetched.season_id, fetched.calendar, aliases_path)
    stats_web = None
    if fetched.stats_web is not None:
        files = record_voti_files(con, fetched.stats_web)
        stats_web = {"files": [r.to_dict() for r in files],
                     "skipped": {str(s): sorted(f.skipped) for s, f in fetched.stats_web.items()},
                     "not_published_from": {str(s): f.not_published_from for s, f in fetched.stats_web.items()
                                            if f.not_published_from is not None}}
    return {"listone": listone.to_dict(), "advanced": [r.to_dict() for r in advanced],
            "calendar": [r.to_dict() for r in calendar], "stats_web": stats_web, "skipped": list(fetched.skipped)}
```

Add `from dataclasses import dataclass`, `from typing import Any` and `from fantaclaude.ingest.calendar import COMPETITIONS` (extend the existing `fantaclaude.ingest.calendar` import) to the import block.

- [ ] **Step 4: Rewrite `ingest all` in `cli/app.py`**

Replace `_render_ingest`, `_run_ingest`, `ingest_listone_cmd` and `ingest_all_cmd` with:

```python
def _render_listone(payload: dict) -> str:
    if payload["skipped_duplicate"]:
        return f"listone: duplicate of snapshot {payload['snapshot_id']} -- nothing new ({payload['raw_path']})"
    return f"listone: snapshot {payload['snapshot_id']}, {payload['inserted']} rows ({payload['raw_path']})"


@ingest_app.command("listone")
def ingest_listone_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Fetch the listone (539 players, Mantra roles and quotazioni) and snapshot it."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.listone_api import fetch_listone, load_listone, record_listone
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir

    store = RawStore(raw_dir())
    # Fetch into data/raw/ first; open the database only to record. Same reason
    # as sync-league: the write lock should not span the network call, and a
    # failed first run must not leave an empty database that looks ingested.
    raw = run_with_api(lambda api: fetch_listone(api, store, league=league))
    con = connect()
    try:
        apply_schema(con)
        result = record_listone(con, load_listone(raw.path), raw)
    finally:
        con.close()
    emit(result.to_dict(), json_=json_, render=_render_listone)


def _render_all(payload: dict) -> str:
    lines = [_render_listone(payload["listone"]), _render_advanced(payload), _render_calendar(payload)]
    if payload["stats_web"] is not None:
        lines.append(_render_stats_web(payload))
    for reason in payload["skipped"]:
        lines.append(f"SKIPPED {reason}")
    return "\n".join(line for line in lines if line)


@ingest_app.command("all")
def ingest_all_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh every source: listone (league API), advanced (Understat), calendar (fantacalcio.it, UEFA), stats-web (voti XLSX). Exit 3 if one had to be skipped."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.ingest import existing_giornate, fetch_everything, record_everything
    from fantaclaude.config import web_cookie
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import build_http
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    seasons = _seasons_or_exit(None)
    existing = existing_giornate(None, seasons)
    cookie = web_cookie()
    store = RawStore(raw_dir())

    async def go(api):
        http = build_http()
        try:
            return await fetch_everything(api, http, store, seasons=seasons, cookie=cookie,
                                          existing_voti=existing, league=league)
        finally:
            await http.aclose()

    with _source_errors():
        fetched = run_with_api(go)
        con = connect()
        try:
            apply_schema(con)
            payload = record_everything(con, fetched, aliases_path())
        finally:
            con.close()
    emit(payload, json_=json_, render=_render_all)
    if payload["skipped"]:
        raise typer.Exit(code=ExitCode.NOT_READY)
```

`run_with_api` opens the league-API client on the loop and `go` opens the web client on the same loop, so both are closed where they were created.

- [ ] **Step 5: Rewrite `doctor.py`**

Replace `core/src/fantaclaude/commands/doctor.py` in full. `Check`, `DoctorPaths`, `_age`, `_token_cache` and `_yaml_check` are unchanged from Phase 0a and are repeated here so the file can be written in one go:

```python
"""fantaclaude doctor: is the workspace ready for the night?

Every check reports existence, parseability, coverage or age -- never a
value. A token is "present, expires in N days", an app key is "set", the
website cookie is "set", and nothing here can leak into a terminal log.
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

from fantaclaude.config import WEB_COOKIE_KEY
from fantaclaude.db.schema import SCHEMA_VERSION
from fantaclaude.ingest.names import AliasError, load_aliases
from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
from fantaclaude.model.modules import ModuleTableError, load_modules

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


def _skipped(reason: str) -> tuple[list[Check], list[Check]]:
    return ([Check(name, False, reason) for name in CORE_DB_CHECKS],
            [Check(name, False, reason) for name in HISTORY_DB_CHECKS])


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
        "SELECT season_id, row_count, matched, ambiguous, unmatched, fetched_at FROM advanced_snapshots "
        "WHERE snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id) "
        "ORDER BY season_id").fetchall()
    if not seasons:
        checks.append(Check("advanced", False, "no Understat rows yet -- run `fantaclaude ingest advanced`"))
    else:
        detail = "; ".join(f"season {r[0]}: {r[1]} rows, {r[2]} matched, {r[3]} ambiguous, {r[4]} unmatched"
                           for r in seasons)
        checks.append(Check("advanced", True, f"{detail}; newest {_age(seasons[-1][5], now)}"))
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


def _database_checks(path: Path, now: datetime) -> tuple[list[Check], list[Check]]:
    """(the Phase 0a checks, the history checks) -- reported in two places so the
    check order stays the documented one."""
    if not path.is_file():
        core, history = _skipped("skipped: no database")
        core[0] = Check("database", False,
                        f"no database at {path} -- run `fantaclaude sync-league` and `fantaclaude ingest listone`")
        return core, history
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        core, history = _skipped("skipped: database unavailable")
        core[0] = Check("database", False, f"cannot open database at {path}: {exc}")
        return core, history
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
    finally:
        con.close()
    return core, history


def _yaml_check(name: str, path: Path, required_key: str) -> Check:
    if not path.is_file():
        return Check(name, False, f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return Check(name, False, f"does not parse: {exc}")
    if not isinstance(data, dict) or required_key not in data:
        return Check(name, False, f"no `{required_key}` key")
    return Check(name, True, f"{len(data)} top-level keys")


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
    core, history = _database_checks(paths.db, now)
    checks.extend(core)
    try:
        entries = load_league_yml(paths.league_yml) if paths.league_yml.is_file() else None
        checks.append(Check("league_yml", entries is not None,
                            f"{len(entries)} provenanced keys" if entries is not None else f"{paths.league_yml} is missing"))
    except (LeagueYmlError, yaml.YAMLError) as exc:
        checks.append(Check("league_yml", False, str(exc)))
    checks.append(_yaml_check("preferences", paths.preferences, "target_composition"))
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
    except (AliasError, yaml.YAMLError) as exc:
        checks.append(Check("aliases", False, str(exc)))
    return checks
```

- [ ] **Step 6: Run the tests, the whole suite and lint**

Run: `uv run ruff check --fix core -q; uv run poe test-core && uv run ruff check core`
Expected: 157 passed (152 + 3 in `test_ingest_all.py` + 2 new doctor tests); ruff clean.

- [ ] **Step 7: Documentation**

In `core/README.md`, replace the commands table with:

```markdown
| command | does |
| --- | --- |
| `fantaclaude sync-league` | appends a `league_settings` snapshot when the rules hash moves; refuses (exit 4) if `league.yml` disagrees with the API |
| `fantaclaude ingest listone` | the listone through the league API → `data/raw/listone/`, `players` |
| `fantaclaude ingest advanced [--season N]…` | Understat season totals (games, minutes, xG, xA) matched onto listone ids → `advanced_stats`; ambiguous and unmatched names are reported, never dropped |
| `fantaclaude ingest calendar [--competition …]…` | the current season's Serie A giornate (fantacalcio.it) and every UEFA tie of an Italian club → `fixtures`, `v_european_ties` |
| `fantaclaude ingest stats-web [--season N]… [--giornata N]… [--refetch]` | per-giornata voti and event counts from the XLSX export → `player_match`, `v_player_season`, `v_player_form`; needs the website session below |
| `fantaclaude ingest all` | every source above; exit 3 if one had to be skipped |
| `fantaclaude schema` | tables, views, columns — what `query` may name |
| `fantaclaude query --sql …` | read-only SQL; prefer the `v_*` views |
| `fantaclaude kb audit` | expired or malformed knowledge-base documents |
| `fantaclaude doctor` | readiness: credentials, token cache, website session, database, every snapshot's coverage, `league.yml`, `kb/`, aliases, module table |
```

After the "**Run them when you need fresh data, once — never in a loop.** Everything else is local." paragraph, add:

```markdown
`ingest advanced`, `ingest calendar` and `ingest stats-web` read public web
hosts (Understat, fantacalcio.it, UEFA) one request at a time with a one-second
pause between pages and an honest `User-Agent`. Run them when data is needed,
not to check whether anything changed: an unchanged source is reported as a
duplicate and costs the host a request all the same.

## The website session

The voti export (`/api/v1/Excel/votes/<season>/<giornata>`) is behind the
fantacalcio.it *website* login — a different session from the league API's.
Nothing in this repository logs in to it. The account holder logs in once in
their own browser, copies the `Cookie` request header of the Excel download
from the developer tools, and puts it in `.env`:

    FANTACALCIO_WEB_COOKIE="name=value; name2=value2"

`fantaclaude doctor` reports whether it is set, never its value; `ingest
stats-web` exits 3 with a re-capture hint when the site rejects it. Names,
lifetime and the workbook layout are recorded in the design spec, open
question 5.
```

And under "Layout": `data/raw/` now holds `listone/`, `advanced/`, `calendar/` (one HTML page per giornata, one JSON page per UEFA competition) and `voti/` (one workbook per giornata); `kb/rules/aliases.yml` is where an ambiguous Understat name or a UEFA club spelling is resolved by hand.

In `CLAUDE.md`, under "## Secrets", add the bullet: `- `FANTACALCIO_WEB_COOKIE` in `.env` is the fantacalcio.it website session. It is copied from a browser, never obtained by code, and no command may print it — `doctor` says "set", nothing more.` Under "## Workspace and tests", append the paragraph:

```markdown
`fantaclaude ingest advanced|calendar|stats-web` read public web hosts. They
are polite by construction (one request at a time, a pause between pages, no
retries) and must stay so: never add a retry loop, never run them "to check",
and never fetch during the auction. The golden fixtures under
`core/tests/fixtures/` are extracted from files in `captured/` by the
`_extract_*.py` scripts; when a source changes shape, capture again and
regenerate — never edit a fixture by hand.
```

- [ ] **Step 8: The exactly-once live run**

Two league-API calls at most (`ingest all` fetches the listone once; `sync-league` is not needed unless `doctor` says the rules are stale), then the web hosts once each. Run, read, do not repeat:

```bash
cd /Users/grimid3v/Workspace/fantaclaudio
uv run fantaclaude doctor                        # expected: schema version 1 -> "migrates forward" note; history checks FAIL
uv run fantaclaude ingest all                    # expected: listone duplicate or new; advanced 18..21; calendar SA (38 giornate), UCL/UEL/UECL; voti 18..21 (up to ~116 files, ~3 minutes)
uv run fantaclaude doctor                        # expected: every check ok except what the run above reported
```

Then, all local:

```bash
uv run fantaclaude query --sql "SELECT season_id, sheet, count(*) AS players, sum(presenze) AS presenze FROM v_player_season GROUP BY 1, 2 ORDER BY 1, 2"
uv run fantaclaude query --sql "SELECT season_id, match_status, count(*) FROM v_advanced_current GROUP BY 1, 2 ORDER BY 1, 2"
uv run fantaclaude query --sql "SELECT * FROM v_advanced_unmatched WHERE match_status = 'ambiguous'"
uv run fantaclaude query --sql "SELECT team_short, competition, count(*) FROM v_european_ties GROUP BY 1, 2 ORDER BY 1, 2"
uv run fantaclaude query --sql "SELECT giornata, min(kickoff), max(kickoff) FROM v_fixtures_current WHERE competition = 'SA' GROUP BY 1 ORDER BY 1 LIMIT 5"
```

Expected: three back seasons at 38 giornate each plus the current season's played ones; matched counts around 300 for the current season and 365 for last season; the ambiguous list is short — resolve each one by adding an `understat:` alias in `kb/rules/aliases.yml` and re-running `ingest advanced` **once**; European ties for the Italian clubs in Europe this season (empty for competitions not yet drawn — re-run `ingest calendar` after the draws). Anything a source rejected is an exit code and a message, never a traceback.

- [ ] **Step 9: Commit**

```bash
git add core/src/fantaclaude/commands/ingest.py core/src/fantaclaude/commands/doctor.py core/src/fantaclaude/cli/app.py core/tests/test_ingest_all.py core/tests/test_doctor.py core/tests/test_listone.py core/README.md CLAUDE.md kb/rules/aliases.yml
git commit -m "feat: ingest all across every source, history-aware doctor, and the web-source rules"
```

---

### Task 9: Team profiles, the `fanta-kb` skill, and the knowledge-base bootstrap

**Files:**
- Create: `core/src/fantaclaude/kb/profiles.py`, `core/tests/test_kb_profiles.py`, `.claude/skills/fanta-kb/SKILL.md`, `kb/rules/mantra.md`, `kb/rules/house-rules.md`, `kb/serie-a/teams/<slug>/profile.md` for every club in `v_teams_current` (twenty)
- Modify: `core/src/fantaclaude/kb/audit.py`, `core/src/fantaclaude/commands/doctor.py`, `core/tests/test_doctor.py`, `core/tests/test_kb_audit.py`, `kb/README.md`, `.gitignore`

**Interfaces:**
- Consumes: `fantaclaude.kb.audit.{parse_front_matter, FrontMatter, FrontMatterError}`, `fantaclaude.ingest.names.normalise`, `v_teams_current`, `v_european_ties`, `v_league_settings_current`, `DoctorPaths`.
- Produces: `fantaclaude.kb.profiles.{PROFILE_KEYS, EUROPE, ROTATION_RANGE, ProfileError, TeamProfile(path, team, team_short, coach, module, europe, rotation_factor, takers, front_matter), team_slug(name) -> str, load_profile(path) -> TeamProfile, load_profiles(kb_dir) -> list[TeamProfile]}`; `kb audit` marks a malformed profile `invalid`; `doctor` check `kb_profiles` (the seventeenth, last); the `/fanta-kb` skill with `bootstrap` and `refresh`; the bootstrapped tree.

The front-matter is for the code, the prose is for the model. Phase 1 reads `rotation_factor`, `europe`, `module` and `takers` as numbers and labels through `load_profiles`; nothing else parses a profile. `rotation_factor` is a judgment written as a visible, dated number — competition type, coach tendency and squad depth combined (spec, "European competition and rotation") — and `doctor` cross-checks `europe` against `v_european_ties` so a profile cannot quietly disagree with the fixture list.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_kb_profiles.py`:

```python
from datetime import UTC, date, datetime

import pytest
from fantaclaude.kb.audit import audit
from fantaclaude.kb.profiles import (
    EUROPE,
    PROFILE_KEYS,
    ProfileError,
    load_profile,
    load_profiles,
    team_slug,
)

PROFILE = """---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: club site, Transfermarkt"
team: {team}
team_short: {short}
coach: Cristian Chivu
module: 3-5-2
europe: {europe}
rotation_factor: {rotation}
takers:
  penalties: Calhanoglu
  corners: Dimarco
---

# {team} — 2026-27

## Tactics
Prose.
"""


def _write(kb, team, short, *, europe="UCL", rotation="0.9", slug=None):
    folder = kb / "serie-a" / "teams" / (slug or team_slug(team))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "profile.md"
    path.write_text(PROFILE.format(team=team, short=short, europe=europe, rotation=rotation), encoding="utf-8")
    return path


def test_team_slug():
    assert team_slug("Inter") == "inter" and team_slug("Hellas Verona") == "hellas-verona"
    assert team_slug("Milan") == "milan" and team_slug("Cagliari ") == "cagliari"


def test_load_profile_reads_the_structured_front_matter(tmp_path):
    path = _write(tmp_path / "kb", "Inter", "INT")
    profile = load_profile(path)
    assert (profile.team, profile.team_short, profile.coach, profile.module) == ("Inter", "INT", "Cristian Chivu", "3-5-2")
    assert profile.europe == "UCL" and profile.rotation_factor == 0.9
    assert profile.takers == {"penalties": "Calhanoglu", "corners": "Dimarco"}
    assert profile.front_matter.updated == date(2026, 8, 29) and profile.path == path
    assert PROFILE_KEYS == ("team", "team_short", "coach", "module", "europe", "rotation_factor")
    assert EUROPE == ("none", "UCL", "UEL", "UECL")


@pytest.mark.parametrize("edit, message", [
    (lambda text: text.replace("europe: UCL", "europe: Champions"), "europe"),
    (lambda text: text.replace("rotation_factor: 0.9", "rotation_factor: 1.4"), "rotation_factor"),
    (lambda text: text.replace("rotation_factor: 0.9", "rotation_factor: high"), "rotation_factor"),
    (lambda text: text.replace("coach: Cristian Chivu\n", ""), "coach"),
    (lambda text: text.replace("team_short: INT", "team_short: int"), "team_short"),
    (lambda text: text.replace("takers:\n  penalties: Calhanoglu\n  corners: Dimarco\n", "takers: Calhanoglu\n"), "takers"),
    (lambda text: text.replace("---\nupdated", "updated", 1), "front-matter"),
])
def test_load_profile_fails_loud(tmp_path, edit, message):
    path = _write(tmp_path / "kb", "Inter", "INT")
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ProfileError, match=message):
        load_profile(path)


def test_the_folder_must_be_the_team_slug(tmp_path):
    path = _write(tmp_path / "kb", "Inter", "INT", slug="internazionale")
    with pytest.raises(ProfileError, match="internazionale"):
        load_profile(path)


def test_load_profiles_walks_the_tree_and_the_audit_flags_bad_ones(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "Inter", "INT")
    _write(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85")
    bad = _write(kb, "Milan", "MIL", europe="Europa")
    with pytest.raises(ProfileError, match="milan"):
        load_profiles(kb)
    statuses = {e.path: e.status for e in audit(kb, date(2026, 8, 30))}
    assert statuses["serie-a/teams/inter/profile.md"] == "ok"
    assert statuses["serie-a/teams/milan/profile.md"] == "invalid"
    bad.unlink()
    assert [p.team for p in load_profiles(kb)] == ["Atalanta", "Inter"]
    assert load_profiles(tmp_path / "nowhere") == []


def test_doctor_kb_profiles_check(tmp_path, fixture_json, mcp_fixture_json):
    from test_doctor import NAMES, _paths, _ready_workspace
    from fantaclaude.commands.doctor import run_doctor

    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)          # listone sample: 8 clubs; UECL ties for ATA
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert NAMES[-1] == "kb_profiles" and not by["kb_profiles"].ok
    assert "0/8 teams profiled" in by["kb_profiles"].detail and "Atalanta" in by["kb_profiles"].detail

    kb = tmp_path / "kb"
    for name, short in (("Cagliari", "CAG"), ("Roma", "ROM"), ("Inter", "INT"), ("Milan", "MIL"), ("Fiorentina", "FIO"),
                        ("Napoli", "NAP"), ("Genoa", "GEN")):
        _write(kb, name, short, europe="none", rotation="1.0")
    _write(kb, "Atalanta", "ATA", europe="none", rotation="1.0")        # disagrees with the UECL ties
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["kb_profiles"].ok and "8/8 teams profiled" in by["kb_profiles"].detail
    assert "Atalanta: profile says none, fixtures say UECL" in by["kb_profiles"].detail

    _write(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["kb_profiles"].ok and by["kb_profiles"].detail == "8/8 teams profiled; europe agrees with the fixtures"

    _write(kb, "Milan", "MIL", europe="Europa")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["kb_profiles"].ok and "milan" in by["kb_profiles"].detail


def test_committed_profiles_load(monkeypatch):
    """After the bootstrap run: every Serie A club has a profile that parses."""
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import kb_dir

    profiles = load_profiles(kb_dir())
    assert len(profiles) == 20
    assert all(len(p.team_short) == 3 and p.team_short.isupper() for p in profiles)
    assert all(0.5 <= p.rotation_factor <= 1.0 for p in profiles)
    assert {p.europe for p in profiles} & {"UCL", "UEL", "UECL"}                    # someone plays in Europe
    for name in ("mantra.md", "house-rules.md"):
        assert (kb_dir() / "rules" / name).is_file(), name
```

In `core/tests/test_doctor.py`, append `"kb_profiles"` to `NAMES` (so it ends `…, "aliases", "kb_profiles"]`), and in `test_every_check_passes_on_a_ready_workspace` change the expectation to `assert [c.name for c in checks if not c.ok] == ["fixtures", "kb_profiles"]`. In `core/tests/test_kb_audit.py::test_audit_classifies_documents`, the bare `serie-a/teams/inter/profile.md` (front-matter only, none of the profile keys) is now correctly reported as invalid: change its expected status from `"ok"` to `"invalid"` and add the comment `# a profile needs the keys fantaclaude.kb.profiles validates`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest core/tests/test_kb_profiles.py core/tests/test_doctor.py -q`
Expected: FAIL — `ModuleNotFoundError: fantaclaude.kb.profiles`; `NAMES` mismatch.

- [ ] **Step 3: Write `kb/profiles.py`**

```python
"""Team profiles: the structured front-matter Phase 1 reads.

kb/serie-a/teams/<slug>/profile.md carries, beside the audit's four keys,
what the projection needs as numbers and labels -- team, team_short,
coach, module, europe, rotation_factor -- and the set-piece takers as a
small mapping. The prose below the front-matter is for the model; the
front-matter is for the code, and this loader is its only reader, so a
malformed profile fails here with its path rather than as a wrong
projection in September.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.ingest.names import normalise
from fantaclaude.kb.audit import FrontMatter, FrontMatterError, parse_front_matter

PROFILE_KEYS = ("team", "team_short", "coach", "module", "europe", "rotation_factor")
EUROPE = ("none", "UCL", "UEL", "UECL")
ROTATION_RANGE = (0.5, 1.0)


class ProfileError(ValueError):
    """A profile's front-matter is missing or malformed; the message names the file."""


@dataclass(frozen=True)
class TeamProfile:
    path: Path
    team: str
    team_short: str
    coach: str
    module: str
    europe: str
    rotation_factor: float
    takers: dict[str, str]
    front_matter: FrontMatter


def team_slug(name: str) -> str:
    """"Hellas Verona" -> "hellas-verona": the folder a club's notes live in."""
    return "-".join(normalise(name))


def load_profile(path: Path) -> TeamProfile:
    try:
        front_matter = parse_front_matter(path.read_text(encoding="utf-8"))
    except (FrontMatterError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ProfileError(f"{path}: {exc}") from None
    if front_matter is None:
        raise ProfileError(f"{path}: no front-matter block")
    data: dict[str, Any] = front_matter.raw
    missing = [key for key in PROFILE_KEYS if data.get(key) in (None, "")]
    if missing:
        raise ProfileError(f"{path}: missing {missing}")
    for key in ("team", "coach", "module"):
        if not isinstance(data[key], str):
            raise ProfileError(f"{path}: {key} must be text")
    short = data["team_short"]
    if not isinstance(short, str) or len(short) != 3 or not short.isupper():
        raise ProfileError(f"{path}: team_short must be the listone's three-letter code, got {short!r}")
    if data["europe"] not in EUROPE:
        raise ProfileError(f"{path}: europe must be one of {EUROPE}, got {data['europe']!r}")
    rotation = data["rotation_factor"]
    if isinstance(rotation, bool) or not isinstance(rotation, (int, float)) \
            or not ROTATION_RANGE[0] <= float(rotation) <= ROTATION_RANGE[1]:
        raise ProfileError(f"{path}: rotation_factor must be a number in {ROTATION_RANGE}, got {rotation!r}")
    takers = data.get("takers") or {}
    if not isinstance(takers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in takers.items()):
        raise ProfileError(f"{path}: takers must be a mapping of role -> player")
    expected = team_slug(data["team"])
    if path.parent.name != expected:
        raise ProfileError(f"{path}: folder {path.parent.name!r} is not the team's slug {expected!r}")
    return TeamProfile(path=path, team=data["team"], team_short=short, coach=data["coach"], module=str(data["module"]),
                       europe=data["europe"], rotation_factor=float(rotation), takers=dict(takers),
                       front_matter=front_matter)


def load_profiles(kb_dir: Path) -> list[TeamProfile]:
    """Every kb/serie-a/teams/*/profile.md, by team name; the first bad one raises."""
    profiles = [load_profile(path) for path in sorted(kb_dir.glob("serie-a/teams/*/profile.md"))]
    return sorted(profiles, key=lambda p: p.team)
```

- [ ] **Step 4: Validate profiles in `kb audit`, and add the `doctor` check**

In `core/src/fantaclaude/kb/audit.py`, inside `audit()`, replace the line `days = ttl_days(fm.ttl)` with:

```python
            days = ttl_days(fm.ttl)
            if path.name == "profile.md" and path.parent.parent.name == "teams":
                from fantaclaude.kb.profiles import ProfileError, load_profile   # audit is imported by profiles

                try:
                    load_profile(path)
                except ProfileError as exc:
                    entries.append(AuditEntry(rel, "invalid", str(exc).split(": ", 1)[-1]))
                    continue
```

In `core/src/fantaclaude/commands/doctor.py`, add `from fantaclaude.kb.profiles import ProfileError, load_profiles` to the imports and this function before `run_doctor`:

```python
def _profiles_check(kb: Path, db: Path) -> Check:
    """Every listone club has a profile, and its `europe` agrees with the fixtures."""
    try:
        profiles = load_profiles(kb)
    except ProfileError as exc:
        return Check("kb_profiles", False, str(exc))
    teams: dict[str, str] = {}
    ties: dict[str, set[str]] = {}
    if db.is_file():
        try:
            con = duckdb.connect(str(db), read_only=True)
        except duckdb.Error:
            con = None
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
            finally:
                con.close()
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
```

and append `checks.append(_profiles_check(paths.kb, paths.db))` as the last line of `run_doctor` before `return checks`.

- [ ] **Step 5: Run the tests to verify they pass, except the committed-tree one**

Run: `uv run ruff check --fix core -q; uv run pytest core/tests/test_kb_profiles.py core/tests/test_doctor.py core/tests/test_kb_audit.py -q`
Expected: everything passes except `test_committed_profiles_load` (no profiles yet) — Step 8 turns it green.

- [ ] **Step 6: Write the `fanta-kb` skill**

Create `.claude/skills/fanta-kb/SKILL.md`:

````markdown
---
name: fanta-kb
description: Build and maintain the fantaclaude knowledge base under kb/ — `bootstrap` writes the rules documents and one profile per Serie A club, `refresh` renews what `fantaclaude kb audit` reports as expired. Use when the knowledge base is empty, stale, or a club changed coach, module or European status.
---

# fanta-kb

The knowledge base holds opinionated prose with provenance; DuckDB holds the
numbers. Every document starts with the front-matter `fantaclaude kb audit`
checks (`updated`, `ttl`, `confidence`, `source`), and a team profile adds the
keys `fantaclaude.kb.profiles` validates (`team`, `team_short`, `coach`,
`module`, `europe`, `rotation_factor`, `takers`). Discover the CLI with
`fantaclaude --help`; never parse a table out of prose you wrote.

Two rules, defended hard:

- **Prose never restates a number.** A profile says *why* a striker is
  first choice, not what he averaged; it links to a query
  (`fantaclaude query --sql "SELECT … FROM v_player_season WHERE …"`) or a
  `run_id`. A number in prose is a claim that will be wrong by November and
  nothing will catch it.
- **State what you do not know.** `confidence: low` and a short "Watch"
  section beat a confident guess; the weekly manager refuses to lean on an
  expired or low-confidence profile, which is the behaviour we want.

## Modes

### `bootstrap`

Run once, on an empty tree (Phase 0b), or to add a promoted club.

1. `fantaclaude doctor` — the listone and the calendar must be ingested; the
   `kb_profiles` check lists the clubs that still need a profile.
2. `fantaclaude query --sql "SELECT name, short FROM v_teams_current ORDER BY name" --json`
   — the clubs, spelled as the listone spells them. Never invent a club.
3. `fantaclaude query --sql "SELECT team_short, competition, count(*) AS ties FROM v_european_ties GROUP BY 1, 2" --json`
   — who plays in Europe, from the fixtures, which is what `europe:` must agree with.
4. Write `kb/rules/mantra.md` from the official regolamento
   (`https://www.fantacalcio.it/regolamenti/sistema-mantra`): the twelve
   roles and what each means on the pitch, how modules constrain the eleven,
   adaptation and the forced-substitution rule, in prose; the module table
   itself lives in `core/src/fantaclaude/model/modules.yml` and is linked,
   not copied. `ttl: never`, `source:` the URL, `confidence: high`.
5. Write `kb/rules/house-rules.md`: this league's deviations and the admin's
   verbal rules — read `league.yml` (every key carries its source) and link
   `fantaclaude query --sql "SELECT * FROM v_league_settings_current"` for
   the numbers. `ttl: 30d`, `source: admin, league.yml`.
6. For every club, research on the web (the club's site, Transfermarkt for
   the squad, two Italian outlets for the coach's habits) and write
   `kb/serie-a/teams/<slug>/profile.md` from the template below, where
   `<slug>` is `fantaclaude.kb.profiles.team_slug(name)` — lower-case ASCII,
   words joined by `-`. `team` and `team_short` are copied from step 2;
   `europe` from step 3 (`none` when the club has no ties); `rotation_factor`
   starts at `1.0` for a club without Europe, `0.9` with Champions League,
   `0.85` with Europa or Conference League, then moves for the coach (a
   rotator lower, a fixed-eleven coach higher) and squad depth — and the
   "Rotation" section says why. `ttl: 14d`, `confidence: medium` when two
   sources agree, `low` otherwise.
7. `fantaclaude kb audit` must report 0 invalid; `fantaclaude doctor` must
   report `kb_profiles` ok. Commit the tree once.

### `refresh`

1. `fantaclaude kb audit --json` — the expired and invalid documents.
2. For each expired profile: re-research only what can have changed (coach,
   module, injuries that alter the pecking order, European status after a
   draw or an exit), rewrite the affected sections, bump `updated`, keep the
   rest. For an invalid one: fix the front-matter; the audit message names
   the key.
3. Never lower `ttl` to silence the audit; never touch `kb/league/season-*/`
   (the journal is append-only) or `kb/rules/aliases.yml` (that file belongs
   to ingestion).

### `interview` — Phase 1

Opponent dossiers under `kb/league/participants/` are elicited conversationally in Phase 1; this skill does not write them yet.

## Profile template

```markdown
---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: inter.it, transfermarkt.it, gazzetta.it (2026-08-29)"
team: Inter
team_short: INT
coach: <name>
module: 3-5-2
europe: UCL
rotation_factor: 0.9
takers:
  penalties: <player>
  corners: <player>
  free_kicks: <player>
---

# Inter — 2026-27

## Tactics
Two to five sentences: the module, the style, who is untouchable and who is
cover. No statistics — the reader can query them.

## Rotation
Why `rotation_factor` is what it is: the competition, the coach's habit,
the depth behind the starters. Name the players who lose minutes to Europe.

## Set pieces
The takers and the contested ones ("takes penalties unless X is on the pitch").

## Watch
What would change this profile — an injury, a signing, a coach on the brink.
```

## Worked example

**Ask:** "bootstrap the knowledge base".

**Good answer:** runs `doctor`, lists the 20 clubs from `v_teams_current`,
reads the European ties, writes `mantra.md` and `house-rules.md`, then
twenty profiles; for Atalanta it writes `europe: UECL`, `rotation_factor:
0.8` ("Conference League Thursdays plus a coach who rotates the front three
on principle; the back line and the keeper play everything") and lists the
penalty taker with the caveat that a January signing may take over; ends
with `kb audit` → 0 invalid and `doctor` → `kb_profiles ok`, and one commit.

**Bad answer:** a profile that says "Lookman averaged 7.1 last season" (a
number, unqueryable, soon wrong), `europe: Europa` (not a valid label —
`kb audit` would have said so), or a `rotation_factor` with no "Rotation"
section explaining it.
````

- [ ] **Step 7: Update `kb/README.md` and `.gitignore`**

In `kb/README.md`, replace the tree block's `serie-a/teams/<team>/` lines with:

```
├── serie-a/teams/<slug>/      # profile.md: front-matter (team, team_short, coach, module, europe,
│   │                          #   rotation_factor, takers) read by fantaclaude.kb.profiles; prose for the model
│   └── players/<name>.md      # sparse: only where prose changes a decision
```

and replace the last paragraph (`fanta-kb bootstrap (Phase 0b) fills this tree; fanta-kb refresh renews it.`) with: `` `/fanta-kb bootstrap` fills this tree and `/fanta-kb refresh` renews it (`.claude/skills/fanta-kb/SKILL.md`). A profile's `europe` must agree with `v_european_ties`; `fantaclaude doctor` says when it does not. ``

Append `.claude/settings.local.json` to `.gitignore`.

- [ ] **Step 8: Run the bootstrap**

Invoke the skill: `/fanta-kb bootstrap`. This is research and writing, not code — twenty profiles from the web plus the two rules documents — and it ends with:

Run: `uv run fantaclaude kb audit && uv run fantaclaude doctor`
Expected: `kb audit` lists 22 documents, 0 expired, 0 invalid, 0 without front-matter; `doctor` reports `kb_profiles` ok (`20/20 teams profiled; europe agrees with the fixtures`). If `fixtures` is still not ok because a European draw has not happened yet, `europe:` follows the fixtures that exist and the profile's "Watch" section says the draw is pending.

- [ ] **Step 9: Run the whole suite and lint, then commit**

Run: `uv run poe test-core && uv run ruff check core`
Expected: 170 passed (157 + 13 in `test_kb_profiles.py`, `test_committed_profiles_load` now green); ruff clean.

```bash
git add core/src/fantaclaude/kb/profiles.py core/src/fantaclaude/kb/audit.py core/src/fantaclaude/commands/doctor.py core/tests/test_kb_profiles.py core/tests/test_doctor.py core/tests/test_kb_audit.py .claude/skills/fanta-kb/SKILL.md kb/README.md kb/rules/mantra.md kb/rules/house-rules.md kb/serie-a/teams .gitignore
git commit -m "feat(kb): team profiles with validated front-matter, the fanta-kb skill, and the bootstrapped knowledge base"
```

---

## Self-Review

**Spec coverage, Phase 0b row and the sections it draws on:**

| spec requirement | task |
| --- | --- |
| "website-session discovery, then `stats_web`" — the website login is a different session from the league API's; one more credential in `.env` | 6 (discovery, by the account holder, no login code), 2 (`web_cookie`), 7 (the adapter) |
| `stats_web`: `player_season` and `player_match` from the voti XLSX; base voto plus event counts, never a stored fantavoto | 7 (`player_match`), 1 (`v_player_season`, `v_player_form`) |
| "`player_season` is the Phase 0 deliverable … `player_match` is the stretch" — with one workbook per giornata the giornata level is the cheap one, so `player_season` is derived from it rather than ingested separately | 1, 7 |
| `advanced`: FBref / Understat xG, xA, minutes per 90 | 4 (Understat; FBref is not used — one source, and Understat's endpoint is the one that answers a polite client) |
| `calendar`: Serie A fixtures plus European midweek ties per team, snapshotted not overwritten | 5 |
| Every adapter: `fetch()` writes an immutable dated raw file, `load()` returns rows matching a declared schema, every row carries `source` and `ingested_at` (`fetched_at`), `ingest all` idempotent, rebuildable from raw | 2, 4, 5, 7, 8 |
| Name matching: `player_aliases` backed by human-editable `kb/rules/aliases.yml`; unmatched rows flagged loudly, never dropped | 3, 4 (the alias file is the override; the DuckDB `player_aliases` table stays for a later importer — `advanced_stats.match_status`/`candidates` carry the flags) |
| Switchover protocol for a second source of the same data | not needed: no source is replaced in this phase; the voti page (public, Task 6 note) is recorded as the fallback for the XLSX, to be diffed against it if ever switched |
| Schema: Reference `fixtures` (incl. European ties), Observed `player_season`, `player_match`, `advanced_stats` | 1 |
| DuckDB extensions verified ahead of time; nothing downloaded on the night | 8 (`doctor` keeps the `extensions` check; no new extension is used — openpyxl reads the workbooks) |
| Testing: ingestion golden files against committed samples; a renamed column is a red test | 4, 5, 7 (`AdvancedShapeError`, `CalendarShapeError`, `VotiShapeError` on header drift) |
| Testing: no test touches the network; `respx` for HTTP | every task |
| Knowledge base: four trees, front-matter contract, `rotation_factor` in the team profile front-matter, sparse player notes, `fanta-kb bootstrap` / `refresh` | 9 (`interview` is Phase 1, as the phasing table says) |
| "Prose never restates a number" | 9 (the skill's first rule; the profile template links queries) |
| The skill ↔ Python contract: `--help`, `--json`, typed arguments, real exit codes, importable commands | 4, 5, 7, 8 |
| `fantaclaude doctor` grows with the spine | 8, 9 |
| Politeness toward external hosts: "aggressive caching, dated raw files, polite intervals, and no fetching during the auction" | 2 (`POLITE_DELAY_SECONDS`, no retries), 8 (CLAUDE.md rule) |
| Secrets: never in fixtures, tests or git; email addresses never reach a tool result | 2 (`cookie` in the secret scan), 6 (the cookie is pasted, never printed), 8 (`doctor` says "set") |

**Deliberately not in this plan** (each named in the spec as a later phase or a different concern): the fantavoto scoring function and the projection (Phase 1 — `v_player_season` and `advanced_stats` are its inputs; which voto source the league scores with is read from `league_settings` there); `results` (scores per fixture) and the post-giornata calibration (Phase 3 — `fixtures` stores the schedule only); the `news` adapter (Phase 3); `rosters_api` (open question 9); `fanta-kb interview` and opponent dossiers (Phase 1); `kb move-player` (there are still no player notes to move — the bootstrap writes team profiles only); `records/` exports (Phase 1, with `valuations`); FBref as a second `advanced` source (one source suffices, and a second one would need the switchover protocol).

**Assumptions stated where the plan had to choose:** the workbook layout in Task 7 (`VOTI_HEADER`, the senza-voto spellings, the club-row shape) is the expected one, corrected from Task 6's observation before Task 7 runs; the voti HTML page being public (observed 2026-08-28) is recorded, not adopted — the spec's XLSX decision stands; the 2026-27 UEFA league phases were not drawn on 2026-08-28, so the first live `ingest calendar` may record empty UEFA snapshots and a later run appends the schedule; `doctor`'s `fixtures` check keys on the Serie A calendar, which always exists.

**Placeholder scan:** no `TBD`, `TODO`, "implement later", "add validation", "handle edge cases", "similar to Task N"; every code step carries its code, and the one step that is not code (Task 9, Step 8, the bootstrap research) names its inputs, its template, and the two commands that prove it done. Task 6's Step 4 tells the executor exactly which constants to reconcile in Task 7 and where.

**Type consistency:** `RawStore.write(kind, payload, *, label=None, fetched_at=None)` / `write_bytes(kind, data, *, ext, label=None, fetched_at=None)` / `list(kind, *, ext="json", label=None)`; `fetch_bytes(http, url, *, method, headers, params, data)`; `Matcher(candidates, aliases).match(name, teams)`; `resolve_team(name, teams, aliases)`; `Aliases.players_for/teams_for`; `record_advanced(con, season_id, rows, raw, *, candidates, teams, aliases)`; `record_fixtures(con, competition, season_id, rows, raws, *, teams, team_aliases)`; `record_voti(con, season_id, giornata, workbook, raw, *, known_ids)`; `fetch_voti_range(http, store, *, cookie, season_id, giornate, existing, refetch)`; `current_season_id(path)`, `default_seasons(*, back, path)`, `existing_giornate(path, seasons)`; `fetch_everything(api, http, store, *, seasons, cookie, existing_voti, league)` / `record_everything(con, fetched, aliases_path)`; `run_doctor(paths, *, now)` returning the seventeen `NAMES`; `load_profile(path)` / `load_profiles(kb_dir)` — used with the same names and signatures in every task that touches them. The `SEASON_OPTION` / `COMPETITION_OPTION` / `GIORNATA_OPTION` singletons are defined once (Tasks 4, 5, 7) and shared.

**Dry run:** every code block of Tasks 1–5 and 7–9 was placed into the tree from this document by a script on 2026-08-28, ruff-fixed and run (Task 7 against a synthetic workbook in the assumed layout, since the real capture is Task 6's): all tests pass except `test_committed_profiles_load`, which the bootstrap in Task 9 turns green. The per-task counts in the "Expected" lines are the measured ones.
