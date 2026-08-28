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
