"""What happened, joined to what was predicted (spec, "Calibration: what 3c
ships").

An actual is one row of the league's own voti sheet, scored under the
bonus/malus in force -- `history`'s rule, "fantavoto is computed, never
stored". A player absent from the sheet got no voto; so did a senza voto.
The predictions are `v_predictions_current`: per player, the newest row that
was not late for him, so a forecast written after its kickoff is never read.
A prediction without an actual is scored as a no-show only when his club has
voti that giornata: a club with none did not play (a postponed match), and
its rows are dropped and counted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import duckdb

from fantaclaude.analysis.history import COACH_ROLE, EVENT_COLUMNS
from fantaclaude.model.scoring import BonusMalus, Events, fantavoto


@dataclass(frozen=True)
class Actual:
    giornata: int
    player_id: int
    team: str
    classic_role: str
    voto: float | None               # None: senza voto
    fantavoto: float | None

    @property
    def voted(self) -> bool:
        return self.voto is not None


@dataclass(frozen=True)
class Scored:
    giornata: int
    player_id: int
    name: str
    club: str | None
    lineup_run_id: int
    model_hash: str
    weekly_hash: str | None
    p_start_published: int | None
    p_start: float
    fv_if_plays: float
    fv_sd: float | None
    actual: Actual | None            # None: absent from the voti sheet

    @property
    def voted(self) -> bool:
        return self.actual is not None and self.actual.voted

    @property
    def error(self) -> float | None:
        """Actual fantavoto minus the predicted one, when he got a voto."""
        return self.actual.fantavoto - self.fv_if_plays if self.voted else None


def load_actuals(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int], sheet: str,
                 bm: BonusMalus) -> dict[tuple[int, int], Actual]:
    rows = con.execute(
        "SELECT giornata, player_id, team, classic_role, voto, senza_voto, " + ", ".join(EVENT_COLUMNS) +
        " FROM v_player_match_current WHERE season_id = ? AND sheet = ? AND giornata = ANY(?) "
        "AND player_id IS NOT NULL AND classic_role <> ?",
        [season_id, sheet, list(giornate), COACH_ROLE]).fetchall()
    actuals: dict[tuple[int, int], Actual] = {}
    for giornata, pid, team, role, voto, senza, *events in rows:
        scored = None if senza or voto is None else float(voto)
        value = None if scored is None else fantavoto(scored, Events(*(float(e or 0) for e in events)), bm)
        actuals[(int(giornata), int(pid))] = Actual(int(giornata), int(pid), str(team), str(role), scored, value)
    return actuals


def clubs_with_voti(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int],
                    sheet: str) -> dict[int, frozenset[str]]:
    rows = con.execute(
        "SELECT giornata, list(DISTINCT team) FROM v_player_match_current "
        "WHERE season_id = ? AND sheet = ? AND giornata = ANY(?) GROUP BY giornata",
        [season_id, sheet, list(giornate)]).fetchall()
    return {int(giornata): frozenset(teams) for giornata, teams in rows}


def load_scored(con: duckdb.DuckDBPyConnection, *, season_id: int, giornate: Sequence[int],
                actuals: dict[tuple[int, int], Actual],
                clubs: dict[int, frozenset[str]]) -> tuple[list[Scored], int]:
    rows = con.execute(
        "SELECT p.giornata, p.player_id, pl.name, pl.team_name, p.lineup_run_id, l.model_hash, l.weekly_hash, "
        "p.p_start_published, p.p_start, p.fv_if_plays, p.fv_sd "
        "FROM v_predictions_current p JOIN lineup_runs l ON l.lineup_run_id = p.lineup_run_id "
        "LEFT JOIN v_players_current pl ON pl.player_id = p.player_id "
        "WHERE p.season_id = ? AND p.giornata = ANY(?) ORDER BY p.giornata, p.player_id",
        [season_id, list(giornate)]).fetchall()
    scored: list[Scored] = []
    dropped = 0
    for giornata, pid, name, club, run, model, weekly, published, p_start, fv, fv_sd in rows:
        actual = actuals.get((int(giornata), int(pid)))
        if actual is None and (club is None or club not in clubs.get(int(giornata), frozenset())):
            dropped += 1
            continue
        scored.append(Scored(int(giornata), int(pid), str(name) if name is not None else f"#{pid}", club, int(run),
                             str(model), weekly, None if published is None else int(published), float(p_start),
                             float(fv), None if fv_sd is None else float(fv_sd), actual))
    return scored, dropped
