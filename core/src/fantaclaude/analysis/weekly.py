"""The weekly forecast (spec, "`fanta-manager` -- the weekly loop", Phase 3a).

The round and its deadline are read off `fixtures`, never off the stored
`status.mday`, which only moves when the rules do. A forecast row is the
published `p_start` (a probability of receiving a voto) times the pinned
run's per-presenza `exp_fantamedia`, for every player the page lists and the
run prices. The write is refused once the giornata's first kickoff has
passed unless the caller says `late`, and then the row says so; several
writes before one deadline are several rows, and `v_lineup_runs_current`
is the latest non-late one. Nothing here updates or deletes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.exports import write_parquet
from fantaclaude.asta.pinned import newest_run_id
from fantaclaude.timeutil import to_db


class ForecastError(RuntimeError):
    """A forecast cannot be written from what is on disk (no calendar, no page, no run)."""


class LateForecast(ForecastError):
    """The giornata has kicked off; a forecast written now is not a forecast."""


@dataclass(frozen=True)
class Round:
    season_id: int
    giornata: int
    first_kickoff: datetime          # naive UTC, as fixtures stores it
    last_kickoff: datetime
    matches: int

    def to_dict(self) -> dict[str, Any]:
        return {"season_id": self.season_id, "giornata": self.giornata,
                "first_kickoff": self.first_kickoff.isoformat(sep=" ", timespec="minutes"),
                "last_kickoff": self.last_kickoff.isoformat(sep=" ", timespec="minutes"), "matches": self.matches}


def target_round(con: duckdb.DuckDBPyConnection, now: datetime, *, season_id: int,
                 giornata: int | None = None) -> Round:
    """The giornata to forecast: the first whose last kickoff is still ahead
    (a giornata in progress is still the target -- and late), or the one asked for."""
    rows = con.execute(
        "SELECT giornata, min(kickoff), max(kickoff), count(*) FROM v_fixtures_current "
        "WHERE competition = 'SA' AND season_id = ? AND giornata IS NOT NULL AND kickoff IS NOT NULL "
        "GROUP BY giornata ORDER BY giornata", [season_id]).fetchall()
    if not rows:
        raise ForecastError(f"no Serie A fixtures for season {season_id} -- run `fantaclaude ingest calendar`")
    rounds = [Round(season_id, int(g), first, last, int(n)) for g, first, last, n in rows]
    if giornata is not None:
        for r in rounds:
            if r.giornata == giornata:
                return r
        raise ForecastError(f"giornata {giornata} is not in the season {season_id} calendar")
    when = to_db(now)
    for r in rounds:
        if r.last_kickoff > when:
            return r
    raise ForecastError(f"every giornata of season {season_id} has kicked off -- pass --giornata to write one late")


@dataclass(frozen=True)
class ForecastRow:
    player_id: int
    name: str
    team_short: str | None
    classic_role: str
    roles: tuple[str, ...]
    p_start_published: int | None
    p_start: float
    fv_if_plays: float
    fv_sd: float | None
    expected_points: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short,
                "classic_role": self.classic_role, "roles": list(self.roles),
                "p_start_published": self.p_start_published, "p_start": self.p_start,
                "fv_if_plays": self.fv_if_plays, "fv_sd": self.fv_sd, "expected_points": self.expected_points,
                "source": self.source}


def newest_probabili_file(con: duckdb.DuckDBPyConnection, season_id: int,
                          giornata: int) -> tuple[int, datetime, int, int] | None:
    row = con.execute("SELECT file_id, fetched_at, row_count, matches FROM probabili_files "
                      "WHERE season_id = ? AND giornata = ? ORDER BY file_id DESC LIMIT 1", [season_id, giornata]).fetchone()
    return None if row is None else (int(row[0]), row[1], int(row[2]), int(row[3]))


def forecast(con: duckdb.DuckDBPyConnection, *, run_id: str, probabili_file_id: int) -> list[ForecastRow]:
    """Every player the page lists and the run prices. 3a: p_start is the
    published number alone (`source: published`), fv_sd is null."""
    rows = con.execute(
        "SELECT v.player_id, v.name, v.team_short, v.classic_role, v.roles, v.exp_fantamedia, p.p_start "
        "FROM valuations v JOIN probabili p ON p.player_id = v.player_id "
        "WHERE v.run_id = ? AND p.file_id = ? ORDER BY v.player_id", [run_id, probabili_file_id]).fetchall()
    out: list[ForecastRow] = []
    for pid, name, short, role, roles, fm, published in rows:
        p_start = int(published) / 100.0
        out.append(ForecastRow(int(pid), str(name), short, str(role), tuple(roles), int(published), p_start,
                               float(fm), None, p_start * float(fm), "published"))
    return out


def write_lineup_run(con: duckdb.DuckDBPyConnection, *, round_: Round, run_id: str, model_hash: str,
                     probabili_file_id: int, rows: list[ForecastRow], now: datetime, late: bool,
                     my_team: int | None = None, module: str | None = None,
                     xi: list[dict[str, Any]] | None = None,
                     module_scores: dict[str, float | None] | None = None) -> int:
    """One lineup_runs row and its predictions, appended; refused after the
    first kickoff unless `late`, and then marked as such by the clock, not the flag."""
    written_at = to_db(now)
    is_late = written_at >= round_.first_kickoff
    if is_late and not late:
        raise LateForecast(
            f"giornata {round_.giornata} kicked off at {round_.first_kickoff:%Y-%m-%d %H:%M} UTC; a forecast written "
            f"now is not a forecast -- pass --late to write it marked, and calibration will exclude it")
    if not rows:
        raise ForecastError(f"nothing to forecast: no player on probabili file {probabili_file_id} is priced by run {run_id}")
    con.begin()
    try:
        lineup_run_id = con.execute(
            "INSERT INTO lineup_runs (season_id, giornata, run_id, model_hash, probabili_file_id, deadline, written_at, "
            "late, my_team, module, xi, module_scores, predictions) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?) "
            "RETURNING lineup_run_id",
            [round_.season_id, round_.giornata, run_id, model_hash, probabili_file_id, round_.first_kickoff, written_at,
             is_late, my_team, module, None if xi is None else json.dumps(xi, ensure_ascii=False),
             None if module_scores is None else json.dumps(module_scores), len(rows)]).fetchone()[0]
        con.executemany(
            "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [[lineup_run_id, round_.season_id, round_.giornata, r.player_id, r.p_start_published, r.p_start,
              r.fv_if_plays, r.fv_sd, r.expected_points, r.source] for r in rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return int(lineup_run_id)


def export_lineup_records(con: duckdb.DuckDBPyConnection, lineup_run_id: int, records_dir: Path) -> list[Path]:
    """records/lineup_runs/<season>-<giornata>-<written_at>.parquet and the same under predictions/, once."""
    season, giornata, written = con.execute(
        "SELECT season_id, giornata, written_at FROM lineup_runs WHERE lineup_run_id = ?", [lineup_run_id]).fetchone()
    stem = f"{season}-{giornata:02d}-{written:%Y%m%dT%H%M%SZ}"
    targets = [(records_dir / "lineup_runs" / f"{stem}.parquet",
                f"SELECT * FROM lineup_runs WHERE lineup_run_id = {int(lineup_run_id)}"),
               (records_dir / "predictions" / f"{stem}.parquet",
                f"SELECT * FROM predictions WHERE lineup_run_id = {int(lineup_run_id)}")]
    return [path for path, query in targets if write_parquet(con, query, path)]


TOP_PER_ROLE = 8


@dataclass(frozen=True)
class LineupReport:
    round_: Round
    run_id: str
    model_hash: str
    page: dict[str, Any]
    late: bool
    rows: list[ForecastRow]
    xi: dict[str, Any] | None
    no_xi_reason: str | None
    my_team: int | None
    lineup_run_id: int
    records: list[Path]
    warnings: list[str]

    def top(self) -> dict[str, list[ForecastRow]]:
        by_role: dict[str, list[ForecastRow]] = {}
        for row in sorted(self.rows, key=lambda r: -r.expected_points):
            by_role.setdefault(row.classic_role, [])
            if len(by_role[row.classic_role]) < TOP_PER_ROLE:
                by_role[row.classic_role].append(row)
        return {role: by_role[role] for role in ("P", "D", "C", "A") if role in by_role}

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round_.to_dict(), "run_id": self.run_id, "model_hash": self.model_hash,
                "page": self.page, "late": self.late,
                "top": {role: [r.to_dict() for r in rows] for role, rows in self.top().items()},
                "xi": self.xi, "no_xi_reason": self.no_xi_reason, "my_team": self.my_team,
                "lineup_run_id": self.lineup_run_id, "predictions": len(self.rows),
                "records": [str(p) for p in self.records], "warnings": list(self.warnings)}


def lineup(con: duckdb.DuckDBPyConnection, *, now: datetime, season_id: int, giornata: int | None, run_id: str | None,
           late: bool, my_team: int | None, records_dir: Path) -> LineupReport:
    round_ = target_round(con, now, season_id=season_id, giornata=giornata)
    run_id = run_id or newest_run_id(con)
    if run_id is None:
        raise ForecastError("no valuation run to read projections from -- run `fantaclaude rank`")
    hashed = con.execute("SELECT model_hash FROM valuation_runs WHERE run_id = ?", [run_id]).fetchone()
    if hashed is None:
        raise ForecastError(f"run {run_id!r} is not in valuation_runs")
    page = newest_probabili_file(con, season_id, round_.giornata)
    if page is None:
        raise ForecastError(f"no probabili page for giornata {round_.giornata} -- run `fantaclaude ingest probabili`")
    file_id, fetched_at, players, matches = page
    uncompiled = con.execute("SELECT uncompiled FROM probabili_files WHERE file_id = ?", [file_id]).fetchone()[0]
    rows = forecast(con, run_id=run_id, probabili_file_id=file_id)
    warnings: list[str] = []
    if uncompiled:
        warnings.append(f"{uncompiled} match(es) of giornata {round_.giornata} not yet compiled on the page fetched "
                        f"{fetched_at:%Y-%m-%d %H:%M} UTC")
    xi, no_xi_reason, module, xi_rows, scores = None, None, None, None, None
    if my_team is None:
        no_xi_reason = "league.yml has no my_team leaf (asta verify-transfer prints it)"
    else:
        no_xi_reason = "the XI lands with Task 8"          # replaced in Task 8
    lineup_run_id = write_lineup_run(con, round_=round_, run_id=run_id, model_hash=str(hashed[0]),
                                     probabili_file_id=file_id, rows=rows, now=now, late=late, my_team=my_team,
                                     module=module, xi=xi_rows, module_scores=scores)
    is_late = bool(con.execute("SELECT late FROM lineup_runs WHERE lineup_run_id = ?", [lineup_run_id]).fetchone()[0])
    records = export_lineup_records(con, lineup_run_id, records_dir)
    return LineupReport(round_, run_id, str(hashed[0]),
                        {"file_id": file_id, "fetched_at": fetched_at.isoformat(sep=" ", timespec="minutes"),
                         "players": players, "matches": matches, "uncompiled": int(uncompiled)},
                        is_late, rows, xi, no_xi_reason, my_team, lineup_run_id, records, warnings)
