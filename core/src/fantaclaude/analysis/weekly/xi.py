"""The XI: my roster from the latest snapshot, one exact solve per permitted
module (spec, "The optimiser")."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.forecast import ForecastRow
from fantaclaude.model.modules import Module, assign_weighted
from fantaclaude.model.roles import Role

ADAPTED_MALUS = 1.0      # Mantra: a player out of position scores his voto minus one


@dataclass(frozen=True)
class RosterPlayer:
    player_id: int
    name: str
    roles: frozenset[Role]
    cost: int
    in_listone: bool


def my_roster(con: duckdb.DuckDBPyConnection, team_id: int) -> list[RosterPlayer]:
    """The team's roster in the latest snapshot, with the listone's roles; an id
    the listone lacks is kept with no roles (it can be fielded nowhere)."""
    rows = con.execute(
        "SELECT r.player_id, r.cost, p.name, p.mantra_roles FROM v_rosters_current r "
        "LEFT JOIN v_players_current p ON p.player_id = r.player_id WHERE r.team_id = ? ORDER BY r.position",
        [team_id]).fetchall()
    if not rows:
        raise ForecastError(f"team {team_id} has no roster in the latest snapshot -- run `fantaclaude ingest rosters`")
    return [RosterPlayer(int(pid), str(name) if name is not None else f"#{pid}",
                         frozenset(Role(r) for r in (roles or [])), int(cost), name is not None)
            for pid, cost, name, roles in rows]


@dataclass(frozen=True)
class XiSlot:
    slot: str
    player_id: int
    name: str
    fit: str
    expected_points: float

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "player_id": self.player_id, "name": self.name, "fit": self.fit,
                "expected_points": self.expected_points}


@dataclass(frozen=True)
class XiChoice:
    module: str
    total: float
    slots: list[XiSlot]
    module_scores: dict[str, float | None]
    unlisted: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "total": self.total, "slots": [s.to_dict() for s in self.slots],
                "module_scores": dict(self.module_scores), "unlisted": list(self.unlisted)}


def choose_xi(roster: list[RosterPlayer], forecast_by_id: dict[int, ForecastRow], modules: dict[str, Module],
              allowed: Sequence[str], excluded: frozenset[int] = frozenset()) -> XiChoice:
    """One exact solve per permitted module; the best total wins. A roster
    player not in `forecast_by_id` -- the page does not list him, or the run
    never priced him -- is worth zero this week and is named (the caller
    tells the two reasons apart; `forecast_by_id` alone cannot). A player in
    `excluded` (a lineup-notes.yml exclude note) is dropped from the roster
    before the solve: he cannot be fielded this week."""
    roster = [p for p in roster if p.player_id not in excluded]
    natural: list[float] = []
    adapted: list[float] = []
    for p in roster:
        row = forecast_by_id.get(p.player_id)
        points = row.expected_points if row else 0.0
        natural.append(points)
        adapted.append(points - (row.p_start * ADAPTED_MALUS if row else 0.0))
    roles = [p.roles for p in roster]
    scores: dict[str, float | None] = {}
    best: tuple[str, float, list[int]] | None = None
    for code in allowed:
        module = modules.get(str(code))
        if module is None:
            raise ForecastError(f"the league permits module {code!r}, which is not in modules.yml")
        solved = assign_weighted(module, roles, natural, adapted)
        scores[str(code)] = None if solved is None else solved[0]
        if solved is not None and (best is None or solved[0] > best[1]):
            best = (str(code), solved[0], solved[1])
    if best is None:
        raise ForecastError("no permitted module can be fielded from this roster")
    code, total, chosen = best
    slots = []
    for k, i in enumerate(chosen):
        fit = modules[code].slots[k].fit(roster[i].roles)
        points = natural[i] if fit.value == "natural" else adapted[i]
        slots.append(XiSlot(modules[code].slots[k].label, roster[i].player_id, roster[i].name, fit.value, points))
    unlisted = [p.player_id for p in roster if p.player_id not in forecast_by_id]
    return XiChoice(code, total, slots, scores, unlisted)
