"""Rosters and purchase costs off the lega's team objects (spec, open question 9).

After the admin transfers the auction, every team object from
`/onboarding/v1/league/teams` carries `cal` -- the owned player ids,
semicolon-separated -- and `cs`, the price paid for each in the same order,
summing to `crs`. Before the transfer both are empty strings, which is an
empty roster and not an error. An id the listone never carried (795 on
2026-09-04) is kept: this is the lega's roster, not ours. The status read
rides along so every snapshot carries the platform's own `mday`/`mstr`,
which `league_settings` only refreshes on a rules change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from fantaclaude.ingest.raw import RawFile
from fantaclaude.timeutil import to_db

SOURCE = "apileague:GET /onboarding/v1/league/teams (cal/cs) + /league/status"


class RosterShapeError(ValueError):
    """The team objects do not carry rosters the way this adapter was written against."""


@dataclass(frozen=True)
class RosterRow:
    team_id: int
    team_name: str
    owner: str | None
    player_id: int
    cost: int
    position: int


def _split(value: Any, *, what: str, team: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        raise RosterShapeError(f"team {team!r}: {what} is {type(value).__name__}, expected a ';'-separated string")
    return [part.strip() for part in value.split(";") if part.strip()]


def parse_rosters(teams_payload: Any) -> tuple[list[RosterRow], list[str]]:
    data = teams_payload.get("data") if isinstance(teams_payload, dict) else None
    if not isinstance(data, list):
        raise RosterShapeError("the teams payload has no data list")
    rows: list[RosterRow] = []
    warnings: list[str] = []
    for team in data:
        name = str(team.get("n", ""))
        ids = _split(team.get("cal"), what="cal", team=name)
        costs = _split(team.get("cs"), what="cs", team=name)
        if len(ids) != len(costs):
            raise RosterShapeError(f"team {name!r}: {len(ids)} ids in cal but {len(costs)} prices in cs")
        total = 0
        for position, (pid, cost) in enumerate(zip(ids, costs)):
            try:
                player_id, credits = int(pid), int(cost)
            except ValueError:
                raise RosterShapeError(f"team {name!r}: cal/cs entry {pid!r}/{cost!r} is not an integer") from None
            total += credits
            rows.append(RosterRow(int(team["id"]), name, team.get("nu"), player_id, credits, position))
        crs = team.get("crs")
        if ids and isinstance(crs, int) and crs != total:
            warnings.append(f"team {name!r}: cs sums to {total} but crs says {crs}")
    return rows, warnings


def _matchday_start(value: Any) -> datetime | None:
    """`mstr` is an ISO instant without a zone and it is UTC (giornata 1:
    2026-08-22T16:30:00 against an 18:30 Rome kickoff)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


@dataclass(frozen=True)
class RosterIngestResult:
    snapshot_id: int
    league_id: int
    season_id: int | None
    matchday: int | None
    matchday_start: str | None
    teams: int
    inserted: int
    skipped_duplicate: bool
    warnings: list[str]
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "league_id": self.league_id, "season_id": self.season_id,
                "matchday": self.matchday, "matchday_start": self.matchday_start, "teams": self.teams,
                "inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate,
                "warnings": list(self.warnings), "sha256": self.sha256, "raw_path": self.raw_path}


def record_rosters(con: duckdb.DuckDBPyConnection, payload: dict[str, Any], raw: RawFile, *,
                   league_id: int) -> RosterIngestResult:
    """Append one snapshot and its rows; the same bytes for the same league is a no-op."""
    rows, warnings = parse_rosters(payload.get("teams"))
    warnings = [*payload.get("fetch_warnings", []), *warnings]
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    season_id = status.get("sId") if isinstance(status.get("sId"), int) else None
    matchday = status.get("mday") if isinstance(status.get("mday"), int) else None
    start = _matchday_start(status.get("mstr"))
    sizes: dict[int, int] = {}
    for r in rows:
        sizes[r.team_id] = sizes.get(r.team_id, 0) + 1
    team_list = [{"id": int(t["id"]), "name": str(t.get("n", "")), "owner": t.get("nu"), "size": sizes.get(int(t["id"]), 0)}
                 for t in payload["teams"]["data"]]           # every team, the empty ones included: rosters has no row for those
    teams = len(team_list)
    existing = con.execute("SELECT snapshot_id FROM roster_snapshots WHERE league_id = ? AND sha256 = ?",
                           [league_id, raw.sha256]).fetchone()
    if existing is not None:
        return RosterIngestResult(existing[0], league_id, season_id, matchday, status.get("mstr"), teams, 0, True,
                                  warnings, raw.sha256, str(raw.path))
    con.begin()
    try:
        snapshot_id = con.execute(
            "INSERT INTO roster_snapshots (league_id, season_id, fetched_at, source, raw_path, sha256, matchday, "
            "matchday_start, team_count, teams, row_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?) RETURNING snapshot_id",
            [league_id, season_id, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, matchday, start,
             teams, json.dumps(team_list, ensure_ascii=False), len(rows)]).fetchone()[0]
        if rows:                                  # executemany rejects an empty parameter list
            con.executemany("INSERT INTO rosters VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [[snapshot_id, r.team_id, r.team_name, r.owner, r.player_id, r.cost, r.position] for r in rows])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return RosterIngestResult(snapshot_id, league_id, season_id, matchday, status.get("mstr"), teams, len(rows), False,
                              warnings, raw.sha256, str(raw.path))
