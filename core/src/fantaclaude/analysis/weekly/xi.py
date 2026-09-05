"""The XI: my roster from the latest snapshot, one exact solve per permitted
module (spec, "The optimiser")."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.forecast import ForecastRow
from fantaclaude.model.modules import Fit, Module, assign_weighted
from fantaclaude.model.roles import Role, sort_roles

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


@dataclass(frozen=True)
class BenchEntry:
    player_id: int
    name: str
    roles: tuple[str, ...]
    expected_points: float
    coverage: float
    covers: tuple[str, ...]
    diffidato: bool

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "roles": list(self.roles),
                "expected_points": self.expected_points, "coverage": self.coverage, "covers": list(self.covers),
                "diffidato": self.diffidato}


@dataclass(frozen=True)
class Bench:
    order: list[BenchEntry]
    uncovered: tuple[str, ...]
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"order": [e.to_dict() for e in self.order], "uncovered": list(self.uncovered), "size": self.size}


def _net(row: ForecastRow | None, fit: Fit) -> float:
    if row is None:
        return 0.0
    return row.expected_points - (row.p_start * ADAPTED_MALUS if fit is Fit.ADAPTED else 0.0)


def order_bench(roster: list[RosterPlayer], xi: XiChoice, forecast_by_id: dict[int, ForecastRow], module: Module, *,
                bench_size: int, excluded: frozenset[int] = frozenset()) -> Bench:
    """The bench in the order the platform will read it (spec, "The ordered
    bench"). The goalkeeper first -- the best remaining Por -- because the
    platform substitutes him first and separately. Then coverage value:
    for each candidate, the sum over the starters of that starter's
    probability of no voto, times whether the candidate legally fits the
    starter's slot (natural or adapted, never forced-only), times the
    candidate's expected points net of the malus where adapted. Built for a
    substitution that keeps the module (open question 20). A slot no bench
    player can legally fill is named."""
    fielded = {s.player_id for s in xi.slots}
    starters = [(module.slots[k], forecast_by_id.get(s.player_id)) for k, s in enumerate(xi.slots)]
    candidates = [p for p in roster if p.player_id not in fielded and p.player_id not in excluded]
    entries: list[BenchEntry] = []
    for p in candidates:
        row = forecast_by_id.get(p.player_id)
        coverage, covers = 0.0, []
        for slot, starter in starters:
            fit = slot.fit(p.roles)
            if fit not in (Fit.NATURAL, Fit.ADAPTED):
                continue
            miss = 1.0 - (starter.p_start if starter is not None else 0.0)
            coverage += miss * _net(row, fit)
            if slot.label not in covers:
                covers.append(slot.label)
        entries.append(BenchEntry(p.player_id, p.name, tuple(r.value for r in sort_roles(p.roles)),
                                  row.expected_points if row else 0.0, coverage, tuple(covers),
                                  bool(row and row.trace.get("diffidato"))))
    keepers = sorted((e for e in entries if Role.Por in roster_roles(roster, e.player_id)), key=lambda e: (-e.expected_points, e.name))
    rest = sorted((e for e in entries if e not in keepers[:1]), key=lambda e: (-e.coverage, -e.expected_points, e.name))
    order = (keepers[:1] + rest)[:max(bench_size, 0)]
    covered = {label for e in order for label in e.covers}
    uncovered = tuple(dict.fromkeys(slot.label for slot in module.slots if slot.label not in covered))
    return Bench(order, uncovered, bench_size)


def roster_roles(roster: list[RosterPlayer], player_id: int) -> frozenset[Role]:
    return next((p.roles for p in roster if p.player_id == player_id), frozenset())


@dataclass(frozen=True)
class Contingency:
    player_id: int
    name: str
    p_start: float
    module: str | None
    module_changes: bool
    enters: tuple[XiSlot, ...]
    leaves: tuple[XiSlot, ...]
    points_lost: float | None
    note: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "p_start": self.p_start, "module": self.module,
                "module_changes": self.module_changes, "enters": [s.to_dict() for s in self.enters],
                "leaves": [s.to_dict() for s in self.leaves], "points_lost": self.points_lost, "note": self.note}


def contingencies(roster: list[RosterPlayer], forecast_by_id: dict[int, ForecastRow], modules: dict[str, Module],
                  allowed: Sequence[str], xi: XiChoice, *, threshold: float,
                  excluded: frozenset[int] = frozenset()) -> list[Contingency]:
    """"If he doesn't start, do this", by computation: for each starter
    whose p_start is below the threshold, one re-solve with him at zero,
    reported as the diff (spec, "The contingencies")."""
    out: list[Contingency] = []
    fielded = {s.player_id for s in xi.slots}
    for s in xi.slots:
        row = forecast_by_id.get(s.player_id)
        p = row.p_start if row is not None else 0.0
        if p >= threshold:
            continue
        try:
            alt = choose_xi(roster, forecast_by_id, modules, allowed, excluded=excluded | {s.player_id})
        except ForecastError as exc:
            out.append(Contingency(s.player_id, s.name, p, None, False, (), (), None, str(exc)))
            continue
        alt_ids = {a.player_id for a in alt.slots}
        enters = tuple(a for a in alt.slots if a.player_id not in fielded)
        leaves = tuple(o for o in xi.slots if o.player_id not in alt_ids)
        out.append(Contingency(s.player_id, s.name, p, alt.module, alt.module != xi.module, enters, leaves,
                               xi.total - alt.total, None))
    return out


@dataclass(frozen=True)
class CloseCall:
    slot: str
    player_in: dict[str, Any]
    player_out: dict[str, Any]
    gap: float

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "in": self.player_in, "out": self.player_out, "gap": self.gap}


def _call_side(row: ForecastRow | None, player: RosterPlayer, net: float) -> dict[str, Any]:
    return {"player_id": player.player_id, "name": player.name, "expected_points": net,
            "fv_sd": row.fv_sd if row else None, "source": row.source if row else None,
            "matchup": row.matchup if row else None}


def close_calls(roster: list[RosterPlayer], xi: XiChoice, forecast_by_id: dict[int, ForecastRow], module: Module, *,
                margin: float, limit: int, excluded: frozenset[int] = frozenset()) -> list[CloseCall]:
    """Per slot, the chosen player against the best excluded player who
    fits it, when the gap is inside the margin; the smallest gaps first,
    at most `limit` (spec, "The close calls")."""
    fielded = {s.player_id for s in xi.slots}
    by_id = {p.player_id: p for p in roster}
    outside = [p for p in roster if p.player_id not in fielded and p.player_id not in excluded]
    calls: list[CloseCall] = []
    for k, s in enumerate(xi.slots):
        slot = module.slots[k]
        best: tuple[float, RosterPlayer] | None = None
        for p in outside:
            fit = slot.fit(p.roles)
            if fit not in (Fit.NATURAL, Fit.ADAPTED):
                continue
            net = _net(forecast_by_id.get(p.player_id), fit)
            if best is None or net > best[0]:
                best = (net, p)
        if best is None:
            continue
        gap = s.expected_points - best[0]
        if gap < margin:
            calls.append(CloseCall(slot.label, _call_side(forecast_by_id.get(s.player_id), by_id[s.player_id], s.expected_points),
                                   _call_side(forecast_by_id.get(best[1].player_id), best[1], best[0]), gap))
    return sorted(calls, key=lambda c: c.gap)[:max(limit, 0)]
