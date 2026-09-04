"""The eleven Mantra modules as slot lists, and exact feasibility matching.

modules.yml is domain data transcribed from the official table (see its
header); nothing here infers a slot from the API. `assign` answers "can this
roster field this module?" exactly, by bipartite matching -- the question the
valuation and the auction advisor ask, and one that eyeballing gets wrong for
multi-role players. `assign_weighted` answers the weekly question beside it
-- which eleven, and where -- exactly, by max-weight matching.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

import yaml

from .roles import Role

MODULES_YML = Path(__file__).with_name("modules.yml")


class Fit(Enum):
    NATURAL = "natural"        # "ok" in the table: no malus
    ADAPTED = "adapted"        # "-1": out of position, with the malus
    FORCED_ONLY = "forced"     # "-1*": only through a forced substitution
    NO = "no"


@dataclass(frozen=True)
class Slot:
    label: str
    natural: frozenset[Role]
    adapted: frozenset[Role]
    forced_only: frozenset[Role]

    def fit(self, roles: frozenset[Role]) -> Fit:
        """The best fit any of a player's roles gives for this slot."""
        if roles & self.natural:
            return Fit.NATURAL
        if roles & self.adapted:
            return Fit.ADAPTED
        if roles & self.forced_only:
            return Fit.FORCED_ONLY
        return Fit.NO


@dataclass(frozen=True)
class Module:
    code: str            # "343" -- the key settings/lineup.mods uses
    label: str           # "3-4-3"
    slots: tuple[Slot, ...]

    def slot_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for slot in self.slots:
            counts[slot.label] = counts.get(slot.label, 0) + 1
        return counts


class ModuleTableError(ValueError):
    """modules.yml does not describe a legal Mantra module table."""


def _roles(names: list[str] | None) -> frozenset[Role]:
    return frozenset(Role(n) for n in (names or []))


@cache
def load_modules(path: Path = MODULES_YML) -> dict[str, Module]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_modules = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(raw_modules, dict):
        raise ModuleTableError(f"{path}: expected a top-level 'modules' mapping")
    modules: dict[str, Module] = {}
    for code, entry in raw_modules.items():
        slots = tuple(
            Slot(label=str(s["slot"]), natural=_roles(s.get("natural")),
                 adapted=_roles(s.get("adapted")), forced_only=_roles(s.get("forced_only")))
            for s in entry["slots"]
        )
        module = Module(code=str(code), label=str(entry["label"]), slots=slots)
        _validate(module)
        modules[module.code] = module
    if len(modules) != 11:
        raise ModuleTableError(f"{path}: expected 11 modules, found {len(modules)}")
    return modules


def _validate(module: Module) -> None:
    if len(module.slots) != 11:
        raise ModuleTableError(f"{module.label}: {len(module.slots)} slots, expected 11")
    if sum(1 for s in module.slots if s.natural == {Role.Por}) != 1:
        raise ModuleTableError(f"{module.label}: exactly one Por slot expected")
    for slot in module.slots:
        if set(slot.label.split("/")) != {r.value for r in slot.natural}:
            raise ModuleTableError(
                f"{module.label}: slot {slot.label!r} natural roles do not match its label")
        if (slot.natural & slot.adapted or slot.natural & slot.forced_only
                or slot.adapted & slot.forced_only):
            raise ModuleTableError(f"{module.label}: slot {slot.label!r} lists a role under two fits")


def assign(module: Module, roster: Sequence[frozenset[Role]], *,
           allow_adapted: bool = False) -> list[int] | None:
    """Match players to slots: per slot, the index into `roster` of the
    player fielded there, or None if the roster cannot field the module.

    Natural fits only, unless `allow_adapted`, which also accepts ADAPTED --
    never FORCED_ONLY, which is not legal at lineup insertion. Exact:
    augmenting-path bipartite matching over eleven slots, so a roster of
    forty multi-role players is answered in microseconds and never by
    guesswork.
    """
    accepted = {Fit.NATURAL, Fit.ADAPTED} if allow_adapted else {Fit.NATURAL}
    candidates = [[i for i, roles in enumerate(roster) if slot.fit(roles) in accepted]
                  for slot in module.slots]
    owner: dict[int, int] = {}          # player index -> slot index

    def try_slot(slot_index: int, seen: set[int]) -> bool:
        for player in candidates[slot_index]:
            if player in seen:
                continue
            seen.add(player)
            if player not in owner or try_slot(owner[player], seen):
                owner[player] = slot_index
                return True
        return False

    for slot_index in range(len(module.slots)):
        if not try_slot(slot_index, set()):
            return None
    result = [-1] * len(module.slots)
    for player, slot_index in owner.items():
        result[slot_index] = player
    return result


_FORBIDDEN = 1e9      # a pair the table forbids: dearer than any legal eleven can ever be


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment of every row to a distinct column (rows <= columns):
    per row, the column chosen. Potentials and shortest augmenting paths,
    O(rows^2 x columns) -- eleven slots against forty players is microseconds."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    matched = [0] * (m + 1)          # matched[j]: the row (1-based) holding column j, 0 = free
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        matched[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = matched[j0]
            delta, j1 = inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[matched[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if matched[j0] == 0:
                break
        while True:
            j1 = way[j0]
            matched[j0] = matched[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1] * n
    for j in range(1, m + 1):
        if matched[j]:
            result[matched[j] - 1] = j - 1
    return result


def assign_weighted(module: Module, roster: Sequence[frozenset[Role]], natural: Sequence[float],
                    adapted: Sequence[float]) -> tuple[float, list[int]] | None:
    """The eleven that maximise total weight: (total, per slot the roster index),
    or None when the roster cannot field the module. A player fielded ADAPTED
    contributes `adapted[i]` -- his expected points net of the out-of-position
    malus -- instead of `natural[i]`; FORCED_ONLY and NO are never fielded, the
    same rule `assign` keeps. Exact, like `assign`: the one thing eyeballing a
    multi-role roster gets wrong is exactly what this exists to prevent."""
    if not (len(roster) == len(natural) == len(adapted)):
        raise ValueError("roster, natural and adapted must be the same length")
    if len(roster) < len(module.slots):
        return None
    cost: list[list[float]] = []
    for slot in module.slots:
        row: list[float] = []
        for i, roles in enumerate(roster):
            fit = slot.fit(roles)
            if fit is Fit.NATURAL:
                row.append(-float(natural[i]))
            elif fit is Fit.ADAPTED:
                row.append(-float(adapted[i]))
            else:
                row.append(_FORBIDDEN)
        cost.append(row)
    chosen = _hungarian(cost)
    total = 0.0
    for slot_index, player in enumerate(chosen):
        if cost[slot_index][player] >= _FORBIDDEN:
            return None
        total -= cost[slot_index][player]
    return total, chosen
