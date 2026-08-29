from itertools import pairwise

import pytest
from fantaclaude.model.demand import (
    ROLE_CLASSES,
    hard_minimums,
    module_demand,
    pin_class,
    player_classes,
    rank_weights,
    role_class,
)
from fantaclaude.model.modules import load_modules
from fantaclaude.model.roles import Role

R = frozenset


def test_role_classes_fold_b_into_dc():
    assert ROLE_CLASSES == ("Por", "Dd", "Ds", "Dc", "E", "M", "C", "W", "T", "A", "Pc")
    assert role_class(Role.B) == "Dc" and role_class(Role.Pc) == "Pc"
    assert player_classes(R({Role.B, Role.Ds, Role.E})) == {"Dc", "Ds", "E"}


def test_every_module_spreads_eleven_units_of_demand():
    demand = module_demand(load_modules())
    assert set(demand) == set(load_modules())
    for code, by_class in demand.items():
        assert sum(by_class.values()) == pytest.approx(11.0), code
        assert set(by_class) <= set(ROLE_CLASSES)
    # 3-4-3: Por 1; Dc, Dc, Dc/B -> 3; E, E -> 2; M/C -> 0.5 M + 0.5 C; C -> 1; W/A x2 -> 1 W + 1 A; A/Pc -> 0.5 + 0.5
    assert demand["343"] == pytest.approx({"Por": 1, "Dc": 3, "E": 2, "M": 0.5, "C": 1.5, "W": 1, "A": 1.5, "Pc": 0.5})
    assert demand["433"]["Dc"] == 2 and demand["433"]["Ds"] == 1 and demand["433"]["Dd"] == 1
    assert "E" not in demand["433"]


def test_rank_weights_follow_module_coverage_and_floor_at_the_bench():
    weights = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1)
    assert set(weights) == set(ROLE_CLASSES)
    for cls, w in weights.items():
        assert all(a >= b for a, b in pairwise(w)), cls                 # non-increasing in rank
        assert min(w) > 0 and max(w) <= 1.0
    # ranks: the peak demand of any module, rounded up, plus one bench slot
    assert {cls: len(w) for cls, w in weights.items()} == {"Por": 2, "Dd": 2, "Ds": 2, "Dc": 4, "E": 3, "M": 3, "C": 3,
                                                           "W": 3, "T": 3, "A": 3, "Pc": 2}
    assert weights["Por"] == (1.0, 0.1)
    assert weights["Dc"] == pytest.approx((1.0, 1.0, 5 / 11, 0.1))          # a third Dc in the five back-three modules
    assert weights["Ds"] == pytest.approx((6 / 11, 0.1))                    # a Ds slot in the six back-four modules
    # Pc: two A/Pc slots (a whole unit) in 3-4-1-2, 3-5-2, 4-4-2; A/Pc plus a third of T/A/Pc in 4-3-1-2; half a unit elsewhere
    assert weights["Pc"][0] == pytest.approx((3 * 1.0 + (0.5 + 1 / 3) + 7 * 0.5) / 11)
    # W: a whole unit in six modules and half a unit in three; the second rank's coverage (half a slot in 4-1-4-1) is
    # below the floor, so it is the first bench rank, and the third decays
    assert weights["W"] == pytest.approx(((6 + 3 * 0.5) / 11, 0.1, 0.05))
    assert rank_weights(module_demand(load_modules()), max_rank=2, bench_weight=0.1)["Dc"] == (1.0, 1.0)


def test_a_target_raises_the_weights_it_names_and_nothing_else():
    base = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1)
    nudged = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1,
                          targets={"W": 3, "Por": 2}, target_weight=0.8)
    assert nudged["W"] == (0.8, 0.8, 0.8) and nudged["Por"] == (1.0, 0.8)
    assert nudged["Dc"] == base["Dc"] and nudged["Pc"] == base["Pc"]
    extended = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1, targets={"Pc": 4})
    assert extended["Pc"] == (0.8, 0.8, 0.8, 0.8)                            # a target extends the ranks to reach it
    with pytest.raises(ValueError, match="Xy"):
        rank_weights(module_demand(load_modules()), max_rank=4, bench_weight=0.1, targets={"Xy": 1})


def test_hard_minimums_are_the_slots_every_module_needs_from_one_class():
    assert hard_minimums(load_modules()) == {"Por": 1, "Dc": 2}


def test_pin_class_takes_the_class_with_the_most_demand():
    weights = rank_weights(module_demand(load_modules()), max_rank=4, bench_weight=0.1)
    assert pin_class(R({Role.Pc}), weights) == "Pc"
    assert pin_class(R({Role.Ds, Role.E}), weights) == "E"                  # E: ~1 slot per module; Ds: 6 of 11
    assert pin_class(R({Role.B, Role.Ds, Role.E}), weights) == "Dc"         # B folds into Dc, and Dc draws two full slots everywhere
    assert pin_class(R({Role.B}), weights) == "Dc"
    with pytest.raises(ValueError):
        pin_class(R(), weights)
