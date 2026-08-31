import duckdb
import pytest
from fantaclaude.api.serve import AstaServer
from fantaclaude.asta.adjustments import EMPTY_LAYER
from fantaclaude.asta.mcp import build_mcp
from fantaclaude.asta.state import parse_snapshot
from fantaclaude.commands.asta import AstaPaths
from fastmcp import Client
from test_advisor import SESSION, pinned_run


def snap(picks, *, selected=None, teams=(0, 1, 2)):
    return parse_snapshot({
        "picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i}
                  for i, (pid, tid, cost) in enumerate(picks)],
        "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams],
        "settings": SESSION, "selectedPlayerId": selected, "status": "live", "locked": False})


@pytest.fixture
async def kit(tmp_path, fixture_json, mcp_fixture_json):
    _result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    db = tmp_path / "toy.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'a'), (2, 'b')) v(n, s)")
    con.close()
    paths = AstaPaths(db=db, adjustments=tmp_path / "data" / "adjustments.yml",
                      state=tmp_path / "data" / "asta-state.json", records=tmp_path / "records", kb=tmp_path / "kb")
    server = AstaServer(run=pinned, layer=EMPTY_LAYER, participants={}, scenario=None,
                        paths=paths, mode="replay", session_code="FA-nri-okm")
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    return server, pinned, build_mcp(server, db)


async def test_status_and_board_read_the_live_state(kit):
    server, pinned, mcp = kit
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)], selected=pids[1]))
    async with Client(mcp) as client:
        status = (await client.call_tool("asta_status", {})).data
        assert status["phase"] == "live" and status["picks"] == 1 and status["session_code"] == "FA-nri-okm"
        board = (await client.call_tool("asta_board", {"top": 3})).data
        assert board["me"]["credits"] == 500 and board["lot"]["player_id"] == pids[1]
        assert all(len(rows) <= 3 for rows in board["tiers"].values())
        assert "prices" not in board                       # the compact summary, never the 553-row dict


async def test_explain_names_the_trace_and_adjust_writes_through_the_one_path(kit):
    server, pinned, mcp = kit
    pids = sorted(pinned.players)
    _name = pinned.players[pids[0]].name
    async with Client(mcp) as client:
        out = (await client.call_tool("asta_explain", {"player": str(pids[0])})).data
        assert out["player"]["player_id"] == pids[0] and out["trace"]["band"]["p50"] >= 0
        adj = (await client.call_tool("asta_adjust", {"type": "exclude", "player_id": pids[0],
                                                      "reason": "the room says he is gone"})).data
        assert adj["count"] == 1 and adj["band_after"] is None
        out2 = (await client.call_tool("asta_explain", {"player": str(pids[0])})).data
        assert out2["trace"] is None and out2["adjustments"]
    assert server.paths.adjustments.is_file()


async def test_query_runs_read_only_in_a_thread_with_a_row_cap(kit):
    _server, _pinned, mcp = kit
    async with Client(mcp) as client:
        out = (await client.call_tool("asta_query", {"sql": "SELECT n, s FROM t ORDER BY n", "limit": 1})).data
        assert out["columns"] == ["n", "s"] and out["rows"] == [[1, "a"]] and out["truncated"] is True
        with pytest.raises(Exception) as err:
            await client.call_tool("asta_query", {"sql": "CREATE TABLE nope (x INT)"})
        assert "read" in str(err.value).lower() or "write" in str(err.value).lower()


async def test_tools_refuse_cleanly_while_pending(tmp_path, fixture_json, mcp_fixture_json):
    _result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    paths = AstaPaths(db=tmp_path / "toy.duckdb", adjustments=tmp_path / "a.yml",
                      state=tmp_path / "s.json", records=tmp_path / "r", kb=tmp_path / "kb")
    server = AstaServer(run=pinned, layer=EMPTY_LAYER, participants={}, scenario=None,
                        paths=paths, mode="feed", session_code="FA-x-y")
    mcp = build_mcp(server, paths.db)
    async with Client(mcp) as client:
        status = (await client.call_tool("asta_status", {})).data
        assert status["phase"] == "pending"
        with pytest.raises(Exception) as err:
            await client.call_tool("asta_board", {})
        assert "mapping" in str(err.value)
