import json
from pathlib import Path

import httpx
import pytest
import respx
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import (
    NotReady,
    current_season_id,
    default_seasons,
    fetch_advanced_seasons,
)
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


def test_record_advanced_force_re_matches_the_same_file(db, tmp_path, fixture_json):
    """Ruling R11: record_advanced's sha256 short-circuit means a later
    alias never gets a chance to re-match the same raw content -- force=True
    (ingest advanced --rematch's mechanism) must skip it and re-derive the
    match, and a plain re-record (force=False, the default) must stay a
    no-op even after that -- it dedupes on the same sha256 either way.

    advanced_snapshots.sha256 is UNIQUE, so a forced re-match cannot append
    a second snapshot for identical content (a real DB constraint, not just
    the Python-level short-circuit) -- it re-derives the *same* snapshot_id's
    matched/ambiguous/unmatched counts and advanced_stats rows in place. The
    raw file's own identity (snapshot_id, sha256, fetched_at, raw_path) does
    not change; only the join onto the listone does."""
    _listone(db, tmp_path, fixture_json)
    store = RawStore(tmp_path / "raw")
    raw = store.write("advanced", fixture_json("understat_sample"), label="20")
    season_id, rows = load_advanced(raw.path)
    no_alias = Aliases()
    first = record_advanced(db, season_id, rows, raw, candidates=load_candidates(db),
                            teams=load_teams(db), aliases=no_alias)
    assert first.snapshot_id == 1 and not first.skipped_duplicate
    assert db.execute("SELECT player_id FROM v_advanced_current WHERE player_name = 'Josep Martínez'").fetchone()[0] is None

    still_a_noop = record_advanced(db, season_id, rows, raw, candidates=load_candidates(db),
                                   teams=load_teams(db), aliases=no_alias, force=False)
    assert still_a_noop.skipped_duplicate and still_a_noop.snapshot_id == 1
    assert db.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 1

    # An alias added *after* the first recording: force=True is the only way
    # to make it apply to the same, already-recorded raw file.
    aliased = Aliases(players={"understat": {"Josep Martínez": 2764}})
    forced = record_advanced(db, season_id, rows, raw, candidates=load_candidates(db),
                             teams=load_teams(db), aliases=aliased, force=True)
    assert not forced.skipped_duplicate and forced.snapshot_id == 1            # same snapshot, re-derived in place
    assert forced.alias == 1                                                   # the one alias added above
    assert db.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 1   # not a new row: UNIQUE(sha256)
    assert db.execute("SELECT count(*) FROM advanced_stats").fetchone()[0] == 10      # replaced in place, not appended
    current = db.execute(
        "SELECT player_id, match_status FROM v_advanced_current WHERE player_name = 'Josep Martínez'").fetchone()
    assert current == (2764, "alias")


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


@respx.mock
def test_cli_ingest_advanced_rematch_re_derives_without_any_network_call(monkeypatch, tmp_path, fixture_json,
                                                                        mcp_fixture_json):
    """Ruling R11: --rematch must apply a newly-added alias to a season's
    raw file already on disk, with zero network -- this is the plan's Step 8
    recovery ("add an understat: alias and re-run ingest advanced once")
    actually working, including for a back season whose Understat content
    will never change again on its own."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    aliases_file = tmp_path / "kb" / "rules" / "aliases.yml"
    aliases_file.parent.mkdir(parents=True)
    aliases_file.write_text("understat: {}\nunderstat_teams:\n  AC Milan: Milan\n")
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    _listone(con, tmp_path, fixture_json)
    _league(con, mcp_fixture_json)
    con.close()
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture_json("understat_sample")["payload"]))

    async def no_pause(seconds=None):
        pass

    monkeypatch.setattr("fantaclaude.commands.ingest.polite_pause", no_pause)
    first = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20", "--json"])
    assert first.exit_code == ExitCode.OK, first.output
    before = json.loads(first.stdout)["advanced"][0]
    assert before["ambiguous"] == 1 and before["alias"] == 0                  # Josep Martínez: no alias yet
    assert route.call_count == 1

    # The alias is added *after* the season is already recorded -- the
    # scenario the plan's Step 8 recovery describes.
    aliases_file.write_text("understat:\n  Josep Martínez: 2764\nunderstat_teams:\n  AC Milan: Milan\n")

    result = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20", "--rematch", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    assert route.call_count == 1                                              # zero new network calls
    after = json.loads(result.stdout)["advanced"][0]
    assert after["ambiguous"] == 0 and after["alias"] == 1 and after["skipped_duplicate"] is False
    assert after["snapshot_id"] == before["snapshot_id"]                       # re-derived in place, not a new one

    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    assert con.execute("SELECT count(*) FROM advanced_snapshots").fetchone()[0] == 1
    current = con.execute(
        "SELECT player_id, match_status FROM v_advanced_current WHERE player_name = 'Josep Martínez'").fetchone()
    assert current == (2764, "alias")
    con.close()


def test_cli_ingest_advanced_rematch_without_a_raw_file_is_not_ready(monkeypatch, tmp_path, fixture_json,
                                                                     mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    (tmp_path / "kb" / "rules").mkdir(parents=True)
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("understat: {}\n")
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    _listone(con, tmp_path, fixture_json)
    _league(con, mcp_fixture_json)
    con.close()
    result = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20", "--rematch"])
    assert result.exit_code == ExitCode.NOT_READY and "no advanced/20 raw file" in result.stderr


def test_cli_ingest_advanced_rematch_creates_no_phantom_database(monkeypatch, tmp_path):
    """Regression: the --rematch branch re-opened Finding F2's phantom
    database -- connect() there is read-write and creates the file before
    rematch_advanced_seasons ever gets a chance to raise NotReady for a
    workspace that has no database (and so no season to rematch) at all."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20", "--rematch"])
    assert result.exit_code == ExitCode.NOT_READY, result.output
    assert not (tmp_path / "data" / "fanta.duckdb").exists(), "phantom database created"


def test_cli_ingest_advanced_rematch_wraps_a_malformed_aliases_file(monkeypatch, tmp_path, fixture_json,
                                                                    mcp_fixture_json):
    """Regression: --rematch ran outside _source_errors(), so a malformed
    kb/rules/aliases.yml (AliasError, a ValueError) escaped as a traceback
    instead of the exit-1 "source shape unexpected" message every other
    command gives it -- and hand-editing that file is the only reason to
    run --rematch."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    (tmp_path / "kb" / "rules").mkdir(parents=True)
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("understat: {}\n")
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.raw import RawStore

    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    _listone(con, tmp_path, fixture_json)
    _league(con, mcp_fixture_json)
    con.close()
    RawStore(tmp_path / "data" / "raw").write(
        "advanced", {"season_id": 20, "understat_season": 2025, "payload": fixture_json("understat_sample")["payload"]},
        label="20")
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("understat: [1, 2]\n")     # valid YAML, but not a mapping -> AliasError

    result = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20", "--rematch"])
    assert result.exit_code == ExitCode.ERROR, result.output
    assert "source shape unexpected" in result.stderr and "understat must be a mapping" in result.stderr
    assert (tmp_path / "data" / "fanta.duckdb").is_file()             # the already-seeded db is untouched, not phantom


def test_cli_ingest_advanced_without_a_database_is_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["ingest", "advanced"])
    assert result.exit_code == ExitCode.NOT_READY and "sync-league" in result.stderr
    assert not (tmp_path / "data" / "fanta.duckdb").exists()


@respx.mock
def test_cli_ingest_advanced_with_explicit_season_creates_no_phantom_database(monkeypatch, tmp_path):
    """Finding F2: --season bypasses _seasons_or_exit's database check --
    it short-circuits to list(season) without ever calling current_season_id,
    so ensure_schema() is the only thing standing between a fresh workspace
    and a phantom database. connect(path) read-write creates the file; if
    ensure_schema() called it unconditionally, a failed fetch here would
    leave a fully-schema'd, empty database behind -- the same contract
    test_a_failed_ingest_leaves_no_database_behind protects for `ingest listone`."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    respx.post(URL).mock(return_value=httpx.Response(503, text="down"))
    result = CliRunner().invoke(app, ["ingest", "advanced", "--season", "20"])
    assert result.exit_code == ExitCode.ERROR, result.output
    assert not (tmp_path / "data" / "fanta.duckdb").exists(), "phantom database created"
