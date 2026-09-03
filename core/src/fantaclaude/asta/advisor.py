"""The board: what the auction state is worth to me, re-derived whole on
every state change (spec, "`fanta-asta` -- live auction copilot").

derive() turns the feed's state, the pinned run, the adjustment layer and
the team mapping into: a ledger per team (credits from the picks, never
from the feed's budget field; the buckets the session fills; what the run
cannot name), my PoolState -- the unsold pool with the value factors
applied, my picks as owned, the excluded, the targets, the credits still
on the market -- the priced board (price_board, one mode, every player
with himself out of the pool), the lot on the block with its band, and the
problems a person has to see: a pick the run cannot name, a player the
feed listed twice, a team over its budget, a session outside the league's
bounds, a roster no completion can make legal. Opponent pressure is
layered on by asta/pressure.py.

The adjustment layer reaches the board three different ways, because its
three kinds have three different mechanics: `value` scales the pool's
quantiles (apply_layer) and my owned players' worth, `exclude` becomes
PoolState.excluded so it raises the rest of the class through V, and
`target` merges into the composition the optimiser starts from and so into
the rank weights. None of the three annotates a priced row.

At minute zero, under the run's own league bounds, this is the run's
committed board band for band (spec, "One pricing function"): the same
function, the same inputs, read back from the run's rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fantaclaude.analysis.ordering import rank_key
from fantaclaude.asta.adjustments import EMPTY_LAYER, AdjustmentLayer, apply_layer
from fantaclaude.asta.pinned import PinnedRun
from fantaclaude.asta.pricing import (
    NEG,
    Band,
    BoardPricing,
    OwnedPlayer,
    PlayerPrice,
    PoolState,
    price_board,
)
from fantaclaude.asta.session import SessionSettings, compare
from fantaclaude.asta.state import AuctionState, Pick
from fantaclaude.kb.participants import Participant
from fantaclaude.model.demand import ROLE_CLASSES
from fantaclaude.values import json_safe


@dataclass(frozen=True)
class TeamMapping:
    """Which team is mine, and which dossier each other team's id maps to.
    The feed cannot supply it and the server never persists it (spec: the
    browser pre-fills it); offline it comes from flags or the state file."""
    mine: int
    nicks: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"mine": self.mine, "nicks": {str(k): v for k, v in sorted(self.nicks.items())}}


@dataclass(frozen=True)
class Ledger:
    team_id: int
    label: str
    nick: str | None
    budget: int
    spent: int
    picks: tuple[Pick, ...]
    goalkeepers: int
    outfield: int
    unknown: int                 # picks the run cannot name: credits counted, roles not

    @property
    def credits(self) -> int:
        """Deliberately unclamped, and allowed to go negative.

        The spec's testing checklist reads "credits never negative in the
        ledgers", but the ledger is the mirror, and the mirror is faithful:
        "nothing local corrects what the admin recorded". If the admin
        recorded a team spending 600 of 500, -100 is the truth and hiding it
        behind a zero would hide the fault the operator has to go and fix.

        The invariant that matters is that nothing negative reaches the
        *pricing*, and that is enforced where the pricing is fed --
        build_pool_state clamps both PoolState.credits and market_credits at
        zero (a negative balance buys nothing), and price_board refuses a
        negative outright. See
        test_advisor.test_credits_never_go_negative_where_the_pricing_can_see_them.
        """
        return self.budget - self.spent

    def missing(self, settings: SessionSettings) -> tuple[int, int]:
        """(goalkeepers, outfield) still needed to reach the session's floor."""
        return max(0, settings.goalkeepers[0] - self.goalkeepers), max(0, settings.outfield[0] - self.outfield)

    def room(self, settings: SessionSettings) -> tuple[int, int]:
        """(goalkeepers, outfield) the session still lets the team buy."""
        return max(0, settings.goalkeepers[1] - self.goalkeepers), max(0, settings.outfield[1] - self.outfield)

    def open_slots(self, settings: SessionSettings) -> int:
        """Slots the session still *lets* the team buy: the roster ceiling."""
        return max(0, settings.size[1] - len(self.picks))

    def required_slots(self, settings: SessionSettings) -> int:
        """Slots the team is still *obliged* to fill: the roster floor.

        The counterpart to open_slots, and not a correction of it -- the
        ceiling is the right answer to "how many more may he buy", which is
        what `to_dict` publishes it as. But a credit reservation is against
        what he still *must* buy, the way `missing` reads the buckets at
        [0]. Under a live session the two coincide (the bounds are exact,
        (25, 25)) so the difference never showed; offline, on `run.league`,
        the league's bounds are ranges (23-40 here), and reserving against
        the ceiling had a rival with 20 picks and 30 credits reserving 19
        of them for slots he is not obliged to fill at all. His floor of 23
        leaves him 28 to spend, not 11.

        The bucket floors are deliberately not folded in: `missing` cannot
        see which bucket a pick the run cannot name filled, so a team with
        one unknown pick would read as owing more slots than it has left,
        and that would move live numbers -- which have no fault to fix."""
        return max(0, settings.size[0] - len(self.picks))

    def to_dict(self, settings: SessionSettings) -> dict[str, Any]:
        gk, mov = self.missing(settings)
        return {"team_id": self.team_id, "label": self.label, "nick": self.nick, "budget": self.budget, "spent": self.spent,
                "credits": self.credits, "picks": [p.player_id for p in self.picks], "goalkeepers": self.goalkeepers,
                "outfield": self.outfield, "unknown": self.unknown, "missing_goalkeepers": gk, "missing_outfield": mov,
                "open_slots": self.open_slots(settings)}


@dataclass(frozen=True)
class Lot:
    player_id: int
    name: str
    team_short: str
    role_class: str
    roles: tuple[str, ...]
    tier: int
    band: Band | None            # None when he is sold or excluded
    expected_price: int | None
    sold_to: int | None
    # From the player, not the price: a sold or excluded lot has no band and no
    # expected price, but the listone's value for him is a fact either way.
    fvm: int = 0
    apps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short, "role_class": self.role_class,
                "roles": list(self.roles), "tier": self.tier, "band": None if self.band is None else self.band.to_dict(),
                "expected_price": self.expected_price, "sold_to": self.sold_to, "fvm": self.fvm, "apps": self.apps}


@dataclass(frozen=True)
class Board:
    run_id: str
    scenario: str
    state: AuctionState
    settings: SessionSettings
    league_conflicts: tuple[str, ...]
    ledgers: dict[int, Ledger]
    mine: int
    pool_state: PoolState
    pricing: BoardPricing
    selected: int | None
    lot: Lot | None
    layer: AdjustmentLayer
    problems: tuple[str, ...]
    players: dict[int, Any] = field(default_factory=dict)          # the run's PinnedPlayers, for the renderings
    club_names: dict[str, str] = field(default_factory=dict)       # team_short -> club name, for the dossiers
    pressure: dict[int, Any] = field(default_factory=dict)         # player_id -> pressure.Pressure (Task 8)
    # The league's formations. They come from the league's own settings, never
    # from the session feed, which does not carry them -- but they are what the
    # demand weights were built from, so the board shows the two together.
    league_modules: tuple[str, ...] = ()
    # modules.yml's per-module demand, as the run priced against it: how many
    # of each class a formation puts on the pitch. `role_demand` is this
    # aggregated across the league's modules; this is the breakdown.
    module_demand: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def me(self) -> Ledger:
        return self.ledgers[self.mine]

    @property
    def market_credits(self) -> int:
        return self.pool_state.market_credits

    def price_of(self, player_id: int) -> PlayerPrice | None:
        return self.pricing.prices.get(player_id)

    def tiers(self, n: int = 5) -> dict[str, list[dict[str, Any]]]:
        """The printed tier board: per class, the unsold top n by max price."""
        out: dict[str, list[dict[str, Any]]] = {}
        for cls in ROLE_CLASSES:
            rows = [self.players[pid] for pid in self.pricing.prices if self.players[pid].role_class == cls]
            rows.sort(key=lambda p: (-self.pricing.prices[p.player_id].band.p50, *rank_key(p)))
            if rows:
                out[cls] = [self._row(p) for p in rows[:n]]
        return out

    def my_coverage(self) -> dict[str, int]:
        """Per class, how many of my players hold that role at all."""
        out: dict[str, int] = {cls: 0 for cls in self.pool_state.weights}
        for pick in self.me.picks:
            player = self.players.get(pick.player_id)
            for role in (getattr(player, "roles", ()) if player else ()):
                if role in out:
                    out[role] += 1
        return out

    def _row(self, p: Any) -> dict[str, Any]:
        price = self.pricing.prices[p.player_id]
        row = {"player_id": p.player_id, "name": p.name, "team_short": p.team_short, "role_class": p.role_class,
               "roles": list(p.roles), "tier": p.tier, "band": price.band.to_dict(), "expected_price": price.expected_price,
               "value_p50": p.value_p50, "fvm": p.fvm, "apps": p.apps}
        if p.player_id in self.pressure:
            row["pressure"] = self.pressure[p.player_id].to_dict()
        return row

    def to_dict(self) -> dict[str, Any]:
        return json_safe({
            "run_id": self.run_id, "scenario": self.scenario, "settings": self.settings.to_dict(),
            "league_conflicts": list(self.league_conflicts), "problems": list(self.problems),
            "status": self.state.status, "locked": self.state.locked, "picks": len(self.state.picks),
            "me": self.me.to_dict(self.settings),
            "teams": [ledger.to_dict(self.settings) for _, ledger in sorted(self.ledgers.items())],
            "modules": list(self.league_modules),
            "module_demand": {m: dict(by) for m, by in self.module_demand.items()},
            # My squad with its role *sets* -- what a lineup draws from. The
            # price rows only carry the unsold, and a ledger only carries ids.
            "my_squad": [{"player_id": p.player_id, "name": p.name, "team_short": p.team_short,
                          "roles": list(p.roles), "role_class": p.role_class}
                         for p in (self.players.get(k.player_id) for k in self.me.picks) if p is not None],
            # What the league's formations ask of each class, rank by rank (the
            # k-th player of a class starts in this share of them), and how many
            # players I own who can *field* in it -- by role set, not by the one
            # class the pricer pinned them to. The two together are the question
            # "do I still need one of these?", which the composition alone
            # cannot answer for a multi-role squad.
            "role_demand": {cls: list(w) for cls, w in self.pool_state.weights.items()},
            "my_coverage": self.my_coverage(),
            "market_credits": self.market_credits, "inflation": self.pricing.inflation,
            "composition": self.pricing.composition, "credits_by_class": self.pricing.credits_by_class,
            "reserve": self.pricing.reserve, "budget": self.pricing.budget, "slot_price": self.pricing.slot_price,
            "targets_departed": list(self.pricing.targets_departed), "completion_value": self.pricing.completion_value,
            "selected": self.selected, "lot": None if self.lot is None else self.lot.to_dict(),
            "lot_pressure": self.pressure[self.selected].to_dict() if self.selected in self.pressure else None,
            "adjustments": self.layer.to_dict(),
            "prices": {str(pid): self._row(self.players[pid]) for pid in sorted(self.pricing.prices)}})


def build_ledgers(state: AuctionState, settings: SessionSettings, run: PinnedRun,
                  mapping: TeamMapping) -> tuple[dict[int, Ledger], list[str]]:
    """One ledger per team the session shows -- or, with no session, one per
    league team -- credits derived from the picks alone.

    The ledger is where a budget meets a spend, so it is where the feed's
    faults become visible: a pick the run cannot name, a player the feed
    listed twice, a team past its budget. Credits are allowed to go
    negative (the mirror is faithful: whatever the admin recorded is what
    the board shows) but a negative balance buys nothing, so the market's
    credits floor each team at zero."""
    ids = set(state.team_ids())
    if not ids:
        ids = set(range(settings.team_count))
    problems: list[str] = []
    if mapping.mine not in ids:
        problems.append(f"my team {mapping.mine} is not in the session, which has teams {sorted(ids)}")
        ids.add(mapping.mine)
    labels = {t.team_id: t.label for t in state.teams}
    ledgers: dict[int, Ledger] = {}
    for team_id in sorted(ids):
        picks = state.picks_of(team_id)
        gk = mov = unknown = 0
        for pick in picks:
            player = run.players.get(pick.player_id)
            if player is None:
                unknown += 1
                problems.append(f"{labels.get(team_id, f'team {team_id}')} bought player {pick.player_id} for {pick.cost}, "
                                f"which run {run.run_id} does not have: his credits count, his roles do not -- "
                                f"check the listone the run was priced on")
            elif player.is_goalkeeper:
                gk += 1
            else:
                mov += 1
        spent = sum(p.cost for p in picks)
        if spent > settings.budget:
            problems.append(f"{labels.get(team_id, f'team {team_id}')} spent {spent} of {settings.budget} credits")
        ledgers[team_id] = Ledger(team_id, labels.get(team_id, f"team {team_id}"), mapping.nicks.get(team_id),
                                  settings.budget, spent, picks, gk, mov, unknown)
    for player_id in state.duplicates:
        named = run.players.get(player_id)
        owner = state.picks[player_id]
        problems.append(f"the feed lists {named.name if named else 'player'} ({player_id}) twice in one snapshot; "
                        f"the later pick stands -- {labels.get(owner.team_id, f'team {owner.team_id}')} for {owner.cost}")
    return ledgers, problems


def build_pool_state(state: AuctionState, settings: SessionSettings, run: PinnedRun, layer: AdjustmentLayer,
                     ledgers: dict[int, Ledger], mine: int, scenario_name: str | None = None) -> PoolState:
    """My side of the board: the unsold pool with the layer's value factors
    applied, what I already own, what I have refused to buy, and the bounds
    the session (not the working tree) says the roster has to satisfy.

    class_min / class_max carry the league's goalkeeper bounds -- nothing
    hardcodes them, and the floor also extends the rank weights, because a
    session that fills three keepers gives Por a floor above the two ranks
    the module demand gives it and the DP would otherwise have no legal
    completion at all."""
    scenario = run.scenario(scenario_name)
    sold = set(state.picks)
    pool = apply_layer(tuple(p.pool_player() for pid, p in sorted(run.players.items()) if pid not in sold), layer)
    me = ledgers[mine]
    owned = tuple(OwnedPlayer(p.player_id, run.players[p.player_id].role_class,
                              run.players[p.player_id].value_p50 * layer.factor(p.player_id),
                              tuple(run.players[p.player_id].roles))
                  for p in me.picks if p.player_id in run.players)
    targets = {**scenario.target_composition, **layer.targets}
    class_min = {"Por": settings.goalkeepers[0]}
    return PoolState(credits=max(0, me.credits), market_credits=sum(max(0, ledger.credits) for ledger in ledgers.values()),
                     pool=pool, weights=run.weights(targets, class_min), hard_minimums=run.hard_minimums, owned=owned,
                     excluded=frozenset(pid for pid in layer.excluded if pid not in sold),
                     roster_min=settings.size[0], roster_max=settings.size[1], class_min=class_min,
                     class_max={"Por": settings.goalkeepers[1]}, targets=targets,
                     class_budget_share=scenario.max_budget_share_per_role)


def derive(state: AuctionState, *, run: PinnedRun, settings: SessionSettings, layer: AdjustmentLayer = EMPTY_LAYER,
           mapping: TeamMapping, scenario: str | None = None,
           participants: dict[str, Participant] | None = None) -> Board:
    scenario_obj = run.scenario(scenario)
    ledgers, problems = build_ledgers(state, settings, run, mapping)
    pool_state = build_pool_state(state, settings, run, layer, ledgers, mapping.mine, scenario_obj.name)
    pricing = price_board(pool_state, run.pricing_cfg)
    if pricing.completion_value == NEG:
        problems.append("no completion of my roster is legal under these bounds: the board's prices are zero -- "
                        f"the session fills {settings.goalkeepers[0]}-{settings.goalkeepers[1]} goalkeepers and "
                        f"{settings.size[0]}-{settings.size[1]} players, the pricing caps goalkeepers at "
                        f"{run.pricing_cfg.max_goalkeepers} (pricing.yml max_goalkeepers)")
    lot = None
    if state.selected is not None:
        player = run.players.get(state.selected)
        if player is None:
            problems.append(f"the lot on the block, player {state.selected}, is not in run {run.run_id}")
        else:
            price = pricing.prices.get(state.selected)
            pick = state.picks.get(state.selected)
            lot = Lot(player.player_id, player.name, player.team_short, player.role_class, player.roles, player.tier,
                      None if price is None else price.band, None if price is None else price.expected_price,
                      None if pick is None else pick.team_id, player.fvm, player.apps)
    problems.extend(layer.problems)
    conflicts = tuple(compare(settings, run.league)) if settings.source == "session" else ()
    if run.superseded:
        problems.append(f"run {run.run_id} is superseded by a rules change; it was pinned by id")
    board = Board(run.run_id, scenario_obj.name, state, settings, conflicts, ledgers, mapping.mine, pool_state, pricing,
                  state.selected, lot, layer, tuple(problems), players=run.players, club_names=run.club_names,
                  league_modules=tuple(getattr(run.league, "modules", ()) or ()),
                  module_demand={m: dict(by) for m, by in (run.demand or {}).items()})
    if participants is not None:
        # advisor -> pressure -> advisor (pressure.py imports Board and Ledger from
        # here), so the import has to live inside the function, not at module scope.
        from fantaclaude.asta.pressure import pressure_board

        board = pressure_board(board, participants)
    return board
