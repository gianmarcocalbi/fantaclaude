"""fantaclaude rank: write a valuation run, render the exports, copy the records.

Importable on purpose -- the CLI and, later, the FastAPI server call this
function; the CLI adds only the re-sync, argument parsing and rendering.
Every run before the freeze is provisional (spec, open question 1): the
report says so, from league.yml's auction date.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fantaclaude.analysis.exports import export_records, write_asta_plan, write_rankings
from fantaclaude.analysis.ordering import by_class, rank_key
from fantaclaude.analysis.projection import ProjectionConfig
from fantaclaude.analysis.valuation import (
    PreferencesError,
    ValuationError,
    load_preferences,
    record_run,
    run_valuation,
)
from fantaclaude.asta.pricing_config import (
    PricingConfig,
    PricingConfigError,
    load_pricing_config,
)
from fantaclaude.commands.ingest import NotReady
from fantaclaude.commands.sync_league import SyncReport
from fantaclaude.league.league_yml import Provenanced
from fantaclaude.model.d_factor import DFactorTable, DFactorTableError, load_d_factor

# The spec (open question 1) fixes no day count -- only that the run after the
# freeze is the final one. Seven days is this plan's own stated requirement
# (its line-30 prose, not the day count once mis-copied into an earlier draft
# of this module). A run inside the window is still provisional -- the freeze
# is what makes a run final, and this code has no way to observe the freeze
# itself -- so the window only changes the wording, never the "provisional"
# label.
PRE_FREEZE_WINDOW_DAYS = 7


@dataclass(frozen=True)
class FreezeStatus:
    """The facts the provisional note is written from, kept as facts.

    Collapsing them into one English sentence put them out of reach of the
    contract the skills consume (finding 19): a `--json` reader had to regex
    "in 2 days" and "8 of 10 expected teams" back out of prose. The sentence
    is still emitted -- it is the line a human reads -- and these sit beside
    it. `provisional` is a field rather than a derivation because it is a
    statement, not a calendar reading: the freeze is what makes a run final,
    this code cannot observe the freeze, so it is always True."""
    provisional: bool
    note: str
    auction_date: str | None
    days_to_auction: int | None
    auction_passed: bool
    inside_pre_freeze_window: bool
    pre_freeze_window_days: int
    teams_present: int
    teams_expected: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankReport:
    run_id: str
    created_at: datetime
    rules_hash: str
    model_hash: str
    inputs_hash: str
    season_id: int
    giornata: int
    scenarios: list[str]
    players: int
    exports: list[str]
    records: list[str]
    warnings: list[str]
    summary: dict[str, Any]
    provisional: str
    freeze: FreezeStatus | None = None
    top: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # the re-sync that preceded the run, when there was one: a rules change
    # detected here is reported with its diff and the runs it superseded, as
    # sync-league reports it, instead of being absorbed silently
    sync: SyncReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "created_at": self.created_at.isoformat(), "rules_hash": self.rules_hash,
                "model_hash": self.model_hash, "inputs_hash": self.inputs_hash, "season_id": self.season_id,
                "giornata": self.giornata, "scenarios": self.scenarios, "players": self.players,
                "exports": self.exports, "records": self.records, "warnings": self.warnings,
                "summary": self.summary, "provisional": self.provisional,
                "freeze": self.freeze.to_dict() if self.freeze is not None else None, "top": self.top,
                "sync": self.sync.to_dict() if self.sync is not None else None}


def _expected_teams(entries: dict[str, Provenanced] | None) -> int | None:
    """league.yml carries no `team_count` leaf today (a real gap, not this
    code's to silently paper over), so an absent expectation stays None
    rather than being treated as "the league is full"."""
    expected = entries.get("team_count") if entries else None
    value = expected.value if expected is not None else None
    # Not is_number: a team count is a whole number of teams, so 9.5 is a
    # league.yml to fix, not a value to compare against. int also excludes NaN.
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def _team_note(expected: int | None, team_count: int) -> str:
    if expected is None:
        return f"{team_count} teams (league.yml does not say how many are expected)"
    if team_count < expected:
        return f"{team_count} of {expected} expected teams"
    return f"{team_count} teams (of {expected} expected)"


def freeze_status(entries: dict[str, Provenanced] | None, now: datetime, team_count: int) -> FreezeStatus:
    auction = entries.get("auction.date") if entries else None
    when = auction.value if auction is not None and isinstance(auction.value, date) else None
    expected = _expected_teams(entries)
    teams = _team_note(expected, team_count)
    days = None if when is None else (when - now.date()).days
    # The window needs a floor as well as a ceiling (finding 10): without one,
    # a date already gone read as "in -3 days -- inside the pre-freeze window",
    # counting backwards towards an auction that has happened.
    passed = days is not None and days < 0
    inside = days is not None and 0 <= days <= PRE_FREEZE_WINDOW_DAYS
    if when is None or days is None:
        note = f"provisional: {teams}, auction date unknown -- the final run is the one after the freeze"
    elif passed:
        # Still provisional: a pre-auction valuation of an auction that has
        # already happened is not a final anything.
        note = (f"provisional: {teams}, auction {when.isoformat()} was {-days} days ago -- this is a pre-auction "
                f"valuation of an auction that has already happened; check league.yml's auction date")
    elif inside:
        # Still provisional: the freeze, not the calendar, is what makes a run
        # final, and this code cannot observe the freeze -- so the label never
        # changes here, only the note about how close the auction is.
        note = (f"provisional: {teams}, auction {when.isoformat()} in {days} days -- inside the pre-freeze window, "
                f"but still provisional until the freeze actually happens; re-run `fantaclaude rank` after it")
    else:
        note = (f"provisional: {teams}, auction {when.isoformat()} in {days} days -- "
                f"re-run after the freeze, when the rules and the teams have settled")
    return FreezeStatus(provisional=True, note=note,
                        auction_date=None if when is None else when.isoformat(), days_to_auction=days,
                        auction_passed=passed, inside_pre_freeze_window=inside,
                        pre_freeze_window_days=PRE_FREEZE_WINDOW_DAYS,
                        teams_present=team_count, teams_expected=expected)


def provisional_note(entries: dict[str, Provenanced] | None, now: datetime, team_count: int) -> str:
    """The human-readable half of `freeze_status`."""
    return freeze_status(entries, now, team_count).note


def _load_preferences(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise NotReady(f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise NotReady(f"{path} does not parse: {exc}") from None
    if not isinstance(data, dict):
        raise NotReady(f"{path}: the top level must be a mapping")
    return data


def check_ready(preferences_path: Path, pricing_path: Path) -> tuple[dict[str, Any], PricingConfig, DFactorTable]:
    """The three not-ready checks a run needs no database connection for:
    preferences.yml, pricing.yml and d_factor.yml. Call this before opening
    a read-write connection -- connect() creates and schemas the file on
    first touch, so running these after it would leave a phantom database
    behind for the sole crime of a missing preferences.yml on a
    never-synced workspace (finding 2): `doctor` would then report "ok,
    schema version 3" instead of "no database -- run sync-league".

    preferences.yml is validated here to the same depth `rank` needs it
    (finding 17), not merely parsed: a malformed *value* is a defect in a
    hashed config file exactly as a malformed pricing.yml is, so it is
    not-ready (exit 3), and it is worth refusing before the live re-sync
    rather than after it."""
    preferences = _load_preferences(preferences_path)
    try:
        load_preferences(preferences)
    except PreferencesError as exc:
        raise NotReady(str(exc)) from None
    try:
        pricing_cfg = load_pricing_config(pricing_path)
    except PricingConfigError as exc:
        raise NotReady(f"pricing.yml: {exc}") from None
    try:
        d_factor = load_d_factor()
    except DFactorTableError as exc:
        raise NotReady(str(exc)) from None
    return preferences, pricing_cfg, d_factor


def rank(con: duckdb.DuckDBPyConnection, *, now: datetime, kb_dir: Path, preferences_path: Path, pricing_path: Path,
         exports_dir: Path, records_dir: Path, league_yml: dict[str, Provenanced] | None = None,
         scenarios: list[str] | None = None, sync: SyncReport | None = None) -> RankReport:
    preferences, pricing_cfg, d_factor = check_ready(preferences_path, pricing_path)
    try:
        run = run_valuation(con, now=now, kb_dir=kb_dir, preferences=preferences, projection_cfg=ProjectionConfig(),
                            pricing_cfg=pricing_cfg, d_factor=d_factor, scenario_names=scenarios)
    except ValuationError as exc:
        raise NotReady(str(exc)) from None
    except PreferencesError as exc:
        # check_ready above has already validated the file, so this is
        # unreachable through the CLI -- kept so no caller of this function can
        # ever see a malformed config file arrive as anything but not-ready.
        # Named, never a blanket `except ValueError`: price_board raises a bare
        # ValueError for an ordinary modelling error and PricingConfigError
        # subclasses ValueError; neither is a PreferencesError.
        raise NotReady(str(exc)) from None
    record_run(con, run)
    md, csv = write_rankings(run, exports_dir)
    plan = write_asta_plan(run, exports_dir)
    records = export_records(con, run.run_id, run.rules_hash, records_dir)
    board = run.boards[run.scenarios[0].name]
    freeze = freeze_status(league_yml, now, run.summary["team_count"])
    grouped = by_class(run.projections)
    top: dict[str, list[dict[str, Any]]] = {}
    # Classes in the order of their best player, as walking one globally sorted
    # list used to give -- but each class's own three now in the run's single
    # ranking order, so the report agrees with rankings.md on a tie (finding E).
    for cls in sorted(grouped, key=lambda c: rank_key(grouped[c][0])):
        top[cls] = [{"name": p.name, "team": p.team_short, "value_p50": round(p.value_p50, 1),
                     "max_p50": board.prices[p.player_id].band.p50, "tier": run.tiers[p.player_id]}
                    for p in grouped[cls][:3]]
    return RankReport(run_id=run.run_id, created_at=run.created_at, rules_hash=run.rules_hash,
                      model_hash=run.model_hash, inputs_hash=run.inputs_hash, season_id=run.season_id,
                      giornata=run.giornata, scenarios=[s.name for s in run.scenarios], players=len(run.projections),
                      exports=[str(md), str(csv), str(plan)], records=[str(p) for p in records],
                      warnings=list(run.warnings), summary=run.summary,
                      provisional=freeze.note, freeze=freeze, top=top, sync=sync)
