"""fantaclaude sync-league: refresh league_settings from the league API.

Importable on purpose -- the CLI and, later, the FastAPI server call this
function; the CLI adds only argument parsing and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.league.league_yml import Conflict, Provenanced, cross_check
from fantaclaude.league.settings import (
    Change,
    LeagueSnapshot,
    record_snapshot,
    snapshot_from_payloads,
)


@dataclass(frozen=True)
class SyncReport:
    league_id: int
    season_id: int | None
    team_count: int | None
    rules_hash: str
    changed: bool
    snapshot_id: int | None
    previous_hash: str | None
    diff: list[Change] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "league_id": self.league_id, "season_id": self.season_id,
            "team_count": self.team_count, "rules_hash": self.rules_hash,
            "changed": self.changed, "snapshot_id": self.snapshot_id,
            "previous_hash": self.previous_hash,
            "diff": [{"path": c.path, "before": c.before, "after": c.after} for c in self.diff],
            "conflicts": [{"key": c.key, "league_yml": c.league_yml, "api": c.api}
                          for c in self.conflicts],
        }


async def fetch_snapshot(api: FantacalcioAPI, *, league: str | None = None) -> LeagueSnapshot:
    # Sequential on purpose: six reads against a real account, one at a time.
    profile = await api.league_profile(league=league)
    status = await api.league_status(league=league)
    rosters = await api.roster_settings(league=league)
    lineup = await api.lineup_settings(league=league)
    calculate = await api.calculation_settings(league=league)
    teams = await api.teams(page=1, league=league)
    return snapshot_from_payloads(profile=profile, status=status, rosters=rosters,
                                  lineup=lineup, calculate=calculate, teams=teams)


async def sync_league(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection,
                      league_yml: dict[str, Provenanced] | None, *,
                      league: str | None = None,
                      fetched_at: datetime | None = None) -> SyncReport:
    """Fetch the rules, refuse loudly if league.yml disagrees with them,
    otherwise append a snapshot when the rules hash moved."""
    snap = await fetch_snapshot(api, league=league)
    conflicts = cross_check(league_yml, snap) if league_yml else []
    if conflicts:
        return SyncReport(snap.league_id, snap.season_id, snap.team_count, snap.rules_hash,
                          changed=False, snapshot_id=None, previous_hash=None,
                          conflicts=conflicts)
    result = record_snapshot(con, snap, fetched_at=fetched_at)
    return SyncReport(snap.league_id, snap.season_id, snap.team_count, snap.rules_hash,
                      changed=result.changed, snapshot_id=result.snapshot_id,
                      previous_hash=result.previous_hash, diff=result.diff)
