"""What each Mantra role class is worth to a roster, derived from the modules.

The pricing DP pins every pool player to one role class and values the k-th
player of a class by how much of a starting slot he can expect: a weight in
[0, 1] per rank, read off modules.yml -- never typed. In each module every
slot's natural roles share one unit of demand equally (an "A/Pc" slot is
half an A and half a Pc; "Dc/B" is a whole Dc, since B is folded into the
Dc class -- it is natural only beside Dc and never appears alone in the
listone). The k-th player of class r then gets, in module m, whatever
fraction of m's demand for r is left after k-1 players took theirs, and
his weight is the average over the eleven modules: two Dc are a full slot
in every module, a third Dc is a slot in the five back-three modules
(5/11), a fourth is bench.

Demand has to be *satisfiable*, though, and the pin is what decides that.
A class can draw slots in every module and still take no player: Dd and Ds
each draw half of every module's eleven, but every player who can play
there is also an E or a Dc, both of which outweigh a flank, so `pin_class`
never pins anyone to Dd or Ds. `satisfiable_demand` keeps, for each class,
the share of its demand its own supply covers -- the players who pin to it
against the starting slots the league draws from it, the per-module demand
times the team count -- and moves the rest onto the classes its players do
pin to, in the proportion this listone supplies them, conserved module by
module and read off the listone at run time rather than typed. A listone
with enough pure Dd folds nothing; one with a single pure Dd keeps a
quarter of the class's demand rather than all of it, which is what keeps
one listed player from moving every price on the board (Phase 1 folded
all or nothing and warned about the edge; the fraction replaces the
warning). The retained share only ever falls across the fixed-point
iteration, so it terminates.

How many ranks a class has is demand too: the most slots any module draws
from the class, rounded up, plus `bench_slots` -- a fifth Pc is not a
roster slot anyone prices. A bench rank's floor is `bench_weight` (the
chance to start through injuries and rotation), decaying by `bench_decay`
for every further bench rank: the first backup plays sometimes, the third
never. A target in preferences.yml raises the weights of the ranks it
names to `target_weight` (and extends the ranks to reach it): a soft prior
the optimiser may still depart from, never a bound (spec, "Live
adjustments": `target`). Hard minimums are the slots every module needs
from one class alone (Por 1, Dc 2 -- no other role fills a "Dc" slot even
adapted): a roster without them can field nothing, so the pricing DP treats
a completion without them as worth -inf, which is what drives the last
needed Dc's price to the credits available.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .modules import Module, load_modules
from .roles import Role

ROLE_CLASSES: tuple[str, ...] = ("Por", "Dd", "Ds", "Dc", "E", "M", "C", "W", "T", "A", "Pc")
_MERGED: dict[Role, str] = {Role.B: "Dc"}


def role_class(role: Role) -> str:
    return _MERGED.get(role, role.value)


def player_classes(roles: frozenset[Role]) -> frozenset[str]:
    return frozenset(role_class(r) for r in roles)


def module_demand(modules: Mapping[str, Module] | None = None) -> dict[str, dict[str, float]]:
    """Module code -> role class -> the natural slots it draws, fractional
    for a composite slot; every module sums to eleven."""
    modules = load_modules() if modules is None else modules
    demand: dict[str, dict[str, float]] = {}
    for code, module in modules.items():
        by_class: dict[str, float] = {}
        for slot in module.slots:
            classes = player_classes(slot.natural)
            for cls in classes:
                by_class[cls] = by_class.get(cls, 0.0) + 1.0 / len(classes)
        demand[code] = by_class
    return demand


def rank_weights(demand_by_module: Mapping[str, Mapping[str, float]], *, max_rank: int, bench_weight: float,
                 bench_decay: float = 0.5, bench_slots: int = 1, targets: Mapping[str, int] | None = None,
                 target_weight: float = 0.8, min_ranks: Mapping[str, int] | None = None) -> dict[str, tuple[float, ...]]:
    """Class -> weight of the k-th player of that class, k = 1 .. the ranks
    the class has (the peak demand of any module, rounded up, plus
    bench_slots; a target extends them, and so does a class floor the
    roster must fill -- at bench weight, since a forced third keeper starts
    no more than a chosen one; never more than max_rank)."""
    unknown = sorted(set(targets or {}) - set(ROLE_CLASSES))
    if unknown:
        raise ValueError(f"target_composition names classes that do not exist: {unknown}; choose from {ROLE_CLASSES}")
    n = len(demand_by_module)
    # In module-code order, always: `coverage` is a floating-point sum over the
    # modules, so the same demand in a different dict order would price a
    # different board in the last bit. Sorting here makes that a property of the
    # function rather than a convention every caller has to remember -- the run
    # (analysis/valuation.py) and the live board (asta/pinned.py) both pre-sort,
    # and a third caller building a demand dict some other way must not be able
    # to get a quietly different answer. Not provable by test on this interpreter:
    # CPython >= 3.12's builtin sum() uses Neumaier compensated summation, so no
    # float vector triggers an order-sensitive result through it (a 400,000-vector
    # random search and a targeted mutation both found none, Task 10 review) --
    # correct and cheap to keep regardless, since neither is guaranteed by sum()'s
    # own contract.
    ordered = [demand_by_module[code] for code in sorted(demand_by_module)]
    weights: dict[str, tuple[float, ...]] = {}
    for cls in ROLE_CLASSES:
        peak = max((by_class.get(cls, 0.0) for by_class in ordered), default=0.0)
        ranks = math.ceil(peak - 1e-9) + bench_slots
        if targets:
            ranks = max(ranks, targets.get(cls, 0))
        if min_ranks:
            ranks = max(ranks, min_ranks.get(cls, 0))
        ranks = max(1, min(max_rank, ranks))
        coverage = [sum(min(1.0, max(0.0, by_class.get(cls, 0.0) - (k - 1))) for by_class in ordered) / n
                    if n else 0.0 for k in range(1, ranks + 1)]
        first_bench = next((k for k, c in enumerate(coverage, 1) if c < bench_weight), None)
        out: list[float] = []
        for k, weight in enumerate(coverage, 1):
            if first_bench is not None and k >= first_bench:
                weight = max(weight, bench_weight * bench_decay ** (k - first_bench))
            if targets and k <= targets.get(cls, 0):
                weight = max(weight, target_weight)
            out.append(weight)
        weights[cls] = tuple(out)
    return weights


def hard_minimums(modules: Mapping[str, Module] | None = None) -> dict[str, int]:
    """Class -> slots that every module fills from that class and no other."""
    modules = load_modules() if modules is None else modules
    minimums: dict[str, int] = {}
    for cls in ROLE_CLASSES:
        exclusive = [sum(1 for slot in module.slots if player_classes(slot.natural) == {cls}) for module in modules.values()]
        if exclusive and min(exclusive) > 0:
            minimums[cls] = min(exclusive)
    return minimums


# Below this, a demand remainder left after moving a class's fraction off it is
# indistinguishable from floating-point noise, so the key is dropped rather
# than kept at a value nobody would ever read as nonzero.
_FOLD_DUST = 1e-12

# The retained-fraction step below which the fixed-point iteration is treated
# as converged.
_KEPT_CONVERGENCE = 1e-12

# An iteration ceiling comfortably past the fixed point any real listone
# reaches -- each class's kept share only ever falls (never rises) across a
# pass, so this bounds the loop without ever being the reason it stops.
_MAX_FOLD_PASSES = len(ROLE_CLASSES) * 4


def _fold_into(demand: dict[str, dict[str, float]], cls: str, pins: Mapping[str, int], fraction: float) -> None:
    """Move `fraction` of `cls`'s demand, module by module, onto the classes
    `pins` counts -- never back onto `cls` itself."""
    targets = {target: count for target, count in pins.items() if target != cls}
    total = sum(targets.values())
    for by_class in demand.values():
        have = by_class.get(cls, 0.0)
        moved = have * fraction
        if not moved:
            continue
        if have - moved > _FOLD_DUST:
            by_class[cls] = have - moved
        else:
            by_class.pop(cls, None)
        if total:
            for target, count in targets.items():
                by_class[target] = by_class.get(target, 0.0) + moved * count / total
            continue
        # Nobody else in the listone carries the role, so there is no
        # distribution to read and the slot cannot be filled by anyone. Its
        # worth goes to whatever else the module fields, in proportion to what
        # that already draws: the eleven units are what a module is worth and
        # they have to land somewhere.
        #
        # Known inversion (Task 10 review, parked -- not fixed here): `targets`
        # only excludes `cls` itself, so this branch also fires for a class that
        # *is* carried but whose every carrier pins to the class itself (e.g. a
        # keeper, who has no other role to pin to) -- not only for a class
        # genuinely nobody carries (Ds). In that case a class's own scarcity
        # moves its demand away from itself onto whatever else the module
        # fields, which is the modelling backwards: a class with fewer carriers
        # should draw more of a module's remaining worth toward the classes
        # that do carry it, not spray its shortfall over classes that may not
        # even be able to field it. Latent on a real listone (`kept == 1`
        # everywhere there, so no carried class ever reaches this branch);
        # confirmed to be the root cause of the composition flip that forced
        # the `test_advisor.py` and `test_valuation.py` fixes in Task 10's
        # report. Left alone deliberately: fixing it is a modelling decision
        # about where an under-supplied-but-carried class's unmet demand
        # should go, not a defect repair, and it is not being taken unreviewed
        # this late in the plan.
        rest = sum(share for other, share in by_class.items() if other != cls)
        if rest <= 0:
            by_class[cls] = by_class.get(cls, 0.0) + moved
            continue
        for other, share in list(by_class.items()):
            if other != cls:
                by_class[other] = share + moved * share / rest


@dataclass(frozen=True)
class FoldedDemand:
    by_module: dict[str, dict[str, float]]      # module code -> class -> the demand priced, after the fold
    # class -> the retained fraction the fixed point settled at: min(1, supply / need) at
    # convergence, 1.0 meaning the class was never folded. Not the share of the class's own
    # raw demand that ended up priced in by_module -- classes fold in ROLE_CLASSES order within a
    # pass, so a class folded early can receive demand back from one folded later in the same
    # pass, and by_module's actual total for it can come out above or below kept x its raw share.
    kept: dict[str, float]
    iterations: int

    def to_dict(self) -> dict[str, Any]:
        return {"by_module": {code: dict(by_class) for code, by_class in self.by_module.items()},
                "kept": dict(self.kept), "iterations": self.iterations}


def satisfiable_demand(demand_by_module: Mapping[str, Mapping[str, float]], supply: Iterable[frozenset[Role]], *,
                       teams: int, max_rank: int, bench_weight: float, bench_decay: float = 0.5,
                       bench_slots: int = 1) -> FoldedDemand:
    """Module demand with every class's unsupplied share folded onto the
    classes its players do pin to, in the proportion the listone supplies.

    `need` is the league-wide starting slots the modules draw from a class
    (its average demand per module times the team count); `supply` is the
    players who pin to it at the current weights. A class keeps
    min(1, supply / need) of its demand. The pins depend on the weights and
    the weights on the demand, so it is iterated to a fixed point; the kept
    share is taken as the running minimum, so it never rises and the loop
    ends. Demand is conserved module by module."""
    players = tuple(supply)
    raw = {code: dict(by_class) for code, by_class in demand_by_module.items()}
    modules = len(raw) or 1
    need = {cls: sum(by_class.get(cls, 0.0) for by_class in raw.values()) / modules * teams for cls in ROLE_CLASSES}
    kept = dict.fromkeys(ROLE_CLASSES, 1.0)
    demand = raw
    iterations = 0
    for _ in range(_MAX_FOLD_PASSES):
        iterations += 1
        weights = rank_weights(demand, max_rank=max_rank, bench_weight=bench_weight, bench_decay=bench_decay,
                               bench_slots=bench_slots)
        pinned: dict[str, int] = {}
        pins_of: dict[str, dict[str, int]] = {}
        for roles in players:
            cls = pin_class(roles, weights)
            pinned[cls] = pinned.get(cls, 0) + 1
            for carried in player_classes(roles):
                counts = pins_of.setdefault(carried, {})
                counts[cls] = counts.get(cls, 0) + 1
        proposed = {cls: min(kept[cls], min(1.0, pinned.get(cls, 0) / need[cls]) if need[cls] > 0 else 1.0)
                    for cls in ROLE_CLASSES}
        if all(abs(proposed[cls] - kept[cls]) < _KEPT_CONVERGENCE for cls in ROLE_CLASSES):
            break
        kept = proposed
        demand = {code: dict(by_class) for code, by_class in raw.items()}
        for cls in ROLE_CLASSES:
            if kept[cls] < 1.0:
                _fold_into(demand, cls, pins_of.get(cls, {}), 1.0 - kept[cls])
    return FoldedDemand(demand, kept, iterations)


def remaining_weights(weights: Mapping[str, tuple[float, ...]], occupancy: Mapping[str, int]) -> dict[str, tuple[float, ...]]:
    """The rank weights a roster still has open: each class's ranks with the
    first `occupancy[cls]` of them taken. With nothing owned it is `weights`
    itself, so pinning against it at minute zero is pinning as the run did;
    with a class covered it is empty there, so a multi-role man pins to the
    role his roster still pays for (see pin_class)."""
    return {cls: tuple(ranks[occupancy.get(cls, 0):]) for cls, ranks in weights.items()}


def pin_class(roles: frozenset[Role], weights: Mapping[str, tuple[float, ...]]) -> str:
    """The one class a multi-role player is valued under when the pool is
    priced: the class with the most demand across the modules, ties broken
    by ROLE_CLASSES order. The run pins against the league-wide weights,
    fixed when it is written; the live board pins the same way against
    `remaining_weights`, the ranks my roster leaves open -- which is how the
    twelve men pinned to a full E on 2026-09-03 stop reading as band 0
    while holding a T, C or M the completion still pays for. The exact
    matching for the player on the block stays the auction's job (spec,
    "Where this is an approximation")."""
    classes = player_classes(roles)
    if not classes:
        raise ValueError("a player carries at least one role")
    return max(sorted(classes, key=ROLE_CLASSES.index), key=lambda cls: sum(weights[cls]))
