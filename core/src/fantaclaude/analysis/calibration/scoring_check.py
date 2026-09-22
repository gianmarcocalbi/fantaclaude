"""The platform's scores checked against the voti (spec, "Calibration: what 3c
ships").

Every recorded `match_scores` row is a check of the voto source and of the
bonus/malus table at once: its status against the league's sheet (absent, a
senza voto, a voto), its voto against the sheet's, its fantavoto against
`scoring.fantavoto` less one point per malus. A disagreement means a wrong
voto source or bonus table -- every projection's, not only calibration's --
so `doctor` fails on one. Rows of a giornata whose voti are not ingested yet
are skipped and counted, never read as "absent".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from fantaclaude.analysis.history import EVENT_COLUMNS
from fantaclaude.analysis.weekly.xi import ADAPTED_MALUS
from fantaclaude.model.scoring import BonusMalus, Events, fantavoto

TOLERANCE = 1e-9


@dataclass(frozen=True)
class Disagreement:
    season_id: int
    giornata: int
    team_id: int
    player_id: int
    field: str                      # status | voto | fantavoto
    platform: Any
    ours: Any

    def describe(self) -> str:
        return (f"giornata {self.giornata}, player {self.player_id} (team {self.team_id}): {self.field} "
                f"platform {self.platform!r}, ours {self.ours!r}")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "describe": self.describe()}


@dataclass(frozen=True)
class ScoringCheck:
    checked: int
    skipped: int
    disagreements: list[Disagreement]

    @property
    def ok(self) -> bool:
        return not self.disagreements

    def to_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "skipped": self.skipped, "ok": self.ok,
                "disagreements": [d.to_dict() for d in self.disagreements]}


def check_scoring(con: duckdb.DuckDBPyConnection, *, sheet: str, bm: BonusMalus, season_id: int | None = None,
                  giornate: Sequence[int] | None = None) -> ScoringCheck:
    where, params = ["true"], []
    if season_id is not None:
        where.append("s.season_id = ?")
        params.append(season_id)
    if giornate is not None:
        where.append("s.giornata = ANY(?)")
        params.append(list(giornate))
    rows = con.execute(
        "SELECT s.season_id, s.giornata, s.team_id, s.player_id, s.status, s.voto, s.fantavoto, s.malus, "
        "EXISTS (SELECT 1 FROM v_voti_files_current f WHERE f.season_id = s.season_id AND f.giornata = s.giornata), "
        "m.voto, m.senza_voto, " + ", ".join(f"m.{c}" for c in EVENT_COLUMNS) +
        " FROM v_match_scores_current s LEFT JOIN v_player_match_current m ON m.season_id = s.season_id "
        "AND m.giornata = s.giornata AND m.player_id = s.player_id AND m.sheet = ? "
        "WHERE " + " AND ".join(where) + " ORDER BY s.season_id, s.giornata, s.team_id, s.part, s.position",
        [sheet, *params]).fetchall()
    checked = skipped = 0
    found: list[Disagreement] = []
    for season, giornata, team, pid, status, voto, value, malus, rated, sheet_voto, senza, *events in rows:
        if not rated:
            skipped += 1
            continue
        checked += 1
        key = (int(season), int(giornata), int(team), int(pid))
        ours_status = "absent" if senza is None else ("sv" if senza or sheet_voto is None else "voto")
        if ours_status != status:
            found.append(Disagreement(*key, "status", status, ours_status))
            continue
        if status != "voto":
            continue
        if abs(float(sheet_voto) - voto) > TOLERANCE:
            found.append(Disagreement(*key, "voto", voto, float(sheet_voto)))
            continue
        ours = fantavoto(float(sheet_voto), Events(*(float(e or 0) for e in events)), bm) - malus * ADAPTED_MALUS
        if abs(ours - value) > TOLERANCE:
            found.append(Disagreement(*key, "fantavoto", value, ours))
    return ScoringCheck(checked, skipped, found)
