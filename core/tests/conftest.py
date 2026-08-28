import base64
import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
# The league API payload shapes are the MCP's ground truth; reuse its scrubbed
# fixtures instead of keeping a drifting second copy.
MCP_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "mcp" / "fantacalcio" / "tests" / "fixtures"


@pytest.fixture
def fixture_json():
    def _load(name: str):
        return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def mcp_fixture_json():
    def _load(name: str):
        return json.loads((MCP_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def db(tmp_path):
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "test.duckdb")
    apply_schema(con)
    yield con
    con.close()


def make_jwt(**claims) -> str:
    """An unsigned RS256-shaped JWT with the given claims (test helper, mirrors the MCP suite)."""
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.signature"


class FakeAPI:
    """The subset of FantacalcioAPI the commands call, answered from fixtures.

    `overrides` replaces a named payload; `calls` records every method name
    so a test can assert how many round-trips a command made.
    """

    def __init__(self, load, overrides=None):
        self._load = load
        self._overrides = dict(overrides or {})
        self.calls: list[str] = []

    async def _answer(self, name: str):
        self.calls.append(name)
        if name in self._overrides:
            return json.loads(json.dumps(self._overrides[name]))
        return self._load(name)

    async def league_profile(self, league=None):
        return await self._answer("league_profile")

    async def league_status(self, league=None):
        return await self._answer("league_status")

    async def roster_settings(self, league=None):
        return await self._answer("roster_settings")

    async def lineup_settings(self, league=None):
        return await self._answer("lineup_settings")

    async def calculation_settings(self, league=None):
        return await self._answer("calculation_settings")

    async def teams(self, page=1, league=None):
        return await self._answer("teams")

    async def players(self, league=None):
        return await self._answer("players")


@pytest.fixture
def fake_api(mcp_fixture_json):
    def _make(overrides=None):
        return FakeAPI(mcp_fixture_json, overrides)
    return _make


@pytest.fixture
def fixture_path():
    def _path(name: str) -> Path:
        return FIXTURE_DIR / f"{name}.json"
    return _path


@pytest.fixture
def fixture_file():
    def _path(name: str) -> Path:
        return FIXTURE_DIR / name
    return _path
