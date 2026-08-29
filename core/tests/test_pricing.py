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
        assert price.expected_price >= 1 and not price.exact
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
        prices.append(price_board(state(rest, owned=owned), CFG, focus=target.player_id).prices[target.player_id].band.p50)
    assert prices == sorted(prices), prices                     # shrinking the Dc pool never lowers his price
    # only he is left and one Dc is required: walking away is infeasible, so the price is every credit
    # not needed by the other hard slots -- the two cheapest goalkeepers at their expected prices
    last = price_board(state(tuple(p for p in pool if p.role_class != "Dc") + (target,), owned=owned), CFG,
                       focus=target.player_id)
    por_costs = sorted(last.expected_prices[p.player_id] for p in by_class(pool, "Por"))
    assert last.prices[target.player_id].band.p50 == 500 - sum(por_costs[:2])
    assert last.prices[target.player_id].walk_value == float("-inf") and last.prices[target.player_id].exact


def test_excluding_a_player_raises_everyone_else_at_his_class_and_removes_him():
    pool = small_pool()
    dc = by_class(pool, "Dc")
    before = price_board(state(), CFG, exact=True)
    after = price_board(state(excluded=frozenset({dc[0].player_id})), CFG, exact=True)
    assert dc[0].player_id not in after.prices
    for p in dc[1:]:
        assert after.prices[p.player_id].band.p50 >= before.prices[p.player_id].band.p50
    assert all(after.prices[p.player_id].band.p50 >= 0 for p in pool if p.role_class != "Dc")


def test_owned_players_consume_ranks_and_bounds():
    pool = small_pool()
    por = by_class(pool, "Por")
    full = price_board(state(owned=tuple(OwnedPlayer(i, "Por", 50.0) for i in range(CFG.max_goalkeepers))), CFG)
    assert all(full.prices[p.player_id].band == Band(0, 0, 0) for p in por)          # no goalkeeper slot left
    assert full.composition["Por"] == 0
    one = price_board(state(owned=(OwnedPlayer(1, "Por", 120.0),)), CFG, focus=por[1].player_id)
    assert one.prices[por[1].player_id].rank_weight == WEIGHTS["Por"][1]              # he would be my second keeper


def test_the_focused_player_is_exact_and_matches_the_exact_board():
    pool = small_pool()
    pc = by_class(pool, "Pc")[0]
    focused = price_board(state(), CFG, focus=pc.player_id)
    every = price_board(state(), CFG, exact=True)
    assert focused.prices[pc.player_id].exact and not focused.prices[by_class(pool, "A")[0].player_id].exact
    assert focused.prices[pc.player_id] == every.prices[pc.player_id]
    assert all(price.exact for price in every.prices.values())


def test_one_pricing_function_is_deterministic():
    a = price_board(state(), CFG, exact=True).to_dict()
    b = price_board(state(), CFG, exact=True).to_dict()
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
    board = price_board(state(roster_min=23), CFG)
    bought = sum(board.composition.values())
    assert board.reserve == max(0, 23 - bought) and board.budget == 500 - board.reserve
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


def test_explain_reads_back_the_trace():
    pool = small_pool()
    pc = by_class(pool, "Pc")[0]
    board = price_board(state(), CFG, focus=pc.player_id)
    trace = explain(board, pc.player_id)
    assert trace["player_id"] == pc.player_id and trace["band"] == board.prices[pc.player_id].band.to_dict()
    assert trace["exact"] and trace["inflation"] == board.inflation and trace["composition"] == board.composition
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


def test_a_full_board_re_prices_inside_the_latency_budget():
    """The spec's constraint that keeps the model out of the loop: with one
    player on the block, the whole 553-player board must re-price in under
    100 ms (the tables are rebuilt; only the focused player pays for exactness)."""
    st = state(big_pool(), roster_min=23)
    focus = 5
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        board = price_board(st, CFG, focus=focus)
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.1, timings
    assert len(board.prices) == 553 and board.prices[focus].exact


def test_pricing_yml_is_loaded_and_validated(tmp_path, monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import pricing_yml_path

    assert load_pricing_config(pricing_yml_path()) == PricingConfig()          # the committed file is the defaults
    path = tmp_path / "pricing.yml"
    path.write_text("bench_weight: 0.2\nmax_per_class: 5\n")
    cfg = load_pricing_config(path)
    assert cfg.bench_weight == 0.2 and cfg.max_per_class == 5 and cfg.inflation_ceiling == 2.5
    for bad in ("bench_weight: heavy\n", "unknown_knob: 1\n", "- a list\n", "max_per_class: 2.5\n"):
        path.write_text(bad)
        with pytest.raises(PricingConfigError):
            load_pricing_config(path)
