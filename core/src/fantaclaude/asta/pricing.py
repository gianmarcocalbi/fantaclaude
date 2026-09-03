"""The one pricing function: a max price is the indifference point between
buying a player and the best completion without him.

Phase 1 calls this with the full listone and pre-auction expected prices;
Phase 2 calls it with the live remaining pool. Same function, so the board
cannot jump when the auction opens (spec, "One pricing function").

State: my credits, the pool, what I already own, the demand weights per role
class and rank (model/demand.py), the hard minimums, the league's bounds per
class (class_min / class_max: the goalkeepers' 2-6 today, a house rule's "3
portieri" tomorrow) and for the whole roster. V(c) is the value of the best
completion of my roster with c credits at the pool's expected prices; for a
player p offered at x, buy(x) = max over the rank a he could take of w_a *
value(p) + V_{-p,-a}(C - x), and walk = V_{-p}(C) -- in both branches p leaves
the pool: if I do not buy him, someone else does. He is not seated at his
class's first rank by construction: which rank he carries depends on how many
better players the completion also buys, so it is the DP's decision, and
taking the maximum over the ranks is how it makes it. The max price is the
largest x with buy(x) >= walk, found by binary search since every V_{-p,-a} is
monotone in credits and so is their maximum; solved at p25, p50 and p75 of
value(p), which is the band.

The machinery (spec, "The algorithm, concretely"): expected prices are
quotazione x inflation, inflation = credits still on the market over the
quotazioni of the credible pool, clamped; per class a knapsack over the
top candidates gives f_r(j, c), the best weighted value of exactly j
players for at most c credits, the j-th chosen (in value order) carrying
the j-th rank weight; the classes combine by max-plus convolution; a
class's curve with one rank left free is what the buy branch completes
from, one such curve per rank. Every player is priced with himself removed
from his class's curve -- one knapsack per candidate, and the class's own
curves for a player the DP never considered, who leaves nothing behind when
he leaves the pool. There is one mode, decided in Phase 2a (2026-08-30):
an earlier version priced only the lot on the block exactly and the rest
of the board from full-pool tables, so the committed pre-auction board and
the live board disagreed for every other player the moment the auction
opened. The exact board re-prices 553 players in about a quarter of a
second on the auction laptop, which a human-paced auction never notices,
so the approximation was removed rather than explained. Composition is a
decision variable: the DP chooses how many of each class within the ranks
the demand gives it; a target only raises weights (a soft prior), and a
departure from it is reported. A completion that cannot meet a hard
minimum is worth -inf, which is what drives the last needed Dc's price to
the credits available. A class budget share caps both what the completion
may spend on the class and what any of its players may be priced at. One
credit is reserved for every roster slot the completion leaves unfilled,
iterated to the running maximum so the reserve and the completion it pays
for agree; when the completion would exceed the roster maximum, a slot
price (the shadow price of a roster place, found by bisection) is charged
per player until it fits, and reported.

Pure: no I/O, no clock, numpy inside, frozen dataclasses at the edges.
Every tunable is in PricingConfig, loaded from pricing.yml elsewhere. A
-inf inside is an impossible branch, and `to_dict` reports it as None
(values.json_safe) so a board is valid JSON for whoever stores it.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from fantaclaude.values import json_safe

NEG = -math.inf
SLOT_PRICE_STEPS = 12


@dataclass(frozen=True)
class PricingConfig:
    candidates_per_class: int = 30      # the DP values the top N by value and the top N by value per credit
    max_per_class: int = 6              # a cap on the ranks a class may have (the demand sets the real number)
    max_goalkeepers: int = 3
    bench_weight: float = 0.12          # the first bench rank of a class: the chance to start anyway
    bench_decay: float = 0.5            # each further bench rank is worth this much of the previous
    bench_slots_per_class: int = 1      # bench ranks beyond the peak demand of any module
    target_weight: float = 0.8          # what a preferences target raises a rank's weight to
    inflation_floor: float = 0.6
    inflation_ceiling: float = 2.5
    replacement_price: int = 1          # the price a replacement-level player is expected to cost
    tiers_per_class: int = 5
    tier_pool: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PoolPlayer:
    player_id: int
    name: str
    role_class: str
    value_p25: float
    value_p50: float
    value_p75: float
    quotazione: int


@dataclass(frozen=True)
class OwnedPlayer:
    player_id: int
    role_class: str
    value_p50: float
    # Every Mantra role he holds. Occupancy is a question about the pitch, not
    # about the pin: a man who can field as T occupies one of T's ranks even
    # when demand pinned him to C for pricing. Defaulted to the pinned class so
    # a caller that does not know the role set behaves as before.
    roles: tuple[str, ...] = ()

    @property
    def can_field(self) -> tuple[str, ...]:
        return self.roles or (self.role_class,)


@dataclass(frozen=True)
class PoolState:
    credits: int
    market_credits: int
    pool: tuple[PoolPlayer, ...]
    weights: dict[str, tuple[float, ...]]
    hard_minimums: dict[str, int]
    owned: tuple[OwnedPlayer, ...] = ()
    excluded: frozenset[int] = frozenset()
    roster_min: int = 23
    roster_max: int = 40
    class_min: dict[str, int] = field(default_factory=dict)     # the league's or the house's floor per class (Por 2)
    class_max: dict[str, int] = field(default_factory=dict)     # and its ceiling (Por 6); hard_minimums are the modules'
    targets: dict[str, int] = field(default_factory=dict)
    class_budget_share: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Band:
    p25: int
    p50: int
    p75: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class PlayerPrice:
    player_id: int
    role_class: str
    band: Band
    expected_price: int
    rank_weight: float        # the rank the completion leaves him at his p50 max price, not his class's first
    walk_value: float
    buy_value: float          # rank_weight * value_p50 - the slot price + the completion at the p50 max price

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"player_id": self.player_id, "role_class": self.role_class, "band": self.band.to_dict(),
                          "expected_price": self.expected_price, "rank_weight": self.rank_weight,
                          "walk_value": self.walk_value, "buy_value": self.buy_value})


@dataclass(frozen=True)
class BoardPricing:
    prices: dict[int, PlayerPrice]
    inflation: float
    expected_prices: dict[int, int]
    composition: dict[str, int]
    credits_by_class: dict[str, int]
    completion_value: float
    reserve: int
    budget: int
    slot_price: float
    targets_departed: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"prices": {str(k): v.to_dict() for k, v in self.prices.items()}, "inflation": self.inflation,
                          "expected_prices": {str(k): v for k, v in self.expected_prices.items()},
                          "composition": self.composition, "credits_by_class": self.credits_by_class,
                          "completion_value": self.completion_value, "reserve": self.reserve, "budget": self.budget,
                          "slot_price": self.slot_price, "targets_departed": list(self.targets_departed)})


@dataclass(frozen=True)
class _Class:
    name: str
    players: tuple[PoolPlayer, ...]
    costs: np.ndarray
    values: np.ndarray
    weights: tuple[float, ...]
    j_min: int
    j_max: int
    cap: int | None


def _curve(costs: np.ndarray, values: np.ndarray, weights: tuple[float, ...] | np.ndarray, budget: int,
           penalty: float = 0.0) -> np.ndarray:
    """dp[v, j, c]: the best weighted value of exactly j players for at most c
    credits, less the slot price each, under rank weighting v. `weights` is a
    stack of weightings (a single row broadcasts to one): they share the one
    pass over the class, because they differ in what the j-th chosen player is
    worth and not in which players exist. Every rank is updated in one numpy
    operation per player: the right-hand side reads the tables as they stood
    before him, which is what a descending loop over j used to guarantee one
    rank at a time, at k times the Python overhead."""
    w = np.atleast_2d(np.asarray(weights, dtype=np.float64))
    k = w.shape[1]
    dp = np.full((w.shape[0], k + 1, budget + 1), NEG)
    dp[:, 0, :] = 0.0
    for cost, value in zip(costs.tolist(), values.tolist()):
        if cost > budget:
            continue
        gain = dp[:, :-1, :budget + 1 - cost] + (w * value - penalty)[:, :, None]
        np.maximum(dp[:, 1:, cost:], gain, out=dp[:, 1:, cost:])
    return dp


def _hole_weights(weights: tuple[float, ...]) -> np.ndarray:
    """Row a: the rank weights the completion keeps when the player on the
    block takes rank a himself. Pricing him means maximising over the rows --
    which rank his value earns against the players the completion actually
    buys is the DP's decision, not rank 1 by construction. Ordering falls out:
    seating him above a better player is never the maximising row, because
    sorted values against sorted weights is the larger sum."""
    k = len(weights)
    return np.array([[weights[r] for r in range(k) if r != a] for a in range(k)],
                    dtype=np.float64).reshape(k, max(0, k - 1))


def _best(dp: np.ndarray, j_min: int, j_max: int, cap: int | None) -> np.ndarray:
    """The best of the j in range, over the last two axes of dp: (..., j, c) -> (..., c)."""
    j_max = min(j_max, dp.shape[-2] - 1)
    if j_min > j_max:
        return np.full(dp.shape[:-2] + dp.shape[-1:], NEG)
    best = dp[..., j_min:j_max + 1, :].max(axis=-2)
    if cap is not None and cap < best.shape[-1] - 1:
        best = best.copy()
        best[..., cap + 1:] = best[..., cap, None]
    return best


def _maxplus(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Both are non-decreasing (a curve is "for at most c credits"), so a
    spend k that buys nothing more than k - 1 does is dominated by k - 1,
    which leaves a credit for the other side: only the steps of `a` are
    worth visiting."""
    n = a.shape[-1]
    out = np.full(b.shape, NEG)
    steps = np.flatnonzero((a > NEG) & np.r_[True, a[1:] > a[:-1]]).tolist()
    for k in steps:
        np.maximum(out[..., k:], a[k] + b[..., :n - k], out=out[..., k:])
    return out


def _at(a: np.ndarray, b: np.ndarray, c: int) -> float:
    return float((a[:c + 1] + b[..., :c + 1][..., ::-1]).max())


def _expected_prices(state: PoolState, cfg: PricingConfig) -> tuple[float, dict[int, int]]:
    by_class: dict[str, list[PoolPlayer]] = {}
    for p in state.pool:
        by_class.setdefault(p.role_class, []).append(p)
    credible: set[int] = set()
    for players in by_class.values():
        # (-value, player_id), the same total order _classes sorts by: without the
        # id, which of several players tied at one value falls inside the cut is
        # decided by the order the caller happened to build the pool in, and the
        # whole board's inflation moves with it. Ties are not exotic -- every
        # player with exp_presenze == 0 sits at value_p50 == 0.0.
        credible.update(p.player_id for p in sorted(players, key=lambda q: (-q.value_p50, q.player_id))
                        [:cfg.candidates_per_class])
    quot = sum(p.quotazione for p in state.pool if p.player_id in credible)
    raw = state.market_credits / quot if quot > 0 else 1.0
    inflation = min(cfg.inflation_ceiling, max(cfg.inflation_floor, raw))
    return inflation, {p.player_id: max(1, round(p.quotazione * inflation)) for p in state.pool}


def _occupancy(state: PoolState) -> dict[str, int]:
    """How many of each class's ranks my squad already covers.

    Counting by pinned class (what this used to do) undercounts a multi-role
    squad: on 2026-09-03 four players who could field as T were pinned across
    C, W and T, so the board saw one and asked for two more of what was already
    covered. Counting by role set instead would overcount -- one player would
    saturate three classes at once, and he can only wear one shirt.

    So it is an assignment: walk every (class, rank) slot from the most
    valuable down, and give it to a player who holds that role and has not
    been placed yet. Filling the best slots first is what a manager does with
    the squad he has, and it leaves each player counted exactly once. Greedy
    over a weight-sorted list, which for this shape -- every slot of a class
    interchangeable to any player who holds it -- places as many players as a
    matching would.
    """
    slots = sorted(((w, cls, k) for cls, ranks in state.weights.items() for k, w in enumerate(ranks)),
                   key=lambda s: (-s[0], s[1], s[2]))
    placed: set[int] = set()
    out: dict[str, int] = {cls: 0 for cls in state.weights}
    for _, cls, _k in slots:
        for o in state.owned:
            if o.player_id in placed or cls not in o.can_field:
                continue
            placed.add(o.player_id)
            out[cls] += 1
            break
    return out


def _classes(state: PoolState, cfg: PricingConfig, expected: dict[int, int], budget: int) -> list[_Class]:
    owned = _occupancy(state)
    grouped: dict[str, list[PoolPlayer]] = {cls: [] for cls in state.weights}
    for p in state.pool:
        if p.player_id in state.excluded:
            continue
        if p.role_class not in grouped:
            raise ValueError(f"player {p.player_id} has role class {p.role_class!r}, which the weights do not know")
        grouped[p.role_class].append(p)
    classes: list[_Class] = []
    for cls, ranks in state.weights.items():
        players = grouped[cls]
        by_value = sorted(players, key=lambda p: (-p.value_p50, p.player_id))
        by_ratio = sorted(players, key=lambda p: (-p.value_p50 / expected[p.player_id], p.player_id))
        chosen = ({p.player_id for p in by_value[:cfg.candidates_per_class]}
                  | {p.player_id for p in by_ratio[:cfg.candidates_per_class]})
        candidates = tuple(p for p in by_value if p.player_id in chosen)
        m = owned.get(cls, 0)
        # the pricing knob for goalkeepers is named for them; the league's and the house's bounds are per class
        cap_cfg = cfg.max_goalkeepers if cls == "Por" else cfg.max_per_class
        k_max = min(cap_cfg, state.class_max.get(cls, cap_cfg), len(ranks))
        j_max = max(0, k_max - m)
        need = max(state.hard_minimums.get(cls, 0), state.class_min.get(cls, 0))
        weights = tuple(ranks[m + i] if m + i < len(ranks) else ranks[-1] for i in range(j_max))
        cap = int(state.class_budget_share[cls] * budget) if cls in state.class_budget_share else None
        classes.append(_Class(cls, candidates, np.array([expected[p.player_id] for p in candidates], dtype=np.int64),
                              np.array([p.value_p50 for p in candidates], dtype=np.float64), weights,
                              max(0, need - m), j_max, cap))
    return classes


@dataclass
class _Solution:
    budget: int
    penalty: float
    total: np.ndarray
    others: dict[str, np.ndarray]
    composition: dict[str, int]
    credits: dict[str, int]


def _solve(classes: list[_Class], budget: int, penalty: float = 0.0) -> _Solution:
    zero = np.zeros(budget + 1)
    dps = {c.name: _curve(c.costs, c.values, c.weights, budget, penalty)[0] for c in classes}
    best = {c.name: _best(dps[c.name], c.j_min, c.j_max, c.cap) for c in classes}
    prefix = [zero]
    for c in classes:
        prefix.append(_maxplus(prefix[-1], best[c.name]))
    suffix = [zero]
    for c in reversed(classes):
        suffix.append(_maxplus(suffix[-1], best[c.name]))
    suffix.reverse()                                            # suffix[i] = every class from i on
    others = {c.name: _maxplus(prefix[i], suffix[i + 1]) for i, c in enumerate(classes)}
    composition: dict[str, int] = {}
    credits: dict[str, int] = {}
    remaining = budget
    for i in range(len(classes) - 1, -1, -1):
        c = classes[i]
        dp, pre = dps[c.name], prefix[i]
        top = min(remaining, c.cap) if c.cap is not None else remaining
        best_value, best_j, best_c = NEG, 0, 0
        for j in range(c.j_min, min(c.j_max, dp.shape[0] - 1) + 1):
            candidates = dp[j, :top + 1] + pre[remaining - np.arange(top + 1)]
            idx = int(np.argmax(candidates))
            if candidates[idx] > best_value:
                best_value, best_j, best_c = float(candidates[idx]), j, idx
        composition[c.name], credits[c.name] = best_j, best_c
        remaining -= best_c
    return _Solution(budget, penalty, prefix[-1], others, composition, credits)


def _fit_roster(classes: list[_Class], budget: int, slots: int) -> _Solution:
    """The completion within `slots` players: free if it fits, else the
    smallest per-player slot price that makes it fit, by bisection."""
    free = _solve(classes, budget)
    if sum(free.composition.values()) <= slots:
        return free
    lo, hi = 0.0, max((float(c.weights[0] * c.values.max()) for c in classes if c.weights and c.values.size), default=1.0)
    fit = _solve(classes, budget, hi)
    for _ in range(SLOT_PRICE_STEPS):
        mid = (lo + hi) / 2
        candidate = _solve(classes, budget, mid)
        if sum(candidate.composition.values()) <= slots:
            hi, fit = mid, candidate
        else:
            lo = mid
    return fit


def _class_holes(c: _Class, budget: int, penalty: float) -> np.ndarray:
    """The class's curves with one rank left free and nobody removed: row a is
    the best the class does around a player seated at rank a. Exact for a
    player the DP never considered -- he was in no table, so his leaving the
    pool leaves every table as it is -- and shared by all of them."""
    dp = _curve(c.costs, c.values, _hole_weights(c.weights), budget, penalty)
    return _best(dp, max(0, c.j_min - 1), max(0, c.j_max - 1), c.cap)


def _column(buy: np.ndarray, others: np.ndarray, c: int) -> np.ndarray:
    """Per rank he could take, buying him with c credits left for the rest:
    the split of c between his class and the rest of the roster, maximised
    point by point. The binary search asks for a handful of points, and a
    whole max-plus convolution per player is what an exact board cannot
    afford."""
    if c < 0:
        return np.full(buy.shape[0], NEG)
    return (others[:c + 1] + buy[:, :c + 1][:, ::-1]).max(axis=1)


def _max_price(buy: np.ndarray, others: np.ndarray, walk: float, budget: int) -> int:
    """The largest x in [0, budget] with buy(budget - x) >= walk; buy(.) is a
    maximum of non-decreasing curves, so the predicate is monotone in x. No
    completion without him (walk = -inf) makes it every credit that still
    leaves the buy branch feasible."""
    def ok(c: int) -> bool:
        value = float(_column(buy, others, c).max())
        return value > NEG if walk == NEG else value >= walk
    if not ok(budget):
        return 0
    lo, hi = 0, budget
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ok(budget - mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def price_board(state: PoolState, cfg: PricingConfig) -> BoardPricing:
    if state.credits < 0:
        raise ValueError("credits cannot be negative")
    inflation, expected = _expected_prices(state, cfg)
    slots = max(0, state.roster_max - len(state.owned))
    reserve, budget = 0, state.credits
    classes = _classes(state, cfg, expected, budget)
    solution = _fit_roster(classes, budget, slots)
    while True:                     # the reserve and the completion it pays for have to agree: reserving credits
        short = state.roster_min - len(state.owned) - sum(solution.composition.values())   # shrinks the budget,
        need = min(state.credits, max(reserve, short))                    # which can buy fewer players, which
        if need <= reserve:                                               # reserves more. Taking the running
            break                                                         # maximum makes that non-decreasing and
        reserve, budget = need, state.credits - need                      # bounded by roster_min, so it settles
        classes = _classes(state, cfg, expected, budget)                  # (2-3 solves) instead of oscillating.
        solution = _fit_roster(classes, budget, slots)
    penalty = solution.penalty
    by_class = {c.name: c for c in classes}
    candidate_of = {p.player_id: c.name for c in classes for p in c.players}
    shared: dict[str, np.ndarray] = {}
    prices: dict[int, PlayerPrice] = {}
    for p in state.pool:
        if p.player_id in state.excluded:
            continue
        c = by_class[p.role_class]
        if c.j_max == 0:
            prices[p.player_id] = PlayerPrice(p.player_id, c.name, Band(0, 0, 0), expected[p.player_id], 0.0,
                                              float(solution.total[budget]), NEG)
            continue
        k = len(c.weights)
        others = solution.others[c.name]
        if p.player_id in candidate_of:
            keep = [i for i, q in enumerate(c.players) if q.player_id != p.player_id]
            stack = np.zeros((k + 1, k))                        # row 0 walks away from him, row a + 1 seats him at rank a
            stack[0] = c.weights
            stack[1:, :k - 1] = _hole_weights(c.weights)        # the padding column is never read: j stops at j_max - 1
            dp = _curve(c.costs[keep], c.values[keep], stack, budget, penalty)
            walk = _at(others, _best(dp[0], c.j_min, c.j_max, c.cap), budget)
            holes = _best(dp[1:], max(0, c.j_min - 1), max(0, c.j_max - 1), c.cap)
        else:                                        # in no table, so the class's own curves are exact for him
            if c.name not in shared:
                shared[c.name] = _class_holes(c, budget, penalty)
            walk, holes = float(solution.total[budget]), shared[c.name]
        # buy(c) = max over the rank he takes; every row already leaves that rank
        # free, so scarcity and the rank weight both fall out of the same maximum.
        ranks = np.asarray(c.weights)[:, None]
        buys = [holes + (ranks * v - penalty) for v in (p.value_p25, p.value_p50, p.value_p75)]
        band = Band(*(_max_price(b, others, walk, budget) for b in buys))
        if c.cap is not None:                                   # a budget share caps the class, so it caps the price
            band = Band(*(min(x, c.cap) for x in (band.p25, band.p50, band.p75)))
        at_p50 = _column(buys[1], others, budget - band.p50)
        taken = int(np.argmax(at_p50))
        buy = float(at_p50[taken]) if at_p50[taken] > NEG else NEG
        prices[p.player_id] = PlayerPrice(p.player_id, c.name, band, expected[p.player_id], c.weights[taken], walk, buy)
    owned = Counter(o.role_class for o in state.owned)
    departed = tuple(cls for cls, n in state.targets.items()
                     if solution.composition.get(cls, 0) + owned.get(cls, 0) < n)
    return BoardPricing(prices, inflation, expected, solution.composition, solution.credits,
                        float(solution.total[budget]), reserve, budget, penalty, departed)


def explain(board: BoardPricing, player_id: int) -> dict[str, Any]:
    """The trace behind one price, for the model to read: never a recomputation."""
    price = board.prices[player_id]
    return json_safe({"player_id": player_id, "role_class": price.role_class, "band": price.band.to_dict(),
                      "expected_price": price.expected_price, "rank_weight": price.rank_weight,
                      "walk_value": price.walk_value, "buy_value": price.buy_value,
                      "inflation": board.inflation, "composition": board.composition,
                      "credits_by_class": board.credits_by_class, "completion_value": board.completion_value,
                      "reserve": board.reserve, "budget": board.budget, "slot_price": board.slot_price,
                      "targets_departed": list(board.targets_departed)})
