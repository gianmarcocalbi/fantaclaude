import itertools
import random

import pytest
from fantaclaude.analysis.weekly import (
    ADAPTED_MALUS,
    ForecastError,
    ForecastRow,
    RosterPlayer,
    choose_xi,
)
from fantaclaude.analysis.weekly.xi import close_calls, contingencies, order_bench
from fantaclaude.model.modules import Fit, Module, Slot
from fantaclaude.model.roles import Role

R = frozenset
SMALL = Module(code="t", label="test", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R({Role.B}), R({Role.Ds})),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("A/Pc", R({Role.A, Role.Pc}), R({Role.W}), R({Role.T}))))
MODULES = {"t": SMALL}


def _row(pid, p_start, fv, *, diffidato=False):
    return ForecastRow(pid, f"p{pid}", "INT", "A", ("A",), int(p_start * 100), p_start, fv, None, p_start * fv, "published",
                       trace={"diffidato": "4 gialli" if diffidato else None})


def _roster(spec):
    return [RosterPlayer(pid, f"p{pid}", R(roles), 1, True) for pid, roles in spec]


ROSTER = _roster([(1, {Role.Por}), (2, {Role.Por}), (3, {Role.Dc}), (4, {Role.B}), (5, {Role.M}), (6, {Role.C, Role.T}),
                  (7, {Role.A}), (8, {Role.W}), (9, {Role.Pc}), (10, {Role.Ds})])
ROWS = {1: _row(1, 0.9, 6.0), 2: _row(2, 0.1, 6.0), 3: _row(3, 0.9, 6.5), 4: _row(4, 0.8, 6.2, diffidato=True),
        5: _row(5, 0.5, 6.4), 6: _row(6, 0.9, 6.3), 7: _row(7, 0.9, 7.5), 8: _row(8, 0.7, 7.0), 9: _row(9, 0.6, 7.2),
        10: _row(10, 0.9, 5.5)}


def test_the_bench_starts_with_the_goalkeeper_and_orders_the_rest_by_coverage():
    xi = choose_xi(ROSTER, ROWS, MODULES, ["t"])
    assert [s.player_id for s in xi.slots] == [1, 3, 6, 7]
    bench = order_bench(ROSTER, xi, ROWS, SMALL, bench_size=4)
    ids = [e.player_id for e in bench.order]
    assert ids[0] == 2 and len(ids) == 4 and bench.size == 4
    # p4 (B) is the only outfielder who fits Dc, adapted: his coverage is the Dc starter's miss (0.1) x (ep - p x malus)
    p4 = next(e for e in bench.order if e.player_id == 4)
    assert p4.covers == ("Dc",) and p4.coverage == pytest.approx(0.1 * (0.8 * 6.2 - 0.8 * ADAPTED_MALUS))
    assert p4.diffidato is True
    assert bench.uncovered == ("M/C",)                                  # p5 (M) is fifth by coverage and the bench holds four
    assert order_bench(ROSTER, xi, ROWS, SMALL, bench_size=5).uncovered == ()
    # ordering: coverage descending, then expected points
    assert [e.coverage for e in bench.order[1:]] == sorted((e.coverage for e in bench.order[1:]), reverse=True)


def test_an_uncovered_slot_is_named_and_forced_only_never_counts_as_cover():
    roster = _roster([(1, {Role.Por}), (3, {Role.Dc}), (5, {Role.M}), (7, {Role.A}), (10, {Role.Ds}), (11, {Role.T})])
    rows = {pid: _row(pid, 0.9, 6.0) for pid in (1, 3, 5, 7, 10, 11)}
    xi = choose_xi(roster, rows, MODULES, ["t"])
    bench = order_bench(roster, xi, rows, SMALL, bench_size=5)
    assert [e.player_id for e in bench.order] == [11, 10] or [e.player_id for e in bench.order] == [10, 11]
    ds = next(e for e in bench.order if e.player_id == 10)
    assert ds.covers == () and ds.coverage == 0.0                       # Ds fits Dc only through a forced substitution
    assert bench.uncovered == ("Por", "Dc", "A/Pc")                     # the T covers M/C adapted and nothing else


def test_an_excluded_player_is_on_neither_list_and_the_bench_respects_its_size():
    xi = choose_xi(ROSTER, ROWS, MODULES, ["t"], excluded=frozenset({7}))
    assert 7 not in {s.player_id for s in xi.slots}
    bench = order_bench(ROSTER, xi, ROWS, SMALL, bench_size=2, excluded=frozenset({7}))
    assert 7 not in {e.player_id for e in bench.order} and len(bench.order) == 2


def _brute(module, roster, natural, adapted, banned):
    best = None
    indexes = [i for i in range(len(roster)) if roster[i].player_id not in banned]
    for perm in itertools.permutations(indexes, len(module.slots)):
        total = 0.0
        for slot, i in zip(module.slots, perm):
            fit = slot.fit(roster[i].roles)
            if fit is Fit.NATURAL:
                total += natural[i]
            elif fit is Fit.ADAPTED:
                total += adapted[i]
            else:
                break
        else:
            best = total if best is None or total > best else best
    return best


def test_contingencies_are_re_solves_and_agree_with_brute_force():
    rng = random.Random(11)
    for _ in range(40):
        roster = rng.sample(ROSTER, k=rng.randint(5, 8))
        rows = {p.player_id: _row(p.player_id, round(rng.uniform(0.3, 1.0), 2), round(rng.uniform(5, 8), 2)) for p in roster}
        try:
            xi = choose_xi(roster, rows, MODULES, ["t"])
        except ForecastError:
            continue
        plans = contingencies(roster, rows, MODULES, ["t"], xi, threshold=1.01)      # every starter gets a plan
        assert [c.player_id for c in plans] == [s.player_id for s in xi.slots]
        natural = [rows[p.player_id].expected_points for p in roster]
        adapted = [rows[p.player_id].expected_points - rows[p.player_id].p_start * ADAPTED_MALUS for p in roster]
        for c in plans:
            oracle = _brute(SMALL, roster, natural, adapted, {c.player_id})
            if oracle is None:
                assert c.note is not None and c.points_lost is None
            else:
                assert c.points_lost == pytest.approx(xi.total - oracle)
                assert c.player_id in {s.player_id for s in c.leaves}


def test_contingencies_only_for_doubtful_starters_and_they_name_who_enters():
    xi = choose_xi(ROSTER, ROWS, MODULES, ["t"])
    plans = contingencies(ROSTER, ROWS, MODULES, ["t"], xi, threshold=0.75)
    assert plans == []                                                  # every starter is at 0.9
    rows = {**ROWS, 7: _row(7, 0.7, 7.5)}                                # 5.25 still beats the Pc's 4.32: he starts, doubtfully
    xi = choose_xi(ROSTER, rows, MODULES, ["t"])
    [plan] = contingencies(ROSTER, rows, MODULES, ["t"], xi, threshold=0.75)
    assert plan.player_id == 7 and plan.p_start == 0.7 and plan.module == "t" and plan.module_changes is False
    assert [s.player_id for s in plan.enters] == [9] and [s.player_id for s in plan.leaves] == [7]
    assert plan.points_lost == pytest.approx(rows[7].expected_points - rows[9].expected_points)


# A second module, distinct from `SMALL`/`MODULES`: two allowed modules whose
# 4th slot differs (A/Pc vs W) is the minimum needed to make a re-solve
# capable of changing which module is best -- with one module only (as in
# every test above) `alt.module` can never differ from `xi.module`, so
# `module_changes` would be untested. Built so the flip is forced by the
# numbers, not incidental (verified by hand and against the solver below).
FLIP_A = Module(code="fa", label="flip-a", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R(), R()),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("A/Pc", R({Role.A, Role.Pc}), R({Role.W}), R())))
FLIP_B = Module(code="fb", label="flip-b", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R(), R()),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("W", R({Role.W}), R({Role.Pc}), R())))
FLIP_MODULES = {"fa": FLIP_A, "fb": FLIP_B}
FLIP_ROSTER = _roster([(1, {Role.Por}), (3, {Role.Dc}), (5, {Role.M}), (6, {Role.C, Role.W}),
                       (7, {Role.A}), (9, {Role.Pc})])
FLIP_ROWS = {1: _row(1, 0.9, 6.0), 3: _row(3, 0.9, 6.5), 5: _row(5, 0.5, 6.4), 6: _row(6, 0.9, 6.3),
            7: _row(7, 0.3, 18.0), 9: _row(9, 0.3, 3.0)}


def test_a_doubtful_starters_contingency_can_flip_the_module_and_moves_more_than_one_player():
    # p6 (C, W) is the pivot: flip-a's only 3rd/4th-slot pair worth playing is
    # p6 at M/C (5.67) beside p7 at A/Pc (5.4) -- p6 adapted at A/Pc (4.77)
    # plus p5 at M/C (3.2) is worse (7.97 < 11.07) while p7 starts. flip-a
    # totals 22.32; flip-b (p6 at W natural 5.67 beside p5 at M/C 3.2 beats
    # p6 at M/C beside p9 adapted at W 0.6, 8.87 > 6.27) totals a fixed 20.12
    # regardless of p7, who fits neither of its slots. flip-a wins overall,
    # fielding the doubtful p7 (p_start 0.3) at A/Pc.
    xi = choose_xi(FLIP_ROSTER, FLIP_ROWS, FLIP_MODULES, ["fa", "fb"])
    assert xi.module == "fa" and xi.total == pytest.approx(22.32)
    assert [s.player_id for s in xi.slots] == [1, 3, 6, 7]
    # Exclude p7 and flip-a drops to 19.22 (p6 moves to A/Pc adapted, p5 in at
    # M/C: 4.77 + 3.2 = 7.97) -- below flip-b's untouched 20.12, so the
    # re-solve's best module changes, not merely its A/Pc occupant.
    [plan] = contingencies(FLIP_ROSTER, FLIP_ROWS, FLIP_MODULES, ["fa", "fb"], xi, threshold=0.75)
    assert plan.player_id == 7 and plan.p_start == 0.3 and plan.module == "fb" and plan.module_changes is True
    assert [(s.slot, s.player_id) for s in plan.enters] == [("M/C", 5)]
    assert [(s.slot, s.player_id) for s in plan.leaves] == [("A/Pc", 7)]
    assert plan.points_lost == pytest.approx(2.2)
    # The module flip moves a second player besides the excluded starter and
    # the one who enters: p6 himself is re-solved from M/C to W -- the
    # cascading change `enters`/`leaves` (player-id membership only) does not
    # surface, and exactly what a same-slot substitution shortcut could never
    # produce.
    alt = choose_xi(FLIP_ROSTER, FLIP_ROWS, FLIP_MODULES, ["fa", "fb"], excluded=frozenset({7}))
    assert next(s for s in xi.slots if s.player_id == 6).slot == "M/C"
    assert next(s for s in alt.slots if s.player_id == 6).slot == "W"


def test_close_calls_name_the_best_excluded_fit_per_slot_within_the_margin():
    rows = {**ROWS, 8: _row(8, 0.9, 8.0)}                                # W at 7.2 - 0.9 malus = 6.3 net vs A p7 at 6.75
    xi = choose_xi(ROSTER, rows, MODULES, ["t"])
    calls = close_calls(ROSTER, xi, rows, SMALL, margin=0.5, limit=3)
    assert [c.slot for c in calls] == ["A/Pc"]                           # every other slot's best alternative is over a point away
    call = calls[0]
    assert call.player_in["player_id"] == 7 and call.player_out["player_id"] == 8
    assert call.gap == pytest.approx(6.75 - (0.9 * 8.0 - 0.9 * ADAPTED_MALUS))
    assert call.player_out["source"] == "published"
    assert close_calls(ROSTER, xi, rows, SMALL, margin=0.5, limit=0) == []
