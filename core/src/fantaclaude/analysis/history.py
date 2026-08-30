"""The observed layer, read once per run and scored under the league's rules.

player_match holds the base voto and the event counts (spec, "Fantavoto is
computed, never stored"); the fantavoto of every row is computed here with
the BonusMalus in force, so a rule change reaches every projection and the
priors alike. One sheet -- the voto source the league scores with. Coach
rows (classic_role 'ALL') are not players and are dropped. Understat's
minutes and xG/xA are joined by season and listone id from v_advanced_current
(matched rows only). Role priors and the clubs' penalty rates come from the
back seasons only: the current season's handful of giornate is a signal for
the player, not a population.

Observed 2026-08-29, season 20, sheet Fantacalcio, players only, under this
league's bonus/malus -- role_priors's shape: P 6.17/0.55 voto, 5.03/1.54
fantavoto; D 5.93/0.58, 6.00/1.07; C 5.99/0.58, 6.23/1.37; A 5.99/0.69,
6.58/1.96 (mean/sd; the fantavoto figures include penalty-goal points via
bmpsc). Quoted so a reviewer can tell a plausible prior from a bug; never
hardcoded here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, fields
from statistics import fmean, pvariance

import duckdb

from fantaclaude.model.scoring import BonusMalus, Events, fantavoto
from fantaclaude.model.seasons import back_seasons

COACH_ROLE = "ALL"
EVENT_COLUMNS = tuple(f.name for f in fields(Events))


@dataclass(frozen=True)
class SeasonLine:
    season_id: int
    team: str
    classic_role: str
    appearances: int
    presenze: int
    giornate: int
    voto_mean: float
    events: Events
    fantavoto_mean: float
    fantavoto_var: float
    minutes: int | None
    xg: float | None
    xa: float | None
    npxg: float | None
    understat_games: int | None


@dataclass(frozen=True)
class RolePrior:
    classic_role: str
    fantavoto_mean: float
    fantavoto_sd: float
    voto_mean: float
    presenze_rate: float
    rows: int


@dataclass(frozen=True)
class History:
    sheet: str
    current_season: int
    seasons: tuple[int, ...]
    giornate: dict[int, int]
    lines: dict[int, tuple[SeasonLine, ...]] = field(default_factory=dict)
    priors: dict[str, RolePrior] = field(default_factory=dict)
    club_penalty_rate: dict[str, float] = field(default_factory=dict)
    # Every club the rate's season named, those that took no penalty included.
    # club_penalty_rate cannot answer that on its own -- it drops the zeroes --
    # and the caller has to tell "this club took none" from "this club is
    # spelled differently here than in the listone, so the lookup misses and
    # every penalty silently becomes zero" (finding 12).
    penalty_rate_clubs: frozenset[str] = frozenset()

    def lines_for(self, player_id: int) -> tuple[SeasonLine, ...]:
        return self.lines.get(player_id, ())

    def penalty_rate(self, team: str) -> float | None:
        """The club's penalties per giornata, or None when the season the rate
        is read off never named the club -- absent, not zero. The two are
        different facts and the projection treats them differently (finding
        A): a club that played and took none is a real 0.0, a club promoted
        into this season has no observation at all."""
        if team not in self.penalty_rate_clubs:
            return None
        return self.club_penalty_rate.get(team, 0.0)

    @property
    def giornate_played(self) -> int:
        return self.giornate.get(self.current_season, 0)


def load_history(con: duckdb.DuckDBPyConnection, *, sheet: str, bm: BonusMalus, current_season: int,
                  back: int = 3) -> History:
    seasons = (*back_seasons(current_season, back), current_season)
    giornate = {int(s): int(n) for s, n in con.execute(
        "SELECT season_id, count(DISTINCT giornata) FROM v_voti_files_current WHERE season_id = ANY(?) GROUP BY 1",
        [list(seasons)]).fetchall()}
    advanced = {(int(s), int(p)): (int(m), int(g), float(xg), float(xa), float(npxg))
                for s, p, m, g, xg, xa, npxg in con.execute(
                    "SELECT season_id, player_id, sum(minutes), sum(games), sum(xg), sum(xa), sum(npxg) "
                    "FROM v_advanced_current WHERE player_id IS NOT NULL AND season_id = ANY(?) GROUP BY 1, 2",
                    [list(seasons)]).fetchall()}
    rows = con.execute(
        "SELECT season_id, giornata, player_id, team, classic_role, voto, senza_voto, "
        + ", ".join(EVENT_COLUMNS) + " FROM v_player_match_current WHERE sheet = ? AND classic_role <> ? "
        "AND season_id = ANY(?) ORDER BY season_id, player_id, giornata",
        [sheet, COACH_ROLE, list(seasons)]).fetchall()

    per_player_season: dict[tuple[int, int], dict] = {}
    role_rows: dict[str, list[tuple[float, float]]] = defaultdict(list)          # role -> (voto, fantavoto), back seasons
    role_presenze: dict[str, list[tuple[int, int]]] = defaultdict(list)          # role -> (presenze, giornate) per player-season
    club_penalties: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for season_id, giornata, player_id, team, role, voto, senza_voto, *counts in rows:
        events = Events(**{name: float(value) for name, value in zip(EVENT_COLUMNS, counts)})
        acc = per_player_season.setdefault((int(season_id), int(player_id)), {
            "team": team, "role": role, "appearances": 0, "presenze": 0, "votes": [], "fantavoti": [], "events": Events()})
        acc["team"], acc["role"] = team, role                    # the last giornata's club and role
        acc["appearances"] += 1
        acc["events"] = acc["events"] + events
        club_penalties[int(season_id)][team] += int(events.pen_scored + events.pen_missed)
        if senza_voto or voto is None:
            continue
        fv = fantavoto(float(voto), events, bm)
        acc["presenze"] += 1
        acc["votes"].append(float(voto))
        acc["fantavoti"].append(fv)
        if int(season_id) != current_season:
            role_rows[role].append((float(voto), fv))

    lines: dict[int, list[SeasonLine]] = defaultdict(list)
    for (season_id, player_id), acc in sorted(per_player_season.items(), key=lambda item: (-item[0][0], item[0][1])):
        adv = advanced.get((season_id, player_id))
        line = SeasonLine(
            season_id=season_id, team=acc["team"], classic_role=acc["role"], appearances=acc["appearances"],
            presenze=acc["presenze"], giornate=giornate.get(season_id, 0),
            voto_mean=fmean(acc["votes"]) if acc["votes"] else 0.0, events=acc["events"],
            fantavoto_mean=fmean(acc["fantavoti"]) if acc["fantavoti"] else 0.0,
            fantavoto_var=pvariance(acc["fantavoti"]) if len(acc["fantavoti"]) > 1 else 0.0,
            minutes=adv[0] if adv else None, understat_games=adv[1] if adv else None,
            xg=adv[2] if adv else None, xa=adv[3] if adv else None, npxg=adv[4] if adv else None)
        lines[player_id].append(line)
        if season_id != current_season and line.giornate:
            role_presenze[acc["role"]].append((line.presenze, line.giornate))

    priors: dict[str, RolePrior] = {}
    for role, pairs in role_rows.items():
        votes = [v for v, _ in pairs]
        fvs = [fv for _, fv in pairs]
        rates = [p / g for p, g in role_presenze.get(role, []) if g]
        priors[role] = RolePrior(role, fmean(fvs), pvariance(fvs) ** 0.5 if len(fvs) > 1 else 0.0, fmean(votes),
                                  fmean(rates) if rates else 0.0, len(pairs))

    last_back = max((s for s in seasons if s != current_season and s in giornate), default=None)
    rated = last_back is not None and bool(giornate.get(last_back))
    club_rate = {team: n / giornate[last_back] for team, n in club_penalties[last_back].items() if n} if rated else {}
    rate_clubs = frozenset(club_penalties[last_back]) if rated else frozenset()
    return History(sheet=sheet, current_season=current_season, seasons=seasons, giornate=giornate,
                    lines={pid: tuple(ls) for pid, ls in lines.items()}, priors=priors, club_penalty_rate=club_rate,
                    penalty_rate_clubs=rate_clubs)
