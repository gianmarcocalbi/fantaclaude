from dataclasses import replace

import pytest
from fantaclaude.asta.session import (
    GAME_CLASSIC,
    GAME_MANTRA,
    SessionError,
    SessionSettings,
    compare,
    league_bounds,
    session_from_feed,
    session_from_league,
)
from fantaclaude.asta.state import read_snapshots
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads

LEAGUE = session_from_league(budget=500, team_count=8, roster_min=23, roster_max=40, minrl=[2, 21], maxrl=[6, 34],
                             game=GAME_MANTRA)


def _record(db, mcp_fixture_json, *, rosters=None, profile=None) -> int:
    """One league_settings row from the MCP fixtures, with the payload tweaked."""
    return record_snapshot(db, snapshot_from_payloads(
        profile=profile or mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=rosters or mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams"))).snapshot_id


def test_the_captured_settings_read_as_exact_counts(fixture_file):
    node = read_snapshots(fixture_file("asta_session_sample.jsonl"))[0]
    s = session_from_feed(node.settings, team_count=len(node.teams))
    assert s == SessionSettings(500, (3, 3), (22, 22), (25, 25), GAME_MANTRA, 3, "session", node.settings,
                                classic_buckets={"def": (8, 8), "mid": (8, 8), "atk": (6, 6)})
    assert s.is_mantra and s.to_dict() == {"budget": 500, "goalkeepers": [3, 3], "outfield": [22, 22], "size": [25, 25],
                                            "game": 2, "team_count": 3, "source": "session",
                                            "classic_buckets": {"def": [8, 8], "mid": [8, 8], "atk": [6, 6]}}


def test_a_pair_is_a_range_and_the_night_of_2026_09_03_reads_as_one():
    """FA-rb8-460 shipped gk [2, 4], mov [23, 28], size [25, 30], and three
    teams ended the night with four keepers on rosters of 27 to 30 players:
    the pair is (min, max), not [classic, mantra]. def/mid/atk are the
    classic-role buckets the room calls its blocks in; Mantra enforces only
    gk and mov, so they are carried beside the bounds, never as bounds."""
    roles = {"gk": [2, 4], "def": [8, 8], "mid": [8, 8], "atk": [6, 6], "mov": [23, 28], "size": [25, 30]}
    s = session_from_feed({"budget": 500, "game": 2, "roles": roles}, team_count=10)
    assert (s.goalkeepers, s.outfield, s.size) == ((2, 4), (23, 28), (25, 30)) and s.is_mantra
    assert s.classic_buckets == {"def": (8, 8), "mid": (8, 8), "atk": (6, 6)}
    assert s.to_dict()["classic_buckets"] == {"def": [8, 8], "mid": [8, 8], "atk": [6, 6]}
    assert compare(session_from_feed(s.raw, team_count=8), LEAGUE) == []       # 2-4, 23-28 and 25-30 are inside the league's
    bare = session_from_feed({"budget": 500, "game": 2, "roles": {"gk": 2, "mov": 21, "size": 23}}, team_count=8)
    assert bare.goalkeepers == (2, 2) and bare.size == (23, 23) and bare.classic_buckets == {}
    classic = session_from_feed({"budget": 500, "game": 1, "roles": roles}, team_count=8)
    assert (classic.goalkeepers, classic.size) == ((2, 4), (25, 30)) and not classic.is_mantra
    for bad, text in (({**roles, "gk": [4, 2]}, "roles.gk"),                                   # a range runs low to high
                      ({"gk": [3, 3], "mov": [22, 22], "size": [24, 24]}, "size"),           # 25 needed, 24 allowed
                      ({"gk": [3, 3], "mov": [22, 22], "size": [26, 26]}, "size"),           # 26 needed, 25 possible
                      ({"gk": [3, 3], "size": [25, 25]}, "roles.mov"),
                      ({"gk": [3, True], "mov": [22, 22], "size": [25, 25]}, "roles.gk"),
                      ({**roles, "def": [9, 8]}, "roles.def")):
        with pytest.raises(SessionError, match=text):
            session_from_feed({"budget": 500, "game": 2, "roles": bad}, team_count=8)
    for bad, text in (({"game": 2, "roles": roles}, "budget"), ({"budget": 500, "game": 3, "roles": roles}, "game"),
                      ({"budget": 500, "game": 2}, "roles"), ({"budget": -5, "game": 2, "roles": roles}, "budget")):
        with pytest.raises(SessionError, match=text):
            session_from_feed(bad, team_count=8)


def test_league_bounds_read_the_run_settings_row(db, mcp_fixture_json):
    record_snapshot(db, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    bounds = league_bounds(db, 1)
    # league_bounds now also carries the league's modules; LEAGUE is built without them
    assert bounds.modules and replace(bounds, modules=()) == LEAGUE
    assert bounds.source == "league" and bounds.game == GAME_MANTRA and bounds.is_mantra
    assert (bounds.goalkeepers, bounds.outfield, bounds.size) == ((2, 6), (21, 34), (23, 40))
    with pytest.raises(SessionError, match="snapshot 9"):
        league_bounds(db, 9)


def test_compare_surfaces_what_the_session_plays_outside_the_league():
    """The session wins for the night; a mismatch is announced at connect,
    before bidding opens, never absorbed."""
    session = session_from_feed({"budget": 500, "game": 2, "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]}},
                                team_count=2)
    assert compare(session, LEAGUE) == ["teams: 2 in the session, 8 in the league"]      # 3, 22 and 25 are inside the bounds
    assert compare(session_from_feed(session.raw, team_count=8), LEAGUE) == []
    rich = session_from_feed({**session.raw, "budget": 1000}, team_count=8)
    assert compare(rich, LEAGUE) == ["budget: the session plays 1000 credits, the league says 500"]
    thin = session_from_feed({**session.raw, "roles": {"gk": [1, 1], "mov": [22, 22], "size": [23, 23]}}, team_count=8)
    assert compare(thin, LEAGUE) == ["goalkeepers: the session fills 1, the league allows 2-6"]
    classic = session_from_feed({**session.raw, "game": 1}, team_count=8)
    assert compare(classic, LEAGUE) == ["game: the session is classic (1), the league is Mantra (2)"]
    assert compare(LEAGUE, LEAGUE) == []


def test_the_game_is_the_leagues_to_state_never_this_readers_to_assume():
    """A classic session in a classic league is no mismatch: `compare` reads
    both games off the settings rather than asserting Mantra, so connect
    never announces a difference that does not exist."""
    classic_league = session_from_league(budget=500, team_count=8, roster_min=23, roster_max=40,
                                         minrl=[2, 21], maxrl=[6, 34], game=GAME_CLASSIC)
    assert classic_league.game == GAME_CLASSIC and not classic_league.is_mantra
    classic = session_from_feed({"budget": 500, "game": 1, "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]}},
                                team_count=8)
    assert compare(classic, classic_league) == []
    assert compare(classic, LEAGUE) == ["game: the session is classic (1), the league is Mantra (2)"]
    mantra = session_from_feed({**classic.raw, "game": 2}, team_count=8)
    assert compare(mantra, classic_league) == ["game: the session is Mantra (2), the league is classic (1)"]


def test_a_league_bound_that_is_not_a_count_is_a_session_error():
    """The stored payload demonstrably carries nulls (`under`, `cteam`), so a
    null among the bounds must be SessionError -- the only error this
    function raises -- and never a bare TypeError past the declared type."""
    ok = {"budget": 500, "team_count": 8, "roster_min": 23, "roster_max": 40, "minrl": [2, 21], "maxrl": [6, 34],
          "game": GAME_MANTRA}
    for key, value, text in (("minrl", [2, None], r"minrl\[1\]"), ("maxrl", [None, 34], r"maxrl\[0\]"),
                             ("minrl", [2, -1], r"minrl\[1\]"), ("maxrl", [6, "34"], r"maxrl\[1\]"),
                             ("roster_min", None, "roster_min"), ("budget", None, "budget"),
                             ("team_count", None, "team_count"), ("minrl", [2], "not the two bounds"),
                             ("maxrl", None, "not the two bounds"), ("game", 0, "game"), ("game", None, "game")):
        with pytest.raises(SessionError, match=text):
            session_from_league(**{**ok, key: value})


def test_league_bounds_read_the_game_and_the_bucket_shape_off_the_row(db, mcp_fixture_json):
    """`profile.tipo` states the game (design spec: "league type"); `sroles`
    states how many groups minrl/maxrl bound, and at anything but 2 this
    reader would call the wrong bucket the outfield bound, so it refuses."""
    rosters, profile = mcp_fixture_json("roster_settings"), mcp_fixture_json("league_profile")
    assert _record(db, mcp_fixture_json, profile={"lega": {**profile["lega"], "tipo": GAME_CLASSIC}}) == 1
    classic = league_bounds(db, 1)
    assert classic.game == GAME_CLASSIC and not classic.is_mantra
    assert (classic.goalkeepers, classic.outfield, classic.size) == ((2, 6), (21, 34), (23, 40))
    assert _record(db, mcp_fixture_json, rosters={**rosters, "sroles": 4}) == 2
    with pytest.raises(SessionError, match="sroles"):
        league_bounds(db, 2)
    assert _record(db, mcp_fixture_json, rosters={**rosters, "minrl": [2, None]}) == 3
    with pytest.raises(SessionError, match=r"minrl\[1\]"):
        league_bounds(db, 3)
    # `fsltc` is read by nothing; it moves the rules hash so the append-only table takes a fourth row.
    assert _record(db, mcp_fixture_json, rosters={**rosters, "fsltc": 1},
                   profile={"lega": {k: v for k, v in profile["lega"].items() if k != "tipo"}}) == 4
    with pytest.raises(SessionError, match="profile.tipo"):
        league_bounds(db, 4)
