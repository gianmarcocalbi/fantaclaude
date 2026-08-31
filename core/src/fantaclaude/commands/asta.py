"""fantaclaude asta: the auction core, offline (spec, "The skill <-> Python
contract"). Importable on purpose -- 2b's server calls these functions and
the CLI adds argument parsing and rendering.

Every function here reads the database through a connection the caller
opened read-only, reads data/adjustments.yml, data/asta-state.json and the
dossiers, and touches no network. `board` prices the pinned run against the
mirrored auction as last seen (or an empty one under the run's own league
settings), `explain` reads one player's trace, `replay` runs a captured
session through the whole pipeline (the rehearsal harness), `adjust`
appends a belief and shows what it moved, `close` copies the state file to
records/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.valuation import UnknownScenarioError
from fantaclaude.asta.adjustments import (
    Adjustment,
    AdjustmentLayer,
    AdjustmentsError,
    append_adjustment,
    file_sha256,
    load_adjustments,
    resolve,
)
from fantaclaude.asta.advisor import Board, TeamMapping, derive
from fantaclaude.asta.auction import Auction
from fantaclaude.asta.pinned import (
    PinnedPlayer,
    PinnedRun,
    PinnedRunError,
    load_pinned_run,
)
from fantaclaude.asta.pricing import explain as explain_price
from fantaclaude.asta.session import SessionError, SessionSettings, session_from_feed
from fantaclaude.asta.snapshot import (
    StateFileError,
    StoredState,
    copy_to_records,
    read_state,
    render_state,
    session_code_is_path,
    write_state,
)
from fantaclaude.asta.state import (
    AuctionState,
    CostEdited,
    Event,
    LotSelected,
    SaleAdded,
    SaleRemoved,
    SettingsChanged,
    Snapshot,
    SnapshotError,
    StatusChanged,
    Team,
    apply_snapshot,
    read_snapshots,
)
from fantaclaude.commands.ingest import NotReady
from fantaclaude.ingest.names import match_listone
from fantaclaude.kb.participants import Participant, ParticipantError, load_participants
from fantaclaude.timeutil import utc_now
from fantaclaude.values import json_safe


class UsageError(ValueError):
    """A flag names something that does not exist -- a bad argument, not a bad file (exit 2)."""


@dataclass(frozen=True)
class AstaPaths:
    db: Path
    adjustments: Path
    state: Path
    records: Path
    kb: Path


def open_run(con: duckdb.DuckDBPyConnection, run_id: str | None = None) -> PinnedRun:
    try:
        return load_pinned_run(con, run_id)
    except PinnedRunError as exc:
        raise NotReady(str(exc)) from None


def load_layer(path: Path, run: PinnedRun) -> AdjustmentLayer:
    try:
        adjustments = load_adjustments(path)
    except AdjustmentsError as exc:
        raise NotReady(str(exc)) from None
    return resolve(adjustments, run.candidates(), sha256=file_sha256(path))


def load_dossiers(kb_dir: Path) -> dict[str, Participant]:
    try:
        return {p.nick: p for p in load_participants(kb_dir)}
    except ParticipantError as exc:
        raise NotReady(str(exc)) from None


def _team(teams: tuple[Team, ...], key: str) -> Team:
    by_label = [t for t in teams if t.label.casefold() == key.casefold()]
    if len(by_label) == 1:
        return by_label[0]
    if key.isdigit():
        by_id = [t for t in teams if t.team_id == int(key)]
        if by_id:
            return by_id[0]
    labels = ", ".join(f"{t.team_id} ({t.label})" for t in teams)
    if len(by_label) > 1:
        raise UsageError(f"{key!r} names {len(by_label)} teams; use the id: {labels}")
    raise UsageError(f"no team {key!r}; the session has {labels}")


def resolve_mapping(teams: tuple[Team, ...], *, me: str | None, maps: tuple[str, ...],
                    participants: dict[str, Participant],
                    remembered: dict[int, str] | None = None) -> TeamMapping:
    """--me names my team by label or id; --map team=nick binds a team to a dossier.

    With no session the league's teams are numbered and nothing has a label,
    so both flags take a team number and mine is 0 unless told otherwise.

    `remembered` is the mapping the state file carries, and the flags are
    layered *over* it: naming my team, or binding one more rival to his
    dossier, must not silently unbind every other rival -- which is exactly
    when `--map` gets typed, mid-auction, and the only sign would have been
    the pressure quietly going neutral for everyone else.
    """
    def team_of(key: str, entry: str) -> int:
        if not teams:
            if not key.isdigit():
                raise UsageError(f"--map takes team=nick, with a team number when there is no session, got {entry!r}")
            return int(key)
        return _team(teams, key).team_id

    nicks: dict[int, str] = dict(remembered or {})
    for entry in maps:
        key, sep, nick = entry.partition("=")
        if not sep or not nick:
            raise UsageError(f"--map takes team=nick, got {entry!r}")
        team_id = team_of(key, entry)
        if nick not in participants:
            raise UsageError(f"no dossier for {nick!r} under kb/league/participants; known: {sorted(participants)}")
        nicks[team_id] = nick
    if not teams:
        if me is not None and not me.isdigit():
            raise UsageError(f"--me must be a team number when there is no session, got {me!r}")
        return TeamMapping(int(me) if me is not None else 0, nicks)
    if me is None:
        if len(teams) != 1:
            raise UsageError("which team is mine? --me one of " + ", ".join(f"{t.team_id} ({t.label})" for t in teams))
        mine = teams[0].team_id
    else:
        mine = _team(teams, me).team_id
    return TeamMapping(mine, nicks)


def _stored(paths: AstaPaths, state_file: Path | None, fresh: bool) -> tuple[StoredState | None, Path]:
    """The mirrored auction the board prices, or None for an empty one.

    An *explicit* `--state` naming nothing is a bad argument (exit 2), never
    an empty board: `state_file or paths.state` erased the difference, so a
    typo'd `--state rehearsal.jsno` read exactly like "no state file yet" --
    500 credits, no picks, exit 0, mid-auction, with nothing saying the file
    named was never opened. `replay` already refuses a missing session file
    the same way. Only the implicit `data/asta-state.json` default may be
    absent, because before the first mirror it always is.

    `--fresh` wins over both, including alongside an explicit `--state`: it
    asks for an empty auction under the run's own league settings and reads
    no state file at all, so there is no file whose absence could mislead --
    the board it prints is the board that was asked for either way."""
    path = state_file or paths.state
    if fresh:
        return None, path
    if not path.is_file():
        if state_file is not None:
            raise UsageError(f"--state names {path}, which is not a file")
        return None, path
    try:
        return read_state(path), path
    except StateFileError as exc:
        raise NotReady(str(exc)) from None


def _settings(snapshot: Snapshot | None, run: PinnedRun) -> SessionSettings:
    if snapshot is None or not snapshot.settings:
        return run.league
    try:
        return session_from_feed(snapshot.settings, team_count=len(snapshot.teams) or run.league.team_count)
    except SessionError as exc:
        raise NotReady(f"the session's settings cannot be read: {exc}") from None


def _player(run: PinnedRun, key: str) -> PinnedPlayer:
    if key.isdigit() and int(key) in run.players:
        return run.players[int(key)]
    match = match_listone(key, run.candidates())
    if match.player_id is None:
        named = {p.player_id: p.name for p in run.players.values()}
        close = ", ".join(repr(named[i]) for i in match.candidates if i in named)
        raise UsageError(f"{key!r} is not a player of run {run.run_id}"
                         + (f"; did you mean {close}?" if close
                            else "; write him the listone's way, or give his id"))
    return run.players[match.player_id]


def _check_mapping(board: Board, mapping: TeamMapping) -> None:
    """A --map key the board has no ledger for is a bad argument (exit 2).

    With a session `_team` already refuses an unknown key, but with no session
    the key is only required to be a number -- so `--map 9=Marco` on an
    eight-team league bound a nick nothing ever reads: no dossier applied, no
    pressure changed, no problem line, and exit 0 as though it had worked. The
    exit-code contract names "a --map that names no team" as a usage error, so
    it is refused here rather than absorbed."""
    unknown = sorted(team_id for team_id in mapping.nicks if team_id not in board.ledgers)
    if not unknown:
        return
    known = ", ".join(f"{t} ({ledger.label})" for t, ledger in sorted(board.ledgers.items()))
    raise UsageError(f"--map names team(s) {unknown}, which this board has no ledger for; the teams are {known}")


@dataclass(frozen=True)
class BoardReport:
    board: Board
    run: PinnedRun
    source: str
    mapping: TeamMapping
    notes: tuple[str, ...]
    top: int = 5

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"run": self.run.describe(), "source": self.source, "mapping": self.mapping.to_dict(),
                          "notes": list(self.notes), "tiers": self.board.tiers(self.top), **self.board.to_dict()})


def board_report(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, run_id: str | None = None,
                 scenario: str | None = None, state_file: Path | None = None, fresh: bool = False,
                 me: str | None = None, maps: tuple[str, ...] = (), top: int = 5) -> BoardReport:
    run = open_run(con, run_id)
    layer = load_layer(paths.adjustments, run)
    participants = load_dossiers(paths.kb)
    stored, path = _stored(paths, state_file, fresh)
    notes: list[str] = []
    if stored is None:
        state, settings = AuctionState.empty(), run.league
        mapping = resolve_mapping((), me=me, maps=maps, participants=participants)
        source = "an empty auction under the run's league settings"
    else:
        state, _ = apply_snapshot(AuctionState.empty(), stored.snapshot)
        settings = _settings(stored.snapshot, run)
        mapping = (stored.mapping if me is None and not maps
                   else resolve_mapping(stored.snapshot.teams, me=me or str(stored.mapping.mine), maps=maps,
                                        participants=participants, remembered=stored.mapping.nicks))
        source = f"state file {path} (written {stored.written_at}, session {stored.session_code or '?'})"
        if stored.run_id != run.run_id:
            notes.append(f"the state file was written under run {stored.run_id}; this board prices run {run.run_id}")
    try:
        board = derive(state, run=run, settings=settings, layer=layer, mapping=mapping, scenario=scenario,
                       participants=participants)
    except UnknownScenarioError as exc:
        raise UsageError(str(exc)) from None
    if stored is not None and board.scenario != stored.scenario:
        # The state file records the scenario the mirrored auction was priced
        # under, and the board resolves its own (the flag, else the run's
        # first). A rehearsal written under value-hunting read back as balanced
        # is a model swap mid-auction, which is exactly when it goes unnoticed.
        # Noted rather than adopted, for the same reason the run_id above is:
        # what the board priced is the board's to state, and the operator
        # chooses the model -- a state file must not quietly select one.
        notes.append(f"the state file was written under scenario {stored.scenario}; "
                     f"this board prices scenario {board.scenario}")
    _check_mapping(board, mapping)
    return BoardReport(board, run, source, mapping, tuple(notes), top)


@dataclass(frozen=True)
class ExplainReport:
    player: PinnedPlayer
    report: BoardReport
    trace: dict[str, Any] | None
    sold_to: int | None
    cost: int | None
    pressure: dict[str, Any] | None
    adjustments: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"run": self.report.run.describe(), "source": self.report.source, "player": self.player.to_dict(),
                          "sold_to": self.sold_to, "cost": self.cost, "trace": self.trace, "pressure": self.pressure,
                          "adjustments": list(self.adjustments), "problems": list(self.report.board.problems)})


def explain_report(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, player: str, **board_kw: Any) -> ExplainReport:
    report = board_report(con, paths=paths, **board_kw)
    who = _player(report.run, player)
    board = report.board
    pick = board.state.picks.get(who.player_id)
    trace = explain_price(board.pricing, who.player_id) if who.player_id in board.pricing.prices else None
    pressure = board.pressure[who.player_id].to_dict() if who.player_id in board.pressure else None
    applied = tuple(e.adjustment.describe() for e in board.layer.entries if e.player_id == who.player_id)
    return ExplainReport(who, report, trace, None if pick is None else pick.team_id, None if pick is None else pick.cost,
                         pressure, applied)


def describe_event(event: Event, run: PinnedRun, labels: dict[int, str]) -> str:
    def name(pid: int | None) -> str:
        if pid is None:
            return "none"
        player = run.players.get(pid)
        return f"{player.name} ({player.role_class})" if player else f"player {pid} (not in the run)"

    if isinstance(event, SaleAdded):
        return f"+ {name(event.player_id)} -> {labels.get(event.team_id, f'team {event.team_id}')} for {event.cost}"
    if isinstance(event, SaleRemoved):
        return f"- {name(event.player_id)} <- {labels.get(event.team_id, f'team {event.team_id}')} ({event.cost}, undone)"
    if isinstance(event, CostEdited):
        return f"= {name(event.player_id)}: {event.before} -> {event.after}"
    if isinstance(event, LotSelected):
        return f"lot: {name(event.player_id)}"
    if isinstance(event, SettingsChanged):
        return "settings: " + "; ".join(f"{path} {before!r} -> {after!r}" for path, before, after in event.changes)
    if isinstance(event, StatusChanged):
        return f"status {event.status}, locked {event.locked}"
    return repr(event)


@dataclass(frozen=True)
class ReplayStep:
    index: int
    events: tuple[str, ...]
    credits: int
    picks: int
    lot: dict[str, Any] | None
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "events": list(self.events), "credits": self.credits, "picks": self.picks,
                "lot": self.lot, "problems": list(self.problems)}


@dataclass(frozen=True)
class ReplayReport:
    steps: tuple[ReplayStep, ...]
    board: Board
    run: PinnedRun
    mapping: TeamMapping
    written: Path | None

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"run": self.run.describe(), "mapping": self.mapping.to_dict(),
                          "steps": [s.to_dict() for s in self.steps],
                          "written": None if self.written is None else str(self.written),
                          "tiers": self.board.tiers(), **self.board.to_dict()})


def replay_report(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, file: Path, run_id: str | None = None,
                  scenario: str | None = None, me: str | None = None, maps: tuple[str, ...] = (),
                  write_state_to: Path | None = None, now: datetime | None = None) -> ReplayReport:
    run = open_run(con, run_id)
    layer = load_layer(paths.adjustments, run)
    participants = load_dossiers(paths.kb)
    if not file.is_file():
        raise UsageError(f"{file} is not a file")
    try:
        snapshots = read_snapshots(file)
    except (OSError, UnicodeDecodeError, SnapshotError) as exc:
        raise NotReady(str(exc)) from None
    if not snapshots:
        raise UsageError(f"{file} holds no snapshots")
    mapping = resolve_mapping(snapshots[0].teams, me=me, maps=maps, participants=participants)
    try:
        auction = Auction(run, mapping, layer=layer, scenario=scenario, participants=participants)
    except UnknownScenarioError as exc:
        raise UsageError(str(exc)) from None
    steps: list[ReplayStep] = []
    for i, snap in enumerate(snapshots):
        try:
            result = auction.mutate(snap)
        except SessionError as exc:
            raise NotReady(f"{file}: snapshot {i}: {exc}") from None
        board = result.board
        labels = {t: ledger.label for t, ledger in board.ledgers.items()}
        steps.append(ReplayStep(i, tuple(describe_event(e, run, labels) for e in result.events), board.me.credits,
                                len(board.state.picks), None if board.lot is None else board.lot.to_dict(),
                                board.problems))
    _check_mapping(auction.board, mapping)          # before anything is written: a bad flag writes no state file
    written = None
    if write_state_to is not None:
        write_state(write_state_to, render_state(auction.board, session_code=None, written_at=now or utc_now()))
        written = write_state_to
    return ReplayReport(tuple(steps), auction.board, run, mapping, written)


def _class_view(board: Board, cls: str, top: int = 5) -> list[dict[str, Any]]:
    return board.tiers(top).get(cls, [])


@dataclass(frozen=True)
class AdjustReport:
    adjustment: Adjustment
    player_id: int | None
    path: Path
    count: int
    before: dict[str, Any]
    after: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"adjustment": self.adjustment.to_entry(), "described": self.adjustment.describe(),
                          "player_id": self.player_id, "path": str(self.path), "count": self.count,
                          "before": self.before, "after": self.after})


def _effect(board: Board, player_id: int | None, cls: str) -> dict[str, Any]:
    price = None if player_id is None else board.pricing.prices.get(player_id)
    return {"band": None if price is None else price.band.to_dict(), "class": cls, "top": _class_view(board, cls),
            "composition": board.pricing.composition, "targets_departed": list(board.pricing.targets_departed),
            "problems": list(board.problems)}


def adjust(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, adjustment: Adjustment, run_id: str | None = None,
           scenario: str | None = None, state_file: Path | None = None, fresh: bool = False) -> AdjustReport:
    """Append one adjustment and show what it moved. The player is resolved
    against the pinned run first: an entry that resolves to nobody is a bad
    argument here, refused and never written, rather than appended inert."""
    run = open_run(con, run_id)
    player_id = None
    if adjustment.kind != "target":
        probe = resolve([adjustment], run.candidates())
        if probe.problems:
            raise UsageError(probe.problems[0])
        player_id = probe.entries[0].player_id
    cls = adjustment.role_class if adjustment.kind == "target" else run.players[player_id].role_class
    kw = {"run_id": run_id, "scenario": scenario, "state_file": state_file, "fresh": fresh}
    before = board_report(con, paths=paths, **kw)
    try:
        entries = append_adjustment(paths.adjustments, adjustment)
    except AdjustmentsError as exc:
        raise NotReady(str(exc)) from None
    after = board_report(con, paths=paths, **kw)
    return AdjustReport(adjustment, player_id, paths.adjustments, len(entries), _effect(before.board, player_id, cls),
                        _effect(after.board, player_id, cls))


def close_auction(paths: AstaPaths, *, session_code: str | None = None) -> Path:
    """Copy the state file to records/ when the auction closes (live-event
    requirement 5): the days between the room and the transfer are not spent
    with the only record of what was paid on one gitignored disk.

    The copy is named by the state file's own `written_at`, not by the clock
    at close, so closing twice over an unchanged state file writes one record
    rather than two identical ones under two names (`copy_to_records`)."""
    if not paths.state.is_file():
        raise NotReady(f"no state file at {paths.state} -- nothing mirrored yet")
    if session_code is not None and session_code_is_path(session_code):
        # --session becomes one path component under records/asta/: a value
        # with a separator in it would write outside records/ entirely. A
        # typo guard, and the code the league shows never contains one.
        #
        # copy_to_records refuses the same value at the sink, so the state
        # file's own session.code is covered too -- but there it is a torn
        # file (exit 3), and here it is a bad flag (exit 2). Same predicate,
        # two verdicts: this one answers first, so a typed --session never
        # reaches the sink and never reports as "not ready".
        raise UsageError(f"--session {session_code!r} is a path, not a session code; it names one file under records/asta/")
    try:
        stored = read_state(paths.state)
        written_at = datetime.fromisoformat(stored.written_at)
    except StateFileError as exc:
        raise NotReady(str(exc)) from None
    except ValueError as exc:
        raise NotReady(f"{paths.state}: written_at {stored.written_at!r} is not a timestamp: {exc}") from None
    try:
        return copy_to_records(paths.state, paths.records, session_code=session_code or stored.session_code,
                               written_at=written_at)
    except StateFileError as exc:
        raise NotReady(str(exc)) from None
