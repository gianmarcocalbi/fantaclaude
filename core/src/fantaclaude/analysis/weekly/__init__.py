"""The weekly forecast (spec, "`fanta-manager` -- the weekly loop").

3a's `analysis/weekly.py`, split by concern in 3b: `rounds` (the round and
its deadlines), `forecast` (the rows), `xi` (the solve), `records` (the
immutable write), `report` (the facade). Every public name is re-exported
here so callers keep their import path.
"""

from fantaclaude.analysis.weekly.errors import ForecastError, LateForecast
from fantaclaude.analysis.weekly.forecast import (
    ForecastRow,
    forecast,
    newest_probabili_file,
)
from fantaclaude.analysis.weekly.records import export_lineup_records, write_lineup_run
from fantaclaude.analysis.weekly.report import TOP_PER_ROLE, LineupReport, lineup
from fantaclaude.analysis.weekly.rounds import (
    MATCHDAY_READ_WINDOW,
    STALE_COMPILATION,
    PlayerFixture,
    Round,
    compilation_staleness,
    matchday_cross_check,
    player_fixtures,
    target_round,
    uncompiled_match_warning,
)
from fantaclaude.analysis.weekly.xi import (
    ADAPTED_MALUS,
    RosterPlayer,
    XiChoice,
    XiSlot,
    choose_xi,
    my_roster,
)

__all__ = [
    "ADAPTED_MALUS", "MATCHDAY_READ_WINDOW", "STALE_COMPILATION", "TOP_PER_ROLE",
    "ForecastError", "ForecastRow", "LateForecast", "LineupReport", "PlayerFixture", "RosterPlayer", "Round",
    "XiChoice", "XiSlot",
    "choose_xi", "compilation_staleness", "export_lineup_records", "forecast", "lineup", "matchday_cross_check",
    "my_roster", "newest_probabili_file", "player_fixtures", "target_round", "uncompiled_match_warning",
    "write_lineup_run",
]
