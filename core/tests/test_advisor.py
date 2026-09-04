import json

import pytest
from fantaclaude.analysis.valuation import record_run
from fantaclaude.asta.adjustments import Adjustment, resolve
from fantaclaude.asta.advisor import Board, Ledger, TeamMapping, build_ledgers, derive
from fantaclaude.asta.pinned import load_pinned_run
from fantaclaude.asta.pricing import PricingConfig
from fantaclaude.asta.session import session_from_feed
from fantaclaude.asta.state import (
    AuctionState,
    Pick,
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
    assert with_lot.lot.fvm == pinned.players[5841].fvm > 0        # the lot carries the listone value too
    assert with_lot.problems == ()
    tiers = board.tiers(2)
    assert list(tiers) and all(len(rows) <= 2 for rows in tiers.values())
    assert tiers["Pc"][0]["band"]["p50"] >= tiers["Pc"][-1]["band"]["p50"] and "name" in tiers["Pc"][0]
    assert all(r["fvm"] == pinned.players[r["player_id"]].fvm for rows in tiers.values() for r in rows)  # the listone value rides on the row
    assert all(r["apps"] == pinned.players[r["player_id"]].apps >= 0 for rows in tiers.values() for r in rows)
    assert with_lot.lot.apps == pinned.players[5841].apps        # the lot carries it too
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
    # The class's best remaining candidate is worth strictly more with a top rival gone -- the
    # invariant the spec names. It does not hold for every remaining member of the class: the
    # pricing DP has no such monotonicity in general -- excluding a class-mate lowers both the
    # buy and walk branches for the players left behind, and _fit_roster's bisected slot penalty
    # plus the reserve/budget loop shift globally whenever the optimal composition moves, which it
    # does here (a T slot displaces a marginal second Pc once Martinez is gone, because the rest of
    # the board's demand -- T's fold, E's -- moved too, not because Pc's own curve changed: Pc's
    # raw, unfolded weight is already bench-level at rank two, (0.6667, 0.12), and the fold actually
    # *raises* rank one to 0.7292). This is not particular to a small or folded listone: pricing 220-
    # player synthetic pools against the real, unfolded modules.yml weight curve, excluding a
    # class's best player made another remaining member of the class cheaper in 73 of 132 class x
    # seed trials, mostly with no composition change at all. The invariant holds for the top of the
    # class, which is what "raises the class" means, not for every remaining member of it.
    pc = {pid: player for pid, player in pinned.players.items() if player.role_class == "Pc" and pid != 2764}
    best_pc = max(pc, key=lambda pid: plain.pricing.prices[pid].band.p50)
    assert without.pricing.prices[best_pc].band.p50 > plain.pricing.prices[best_pc].band.p50
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


def test_a_ledger_reads_ranged_bounds_and_counts_the_classic_blocks(tmp_path, fixture_json, mcp_fixture_json):
    """The night's bounds were ranges (gk 2-4, mov 23-28, roster 25-30). A
    full roster owes nothing more; a short one owes only what the floors say.
    And every ledger counts its picks by classic role, because the room calls
    the auction in P, D, C, A blocks."""
    settings = session_from_feed({"budget": 500, "game": 2,
                                  "roles": {"gk": [2, 4], "mov": [23, 28], "size": [25, 30]}}, team_count=10)
    picks = tuple(Pick(i, 3, 1, i) for i in range(30))
    full = Ledger(3, "Claudio", None, 500, 480, picks, 3, 27, 0)
    assert full.missing(settings) == (0, 0) and full.room(settings) == (1, 1)
    assert full.open_slots(settings) == 0 and full.required_slots(settings) == 0
    short = Ledger(7, "radyandre", None, 500, 499, picks[:27], 4, 23, 0)
    assert short.missing(settings) == (0, 0) and short.room(settings) == (0, 5) and short.open_slots(settings) == 3
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    ledgers, _ = build_ledgers(node([(2764, 0, 90), (2120, 0, 30), (5841, 1, 20)]), settings, pinned, TeamMapping(mine=1))
    assert ledgers[0].classic == {"A": 1, "D": 1} and ledgers[1].classic == {"P": 1} and ledgers[2].classic == {}
    assert ledgers[0].to_dict(settings)["classic"] == {"A": 1, "D": 1}


def test_the_board_re_pins_against_the_ranks_my_roster_leaves_open(tmp_path, fixture_json, mcp_fixture_json):
    """At minute zero every pin is the run's. Once my squad covers a class,
    an unsold man pinned there is priced under another role he holds: the
    class that has ranks left for him, never a band of 0 for a man the
    completion would still pay for as a W."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json,
                           pricing_cfg=PricingConfig(max_per_class=1, max_goalkeepers=2))
    settings = session_from_feed({**SESSION, "roles": {"gk": [2, 2], "mov": [20, 30], "size": [22, 32]}}, team_count=3)
    dimarco = pinned.players[254]
    assert set(dimarco.roles) == {"E", "W"} and dimarco.role_class == "E"
    zero = derive(node([]), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert all(price.role_class == pinned.players[pid].role_class for pid, price in zero.pricing.prices.items())
    assert zero.pins == {}
    covered = derive(node([(791, 1, 5), (5877, 1, 5)]), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert covered.pricing.prices[254].role_class == "W" and covered.pins == {254: "W"}
    assert covered.pricing.occupancy["E"] >= 1 and covered.to_dict()["prices"]["254"]["role_class"] == "W"
    assert 254 in {r["player_id"] for r in covered.tiers()["W"]} and 254 not in {r["player_id"] for r in covered.tiers().get("E", [])}


def test_the_board_names_the_block_the_room_is_calling(tmp_path, fixture_json, mcp_fixture_json):
    """The room calls the auction in classic-role blocks (P, D, C, A). The
    board reads the block off the lot on the block, else off the latest
    pick, and puts that block's classes first on the tier board."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    settings = session_from_feed(SESSION, team_count=3)
    quiet = derive(node([]), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert quiet.block is None and quiet.to_dict()["block"] is None
    defenders = derive(node([(2120, 0, 30)]), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert defenders.block == {"classic_role": "D", "classes": defenders.block["classes"]}
    unsold_d = {price.role_class for pid, price in defenders.pricing.prices.items() if pinned.players[pid].classic_role == "D"}
    assert set(defenders.block["classes"]) == unsold_d and "Dc" in unsold_d
    assert list(defenders.tiers())[:len(unsold_d)] == defenders.block["classes"]
    keeper_up = derive(node([(2120, 0, 30)], selected=5841), run=pinned, settings=settings, mapping=TeamMapping(mine=1))
    assert keeper_up.block["classic_role"] == "P" and keeper_up.block["classes"] == ["Por"]
    assert next(iter(keeper_up.tiers())) == "Por"


def test_a_row_carries_the_adjusted_value_and_the_list_hash_rides_on_the_board(tmp_path, fixture_json, mcp_fixture_json):
    """The band came from the pricer, which saw the adjustment; value_p50
    came from the run, which did not -- so a halved man sorted among the
    band-0 rows by his pre-adjustment value (Franjic, 2026-09-03). The row
    carries what he is worth to this board. And the room's own list is a
    fact the mirror stores only as a hash: the board says which list it saw."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    layer = resolve([Adjustment("value", "knee", player="Hojlund", factor=0.5)], pinned.candidates(), sha256="s")
    snap = parse_snapshot({"picks": [], "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in (0, 1, 2)],
                           "settings": SESSION, "playerListHash": "9da873c6"})
    board = derive(apply_snapshot(AuctionState.empty(), snap)[0], run=pinned, settings=session_from_feed(SESSION, team_count=3),
                   layer=layer, mapping=TeamMapping(mine=1))
    payload = board.to_dict()
    assert payload["prices"]["6052"]["value_p50"] == pytest.approx(pinned.players[6052].value_p50 * 0.5)
    assert payload["prices"]["2764"]["value_p50"] == pytest.approx(pinned.players[2764].value_p50)
    pc = board.tiers(10)["Pc"]
    assert [r["player_id"] for r in pc] == sorted((r["player_id"] for r in pc),
                                                   key=lambda pid: (-board.pricing.prices[pid].band.p50,
                                                                    -payload["prices"][str(pid)]["value_p50"], pid))
    assert payload["player_list_hash"] == "9da873c6" and payload["occupancy"]["Por"] == 0
    assert payload["room_by_class"]["Por"] == len(board.pool_state.weights["Por"]) == 3     # the session's three keepers: three ranks
