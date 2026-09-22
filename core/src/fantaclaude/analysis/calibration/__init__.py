"""Calibration (spec, "Calibration: what 3c ships"): predicted against actual,
computed on read and never stored.

`calibrate` reads immutable inputs -- `v_predictions_current`, the voti, the
platform's own `match_scores` -- and writes nothing: a stored copy would go
stale the first time fantacalcio.it corrects a voto, which is
`v_market_prices`'s argument. `actuals` joins, `pstart` draws the reliability
curve, `fantavoto` measures the bias and names the surprises, `weeks` gives
the week's verdict, `scoring_check` holds the platform's scores against the
voti. Actual fantavoti are scored under the rules in force -- what `lineup`
scores under -- and a giornata predicted under other rules is named.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from fantaclaude.analysis.calibration.actuals import (
    clubs_with_voti,
    load_actuals,
    load_scored,
)
from fantaclaude.analysis.calibration.errors import CalibrationError, NothingToCalibrate
from fantaclaude.analysis.calibration.fantavoto import (
    ModelBias,
    Surprise,
    fantavoto_bias,
    surprises,
)
from fantaclaude.analysis.calibration.pstart import PStartReport, reliability
from fantaclaude.analysis.calibration.scoring_check import ScoringCheck, check_scoring
from fantaclaude.analysis.calibration.weeks import Week, week
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.forecast import scoring_in_force
from fantaclaude.db.schema import SCHEMA_VERSION
from fantaclaude.model.modules import load_modules
from fantaclaude.model.scoring import ScoringError, modifier_status

__all__ = ["CalibrationError", "CalibrationReport", "NothingToCalibrate", "calibrate", "calibration_giornate"]


@dataclass(frozen=True)
class CalibrationReport:
    season_id: int
    giornate: list[int]
    weeks: list[Week]
    p_start: PStartReport
    fantavoto: list[ModelBias]
    surprises: dict[str, list[Surprise]]
    scoring: ScoringCheck
    predictions: int
    dropped: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"season_id": self.season_id, "giornate": list(self.giornate),
                "weeks": [w.to_dict() for w in self.weeks], "p_start": self.p_start.to_dict(),
                "fantavoto": [m.to_dict() for m in self.fantavoto],
                "surprises": {k: [asdict(s) for s in v] for k, v in self.surprises.items()},
                "scoring": self.scoring.to_dict(), "predictions": self.predictions, "dropped": self.dropped,
                "warnings": list(self.warnings)}


def calibration_giornate(con: duckdb.DuckDBPyConnection, season_id: int) -> list[int]:
    """Every giornata of the season with voti and either predictions or a recorded match."""
    rows = con.execute(
        "SELECT DISTINCT giornata FROM v_voti_files_current WHERE season_id = ? AND ("
        "giornata IN (SELECT giornata FROM v_predictions_current WHERE season_id = ?) OR "
        "giornata IN (SELECT giornata FROM v_match_files_current WHERE season_id = ?)) ORDER BY giornata",
        [season_id, season_id, season_id]).fetchall()
    return [int(r[0]) for r in rows]


def _refusal(calculate: dict[str, Any]) -> str | None:
    status = modifier_status(calculate)
    if not status.any_active:
        return None
    active = (["D-Factor"] if status.d_factor else []) + list(status.unknown_active)
    return f"a scoring modifier is active ({', '.join(active)}) -- a per-slot sum no longer scores an eleven"


def calibrate(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int] | None = None,
              my_team: int | None = None) -> CalibrationReport:
    stored = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    if stored is None or stored < SCHEMA_VERSION:
        raise CalibrationError(f"database at schema {stored}, code expects {SCHEMA_VERSION} -- any "
                               f"`fantaclaude ingest` migrates it")
    asked = sorted(set(giornate)) if giornate else calibration_giornate(con, season_id)
    if not asked:
        raise NothingToCalibrate(f"no giornata of season {season_id} has voti and either predictions or a recorded "
                                 f"match -- `fantaclaude ingest stats-web`, then `fantaclaude ingest lineup`")
    rated = {int(r[0]) for r in con.execute(
        "SELECT giornata FROM v_voti_files_current WHERE season_id = ? AND giornata = ANY(?)",
        [season_id, asked]).fetchall()}
    warnings = [f"giornata {g} has no voti yet -- skipped (`fantaclaude ingest stats-web --giornata {g}`)"
                for g in asked if g not in rated]
    scored_giornate = [g for g in asked if g in rated]
    if not scored_giornate:
        raise NothingToCalibrate(f"giornata {', '.join(map(str, asked))}: no voti yet -- "
                                 f"`fantaclaude ingest stats-web` once the round is rated")
    try:
        sheet, bm = scoring_in_force(con)
    except (ForecastError, ScoringError) as exc:
        raise CalibrationError(str(exc)) from None
    payload, allowed, rules_hash = con.execute(
        "SELECT payload, modules, rules_hash FROM v_league_settings_current").fetchone()
    payload = payload if isinstance(payload, dict) else json.loads(payload)
    refusal = _refusal(payload.get("calculate") or {})

    actuals = load_actuals(con, season_id=season_id, giornate=scored_giornate, sheet=sheet, bm=bm)
    clubs = clubs_with_voti(con, season_id=season_id, giornate=scored_giornate, sheet=sheet)
    scored, dropped = load_scored(con, season_id=season_id, giornate=scored_giornate, actuals=actuals, clubs=clubs)
    for giornata, rules in con.execute(
            "SELECT DISTINCT p.giornata, v.rules_hash FROM v_predictions_current p "
            "JOIN lineup_runs l ON l.lineup_run_id = p.lineup_run_id JOIN valuation_runs v ON v.run_id = l.run_id "
            "WHERE p.season_id = ? AND p.giornata = ANY(?) ORDER BY 1", [season_id, scored_giornate]).fetchall():
        if rules != rules_hash:
            warnings.append(f"giornata {giornata} was predicted under rules {rules}; the voti are scored under "
                            f"{rules_hash} -- its bias mixes a rule change with model error")

    weeks: list[Week] = []
    my_roster: frozenset[int] = frozenset()
    if my_team is None:
        warnings.append("league.yml has no my_team leaf -- no weekly verdict, and no roster to name the misses on")
    else:
        my_roster = frozenset(int(r[0]) for r in con.execute(
            "SELECT player_id FROM v_rosters_current WHERE team_id = ?", [my_team]).fetchall())
        modules = load_modules()
        for giornata in scored_giornate:
            fantavoti = {pid: a.fantavoto for (g, pid), a in actuals.items() if g == giornata and a.voted}
            verdict = week(con, season_id=season_id, giornata=giornata, my_team=my_team, fantavoti=fantavoti,
                           modules=modules, allowed=list(allowed or []), refusal=refusal)
            if verdict is not None:
                weeks.append(verdict)
    if not scored and not weeks:
        raise NothingToCalibrate(f"giornata {', '.join(map(str, scored_giornate))}: neither a prediction nor a "
                                 f"recorded match to score -- `fantaclaude lineup` before the lock, "
                                 f"`fantaclaude ingest lineup` after the round")
    return CalibrationReport(season_id, scored_giornate, weeks, reliability(scored), fantavoto_bias(scored),
                             surprises(scored, my_roster=my_roster),
                             check_scoring(con, sheet=sheet, bm=bm, season_id=season_id, giornate=scored_giornate),
                             len(scored), dropped, warnings)
