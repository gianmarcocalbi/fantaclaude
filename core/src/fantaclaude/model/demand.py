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
never pins anyone to Dd or Ds. `satisfiable_demand` moves such a class's
demand onto the classes its own players do pin to, in the proportion this
listone supplies them -- conserved module by module, and read off the
listone at run time rather than typed, so a listone with real Dd players
folds nothing. Without it the flank slots are neither satisfied nor priced,
and E and Dc are weighted as though they only had to cover their own slots
while their players are the ones fielding the flanks. The fold turns on
whether a class has *any* player, which is a knife edge -- one listed pure
Dd hands the class its half-slot back and moves every price -- so
`thin_classes` names the classes standing on that edge and the run warns.

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


def _fold_into(demand: dict[str, dict[str, float]], cls: str, pins: Mapping[str, int]) -> None:
    """Move `cls`'s demand, module by module, onto the classes `pins` counts."""
    total = sum(pins.values())
    for by_class in demand.values():
        moved = by_class.pop(cls, 0.0)
        if not moved:
            continue
        if total:
            for target, count in pins.items():
                by_class[target] = by_class.get(target, 0.0) + moved * count / total
            continue
        # Nobody in the listone carries the role at all, so there is no
        # distribution to read and the slot cannot be filled by anyone. Its
        # worth goes to whatever else the module fields, in proportion to what
        # that already draws: the eleven units are what a module is worth and
        # they have to land somewhere.
        rest = sum(by_class.values())
        if rest <= 0:
            by_class[cls] = moved
            continue
        for other, share in list(by_class.items()):
            by_class[other] = share + moved * share / rest


def satisfiable_demand(demand_by_module: Mapping[str, Mapping[str, float]], supply: Iterable[frozenset[Role]], *,
                       max_rank: int, bench_weight: float, bench_decay: float = 0.5,
                       bench_slots: int = 1) -> dict[str, dict[str, float]]:
    """Module demand with every class no player can pin to folded onto the
    classes its players do pin to, in the proportion the listone supplies.

    `pin_class` values a multi-role player under his most-demanded class, so a
    class can draw slots in every module and still take no player: Dd and Ds
    each draw half of every module's eleven, but a Dd is a `Dd;E` or a `Dd;B`
    and both of those outweigh him, so nobody is ever priced as one. Left
    alone that is a double error -- the flank demand is never satisfied or
    priced, and E and Dc are weighted as though they only had to cover their
    own slots when their players are the ones who actually field the flanks,
    which under-prices them.

    So the demand moves to where the supply is: for each such class, the
    classes its own players pin to, weighted by how many of them do. Nothing
    is typed -- which classes are affected, and in what proportion, are both
    read off the listone at run time, so a listone with real Dd players folds
    nothing. Demand is conserved module by module, and the loop terminates
    because each pass zeroes at least one class's demand and no pass ever
    gives a class demand back."""
    players = tuple(supply)
    demand = {code: dict(by_class) for code, by_class in demand_by_module.items()}
    for _ in range(len(ROLE_CLASSES) + 1):
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
        orphans = [cls for cls in ROLE_CLASSES
                   if not pinned.get(cls) and any(by_class.get(cls, 0.0) > 0.0 for by_class in demand.values())]
        if not orphans:
            break
        for cls in orphans:
            _fold_into(demand, cls, pins_of.get(cls, {}))
    return demand


THIN_SUPPLY_RATIO = 1 / 3


def thin_classes(demand_by_module: Mapping[str, Mapping[str, float]], pinned: Mapping[str, int], *, teams: int,
                 ratio: float = THIN_SUPPLY_RATIO) -> list[tuple[str, int, float]]:
    """Classes whose pricing rests on a handful of players -- (class, players
    pinned to it, starting slots the league draws from it).

    `satisfiable_demand` asks only whether a class has *any* player, which is a
    knife edge: one listed pure `Dd` hands the class back half a slot of every
    module and moves every price on the board, silently, off a routine
    re-sync. Nothing here changes that -- making the fold continuous in the
    shortfall would move every price again -- but the run can at least say when
    it is standing on the edge.

    Two conditions, because either alone is ordinary. The listone supplies the
    class at less than `ratio` of the rate the modules demand it (a small
    listone is small in every class, so a share catches what a count cannot),
    *and* there are fewer players in it than the league has starting slots to
    fill from it (a niche class with enough bodies for the league is fine)."""
    modules = len(demand_by_module) or 1
    pool = sum(pinned.values())
    thin: list[tuple[str, int, float]] = []
    for cls in ROLE_CLASSES:
        per_module = sum(by_class.get(cls, 0.0) for by_class in demand_by_module.values()) / modules
        slots = per_module * teams
        n = pinned.get(cls, 0)
        if per_module <= 0 or not pool:
            continue
        if n / pool < ratio * per_module / 11 and n < slots:
            thin.append((cls, n, slots))
    return thin


def pin_class(roles: frozenset[Role], weights: Mapping[str, tuple[float, ...]]) -> str:
    """The one class a multi-role player is valued under when the pool is
    priced: the class with the most demand across the modules, ties broken
    by ROLE_CLASSES order. The exact matching for the player on the block
    is the auction's job (spec, "Where this is an approximation")."""
    classes = player_classes(roles)
    if not classes:
        raise ValueError("a player carries at least one role")
    return max(sorted(classes, key=ROLE_CLASSES.index), key=lambda cls: sum(weights[cls]))
