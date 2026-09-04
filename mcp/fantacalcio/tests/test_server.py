import json
from pathlib import Path

import pytest
from conftest import keys_at_any_depth
from fantacalcio_mcp.server import build_server
from fastmcp import Client

SRC = Path(__file__).resolve().parents[1] / "src" / "fantacalcio_mcp"

EXPECTED_TOOLS = {
    "get_account", "get_league", "get_league_settings", "get_my_team",
    "list_teams", "list_competitions", "get_server_time",
}


class FakeAPI:
    """Stands in for FantacalcioAPI; returns fixtures, records calls."""

    def __init__(self, fixture_json):
        self._f = fixture_json
        self.calls: list[tuple[str, dict]] = []

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))

    async def profile(self, user_id=None):
        self._record("profile", user_id=user_id); return self._f("profile")

    async def league_profile(self, league=None):
        self._record("league_profile", league=league); return self._f("league_profile")

    async def league_status(self, league=None):
        self._record("league_status", league=league); return self._f("league_status")

    async def competitions(self, league=None):
        self._record("competitions", league=league); return self._f("competitions")

    async def my_team(self, league=None):
        self._record("my_team", league=league); return self._f("my_team")

    async def teams(self, page=1, league=None):
        self._record("teams", page=page, league=league); return self._f("teams")

    async def roster_settings(self, league=None):
        return self._f("roster_settings")

    async def lineup_settings(self, league=None):
        return self._f("lineup_settings")

    async def calculation_settings(self, league=None):
        return self._f("calculation_settings")

    async def participants(self, page_number=1, page_size=1000, league=None):
        self._record("participants", league=league); return self._f("participants")

    async def invitees(self, page_number=1, page_size=1000, league=None):
        self._record("invitees", league=league); return self._f("invitees")

    async def server_time(self, league=None):
        return self._f("server_time")


@pytest.fixture
def fake_api(fixture_json):
    return FakeAPI(fixture_json)


def test_api_module_never_imports_fastmcp():
    # api.py's own docstring legitimately says (in prose) "Must never
    # import fastmcp", explaining *why* -- so any substring check on the
    # whole file text, even "import fastmcp", false-positives against that
    # sentence. Check each line for an actual import *statement* (a line
    # starting with "import fastmcp"/"from fastmcp") instead, mirroring
    # how test_server_module_never_imports_httpx checks server.py.
    lines = (SRC / "api.py").read_text(encoding="utf-8").splitlines()
    assert not any(line.strip().startswith(("import fastmcp", "from fastmcp"))
                   for line in lines)


def test_server_module_never_imports_httpx():
    # M5: a bare `"import httpx" not in text` substring check is not the
    # same guarantee -- `from httpx import AsyncClient` slips straight past
    # it. Check each line for an actual import *statement*, exactly as
    # test_api_module_never_imports_fastmcp above does.
    lines = (SRC / "server.py").read_text(encoding="utf-8").splitlines()
    assert not any(line.strip().startswith(("import httpx", "from httpx"))
                   for line in lines)


async def test_exactly_seven_tools_are_registered(fake_api):
    async with Client(build_server(fake_api)) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_every_tool_has_a_description(fake_api):
    async with Client(build_server(fake_api)) as client:
        for tool in await client.list_tools():
            assert tool.description and len(tool.description) > 20, tool.name


async def test_get_league_merges_profile_and_status(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("get_league", {})
    payload = json.loads(result.content[0].text)
    assert payload["name"] == "Fantabalotelli3"
    assert payload["status"]["matchday"] == 1
    # The real join password lives under the "parola" key and must never be
    # returned. "parola_ordine" is a *different*, non-secret boolean flag
    # (see models.py / test_models.py's
    # test_league_strips_parola_but_keeps_parola_ordine) that is deliberately
    # preserved -- so this checks dict-key membership on `raw`, not a bare
    # substring of the JSON text, which would false-positive on
    # "parola_ordine".
    #
    # L16: checked over the whole payload, not just `payload["raw"]`.
    # `payload["status"]` is `LeagueStatus.raw` verbatim, so a `parola` key
    # arriving on /league/status would have leaked with nothing to catch
    # it. `keys_at_any_depth` also means a future nesting change cannot
    # quietly move the key out from under this assertion.
    assert "parola" not in keys_at_any_depth(payload)
    assert "parola_ordine" in keys_at_any_depth(payload), (
        "the non-secret flag must survive -- otherwise this assertion could "
        "pass simply because nothing parola-ish reaches the payload at all"
    )


async def test_get_league_settings_merges_three_endpoints(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("get_league_settings", {})
    payload = json.loads(result.content[0].text)
    assert payload["budget"] == 500
    assert payload["substitutions"] == 5
    assert "442" in payload["modules"]


async def test_list_teams_merges_managers_into_teams(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("list_teams", {})
    payload = json.loads(result.content[0].text)
    by_name = {t["name"]: t for t in payload["teams"]}
    assert by_name["KingKlavan FC"]["managers"] == ["KingNazzario"]
    assert "@" not in json.dumps(payload), "manager emails must never be returned"


async def test_list_teams_can_include_pending_invites(fake_api):
    async with Client(build_server(fake_api)) as client:
        await client.call_tool("list_teams", {"include_pending": True})
    assert any(name == "invitees" for name, _ in fake_api.calls)


async def test_league_argument_is_forwarded(fake_api):
    async with Client(build_server(fake_api)) as client:
        await client.call_tool("get_my_team", {"league": "fantabalotelli3"})
    assert ("my_team", {"league": "fantabalotelli3"}) in fake_api.calls


async def test_get_account_never_returns_tokens(fake_api):
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("get_account", {})
    text = result.content[0].text
    assert "eyJhbGci" not in text and "jwt" not in text.lower()


# Nested shape observed on the sibling endpoint /invitation/participants.
# `invitees.json` is `[]`, so the invitees shape was never observed -- this
# is the shape it most likely shares, built inline rather than by editing a
# fixture. The email here is a made-up address, never a real one.
NESTED_INVITEES = [
    {
        "teamId": 11554999,
        "teamName": "Pending FC",
        "teamLogo": "no_logo16.png",
        "coaches": [
            {"id": 3001, "name": "InvitedManager", "email": "victim@example.it",
             "code": "PAROLA", "admin": 0},
        ],
    },
    {
        "teamId": 11555000,
        "teamName": "Also Pending",
        "coaches": [{"id": 3002, "name": "SecondInvitee",
                     "email": "another.person@example.com"}],
    },
]


async def test_list_teams_pending_invites_strip_emails_at_any_depth(fake_api):
    """L16/I2: `include_pending` stripped `email` only at the TOP level of
    each invitee row -- a guess, since invitees.json is empty. Against the
    nested shape its sibling endpoint actually returns
    (`coaches: [{id, name, email}]`) the top-level strip does nothing and
    every invitee's email address was returned verbatim, contradicting both
    the tool's docstring ("stripped before this tool returns anything") and
    the spec ("Manager emails are dropped, not forwarded").

    The scrub is now recursive and key-based, so it holds for whatever
    shape the endpoint really returns -- not only the one we guessed.
    """
    async def invitees(page_number=1, page_size=1000, league=None):
        fake_api._record("invitees", league=league)
        return NESTED_INVITEES

    fake_api.invitees = invitees
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("list_teams", {"include_pending": True})
    text = result.content[0].text
    assert "@" not in text, "invitee emails must never be returned"
    assert "victim" not in text and "another.person" not in text

    # ...while everything that is not an email survives.
    payload = json.loads(text)
    pending = payload["pending_invites"]
    assert [row["teamName"] for row in pending] == ["Pending FC", "Also Pending"]
    assert pending[0]["coaches"][0]["name"] == "InvitedManager"
    assert pending[0]["coaches"][0]["id"] == 3001


async def test_list_teams_pending_invites_strip_a_top_level_email_too(fake_api):
    """The flat shape the old code assumed must keep working: recursion
    generalises the strip, it does not replace it.
    """
    async def invitees(page_number=1, page_size=1000, league=None):
        return [{"id": 7, "name": "Flat Invitee", "email": "flat@example.it"}]

    fake_api.invitees = invitees
    async with Client(build_server(fake_api)) as client:
        result = await client.call_tool("list_teams", {"include_pending": True})
    text = result.content[0].text
    assert "@" not in text
    assert json.loads(text)["pending_invites"] == [{"id": 7, "name": "Flat Invitee"}]


async def test_list_teams_reads_every_page_and_says_when_one_is_missing(fake_api, fixture_json):
    """The endpoint pages by ten. On 2026-09-04 the real league had eleven
    teams, `divisions[A].count` said 11, and this tool returned the ten on
    page 1 -- the missing one was the signed-in user's own team, which is
    the worst possible row to drop. Every page is read, and a total that
    still disagrees with the division count is said in the payload rather
    than left for the caller to notice."""
    base = fixture_json("teams")
    row = base["data"][0]
    page1 = {**base, "data": base["data"], "nextPage": True, "pages": 2,
             "divisions": [{"division": "A", "count": len(base["data"]) + 1}]}
    page2 = {**base, "page": 2, "nextPage": False, "prevPage": True, "pages": 2,
             "data": [{**row, "id": 99, "idu": 99, "n": "Ultimo Arrivato", "nu": "latecomer"}],
             "divisions": page1["divisions"]}
    pages = {1: page1, 2: page2}

    async def by_page(page=1, league=None):
        fake_api._record("teams", page=page, league=league)
        return json.loads(json.dumps(pages[page]))

    fake_api.teams = by_page
    async with Client(build_server(fake_api)) as client:
        payload = json.loads((await client.call_tool("list_teams", {})).content[0].text)
    assert [p for name, p in fake_api.calls if name == "teams"] == [{"page": 1, "league": None},
                                                                    {"page": 2, "league": None}]
    assert "Ultimo Arrivato" in {t["name"] for t in payload["teams"]}
    assert len(payload["teams"]) == len(base["data"]) + 1 and payload.get("incomplete") is None

    async def one_page_only(page=1, league=None):
        fake_api._record("teams", page=page, league=league)
        return json.loads(json.dumps({**page1, "nextPage": False, "pages": 1}))

    fake_api.teams = one_page_only
    async with Client(build_server(fake_api)) as client:
        short = json.loads((await client.call_tool("list_teams", {})).content[0].text)
    assert str(len(base["data"])) in short["incomplete"] and str(len(base["data"]) + 1) in short["incomplete"]
