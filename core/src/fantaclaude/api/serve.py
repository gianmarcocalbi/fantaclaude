"""One owner of live state (spec, "Concurrency: one owner of state, and two
classes of query"): AstaServer wraps 2a's Auction in an asyncio shell. Every
change — a feed snapshot, an adjustment from any surface, a refresh — passes
through one lock and one worker thread, re-derives the board, writes the
state file, and broadcasts to every WebSocket. Being callback-shaped (plain
async senders, no FastAPI types) is what keeps this testable without HTTP.

The server starts `pending` unless a mapping is handed in (state-file mode)
or `--me`/`--map` flags resolve against the first snapshot; `POST
/api/mapping` (the screen) moves it to `live`. The mapping is never
persisted by the server (spec: the browser pre-fills the screen); it reaches
the state file only inside render_state, as the board's own labels.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fantaclaude.asta.adjustments import (
    Adjustment,
    AdjustmentLayer,
    append_adjustment,
    file_sha256,
    load_adjustments,
    resolve,
)
from fantaclaude.asta.advisor import Board, TeamMapping
from fantaclaude.asta.auction import Auction, MutationResult, Refresh
from fantaclaude.asta.pinned import PinnedRun
from fantaclaude.asta.session import compare, session_from_feed
from fantaclaude.asta.snapshot import render_state, write_state
from fantaclaude.asta.state import Snapshot
from fantaclaude.commands.asta import (
    AstaPaths,
    UsageError,
    describe_event,
    resolve_mapping,
)
from fantaclaude.ingest.asta_live import LIVE, OFFLINE, RECONNECTING
from fantaclaude.kb.participants import Participant, load_participants
from fantaclaude.timeutil import utc_now

Sender = Callable[[str], Awaitable[None]]
Mode = Literal["feed", "replay", "state"]
# The feed-status vocabulary: LIVE/RECONNECTING/OFFLINE for feed mode, plus
# the two non-feed modes this class already uses as a status in their own
# right (Mode's other two members) -- one set, enforced at the one place a
# caller (Task 5's WebSocket handler, Task 7's replay driver) sets it.
FEED_STATUSES = frozenset({LIVE, RECONNECTING, OFFLINE, "replay", "state"})


class PhaseError(RuntimeError):
    """The mapping screen has not been answered; the board does not exist yet."""


class AstaServer:
    def __init__(self, *, run: PinnedRun, layer: AdjustmentLayer, participants: dict[str, Participant],
                 scenario: str | None, paths: AstaPaths, mode: Mode, session_code: str | None = None,
                 mapping: TeamMapping | None = None, pending_me: str | None = None,
                 pending_maps: tuple[str, ...] = ()) -> None:
        self.run = run
        self.layer = layer
        self.participants = participants
        self.scenario = scenario
        self.paths = paths
        self.mode: Mode = mode
        self.session_code = session_code
        self.feed_status = OFFLINE if mode == "feed" else mode
        self.auction: Auction | None = None
        self.last_snapshot: Snapshot | None = None
        self.pending_note: str | None = None
        self._pending_me = pending_me
        self._pending_maps = tuple(pending_maps)
        self._lock = asyncio.Lock()
        self._senders: list[Sender] = []
        if mapping is not None:
            self._build(mapping)

    # -- surface -----------------------------------------------------------

    def hello(self) -> dict[str, Any]:
        # Bound once: self.auction is assigned from a worker thread (_build,
        # under asyncio.to_thread), and hello() runs on the event loop -- a
        # thread switch between two separate `self.auction` reads could see
        # it change mid-call and answer from a mix of before and after.
        auction = self.auction
        board = auction.board if auction is not None else None
        if board is not None:
            settings = board.settings
            conflicts = list(board.league_conflicts)
            teams = [{"team_id": tid, "label": ledger.label} for tid, ledger in sorted(board.ledgers.items())]
            scenario: str | None = board.scenario
        elif self.last_snapshot is not None and self.last_snapshot.settings:
            settings = session_from_feed(self.last_snapshot.settings,
                                          team_count=len(self.last_snapshot.teams) or self.run.league.team_count)
            conflicts = compare(settings, self.run.league)
            teams = [{"team_id": t.team_id, "label": t.label} for t in self.last_snapshot.teams]
            scenario = self.scenario
        else:
            settings, conflicts, teams, scenario = None, [], [], self.scenario
        return {"phase": "live" if auction is not None else "pending", "mode": self.mode,
                "session_code": self.session_code, "feed": self.feed_status, "run": self.run.describe(),
                "scenario": scenario, "settings": None if settings is None else settings.to_dict(),
                "league_conflicts": list(conflicts), "note": self.pending_note,
                "teams": teams, "participants": sorted(self.participants),
                "mapping": None if auction is None else auction.mapping.to_dict(),
                "board": None if board is None else board.to_dict()}

    def subscribe(self, sender: Sender) -> Callable[[], None]:
        self._senders.append(sender)

        def unsubscribe() -> None:
            if sender in self._senders:
                self._senders.remove(sender)
        return unsubscribe

    async def on_snapshot(self, snap: Snapshot) -> None:
        self.last_snapshot = snap
        if self.auction is None:
            if self._pending_me is not None:
                me, maps = self._pending_me, self._pending_maps
                self._pending_me, self._pending_maps = None, ()
                try:
                    mapping = resolve_mapping(snap.teams, me=me, maps=maps, participants=self.participants)
                except UsageError as exc:
                    self.pending_note = f"--me/--map could not be applied: {exc}; answer the mapping screen"
                else:
                    await self.set_mapping(mapping.mine, mapping.nicks)
                    return
            await self._broadcast({"type": "hello", "hello": self.hello()})
            return
        await self._apply(snap)

    async def set_mapping(self, mine: int, nicks: dict[int, str]) -> dict[str, Any]:
        unknown_nicks = sorted(set(nicks.values()) - set(self.participants))
        if unknown_nicks:
            raise UsageError(f"no dossier for {unknown_nicks} under kb/league/participants; "
                              f"known: {sorted(self.participants)}")
        if self.last_snapshot is not None and self.last_snapshot.teams:
            ids = {t.team_id for t in self.last_snapshot.teams}
            bad = sorted((set(nicks) | {mine}) - ids)
            if bad:
                raise UsageError(f"team(s) {bad} are not in the session, which has {sorted(ids)}")
        async with self._lock:
            await asyncio.to_thread(self._build, TeamMapping(mine, dict(nicks)))
        self.pending_note = None
        hello = self.hello()
        await self._broadcast({"type": "hello", "hello": hello})
        return hello

    async def set_feed_status(self, status: str) -> None:
        if status not in FEED_STATUSES:
            raise UsageError(f"feed status {status!r} is not one of {sorted(FEED_STATUSES)}")
        self.feed_status = status
        await self._broadcast({"type": "feed", "status": status})

    async def adjust(self, adjustment: Adjustment) -> dict[str, Any]:
        self._require_live()
        player_id: int | None = None
        if adjustment.kind != "target":
            probe = resolve([adjustment], self.run.candidates())
            if probe.problems:
                raise UsageError(probe.problems[0])
            player_id = probe.entries[0].player_id
        async with self._lock:
            def work() -> tuple[int, MutationResult]:
                entries = append_adjustment(self.paths.adjustments, adjustment)
                layer = resolve(load_adjustments(self.paths.adjustments), self.run.candidates(),
                                 sha256=file_sha256(self.paths.adjustments))
                self.layer = layer
                return len(entries), self._mutate_and_write(Refresh(layer=layer))
            count, result = await asyncio.to_thread(work)
        await self._broadcast_board(result)
        return {"described": adjustment.describe(), "count": count, "player_id": player_id,
                "board": result.board.to_dict()}

    async def refresh(self) -> dict[str, Any]:
        self._require_live()
        async with self._lock:
            def work() -> MutationResult:
                layer = resolve(load_adjustments(self.paths.adjustments), self.run.candidates(),
                                 sha256=file_sha256(self.paths.adjustments))       # AdjustmentsError propagates; the previous layer stands
                participants = {p.nick: p for p in load_participants(self.paths.kb)} if self.paths.kb.is_dir() else {}
                self.layer, self.participants = layer, participants
                return self._mutate_and_write(Refresh(layer=layer, participants=participants))
            result = await asyncio.to_thread(work)
        await self._broadcast_board(result)
        return {"board": result.board.to_dict(), "problems": list(result.board.problems)}

    # -- internals ---------------------------------------------------------

    def _require_live(self) -> None:
        if self.auction is None:
            raise PhaseError("the mapping screen has not been answered; the board does not exist yet")

    def _build(self, mapping: TeamMapping) -> None:
        auction = Auction(self.run, mapping, layer=self.layer, scenario=self.scenario,
                           participants=self.participants)
        if self.last_snapshot is None:
            # No snapshot has been mirrored yet: this auction has never seen
            # one, and its board is the run's own empty board -- writing it
            # now would overwrite data/asta-state.json's prior mirror (state
            # mode restores `mapping` from that very file with no snapshot
            # constructor argument to replay) with nothing, before the feed
            # or replay ever gets a chance to. Publish the auction so the
            # board reads live; leave the file exactly as it was.
            self.auction = auction
            return
        auction.mutate(self.last_snapshot)
        self._write_state(auction.board)          # write first: the file must hold what self.auction publishes
        self.auction = auction

    async def _apply(self, snap: Snapshot) -> MutationResult:
        async with self._lock:
            result = await asyncio.to_thread(self._mutate_and_write, snap)
        await self._broadcast_board(result)
        return result

    def _mutate_and_write(self, change: Snapshot | Refresh) -> MutationResult:
        result = self.auction.mutate(change)
        self._write_state(result.board)
        return result

    def _write_state(self, board: Board) -> None:
        write_state(self.paths.state, render_state(board, session_code=self.session_code, written_at=utc_now()))

    async def _broadcast_board(self, result: MutationResult) -> None:
        labels = {tid: ledger.label for tid, ledger in result.board.ledgers.items()}
        events = [describe_event(e, self.run, labels) for e in result.events]
        await self._broadcast({"type": "board", "board": result.board.to_dict(), "events": events})

    async def _broadcast(self, message: dict[str, Any]) -> None:
        text = json.dumps(message, ensure_ascii=False)
        for sender in list(self._senders):
            try:
                await sender(text)
            except Exception:                       # noqa: BLE001 -- a dead client detaches itself; the sender is
                                                     # caller-supplied (a WebSocket send, in production) and may
                                                     # raise anything, so nothing narrower is safe to name here
                if sender in self._senders:
                    self._senders.remove(sender)
