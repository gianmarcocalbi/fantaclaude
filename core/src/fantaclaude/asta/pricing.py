"""The one pricing function: a max price is the indifference point between
buying a player and the best completion without him.

Phase 1 calls this with the full listone and pre-auction expected prices;
Phase 2 calls it with the live remaining pool. Same function, so the board
cannot jump when the auction opens (spec, "One pricing function").

State: my credits, the pool, what I already own, the demand weights per
role class and rank (model/demand.py), the hard minimums, the league's
bounds. V(c) is the value of the best completion of my roster with c
credits at the pool's expected prices; for a player p offered at x,
buy(x) = w * value(p) + V_{-p,-slot}(C - x) and walk = V_{-p}(C) -- in both
branches p leaves the pool: if I do not buy him, someone else does. The
max price is the largest x with buy(x) >= walk, found by binary search
since V is monotone in credits; solved at p25, p50 and p75 of value(p),
which is the band.

The machinery (spec, "The algorithm, concretely"): expected prices are
quotazione x inflation, inflation = credits still on the market over the
quotazioni of the credible pool, clamped; per class a knapsack over the
top candidates gives f_r(j, c), the best weighted value of exactly j
players for at most c credits, the j-th chosen (in value order) carrying
the j-th rank weight; the classes combine by max-plus convolution; a
class's curve without its first slot (weights shifted by one) is what the
buy branch completes from. Removing p from his class's curve is done
exactly for the player on the block (`focus`) and, with `exact=True`, for
every player of a pre-auction run; otherwise the board is priced from the
full-pool tables and says so (`PlayerPrice.exact`). Composition is a
decision variable: the DP chooses how many of each class within the ranks
the demand gives it; a target only raises weights (a soft prior), and a
departure from it is reported. A completion that cannot meet a hard
minimum is worth -inf, which is what drives the last needed Dc's price to
the credits available. A class budget share caps both what the completion
may spend on the class and what any of its players may be priced at. One
credit is reserved for every roster slot the completion leaves unfilled;
when the completion would exceed the roster maximum, a slot price (the
shadow price of a roster place, found by bisection) is charged per player
until it fits, and reported.

Pure: no I/O, no clock, numpy inside, frozen dataclasses at the edges.
Every tunable is in PricingConfig, loaded from pricing.yml elsewhere.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

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
    min_goalkeepers: int = 2
    max_goalkeepers: int = 6
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
    rank_weight: float
    walk_value: float
    buy_value: float          # w * value_p50 - the slot price + the completion at the p50 max price
    exact: bool

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "role_class": self.role_class, "band": self.band.to_dict(),
                "expected_price": self.expected_price, "rank_weight": self.rank_weight,
                "walk_value": self.walk_value, "buy_value": self.buy_value, "exact": self.exact}


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
        return {"prices": {str(k): v.to_dict() for k, v in self.prices.items()}, "inflation": self.inflation,
                "expected_prices": {str(k): v for k, v in self.expected_prices.items()},
                "composition": self.composition, "credits_by_class": self.credits_by_class,
                "completion_value": self.completion_value, "reserve": self.reserve, "budget": self.budget,
                "slot_price": self.slot_price, "targets_departed": list(self.targets_departed)}


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


def _curve(costs: np.ndarray, values: np.ndarray, weights: tuple[float, ...], budget: int,
           penalty: float = 0.0) -> np.ndarray:
    """dp[j, c]: the best weighted value of exactly j players for at most c credits, less the slot price each."""
    k = len(weights)
    dp = np.full((k + 1, budget + 1), NEG)
    dp[0, :] = 0.0
    for cost, value in zip(costs.tolist(), values.tolist()):
        if cost > budget:
            continue
        for j in range(k, 0, -1):
            gain = dp[j - 1, :budget + 1 - cost] + (weights[j - 1] * value - penalty)
            np.maximum(dp[j, cost:], gain, out=dp[j, cost:])
    return dp


def _best(dp: np.ndarray, j_min: int, j_max: int, cap: int | None) -> np.ndarray:
    j_max = min(j_max, dp.shape[0] - 1)
    if j_min > j_max:
        return np.full(dp.shape[1], NEG)
    best = dp[j_min:j_max + 1].max(axis=0)
    if cap is not None and cap < best.shape[0] - 1:
        best = best.copy()
        best[cap + 1:] = best[cap]
    return best


def _maxplus(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = a.shape[0]
    out = np.full(n, NEG)
    for k in np.flatnonzero(a > NEG).tolist():
        np.maximum(out[k:], a[k] + b[:n - k], out=out[k:])
    return out


def _at(a: np.ndarray, b: np.ndarray, c: int) -> float:
    return float((a[:c + 1] + b[:c + 1][::-1]).max())


def _expected_prices(state: PoolState, cfg: PricingConfig) -> tuple[float, dict[int, int]]:
    by_class: dict[str, list[PoolPlayer]] = {}
    for p in state.pool:
        by_class.setdefault(p.role_class, []).append(p)
    credible: set[int] = set()
    for players in by_class.values():
        credible.update(p.player_id for p in sorted(players, key=lambda q: -q.value_p50)[:cfg.candidates_per_class])
    quot = sum(p.quotazione for p in state.pool if p.player_id in credible)
    raw = state.market_credits / quot if quot > 0 else 1.0
    inflation = min(cfg.inflation_ceiling, max(cfg.inflation_floor, raw))
    return inflation, {p.player_id: max(1, round(p.quotazione * inflation)) for p in state.pool}


def _classes(state: PoolState, cfg: PricingConfig, expected: dict[int, int], budget: int) -> list[_Class]:
    owned = Counter(o.role_class for o in state.owned)
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
        k_max = min(cfg.max_goalkeepers, state.max_goalkeepers) if cls == "Por" else cfg.max_per_class
        k_max = min(k_max, len(ranks))
        j_max = max(0, k_max - m)
        need = max(state.hard_minimums.get(cls, 0), state.min_goalkeepers if cls == "Por" else 0)
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
    minus_one: dict[str, np.ndarray]     # others ⊕ the class curve without its first slot
    composition: dict[str, int]
    credits: dict[str, int]


def _solve(classes: list[_Class], budget: int, penalty: float = 0.0) -> _Solution:
    zero = np.zeros(budget + 1)
    dps = {c.name: _curve(c.costs, c.values, c.weights, budget, penalty) for c in classes}
    best = {c.name: _best(dps[c.name], c.j_min, c.j_max, c.cap) for c in classes}
    prefix = [zero]
    for c in classes:
        prefix.append(_maxplus(prefix[-1], best[c.name]))
    suffix = [zero]
    for c in reversed(classes):
        suffix.append(_maxplus(suffix[-1], best[c.name]))
    suffix.reverse()                                            # suffix[i] = every class from i on
    others = {c.name: _maxplus(prefix[i], suffix[i + 1]) for i, c in enumerate(classes)}
    minus_one = {}
    for c in classes:
        dp = _curve(c.costs, c.values, c.weights[1:], budget, penalty)
        minus_one[c.name] = _maxplus(others[c.name], _best(dp, max(0, c.j_min - 1), max(0, c.j_max - 1), c.cap))
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
    return _Solution(budget, penalty, prefix[-1], others, minus_one, composition, credits)


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


def _max_price(gain: float, curve: np.ndarray, walk: float, budget: int) -> int:
    """The largest x in [0, budget] with gain + curve[budget - x] >= walk;
    curve is non-decreasing, so the predicate is monotone in x."""
    if walk == NEG:                                             # no completion without him: every spare credit
        feasible = np.flatnonzero(curve[:budget + 1] > NEG)
        return int(budget - feasible.min()) if feasible.size else 0
    if gain + curve[budget] < walk:
        return 0
    lo, hi = 0, budget
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if gain + curve[budget - mid] >= walk:
            lo = mid
        else:
            hi = mid - 1
    return lo


def price_board(state: PoolState, cfg: PricingConfig, focus: int | None = None, *,
                exact: bool = False) -> BoardPricing:
    if state.credits < 0:
        raise ValueError("credits cannot be negative")
    inflation, expected = _expected_prices(state, cfg)
    slots = max(0, state.roster_max - len(state.owned))
    classes = _classes(state, cfg, expected, state.credits)
    solution = _fit_roster(classes, state.credits, slots)
    bought = sum(solution.composition.values())
    reserve = min(state.credits, max(0, state.roster_min - len(state.owned) - bought))
    budget = state.credits - reserve
    if reserve:                     # the reserve is the free completion's shortfall; the completion inside the
                                    # reduced budget may then buy a different number, and is what is reported
        classes = _classes(state, cfg, expected, budget)
        solution = _fit_roster(classes, budget, slots)
    penalty = solution.penalty
    by_class = {c.name: c for c in classes}
    candidate_of = {p.player_id: c.name for c in classes for p in c.players}
    prices: dict[int, PlayerPrice] = {}
    for p in state.pool:
        if p.player_id in state.excluded:
            continue
        c = by_class[p.role_class]
        if c.j_max == 0:
            prices[p.player_id] = PlayerPrice(p.player_id, c.name, Band(0, 0, 0), expected[p.player_id], 0.0,
                                              float(solution.total[budget]), NEG, True)
            continue
        weight = c.weights[0]
        wants_exact = exact or p.player_id == focus
        if wants_exact and p.player_id in candidate_of:
            keep = [i for i, q in enumerate(c.players) if q.player_id != p.player_id]
            costs, values = c.costs[keep], c.values[keep]
            walk = _at(solution.others[c.name],
                       _best(_curve(costs, values, c.weights, budget, penalty), c.j_min, c.j_max, c.cap), budget)
            curve = _maxplus(solution.others[c.name],
                             _best(_curve(costs, values, c.weights[1:], budget, penalty), max(0, c.j_min - 1),
                                   max(0, c.j_max - 1), c.cap))
        else:
            walk, curve = float(solution.total[budget]), solution.minus_one[c.name]
        band = Band(*(_max_price(weight * v - penalty, curve, walk, budget)
                      for v in (p.value_p25, p.value_p50, p.value_p75)))
        if c.cap is not None:                                   # a budget share caps the class, so it caps the price
            band = Band(*(min(x, c.cap) for x in (band.p25, band.p50, band.p75)))
        completion = float(curve[budget - band.p50])
        buy = weight * p.value_p50 - penalty + completion if completion > NEG else NEG
        prices[p.player_id] = PlayerPrice(p.player_id, c.name, band, expected[p.player_id], weight, walk, buy,
                                          wants_exact)
    owned = Counter(o.role_class for o in state.owned)
    departed = tuple(cls for cls, n in state.targets.items()
                     if solution.composition.get(cls, 0) + owned.get(cls, 0) < n)
    return BoardPricing(prices, inflation, expected, solution.composition, solution.credits,
                        float(solution.total[budget]), reserve, budget, penalty, departed)


def explain(board: BoardPricing, player_id: int) -> dict[str, Any]:
    """The trace behind one price, for the model to read: never a recomputation."""
    price = board.prices[player_id]
    return {"player_id": player_id, "role_class": price.role_class, "band": price.band.to_dict(),
            "expected_price": price.expected_price, "rank_weight": price.rank_weight,
            "walk_value": price.walk_value, "buy_value": price.buy_value, "exact": price.exact,
            "inflation": board.inflation, "composition": board.composition,
            "credits_by_class": board.credits_by_class, "completion_value": board.completion_value,
            "reserve": board.reserve, "budget": board.budget, "slot_price": board.slot_price,
            "targets_departed": list(board.targets_departed),
            "note": ("priced with him removed from the pool in both branches" if price.exact
                     else "board price: the walk-away plan still counts him as available; the lot on the block is exact")}
