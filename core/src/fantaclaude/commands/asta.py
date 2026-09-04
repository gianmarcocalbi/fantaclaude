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

import json
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
    newest_run_id,
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
    state_from_snapshot,
)
from fantaclaude.asta.transfer import Reconciliation, reconcile
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


def player_of(run: PinnedRun, key: str) -> PinnedPlayer:
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


_player = player_of


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
    kw = {"run_id": run_id, "scenario": scenario, "state_file": state_file, "fresh": fresh}
    before = board_report(con, paths=paths, **kw)
    # The class shown is the one the board prices him under -- the re-pinned
    # one when my roster moved him off the run's pin -- else the run's.
    priced = None if player_id is None else before.board.pricing.prices.get(player_id)
    cls = (adjustment.role_class if adjustment.kind == "target"
           else priced.role_class if priced is not None else run.players[player_id].role_class)
    try:
        entries = append_adjustment(paths.adjustments, adjustment)
    except AdjustmentsError as exc:
        raise NotReady(str(exc)) from None
    after = board_report(con, paths=paths, **kw)
    return AdjustReport(adjustment, player_id, paths.adjustments, len(entries), _effect(before.board, player_id, cls),
                        _effect(after.board, player_id, cls))


# One address, by construction. `asta serve` binds exactly this and takes no
# --host/--port, because the number has to agree in six places at once --
# .mcp.json's URL, SERVER_URL_DEFAULT (the CLI proxy), cli/app.py's
# SERVER_OPTION literal, web/vite.config.ts's /api and /ws proxy targets, and
# the docs -- and a flag is the only thing that could make them disagree. When
# it did, it broke three mechanisms silently and at once: `asta adjust` stopped
# reaching the server and became a second writer of data/adjustments.yml, the
# MCP config pointed at a dead port, and `poe web-dev`'s proxy missed. No
# workflow needs another port, and --host's only non-default value would serve
# the live board to the room, which the spec calls a non-goal.
#
# These constants live here rather than in commands/serve.py so the light
# paths (the CLI proxy, the tests) can read them without importing
# fastapi/uvicorn; serve.py imports them, never the other way round.
SERVE_HOST = "127.0.0.1"
SERVE_PORT = 8765
SERVER_URL_DEFAULT = f"http://{SERVE_HOST}:{SERVE_PORT}"


def _server_payload(resp) -> dict[str, Any]:
    try:
        body = resp.json()                      # parsed once: the 200 path read it a second time
    except ValueError:
        body = None
    if resp.status_code == 200:
        if not isinstance(body, dict):
            raise NotReady(f"the server answered 200 with a body this client cannot read: {resp.text[:120]!r}")
        return body
    detail = body.get("detail") if isinstance(body, dict) else None
    message = detail or f"the server answered {resp.status_code}"
    if resp.status_code == 422:
        raise UsageError(message)
    raise NotReady(message)          # 409 pending, 400 malformed file or unreadable session settings, anything else


def _exchange_failed(url: str, what: str, exc: Exception) -> NotReady:
    """Every httpx failure that is *not* "nothing came up on the socket".

    A read timeout (a re-derive plus the fsync'd write running long), a
    RemoteProtocolError (the server restarted mid-request), an
    UnsupportedProtocol or InvalidURL (a typo'd --server) all propagated past
    `_asta_errors` -- which maps NotReady, duckdb.Error, UsageError and
    UnknownScenarioError, and nothing else -- so they printed a Python
    traceback and exited 1, mid-auction. They are "not ready" (exit 3), and the
    message has to say what the ConnectError path can say and this one cannot:
    the server may well have taken the write, so the CLI is not going to append
    behind its back."""
    return NotReady(f"{url} was reached but the {what} exchange failed: {exc!r}\n"
                    f"nothing was written here -- while `asta serve` runs it is the one writer of the "
                    f"adjustments file, and this command will not append behind its back. Check the "
                    f"serving terminal, then retry (or stop the server and run this again).")


def server_adjust(url: str, adjustment: Adjustment, timeout: float = 5.0) -> dict[str, Any] | None:
    """POST the adjustment to a running `asta serve`; None when nothing is
    listening there -- the offline path appends directly and stays the one
    writer. While a server runs, it is the one writer (spec, "Live
    adjustments"), so the CLI never touches the file behind its back."""
    import httpx

    try:
        resp = httpx.post(f"{url}/api/adjust", json=adjustment.to_entry(), timeout=timeout)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        # Both mean the connection never came up, so nothing is serving and
        # the offline path is safe. A *read* timeout is deliberately not here:
        # the server accepted, may well have written the file, and falling
        # back would make a second writer of it.
        return None
    except (httpx.HTTPError, httpx.InvalidURL) as exc:   # InvalidURL is not an HTTPError; both end here
        raise _exchange_failed(url, "adjust", exc) from None
    return _server_payload(resp)


def server_refresh(url: str, timeout: float = 30.0) -> dict[str, Any]:
    """Tell a running `asta serve` to reread adjustments.yml and the dossiers
    and re-price the board. Unlike `server_adjust`, refresh has no offline
    fallback -- it is a live-server action, so nothing listening is NotReady."""
    import httpx

    try:
        resp = httpx.post(f"{url}/api/refresh", timeout=timeout)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise NotReady(f"no `asta serve` is listening at {url} -- refresh re-prices a live board; "
                       f"offline boards recompute on every command") from None
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise _exchange_failed(url, "refresh", exc) from None
    return _server_payload(resp)


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


class TransferMismatch(RuntimeError):
    """--prune asked for on a diff that is not clean."""


def _min_bid(settings: dict[str, Any]) -> int:
    """The session's minimum bid, read off `settings.minimumBid` -- which the
    live feed sends as a bare int in some sessions and, confirmed by
    `asta_session_sample.jsonl`, as `{"type": "fixed", "value": N}` in
    others. An `isinstance(..., int)` test against the raw value is always
    False for the second shape and silently falls back to 1 with no error
    (review finding 2, 2026-09-04) -- reading a league with a different
    minimum bid right, by coincidence, only for leagues where it happens to
    be 1. Neither shape present defaults to 1, same as before."""
    raw = settings.get("minimumBid")
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, dict):
        value = raw.get("value")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 1


def _diff_summary(result: Reconciliation) -> str:
    """What is not clean, named -- so a --prune refusal says *why*, not just
    that it refused. `verify_transfer` without --prune prints the same facts
    at length; this is the one line that has to fit an error message."""
    problems: list[str] = []
    for t in result.teams:
        if t.missing_in_lega:
            problems.append(f"{t.lega_team_name}: {len(t.missing_in_lega)} missing in the lega")
        if t.cost_differences:
            problems.append(f"{t.lega_team_name}: {len(t.cost_differences)} cost differs")
        if t.extra_in_lega:
            problems.append(f"{t.lega_team_name}: {len(t.extra_in_lega)} dear extra")
    problems += [f"{name}: not in the room ({size} players)" for _, name, size in result.lega_not_in_room if size]
    if result.mirror_unmatched:
        problems.append(f"{len(result.mirror_unmatched)} room team(s) unmatched")
    problems += list(result.ambiguous)
    return "; ".join(problems) if problems else "not clean"


@dataclass(frozen=True)
class VerifyReport:
    state_path: Path
    snapshot_id: int
    fetched_at: datetime
    result: Reconciliation
    names: dict[int, str]
    my_team_leaf: str | None
    my_team_hint: str | None
    pruned: bool

    def to_dict(self) -> dict[str, Any]:
        r = self.result
        return {"state": str(self.state_path), "roster_snapshot": self.snapshot_id,
                "rosters_fetched_at": self.fetched_at.isoformat(sep=" ", timespec="minutes"),
                "teams": [t.to_dict() for t in r.teams],
                "lega_not_in_room": [list(x) for x in r.lega_not_in_room],
                "mirror_unmatched": [list(x) for x in r.mirror_unmatched], "ambiguous": list(r.ambiguous),
                "my_team": None if r.my_team is None else {"lega_team_id": r.my_team[0], "name": r.my_team[1],
                                                             "leaf": self.my_team_leaf},
                "my_team_hint": self.my_team_hint,
                "player_names": {str(k): v for k, v in self.names.items()},
                "clean": r.clean, "pruned": self.pruned}


def verify_transfer(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, state_file: Path | None = None,
                    prune: bool = False) -> VerifyReport:
    """The lega's latest roster snapshot against the mirrored auction. Reports;
    `--prune` deletes data/asta-state.json alone, on a clean diff, never a
    `--state` file and never anything under records/."""
    if prune and state_file is not None:
        raise UsageError("--prune removes data/asta-state.json only; it does not apply to a --state file")
    stored, path = _stored(paths, state_file, fresh=False)
    if stored is None:
        raise NotReady(f"no state file at {path} -- nothing mirrored to verify; pass --state records/asta/<file>.json")
    state = state_from_snapshot(stored.snapshot)
    mirror: dict[int, dict[int, int]] = {t.team_id: {} for t in stored.snapshot.teams}
    for pick in state.picks.values():
        mirror.setdefault(pick.team_id, {})[pick.player_id] = pick.cost
    labels = {t.team_id: t.label for t in stored.snapshot.teams}
    labels.update(stored.mapping.nicks)
    snapshot = con.execute("SELECT snapshot_id, fetched_at, teams FROM roster_snapshots "
                           "ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    if snapshot is None:
        raise NotReady("no roster snapshot -- run `fantaclaude ingest rosters` once the admin has transferred the auction")
    snapshot_id, fetched_at, teams_json = snapshot
    teams = json.loads(teams_json) if isinstance(teams_json, str) else teams_json
    lega: dict[int, dict[int, int]] = {int(t["id"]): {} for t in teams}      # every team, the empty ones included
    names: dict[int, str] = {int(t["id"]): str(t["name"]) for t in teams}
    for team_id, player_id, cost in con.execute(
            "SELECT team_id, player_id, cost FROM v_rosters_current").fetchall():
        lega.setdefault(int(team_id), {})[int(player_id)] = int(cost)
    if not any(lega.values()):
        raise NotReady("the lega's rosters are all empty -- the admin has not transferred the auction yet")
    settings = stored.snapshot.settings or {}
    min_bid = _min_bid(settings)
    result = reconcile(mirror, lega, me=stored.mapping.mine, labels=labels, names=names, min_bid=min_bid)
    player_names = {int(pid): str(name) for pid, name in con.execute(
        "SELECT player_id, name FROM v_players_current").fetchall()}
    leaf = None
    if result.my_team is not None:
        note = (f"{result.my_team[1]} -- the lega team the mirror's 'me' reconciled with, player for player")
        # A league team name is free text off the room, and a plain YAML scalar
        # breaks on a ": " inside it (reads as a nested key) or on a leading
        # quote (reads as the start of a quoted scalar). Single-quoting the
        # whole note -- with embedded "'" doubled, the YAML escape for it --
        # is safe against both, whatever the team is called.
        quoted_note = "'" + note.replace("'", "''") + "'"
        leaf = (f"my_team:\n  value: {result.my_team[0]}\n  source: verify-transfer\n"
                f"  verified_on: {utc_now():%Y-%m-%d}\n  note: {quoted_note}")
    hint = None
    if result.my_team is None and not mirror.get(stored.mapping.mine):
        # The one case worth explaining plainly, distinct from a genuine
        # UNMATCHED room team (already reported): `me` bought nothing, so it
        # has zero overlap with everything and cannot be told apart from a
        # stranger's empty team by roster alone (review finding 1,
        # 2026-09-04) -- no fallback infers it, so the maintainer has to say
        # which lega team is his.
        hint = ("my room team ('me') bought nothing in the room, so it has no overlap to match by; "
               "paste the lega team id into league.yml's my_team leaf by hand")
    pruned = False
    if prune:
        if not result.clean:
            raise TransferMismatch(f"the diff is not clean ({_diff_summary(result)}); nothing deleted -- "
                                   f"see `asta verify-transfer` without --prune for the detail")
        path.unlink()
        pruned = True
    return VerifyReport(path, int(snapshot_id), fetched_at, result, player_names, leaf, hint, pruned)


@dataclass(frozen=True)
class MarketReport:
    run_id: str
    scenario: str
    source: str
    snapshot_id: int
    classes: list[dict[str, Any]]
    overall: dict[str, Any]
    unpriced: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "scenario": self.scenario, "source": self.source, "snapshot_id": self.snapshot_id,
                "classes": list(self.classes), "overall": dict(self.overall), "unpriced": dict(self.unpriced)}


def _ratio(num: float, den: float) -> float | None:
    return None if not den else num / den


def _newest_closing_state(records_dir: Path) -> Path | None:
    files = sorted(p for p in (records_dir / "asta").glob("*.json") if not p.name.endswith("-bids.json"))
    return files[-1] if files else None


def market_prices(con: duckdb.DuckDBPyConnection, *, paths: AstaPaths, run_id: str | None = None,
                  scenario: str | None = None) -> MarketReport:
    """What the room paid over what the run expected, per class, off the
    earliest non-empty roster snapshot of the season (spec: `v_market_prices`).
    The run and scenario each default independently to the pair the newest
    closing state under records/asta names -- the board the night was priced
    against -- and `source` reports where *each half* actually came from, so
    a flag pinning one of the two while the other is defaulted never reads
    as if both were pinned, or both defaulted from the same place."""
    # run_source/scenario_source are tracked separately, never folded into one
    # variable early: `--run` with no `--scenario` and no closing state must
    # not claim the scenario was pinned too (or vice-versa) -- and a closing
    # state that only fills the *other* half must not be credited for the one
    # that was already pinned by flag.
    run_source = "--run" if run_id is not None else None
    scenario_source = "--scenario" if scenario is not None else None
    if run_id is None or scenario is None:
        record = _newest_closing_state(paths.records)
        if record is not None:
            stored = read_state(record)
            label = (record.relative_to(paths.records.parent).as_posix()
                     if record.is_relative_to(paths.records.parent) else str(record))
            if run_id is None:
                run_id, run_source = stored.run_id, label
            if scenario is None:
                scenario, scenario_source = stored.scenario, label
    if run_id is None:
        run_id = newest_run_id(con)
        run_source = "the newest run"
        if run_id is None:
            raise NotReady("no valuation run -- run `fantaclaude rank`")
    if scenario is None:
        row = con.execute("SELECT scenarios[1] FROM valuation_runs WHERE run_id = ?", [run_id]).fetchone()
        if row is None:
            raise NotReady(f"run {run_id!r} is not in valuation_runs")
        scenario = str(row[0])
        scenario_source = "the run's default scenario"
    # Equal halves (both pinned by the same closing state file) collapse to
    # one label rather than doubling it; unequal halves are shown side by
    # side so a mixed pair -- one pinned by flag, the other defaulted --
    # never gets misreported as either "all pinned" or "all defaulted".
    source = run_source if run_source == scenario_source else f"{run_source}/{scenario_source}"
    # Scoped to the run's own season (as v_market_prices already joins), not
    # `v_rosters_first` bare -- that view groups by (league_id, season_id), so
    # an unscoped min() picks the first snapshot of ANY season once a second
    # one exists (review finding 1, 2026-09-04). `first` is the snapshot this
    # report is about; `unpriced` below is pinned to that same snapshot_id so
    # the reported id and the numbers provably describe one snapshot.
    first = con.execute(
        "SELECT min(f.snapshot_id) FROM v_rosters_first f JOIN valuation_runs vr ON vr.season_id = f.season_id "
        "WHERE vr.run_id = ?", [run_id]).fetchone()[0]
    if first is None:
        raise NotReady("no roster snapshot with players -- run `fantaclaude ingest rosters` once the admin has transferred the auction")
    rows = con.execute(
        "SELECT role_class, count(*), sum(paid), sum(expected_price), sum(coalesce(quot_mantra, 0)) FROM v_market_prices "
        "WHERE run_id = ? AND scenario = ? GROUP BY role_class ORDER BY role_class", [run_id, scenario]).fetchall()
    classes = [{"role_class": cls, "players": int(n), "paid": int(paid), "expected": int(exp),
                "paid_over_expected": _ratio(paid, exp), "quotazione": int(quot),
                "paid_over_quotazione": _ratio(paid, quot)} for cls, n, paid, exp, quot in rows]
    n, paid, exp, quot = (sum(c[k] for c in classes) for k in ("players", "paid", "expected", "quotazione"))
    overall = {"players": n, "paid": paid, "expected": exp, "paid_over_expected": _ratio(paid, exp),
               "quotazione": quot, "paid_over_quotazione": _ratio(paid, quot)}
    unpriced = con.execute(
        "SELECT count(*), coalesce(sum(cost), 0) FROM v_rosters_first f WHERE f.snapshot_id = ? AND f.player_id NOT IN "
        "(SELECT player_id FROM valuation_prices WHERE run_id = ? AND scenario = ?)", [first, run_id, scenario]).fetchone()
    return MarketReport(run_id, scenario, source, int(first), classes, overall,
                        {"players": int(unpriced[0]), "paid": int(unpriced[1])})
