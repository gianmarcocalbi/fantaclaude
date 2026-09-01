import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fantaclaude.api.app import create_app
from fantaclaude.api.serve import AstaServer
from fantaclaude.asta.adjustments import EMPTY_LAYER
from fantaclaude.asta.mcp import MCP_PATH
from fantaclaude.asta.state import parse_snapshot
from fantaclaude.commands.asta import AstaPaths
from starlette.testclient import TestClient
from test_advisor import SESSION, pinned_run

REPO_ROOT = Path(__file__).resolve().parents[2]


def snap(picks, *, selected=None, teams=(0, 1, 2), settings=SESSION):
    return parse_snapshot({
        "picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i}
                  for i, (pid, tid, cost) in enumerate(picks)],
        "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams],
        "settings": settings, "selectedPlayerId": selected, "status": "live", "locked": False})


@pytest.fixture
def kit(tmp_path, fixture_json, mcp_fixture_json):
    _result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    paths = AstaPaths(db=tmp_path / "data" / "fanta.duckdb", adjustments=tmp_path / "data" / "adjustments.yml",
                      state=tmp_path / "data" / "asta-state.json", records=tmp_path / "records", kb=tmp_path / "kb")
    server = AstaServer(run=pinned, layer=EMPTY_LAYER, participants={}, scenario=None,
                        paths=paths, mode="replay", session_code=None)
    return server, pinned, create_app(server)


def test_hello_then_mapping_then_board(kit):
    _server, _pinned, app = kit
    with TestClient(app) as client:
        assert client.get("/api/board").status_code == 409
        hello = client.get("/api/hello").json()
        assert hello["phase"] == "pending" and hello["run"].startswith("run ")
        answered = client.post("/api/mapping", json={"mine": 0, "nicks": {}}).json()
        assert answered["phase"] == "live"
        board = client.get("/api/board").json()
        assert board["me"]["credits"] == 500 and board["prices"]


def test_mapping_refuses_an_unknown_dossier_nick(kit):
    _server, _pinned, app = kit
    with TestClient(app) as client:
        resp = client.post("/api/mapping", json={"mine": 0, "nicks": {"1": "Nobody"}})
        assert resp.status_code == 422 and "Nobody" in resp.json()["detail"]


def test_websocket_hears_hello_then_every_mutation(kit):
    _server, pinned, app = kit
    pids = sorted(pinned.players)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "hello" and first["hello"]["phase"] == "pending"
        client.post("/api/mapping", json={"mine": 0, "nicks": {}})
        assert ws.receive_json()["hello"]["phase"] == "live"
        client.post("/api/adjust", json={"type": "exclude", "player_id": pids[0], "reason": "not buying"})
        msg = ws.receive_json()
        assert msg["type"] == "board" and str(pids[0]) not in msg["board"]["prices"]


def test_adjust_maps_the_error_classes_to_the_contract(kit):
    server, pinned, app = kit
    with TestClient(app) as client:
        pending = client.post("/api/adjust", json={"type": "exclude", "player_id": 1, "reason": "x"})
        assert pending.status_code == 409
        client.post("/api/mapping", json={"mine": 0, "nicks": {}})
        bad_input = client.post("/api/adjust", json={"type": "value", "player_id": 1, "reason": "x"})
        assert bad_input.status_code == 422            # value without factor
        inert = client.post("/api/adjust", json={"type": "exclude", "player_id": 999_999, "reason": "x"})
        assert inert.status_code == 422
        server.paths.adjustments.parent.mkdir(parents=True, exist_ok=True)
        server.paths.adjustments.write_text("]: not yaml", encoding="utf-8")
        broken_file = client.post("/api/adjust", json={"type": "exclude",
                                                       "player_id": min(pinned.players), "reason": "x"})
        assert broken_file.status_code == 400


def test_refresh_rereads_and_reports(kit):
    server, pinned, app = kit
    pids = sorted(pinned.players)
    with TestClient(app) as client:
        client.post("/api/mapping", json={"mine": 0, "nicks": {}})
        server.paths.adjustments.parent.mkdir(parents=True, exist_ok=True)
        server.paths.adjustments.write_text(f"- player_id: {pids[0]}\n  type: exclude\n  reason: hand-edit\n",
                                            encoding="utf-8")
        out = client.post("/api/refresh")
        assert out.status_code == 200 and str(pids[0]) not in out.json()["board"]["prices"]


def test_static_dist_is_served_when_built_and_a_hint_stands_in_when_not(kit, tmp_path):
    server, _pinned, _ = kit
    bare = create_app(server)
    with TestClient(bare) as client:
        resp = client.get("/")
        assert resp.status_code == 200 and "poe web-build" in resp.text
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>fantaclaude asta</title>", encoding="utf-8")
    built = create_app(server, web_dist=dist)
    with TestClient(built) as client:
        assert "fantaclaude asta" in client.get("/").text


def test_hello_maps_a_broken_session_to_400(kit):
    server, _pinned, app = kit
    # A malformed settings node reaches AstaServer.last_snapshot exactly the
    # way a real feed snapshot would (session mode's on_snapshot assigns it
    # unconditionally, before it ever tries to read it); assigning it here
    # directly is the seam that exercises the *route's* SessionError mapping
    # without re-testing AstaServer.hello() itself, which test_api_serve.py
    # already covers.
    server.last_snapshot = snap([], settings={"budget": "not-a-number", "game": 2,
                                              "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]}})
    with TestClient(app) as client:
        resp = client.get("/api/hello")
        assert resp.status_code == 400
        assert "settings.budget" in resp.json()["detail"]


def test_the_schema_dump_app_needs_no_server():
    app = create_app(None)
    schema = app.openapi()
    assert "/api/board" in schema["paths"] and "/api/adjust" in schema["paths"]
    with TestClient(app) as client:
        assert client.get("/api/hello").status_code == 503


def shipped_mcp_url() -> str:
    """The URL `.mcp.json` hands to the MCP client -- the one thing production
    actually dials."""
    config = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    return config["mcpServers"]["fantaclaude-asta"]["url"]


def test_the_shipped_mcp_url_is_the_path_the_app_serves():
    # The guard that would have caught the ship-broken URL: `.mcp.json` is
    # hand-written and the mount path is code, and nothing else compares them.
    from fantaclaude.asta.mcp import MCP_URL_PATH
    assert urlsplit(shipped_mcp_url()).path == MCP_URL_PATH


def test_the_mcp_mounts_under_the_app_and_answers(kit, tmp_path):
    # Built the way production builds it -- *with* a dashboard, whose
    # StaticFiles mount at "/" is what swallowed a bare /mcp -- and driven at
    # the path .mcp.json actually carries, not a hardcoded working one.
    server, _pinned, _ = kit
    from fantaclaude.asta.mcp import build_mcp
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>fantaclaude asta</title>", encoding="utf-8")
    mcp_app = build_mcp(server, server.paths.db).http_app(path="/", transport="http", stateless_http=True)
    app = create_app(server, web_dist=dist, mcp_app=mcp_app)
    path = urlsplit(shipped_mcp_url()).path
    with TestClient(app) as client:
        resp = client.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                           headers={"accept": "application/json, text/event-stream",
                                    "content-type": "application/json"})
        assert resp.status_code == 200, f"{path} answered {resp.status_code}: {resp.text[:200]}"
        body = resp.text
        if resp.headers["content-type"].startswith("text/event-stream"):   # one SSE frame carries the reply
            body = next(line[len("data: "):] for line in body.splitlines() if line.startswith("data: "))
        answer = json.loads(body)
        assert answer["jsonrpc"] == "2.0" and answer["id"] == 1 and answer["result"] == {}
        # and the hand-typed form still lands somewhere useful rather than on the dashboard's 404
        assert client.get(MCP_PATH, follow_redirects=False).status_code == 307


def test_openapi_dump_writes_the_document(tmp_path, monkeypatch):
    import sys

    from fantaclaude.api import openapi_dump
    out = tmp_path / "openapi.json"
    monkeypatch.setattr(sys, "argv", ["openapi_dump", "--out", str(out)])
    openapi_dump.main()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/board" in doc["paths"] and "BoardPayload" in doc["components"]["schemas"]
