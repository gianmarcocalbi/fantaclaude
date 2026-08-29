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
from collections.abc import Mapping

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
                 target_weight: float = 0.8) -> dict[str, tuple[float, ...]]:
    """Class -> weight of the k-th player of that class, k = 1 .. the ranks
    the class has (the peak demand of any module, rounded up, plus
    bench_slots; a target extends them; never more than max_rank)."""
    unknown = sorted(set(targets or {}) - set(ROLE_CLASSES))
    if unknown:
        raise ValueError(f"target_composition names classes that do not exist: {unknown}; choose from {ROLE_CLASSES}")
    n = len(demand_by_module)
    weights: dict[str, tuple[float, ...]] = {}
    for cls in ROLE_CLASSES:
        peak = max((by_class.get(cls, 0.0) for by_class in demand_by_module.values()), default=0.0)
        ranks = math.ceil(peak - 1e-9) + bench_slots
        if targets:
            ranks = max(ranks, targets.get(cls, 0))
        ranks = max(1, min(max_rank, ranks))
        coverage = [sum(min(1.0, max(0.0, by_class.get(cls, 0.0) - (k - 1))) for by_class in demand_by_module.values()) / n
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


def pin_class(roles: frozenset[Role], weights: Mapping[str, tuple[float, ...]]) -> str:
    """The one class a multi-role player is valued under when the pool is
    priced: the class with the most demand across the modules, ties broken
    by ROLE_CLASSES order. The exact matching for the player on the block
    is the auction's job (spec, "Where this is an approximation")."""
    classes = player_classes(roles)
    if not classes:
        raise ValueError("a player carries at least one role")
    return max(sorted(classes, key=ROLE_CLASSES.index), key=lambda cls: sum(weights[cls]))
