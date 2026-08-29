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


def _mock_web_except_advanced(fixture_json, sample_xlsx):
    """Every _mock_web route except Understat -- for a test that mocks the
    advanced route itself, so as not to register it twice."""
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
def test_cli_ingest_all_records_everything_else_when_the_cookie_is_rejected(monkeypatch, tmp_path, fixture_json,
                                                                            mcp_fixture_json, fixture_file, fake_api,
                                                                            no_pause):
    """Finding F1: fetch_voti_range raises WebSessionExpired, not NotPublished,
    for a rejected cookie -- it must not propagate out of fetch_everything and
    abort before record_everything runs. The listone, advanced and calendar
    have already been fetched by the time stats_web is attempted (it goes
    last) and have no on-disk recovery path of their own, unlike voti's raw
    store (Ruling R8b) -- so losing them to an aborted run is exactly the
    hazard the brief's "after the other sources are already recorded" rules
    out."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.setenv("FANTACALCIO_WEB_COOKIE", COOKIE)
    _seed(tmp_path, fixture_json, mcp_fixture_json)
    _mock_web(fixture_json, fixture_file("voti_sample.xlsx").read_bytes())
    respx.get(url__regex=r".*/api/v1/Excel/votes/(?P<s>\d+)/(?P<g>\d+)$").mock(return_value=httpx.Response(401))
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: __import__("asyncio").run(fn(api)))

    result = CliRunner().invoke(app, ["ingest", "all", "--json"])
    assert result.exit_code == ExitCode.NOT_READY, result.output
    payload = json.loads(result.stdout)
    assert payload["stats_web"] is None
    assert len(payload["skipped"]) == 1 and "website session rejected" in payload["skipped"][0]
    assert payload["listone"]["skipped_duplicate"] is True                        # still recorded
    assert [r["season_id"] for r in payload["advanced"]] == [18, 19, 20, 21]       # still recorded
    assert {r["competition"] for r in payload["calendar"]} == {"SA", "UCL", "UEL", "UECL"}   # still recorded


@respx.mock
def test_cli_ingest_all_records_everything_else_when_a_voti_workbook_is_malformed(monkeypatch, tmp_path, fixture_json,
                                                                                  mcp_fixture_json, fixture_file,
                                                                                  fake_api, no_pause):
    """Items 1 and 2 of the fix wave both add new VotiShapeError raise paths
    (an appended column, a missing club row) to fetch_voti -- reachable from
    fetch_everything the same way a rejected cookie already was (Finding
    F1). Before this fix, a VotiShapeError escaped fetch_everything entirely,
    so record_everything never ran and the already-fetched listone, advanced
    and calendar payloads were discarded -- fixing Items 1 and 2 without
    this would be a net regression."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.setenv("FANTACALCIO_WEB_COOKIE", COOKIE)
    _seed(tmp_path, fixture_json, mcp_fixture_json)
    _mock_web(fixture_json, fixture_file("voti_sample.xlsx").read_bytes())
    respx.get(url__regex=r".*/api/v1/Excel/votes/(?P<s>\d+)/(?P<g>\d+)$").mock(
        return_value=httpx.Response(200, content=b"garbage, not an xlsx and not html either"))
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: __import__("asyncio").run(fn(api)))

    result = CliRunner().invoke(app, ["ingest", "all", "--json"])
    assert result.exit_code == ExitCode.NOT_READY, result.output
    payload = json.loads(result.stdout)
    assert payload["stats_web"] is None
    assert len(payload["skipped"]) == 1 and "not an xlsx" in payload["skipped"][0]
    assert payload["listone"]["skipped_duplicate"] is True                        # still recorded
    assert [r["season_id"] for r in payload["advanced"]] == [18, 19, 20, 21]       # still recorded
    assert {r["competition"] for r in payload["calendar"]} == {"SA", "UCL", "UEL", "UECL"}   # still recorded


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
    recorded = record_everything(db, RawStore(tmp_path / "raw"), fetched, aliases)
    assert recorded["listone"]["skipped_duplicate"] and recorded["stats_web"] is None
    assert db.execute("SELECT count(*) FROM v_advanced_current").fetchone()[0] == 20
    assert db.execute("SELECT count(*) FROM v_fixtures_current WHERE competition = 'SA'").fetchone()[0] == 114


V1_TABLES = ("player_match", "voti_files", "advanced_stats", "advanced_snapshots", "fixtures", "fixture_snapshots")
V1_VIEWS = ("v_voti_files_current", "v_player_match_current", "v_player_season", "v_player_form",
           "v_advanced_current", "v_advanced_unmatched", "v_fixtures_current", "v_european_ties")


def _downgrade_to_v1(con):
    """Turn a freshly-migrated v2 database back into a Phase 0a (v1) one -- the
    same recipe test_schema.py's test_a_version_1_file_is_migrated_forward_in_place
    uses to build its synthetic v1 state."""
    for view in V1_VIEWS:
        con.execute(f"DROP VIEW {view}")
    for table in V1_TABLES:
        con.execute(f"DROP TABLE {table}")
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version (version) VALUES (1)")


@respx.mock
def test_cli_ingest_all_migrates_a_stale_v1_database(monkeypatch, tmp_path, fixture_json, mcp_fixture_json,
                                                     fixture_file, fake_api, no_pause):
    """Ruling R7 / Finding F4: apply_schema only ever ran on the write
    connection each ingest command opens after its fetch. A database left at
    schema 1 (this phase's live one, before Task 1's migration ever ran
    against it) made the very first read-only pre-read crash with a
    CatalogException, before any network call. ensure_schema() must migrate
    the database forward before that pre-read runs.

    Finding F4: asserting the final schema version, after the whole command
    has run, does not bind to ensure_schema() -- Ruling R8b independently
    removed the only v2-table read from the pre-fetch path, and the
    post-fetch apply_schema (inside record_everything) migrates the file
    regardless, so this test passed even with ensure_schema() disabled. This
    version checks the schema version *from inside the first network
    request* instead, before fetch_everything has done anything else that
    could migrate it -- the only point that actually distinguishes
    ensure_schema() running from not."""
    from fantaclaude.db.connection import connect

    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.setenv("FANTACALCIO_WEB_COOKIE", COOKIE)
    _seed(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    _downgrade_to_v1(con)
    con.close()

    seen_versions = []

    def _check_schema_then_answer(request):
        probe = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
        try:
            seen_versions.append(probe.execute("SELECT max(version) FROM schema_version").fetchone()[0])
        finally:
            probe.close()
        return httpx.Response(200, json=fixture_json("understat_sample")["payload"])

    # advanced is the first source fetch_everything reaches that makes a real
    # HTTP request (listone goes through the FakeAPI, not respx) -- mocking
    # its first call this way observes the schema exactly where ensure_schema()
    # is the only thing that could have already migrated it.
    respx.post(UNDERSTAT_URL).mock(side_effect=_check_schema_then_answer)
    _mock_web_except_advanced(fixture_json, fixture_file("voti_sample.xlsx").read_bytes())
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: __import__("asyncio").run(fn(api)))

    result = CliRunner().invoke(app, ["ingest", "all", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    assert seen_versions[0] == 2          # already migrated by the time the first network request lands
    payload = json.loads(result.stdout)
    assert [(f["season_id"], f["giornata"]) for f in payload["stats_web"]["files"]] == [(18, 1), (19, 1), (20, 1), (21, 1)]

    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 2
    con.close()


@respx.mock
def test_cli_ingest_all_recovers_a_fetch_succeeded_record_failed_run_without_redownloading(
        monkeypatch, tmp_path, fixture_json, mcp_fixture_json, fixture_file, fake_api, no_pause):
    """Ruling R8b: existing_giornate must decide what to (re-)fetch from the
    raw store, not the database, and record_voti_files must record every
    on-disk workbook for the requested range, not only what this run
    downloaded. Otherwise a run that fetches successfully and then fails to
    record -- exactly what happened against the live database when the
    calendar step raised after stats_web had already been fetched -- is
    recoverable only by re-downloading every workbook: 117 authenticated
    requests against a real account for files already held."""
    from fantaclaude.db.connection import connect

    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.setenv("FANTACALCIO_WEB_COOKIE", COOKIE)
    _seed(tmp_path, fixture_json, mcp_fixture_json)
    _mock_web(fixture_json, fixture_file("voti_sample.xlsx").read_bytes())
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: __import__("asyncio").run(fn(api)))

    def voti_calls():
        return [str(c.request.url) for c in respx.calls if re.search(r"votes/\d+/\d+", str(c.request.url))]

    def giornata1_calls():
        return [u for u in voti_calls() if re.search(r"votes/\d+/1$", u)]

    first = CliRunner().invoke(app, ["ingest", "all", "--json"])
    assert first.exit_code == ExitCode.OK, first.output
    # 2 requests per season: giornata 1 (200, downloaded and stored) then
    # giornata 2 (404 -- Ruling R4 stops there, and nothing is stored for it).
    assert len(voti_calls()) == 8 and len(giornata1_calls()) == 4

    # Simulate "fetched but failed to record": the workbooks are on disk (the
    # fetch already happened), but nothing about them is in the database yet.
    con = connect(tmp_path / "data" / "fanta.duckdb")
    con.execute("DELETE FROM player_match")
    con.execute("DELETE FROM voti_files")
    con.close()
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM voti_files").fetchone()[0] == 0
    con.close()

    again = CliRunner().invoke(app, ["ingest", "all", "--json"])
    assert again.exit_code == ExitCode.OK, again.output
    # The giornata-1 workbooks are already on disk: zero new downloads of
    # them. Giornata 2 was never stored (it was never published), so
    # re-probing it every run is correct and expected -- not a regression.
    assert len(giornata1_calls()) == 4
    assert len(voti_calls()) == 12
    payload = json.loads(again.stdout)
    assert [(f["season_id"], f["giornata"]) for f in payload["stats_web"]["files"]] == [(18, 1), (19, 1), (20, 1), (21, 1)]

    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM voti_files").fetchone()[0] == 4
    con.close()
