"""The facade the CLI calls: the round, the page, the forecast, the XI when
league.yml names my team, the write, the records, the warnings."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.blend import load_layer
from fantaclaude.analysis.weekly.config import DEFAULT_CONFIG, WeeklyConfig, weekly_hash
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.forecast import (
    ForecastRow,
    forecast,
    load_terms,
    newest_probabili_file,
)
from fantaclaude.analysis.weekly.records import export_lineup_records, write_lineup_run
from fantaclaude.analysis.weekly.rounds import (
    Round,
    compilation_staleness,
    matchday_cross_check,
    player_fixtures,
    target_round,
    uncompiled_match_warning,
)
from fantaclaude.analysis.weekly.xi import (
    choose_xi,
    close_calls,
    contingencies,
    my_roster,
    order_bench,
)
from fantaclaude.asta.pinned import newest_run_id
from fantaclaude.ingest.names import AliasError, load_aliases
from fantaclaude.model.modules import load_modules
from fantaclaude.timeutil import to_db

TOP_PER_ROLE = 8


@dataclass(frozen=True)
class LineupReport:
    round_: Round
    run_id: str
    model_hash: str
    page: dict[str, Any]
    late: bool
    late_predictions: int
    rows: list[ForecastRow]
    xi: dict[str, Any] | None
    no_xi_reason: str | None
    my_team: int | None
    lineup_run_id: int
    records: list[Path]
    warnings: list[str]
    weekly_hash: str
    blend: dict[str, Any]
    bench: dict[str, Any] | None
    contingencies: list[dict[str, Any]]
    close_calls: list[dict[str, Any]]

    def top(self) -> dict[str, list[ForecastRow]]:
        by_role: dict[str, list[ForecastRow]] = {}
        for row in sorted(self.rows, key=lambda r: -r.expected_points):
            by_role.setdefault(row.classic_role, [])
            if len(by_role[row.classic_role]) < TOP_PER_ROLE:
                by_role[row.classic_role].append(row)
        return {role: by_role[role] for role in ("P", "D", "C", "A") if role in by_role}

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round_.to_dict(), "run_id": self.run_id, "model_hash": self.model_hash,
                "page": self.page, "late": self.late, "late_predictions": self.late_predictions,
                "top": {role: [r.to_dict() for r in rows] for role, rows in self.top().items()},
                "xi": self.xi, "no_xi_reason": self.no_xi_reason, "my_team": self.my_team,
                "lineup_run_id": self.lineup_run_id, "predictions": len(self.rows),
                "records": [str(p) for p in self.records], "warnings": list(self.warnings),
                "weekly_hash": self.weekly_hash, "blend": self.blend,
                "bench": self.bench, "contingencies": list(self.contingencies), "close_calls": list(self.close_calls)}


def lineup(con: duckdb.DuckDBPyConnection, *, now: datetime, season_id: int, giornata: int | None, run_id: str | None,
           late: bool, my_team: int | None, records_dir: Path, notes_path: Path | None = None,
           kb_dir: Path | None = None, aliases_path: Path | None = None, cfg: WeeklyConfig | None = None) -> LineupReport:
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
    file_id, fetched_at, players, matches, uncompiled = page
    fetched_at_str = fetched_at.isoformat(sep=" ", timespec="minutes")
    cfg = cfg or DEFAULT_CONFIG
    layer, layer_warnings = load_layer(con, season_id=season_id, giornata=round_.giornata, run_id=run_id,
                                       notes_path=notes_path, kb_dir=kb_dir, cfg=cfg)
    fixtures = player_fixtures(con, file_id)
    team_aliases: dict[str, str] = {}
    alias_warnings: list[str] = []
    if aliases_path is not None:
        try:
            team_aliases = load_aliases(aliases_path).teams_for("fantacalcio")
        except AliasError as exc:
            alias_warnings.append(f"aliases not read, the matchup term's club names matched by case only: {exc}")
    terms = load_terms(con, season_id=season_id, cfg=cfg, team_aliases=team_aliases)
    forecasted = forecast(con, run_id=run_id, probabili_file_id=file_id, fixtures=fixtures, layer=layer, cfg=cfg, terms=terms)
    rows = forecasted.rows
    warnings: list[str] = [*layer_warnings, *alias_warnings, *forecasted.warnings]
    if terms.matchups.rows == 0:
        warnings.append(f"the matchup table has no rows for season {season_id} -- a renamed club or a season with no "
                        f"fixtures ingested would look the same as the term being genuinely near zero")
    if (mismatch := matchday_cross_check(con, round_)):
        warnings.append(mismatch)
    if uncompiled:
        warnings.append(uncompiled_match_warning(round_.giornata, uncompiled, fetched_at_str))
    warnings += compilation_staleness(con, round_.giornata, file_id)
    xi, no_xi_reason, module, xi_rows, scores = None, None, None, None, None
    bench_dict: dict[str, Any] | None = None
    contingency_dicts: list[dict[str, Any]] = []
    close_call_dicts: list[dict[str, Any]] = []
    if my_team is None:
        no_xi_reason = "league.yml has no my_team leaf (asta verify-transfer prints it)"
    else:
        try:
            roster = my_roster(con, my_team)
            settings = con.execute("SELECT modules, bench_size FROM v_league_settings_current").fetchone()
            if settings is None or not settings[0]:
                raise ForecastError("no league_settings snapshot names the permitted modules -- run `fantaclaude sync-league`")
            modules = load_modules()
            allowed = list(settings[0])
            forecast_by_id = {r.player_id: r for r in rows}
            # `rows` is the probabili page (times the run's priced set); a
            # roster player the page dropped, or the run never priced, has no
            # row there at all, so his own exclude note would never reach
            # this set from `rows` alone -- `layer.notes.excluded` (keyed by
            # player_id, resolved against the listone, not the page) is
            # unioned in so the note still keeps him off the XI and the
            # bench (review finding, Important 1).
            excluded = frozenset(layer.notes.excluded) | frozenset(r.player_id for r in rows if r.excluded)
            choice = choose_xi(roster, forecast_by_id, modules, allowed, excluded=excluded)
            xi, module, scores = choice.to_dict(), choice.module, choice.module_scores
            xi_rows = [s.to_dict() for s in choice.slots]
            bench = None
            if settings[1] is None:
                warnings.append("league_settings carries no bench size -- run fantaclaude sync-league; no bench ordered")
            else:
                bench = order_bench(roster, choice, forecast_by_id, modules[choice.module],
                                    bench_size=int(settings[1]), excluded=excluded)
            plans = contingencies(roster, forecast_by_id, modules, allowed, choice, threshold=cfg.contingency_threshold,
                                  excluded=excluded)
            calls = close_calls(roster, choice, forecast_by_id, modules[choice.module], margin=cfg.close_call_margin,
                                limit=cfg.close_calls_max, excluded=excluded)
            bench_dict = bench.to_dict() if bench is not None else None
            contingency_dicts = [c.to_dict() for c in plans]
            close_call_dicts = [c.to_dict() for c in calls]
            if bench is not None and bench.uncovered:
                warnings.append(f"bench covers no {', '.join(bench.uncovered)} slot: a starter there who misses is replaced by the "
                                f"platform's own algorithm, changing the module or adapting someone unasked")
            if choice.unlisted:
                # `choice.unlisted` conflates two different causes (the page
                # never listed the player, or the run never priced him -- the
                # live case is id 795, on a lega roster and in no listone);
                # the zero is right either way, but the sentence must send a
                # reader to the right file, so the two are told apart here,
                # where the page's own membership is still queryable (review
                # finding 4, 2026-09-04).
                names = {p.player_id: p.name for p in roster}
                on_page = {pid for (pid,) in con.execute(
                    "SELECT player_id FROM probabili WHERE file_id = ?", [file_id]).fetchall()}
                not_on_page = [pid for pid in choice.unlisted if pid not in on_page]
                unpriced = [pid for pid in choice.unlisted if pid in on_page]
                if not_on_page:
                    warnings.append(f"{len(not_on_page)} roster player(s) not on the page, counted as 0: "
                                    + ", ".join(names[pid] for pid in not_on_page))
                if unpriced:
                    warnings.append(f"{len(unpriced)} roster player(s) on the page but not priced by run {run_id}, "
                                    "counted as 0: " + ", ".join(names[pid] for pid in unpriced))
        except ForecastError as exc:
            no_xi_reason = str(exc)
    whash = weekly_hash(cfg)
    lineup_run_id, is_late = write_lineup_run(con, round_=round_, run_id=run_id, model_hash=str(hashed[0]),
                                              probabili_file_id=file_id, rows=rows, now=now, late=late, my_team=my_team,
                                              module=module, xi=xi_rows, module_scores=scores, weekly_hash=whash,
                                              bench=bench_dict, contingencies=contingency_dicts, close_calls=close_call_dicts)
    records = export_lineup_records(con, lineup_run_id, records_dir)
    late_predictions = sum(1 for r in rows if to_db(now) >= (r.kickoff or round_.first_kickoff))
    blend_summary = {**layer.to_dict(), "sources": dict(Counter(r.source for r in rows)),
                     "disagreements": sum(1 for w in warnings if w.startswith("disagreement:"))}
    return LineupReport(round_, run_id, str(hashed[0]),
                        {"file_id": file_id, "fetched_at": fetched_at_str,
                         "players": players, "matches": matches, "uncompiled": int(uncompiled)},
                        is_late, late_predictions, rows, xi, no_xi_reason, my_team, lineup_run_id, records, warnings,
                        whash, blend_summary, bench_dict, contingency_dicts, close_call_dicts)
