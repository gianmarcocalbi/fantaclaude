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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.exports import write_parquet
from fantaclaude.asta.pinned import newest_run_id
from fantaclaude.model.modules import Module, assign_weighted, load_modules
from fantaclaude.model.roles import Role
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
                          giornata: int) -> tuple[int, datetime, int, int, int] | None:
    """(file_id, fetched_at, row_count, matches, uncompiled). `uncompiled`
    rides along in this one SELECT rather than a second query for it in the
    caller -- both come from the same `probabili_files` row anyway (review
    finding 14, 2026-09-04)."""
    row = con.execute("SELECT file_id, fetched_at, row_count, matches, uncompiled FROM probabili_files "
                      "WHERE season_id = ? AND giornata = ? ORDER BY file_id DESC LIMIT 1", [season_id, giornata]).fetchone()
    return None if row is None else (int(row[0]), row[1], int(row[2]), int(row[3]), int(row[4]))


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
                     module_scores: dict[str, float | None] | None = None) -> tuple[int, bool]:
    """One lineup_runs row and its predictions, appended; refused after the
    first kickoff unless `late`, and then marked as such by the clock, not
    the flag. Returns (lineup_run_id, is_late) -- the caller already needs
    `is_late` for the report and would otherwise SELECT the very row this
    just wrote to get it back (review finding 14, 2026-09-04)."""
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


ADAPTED_MALUS = 1.0      # Mantra: a player out of position scores his voto minus one


@dataclass(frozen=True)
class RosterPlayer:
    player_id: int
    name: str
    roles: frozenset[Role]
    cost: int
    in_listone: bool


def my_roster(con: duckdb.DuckDBPyConnection, team_id: int) -> list[RosterPlayer]:
    """The team's roster in the latest snapshot, with the listone's roles; an id
    the listone lacks is kept with no roles (it can be fielded nowhere)."""
    rows = con.execute(
        "SELECT r.player_id, r.cost, p.name, p.mantra_roles FROM v_rosters_current r "
        "LEFT JOIN v_players_current p ON p.player_id = r.player_id WHERE r.team_id = ? ORDER BY r.position",
        [team_id]).fetchall()
    if not rows:
        raise ForecastError(f"team {team_id} has no roster in the latest snapshot -- run `fantaclaude ingest rosters`")
    return [RosterPlayer(int(pid), str(name) if name is not None else f"#{pid}",
                         frozenset(Role(r) for r in (roles or [])), int(cost), name is not None)
            for pid, cost, name, roles in rows]


@dataclass(frozen=True)
class XiSlot:
    slot: str
    player_id: int
    name: str
    fit: str
    expected_points: float

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "player_id": self.player_id, "name": self.name, "fit": self.fit,
                "expected_points": self.expected_points}


@dataclass(frozen=True)
class XiChoice:
    module: str
    total: float
    slots: list[XiSlot]
    module_scores: dict[str, float | None]
    unlisted: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "total": self.total, "slots": [s.to_dict() for s in self.slots],
                "module_scores": dict(self.module_scores), "unlisted": list(self.unlisted)}


def choose_xi(roster: list[RosterPlayer], forecast_by_id: dict[int, ForecastRow], modules: dict[str, Module],
              allowed: Sequence[str]) -> XiChoice:
    """One exact solve per permitted module; the best total wins. A roster
    player not in `forecast_by_id` -- the page does not list him, or the run
    never priced him -- is worth zero this week and is named (the caller
    tells the two reasons apart; `forecast_by_id` alone cannot)."""
    natural: list[float] = []
    adapted: list[float] = []
    for p in roster:
        row = forecast_by_id.get(p.player_id)
        points = row.expected_points if row else 0.0
        natural.append(points)
        adapted.append(points - (row.p_start * ADAPTED_MALUS if row else 0.0))
    roles = [p.roles for p in roster]
    scores: dict[str, float | None] = {}
    best: tuple[str, float, list[int]] | None = None
    for code in allowed:
        module = modules.get(str(code))
        if module is None:
            raise ForecastError(f"the league permits module {code!r}, which is not in modules.yml")
        solved = assign_weighted(module, roles, natural, adapted)
        scores[str(code)] = None if solved is None else solved[0]
        if solved is not None and (best is None or solved[0] > best[1]):
            best = (str(code), solved[0], solved[1])
    if best is None:
        raise ForecastError("no permitted module can be fielded from this roster")
    code, total, chosen = best
    slots = []
    for k, i in enumerate(chosen):
        fit = modules[code].slots[k].fit(roster[i].roles)
        points = natural[i] if fit.value == "natural" else adapted[i]
        slots.append(XiSlot(modules[code].slots[k].label, roster[i].player_id, roster[i].name, fit.value, points))
    unlisted = [p.player_id for p in roster if p.player_id not in forecast_by_id]
    return XiChoice(code, total, slots, scores, unlisted)


MATCHDAY_READ_WINDOW = timedelta(days=5)


def matchday_cross_check(con: duckdb.DuckDBPyConnection, round_: Round) -> str | None:
    """A warning when the freshest roster snapshot's mday/mstr disagree with
    the calendar's round; None when they agree, nothing has been fetched, or
    the snapshot has nothing current to say.

    `ingest rosters` runs "when the rosters changed, never to check"
    (CLAUDE.md), so the freshest snapshot can sit unchanged for weeks --
    without a recency bound, a matchday-3 read from the day after the
    auction would forever be compared against giornata 7's calendar, and the
    (backwards) advice to pass --giornata would fire on every `lineup` run
    from giornata 4 onward, drowning the real warnings beside it (review
    finding 4, 2026-09-04). So the read is compared only when it is recent
    enough, relative to THIS round's kickoff, to plausibly still describe
    it -- `fetched_at` no more than `MATCHDAY_READ_WINDOW` before
    `round_.first_kickoff` (a read fetched at or after kickoff is always
    compared, however "stale" it looks by this measure)."""
    row = con.execute("SELECT matchday, matchday_start, fetched_at FROM roster_snapshots "
                      "WHERE matchday IS NOT NULL ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    matchday, start, fetched_at = row
    if round_.first_kickoff - fetched_at > MATCHDAY_READ_WINDOW:
        return None
    if int(matchday) == round_.giornata and (start is None or start == round_.first_kickoff):
        return None
    return (f"the league API's status read on {fetched_at:%Y-%m-%d %H:%M} UTC said matchday {matchday} starting "
            f"{start}; the calendar says giornata {round_.giornata} at {round_.first_kickoff} -- if the platform is "
            f"fresher, pass --giornata")


STALE_COMPILATION = timedelta(days=1)


def compilation_staleness(con: duckdb.DuckDBPyConnection, giornata: int,
                          probabili_file_id: int) -> list[str]:
    """Warnings, one per match, when that match's OWN probabili compilation
    stamp predates that match's OWN kickoff by more than a day (spec: "the
    lineup command warns when a match's compilation predates its own
    kickoff by more than a day, instead of treating Tuesday's guess as
    Saturday's team news").

    No `season_id` parameter: the query is already fully scoped by
    `p.file_id = ?` (one probabili page, one season, one giornata) and the
    `f.season_id = p.season_id` join carries the season across to
    `fixtures` -- a `season_id` argument here would be redundant with
    `probabili_file_id` and, worse, invite a reader to assume it does some
    scoping the query does not actually use it for (review finding 13,
    2026-09-04).

    The join to `fixtures` is on `team_short`, not `club_slug`: the
    fantacalcio.it URL slug `club_slug` carries (e.g. "inter") has no
    established mapping anywhere in this codebase to the listone short code
    `fixtures.home_short`/`away_short` use, and inventing one here would be
    exactly the kind of club fact CLAUDE.md says must never come from
    memory. `team_short` needs no such mapping: `ingest probabili` already
    resolves it per row from the listone by `player_id` (the reliable join
    the page gives for free), the same listone `resolve_team` fills
    `fixtures.home_short`/`away_short` from at calendar ingest -- so the two
    columns already speak the same short code. A match with no listone-known
    player on the page (an unmapped `player_id`, `team_short IS NULL` for
    both its clubs) is not checked; that is the honest limit of this join,
    not a fallback to the round's first kickoff."""
    rows = con.execute(
        "SELECT f.home_short, f.away_short, f.kickoff, min(p.updated_at) FROM probabili p "
        "JOIN v_fixtures_current f ON f.competition = 'SA' AND f.season_id = p.season_id AND f.giornata = p.giornata "
        "AND (f.home_short = p.team_short OR f.away_short = p.team_short) "
        "WHERE p.file_id = ? AND p.updated_at IS NOT NULL AND f.kickoff IS NOT NULL "
        "GROUP BY f.home_short, f.away_short, f.kickoff", [probabili_file_id]).fetchall()
    warnings = []
    for home, away, kickoff, updated_at in rows:
        age = kickoff - updated_at
        if age > STALE_COMPILATION:
            warnings.append(f"{home}-{away} (giornata {giornata}): probabili compiled {updated_at:%Y-%m-%d %H:%M} UTC, "
                            f"{age.days} day(s) before its own kickoff {kickoff:%Y-%m-%d %H:%M} UTC -- treat its p_start as stale")
    return sorted(warnings)


def uncompiled_match_warning(giornata: int, uncompiled: int, fetched_at: str) -> str:
    """The one sentence for "N matches of this giornata are not yet
    compiled", shared with the CLI's plain-text renderer so the two can
    never fall out of sync. `_render_lineup` used to find this specific
    entry in `warnings` by substring-matching a fragment of THIS sentence
    hardcoded a second time in `cli/app.py` -- reword it here and the
    renderer's match silently stops firing: the UNCOMPILED line vanishes
    from its near-header position while the same warning reappears,
    undeduplicated, at the bottom (review finding 10, 2026-09-04). Calling
    this one function from both places instead means a reword changes both
    at once, by construction, and the renderer can select the entry by
    exact equality against what it independently builds from
    `page['uncompiled']`/`page['fetched_at']`, never by parsing prose."""
    return f"{uncompiled} match(es) of giornata {giornata} not yet compiled on the page fetched {fetched_at} UTC"


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
    file_id, fetched_at, players, matches, uncompiled = page
    fetched_at_str = fetched_at.isoformat(sep=" ", timespec="minutes")
    rows = forecast(con, run_id=run_id, probabili_file_id=file_id)
    warnings: list[str] = []
    if (mismatch := matchday_cross_check(con, round_)):
        warnings.append(mismatch)
    if uncompiled:
        warnings.append(uncompiled_match_warning(round_.giornata, uncompiled, fetched_at_str))
    warnings += compilation_staleness(con, round_.giornata, file_id)
    xi, no_xi_reason, module, xi_rows, scores = None, None, None, None, None
    if my_team is None:
        no_xi_reason = "league.yml has no my_team leaf (asta verify-transfer prints it)"
    else:
        try:
            roster = my_roster(con, my_team)
            allowed_row = con.execute("SELECT modules FROM v_league_settings_current").fetchone()
            if allowed_row is None or not allowed_row[0]:
                raise ForecastError("no league_settings snapshot names the permitted modules -- run `fantaclaude sync-league`")
            choice = choose_xi(roster, {r.player_id: r for r in rows}, load_modules(), list(allowed_row[0]))
            xi, module, scores = choice.to_dict(), choice.module, choice.module_scores
            xi_rows = [s.to_dict() for s in choice.slots]
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
    lineup_run_id, is_late = write_lineup_run(con, round_=round_, run_id=run_id, model_hash=str(hashed[0]),
                                              probabili_file_id=file_id, rows=rows, now=now, late=late, my_team=my_team,
                                              module=module, xi=xi_rows, module_scores=scores)
    records = export_lineup_records(con, lineup_run_id, records_dir)
    return LineupReport(round_, run_id, str(hashed[0]),
                        {"file_id": file_id, "fetched_at": fetched_at_str,
                         "players": players, "matches": matches, "uncompiled": int(uncompiled)},
                        is_late, rows, xi, no_xi_reason, my_team, lineup_run_id, records, warnings)
