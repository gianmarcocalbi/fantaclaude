"""The week's verdict (spec, "Calibration: what 3c ships").

My score is the platform's `tot`, never a recomputation: its substitutions
and the adaptation malus are already in it, and reimplementing the
platform's Mantra substitution is a non-goal. Beside it, the best eleven my
roster could have fielded knowing the fantavoti -- the exact solve per
permitted module over the players who got a voto, a player fielded adapted
worth his fantavoto less the malus -- and the model's XI scored on its own
eleven: exact when all eleven got a voto, because then the platform would
have made no substitution, otherwise a lower bound that names who had none.
Never completed by a guessed substitution. Under an active scoring modifier
a per-slot sum no longer scores an eleven, so both are refused with the
reason and the platform's own numbers stand.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import duckdb

from fantaclaude.analysis.calibration.errors import CalibrationError
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.submitted import load_run_xi
from fantaclaude.analysis.weekly.xi import ADAPTED_MALUS, RosterPlayer
from fantaclaude.ingest.match_scores import oriented_result
from fantaclaude.model.modules import Fit, Module, assign_weighted
from fantaclaude.model.roles import Role


@dataclass(frozen=True)
class SlotScore:
    slot: str
    player_id: int
    name: str
    fit: str
    fantavoto: float | None          # None: no voto


@dataclass(frozen=True)
class XiScore:
    module: str
    total: float
    exact: bool
    missing: list[str]
    slots: list[SlotScore]

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "total": self.total, "exact": self.exact, "missing": list(self.missing),
                "slots": [asdict(s) for s in self.slots]}


@dataclass(frozen=True)
class FieldedPlayer:
    """One platform-side row of the fielded eleven or the bench, in the
    platform's own order (position within its part)."""
    part: str                        # 'xi' or 'bench'
    position: int
    player_id: int
    name: str
    status: str
    fantavoto: float | None          # None: no voto
    malus: int


@dataclass(frozen=True)
class Week:
    giornata: int
    match_file: int
    my_team: int
    opponent: int
    opponent_name: str | None
    my_total: float
    opponent_total: float
    result: str | None               # my goals first
    points: int
    module: str | None
    eleven_total: float
    eleven_missing: list[str]
    bench_added: float
    best: XiScore | None
    best_note: str | None
    left_on_bench: float | None
    model_xi: XiScore | None
    model_note: str | None
    lineup_run_id: int | None
    roster_note: str
    fielded: list[FieldedPlayer]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["best"] = None if self.best is None else self.best.to_dict()
        out["model_xi"] = None if self.model_xi is None else self.model_xi.to_dict()
        return out


def best_xi(roster: Sequence[RosterPlayer], fantavoti: dict[int, float], modules: dict[str, Module],
            allowed: Sequence[str]) -> XiScore | None:
    """The eleven that would have scored most, knowing every fantavoto; None
    when no permitted module can be filled from the players who got one."""
    available = [p for p in roster if p.player_id in fantavoti]
    natural = [fantavoti[p.player_id] for p in available]
    adapted = [value - ADAPTED_MALUS for value in natural]
    roles = [p.roles for p in available]
    best: tuple[str, float, list[int]] | None = None
    for code in allowed:
        module = modules.get(str(code))
        if module is None:
            raise CalibrationError(f"the league permits module {code!r}, which is not in modules.yml")
        solved = assign_weighted(module, roles, natural, adapted)
        if solved is not None and (best is None or solved[0] > best[1]):
            best = (str(code), solved[0], solved[1])
    if best is None:
        return None
    code, total, chosen = best
    slots = []
    for k, i in enumerate(chosen):
        slot = modules[code].slots[k]
        fit = slot.fit(available[i].roles)
        slots.append(SlotScore(slot.label, available[i].player_id, available[i].name, fit.value,
                               natural[i] if fit is Fit.NATURAL else adapted[i]))
    return XiScore(code, total, True, [], slots)


def score_run_xi(xi: Sequence[dict[str, Any]], fantavoti: dict[int, float], module: str) -> XiScore:
    """A named XI on its own eleven: exact when every one got a voto."""
    slots: list[SlotScore] = []
    missing: list[str] = []
    total = 0.0
    for entry in xi:
        pid = int(entry["player_id"])
        name = str(entry.get("name") or f"#{pid}")
        fit = str(entry.get("fit") or Fit.NATURAL.value)
        value = fantavoti.get(pid)
        if value is None:
            missing.append(name)
        else:
            value -= ADAPTED_MALUS if fit == Fit.ADAPTED.value else 0.0
            total += value
        slots.append(SlotScore(str(entry.get("slot")), pid, name, fit, value))
    return XiScore(module, total, not missing, missing, slots)


def roster_before(con: duckdb.DuckDBPyConnection, team_id: int,
                  before: datetime | None) -> tuple[list[RosterPlayer], str]:
    """My roster as it stood: the newest snapshot naming the team fetched
    before `before` (the round's first kickoff), else the earliest -- and a
    note saying which."""
    snapshot = None
    if before is not None:
        snapshot = con.execute(
            "SELECT max(s.snapshot_id) FROM roster_snapshots s WHERE s.fetched_at < ? "
            "AND s.snapshot_id IN (SELECT snapshot_id FROM rosters WHERE team_id = ?)", [before, team_id]).fetchone()[0]
    if snapshot is not None:
        note = f"roster snapshot {snapshot}, fetched before the round's first kickoff"
    else:
        snapshot = con.execute("SELECT min(snapshot_id) FROM rosters WHERE team_id = ?", [team_id]).fetchone()[0]
        if snapshot is None:
            return [], f"no roster snapshot names team {team_id} -- run `fantaclaude ingest rosters`"
        note = f"roster snapshot {snapshot}, the earliest -- none was fetched before the round's first kickoff"
    rows = con.execute(
        "SELECT r.player_id, r.cost, p.name, p.mantra_roles FROM rosters r "
        "LEFT JOIN v_players_current p ON p.player_id = r.player_id "
        "WHERE r.snapshot_id = ? AND r.team_id = ? ORDER BY r.position", [snapshot, team_id]).fetchall()
    roster = [RosterPlayer(int(pid), str(name) if name is not None else f"#{pid}",
                           frozenset(Role(r) for r in (roles or [])), int(cost), name is not None)
              for pid, cost, name, roles in rows]
    return roster, note


def week(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int, my_team: int,
         fantavoti: dict[int, float], modules: dict[str, Module], allowed: Sequence[str],
         refusal: str | None) -> Week | None:
    """The verdict for one giornata, or None when no match of mine is recorded for it."""
    row = con.execute(
        "SELECT file_id, home_team, away_team, home_module, away_module, home_total, away_total, home_points, "
        "away_points, result FROM v_match_files_current WHERE season_id = ? AND giornata = ? "
        "AND (home_team = ? OR away_team = ?) ORDER BY file_id DESC LIMIT 1",
        [season_id, giornata, my_team, my_team]).fetchone()
    if row is None:
        return None
    file_id, home, away, home_module, away_module, home_total, away_total, home_points, away_points, result = row
    mine_home = home == my_team
    opponent = away if mine_home else home
    my_total, opponent_total = (home_total, away_total) if mine_home else (away_total, home_total)
    fielded_rows = con.execute(
        "SELECT s.part, s.position, s.player_id, s.status, s.fantavoto, s.malus, p.name FROM match_scores s "
        "LEFT JOIN v_players_current p ON p.player_id = s.player_id "
        "WHERE s.file_id = ? AND s.team_id = ? ORDER BY (s.part != 'xi'), s.position",
        [file_id, my_team]).fetchall()
    fielded = [FieldedPlayer(part, int(position), int(pid), (name or f"#{pid}"), status, fantavoto, int(malus))
              for part, position, pid, status, fantavoto, malus, name in fielded_rows]
    eleven_total = sum(f.fantavoto for f in fielded if f.part == "xi" and f.status == "voto")
    eleven_missing = [f.name for f in fielded if f.part == "xi" and f.status != "voto"]
    opponent_name = con.execute("SELECT any_value(team_name) FROM rosters WHERE team_id = ?", [opponent]).fetchone()[0]
    first = con.execute("SELECT min(kickoff) FROM v_fixtures_current WHERE competition = 'SA' AND season_id = ? "
                        "AND giornata = ?", [season_id, giornata]).fetchone()[0]
    roster, roster_note = roster_before(con, my_team, first)
    best = model = None
    best_note = model_note = None
    lineup_run_id = None
    if refusal is not None:
        best_note = model_note = refusal
    else:
        best = best_xi(roster, fantavoti, modules, allowed)
        if best is None:
            best_note = "no permitted module can be filled from the players who got a voto"
        try:
            run = load_run_xi(con, season_id=season_id, giornata=giornata, lineup_run_id=None)
        except ForecastError:
            model_note = "no forecast named an XI for this giornata before the lock"
        else:
            model, lineup_run_id = score_run_xi(run.xi, fantavoti, run.module), run.lineup_run_id
    return Week(giornata, int(file_id), my_team, int(opponent), opponent_name, float(my_total), float(opponent_total),
                oriented_result(result, mine_home), int(home_points if mine_home else away_points),
                home_module if mine_home else away_module, float(eleven_total), eleven_missing,
                float(my_total) - float(eleven_total), best, best_note,
                None if best is None else best.total - float(my_total), model, model_note, lineup_run_id, roster_note,
                fielded)
