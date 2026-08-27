import time

import httpx
import respx
from conftest import make_jwt
from fantaclaude.api_client import run_with_api

BASE = "https://apileague.fantacalcio.it"


def test_run_with_api_builds_a_client_from_the_workspace_env(monkeypatch, tmp_path, mcp_fixture_json):
    for var in ("FANTACALCIO_USERNAME", "FANTACALCIO_PASSWORD", "FANTACALCIO_LEAGUE_TOKEN",
                "FANTACALCIO_APP_KEY", "FANTACALCIO_API_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    token = make_jwt(user_id="10426252", l_id="2578630", t_id="11560832", role="user_league",
                     exp=int(time.time()) + 31_536_000)
    (tmp_path / ".env").write_text(f"FANTACALCIO_APP_KEY=K\nFANTACALCIO_LEAGUE_TOKEN={token}\n")
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/market/v1/time").mock(
            return_value=httpx.Response(200, json=mcp_fixture_json("server_time")))
        payload = run_with_api(lambda api: api.server_time())
    assert route.called
    assert route.calls[0].request.headers["app_key"] == "K"
    assert payload == mcp_fixture_json("server_time")
