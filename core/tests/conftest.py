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
