"""A valuation run read back for the night (spec: "`asta serve --run <id>`
loads the pinned valuation into memory at startup, so the advice loop
never reaches for a file at all").

Everything the live board needs to reproduce the run's own board at minute
zero comes from the run's rows, never from the working tree: the
projections and quotazioni from `valuations`; the pricing knobs, the
scenarios and the folded per-module demand from `valuation_runs.config`;
the league's bounds from the `league_settings` row the run was priced
under; the committed bands from `valuation_prices`. pricing.yml as it is
today may already be a different model -- the run is the record. A run
recorded before `config` carried `demand_by_module` and `hard_minimums`
-- the two halves of what modules.yml contributes to a price -- has them
re-derived from its own rows' role sets and from the file, and says so.
modules.yml is in neither model_hash nor rules_hash, so an edit there
supersedes no run: reading both halves from the run is the only thing
that keeps them in step.

A scenario is pinnable only if the run *priced* it: `rank --scenario
balanced` writes one band per player and one scenario's rows, so
preferences.yml naming three scenarios does not make three boards exist.
The scenarios are therefore the ones with committed `valuation_prices`
rows, not the ones the run's preferences define -- otherwise `asta board
--scenario value-hunting` would be accepted for a scenario with no
committed band behind it, and `describe()` would advertise it.

Without a run id the newest run whose rules_hash is not superseded is
taken and named (spec: "so the wrong run cannot be pinned silently"); a
superseded run can be pinned by id, and the board says it is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from fantaclaude.analysis.valuation import (
    PreferencesError,
    Scenario,
    UnknownScenarioError,
    load_scenarios,
)
from fantaclaude.asta.pricing import Band, PoolPlayer, PricingConfig
from fantaclaude.asta.session import SessionError, SessionSettings, league_bounds
from fantaclaude.ingest.names import Candidate
from fantaclaude.model.demand import (
    hard_minimums,
    module_demand,
    rank_weights,
    satisfiable_demand,
)
from fantaclaude.model.roles import Role


class PinnedRunError(RuntimeError):
    """No run to pin, or a run this code cannot read back."""


@dataclass(frozen=True)
class PinnedPlayer:
    player_id: int
    name: str
    team_short: str
    classic_role: str
    role_class: str
    roles: tuple[str, ...]
    value_p25: float
    value_p50: float
    value_p75: float
    quotazione: int
    tier: int

    @property
    def is_goalkeeper(self) -> bool:
        return "Por" in self.roles

    def pool_player(self) -> PoolPlayer:
        return PoolPlayer(self.player_id, self.name, self.role_class, self.value_p25, self.value_p50, self.value_p75,
                          self.quotazione)

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short,
                "classic_role": self.classic_role, "role_class": self.role_class, "roles": list(self.roles),
                "value_p25": self.value_p25, "value_p50": self.value_p50, "value_p75": self.value_p75,
                "quotazione": self.quotazione, "tier": self.tier}


@dataclass(frozen=True)
class PinnedRun:
    run_id: str
    created_at: datetime
    rules_hash: str
    model_hash: str
    superseded: bool
    settings_snapshot_id: int
    listone_snapshot_id: int
    season_id: int
    giornata: int
    players: dict[int, PinnedPlayer]
    pricing_cfg: PricingConfig
    scenarios: list[Scenario]                     # only the ones this run committed prices for
    demand: dict[str, dict[str, float]]           # per module, folded, as the run priced it
    demand_rederived: bool
    hard_minimums: dict[str, int]                 # modules.yml's, as the run priced against them
    league: SessionSettings                       # the bounds the run was priced under
    prices: dict[str, dict[int, Band]]            # per scenario, the committed bands
    club_names: dict[str, str]                    # team_short -> the listone's club name

    def scenario(self, name: str | None = None) -> Scenario:
        if name is None:
            return self.scenarios[0]
        for scenario in self.scenarios:
            if scenario.name == name:
                return scenario
        raise UnknownScenarioError(f"run {self.run_id} has no scenario {name!r}; it priced {[s.name for s in self.scenarios]}")

    def candidates(self) -> list[Candidate]:
        return [Candidate(p.player_id, p.name, p.team_short, self.club_names.get(p.team_short, p.team_short))
                for p in sorted(self.players.values(), key=lambda p: p.player_id)]

    def weights(self, targets: dict[str, int], min_ranks: dict[str, int]) -> dict[str, tuple[float, ...]]:
        cfg = self.pricing_cfg
        return rank_weights(self.demand, max_rank=max(cfg.max_per_class, cfg.max_goalkeepers), bench_weight=cfg.bench_weight,
                            bench_decay=cfg.bench_decay, bench_slots=cfg.bench_slots_per_class, targets=targets,
                            target_weight=cfg.target_weight, min_ranks=min_ranks)

    def describe(self) -> str:
        state = "superseded by a rules change" if self.superseded else "current"
        return (f"run {self.run_id} · rules {self.rules_hash} · model {self.model_hash} · {len(self.players)} players · "
                f"scenarios {', '.join(s.name for s in self.scenarios)} · {state}"
                + (" · demand re-derived (the run predates demand_by_module / hard_minimums)"
                   if self.demand_rederived else ""))


def newest_run_id(con: duckdb.DuckDBPyConnection) -> str | None:
    row = con.execute("SELECT run_id FROM v_valuation_runs WHERE NOT superseded "
                      "ORDER BY created_at DESC, run_id DESC LIMIT 1").fetchone()
    return None if row is None else str(row[0])


def _rederive_demand(players: dict[int, PinnedPlayer], cfg: PricingConfig) -> dict[str, dict[str, float]]:
    """The folded demand of a run recorded before `config` carried it, from
    the run's own rows: the same fold, against the same supply, in the same
    module-code order the config would have stored it in."""
    supply = [frozenset(Role(r) for r in p.roles) for p in players.values()]
    demand = satisfiable_demand(module_demand(), supply, max_rank=max(cfg.max_per_class, cfg.max_goalkeepers),
                                bench_weight=cfg.bench_weight, bench_decay=cfg.bench_decay,
                                bench_slots=cfg.bench_slots_per_class)
    return {code: demand[code] for code in sorted(demand)}


def load_pinned_run(con: duckdb.DuckDBPyConnection, run_id: str | None = None) -> PinnedRun:
    if run_id is None:
        run_id = newest_run_id(con)
        if run_id is None:
            count = con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0]
            raise PinnedRunError("every valuation run is superseded by a rules change -- run `fantaclaude rank`, "
                                 "or pin one by id with --run" if count else "no valuation run to pin -- run `fantaclaude rank`")
    row = con.execute("SELECT run_id, created_at, rules_hash, model_hash, superseded, settings_snapshot_id, "
                      "listone_snapshot_id, season_id, giornata, config FROM v_valuation_runs WHERE run_id = ?",
                      [run_id]).fetchone()
    if row is None:
        raise PinnedRunError(f"no valuation run {run_id!r}")
    config = row[9] if isinstance(row[9], dict) else json.loads(row[9])
    try:
        pricing_cfg = PricingConfig(**config["pricing"])
        defined = load_scenarios(config["preferences"])
    except (KeyError, TypeError, PreferencesError) as exc:
        raise PinnedRunError(f"run {run_id}: its config cannot be read back by this code ({exc})") from None
    players = {int(r[0]): PinnedPlayer(int(r[0]), str(r[1]), str(r[2] or ""), str(r[3]), str(r[4]), tuple(r[5]),
                                       float(r[6]), float(r[7]), float(r[8]), int(r[9] or 0), int(r[10]))
               for r in con.execute("SELECT player_id, name, team_short, classic_role, role_class, roles, value_p25, "
                                    "value_p50, value_p75, quot_mantra, tier FROM valuations WHERE run_id = ? "
                                    "ORDER BY player_id", [run_id]).fetchall()}
    if not players:
        raise PinnedRunError(f"run {run_id} has no valuations rows")
    # modules.yml's two contributions to a price, both read from the run. They
    # were recorded by the same commit, so a run predating one predates both;
    # either missing is a run whose board is not wholly its own, and it says so.
    demand = config.get("demand_by_module")
    minimums = config.get("hard_minimums")
    rederived = not demand or not minimums
    if not demand:
        demand = _rederive_demand(players, pricing_cfg)
    if not minimums:
        minimums = hard_minimums()
    try:
        league = league_bounds(con, int(row[5]))
    except SessionError as exc:
        raise PinnedRunError(f"run {run_id}: {exc}") from None
    prices: dict[str, dict[int, Band]] = {}
    for scenario, pid, p25, p50, p75 in con.execute(
            "SELECT scenario, player_id, max_p25, max_p50, max_p75 FROM valuation_prices WHERE run_id = ?", [run_id]).fetchall():
        prices.setdefault(str(scenario), {})[int(pid)] = Band(int(p25), int(p50), int(p75))
    # The scenarios of the run are the ones it priced, in preferences.yml's own
    # order: a scenario the run filtered out has no committed band, so naming it
    # is a usage error rather than a board nobody computed.
    scenarios = [s for s in defined if s.name in prices]
    if not scenarios:
        raise PinnedRunError(f"run {run_id} has no committed prices for any scenario preferences.yml defines "
                             f"({[s.name for s in defined]}); it recorded {sorted(prices)}")
    clubs = {str(short): str(name) for name, short in con.execute(
        "SELECT name, short FROM teams WHERE snapshot_id = ?", [int(row[6])]).fetchall() if short}
    return PinnedRun(run_id=str(row[0]), created_at=row[1], rules_hash=str(row[2]), model_hash=str(row[3]),
                     superseded=bool(row[4]), settings_snapshot_id=int(row[5]), listone_snapshot_id=int(row[6]),
                     season_id=int(row[7]), giornata=int(row[8]), players=players, pricing_cfg=pricing_cfg,
                     scenarios=scenarios, demand={code: dict(by_class) for code, by_class in demand.items()},
                     demand_rederived=rederived, hard_minimums={cls: int(n) for cls, n in minimums.items()}, league=league,
                     prices={s.name: prices[s.name] for s in scenarios}, club_names=clubs)
