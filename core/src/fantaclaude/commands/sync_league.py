"""fantaclaude sync-league: refresh league_settings from the league API.

Importable on purpose -- the CLI and, later, the FastAPI server call this
function; the CLI adds only argument parsing and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    superseded_runs: int = 0
    conflicts: list[Conflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "league_id": self.league_id, "season_id": self.season_id,
            "team_count": self.team_count, "rules_hash": self.rules_hash,
            "changed": self.changed, "snapshot_id": self.snapshot_id,
            "previous_hash": self.previous_hash,
            "diff": [{"path": c.path, "before": c.before, "after": c.after} for c in self.diff],
            "superseded_runs": self.superseded_runs,
            "conflicts": [{"key": c.key, "league_yml": c.league_yml, "api": c.api}
                          for c in self.conflicts],
            "warnings": list(self.warnings),
        }


# The endpoint pages by ten and a league can outgrow one page; the loop is
# bounded so a server that always answers `nextPage: true` cannot spin it.
MAX_TEAM_PAGES = 20


async def fetch_teams(api: FantacalcioAPI, *, league: str | None = None) -> tuple[Any, list[str]]:
    """Every page of the team list, folded into the first page's envelope,
    and a warning when the pages do not add up to the division's own count.

    Spec open question 12 (found 2026-09-02): page 1 alone carried ten of
    twelve teams and `divisions[A].count = 12`, and the two that fell off
    were the newest -- exactly the manager who joined before an auction.
    """
    first = await api.teams(page=1, league=league)
    if not isinstance(first, dict) or not isinstance(first.get("data"), list):
        return first, []
    rows = list(first["data"])
    page = 1
    while first.get("nextPage") and page < MAX_TEAM_PAGES:
        page += 1
        more = await api.teams(page=page, league=league)
        chunk = more.get("data") if isinstance(more, dict) else None
        if not isinstance(chunk, list) or not chunk:
            break
        rows.extend(chunk)
        if not more.get("nextPage"):
            break
    warnings: list[str] = []
    counted = sum(int(d.get("count") or 0) for d in (first.get("divisions") or []) if isinstance(d, dict))
    if counted and counted != len(rows):
        warnings.append(f"the team list carries {len(rows)} teams over {page} page(s) but the divisions count {counted}; "
                        f"the snapshot's team list is not complete")
    return {**first, "data": rows, "page": 1, "nextPage": False, "pages": page, "item": len(rows)}, warnings


async def fetch_snapshot(api: FantacalcioAPI, *, league: str | None = None) -> LeagueSnapshot:
    # Sequential on purpose: six reads against a real account, one at a time
    # (the team list may take one more per page beyond the first).
    profile = await api.league_profile(league=league)
    status = await api.league_status(league=league)
    rosters = await api.roster_settings(league=league)
    lineup = await api.lineup_settings(league=league)
    calculate = await api.calculation_settings(league=league)
    teams, warnings = await fetch_teams(api, league=league)
    snap = snapshot_from_payloads(profile=profile, status=status, rosters=rosters,
                                  lineup=lineup, calculate=calculate, teams=teams)
    return replace(snap, warnings=tuple(warnings)) if warnings else snap


async def prepare_sync(api: FantacalcioAPI, league_yml: dict[str, Provenanced] | None, *,
                       league: str | None = None) -> tuple[LeagueSnapshot, list[Conflict]]:
    """Everything that needs the network and nothing that needs the database.

    Split out so a caller can hold the database open only for the write. The
    fetch is six round-trips plus a possible login; DuckDB is single-writer, so
    opening before this runs locks the file for the whole of it -- and creates
    it, which makes an empty database indistinguishable from an unbuilt one.
    """
    snap = await fetch_snapshot(api, league=league)
    return snap, (cross_check(league_yml, snap) if league_yml else [])


def apply_sync(con: duckdb.DuckDBPyConnection | None, snap: LeagueSnapshot,
               conflicts: list[Conflict], *,
               fetched_at: datetime | None = None) -> SyncReport:
    """Record the snapshot, or report the conflict without touching the row.

    `con` may be None when conflicts are present: a refusal records nothing, so
    the caller need not have opened the database at all.
    """
    if conflicts:
        return SyncReport(snap.league_id, snap.season_id, snap.team_count, snap.rules_hash,
                          changed=False, snapshot_id=None, previous_hash=None,
                          conflicts=conflicts, warnings=list(snap.warnings))
    result = record_snapshot(con, snap, fetched_at=fetched_at)
    superseded = 0
    if result.changed and result.previous_hash is not None:
        # The runs *this* change supersedes: the ones stamped with the rules
        # hash that was current until a moment ago. Counting every run whose
        # hash is not the new one (finding 8) also counted the runs a previous
        # rules change had already superseded, so the second change reported
        # two, the third three -- a number that only ever grows and stops
        # describing what just happened. One rules change is the case where the
        # two agree, which is why the original test never saw it.
        superseded = con.execute("SELECT count(*) FROM valuation_runs WHERE rules_hash = ?",
                                 [result.previous_hash]).fetchone()[0]
    return SyncReport(snap.league_id, snap.season_id, snap.team_count, snap.rules_hash,
                      changed=result.changed, snapshot_id=result.snapshot_id,
                      previous_hash=result.previous_hash, diff=result.diff, superseded_runs=int(superseded),
                      warnings=list(snap.warnings))


async def sync_league(api: FantacalcioAPI, con: duckdb.DuckDBPyConnection,
                      league_yml: dict[str, Provenanced] | None, *,
                      league: str | None = None,
                      fetched_at: datetime | None = None) -> SyncReport:
    """Fetch the rules, refuse loudly if league.yml disagrees with them,
    otherwise append a snapshot when the rules hash moved.

    For a caller that already owns a connection. The CLI composes
    prepare_sync/apply_sync instead, so it opens the database only once there
    is something to write.
    """
    snap, conflicts = await prepare_sync(api, league_yml, league=league)
    return apply_sync(con, snap, conflicts, fetched_at=fetched_at)
