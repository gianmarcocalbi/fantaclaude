"""The auction as the feed describes it -- picks, the lot on the block, the
teams, the settings -- and the set-diff that turns one snapshot into events
(spec, "The adapter, and the rules that keep it safe").

The state is a pure function of the last snapshot: apply_snapshot returns
the state that snapshot describes and the events that separate it from the
state before -- adds, removals (the admin undid a lot), cost edits, the lot
changing, the settings changing, the session's status changing. Applying
the same snapshot twice is a no-op, and any sequence of snapshots ends
where replaying only the last one would, which is what makes reconnects
and replays safe for free. Nothing here corrects anything: whatever the
admin records is what the board shows (spec, "The mirror is faithful").

Credits are derived from picks, never read from teams[].currentBudget
(observed 2026-08-23: after 181 credits spent the mirrored field still read
500). A pick's playerId is the listone id (spec, open question 8), so the
advisor names a player from the pinned run and never fuzzy-matches; a pick
it cannot name is a fault it surfaces. Nicks are scrubbed here, at
ingestion: an @-shaped label is replaced by the team id before it can reach
a state file, a dashboard or a tool result.

The node shape is the spec's (`picks[] {playerId, teamId, cost, value,
index, timestamp}`, `selectedPlayerId`, `turnTeamId`, `status`, `locked`,
`teams[]`, `settings`, `options`, `pickOrder`, `hostId`, `playerListHash`);
of a pick only playerId, teamId and cost are consumed -- `value` is what
FantaAstaLive lists him at, and `cost` is what was paid. Firebase returns a
list with holes as an object keyed by index, so both shapes are read.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fantaclaude.league.settings import EMAIL_PATTERN, diff_payloads


class SnapshotError(ValueError):
    """The node is not the shape the mirror reads; the message names the field."""


@dataclass(frozen=True)
class Pick:
    player_id: int
    team_id: int
    cost: int
    index: int
    timestamp: int | None = None

    def to_node(self) -> dict[str, Any]:
        """The feed's own shape, so a state file reloads through parse_snapshot."""
        return {"playerId": self.player_id, "teamId": self.team_id, "cost": self.cost, "index": self.index,
                "timestamp": self.timestamp}


@dataclass(frozen=True)
class Team:
    team_id: int
    label: str                     # scrubbed: never an email address

    def to_node(self) -> dict[str, Any]:
        return {"id": self.team_id, "connection": {"label": self.label}}


@dataclass(frozen=True)
class Snapshot:
    picks: tuple[Pick, ...]
    teams: tuple[Team, ...]
    settings: dict[str, Any]
    selected: int | None = None
    turn_team: int | None = None
    status: str | None = None
    locked: bool | None = None
    player_list_hash: str | None = None

    def to_node(self) -> dict[str, Any]:
        return {"picks": [p.to_node() for p in self.picks], "teams": [t.to_node() for t in self.teams],
                "settings": dict(self.settings), "selectedPlayerId": self.selected, "turnTeamId": self.turn_team,
                "status": self.status, "locked": self.locked, "playerListHash": self.player_list_hash}


def scrub_label(label: Any, team_id: int) -> str:
    """A team's display name: whatever someone typed, unless it has the shape
    of an email address or is empty, in which case the team id stands in."""
    text = label.strip() if isinstance(label, str) else ""
    if not text or EMAIL_PATTERN.search(text):
        return f"team {team_id}"
    return text


def _int(value: Any, where: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotError(f"{where} is {value!r}; expected an integer")
    if minimum is not None and value < minimum:
        raise SnapshotError(f"{where} is {value!r}; expected at least {minimum}")
    return value


def _optional_int(value: Any, where: str) -> int | None:
    return None if value is None else _int(value, where)


def _entries(value: Any, where: str) -> list[Any]:
    """A Firebase list: an array, or an object keyed by index when the array
    had holes. None entries are holes and are skipped."""
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v is not None]
    if isinstance(value, Mapping):
        try:
            keys = sorted(value, key=int)
        except (TypeError, ValueError):
            raise SnapshotError(f"{where} is keyed by {list(value)[:3]}; expected list indexes") from None
        return [value[k] for k in keys if value[k] is not None]
    raise SnapshotError(f"{where} is {type(value).__name__}; expected a list")


def parse_snapshot(node: Mapping[str, Any]) -> Snapshot:
    if not isinstance(node, Mapping):
        raise SnapshotError("the state node is not a mapping")
    picks: list[Pick] = []
    for i, raw in enumerate(_entries(node.get("picks"), "picks")):
        if not isinstance(raw, Mapping):
            raise SnapshotError(f"picks[{i}] is {raw!r}; expected a mapping")
        picks.append(Pick(_int(raw.get("playerId"), f"picks[{i}].playerId"),
                          _int(raw.get("teamId"), f"picks[{i}].teamId"),
                          _int(raw.get("cost"), f"picks[{i}].cost", minimum=0),
                          _int(raw.get("index", i), f"picks[{i}].index"),
                          _optional_int(raw.get("timestamp"), f"picks[{i}].timestamp")))
    teams: list[Team] = []
    for i, raw in enumerate(_entries(node.get("teams"), "teams")):
        if not isinstance(raw, Mapping):
            raise SnapshotError(f"teams[{i}] is {raw!r}; expected a mapping")
        team_id = _int(raw.get("id"), f"teams[{i}].id")
        connection = raw.get("connection") if isinstance(raw.get("connection"), Mapping) else {}
        teams.append(Team(team_id, scrub_label(connection.get("label") or raw.get("nick") or raw.get("name"), team_id)))
    settings = node.get("settings")
    if settings is not None and not isinstance(settings, Mapping):
        raise SnapshotError(f"settings is {type(settings).__name__}; expected a mapping")
    locked = node.get("locked")
    if locked is not None and not isinstance(locked, bool):
        raise SnapshotError(f"locked is {locked!r}; expected a boolean")
    status = node.get("status")
    list_hash = node.get("playerListHash")
    return Snapshot(tuple(sorted(picks, key=lambda p: (p.index, p.player_id))),
                    tuple(sorted(teams, key=lambda t: t.team_id)), dict(settings or {}),
                    _optional_int(node.get("selectedPlayerId"), "selectedPlayerId"),
                    _optional_int(node.get("turnTeamId"), "turnTeamId"),
                    None if status is None else str(status), locked, list_hash if isinstance(list_hash, str) else None)


def read_snapshots(path: Path) -> list[Snapshot]:
    """One state node per line (JSON lines): the shape a captured session replays through."""
    out: list[Snapshot] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            node = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"{path}:{number}: {exc}") from None
        try:
            out.append(parse_snapshot(node))
        except SnapshotError as exc:
            raise SnapshotError(f"{path}:{number}: {exc}") from None
    return out


@dataclass(frozen=True)
class AuctionState:
    picks: dict[int, Pick]                 # by player_id: a player is sold once
    teams: tuple[Team, ...]
    settings: dict[str, Any]
    selected: int | None = None
    turn_team: int | None = None
    status: str | None = None
    locked: bool | None = None
    player_list_hash: str | None = None
    duplicates: tuple[int, ...] = ()       # listed twice in one snapshot: the last pick by index stood, and the board says so

    @classmethod
    def empty(cls) -> AuctionState:
        return cls({}, (), {})

    def team_ids(self) -> tuple[int, ...]:
        return tuple(sorted({t.team_id for t in self.teams} | {p.team_id for p in self.picks.values()}))

    def picks_of(self, team_id: int) -> tuple[Pick, ...]:
        return tuple(sorted((p for p in self.picks.values() if p.team_id == team_id), key=lambda p: (p.index, p.player_id)))

    def spent(self, team_id: int) -> int:
        return sum(p.cost for p in self.picks.values() if p.team_id == team_id)

    def to_snapshot(self) -> Snapshot:
        return Snapshot(tuple(sorted(self.picks.values(), key=lambda p: (p.index, p.player_id))), self.teams,
                        dict(self.settings), self.selected, self.turn_team, self.status, self.locked, self.player_list_hash)


@dataclass(frozen=True)
class SaleAdded:
    player_id: int
    team_id: int
    cost: int


@dataclass(frozen=True)
class SaleRemoved:
    player_id: int
    team_id: int
    cost: int


@dataclass(frozen=True)
class CostEdited:
    player_id: int
    team_id: int
    before: int
    after: int


@dataclass(frozen=True)
class LotSelected:
    player_id: int | None


@dataclass(frozen=True)
class SettingsChanged:
    changes: tuple[tuple[str, Any, Any], ...]      # (dotted path, before, after), as sync-league reports a rules change


@dataclass(frozen=True)
class StatusChanged:
    status: str | None
    locked: bool | None


Event = SaleAdded | SaleRemoved | CostEdited | LotSelected | SettingsChanged | StatusChanged


def state_from_snapshot(snap: Snapshot) -> AuctionState:
    picks: dict[int, Pick] = {}
    duplicates: set[int] = set()
    for pick in snap.picks:                     # sorted by index: the later pick of a player listed twice stands
        if pick.player_id in picks:
            duplicates.add(pick.player_id)
        picks[pick.player_id] = pick
    return AuctionState(picks, snap.teams, dict(snap.settings), snap.selected, snap.turn_team, snap.status, snap.locked,
                        snap.player_list_hash, tuple(sorted(duplicates)))


def apply_snapshot(state: AuctionState, snap: Snapshot) -> tuple[AuctionState, tuple[Event, ...]]:
    """The state the snapshot describes, and what separates it from `state`.
    Pure: the new state carries nothing of the old one, so a replay of every
    snapshot and a replay of the last alone agree; the events are the
    difference, in a deterministic order (by player id)."""
    new = state_from_snapshot(snap)
    events: list[Event] = []
    for pid in sorted(set(state.picks) | set(new.picks)):
        before, after = state.picks.get(pid), new.picks.get(pid)
        if after is None:
            events.append(SaleRemoved(pid, before.team_id, before.cost))
        elif before is None:
            events.append(SaleAdded(pid, after.team_id, after.cost))
        elif before.team_id != after.team_id:
            events.append(SaleRemoved(pid, before.team_id, before.cost))
            events.append(SaleAdded(pid, after.team_id, after.cost))
        elif before.cost != after.cost:
            events.append(CostEdited(pid, after.team_id, before.cost, after.cost))
    if new.selected != state.selected:
        events.append(LotSelected(new.selected))
    if state.settings and new.settings != state.settings:      # the first snapshot's settings are the baseline
        # Two dicts can differ where diff_payloads sees nothing -- it walks with
        # .get(), so {"a": None} and {} are unequal but hold no change. An event
        # announcing zero changes is a false alarm, so it is not raised.
        changes = tuple((c.path, c.before, c.after) for c in diff_payloads(state.settings, new.settings))
        if changes:
            events.append(SettingsChanged(changes))
    if (new.status, new.locked) != (state.status, state.locked):
        events.append(StatusChanged(new.status, new.locked))
    return new, tuple(events)
