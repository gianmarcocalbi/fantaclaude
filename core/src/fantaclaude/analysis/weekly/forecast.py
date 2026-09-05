"""The forecast rows: every player the page lists and the run prices (spec,
"Predictions are written for every player the page lists and the run prices
-- not for my roster")."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import fmean, pstdev
from typing import Any

import duckdb

from fantaclaude.analysis.history import COACH_ROLE, EVENT_COLUMNS
from fantaclaude.analysis.weekly.blend import EMPTY_BLEND, BlendLayer, blend
from fantaclaude.analysis.weekly.config import DEFAULT_CONFIG, WeeklyConfig
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.rounds import PlayerFixture
from fantaclaude.model.scoring import BonusMalus, Events, fantavoto, voto_sheet
from fantaclaude.model.seasons import back_seasons


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
    kickoff: datetime | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    excluded: bool = False
    matchup: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short,
                "classic_role": self.classic_role, "roles": list(self.roles),
                "p_start_published": self.p_start_published, "p_start": self.p_start,
                "fv_if_plays": self.fv_if_plays, "fv_sd": self.fv_sd, "expected_points": self.expected_points,
                "source": self.source,
                "kickoff": None if self.kickoff is None else self.kickoff.isoformat(sep=" ", timespec="minutes"),
                "trace": dict(self.trace), "excluded": self.excluded, "matchup": self.matchup}


@dataclass(frozen=True)
class Forecast:
    rows: list[ForecastRow]
    warnings: list[str]


def scoring_in_force(con: duckdb.DuckDBPyConnection) -> tuple[str, BonusMalus]:
    """The voto sheet and the bonus/malus of the current league_settings row -- what the run itself scored under."""
    row = con.execute("SELECT payload FROM v_league_settings_current").fetchone()
    if row is None:
        raise ForecastError("no league_settings snapshot -- run `fantaclaude sync-league` first")
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    calculate = payload.get("calculate") or {}
    return voto_sheet(calculate), BonusMalus.from_calculate(calculate)


def _shrunk(values: list[float], mean: float, k: float) -> tuple[float, int]:
    n = len(values)
    if n == 0:
        return 0.0, 0
    return (fmean(values) - mean) * n / (n + k), n


@dataclass(frozen=True)
class MatchupTable:
    venue: dict[tuple[str, bool], tuple[float, int]]        # (classic_role, home) -> (shrunk delta, rows)
    conceded: dict[tuple[str, str], tuple[float, int]]      # (opponent_short, classic_role) -> (shrunk delta, rows)
    rows: int
    season_id: int


def load_matchups(con: duckdb.DuckDBPyConnection, *, season_id: int, sheet: str, bm: BonusMalus,
                  cfg: WeeklyConfig) -> MatchupTable:
    """This season's rated rows joined to this season's fixtures -- the only
    season with fixtures, since the voti workbooks carry no opponent and no
    venue (spec, "The matchup term"). Two deltas per role against the
    role's season mean, each shrunk toward zero by n / (n + k)."""
    rows = con.execute(
        "SELECT m.classic_role, m.voto, " + ", ".join(f"m.{c}" for c in EVENT_COLUMNS) + ", t.short, f.home_short, f.away_short "
        "FROM v_player_match_current m "
        "JOIN v_teams_current t ON lower(t.name) = lower(m.team) "
        "JOIN v_fixtures_current f ON f.competition = 'SA' AND f.season_id = m.season_id AND f.giornata = m.giornata "
        "AND (f.home_short = t.short OR f.away_short = t.short) "
        "WHERE m.sheet = ? AND m.season_id = ? AND NOT m.senza_voto AND m.voto IS NOT NULL AND m.classic_role <> ?",
        [sheet, season_id, COACH_ROLE]).fetchall()
    by_role: dict[str, list[float]] = defaultdict(list)
    by_venue: dict[tuple[str, bool], list[float]] = defaultdict(list)
    by_opponent: dict[tuple[str, str], list[float]] = defaultdict(list)
    for role, voto, *counts, short, home_short, away_short in rows:
        fv = fantavoto(float(voto), Events(**{name: float(v) for name, v in zip(EVENT_COLUMNS, counts)}), bm)
        home = short == home_short
        by_role[str(role)].append(fv)
        by_venue[(str(role), home)].append(fv)
        by_opponent[(str(away_short if home else home_short), str(role))].append(fv)
    means = {role: fmean(v) for role, v in by_role.items()}
    venue = {key: _shrunk(v, means[key[0]], cfg.matchup_shrink_k) for key, v in by_venue.items()}
    conceded = {key: _shrunk(v, means[key[1]], cfg.matchup_shrink_k) for key, v in by_opponent.items()}
    return MatchupTable(venue, conceded, len(rows), season_id)


def matchup_term(table: MatchupTable, *, classic_role: str, fixture: PlayerFixture | None,
                 cfg: WeeklyConfig) -> tuple[float, dict[str, Any]]:
    """Venue plus conceded, capped at +-matchup_cap; zero with no fixture."""
    if fixture is None:
        return 0.0, {"reason": "no fixture"}
    venue, n_venue = table.venue.get((classic_role, fixture.home), (0.0, 0))
    conceded, n_conceded = table.conceded.get((fixture.opponent_short or "", classic_role), (0.0, 0))
    term = max(-cfg.matchup_cap, min(cfg.matchup_cap, venue + conceded))
    return term, {"home": fixture.home, "opponent": fixture.opponent_short, "venue": round(venue, 4), "n_venue": n_venue,
                  "conceded": round(conceded, 4), "n_conceded": n_conceded, "term": round(term, 4)}


@dataclass(frozen=True)
class SpreadTable:
    player: dict[int, tuple[float, int]]      # player_id -> (own dispersion, rated matches)
    role_prior: dict[str, float]              # classic_role -> pstdev of the back seasons' fantavoti


def load_spreads(con: duckdb.DuckDBPyConnection, *, current_season: int, sheet: str, bm: BonusMalus,
                 cfg: WeeklyConfig) -> SpreadTable:
    """Every player's fantavoto dispersion over his rated matches in the
    stored seasons, scored under the current bonus/malus, and the role
    prior from the back seasons alone."""
    seasons = [*back_seasons(current_season, cfg.spread_back_seasons), current_season]
    rows = con.execute(
        "SELECT season_id, player_id, classic_role, voto, " + ", ".join(EVENT_COLUMNS) + " FROM v_player_match_current "
        "WHERE sheet = ? AND NOT senza_voto AND voto IS NOT NULL AND classic_role <> ? AND season_id = ANY(?)",
        [sheet, COACH_ROLE, seasons]).fetchall()
    own: dict[int, list[float]] = defaultdict(list)
    prior_rows: dict[str, list[float]] = defaultdict(list)
    for season_id, player_id, role, voto, *counts in rows:
        fv = fantavoto(float(voto), Events(**{name: float(v) for name, v in zip(EVENT_COLUMNS, counts)}), bm)
        own[int(player_id)].append(fv)
        if int(season_id) != current_season:
            prior_rows[str(role)].append(fv)
    player = {pid: (pstdev(v) if len(v) > 1 else 0.0, len(v)) for pid, v in own.items()}
    prior = {role: pstdev(v) if len(v) > 1 else 0.0 for role, v in prior_rows.items()}
    return SpreadTable(player, prior)


def spread_for(table: SpreadTable, *, player_id: int, classic_role: str, cfg: WeeklyConfig) -> tuple[float | None, dict[str, Any]]:
    """sd^2 = (n s^2 + k prior^2) / (n + k); None when the role has no prior."""
    prior = table.role_prior.get(classic_role)
    if prior is None:
        return None, {"reason": "no role prior"}
    own, n = table.player.get(player_id, (0.0, 0))
    pooled = ((n * own ** 2 + cfg.spread_prior_k * prior ** 2) / (n + cfg.spread_prior_k)) ** 0.5
    return pooled, {"n": n, "own": round(own, 4), "prior": round(prior, 4), "k": cfg.spread_prior_k}


@dataclass(frozen=True)
class Terms:
    matchups: MatchupTable
    spreads: SpreadTable


def load_terms(con: duckdb.DuckDBPyConnection, *, season_id: int, cfg: WeeklyConfig) -> Terms:
    sheet, bm = scoring_in_force(con)
    return Terms(load_matchups(con, season_id=season_id, sheet=sheet, bm=bm, cfg=cfg),
                 load_spreads(con, current_season=season_id, sheet=sheet, bm=bm, cfg=cfg))


def newest_probabili_file(con: duckdb.DuckDBPyConnection, season_id: int,
                          giornata: int) -> tuple[int, datetime, int, int, int] | None:
    """(file_id, fetched_at, row_count, matches, uncompiled). `uncompiled`
    rides along in this one SELECT rather than a second query for it in the
    caller -- both come from the same `probabili_files` row anyway (review
    finding 14, 2026-09-04)."""
    row = con.execute("SELECT file_id, fetched_at, row_count, matches, uncompiled FROM probabili_files "
                      "WHERE season_id = ? AND giornata = ? ORDER BY file_id DESC LIMIT 1", [season_id, giornata]).fetchone()
    return None if row is None else (int(row[0]), row[1], int(row[2]), int(row[3]), int(row[4]))


def forecast(con: duckdb.DuckDBPyConnection, *, run_id: str, probabili_file_id: int,
             fixtures: dict[int, PlayerFixture] | None = None, layer: BlendLayer = EMPTY_BLEND,
             cfg: WeeklyConfig = DEFAULT_CONFIG, terms: Terms | None = None) -> Forecast:
    """Every player the page lists and the run prices, blended by precedence
    (blend.py), plus the matchup term and the pooled spread when `terms` is
    given; both are null/zero without it."""
    fixtures = fixtures or {}
    rows = con.execute(
        "SELECT v.player_id, v.name, v.team_short, v.classic_role, v.roles, v.exp_fantamedia, v.exp_presenze, p.p_start "
        "FROM valuations v JOIN probabili p ON p.player_id = v.player_id "
        "WHERE v.run_id = ? AND p.file_id = ? ORDER BY v.player_id", [run_id, probabili_file_id]).fetchall()
    out: list[ForecastRow] = []
    warnings: list[str] = []
    for pid, name, short, role, roles, fm, presenze, published in rows:
        fixture = fixtures.get(int(pid))
        kickoff = None if fixture is None else fixture.kickoff
        b = blend(player_id=int(pid), name=str(name), team_short=short, published=int(published),
                  exp_presenze=float(presenze), kickoff=kickoff, layer=layer, cfg=cfg)
        matchup, matchup_trace = (0.0, {"reason": "no terms"}) if terms is None else matchup_term(
            terms.matchups, classic_role=str(role), fixture=fixture, cfg=cfg)
        fv_sd, sd_trace = (None, {"reason": "no terms"}) if terms is None else spread_for(
            terms.spreads, player_id=int(pid), classic_role=str(role), cfg=cfg)
        fv_if_plays = (float(fm) + matchup) * b.value_factor
        b.trace["kickoff"] = None if kickoff is None else kickoff.isoformat(sep=" ", timespec="minutes")
        b.trace["deadline"] = "player" if kickoff is not None else "round"
        b.trace["matchup"], b.trace["spread"] = matchup_trace, sd_trace
        out.append(ForecastRow(int(pid), str(name), short, str(role), tuple(roles), int(published), b.p_start,
                               fv_if_plays, fv_sd, b.p_start * fv_if_plays, b.source, kickoff=kickoff,
                               trace=b.trace, excluded=b.excluded, matchup=matchup))
        warnings += list(b.warnings)
    return Forecast(out, warnings)
