"""The immutable write: one lineup_runs row and its predictions, appended,
refused only once every match of the round has kicked off unless late, and
the parquet copies under records/ (spec, "Forecasts are immutable")."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.exports import write_parquet
from fantaclaude.analysis.weekly.errors import ForecastError, LateForecast
from fantaclaude.analysis.weekly.forecast import ForecastRow
from fantaclaude.analysis.weekly.rounds import Round
from fantaclaude.timeutil import to_db


def write_lineup_run(con: duckdb.DuckDBPyConnection, *, round_: Round, run_id: str, model_hash: str,
                     probabili_file_id: int, rows: list[ForecastRow], now: datetime, late: bool,
                     my_team: int | None = None, module: str | None = None,
                     xi: list[dict[str, Any]] | None = None,
                     module_scores: dict[str, float | None] | None = None,
                     weekly_hash: str | None = None,
                     bench: dict[str, Any] | None = None,
                     contingencies: list[dict[str, Any]] | None = None,
                     close_calls: list[dict[str, Any]] | None = None) -> tuple[int, bool]:
    """One lineup_runs row and its predictions, appended. The run is late
    once the round's first kickoff has passed (the lega's lock on the XI);
    each prediction is late once ITS player's kickoff has passed -- the
    round's first when no fixture matched him. The write is refused only
    once every match of the round has started, unless `late`; between the
    first kickoff and the last it writes and marks (open question 18)."""
    written_at = to_db(now)
    is_late = written_at >= round_.first_kickoff
    if written_at >= round_.last_kickoff and not late:
        raise LateForecast(
            f"giornata {round_.giornata}: every match has kicked off (the last at {round_.last_kickoff:%Y-%m-%d %H:%M} UTC); "
            f"a forecast written now is not a forecast -- pass --late to write it marked, and calibration will exclude it")
    if not rows:
        raise ForecastError(f"nothing to forecast: no player on probabili file {probabili_file_id} is priced by run {run_id}")
    con.begin()
    try:
        lineup_run_id = con.execute(
            "INSERT INTO lineup_runs (season_id, giornata, run_id, model_hash, probabili_file_id, deadline, written_at, "
            "late, my_team, module, xi, module_scores, predictions, weekly_hash, bench, contingencies, close_calls) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?, ?::JSON, ?::JSON, ?::JSON) "
            "RETURNING lineup_run_id",
            [round_.season_id, round_.giornata, run_id, model_hash, probabili_file_id, round_.first_kickoff, written_at,
             is_late, my_team, module, None if xi is None else json.dumps(xi, ensure_ascii=False),
             None if module_scores is None else json.dumps(module_scores), len(rows), weekly_hash,
             None if bench is None else json.dumps(bench, ensure_ascii=False),
             None if contingencies is None else json.dumps(contingencies, ensure_ascii=False),
             None if close_calls is None else json.dumps(close_calls, ensure_ascii=False)]).fetchone()[0]
        con.executemany(
            "INSERT INTO predictions (lineup_run_id, season_id, giornata, player_id, p_start_published, p_start, "
            "fv_if_plays, fv_sd, expected_points, source, kickoff, late, trace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[lineup_run_id, round_.season_id, round_.giornata, r.player_id, r.p_start_published, r.p_start,
              r.fv_if_plays, r.fv_sd, r.expected_points, r.source, r.kickoff,
              written_at >= (r.kickoff or round_.first_kickoff), json.dumps(r.trace, ensure_ascii=False)] for r in rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return int(lineup_run_id), is_late


def export_lineup_records(con: duckdb.DuckDBPyConnection, lineup_run_id: int, records_dir: Path) -> list[Path]:
    """records/lineup_runs/<season>-<giornata>-<written_at>-<lineup_run_id>.parquet and the same under
    predictions/, once. The id suffix is load-bearing: `written_at` is a
    TIMESTAMP column but the stamp here is second-precision, so two `lineup`
    invocations inside the same second are two immutable rows sharing one
    stem without it -- `write_parquet` would then silently skip the second
    file rather than record it (review finding 3, 2026-09-04)."""
    season, giornata, written = con.execute(
        "SELECT season_id, giornata, written_at FROM lineup_runs WHERE lineup_run_id = ?", [lineup_run_id]).fetchone()
    stem = f"{season}-{giornata:02d}-{written:%Y%m%dT%H%M%SZ}-{lineup_run_id}"
    targets = [(records_dir / "lineup_runs" / f"{stem}.parquet",
                f"SELECT * FROM lineup_runs WHERE lineup_run_id = {int(lineup_run_id)}"),
               (records_dir / "predictions" / f"{stem}.parquet",
                f"SELECT * FROM predictions WHERE lineup_run_id = {int(lineup_run_id)}")]
    return [path for path, query in targets if write_parquet(con, query, path)]
