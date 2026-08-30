"""data/asta-state.json: the mirrored auction as last seen, kept for the days
between the room and the transfer (spec, "One database, and the auction is
not in it": a plain state dump, atomically replaced on change, written
with names, roles and participants resolved so it reads on its own; and
live-event requirement 5: a copy to records/ when the auction closes, both
removed once the transfer is confirmed -- by 2b's verify-transfer, open
question 9, never here).

Nothing depends on the file during the auction: a restart resubscribes and
gets full state from the feed. Read back with no feed available it
reproduces the board (the post-auction path the spec's crash-recovery test
names): the feed's own node is kept under `feed`, verbatim in shape, beside
the resolved names, so a state file reloads through parse_snapshot and
derive() gives the same board -- the names are for the reader, the ids are
what is reloaded. The mapping travels with it, because the feed cannot
supply it and the server never persists it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fantaclaude.asta.advisor import Board, TeamMapping
from fantaclaude.asta.state import Snapshot, SnapshotError, parse_snapshot
from fantaclaude.atomic import write_atomic
from fantaclaude.league.settings import EMAIL_PATTERN
from fantaclaude.values import json_safe

STATE_VERSION = 1


class StateFileError(ValueError):
    """The state file is not one this code wrote, or is torn."""


def _scrub_nick(nick: str | None) -> str | None:
    """A nick is caller-supplied (TeamMapping is offline input -- flags, or a
    prior state file -- and never passes through the feed, so it never
    reaches state.scrub_label). render_state is the last place before it
    reaches a stored payload, so it applies the same email-shape rule here,
    dropping the nick rather than fabricating a label."""
    return None if nick is None or EMAIL_PATTERN.search(nick) else nick


def render_state(board: Board, *, session_code: str | None, written_at: datetime) -> dict[str, Any]:
    teams = []
    for team_id, ledger in sorted(board.ledgers.items()):
        picks = []
        for pick in ledger.picks:
            player = board.players.get(pick.player_id)
            picks.append({"player_id": pick.player_id, "name": None if player is None else player.name,
                          "team_short": None if player is None else player.team_short,
                          "roles": [] if player is None else list(player.roles), "cost": pick.cost, "index": pick.index,
                          "timestamp": pick.timestamp})
        teams.append({"id": team_id, "label": ledger.label, "nick": _scrub_nick(ledger.nick), "budget": ledger.budget,
                      "spent": ledger.spent, "credits": ledger.credits, "picks": picks})
    return json_safe({
        "version": STATE_VERSION, "written_at": written_at.isoformat(),
        "session": {"code": session_code, "status": board.state.status, "locked": board.state.locked,
                    "settings": board.settings.to_dict()},
        "run_id": board.run_id, "scenario": board.scenario, "adjustments_sha256": board.layer.sha256,
        "me": board.mine, "teams": teams, "selected": None if board.lot is None else board.lot.to_dict(),
        "problems": list(board.problems), "league_conflicts": list(board.league_conflicts),
        "feed": board.state.to_snapshot().to_node()})


def write_state(path: Path, payload: dict[str, Any]) -> None:
    write_atomic(path, (json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))


@dataclass(frozen=True)
class StoredState:
    snapshot: Snapshot
    mapping: TeamMapping
    session_code: str | None
    run_id: str
    scenario: str
    written_at: str
    payload: dict[str, Any]


def read_state(path: Path) -> StoredState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateFileError(f"{path}: {exc}") from None
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        raise StateFileError(f"{path}: not a fantaclaude state file of version {STATE_VERSION}")
    try:
        snapshot = parse_snapshot(payload["feed"])
        mine = int(payload["me"])
        nicks = {int(t["id"]): str(t["nick"]) for t in payload["teams"] if t.get("nick")}
        session = payload.get("session")
        if session is not None and not isinstance(session, dict):
            raise TypeError(f"session is {type(session).__name__}; expected a mapping")
        session_code = session.get("code") if isinstance(session, dict) else None
        return StoredState(snapshot, TeamMapping(mine, nicks), session_code,
                           str(payload["run_id"]), str(payload["scenario"]), str(payload["written_at"]), payload)
    except (KeyError, TypeError, ValueError, AttributeError, SnapshotError) as exc:
        raise StateFileError(f"{path}: {exc}") from None


def copy_to_records(path: Path, records_dir: Path, *, session_code: str | None, written_at: datetime) -> Path:
    """The state file's copy under records/asta/, written once: a file that
    exists with the same bytes is fine, one with different bytes is refused
    -- records are never rewritten.

    The name comes from the state file's *own* `written_at`, never from the
    clock at close. Stamped with the close instant, two `fantaclaude asta
    close` runs a second apart produced two files with different names and
    identical bytes, so the same-bytes guard below could never fire and
    records/ -- committed, never rewritten -- silently accumulated copies of
    one auction. Named by what it holds, an unchanged state file closes to
    the same name and no-ops, and a state file that genuinely moved on gets
    its own record.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise StateFileError(f"{path}: {exc}") from None
    # The filename names an instant, never a local clock -- records/ is committed and never rewritten.
    stamp = written_at.astimezone(UTC) if written_at.tzinfo is not None else written_at.replace(tzinfo=UTC)
    target = records_dir / "asta" / f"{session_code or 'session'}-{stamp:%Y%m%dT%H%M%SZ}.json"
    if target.exists():
        if target.read_bytes() == data:
            return target
        raise StateFileError(f"{target} exists with different content; records are never rewritten")
    write_atomic(target, data)
    return target
