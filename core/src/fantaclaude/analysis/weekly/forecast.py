"""The forecast rows: every player the page lists and the run prices (spec,
"Predictions are written for every player the page lists and the run prices
-- not for my roster")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.rounds import PlayerFixture


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

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short,
                "classic_role": self.classic_role, "roles": list(self.roles),
                "p_start_published": self.p_start_published, "p_start": self.p_start,
                "fv_if_plays": self.fv_if_plays, "fv_sd": self.fv_sd, "expected_points": self.expected_points,
                "source": self.source,
                "kickoff": None if self.kickoff is None else self.kickoff.isoformat(sep=" ", timespec="minutes")}


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
             fixtures: dict[int, PlayerFixture] | None = None) -> list[ForecastRow]:
    """Every player the page lists and the run prices. p_start is the
    published number alone until Task 7 (`source: published`), fv_sd is null."""
    fixtures = fixtures or {}
    rows = con.execute(
        "SELECT v.player_id, v.name, v.team_short, v.classic_role, v.roles, v.exp_fantamedia, p.p_start "
        "FROM valuations v JOIN probabili p ON p.player_id = v.player_id "
        "WHERE v.run_id = ? AND p.file_id = ? ORDER BY v.player_id", [run_id, probabili_file_id]).fetchall()
    out: list[ForecastRow] = []
    for pid, name, short, role, roles, fm, published in rows:
        p_start = int(published) / 100.0
        fixture = fixtures.get(int(pid))
        out.append(ForecastRow(int(pid), str(name), short, str(role), tuple(roles), int(published), p_start,
                               float(fm), None, p_start * float(fm), "published",
                               kickoff=None if fixture is None else fixture.kickoff))
    return out
