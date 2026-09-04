from itertools import pairwise

import pytest
from fantaclaude.model.demand import (
    ROLE_CLASSES,
    hard_minimums,
    module_demand,
    pin_class,
    player_classes,
    rank_weights,
    remaining_weights,
    role_class,
    satisfiable_demand,
)
from fantaclaude.model.modules import load_modules
from fantaclaude.model.roles import Role

R = frozenset
FOLD = {"teams": 8, "max_rank": 6, "bench_weight": 0.1}
RANK = {k: v for k, v in FOLD.items() if k != "teams"}    # rank_weights takes no `teams` -- only satisfiable_demand does


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
    # a class floor the roster must fill extends the ranks too, at bench weight: a forced third keeper is a bench keeper
    floored = rank_weights(module_demand(load_modules()), max_rank=6, bench_weight=0.1, min_ranks={"Por": 3})
    assert floored["Por"] == (1.0, 0.1, 0.05) and floored["Pc"] == base["Pc"]
    with pytest.raises(ValueError, match="Xy"):
        rank_weights(module_demand(load_modules()), max_rank=4, bench_weight=0.1, targets={"Xy": 1})


def test_hard_minimums_are_the_slots_every_module_needs_from_one_class():
    assert hard_minimums(load_modules()) == {"Por": 1, "Dc": 2}


def listone_shaped_supply():
    """A supply with the real listone's shape: nobody carries Dd or Ds alone,
    so every flank player pins to E or to Dc and the flank classes take none
    of the pool."""
    supply = []
    for role, n in ((Role.Por, 70), (Role.Dc, 90), (Role.E, 40), (Role.M, 68), (Role.C, 60), (Role.W, 25),
                    (Role.T, 11), (Role.A, 55), (Role.Pc, 61)):
        supply += [R({role})] * n
    for roles, n in ((R({Role.Ds, Role.E}), 31), (R({Role.Dd, Role.E}), 29), (R({Role.Dc, Role.Ds}), 19),
                     (R({Role.Dc, Role.Dd}), 15), (R({Role.Dd, Role.Ds, Role.E}), 8)):
        supply += [roles] * n
    return tuple(supply)


def test_demand_no_player_can_pin_to_is_folded_onto_the_classes_that_field_it():
    """Dd and Ds each draw half a slot of every module, and no player in the
    listone ever pins to them -- a Dd is always an E or a Dc first, by demand.
    That demand has to reach the classes whose players actually fill the
    flanks, or it is never priced and E and Dc are priced as though they only
    had to cover their own slots."""
    supply = listone_shaped_supply()
    raw = module_demand(load_modules())
    weights = rank_weights(raw, **RANK)
    assert {pin_class(roles, weights) for roles in supply}.isdisjoint({"Dd", "Ds"})
    folded = satisfiable_demand(raw, supply, **FOLD).by_module
    assert all("Dd" not in by_class and "Ds" not in by_class for by_class in folded.values())
    # 4-3-3 draws one Dd and one Ds; of the 52 Dd players 37 pin to E and 15 to
    # Dc, of the 58 Ds players 39 pin to E and 19 to Dc
    assert folded["433"]["E"] == pytest.approx(raw["433"].get("E", 0.0) + 37 / 52 + 39 / 58)
    assert folded["433"]["Dc"] == pytest.approx(raw["433"]["Dc"] + 15 / 52 + 19 / 58)
    # and the classes that field the flanks are worth more per rank for it
    after = rank_weights(folded, **RANK)
    assert after["E"][0] > weights["E"][0] and after["Dc"][2] > weights["Dc"][2]
    assert after["M"] == weights["M"] and after["Pc"] == weights["Pc"]


def test_folding_conserves_demand_and_leaves_none_of_it_unsatisfiable():
    supply = listone_shaped_supply()
    raw = module_demand(load_modules())
    folded = satisfiable_demand(raw, supply, **FOLD).by_module
    for code, by_class in folded.items():
        assert sum(by_class.values()) == pytest.approx(sum(raw[code].values())), code
        assert min(by_class.values()) > 0.0, code
    pinned = {pin_class(roles, rank_weights(folded, **RANK)) for roles in supply}
    wanted = {cls for by_class in folded.values() for cls, d in by_class.items() if d > 0}
    assert wanted <= pinned


def test_a_listone_that_can_pin_to_every_class_is_left_alone():
    """The fold is driven by the supply, never by a typed list of classes: give
    it players who do pin to the flanks and it changes nothing."""
    raw = module_demand(load_modules())
    supply = (*listone_shaped_supply(), *([R({Role.Dd})] * 12), *([R({Role.Ds})] * 12))
    assert satisfiable_demand(raw, supply, **FOLD).by_module == {code: dict(by_class) for code, by_class in raw.items()}


def test_a_class_no_player_carries_at_all_still_conserves_the_eleven():
    """Nobody in the listone can play there, so the slot's worth goes to
    whatever else the module fields rather than evaporating."""
    raw = module_demand(load_modules())
    supply = tuple(roles for roles in listone_shaped_supply() if "W" not in player_classes(roles))
    folded = satisfiable_demand(raw, supply, **FOLD).by_module
    for code, by_class in folded.items():
        assert sum(by_class.values()) == pytest.approx(sum(raw[code].values())), code
    assert all("W" not in by_class for by_class in folded.values())


def test_the_fold_is_continuous_in_the_shortfall():
    """One listed pure Dd used to hand the class its whole half-slot back
    and move every price on the board. The class keeps the share of its
    demand its supply covers: n pure Dd against the 6/11 x 8 = 4.36 starting
    slots the league draws from Dd, never more than all of it, never less
    than nothing, and the eleven units of every module conserved."""
    raw = module_demand(load_modules())
    base = listone_shaped_supply()
    need = 6 / 11 * 8
    for n in (0, 1, 2, 4, 5):
        folded = satisfiable_demand(raw, (*base, *([R({Role.Dd})] * n)), **FOLD)
        kept = folded.kept["Dd"]
        # min(1, n / need) is itself non-decreasing in n, so an assertion that kept rises with n
        # would add nothing on top of this -- the interesting monotonicity is across the
        # fixed-point iteration, not across these calls, and this loop does not exercise that.
        assert kept == pytest.approx(min(1.0, n / need))
        dd = sum(m.get("Dd", 0.0) for m in folded.by_module.values()) / len(raw)
        assert dd == pytest.approx(6 / 11 * kept)
        for code, by_class in folded.by_module.items():
            assert sum(by_class.values()) == pytest.approx(11.0), code
        assert folded.kept["Ds"] == 0.0 and folded.kept["E"] == 1.0
    none = satisfiable_demand(raw, base, **FOLD)
    assert none.kept["Dd"] == 0.0 and all("Dd" not in m for m in none.by_module.values())
    assert none.to_dict()["kept"]["Dd"] == 0.0 and set(none.to_dict()) == {"by_module", "kept", "iterations"}


def test_pin_class_takes_the_class_with_the_most_demand():
    weights = rank_weights(module_demand(load_modules()), max_rank=4, bench_weight=0.1)
    assert pin_class(R({Role.Pc}), weights) == "Pc"
    assert pin_class(R({Role.Ds, Role.E}), weights) == "E"                  # E: ~1 slot per module; Ds: 6 of 11
    assert pin_class(R({Role.B, Role.Ds, Role.E}), weights) == "Dc"         # B folds into Dc, and Dc draws two full slots everywhere
    assert pin_class(R({Role.B}), weights) == "Dc"
    with pytest.raises(ValueError):
        pin_class(R(), weights)


def test_a_pin_follows_the_ranks_my_roster_leaves_open():
    """pin_class values a multi-role player under the class with the most
    demand league-wide, fixed when the run is written. On the night of
    2026-09-03 twelve unsold men sat pinned to a full E at band 0 while
    holding T, C or M roles the completion still paid 0.55-0.86 for. The
    board re-pins against the ranks my roster leaves open: the same
    criterion over the remaining weights, so an empty roster pins exactly
    as the run did and a full class hands its men to their other roles."""
    weights = {**{cls: (0.0,) for cls in ROLE_CLASSES}, "E": (0.9, 0.8), "T": (0.6, 0.1)}
    both = R({Role.E, Role.T})
    assert pin_class(both, weights) == "E"
    assert remaining_weights(weights, {}) == weights
    assert remaining_weights(weights, {"E": 1})["E"] == (0.8,) and remaining_weights(weights, {"E": 5})["E"] == ()
    assert pin_class(both, remaining_weights(weights, {"E": 1})) == "E"          # 0.8 still beats 0.7
    assert pin_class(both, remaining_weights(weights, {"E": 2})) == "T"          # E is full: his T role is what is left
    assert pin_class(R({Role.E}), remaining_weights(weights, {"E": 2})) == "E"   # a one-role man has nowhere else to go
