"""One owner of live state (spec, "Concurrency: one owner of state, and two
classes of query"): every change -- a feed snapshot, a new adjustment
layer, a refresh -- goes through mutate(), which re-derives the board and
tells every listener. 2b's server is one listener (the WebSocket
broadcast, the state file); the CLI's replay is another. No I/O here: the
caller reads the feed or the file and hands the result in, so a change
made from any surface reaches the board through the same path and no
state change can escape a listener's notice.

A Refresh carrying no layer is the caller's answer to a file it could not
read: load_adjustments raises, the caller reports it, and the previous
layer stands because nothing here replaces it (spec, "Adjustments are
hot-reloaded").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from fantaclaude.asta.adjustments import EMPTY_LAYER, AdjustmentLayer
from fantaclaude.asta.advisor import Board, TeamMapping, derive
from fantaclaude.asta.pinned import PinnedRun
from fantaclaude.asta.session import SessionSettings, session_from_feed
from fantaclaude.asta.state import AuctionState, Event, Snapshot, apply_snapshot
from fantaclaude.kb.participants import Participant


@dataclass(frozen=True)
class Refresh:
    """Re-derive from the inputs as they are now: a re-read adjustments.yml,
    re-read dossiers, or nothing new at all -- a forced deterministic
    recompute (spec, live-event requirement 6)."""
    layer: AdjustmentLayer | None = None
    participants: dict[str, Participant] | None = None


@dataclass(frozen=True)
class MutationResult:
    events: tuple[Event, ...]
    board: Board


Change = Snapshot | Refresh
Listener = Callable[[MutationResult], None]


class Auction:
    def __init__(self, run: PinnedRun, mapping: TeamMapping, *, settings: SessionSettings | None = None,
                 layer: AdjustmentLayer = EMPTY_LAYER, scenario: str | None = None,
                 participants: dict[str, Participant] | None = None) -> None:
        self.run = run
        self.mapping = mapping
        self.settings = settings or run.league
        self.layer = layer
        self.scenario = scenario
        self.participants = participants
        self.state = AuctionState.empty()
        self.listeners: list[Listener] = []
        self.board = self._derive()

    def subscribe(self, listener: Listener) -> None:
        self.listeners.append(listener)

    def _derive(self) -> Board:
        return derive(self.state, run=self.run, settings=self.settings, layer=self.layer, mapping=self.mapping,
                      scenario=self.scenario, participants=self.participants)

    def mutate(self, change: Change) -> MutationResult:
        """Apply one change, re-derive the board, notify. A snapshot whose
        settings this code cannot read raises before anything is touched, so
        the auction stays where it was.

        A snapshot carrying no settings node keeps the ones in force, and
        carries them *into* the state rather than around it: `apply_snapshot`
        replaces `AuctionState.settings` with the snapshot's unconditionally,
        so a settings-less snapshot used to announce every key as removed
        (one spurious SettingsChanged) and leave `board.settings` and
        `board.state.settings` disagreeing. `render_state` writes the
        *state's* node under `feed`, so a state file written at that moment
        no longer reproduced its own board: reloaded, `_settings` saw no
        settings and fell back to the run's league ranges, swapping the
        night's rules for the league's -- the one property the snapshot
        module exists for. `apply_snapshot` stays a pure function of the
        snapshot it is handed; what changes is the snapshot handed to it."""
        events: tuple[Event, ...] = ()
        if isinstance(change, Snapshot):
            settings = self.settings
            if change.settings:
                settings = session_from_feed(change.settings, team_count=len(change.teams) or self.settings.team_count)
            else:
                change = replace(change, settings=dict(self.settings.raw))
            self.state, events = apply_snapshot(self.state, change)
            self.settings = settings
        elif isinstance(change, Refresh):
            if change.layer is not None:
                self.layer = change.layer
            if change.participants is not None:
                self.participants = change.participants
        else:
            raise TypeError(f"not a change: {change!r}")
        self.board = self._derive()
        result = MutationResult(events, self.board)
        for listener in self.listeners:
            listener(result)
        return result
