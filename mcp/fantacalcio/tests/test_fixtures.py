import json
from pathlib import Path

from conftest import keys_at_any_depth

FIXTURE_DIR = Path(__file__).parent / "fixtures"

EXPECTED = {
    "profile", "league_profile", "league_status", "competitions", "my_team",
    "teams", "roster_settings", "lineup_settings", "calculation_settings",
    "participants", "invitees", "server_time", "login",
}


def test_every_expected_fixture_exists():
    actual = {p.stem for p in FIXTURE_DIR.glob("*.json")}
    assert EXPECTED <= actual


def test_fixtures_contain_no_secrets():
    """A JWT, app_key, email or league password must never reach the repo.

    The join password is checked by *key*, not by value: a substring match
    would have to hardcode the password, which would put the very secret
    this test exists to keep out of the repo into the repo. Scanning for a
    `parola` key at any depth is also strictly stronger than the old
    top-level `payload["lega"]` check -- it catches the password wherever
    it is nested, not only at the one level we happened to observe.
    """
    for path in FIXTURE_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "eyJhbGci" not in text, f"{path.name} contains a JWT"
        assert "@" not in text.replace("\\u0040", ""), f"{path.name} contains an email"
        payload = json.loads(text)
        assert "parola" not in keys_at_any_depth(payload), f"{path.name} leaks parola"


def test_parola_scan_looks_past_the_top_level():
    """Pins that the scan above is genuinely recursive. The check it
    replaced only looked at payload["lega"], so a `parola` nested anywhere
    else would have sailed through; and `parola_ordine` (a non-secret
    boolean flag) must still not trip it.
    """
    assert "parola" in keys_at_any_depth({"a": [{"b": {"lega": {"parola": "x"}}}]})
    assert "parola" not in keys_at_any_depth({"lega": {"parola_ordine": True}})


def test_league_profile_shape_survived_scrubbing(fixture_json):
    lega = fixture_json("league_profile")["lega"]
    assert lega["nome"]
    assert lega["id"]
    assert "admins" in lega


def test_teams_fixture_is_paginated_envelope(fixture_json):
    teams = fixture_json("teams")
    assert set(teams) >= {"page", "pages", "data", "divisions"}
    assert isinstance(teams["data"], list) and teams["data"]


def test_login_fixture_carries_league_tokens(fixture_json):
    data = fixture_json("login")["data"]
    assert data["leghe"], "login fixture must contain at least one league"
    assert {"alias", "jwt", "id", "id_squadra"} <= set(data["leghe"][0])
