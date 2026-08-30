import json

import pytest
from fantaclaude.analysis.valuation import record_run
from fantaclaude.asta.adjustments import Adjustment, resolve
from fantaclaude.asta.advisor import Board, Ledger, TeamMapping, build_ledgers, derive
from fantaclaude.asta.pinned import load_pinned_run
from fantaclaude.asta.session import session_from_feed
from fantaclaude.asta.state import (
    AuctionState,
    apply_snapshot,
    parse_snapshot,
    read_snapshots,
)
from test_valuation import PREFS, run, seeded

SESSION = {"budget": 500, "game": 2, "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]}}


def pinned_run(tmp_path, fixture_json, mcp_fixture_json, **kw):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path, **kw)
    record_run(con, result)
    try:
        return result, load_pinned_run(con)
    finally:
        con.close()


def replayed(fixture_file, upto=None):
    state = AuctionState.empty()
    for snap in read_snapshots(fixture_file("asta_session_sample.jsonl"))[:upto]:
        state, _ = apply_snapshot(state, snap)
    return state


def node(picks, *, selected=None, teams=(0, 1, 2), settings=SESSION):
    """The state one synthetic snapshot describes."""
    snap = parse_snapshot({"picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i} for i, (pid, tid, cost) in enumerate(picks)],
                           "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams], "settings": settings,
                           "selectedPlayerId": selected, "status": "live", "locked": False})
    return apply_snapshot(AuctionState.empty(), snap)[0]


def test_the_live_board_at_minute_zero_reproduces_the_pinned_board(tmp_path, fixture_json, mcp_fixture_json):
    """One pricing function (spec): the run's committed board and the live
    board of an empty auction under the run's own league bounds are the same
    computation -- the same function, the same inputs, read back from the
    run's rows -- and agree band for band, inflation, composition and all."""
    prefs = {**PREFS, "scenarios": {"value-hunting": {"risk_appetite": "cautious", "max_budget_share_per_role": {"Pc": 0.25}}}}
    result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json, preferences=prefs)
    for scenario in ("balanced", "value-hunting"):
        board = derive(AuctionState.empty(), run=pinned, settings=pinned.league, mapping=TeamMapping(mine=0), scenario=scenario)
        assert isinstance(board, Board) and board.scenario == scenario and board.problems == () and board.league_conflicts == ()
        assert board.pricing.to_dict() == result.boards[scenario].to_dict()
        assert all(board.pricing.prices[pid].band == band for pid, band in pinned.prices[scenario].items())
        assert board.me.credits == 500 and board.market_credits == 4000 and len(board.ledgers) == 8
        assert board.pool_state.roster_min == 23 and board.pool_state.class_min == {"Por": 2} and board.pool_state.class_max == {"Por": 6}


def test_ledgers_follow_the_picks_and_name_what_the_run_cannot(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    state = replayed(fixture_file)
    settings = session_from_feed(state.settings, team_count=len(state.teams))
    board = derive(state, run=pinned, settings=settings, mapping=TeamMapping(mine=1, nicks={0: "Marco"}))
    host, me, third = board.ledgers[0], board.me, board.ledgers[2]
    assert isinstance(host, Ledger) and host.label == "host" and host.nick == "Marco" and host.spent == 165 and host.credits == 335
    assert [p.player_id for p in host.picks] == [2764, 2120] and host.goalkeepers == 0 and host.outfield == 2
    assert me.label == "Claude" and me.credits == 500 and me.picks == () and me.missing(settings) == (3, 22)
    assert third.label == "@bomber" and third.spent == 3 and third.unknown == 1 and third.outfield == 0
    assert board.market_credits == 335 + 500 + 497 and board.pool_state.credits == 500
    assert set(board.pricing.prices) == set(pinned.players) - {2764, 2120}          # the sold leave the pool
    assert len(board.problems) == 1 and "999999" in board.problems[0] and "@bomber" in board.problems[0]
    assert board.league_conflicts == ("teams: 3 in the session, 8 in the league",)
    assert board.selected is None and board.lot is None
    with_lot = derive(replayed(fixture_file, 6), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert with_lot.lot is not None and with_lot.lot.name == "Svilar" and with_lot.lot.role_class == "Por"
    assert with_lot.lot.band == with_lot.pricing.prices[5841].band and with_lot.lot.band.p50 > 0 and with_lot.lot.sold_to is None
    assert with_lot.problems == ()
    tiers = board.tiers(2)
    assert list(tiers) and all(len(rows) <= 2 for rows in tiers.values())
    assert tiers["Pc"][0]["band"]["p50"] >= tiers["Pc"][-1]["band"]["p50"] and "name" in tiers["Pc"][0]
    payload = json.loads(json.dumps(board.to_dict(), allow_nan=False))
    assert payload["me"]["credits"] == 500 and payload["teams"][0]["spent"] == 165 and payload["picks"] == 3
    assert payload["prices"]["5841"]["role_class"] == "Por" and "2764" not in payload["prices"]
    assert "@example" not in json.dumps(payload) and payload["adjustments"]["count"] == 0


def test_a_sale_to_me_and_a_lot_already_sold(tmp_path, fixture_json, mcp_fixture_json):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    settings = session_from_feed(SESSION, team_count=3)
    before = derive(node([]), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    after = derive(node([(5841, 1, 30)], selected=5841), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert after.me.credits == 470 and after.me.goalkeepers == 1 and after.me.missing(settings) == (2, 22)
    assert after.pool_state.credits == 470 and [o.player_id for o in after.pool_state.owned] == [5841]
    assert after.pool_state.owned[0].role_class == "Por" and 5841 not in after.pricing.prices
    assert after.market_credits == before.market_credits - 30
    assert after.lot is not None and after.lot.sold_to == 1 and after.lot.band is None and after.lot.expected_price is None
    assert after.pricing.composition["Por"] + after.me.goalkeepers >= 3               # the session's three keepers, one bought
    # a team over its budget, and my team missing from the session, are problems -- never a crash
    broke = derive(node([(2764, 0, 600)]), run=pinned, settings=settings, mapping=TeamMapping(mine=7))
    assert any("spent 600 of 500" in p for p in broke.problems) and any("my team 7" in p for p in broke.problems)
    assert broke.ledgers[0].credits == -100 and broke.market_credits == 500 * 3          # a negative balance buys nothing


def test_credits_never_go_negative_where_the_pricing_can_see_them(tmp_path, fixture_json, mcp_fixture_json):
    """The spec's checklist item ("credits never negative in the ledgers"),
    discharged where it actually binds. The ledger itself stays faithful: an
    admin who recorded a team spending 600 of 500 recorded an overspend, and
    Ledger.credits says -100 rather than hiding it. What must never go
    negative is what the pricing sees -- price_board raises ValueError on
    negative credits -- so build_pool_state floors both my credits and the
    market's at zero: a negative balance buys nothing."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    settings = session_from_feed(SESSION, team_count=3)
    board = derive(node([(2764, 0, 600)]), run=pinned, settings=settings, mapping=TeamMapping(mine=0))
    assert board.me.credits == -100                                  # the mirror is faithful
    assert board.pool_state.credits == 0 and board.market_credits == 1000     # the pricing never sees it
    assert board.market_credits == sum(max(0, led.credits) for led in board.ledgers.values())
    assert board.pricing.budget == 0 and board.to_dict()["me"]["credits"] == -100
    assert any("spent 600 of 500" in p for p in board.problems)      # and the operator is told


def test_a_player_the_feed_lists_twice_is_named(tmp_path, fixture_json, mcp_fixture_json):
    """The state machine keeps the later pick by index and records the
    duplicate; the ledgers are where a person sees it, so it is a problem."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    settings = session_from_feed(SESSION, team_count=3)
    twice = apply_snapshot(AuctionState.empty(), parse_snapshot(
        {"picks": [{"playerId": 2764, "teamId": 0, "cost": 90, "index": 0},
                   {"playerId": 2764, "teamId": 1, "cost": 120, "index": 1}],
         "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in (0, 1, 2)], "settings": SESSION}))[0]
    board = derive(twice, run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert twice.duplicates == (2764,) and board.ledgers[0].picks == () and board.ledgers[1].spent == 120
    assert any("2764" in p and "twice" in p for p in board.problems)


def test_adjustments_reach_the_board_through_v(tmp_path, fixture_json, mcp_fixture_json):
    """`exclude` raises the class, `value` scales one man's band, `target`
    moves the composition the optimiser starts from -- through V, never by
    annotating a row (spec, "Adjustments are hot-reloaded, and `exclude` has a
    directional invariant")."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    mapping = TeamMapping(mine=0)
    plain = derive(AuctionState.empty(), run=pinned, settings=pinned.league, mapping=mapping)
    excluded = resolve([Adjustment("exclude", "not buying him", player="Martinez L.")], pinned.candidates())
    without = derive(AuctionState.empty(), run=pinned, settings=pinned.league, layer=excluded, mapping=mapping)
    assert 2764 not in without.pricing.prices and 2764 in plain.pricing.prices
    for pid, player in pinned.players.items():
        if player.role_class == "Pc" and pid != 2764:
            assert without.pricing.prices[pid].band.p50 >= plain.pricing.prices[pid].band.p50
    layer = resolve([Adjustment("exclude", "not buying him", player="Martinez L."),
                     Adjustment("value", "knee", player="Hojlund", factor=0.5),
                     Adjustment("target", "more keepers", role_class="Por", count=3),
                     Adjustment("exclude", "typo", player="Nobody")], pinned.candidates(), sha256="s")
    adjusted = derive(AuctionState.empty(), run=pinned, settings=pinned.league, layer=layer, mapping=mapping)
    assert adjusted.pricing.prices[6052].band.p50 < without.pricing.prices[6052].band.p50       # half the value, a lower band
    assert adjusted.pool_state.targets == {"Por": 3} and adjusted.pool_state.weights["Por"][2] == pytest.approx(0.8)
    assert adjusted.problems == layer.problems and "'Nobody'" in adjusted.problems[0]
    assert adjusted.to_dict()["adjustments"]["excluded"] == [2764] and adjusted.to_dict()["adjustments"]["sha256"] == "s"
    # an excluded player who is then sold to me is simply owned: the exclusion was about my bidding
    settings = session_from_feed(SESSION, team_count=3)
    bought = derive(node([(2764, 0, 90)]), run=pinned, settings=settings, layer=layer, mapping=mapping)
    assert [o.player_id for o in bought.pool_state.owned] == [2764] and bought.pool_state.excluded == frozenset()
    # and a value factor follows him out of the pool: what he is worth to the roster is scaled too
    halved = derive(node([(6052, 0, 40)]), run=pinned, settings=settings, layer=layer, mapping=mapping)
    assert halved.pool_state.owned[0].value_p50 == pytest.approx(pinned.players[6052].value_p50 * 0.5)


def test_an_impossible_roster_is_a_problem_not_a_crash(tmp_path, fixture_json, mcp_fixture_json):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    five_keepers = session_from_feed({**SESSION, "roles": {"gk": [5, 5], "mov": [20, 20], "size": [25, 25]}}, team_count=3)
    board = derive(node([]), run=pinned, settings=five_keepers, mapping=TeamMapping(mine=1))
    assert board.pricing.completion_value == float("-inf")
    assert any("no completion" in p and "max_goalkeepers" in p for p in board.problems)
    assert json.loads(json.dumps(board.to_dict(), allow_nan=False))["completion_value"] is None
    ledgers, problems = build_ledgers(node([]), five_keepers, pinned, TeamMapping(mine=1))
    assert sorted(ledgers) == [0, 1, 2] and problems == []
