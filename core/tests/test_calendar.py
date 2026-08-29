import asyncio
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
    MAX_UEFA_PAGES,
    SERIE_A_URL,
    UEFA_PAGE,
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
TWO_GIORNATE_SAMPLE = (FIXTURE_DIR / "calendario_two_giornate_sample.html").read_text(encoding="utf-8")
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


def test_load_uefa_fails_loud_on_a_null_matchday_or_round(tmp_path, fixture_json):
    """Finding F2: UEFA_REQUIRED checks key *presence*, not that the value is
    a mapping, while `match["matchday"].get("name")` and
    `match["round"].get("phase")` were unguarded (unlike `kickOffTime` two
    lines above, which already does `(match.get("kickOffTime") or {})`). A
    null value raised AttributeError, not CalendarShapeError, and unmapped
    by cli/app.py's _source_errors. No evidence UEFA's feed actually emits
    this: all 1,284 matches in data/raw/calendar/*.json carry non-null
    values for both -- this is defensive hardening for an inconsistency,
    not a fix for an observed failure."""
    pages = fixture_json("uefa_sample")
    match_id = pages[0]["matches"][0]["id"]
    pages[0]["matches"][0]["matchday"] = None
    path = tmp_path / "null_matchday.json"
    path.write_text(json.dumps(pages))
    with pytest.raises(CalendarShapeError, match=str(match_id)):
        load_uefa([path])

    pages = fixture_json("uefa_sample")
    pages[0]["matches"][0]["round"] = None
    path2 = tmp_path / "null_round.json"
    path2.write_text(json.dumps(pages))
    with pytest.raises(CalendarShapeError, match=str(match_id)):
        load_uefa([path2])


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


def test_load_serie_a_filters_a_page_that_advertises_the_next_giornata(tmp_path):
    """Ruling R8a: a played giornata's page also shows the next one -- ten
    giornata-1 matches and ten giornata-2 preview pills on the same real page
    (observed 2026-08-29, captured/calendario-2026-27-giornata-1.html).
    load_serie_a must keep only the giornata the page was fetched for, taken
    from the raw file's own label, not "the one giornata on the page"."""
    store = RawStore(tmp_path / "raw")
    raw = store.write_bytes("calendar", TWO_GIORNATE_SAMPLE.encode(), ext="html", label="sa-21-01")
    rows = load_serie_a([raw.path], season_id=21)
    assert {r.giornata for r in rows} == {1} and {r.source_id for r in rows} == {"17955", "17956"}


def test_load_serie_a_fails_loud_when_the_page_lacks_its_own_giornata(tmp_path):
    store = RawStore(tmp_path / "raw")
    raw = store.write_bytes("calendar", TWO_GIORNATE_SAMPLE.encode(), ext="html", label="sa-21-05")
    with pytest.raises(CalendarShapeError, match="giornata 5 is not on its own page"):
        load_serie_a([raw.path], season_id=21)
    not_labelled = store.write_bytes("calendar", TWO_GIORNATE_SAMPLE.encode(), ext="html", label="not-a-page")
    with pytest.raises(CalendarShapeError, match="not a Serie A page"):
        load_serie_a([not_labelled.path], season_id=21)


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


@respx.mock
async def test_fetch_uefa_stops_at_the_page_cap_if_the_host_never_shortens_a_page(tmp_path, no_pause):
    """CLAUDE.md: never add a loop that fetches without bound. If
    match.uefa.com ever ignores `offset` and keeps answering a full page,
    termination must not depend on it eventually doing otherwise -- capped
    at MAX_UEFA_PAGES, raising CalendarShapeError naming the competition,
    instead of writing a raw file into data/raw/calendar once a second
    forever. Every page here is a full page with ids that never repeat, so
    neither the short-page nor the same-ids terminations can fire -- only
    the cap can end the loop. Bounded with wait_for as a belt-and-braces
    guard: with the cap removed this would otherwise spin forever."""
    def full_page(request):
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json=[{"id": offset + i} for i in range(UEFA_PAGE)])

    respx.get(UEFA_URL).mock(side_effect=full_page)
    store = RawStore(tmp_path / "raw")
    async with httpx.AsyncClient() as http:
        with pytest.raises(CalendarShapeError, match="UCL"):
            await asyncio.wait_for(fetch_uefa(http, store, season_id=21, competition="UCL"), timeout=10)
    assert len(list((tmp_path / "raw" / "calendar").glob("*-ucl-*.json"))) == MAX_UEFA_PAGES


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


@respx.mock
def test_cli_ingest_calendar_dedupes_a_repeated_competition(monkeypatch, tmp_path, fixture_json, mcp_fixture_json,
                                                             no_pause):
    """Finding F7: `--competition SA --competition sa` upper-cases both to
    "SA" but did not dedupe, so `fetch_calendar` ran `fetch_serie_a` twice
    (76 requests at one per second) and, because `raws` is a dict keyed by
    competition, the first 38 raw files were orphaned on disk and never
    passed to `record_calendar`. Deduping with `dict.fromkeys` must fetch SA
    exactly once."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    _seeded(tmp_path, fixture_json, mcp_fixture_json)
    route = respx.get(url__regex=r"https://www\.fantacalcio\.it/serie-a/calendario/(?P<giornata>\d+)$").mock(
        side_effect=lambda request, giornata: httpx.Response(200, text=_page(int(giornata), renamed=True)))

    result = CliRunner().invoke(app, ["ingest", "calendar", "--competition", "SA", "--competition", "sa", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)["calendar"]
    assert [r["competition"] for r in payload] == ["SA"]                          # one entry, not two
    assert payload[0]["inserted"] == 114
    assert route.call_count == 38                                                 # not 76
    assert len(list((tmp_path / "data" / "raw" / "calendar").glob("*-sa-21-*.html"))) == 38   # none orphaned


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
