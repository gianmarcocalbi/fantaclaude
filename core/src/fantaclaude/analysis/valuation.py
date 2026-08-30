"""A valuation run: every listone player projected, pinned to a role class,
priced against the best completion of the roster, and stamped.

Two hashes, because there are two ways a run goes stale (spec, "Schema"):
rules_hash is the league_settings row in force; model_hash covers the
projection and pricing configuration, preferences.yml and the D-Factor
table -- what moved after I changed the minutes projection? -- and
inputs_hash covers the data and the knowledge base the run read, so a run
is reproducible from what it names. The permanent record is the run_id
(spec, "fanta-market"): the exports are renderings of these rows.

The stages, in the spec's order: project (Task 6), Mantra-adjust (the
flexibility bonus in the projection and the role pinning here), value
above replacement (against the best player expected to cost one credit at
the class), allocate (price_board with exact=True, once per scenario --
the composition is the DP's), tier (the largest gaps in value within the
class). The quotazione enters only as the expected price and, at the end,
as the divergence check: where we disagree most with the market is either
the edge or a bug, and it is the list worth reading by hand.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.history import History, load_history
from fantaclaude.analysis.projection import (
    PlayerInputs,
    Projection,
    ProjectionConfig,
    project_all,
)
from fantaclaude.asta.pricing import (
    BoardPricing,
    PoolPlayer,
    PoolState,
    PricingConfig,
    price_board,
)
from fantaclaude.ingest.names import (
    Candidate,
    Match,
    match_listone,
    unresolved_detail,
)
from fantaclaude.kb.notes import (
    NoteError,
    PlayerNote,
    load_player_notes,
    misdeclared_team_notes,
    orphan_notes,
)
from fantaclaude.kb.profiles import ProfileError, TeamProfile, load_profiles
from fantaclaude.league.settings import canonical_json
from fantaclaude.model.d_factor import DFactorTable
from fantaclaude.model.demand import (
    ROLE_CLASSES,
    hard_minimums,
    module_demand,
    pin_class,
    rank_weights,
)
from fantaclaude.model.roles import Role
from fantaclaude.model.scoring import (
    BonusMalus,
    ScoringError,
    modifier_status,
    voto_sheet,
)
from fantaclaude.model.seasons import SERIE_A_GIORNATE
from fantaclaude.timeutil import to_db
from fantaclaude.values import is_number

MODEL_VERSION = "1"
RISK_APPETITES = ("cautious", "balanced", "aggressive")
QUANTILE_OF = {"cautious": "p25", "balanced": "p50", "aggressive": "p75"}


class PreferencesError(ValueError):
    """preferences.yml is malformed -- a defect in a config file (exit 3)."""


class UnknownScenarioError(ValueError):
    """`--scenario` names a scenario preferences.yml does not define.

    Deliberately *not* a PreferencesError (finding 17): the file is fine, the
    argument is wrong. While the two shared a class the whole class had to
    pick one exit code, and it picked 2 -- so a malformed *value* in
    preferences.yml exited 2 ("bad arguments") while a malformed pricing.yml,
    or a preferences.yml that would not even parse, exited 3. The codes now
    split on the defect: a bad argument is 2, a malformed config file is 3."""


class ValuationError(RuntimeError):
    """The run cannot be made honestly: a rule this code does not model is active, or an input is missing."""


@dataclass(frozen=True)
class Scenario:
    name: str
    target_composition: dict[str, int]
    risk_appetite: str
    max_budget_share_per_role: dict[str, float]

    @property
    def quantile(self) -> str:
        return QUANTILE_OF[self.risk_appetite]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "target_composition": self.target_composition,
                "risk_appetite": self.risk_appetite, "max_budget_share_per_role": self.max_budget_share_per_role}


def _composition(value: Any, where: str) -> dict[str, int]:
    value = value or {}
    # Not is_number: a composition is a count of players, so 2.5 is a mistake
    # to name, not a number to round. int also excludes NaN for free.
    if not isinstance(value, dict) or any(k not in ROLE_CLASSES or isinstance(v, bool) or not isinstance(v, int) or v < 0
                                          for k, v in value.items()):
        raise PreferencesError(f"{where}: target_composition maps role classes ({ROLE_CLASSES}) to counts, got {value!r}")
    return dict(value)


def _shares(value: Any, where: str) -> dict[str, float]:
    value = value or {}
    if not isinstance(value, dict) or any(k not in ROLE_CLASSES or not is_number(v) or not 0 < float(v) <= 1
                                          for k, v in value.items()):
        raise PreferencesError(f"{where}: max_budget_share_per_role maps role classes to shares in (0, 1], got {value!r}")
    return {k: float(v) for k, v in value.items()}


def _risk(value: Any, where: str) -> str:
    if value not in RISK_APPETITES:
        raise PreferencesError(f"{where}: risk_appetite must be one of {RISK_APPETITES}, got {value!r}")
    return value


def load_scenarios(preferences: dict[str, Any]) -> list[Scenario]:
    base = Scenario("balanced", _composition(preferences.get("target_composition"), "preferences.yml"),
                    _risk(preferences.get("risk_appetite", "balanced"), "preferences.yml"),
                    _shares(preferences.get("max_budget_share_per_role"), "preferences.yml"))
    scenarios = [base]
    raw = preferences.get("scenarios") or {}
    if not isinstance(raw, dict):
        raise PreferencesError("preferences.yml: scenarios must be a mapping of name -> overrides")
    for name, over in raw.items():
        if name == base.name:
            # Skipping it was the one silent failure in a file that otherwise
            # refuses everything malformed: the override never applied, but it
            # still entered config and model_hash, and the asta plan still said
            # "bid to p50" under a heading the operator had just told to be
            # cautious (finding 9). Refusing keeps one place to say what
            # balanced is, rather than two with an invisible precedence rule.
            raise PreferencesError(f"preferences.yml: scenarios.{base.name} collides with the base scenario, which "
                                   f"*is* the file's top-level target_composition / risk_appetite / "
                                   f"max_budget_share_per_role -- set those, or give this scenario another name")
        if not isinstance(over, dict):
            raise PreferencesError(f"preferences.yml: scenario {name!r} must be a mapping of overrides")
        where = f"preferences.yml: scenarios.{name}"
        scenarios.append(Scenario(str(name), {**base.target_composition, **_composition(over.get("target_composition"), where)},
                                  _risk(over.get("risk_appetite", base.risk_appetite), where),
                                  {**base.max_budget_share_per_role, **_shares(over.get("max_budget_share_per_role"), where)}))
    return scenarios


def load_preferences(preferences: dict[str, Any]) -> list[Scenario]:
    """Everything preferences.yml has to satisfy before `rank` will run: the
    keys Phase 1 refuses outright, then the scenarios themselves.

    One entry point so `doctor` predicts `rank` instead of approximating it
    (finding 4). Doctor's own reading of the file -- parse it, require a
    `target_composition` key -- disagreed in both directions: `excluded_clubs`,
    a bad `risk_appetite` and a scenario naming an unknown role class all
    passed doctor and then made `rank` exit 2, *after* the live re-sync doctor
    exists to gate had been spent; and a file with no `target_composition`
    failed doctor while ranking perfectly well, since an empty composition is
    a legitimate "no targets"."""
    # excluded_clubs is hashed into model_hash with the rest of preferences, so a
    # non-empty list would mint a new model_hash, a new run_id and an immutable run
    # incomparable to every earlier one -- while still pricing every player of those
    # clubs, because dropping them from the pool is price_board's `excluded`, which
    # would leave board.prices no longer covering every projection. Refusing is the
    # honest answer until Phase 2 wires it through the exports too.
    excluded = preferences.get("excluded_clubs") or []
    if excluded:
        raise PreferencesError(f"preferences.yml: excluded_clubs {list(excluded)} is not honoured in Phase 1 -- it would "
                               f"change model_hash without changing a single price. Leave it empty; club exclusion lands "
                               f"with the live pool in Phase 2")
    return load_scenarios(preferences)


def _digest(view: Any) -> str:
    return hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()[:16]


def _finite(value: Any) -> Any:
    """-inf / inf / nan are not JSON, and DuckDB's JSON column refuses them:
    stored as null in the JSON payloads (the DOUBLE columns keep the real value)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def model_hash(projection_cfg: ProjectionConfig, pricing_cfg: PricingConfig, preferences: dict[str, Any],
               d_factor: DFactorTable) -> str:
    return _digest({"model_version": MODEL_VERSION, "projection": projection_cfg.to_dict(),
                    "pricing": pricing_cfg.to_dict(), "preferences": preferences, "d_factor": d_factor.to_dict()})


def inputs_hash(con: duckdb.DuckDBPyConnection, *, profiles: list[TeamProfile], notes: dict[int, PlayerNote]) -> str:
    """Content, never a sequence id (finding 6). A snapshot_id is a DuckDB
    sequence value: `data/` is gitignored and documented as rebuildable from
    `data/raw/`, so the rebuild mints fresh ids for byte-identical raw files
    and a hash keyed on them names a run nobody can reproduce -- including the
    operator who committed it to records/. Every entry below is a sha256 the
    ingest already stored, or a rules_hash, or the derivation itself. Ids are
    still used to *select* the current snapshot; they are just not hashed.

    advanced needs both its digests and its derivation, because
    `ingest advanced --rematch` re-derives a snapshot in place: the row's
    UNIQUE key is (sha256, aliases_sha256, listone_snapshot_id), so an
    identical key is precisely what a rematch keeps while it rewrites which
    listone player each Understat row belongs to. Only the ids are hashed, not
    the stats: the DOUBLE columns are already fixed by sha256, and summing
    them here would put a parallel float reduction inside a digest that has to
    be byte-stable. Only matched rows, because only those are read."""
    listone = con.execute("SELECT sha256 FROM listone_snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    voti = con.execute("SELECT season_id, giornata, sha256 FROM v_voti_files_current ORDER BY 1, 2").fetchall()
    advanced = con.execute("SELECT a.season_id, a.sha256, a.aliases_sha256, l.sha256 FROM advanced_snapshots a "
                           "LEFT JOIN listone_snapshots l ON l.snapshot_id = a.listone_snapshot_id "
                           "WHERE a.snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id) "
                           "ORDER BY 1").fetchall()
    matches = con.execute("SELECT season_id, source_id, player_id FROM v_advanced_current "
                          "WHERE player_id IS NOT NULL ORDER BY 1, 2").fetchall()
    fixtures = con.execute("SELECT competition, season_id, sha256 FROM fixture_snapshots WHERE snapshot_id IN "
                           "(SELECT max(snapshot_id) FROM fixture_snapshots GROUP BY competition, season_id) "
                           "ORDER BY 1, 2").fetchall()
    # rules_hash covers the three payloads and the team count, and budget and
    # the roster bounds are derived from them -- but not season_id, which is a
    # settings column of its own and is a real season number, not a sequence.
    settings = con.execute("SELECT season_id, rules_hash FROM v_league_settings_current").fetchone()
    # team_short is the *only* key build_inputs joins a profile to its players
    # on, so it belongs here above all the rest: a typo there (INT -> INR)
    # unjoins a whole club -- its rotation factor and its penalty taker both
    # stop applying -- and without it in the payload the two runs are stamped
    # byte-identically while disagreeing about real prices (finding 5).
    # coach/module/europe are hashed although no numeric path reads them (only
    # doctor's fixtures cross-check reads europe). Kept deliberately: they are
    # the human judgement rotation_factor and takers are *derived from*, and
    # over-stamping only makes a run look new when nothing moved, while
    # under-stamping makes two different runs look like one.
    kb = {"profiles": [{"team": p.team, "team_short": p.team_short, "coach": p.coach, "module": p.module,
                        "europe": p.europe, "rotation_factor": p.rotation_factor, "takers": p.takers} for p in profiles],
          "notes": [notes[k].to_dict() for k in sorted(notes)]}
    return _digest({"listone": list(listone) if listone else None, "voti": [list(r) for r in voti],
                    "advanced": [list(r) for r in advanced], "advanced_matches": [list(r) for r in matches],
                    "fixtures": [list(r) for r in fixtures],
                    "settings": list(settings) if settings else None, "kb": kb})


@dataclass(frozen=True)
class RunContext:
    settings_snapshot_id: int
    rules_hash: str
    season_id: int
    team_count: int
    budget: int
    roster_min: int
    roster_max: int
    min_goalkeepers: int
    max_goalkeepers: int
    calculate: dict[str, Any]
    listone_snapshot_id: int


def load_context(con: duckdb.DuckDBPyConnection) -> RunContext:
    row = con.execute("SELECT snapshot_id, rules_hash, season_id, team_count, budget, roster_min, roster_max, payload "
                      "FROM v_league_settings_current").fetchone()
    if row is None:
        raise ValuationError("no league_settings snapshot -- run `fantaclaude sync-league` first")
    payload = row[7] if isinstance(row[7], dict) else json.loads(row[7])
    listone = con.execute("SELECT max(snapshot_id) FROM listone_snapshots").fetchone()[0]
    if listone is None:
        raise ValuationError("no listone snapshot -- run `fantaclaude ingest listone` first")
    missing = [name for name, value in (("season_id", row[2]), ("team_count", row[3]), ("budget", row[4]),
                                        ("roster_min", row[5]), ("roster_max", row[6])) if value is None]
    if missing:
        raise ValuationError(f"league_settings lacks {missing}; the money supply and the bounds are not known")
    rosters = payload.get("rosters") or {}
    minrl, maxrl = rosters.get("minrl") or [None, None], rosters.get("maxrl") or [None, None]
    if minrl[0] is None or maxrl[0] is None:
        raise ValuationError("league_settings.rosters lacks minrl/maxrl; the goalkeeper bounds are not known")
    return RunContext(int(row[0]), str(row[1]), int(row[2]), int(row[3]), int(row[4]), int(row[5]), int(row[6]),
                      int(minrl[0]), int(maxrl[0]), payload.get("calculate") or {}, int(listone))


def _taker_warning(profile: TeamProfile, name: str, match: Match, candidates: list[Candidate]) -> str:
    """The run's own wording around the shared diagnosis: what happens to this
    run (the club's own history stands) is `rank`'s to say, while *why* the
    name did not resolve is the same fact `doctor` reports."""
    return f"{profile.team}: penalty taker {name!r} {unresolved_detail(profile.team, match, candidates)}; history stands"


def _resolve_taker(profile: TeamProfile, candidates: list[Candidate]) -> Match:
    """The profile writes the taker the listone's way, so he is matched that
    way: Matcher is for the sources that write the given name first, and it
    reads the trailing initial of "Adams A." as the surname."""
    return match_listone(profile.takers.get("penalties") or "", candidates)


def build_inputs(con: duckdb.DuckDBPyConnection, history: History, profiles: list[TeamProfile],
                 notes: dict[int, PlayerNote], weights: dict[str, tuple[float, ...]]) -> tuple[list[PlayerInputs], list[str]]:
    rows = con.execute("SELECT player_id, name, team_name, team_short, classic_role, mantra_roles, quot_current_mantra, age "
                       "FROM v_players_current ORDER BY player_id").fetchall()
    by_short = {p.team_short: p for p in profiles}
    club_players: dict[str, list[Candidate]] = {}
    for player_id, name, team_name, team_short, *_ in rows:
        club_players.setdefault(team_short, []).append(Candidate(int(player_id), str(name), str(team_short), str(team_name)))
    warnings: list[str] = []
    takers: dict[str, int | None] = {}
    for short, candidates in sorted(club_players.items()):
        profile = by_short.get(short)
        if profile is None:
            warnings.append(f"no profile for {candidates[0].team_name} ({short}): rotation_factor 1.0 assumed")
            takers[short] = None
            continue
        name = profile.takers.get("penalties")
        match = _resolve_taker(profile, candidates)
        if name and match.player_id is None:
            warnings.append(_taker_warning(profile, name, match, candidates))
        takers[short] = match.player_id
        team_name = candidates[0].team_name
        if match.player_id is not None and team_name not in history.penalty_rate_clubs:
            # The club penalty rate is keyed by the voti workbook's own club
            # string and looked up by the listone's team_name: two free-text
            # sources, no id, no alias table on the voti side. A promoted club,
            # a rename or "Hellas Verona" against "Verona" all miss. The
            # projection no longer redistributes on a rate it never observed
            # (finding A), so the taker is not punished for the miss -- but the
            # profile's statement about who takes the penalties still has no
            # effect, and a rename or a spelling difference is a fixable join,
            # not a fact about the club, so it is still named. Only warned when
            # a taker actually resolved: that is the only case where the rate
            # is read (finding 12). A club the workbook does name but that took
            # no penalty is a real 0.0, so it is in penalty_rate_clubs and
            # stays quiet.
            warnings.append(f"{profile.team}: the voti history never names {team_name!r} (promoted, renamed, or "
                            f"spelled differently there), so it has no observed penalty rate; penalty taker "
                            f"{name!r} therefore changes nothing and every {team_name} player keeps the penalties "
                            f"his own history records. Fix the spelling if the club is only spelled differently")
    inputs: list[PlayerInputs] = []
    for player_id, name, team_name, team_short, classic_role, mantra_roles, quot, age in rows:
        roles = frozenset(Role(r) for r in mantra_roles)
        profile = by_short.get(team_short)
        taker = takers.get(team_short)
        inputs.append(PlayerInputs(
            player_id=int(player_id), name=str(name), team_short=str(team_short), team_name=str(team_name),
            classic_role=str(classic_role), roles=roles, role_class=pin_class(roles, weights),
            quotazione=int(quot or 0), age=None if age is None else int(age), lines=history.lines_for(int(player_id)),
            rotation_factor=profile.rotation_factor if profile else 1.0, note=notes.get(int(player_id)),
            penalty_taker=taker == int(player_id), club_has_taker=taker is not None,
            club_penalty_rate=history.penalty_rate(str(team_name))))
    names_of = {int(pid): str(team_name) for pid, _, team_name, *_ in rows}
    shorts_of = {int(pid): str(team_short) for pid, _, _, team_short, *_ in rows}
    for note in orphan_notes(notes, names_of):
        # notes.get(player_id) never finds this one, so it changes nothing --
        # but it is in inputs_hash, so the run looks new when nothing applied.
        warnings.append(f"note {note.name!r} ({note.path}): player_id {note.player_id} is not in the listone; "
                        f"the note has no effect")
    for note, short in misdeclared_team_notes(notes, shorts_of):
        warnings.append(f"note {note.name!r} ({note.path}): team_short {note.team_short!r}, but the listone has "
                        f"him at {short!r}")
    return inputs, warnings


def build_pool(projections: list[Projection]) -> tuple[PoolPlayer, ...]:
    return tuple(PoolPlayer(p.player_id, p.name, p.role_class, p.value_p25, p.value_p50, p.value_p75, p.quotazione)
                 for p in projections)


def replacement_levels(pool: tuple[PoolPlayer, ...], expected_prices: dict[int, int],
                       cfg: PricingConfig) -> dict[str, float]:
    """Per class, the value of the best player expected to cost the replacement price (one credit);
    the class's weakest player when nobody is that cheap."""
    levels: dict[str, float] = {}
    for cls in {p.role_class for p in pool}:
        players = [p for p in pool if p.role_class == cls]
        cheap = [p.value_p50 for p in players if expected_prices.get(p.player_id, 1) <= cfg.replacement_price]
        levels[cls] = max(cheap) if cheap else min(p.value_p50 for p in players)
    return levels


def assign_tiers(pool: tuple[PoolPlayer, ...], cfg: PricingConfig) -> dict[int, int]:
    tiers: dict[int, int] = {}
    for cls in {p.role_class for p in pool}:
        ranked = sorted((p for p in pool if p.role_class == cls), key=lambda p: (-p.value_p50, p.player_id))
        top, rest = ranked[:cfg.tier_pool], ranked[cfg.tier_pool:]
        gaps = sorted(range(1, len(top)), key=lambda i: top[i - 1].value_p50 - top[i].value_p50, reverse=True)
        cuts = set(gaps[:max(0, cfg.tiers_per_class - 1)])
        tier = 1
        for i, p in enumerate(top):
            if i in cuts:
                tier += 1
            tiers[p.player_id] = tier
        for p in rest:
            tiers[p.player_id] = tier + 1
    return tiers


def divergence(pool: tuple[PoolPlayer, ...]) -> dict[int, tuple[float, float]]:
    """(the value implied by the quotazione, our value minus it): the player at
    quotazione rank i is implied to be worth what our i-th best is worth."""
    out: dict[int, tuple[float, float]] = {}
    for cls in {p.role_class for p in pool}:
        players = [p for p in pool if p.role_class == cls]
        by_quot = sorted(players, key=lambda p: (-p.quotazione, -p.value_p50, p.player_id))
        by_value = sorted(players, key=lambda p: (-p.value_p50, p.player_id))
        for market, ours in zip(by_quot, by_value):
            out[market.player_id] = (ours.value_p50, market.value_p50 - ours.value_p50)
    return out


def new_run_id(now: datetime, rules_hash: str, model_hash_: str) -> str:
    return f"{now:%Y%m%dT%H%M%SZ}-{model_hash_[:4]}{rules_hash[:4]}"


@dataclass(frozen=True)
class ValuationRun:
    run_id: str
    created_at: datetime
    rules_hash: str
    model_hash: str
    inputs_hash: str
    settings_snapshot_id: int
    listone_snapshot_id: int
    season_id: int
    giornata: int
    scenarios: list[Scenario]
    config: dict[str, Any]
    projections: list[Projection]
    pool: tuple[PoolPlayer, ...]
    replacement: dict[str, float]
    vor: dict[int, float]
    tiers: dict[int, int]
    implied: dict[int, tuple[float, float]]
    boards: dict[str, BoardPricing]
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def run_valuation(con: duckdb.DuckDBPyConnection, *, now: datetime, kb_dir: Path, preferences: dict[str, Any],
                  projection_cfg: ProjectionConfig, pricing_cfg: PricingConfig, d_factor: DFactorTable,
                  scenario_names: list[str] | None = None) -> ValuationRun:
    ctx = load_context(con)
    status = modifier_status(ctx.calculate)
    if status.unknown_active:
        raise ValuationError(f"modifier(s) {list(status.unknown_active)} are active in league_settings and this code does "
                             f"not model them -- see the Phase 1 plan, Task 10")
    if status.d_factor and d_factor.is_empty:
        raise ValuationError("the D-Factor is active (calculate.smodd) but core/src/fantaclaude/model/d_factor.yml has no "
                             "bands -- transcribe the league's table first (Phase 1 plan, Task 10)")
    # ScoringError, NoteError and ProfileError are all ValueError subclasses (the
    # loaders' own convention), but a bare ValueError elsewhere in this function --
    # price_board's for an ordinary modelling error -- must not become exit 3. Only
    # these four calls are wrapped, by name, never a blanket `except ValueError`.
    try:
        bm = BonusMalus.from_calculate(ctx.calculate)
        sheet = voto_sheet(ctx.calculate)
    except ScoringError as exc:
        raise ValuationError(str(exc)) from exc
    scenarios = load_preferences(preferences)
    if scenario_names:
        unknown = sorted(set(scenario_names) - {s.name for s in scenarios})
        if unknown:
            raise UnknownScenarioError(
                f"unknown scenario(s) {unknown}; preferences.yml defines {[s.name for s in scenarios]}")
        scenarios = [s for s in scenarios if s.name in scenario_names]
    history = load_history(con, sheet=sheet, bm=bm, current_season=ctx.season_id)
    if not history.lines:
        raise ValuationError("no voti history at all -- run `fantaclaude ingest stats-web` first")
    giornate_remaining = max(0, SERIE_A_GIORNATE - history.giornate_played)
    try:
        profiles, notes = load_profiles(kb_dir), load_player_notes(kb_dir)
    except (ProfileError, NoteError) as exc:
        raise ValuationError(str(exc)) from exc
    demand = module_demand()
    max_rank = max(pricing_cfg.max_per_class, pricing_cfg.max_goalkeepers)
    base_weights = rank_weights(demand, max_rank=max_rank, bench_weight=pricing_cfg.bench_weight,
                                bench_decay=pricing_cfg.bench_decay, bench_slots=pricing_cfg.bench_slots_per_class)
    inputs, warnings = build_inputs(con, history, profiles, notes, base_weights)
    table = d_factor if status.d_factor else None
    projections = project_all(inputs, cfg=projection_cfg, priors=history.priors, bm=bm,
                              giornate_remaining=giornate_remaining, current_season=ctx.season_id, d_factor=table)
    pool = build_pool(projections)
    minimums = hard_minimums()
    boards: dict[str, BoardPricing] = {}
    for scenario in scenarios:
        weights = rank_weights(demand, max_rank=max_rank, bench_weight=pricing_cfg.bench_weight,
                               bench_decay=pricing_cfg.bench_decay, bench_slots=pricing_cfg.bench_slots_per_class,
                               targets=scenario.target_composition, target_weight=pricing_cfg.target_weight)
        state = PoolState(credits=ctx.budget, market_credits=ctx.team_count * ctx.budget, pool=pool, weights=weights,
                          hard_minimums=minimums, roster_min=ctx.roster_min, roster_max=ctx.roster_max,
                          min_goalkeepers=ctx.min_goalkeepers, max_goalkeepers=ctx.max_goalkeepers,
                          targets=scenario.target_composition, class_budget_share=scenario.max_budget_share_per_role)
        boards[scenario.name] = price_board(state, pricing_cfg, exact=True)
    reference = boards[scenarios[0].name]
    replacement = replacement_levels(pool, reference.expected_prices, pricing_cfg)
    vor = {p.player_id: max(0.0, p.value_p50 - replacement[p.role_class]) for p in pool}
    hashes = (model_hash(projection_cfg, pricing_cfg, preferences, d_factor), inputs_hash(con, profiles=profiles, notes=notes))
    # The scenarios actually run, beside the preferences that define them all: a
    # filtered run priced one board, and its immutable config must say so rather than
    # let preferences.scenarios imply three. It is deliberately not in model_hash --
    # the model is the same, so a filtered run stays comparable to a full one.
    config = {"projection": projection_cfg.to_dict(), "pricing": pricing_cfg.to_dict(), "preferences": preferences,
              "scenarios": [s.name for s in scenarios], "d_factor": d_factor.to_dict(),
              "model_version": MODEL_VERSION, "sheet": sheet, "bonus_malus": bm.to_dict(),
              "modifiers": status.to_dict()}
    summary = {"players": len(pool), "team_count": ctx.team_count, "budget": ctx.budget,
               "market_credits": ctx.team_count * ctx.budget, "giornate_played": history.giornate_played,
               "giornate_remaining": giornate_remaining, "sheet": sheet, "d_factor_active": status.d_factor,
               "scenarios": {name: {"inflation": b.inflation, "composition": b.composition,
                                    "credits_by_class": b.credits_by_class, "reserve": b.reserve,
                                    "targets_departed": list(b.targets_departed)} for name, b in boards.items()},
               "warnings": warnings}
    run_id = base = new_run_id(now, ctx.rules_hash, hashes[0])
    taken = {r[0] for r in con.execute("SELECT run_id FROM valuation_runs WHERE run_id LIKE ?", [base + "%"]).fetchall()}
    suffix = 2
    while run_id in taken:                     # the stamp has one-second resolution; two runs in a second are both kept
        run_id = f"{base}-{suffix}"
        suffix += 1
    return ValuationRun(run_id=run_id, created_at=now, rules_hash=ctx.rules_hash,
                        model_hash=hashes[0], inputs_hash=hashes[1], settings_snapshot_id=ctx.settings_snapshot_id,
                        listone_snapshot_id=ctx.listone_snapshot_id, season_id=ctx.season_id,
                        giornata=history.giornate_played, scenarios=scenarios, config=config, projections=projections,
                        pool=pool, replacement=replacement, vor=vor, tiers=assign_tiers(pool, pricing_cfg),
                        implied=divergence(pool), boards=boards, warnings=warnings, summary=summary)


def record_run(con: duckdb.DuckDBPyConnection, run: ValuationRun) -> None:
    """Append the run: runs, one valuation row per player, one price row per scenario and player. Never updates."""
    con.begin()
    try:
        con.execute("INSERT INTO valuation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON)",
                    [run.run_id, to_db(run.created_at), run.rules_hash, run.model_hash, run.inputs_hash,
                     run.settings_snapshot_id, run.listone_snapshot_id, run.season_id, run.giornata,
                     [s.name for s in run.scenarios], canonical_json(_finite(run.config)),
                     canonical_json(_finite(run.summary))])
        con.executemany(
            "INSERT INTO valuations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[run.run_id, p.player_id, p.name, p.team_short, p.classic_role, p.role_class, list(p.roles), p.exp_presenze,
              p.exp_fantamedia, p.exp_voto, p.value_p25, p.value_p50, p.value_p75, run.replacement[p.role_class],
              run.vor[p.player_id], run.tiers[p.player_id], p.quotazione, run.implied[p.player_id][0],
              run.implied[p.player_id][1], canonical_json(_finite(p.explain))] for p in run.projections])
        con.executemany(
            "INSERT INTO valuation_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[run.run_id, name, price.player_id, price.role_class, price.expected_price, price.band.p25, price.band.p50,
              price.band.p75, price.walk_value, price.exact, canonical_json(_finite(price.to_dict()))]
             for name, board in run.boards.items() for price in board.prices.values()])
    except Exception:
        con.rollback()
        raise
    con.commit()
