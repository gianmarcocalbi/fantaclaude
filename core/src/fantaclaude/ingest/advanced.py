"""Understat season totals: fetch, load, match, record.

One POST per season to the endpoint Understat's own league page calls
(the page no longer embeds the tables), answering
{"success": true, "players": [...]} -- games, minutes ("time"), goals,
assists, xG, xA, shots, key passes, cards, per player per season: the
luck-correction inputs and the minutes the voti do not carry. Observed
2026-08-28; every field is a string, `team_title` is "A,B" for a mid-season
mover, `player_name` is HTML-escaped. Names are matched onto the listone by
ingest.names; unmatched and ambiguous rows are stored with player_id NULL
and reported, never dropped.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes
from fantaclaude.ingest.names import (
    AMBIGUOUS,
    Aliases,
    Candidate,
    Matcher,
    resolve_team,
)
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.model.seasons import understat_season
from fantaclaude.timeutil import to_db

SOURCE = "understat:POST /main/getPlayersStats/"
URL = "https://understat.com/main/getPlayersStats/"
REQUIRED = ("id", "player_name", "games", "time", "goals", "assists", "xG", "xA", "npg", "npxG",
            "shots", "key_passes", "yellow_cards", "red_cards", "position", "team_title",
            "xGChain", "xGBuildup")


class AdvancedShapeError(ValueError):
    """The payload is not the Understat table this adapter was written against."""


@dataclass(frozen=True)
class AdvancedRow:
    source_id: str
    player_name: str
    teams: tuple[str, ...]
    games: int
    minutes: int
    goals: int
    assists: int
    xg: float
    xa: float
    npg: int
    npxg: float
    shots: int
    key_passes: int
    yellow: int
    red: int
    xg_chain: float
    xg_buildup: float
    position: str
    raw: dict[str, Any]


async def fetch_advanced(http: httpx.AsyncClient, store: RawStore, *, season_id: int) -> RawFile:
    data = await fetch_bytes(http, URL, method="POST", headers={"X-Requested-With": "XMLHttpRequest"},
                             data={"league": "Serie_A", "season": str(understat_season(season_id))})
    try:
        payload = json.loads(data)
    except ValueError:
        raise AdvancedShapeError("Understat answered something that is not JSON") from None
    if not (isinstance(payload, dict) and payload.get("success") is True
            and isinstance(payload.get("players"), list)):
        raise AdvancedShapeError('Understat payload is not {"success": true, "players": [...]}')
    # The response does not say which season it is for, so the wrapper does.
    return store.write("advanced", {"season_id": season_id, "understat_season": understat_season(season_id),
                                    "payload": payload}, label=str(season_id))


def load_advanced(path: Path) -> tuple[int, list[AdvancedRow]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    players = doc.get("payload", {}).get("players") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or not isinstance(doc.get("season_id"), int) \
            or not isinstance(players, list) or not players:
        raise AdvancedShapeError(f"{path}: no season_id or no players")
    rows: list[AdvancedRow] = []
    for entry in players:
        missing = [k for k in REQUIRED if k not in entry]
        if missing:
            raise AdvancedShapeError(
                f"{path}: player {entry.get('id')} ({entry.get('player_name')}) lacks {missing}")
        rows.append(AdvancedRow(
            source_id=str(entry["id"]),
            player_name=html.unescape(str(entry["player_name"])).strip(),
            teams=tuple(t.strip() for t in str(entry["team_title"]).split(",") if t.strip()),
            games=int(entry["games"]), minutes=int(entry["time"]), goals=int(entry["goals"]),
            assists=int(entry["assists"]), xg=float(entry["xG"]), xa=float(entry["xA"]),
            npg=int(entry["npg"]), npxg=float(entry["npxG"]), shots=int(entry["shots"]),
            key_passes=int(entry["key_passes"]), yellow=int(entry["yellow_cards"]),
            red=int(entry["red_cards"]), xg_chain=float(entry["xGChain"]),
            xg_buildup=float(entry["xGBuildup"]), position=str(entry["position"]), raw=entry))
    ids = [r.source_id for r in rows]
    if len(set(ids)) != len(ids):
        raise AdvancedShapeError(f"{path}: duplicate Understat ids")
    return int(doc["season_id"]), rows


@dataclass(frozen=True)
class AdvancedIngestResult:
    snapshot_id: int | None
    season_id: int
    inserted: int
    skipped_duplicate: bool
    matched: int
    alias: int
    ambiguous: int
    unmatched: int
    ambiguous_names: list[dict[str, Any]]
    unresolved_teams: list[str]
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, "season_id": self.season_id, "inserted": self.inserted,
                "skipped_duplicate": self.skipped_duplicate, "matched": self.matched, "alias": self.alias,
                "ambiguous": self.ambiguous, "unmatched": self.unmatched,
                "ambiguous_names": self.ambiguous_names, "unresolved_teams": self.unresolved_teams,
                "sha256": self.sha256, "raw_path": self.raw_path}


def record_advanced(con: duckdb.DuckDBPyConnection, season_id: int, rows: list[AdvancedRow],
                    raw: RawFile, *, candidates: list[Candidate], teams: dict[str, str],
                    aliases: Aliases) -> AdvancedIngestResult:
    """Append one snapshot per distinct raw file; the same bytes twice is a no-op.

    Matching happens here, at record time, against the *current* listone: a
    re-record after the listone moved (a January transfer) re-matches from the
    same immutable file -- which is what "rebuildable from raw" means.
    """
    existing = con.execute(
        "SELECT snapshot_id, matched, ambiguous, unmatched FROM advanced_snapshots WHERE sha256 = ?",
        [raw.sha256]).fetchone()
    if existing is not None:
        alias_count = con.execute(
            "SELECT count(*) FROM advanced_stats WHERE snapshot_id = ? AND match_status = 'alias'",
            [existing[0]]).fetchone()[0]
        return AdvancedIngestResult(existing[0], season_id, 0, True, existing[1], alias_count,
                                    existing[2], existing[3], [], [], raw.sha256, str(raw.path))
    matcher = Matcher(candidates, aliases.players_for("understat"))
    team_aliases = aliases.teams_for("understat")
    names = {c.player_id: c.name for c in candidates}
    counts: Counter[str] = Counter()
    ambiguous_names: list[dict[str, Any]] = []
    unresolved: set[str] = set()
    records: list[list[Any]] = []
    for r in rows:
        shorts: list[str] = []
        for team in r.teams:
            short = resolve_team(team, teams, team_aliases)
            if short is None:
                unresolved.add(team)          # relegated or foreign in a back season: expected, reported
            else:
                shorts.append(short)
        match = matcher.match(r.player_name, tuple(shorts))
        counts[match.status] += 1
        if match.status == AMBIGUOUS:
            ambiguous_names.append({"name": r.player_name, "teams": list(r.teams),
                                    "candidates": [{"player_id": pid, "name": names[pid]}
                                                   for pid in match.candidates]})
        records.append([None, season_id, r.source_id, r.player_name, list(r.teams), match.player_id,
                        match.status, list(match.candidates), r.games, r.minutes, r.goals, r.assists,
                        r.xg, r.xa, r.npg, r.npxg, r.shots, r.key_passes, r.yellow, r.red,
                        r.xg_chain, r.xg_buildup, r.position, json.dumps(r.raw, ensure_ascii=False)])
    con.begin()
    try:
        snapshot_id = con.execute(
            "INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, row_count, "
            "matched, ambiguous, unmatched) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING snapshot_id",
            [season_id, to_db(raw.fetched_at), SOURCE, str(raw.path), raw.sha256, len(rows),
             counts["matched"], counts["ambiguous"], counts["unmatched"]]).fetchone()[0]
        for record in records:
            record[0] = snapshot_id
        con.executemany(
            "INSERT INTO advanced_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?::JSON)", records)
    except Exception:
        con.rollback()
        raise
    con.commit()
    return AdvancedIngestResult(snapshot_id, season_id, len(rows), False, counts["matched"], counts["alias"],
                                counts["ambiguous"], counts["unmatched"], ambiguous_names,
                                sorted(unresolved), raw.sha256, str(raw.path))
