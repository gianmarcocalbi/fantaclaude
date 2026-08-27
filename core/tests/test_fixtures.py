"""The secret scan for this package's fixtures: key names and shapes, never
a literal value -- a scanner that embeds the secret it scans for ships it."""

import json

from conftest import FIXTURE_DIR

SECRET_KEYS = {"parola", "password", "token", "jwt", "email", "app_key"}


def _keys_at_any_depth(value) -> set[str]:
    found: set[str] = set()
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            found.update(str(k).lower() for k in node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def test_expected_fixtures_exist():
    assert (FIXTURE_DIR / "listone_sample.json").is_file()


def test_fixtures_contain_no_secrets():
    for path in FIXTURE_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "eyJhbGci" not in text, f"{path.name} contains a JWT"
        assert "@" not in text.replace("\\u0040", ""), f"{path.name} contains an email"
        assert not SECRET_KEYS & _keys_at_any_depth(json.loads(text)), f"{path.name} carries a secret key"
