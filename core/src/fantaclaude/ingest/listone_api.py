"""The listone through the league API: fetch, parse, snapshot.

Column names follow the MCP spec's confirmed meanings; everything else rides
in `raw`. An unknown role code fails loud with the player's name (roles.py)
and a missing confirmed field fails loud with the field's name -- a red
ingest, never a silently-null quotazione.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from fantacalcio_mcp.api import FantacalcioAPI

from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.model.roles import (
    ClassicRole,
    Role,
    decode_classic,
    decode_mantra,
    sort_roles,
)
from fantaclaude.timeutil import to_db

SOURCE = "league_api:/onboarding/v1/league/players"
REQUIRED = ("id", "name", "tname", "stnme", "tid", "fcrle", "marle",
            "icsfc", "acsfc", "icsma", "acsma", "fvmfc", "fvmma")


class ListoneShapeError(ValueError):
    """The payload is not the listone this adapter was written against."""


@dataclass(frozen=True)
class PlayerRow:
    player_id: int
    name: str
    team_id: int
    team_name: str
    team_short: str
    classic_role: ClassicRole
    mantra_roles: frozenset[Role]
    mantra_role_codes: tuple[int, ...]
    quot_initial_classic: int
    quot_current_classic: int
    quot_initial_mantra: int
    quot_current_mantra: int
    fvm_classic: int
    fvm_mantra: int
    age: int | None
    nationality: str | None
    transfer_flag: bool
    raw: dict[str, Any]


async def fetch_listone(api: FantacalcioAPI, store: RawStore, *, league: str | None = None) -> RawFile:
    payload = await api.players(league=league)
    if not isinstance(payload, dict) or not isinstance(payload.get("players"), list):
        raise ListoneShapeError("listone payload is not {players: [...], timestamp}")
    return store.write("listone", payload)


def load_listone(path: Path) -> list[PlayerRow]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    players = payload.get("players") if isinstance(payload, dict) else None
    if not isinstance(players, list) or not players:
        raise ListoneShapeError(f"{path}: no players array")
    rows: list[PlayerRow] = []
    for entry in players:
        missing = [k for k in REQUIRED if k not in entry]
        if missing:
            raise ListoneShapeError(
                f"{path}: player {entry.get('id')} ({entry.get('name')}) lacks {missing}")
        context = f"{entry['name']} (id {entry['id']})"
        rows.append(PlayerRow(
            player_id=int(entry["id"]),
            name=str(entry["name"]),
            team_id=int(entry["tid"]),
            team_name=str(entry["tname"]),
            team_short=str(entry["stnme"]),
            classic_role=decode_classic(int(entry["fcrle"]), context=context),
            mantra_roles=decode_mantra(entry["marle"], context=context),
            mantra_role_codes=tuple(int(c) for c in entry["marle"]),
            quot_initial_classic=int(entry["icsfc"]),
            quot_current_classic=int(entry["acsfc"]),
            quot_initial_mantra=int(entry["icsma"]),
            quot_current_mantra=int(entry["acsma"]),
            fvm_classic=int(entry["fvmfc"]),
            fvm_mantra=int(entry["fvmma"]),
            age=entry.get("age"),
            nationality=entry.get("naty"),
            transfer_flag=bool(entry.get("trnsf")),
            raw=entry,
        ))
    ids = [r.player_id for r in rows]
    if len(set(ids)) != len(ids):
        raise ListoneShapeError(f"{path}: duplicate player ids")
    return rows


@dataclass(frozen=True)
class IngestResult:
    snapshot_id: int | None
    inserted: int
    skipped_duplicate: bool
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "inserted": self.inserted,
                "skipped_duplicate": self.skipped_duplicate, "sha256": self.sha256,
                "raw_path": self.raw_path}


def record_listone(con: duckdb.DuckDBPyConnection, rows: list[PlayerRow], raw: RawFile) -> IngestResult:
    """Append one snapshot per distinct raw file; the same bytes twice is a no-op.

    The snapshot, players and teams rows land in one transaction: the
    v_players_current/v_teams_current views key off the latest
    listone_snapshots row, so a snapshot row committed without its players
    would make "current" report zero rows instead of falling back to the
    previous complete snapshot.
    """
    existing = con.execute("SELECT snapshot_id FROM listone_snapshots WHERE sha256 = ?",
                           [raw.sha256]).fetchone()
    if existing is not None:
        return IngestResult(existing[0], 0, True, raw.sha256, str(raw.path))
    con.begin()
    try:
        snapshot_id = con.execute(
            "INSERT INTO listone_snapshots (fetched_at, source, raw_path, sha256, player_count) "
            "VALUES (?, ?, ?, ?, ?) RETURNING snapshot_id",
            [to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, len(rows)]).fetchone()[0]
        con.executemany(
            "INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[snapshot_id, r.player_id, r.name, r.team_id, r.team_name, r.team_short,
              r.classic_role.value, [x.value for x in sort_roles(r.mantra_roles)],
              list(r.mantra_role_codes), r.quot_initial_classic, r.quot_current_classic,
              r.quot_initial_mantra, r.quot_current_mantra, r.fvm_classic, r.fvm_mantra,
              r.age, r.nationality, r.transfer_flag, json.dumps(r.raw, ensure_ascii=False)]
             for r in rows])
        teams = sorted({(r.team_id, r.team_name, r.team_short) for r in rows})
        con.executemany("INSERT INTO teams VALUES (?, ?, ?, ?)",
                        [[snapshot_id, team_id, name, short] for team_id, name, short in teams])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return IngestResult(snapshot_id, len(rows), False, raw.sha256, str(raw.path))
