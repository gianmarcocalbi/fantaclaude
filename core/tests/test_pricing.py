import json
import time

import numpy as np
import pytest
from fantaclaude.asta.pricing import (
    Band,
    BoardPricing,
    OwnedPlayer,
    PlayerPrice,
    PoolPlayer,
    PoolState,
    PricingConfig,
    _curve,
    explain,
    price_board,
)
from fantaclaude.asta.pricing_config import PricingConfigError, load_pricing_config
from fantaclaude.model.demand import (
    ROLE_CLASSES,
    hard_minimums,
    module_demand,
    rank_weights,
)
from fantaclaude.model.modules import load_modules

CFG = PricingConfig()
WEIGHTS = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=CFG.bench_weight)
HARD = hard_minimums(load_modules())


def player(pid, cls, value, quot, spread=0.25):
    return PoolPlayer(pid, f"p{pid}", cls, value * (1 - spread), value, value * (1 + spread), quot)


def small_pool():
    """Values in remaining-season fantapunti, quotazioni as the listone would price them."""
    spec = {"Por": [(120, 12), (60, 4), (20, 1)], "Dd": [(90, 8), (40, 2)], "Ds": [(90, 8), (40, 2)],
            "Dc": [(150, 20), (120, 12), (90, 8), (60, 4), (30, 1)], "E": [(110, 10), (70, 5), (30, 1)],
            "M": [(100, 9), (60, 4), (30, 1)], "C": [(130, 14), (90, 8), (60, 4), (30, 1)],
            "W": [(120, 12), (80, 6), (30, 1)], "T": [(140, 16), (80, 6), (30, 1)],
            "A": [(160, 22), (110, 10), (60, 4), (30, 1)], "Pc": [(220, 36), (150, 20), (80, 6), (30, 1)]}
    pool, pid = [], 100
    for cls, entries in spec.items():
        for value, quot in entries:
            pool.append(player(pid, cls, value, quot))
            pid += 1
    return tuple(pool)


def state(pool=None, **kw):
    base = {"credits": 500, "market_credits": 4000, "pool": pool or small_pool(), "weights": WEIGHTS,
            "hard_minimums": HARD, "roster_min": 1, "roster_max": 40, "min_goalkeepers": 2, "max_goalkeepers": 6}
    base.update(kw)
    return PoolState(**base)


def by_class(pool, cls):
    return [p for p in pool if p.role_class == cls]


def test_bands_are_ordered_and_bounded():
    board = price_board(state(), CFG)
    assert isinstance(board, BoardPricing) and set(board.prices) == {p.player_id for p in small_pool()}
    for price in board.prices.values():
        assert isinstance(price, PlayerPrice) and isinstance(price.band, Band)
        assert 0 <= price.band.p25 <= price.band.p50 <= price.band.p75 <= board.budget
        assert price.expected_price >= 1
    assert board.reserve == 0 and board.budget == 500
    assert sum(board.credits_by_class.values()) <= 500 and 3 <= sum(board.composition.values()) <= 40
    assert board.slot_price == 0.0
    assert board.composition["Por"] >= 2 and board.composition["Dc"] >= 2                # the hard minimums hold
    d = board.to_dict()
    assert d["inflation"] == board.inflation and d["prices"][str(100)]["band"]["p50"] == board.prices[100].band.p50


def test_inflation_is_self_calibrating_and_clamped():
    pool = small_pool()
    quot = sum(p.quotazione for p in pool)                    # every class has <= 30 players, so all are credible
    assert price_board(state(market_credits=quot), CFG).inflation == pytest.approx(1.0)
    assert price_board(state(market_credits=quot * 10), CFG).inflation == CFG.inflation_ceiling
    assert price_board(state(market_credits=quot // 10), CFG).inflation == CFG.inflation_floor
    board = price_board(state(market_credits=quot), CFG)
    assert all(board.expected_prices[p.player_id] == max(1, p.quotazione) for p in pool)


def test_scarcity_never_lowers_the_price_and_exhaustion_drives_it_to_the_credits_available():
    pool = small_pool()
    dc = by_class(pool, "Dc")
    target = dc[1]                                              # value 120
    owned = (OwnedPlayer(1, "Dc", 150.0),)                      # one Dc owned: one more needed by the hard minimum
    prices = []
    for keep in (dc, dc[1:], dc[1:3], [target]):
        rest = tuple(p for p in pool if p.role_class != "Dc") + tuple(keep)
        prices.append(price_board(state(rest, owned=owned), CFG).prices[target.player_id].band.p50)
    assert prices == sorted(prices), prices                     # shrinking the Dc pool never lowers his price
    # only he is left and one Dc is required: walking away is infeasible, so the price is every credit
    # not needed by the other hard slots -- the two cheapest goalkeepers at their expected prices
    last = price_board(state(tuple(p for p in pool if p.role_class != "Dc") + (target,), owned=owned), CFG)
    por_costs = sorted(last.expected_prices[p.player_id] for p in by_class(pool, "Por"))
    assert last.prices[target.player_id].band.p50 == 500 - sum(por_costs[:2])
    assert last.prices[target.player_id].walk_value == float("-inf")


def test_excluding_a_player_raises_everyone_else_at_his_class_and_removes_him():
    pool = small_pool()
    dc = by_class(pool, "Dc")
    before = price_board(state(), CFG)
    after = price_board(state(excluded=frozenset({dc[0].player_id})), CFG)
    assert dc[0].player_id not in after.prices
    for p in dc[1:]:
        assert after.prices[p.player_id].band.p50 >= before.prices[p.player_id].band.p50
    # weakly for the class, strictly for the man who inherits his slot: without the best Dc the second is worth more
    assert after.prices[dc[1].player_id].band.p50 > before.prices[dc[1].player_id].band.p50
    assert all(after.prices[p.player_id].band.p50 >= 0 for p in pool if p.role_class != "Dc")


def test_owned_players_consume_ranks_and_bounds():
    pool = small_pool()
    por = by_class(pool, "Por")
    full = price_board(state(owned=tuple(OwnedPlayer(i, "Por", 50.0) for i in range(CFG.max_goalkeepers))), CFG)
    assert all(full.prices[p.player_id].band == Band(0, 0, 0) for p in por)          # no goalkeeper slot left
    assert full.composition["Por"] == 0
    plain = price_board(state(), CFG)
    assert plain.prices[por[0].player_id].rank_weight == WEIGHTS["Por"][0]
    one = price_board(state(owned=(OwnedPlayer(1, "Por", 120.0),)), CFG)
    assert one.prices[por[0].player_id].rank_weight == WEIGHTS["Por"][1]              # he would be my second keeper


CLIFF = (0.939, 0.12, 0.06)                     # the shape the real demand gives A, W and Dc: a starter and two benches


def cliff_state(values=(230.0, 222.0, 207.0, 197.0), quots=(30, 28, 25, 23), **kw):
    pool = tuple(player(200 + i, "A", v, q, spread=0.05) for i, (v, q) in enumerate(zip(values, quots, strict=True)))
    base = {"credits": 500, "market_credits": 500, "pool": pool, "weights": {"A": CLIFF}, "hard_minimums": {},
            "roster_min": 1, "roster_max": 40, "min_goalkeepers": 0, "max_goalkeepers": 6}
    base.update(kw)
    return PoolState(**base)


def test_a_player_who_is_not_his_classs_best_still_has_a_price():
    """Regression. The buy branch used to seat the bought player at rank 1 by
    construction while the walk branch let the class's genuine best sit there,
    so buy - walk was negative for everyone but that best whenever the weights
    are cliff-shaped -- and on the real board 540 of 553 players priced at 0.
    Which rank he carries is the DP's decision: a second striker worth 222
    against a best of 230 is bought as the bench man, not as the starter."""
    board = price_board(cliff_state(), CFG)
    prices = [board.prices[200 + i].band.p50 for i in range(4)]
    assert all(x > 0 for x in prices[:3]), prices               # the class has three ranks and they were 0, 0 before
    assert prices[3] == 0, prices                               # a fourth striker fills no rank: he really is worth nothing
    assert prices == sorted(prices, reverse=True), prices
    second = board.prices[201]
    assert second.rank_weight == CLIFF[1] and second.buy_value >= second.walk_value    # bought as the first bench


def test_a_max_price_is_non_increasing_down_a_classs_value_ranking():
    """A worse player is never worth more: the property the all-zero board
    satisfied vacuously, checked class by class on a 553-player pool -- which
    has more players per class than the DP takes as candidates, so both ways
    of pricing a man (his own knapsack, or the class's curves for a player no
    table holds) are on the same ranking."""
    board = price_board(state(big_pool(), roster_min=23), CFG)
    ranked: dict[str, list] = {}
    for p in sorted(big_pool(), key=lambda p: (-p.value_p50, p.player_id)):
        ranked.setdefault(p.role_class, []).append(board.prices[p.player_id].band.p50)
    for cls, prices in ranked.items():
        assert len(prices) > CFG.candidates_per_class, cls
        assert prices == sorted(prices, reverse=True), (cls, prices[:12])
        assert prices[1] > 0 and prices[2] > 0, (cls, prices[:12])            # the #2 and #3 of a populated class
    assert sum(1 for p in board.prices.values() if p.band.p50 > 0) > len(board.prices) // 2


def test_every_player_is_priced_with_himself_out_of_the_pool():
    """One mode (Phase 2a's decision): a player's walk-away plan never counts
    him. Removing a candidate from the pool must therefore leave every other
    price in his class where it was -- they were already priced without him
    in the walk branch -- except where his absence changes what the class can
    field at all, which is the scarcity effect and moves prices up, never down."""
    pool = small_pool()
    pc = by_class(pool, "Pc")
    before = price_board(state(), CFG)
    without = price_board(state(tuple(p for p in pool if p.player_id != pc[0].player_id)), CFG)
    for p in pc[1:]:
        assert without.prices[p.player_id].band.p50 >= before.prices[p.player_id].band.p50
    # and his own price is what the board said it was when he was on it: the
    # board is one computation, not a lot-by-lot re-solve that could disagree with itself
    again = price_board(state(), CFG)
    assert again.prices[pc[0].player_id] == before.prices[pc[0].player_id]


def test_one_pricing_function_is_deterministic():
    a = price_board(state(), CFG).to_dict()
    b = price_board(state(), CFG).to_dict()
    assert a == b


def test_a_target_is_soft_and_a_departure_is_reported():
    plain = price_board(state(), CFG)
    nudged_weights = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=CFG.bench_weight,
                                  targets={"W": 3}, target_weight=CFG.target_weight)
    nudged = price_board(state(weights=nudged_weights, targets={"W": 3}), CFG)
    assert nudged.composition["W"] >= plain.composition["W"] and nudged.targets_departed == ()
    impossible = price_board(state(weights=nudged_weights, targets={"W": 9}), CFG)
    assert impossible.targets_departed == ("W",) and impossible.completion_value > float("-inf")


def test_a_budget_share_caps_a_class():
    capped = price_board(state(class_budget_share={"Pc": 0.1}), CFG)
    assert capped.credits_by_class["Pc"] <= 50
    assert capped.prices[by_class(small_pool(), "Pc")[0].player_id].band.p50 <= 50


def test_the_reserve_keeps_one_credit_per_unfilled_slot():
    """Reserving credits shrinks the budget, which can buy fewer players,
    which needs a larger reserve: the board is only coherent if the reserve
    it prints covers the slots the completion it prints leaves unfilled."""
    filled = price_board(state(roster_min=23), CFG)
    assert filled.reserve == 0 and filled.budget == 500          # the completion already reaches the minimum
    for roster_min in (25, 30, 35, 40):
        board = price_board(state(roster_min=roster_min), CFG)
        bought = sum(board.composition.values())
        assert board.reserve > 0, roster_min                      # the completion falls short of the minimum
        assert board.reserve >= roster_min - bought, (roster_min, board.reserve, bought)
        assert board.budget == 500 - board.reserve
        assert all(p.band.p75 <= board.budget for p in board.prices.values())


def test_the_roster_maximum_binds_through_a_slot_price():
    """Nothing in the demand bounds the roster at the league's maximum, so a
    tight maximum is enforced by charging every player a slot price -- the
    shadow price of a roster place -- found by bisection until the
    completion fits; a loose maximum costs nothing."""
    loose = price_board(state(roster_max=40), CFG)
    assert loose.slot_price == 0.0
    tight = price_board(state(roster_max=8), CFG)
    assert tight.slot_price > 0 and sum(tight.composition.values()) <= 8
    assert tight.composition["Por"] >= 2 and tight.composition["Dc"] >= 2         # the hard minimums still hold
    assert all(0 <= p.band.p25 <= p.band.p50 <= p.band.p75 <= tight.budget for p in tight.prices.values())
    assert explain(tight, by_class(small_pool(), "Pc")[0].player_id)["slot_price"] == tight.slot_price


def test_a_pool_class_the_weights_do_not_know_is_refused():
    bad = small_pool() + (player(999, "Xy", 50, 3),)
    with pytest.raises(ValueError, match="Xy"):
        price_board(state(bad), CFG)


def test_a_board_is_valid_json_even_where_a_branch_is_impossible():
    """-inf is a real answer inside -- no completion exists without him, or
    his class has no slot left -- and JSON has no such number, so a board
    reports the impossible branch as null rather than -Infinity, and so does
    the trace explain() hands the model."""
    saturated = price_board(state(owned=tuple(OwnedPlayer(i, "Por", 50.0) for i in range(CFG.max_goalkeepers))), CFG)
    por = by_class(small_pool(), "Por")[0]
    assert saturated.prices[por.player_id].buy_value == float("-inf")          # inside, the branch is impossible
    d = json.loads(json.dumps(saturated.to_dict(), allow_nan=False))           # outside, it is null
    assert d["prices"][str(por.player_id)]["buy_value"] is None
    assert d["prices"][str(por.player_id)]["walk_value"] == saturated.completion_value
    assert json.loads(json.dumps(explain(saturated, por.player_id), allow_nan=False))["buy_value"] is None
    keeperless = price_board(state(tuple(p for p in small_pool() if p.role_class != "Por")), CFG)
    assert keeperless.completion_value == float("-inf")                        # two goalkeepers are a hard minimum
    assert json.loads(json.dumps(keeperless.to_dict(), allow_nan=False))["completion_value"] is None


def test_explain_reads_back_the_trace():
    pool = small_pool()
    pc = by_class(pool, "Pc")[0]
    board = price_board(state(), CFG)
    trace = explain(board, pc.player_id)
    assert trace["player_id"] == pc.player_id and trace["band"] == board.prices[pc.player_id].band.to_dict()
    assert trace["inflation"] == board.inflation and trace["composition"] == board.composition
    assert trace["slot_price"] == board.slot_price
    if trace["band"]["p50"] > 0:                                               # at his p50 max price, buying is worth at least walking
        assert trace["walk_value"] <= trace["buy_value"] + 1e-9
    with pytest.raises(KeyError):
        explain(board, 424242)


def big_pool(n=553, seed=7):
    rng = np.random.default_rng(seed)
    pool = []
    for pid in range(n):
        cls = ROLE_CLASSES[pid % len(ROLE_CLASSES)]
        value = float(np.exp(rng.normal(4.3, 0.6)))            # ~ 75 fantapunti, long right tail
        quot = int(max(1, min(40, round(value / 6 + rng.normal(0, 2)))))
        pool.append(player(pid, cls, value, quot))
    return tuple(pool)


LATENCY_BUDGET = 0.5


def test_a_full_board_re_prices_inside_the_latency_budget():
    """The spec's constraint that keeps the model out of the loop, at the
    budget Phase 2a set when it chose one exact mode: the whole 553-player
    board -- every player priced with himself out of the pool -- must re-price
    in under half a second. Measured 2026-08-30 on the auction laptop: 189-241
    ms per board (the focused-only board this replaced took 28 ms), so the
    budget holds with about twice the headroom. A state change arrives once
    per sale, which is once every half a minute at the fastest; a quarter of a
    second on that cadence is what a human-paced auction never notices."""
    st = state(big_pool(), roster_min=23)
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        board = price_board(st, CFG)
        timings.append(time.perf_counter() - start)
    assert min(timings) < LATENCY_BUDGET, timings
    assert len(board.prices) == 553


def test_pricing_yml_is_loaded_and_validated(tmp_path, monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import pricing_yml_path

    assert load_pricing_config(pricing_yml_path()) == PricingConfig()          # the committed file is the defaults
    path = tmp_path / "pricing.yml"
    path.write_text("bench_weight: 0.2\nmax_per_class: 5\n")
    cfg = load_pricing_config(path)
    assert cfg.bench_weight == 0.2 and cfg.max_per_class == 5 and cfg.inflation_ceiling == 2.5
    # `.nan` / `.inf` are floats, and nothing range-checks a knob, so they used
    # to load: bench_weight NaN makes every rank weight NaN and every max price
    # with it, and neither survives the canonical_json that model_hash and the
    # stored config both go through.
    for bad in ("bench_weight: heavy\n", "unknown_knob: 1\n", "- a list\n", "max_per_class: 2.5\n",
                "bench_weight: .nan\n", "inflation_ceiling: .inf\n"):
        path.write_text(bad)
        with pytest.raises(PricingConfigError):
            load_pricing_config(path)


def _curve_scalar(costs: np.ndarray, values: np.ndarray, weights: np.ndarray, budget: int,
                   penalty: float = 0.0) -> np.ndarray:
    """The descending-`j` loop `_curve` replaced -- one rank updated at a
    time, in item order, at k times the Python overhead -- kept here only as
    the reference `test_curve_matches_the_scalar_reference` checks the
    vectorised version against. Never imported by the production module."""
    w = np.atleast_2d(np.asarray(weights, dtype=np.float64))
    k = w.shape[1]
    dp = np.full((w.shape[0], k + 1, budget + 1), float("-inf"))
    dp[:, 0, :] = 0.0
    for cost, value in zip(costs.tolist(), values.tolist()):
        if cost > budget:
            continue
        for j in range(k, 0, -1):
            gain = dp[:, j - 1, :budget + 1 - cost] + (w[:, j - 1, None] * value - penalty)
            np.maximum(dp[:, j, cost:], gain, out=dp[:, j, cost:])
    return dp


def test_curve_matches_the_scalar_reference():
    """The plan's binding equality constraint (global constraints: "the
    vectorised board must equal the old exact board"), encoded directly. Every
    other assertion on `_curve`'s output in this file is a shape or ordering
    invariant -- monotone under removal, non-increasing down a ranking,
    deterministic, under budget -- and a `_curve` that selected an item
    twice, or shifted the rank axis by one, would still satisfy all of them
    while raising completion values. Only a numeric comparison against the
    descending-j reference catches that, so this asserts exact equality
    (`np.array_equal`), not a tolerance: a loosened tolerance would hide the
    very divergence this test exists to catch."""
    rng = np.random.default_rng(20260830)
    penalties = (0.0, 0.7, 13.5)
    shapes = [(0, 0, 1, 1), (0, 40, 3, 2), (5, 0, 4, 1)]                      # empty pool, zero budget, zero-cost-only
    shapes += [(int(rng.integers(0, 41)), int(rng.integers(0, 121)), int(rng.integers(1, 7)),
               int(rng.integers(1, 5))) for _ in range(21)]                  # n <= 40, budget <= 120, k <= 6, 1-4 rows
    for trial, (n, budget, k, rows) in enumerate(shapes):
        penalty = penalties[trial % len(penalties)]
        costs = rng.integers(0, budget + 21, size=n).astype(np.int64) if n else np.zeros(0, dtype=np.int64)
        if n >= 1:
            costs[0] = 0                          # a free item
        if n >= 2:
            costs[-1] = budget + 7                 # an item the budget can never afford
        values = rng.uniform(0.0, 100.0, size=n)
        weights = rng.uniform(0.0, 1.0, size=(rows, k))
        vectorised = _curve(costs, values, weights, budget, penalty)
        scalar = _curve_scalar(costs, values, weights, budget, penalty)
        assert np.array_equal(vectorised, scalar), (n, budget, k, rows, penalty)
