import json
from datetime import UTC, datetime, timedelta

import httpx
import respx
from conftest import (
    FIXTURE_DIR,
    seed_fixtures,
    seed_matches,
    seed_news,
    seed_probabili,
    seed_rosters,
)
from fantaclaude.cli.app import ExitCode, _render_lineup, app
from fantaclaude.db.connection import connect
from test_rank_cli import _workspace
from typer.testing import CliRunner

runner = CliRunner()
SAMPLE = (FIXTURE_DIR / "probabili_sample.html").read_text(encoding="utf-8")
PAGE = [(2764, "Martinez L.", "inter", 90), (5841, "Svilar", "roma", 100), (2640, "Kolasinac", "atalanta", 55),
        (2120, "Bastoni", "inter", 90), (254, "Dimarco", "inter", 75), (2194, "Calhanoglu", "inter", 35)]


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
    # once every match of the round has started, the write needs --late; the
    # default target has by then rolled on to giornata 4 (target_round picks
    # the first giornata whose last kickoff is still ahead -- unchanged, spec
    # "the round and the deadline are read off the calendar"), so naming
    # giornata 3 explicitly is what a late write for it now takes.
    con = connect(tmp_path / "data" / "fanta.duckdb")
    seed_matches(con, 21, [(3, now - timedelta(days=3), "INT", "ROM"), (3, now - timedelta(hours=1), "ATA", "GEN"),
                           (4, now + timedelta(days=7), "MIL", "NAP")])
    con.close()
    refused = runner.invoke(app, ["lineup", "--giornata", "3"])
    assert refused.exit_code == ExitCode.CONFLICT and "--late" in refused.stderr
    late = runner.invoke(app, ["lineup", "--giornata", "3", "--late", "--json"])
    assert late.exit_code == ExitCode.OK and json.loads(late.stdout)["late_predictions"] == 3


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
    # The sample page names its own giornata (3, Task 3's meta-tag parse) -- asking to
    # record it under 4 must be refused, not silently accepted (the designed cross-check).
    plain = runner.invoke(app, ["ingest", "probabili", "--giornata", "4"])
    assert plain.exit_code == ExitCode.CONFLICT and "giornata 3" in plain.stderr


@respx.mock
def test_ingest_probabili_maps_a_changed_page_to_exit_1(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    respx.get("https://www.fantacalcio.it/probabili-formazioni-serie-a").mock(return_value=httpx.Response(200, text="<html></html>"))
    result = runner.invoke(app, ["ingest", "probabili"])
    assert result.exit_code == ExitCode.ERROR and "player-item" in result.stderr


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
    assert payload["bench"]["size"] == 12 and 1 <= len(payload["bench"]["order"]) <= 6      # 17 players, 11 fielded
    assert all(e["player_id"] not in {s["player_id"] for s in xi["slots"]} for e in payload["bench"]["order"])
    assert payload["contingencies"] == [] and isinstance(payload["close_calls"], list)      # everyone at 90%
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT my_team, module FROM lineup_runs").fetchone() == (4242, xi["module"])
    assert con.execute("SELECT bench IS NOT NULL, contingencies IS NOT NULL FROM lineup_runs").fetchone() == (True, True)
    con.close()
    plain = runner.invoke(app, ["lineup"])
    assert plain.exit_code == ExitCode.OK and f"XI: {xi['module']}" in plain.stdout
    assert "bench: " in plain.stdout


def test_lineup_with_no_bench_size_skips_ordering_without_a_false_uncovered_warning(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """When the league_settings snapshot carries no bench size, `order_bench`
    must not run at all -- calling it with `bench_size=0` empties the bench
    and then trips the `bench.uncovered` check for every slot in the module,
    a false "no coverage" warning that is really just a missing settings
    field (review finding, report.py:140)."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]     # the 17 can field 3-4-3
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone])
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone})})
    # a settings snapshot with no bench size -- e.g. the platform's own payload never named one.
    # `rules_hash` stays exactly the run's own: changing it would mark the run already pinned by
    # `_ranked` as superseded (v_valuation_runs), and `lineup` would find no run to read at all.
    con.execute("INSERT INTO league_settings (fetched_at, league_id, season_id, matchday, rules_hash, team_count, budget, "
                "roster_min, roster_max, modules, bench_size, substitutions, payload) "
                "SELECT now(), league_id, season_id, matchday, rules_hash, team_count, budget, roster_min, "
                "roster_max, modules, NULL, substitutions, payload FROM v_league_settings_current")
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["xi"] is not None and len(payload["xi"]["slots"]) == 11    # the XI itself still comes through
    assert payload["bench"] is None
    assert any("no bench ordered" in w for w in payload["warnings"])
    assert not any("bench covers no" in w for w in payload["warnings"])
    plain = runner.invoke(app, ["lineup"])
    assert plain.exit_code == ExitCode.OK and "bench: " not in plain.stdout


def test_lineup_tells_apart_not_on_the_page_from_not_priced_by_the_run(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """Two roster players are missing from the XI's forecast for two
    different reasons -- one the page never listed, one the page lists but
    the run never priced (the live case in this repo is id 795: on a lega
    roster, in no listone) -- and the warning must name each reason
    separately rather than blaming "not on the page" for both (review
    finding 4, 2026-09-04)."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]     # the 17 can field 3-4-3
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone] + [(999999, "Ghost", "club", 90)])
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone} | {999999: 5, 888888: 3})})
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    warnings = payload["warnings"]
    not_on_page = next(w for w in warnings if "not on the page" in w)
    unpriced = next(w for w in warnings if "not priced by run" in w)
    assert "1 roster player(s) not on the page" in not_on_page and "#888888" in not_on_page
    assert "1 roster player(s) on the page but not priced" in unpriced and "#999999" in unpriced
    assert "#888888" not in unpriced and "#999999" not in not_on_page


def test_an_exclude_note_keeps_a_page_absent_roster_player_off_both_lists(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """`rows` is the probabili page times the run's priced set, so a roster
    player the page doesn't list never gets a `ForecastRow`, and his own
    `excluded` flag on it never exists to read. A `lineup note --type
    exclude` for exactly that player still resolves cleanly against the
    listone (`NotesLayer.excluded`, independent of `rows`) and must still
    keep him off both the XI and the bench -- not merely appear, inert, in
    `blend.notes.excluded` while the solve fields him anyway (review
    finding, Important 1)."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]     # the 17 can field 3-4-3
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone if pid != 2097])     # Kean: the page drops him
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone})})
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    note = runner.invoke(app, ["lineup", "note", "--type", "exclude", "--player-id", "2097", "--reason", "not this week"])
    assert note.exit_code == ExitCode.OK, note.output
    result = runner.invoke(app, ["lineup", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["blend"]["notes"]["excluded"] == [2097]
    fielded = {s["player_id"] for s in payload["xi"]["slots"]}
    benched = {e["player_id"] for e in payload["bench"]["order"]}
    assert 2097 not in fielded and 2097 not in benched
    assert not any("Kean" in w for w in payload["warnings"])                  # not merely "not on the page": excluded outright


def test_render_lineup_surfaces_compilation_state_and_shortfall_near_the_header():
    """The plain-text render must let a skim top-to-bottom answer "is this
    forecast sane?" without subtracting two numbers from opposite ends of
    the output: the matches-compiled count needs a denominator (2/2 must
    not read like 2/10), and the uncompiled warning and the page/predictions
    shortfall belong near the header, the way LATE already is -- not only as
    the last line, after two absolute parquet paths (review finding 5,
    2026-09-04). This is a rendering change only: the JSON payload shape is
    untouched."""
    payload = {
        "round": {"giornata": 3, "first_kickoff": "2026-09-06 18:45"},
        "run_id": "run123",
        "page": {"fetched_at": "2026-09-04 13:46", "players": 479, "matches": 8, "uncompiled": 2},
        "late": False,
        "top": {"A": [{"name": "Lautaro", "p_start_published": 90, "fv_if_plays": 8.1, "expected_points": 7.29}]},
        "xi": None,
        "no_xi_reason": "league.yml has no my_team leaf (asta verify-transfer prints it)",
        "lineup_run_id": 42,
        "predictions": 473,
        "records": ["records/lineup_runs/x.parquet", "records/predictions/x.parquet"],
        "warnings": ["2 match(es) of giornata 3 not yet compiled on the page fetched 2026-09-04 13:46 UTC",
                    "1 roster player(s) not on the page, counted as 0: #888888"],
    }
    text = _render_lineup(payload)
    lines = text.splitlines()
    assert "(479 players, 8/10 matches compiled)" in lines[0]                          # denominated, not bare "8 compiled"
    uncompiled_idx = next(i for i, ln in enumerate(lines) if ln.startswith("UNCOMPILED:"))
    predictions_idx = next(i for i, ln in enumerate(lines) if ln.startswith("predictions:"))
    xi_idx = next(i for i, ln in enumerate(lines) if ln.startswith("XI:"))
    assert uncompiled_idx < xi_idx and predictions_idx < xi_idx                        # near the header, not after XI/written
    assert "473/479 page player(s) priced by the run (6 not priced)" in lines[predictions_idx]
    assert sum(1 for ln in lines if "not yet compiled on the page fetched" in ln) == 1  # moved, not duplicated
    assert any("1 roster player(s) not on the page" in ln for ln in lines if ln.startswith("warning:"))

    # a fully-compiled page with every listed player priced: no UNCOMPILED
    # line, and the shortfall line still shows the (now equal) denominator.
    payload["page"] = {**payload["page"], "matches": 10, "uncompiled": 0}
    payload["predictions"] = 479
    payload["warnings"] = []
    clean = _render_lineup(payload)
    assert "10/10 matches compiled" in clean and "UNCOMPILED" not in clean
    assert "predictions: 479/479 page player(s) priced by the run" in clean and "not priced" not in clean


def test_render_lineup_uncompiled_line_does_not_depend_on_the_wording_in_warnings():
    """`_render_lineup` used to locate the UNCOMPILED line by
    substring-matching a fragment of the sentence `weekly.uncompiled_
    match_warning` builds, hardcoded a second time here -- reword that
    sentence and the match silently stops firing: the line vanishes from
    its near-header position while the same information reappears,
    undeduplicated, at the bottom (review finding 10, 2026-09-04). Built
    instead from `page['uncompiled']`/`page['fetched_at']` alone, it must
    still appear correctly even when `warnings` carries a completely
    different sentence for it -- exactly what a reword, with the renderer
    not yet updated, would look like."""
    payload = {
        "round": {"giornata": 3, "first_kickoff": "2026-09-06 18:45"},
        "run_id": "run123",
        "page": {"fetched_at": "2026-09-04 13:46", "players": 479, "matches": 8, "uncompiled": 2},
        "late": False,
        "top": {},
        "xi": None,
        "no_xi_reason": "league.yml has no my_team leaf (asta verify-transfer prints it)",
        "lineup_run_id": 42,
        "predictions": 473,
        "records": [],
        "warnings": ["2 matches for giornata 3 are still awaiting team news as of 2026-09-04 13:46"],
    }
    lines = _render_lineup(payload).splitlines()
    uncompiled_line = next(ln for ln in lines if ln.startswith("UNCOMPILED:"))
    assert "2" in uncompiled_line and "giornata 3" in uncompiled_line and "2026-09-04 13:46" in uncompiled_line
    xi_idx = next(i for i, ln in enumerate(lines) if ln.startswith("XI:"))
    assert lines.index(uncompiled_line) < xi_idx                          # still near the header, not lost at the bottom


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


@respx.mock
def test_ingest_news_records_the_page_that_parsed_even_when_its_sibling_breaks(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """A shape change on one page (the site reworked its layout) must not
    cost the other: both requests are already spent by the time either page
    is parsed, and the squalificati page in particular carries entries that
    force a p_start to zero -- losing it because `infortunati` broke would
    silently field a suspended player at full price (review finding,
    cli/app.py:585)."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    respx.get("https://www.fantacalcio.it/squalificati-e-diffidati-campionato-serie-a").mock(
        return_value=httpx.Response(200, text=SUSPENSIONS))
    respx.get("https://www.fantacalcio.it/infortunati-serie-a").mock(return_value=httpx.Response(200, text="<html></html>"))
    result = runner.invoke(app, ["ingest", "news"])
    assert result.exit_code == ExitCode.ERROR, result.output
    assert "infortunati" in result.stderr and "recorded: squalificati" in result.stderr
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    kinds = {r[0] for r in con.execute("SELECT kind FROM news_files").fetchall()}
    assert kinds == {"squalificati"}                                        # the good page still landed
    con.close()


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


def test_lineup_record_needs_league_settings_and_exits_not_ready(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """A missing league_settings snapshot is missing input, not a usage
    error: `allowed=[]` used to fall through into `build_submission`'s
    'module ... not permitted' SubmissionError, mapped to exit 2, while
    `fantaclaude lineup` itself already treats the same gap as exit 3 with
    a `sync-league` pointer -- the two paths must agree (review finding,
    Minor 8)."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone])
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone})})
    # the row itself (season_id, league_id) must stay -- `_seasons_or_exit`
    # needs it to resolve the season before `lineup_record_cmd` ever gets to
    # its own read; only `modules`, what the finding is about, goes missing.
    con.execute("UPDATE league_settings SET modules = NULL")
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    # --xi/--module in full: my_roster and load_run_xi are both bypassed or
    # trivially satisfied, so the missing `modules` is the only thing left
    # to answer for -- exactly the case the finding names.
    result = runner.invoke(app, ["lineup", "record", "--module", "343", "--xi", "Kean"])
    assert result.exit_code == ExitCode.NOT_READY, result.output
    assert "no league_settings snapshot names the permitted modules" in result.stderr and "sync-league" in result.stderr


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


def test_lineup_record_refuses_swap_together_with_xi(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """`--xi` already states the full eleven; a `--swap` beside it can only be
    a mistake and must be refused rather than silently dropped (review
    finding, submitted.py:155)."""
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
    bench_names = [e["name"] for e in forecast["bench"]["order"]]
    result = runner.invoke(app, ["lineup", "record", "--module", forecast["xi"]["module"], "--xi", ",".join(xi_names),
                                "--swap", f"{xi_names[0]}={bench_names[0]}"])
    assert result.exit_code == ExitCode.USAGE, result.output
    assert "--swap is ignored with --xi" in result.stderr
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 0     # nothing recorded on refusal
    con.close()


def test_lineup_record_finds_the_run_that_named_an_xi_even_when_a_later_run_has_none(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    """`load_run_xi`'s default branch must pick the newest non-late run of
    the giornata that actually named an XI -- not merely the giornata's
    "current" run under `v_lineup_runs_current`, which already reduces to
    one row per giornata *before* `xi IS NOT NULL` is applied. A run written
    while `league_settings.modules` was momentarily empty (any ForecastError
    inside the XI-building block, not only a missing roster) leaves `xi`
    NULL on that row forever; a later, fixed run of the same giornata must
    still be found by the default selection (review finding, submitted.py:57)."""
    _ranked(monkeypatch, tmp_path, fixture_json, mcp_fixture_json)
    _calendar(tmp_path, first=datetime.now(UTC) + timedelta(days=2))
    con = connect(tmp_path / "data" / "fanta.duckdb")
    everyone = [r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()]
    seed_probabili(con, 21, 3, [(pid, f"p{pid}", "club", 90) for pid in everyone])
    seed_rosters(con, 2578630, 21, {4242: ("G8 E CLAUDIO", {pid: 10 for pid in everyone})})
    modules = con.execute("SELECT modules FROM v_league_settings_current").fetchone()[0]
    con.close()
    with open(tmp_path / "league.yml", "a", encoding="utf-8") as fh:
        fh.write("my_team: {value: 4242, source: verify-transfer, verified_on: 2026-09-04}\n")
    wednesday = json.loads(runner.invoke(app, ["lineup", "--json"]).stdout)
    assert wednesday["xi"] is not None
    # Thursday: the settings snapshot momentarily carries no permitted modules -- the XI block
    # raises ForecastError, and the run is written anyway, with xi = NULL (never late: same round).
    con = connect(tmp_path / "data" / "fanta.duckdb")
    con.execute("UPDATE league_settings SET modules = NULL")
    con.close()
    thursday = json.loads(runner.invoke(app, ["lineup", "--run", wednesday["run_id"], "--json"]).stdout)
    assert thursday["xi"] is None and "league_settings" in thursday["no_xi_reason"]
    assert thursday["lineup_run_id"] != wednesday["lineup_run_id"]
    # Fixed before the operator gets to `lineup record` -- but Thursday's already-written row keeps xi = NULL.
    con = connect(tmp_path / "data" / "fanta.duckdb")
    con.execute("UPDATE league_settings SET modules = ?", [modules])
    con.close()
    result = runner.invoke(app, ["lineup", "record", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["lineup_run_id"] == wednesday["lineup_run_id"]
