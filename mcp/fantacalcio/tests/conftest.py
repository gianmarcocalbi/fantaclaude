import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_json():
    def _load(name: str):
        return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load


def keys_at_any_depth(value) -> set[str]:
    """Every mapping key anywhere inside a JSON-ish structure.

    Shared by the leak tests. A key-based scan is what lets those tests
    check for a secret *without embedding it*: asserting "no key named
    `parola` exists at any depth" catches the league join password
    wherever it appears, whereas a substring match would have to hardcode
    the password itself -- shipping, in the scanner, the exact secret the
    scanner exists to keep out of the repo.
    """
    found: set[str] = set()
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            found.update(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found
