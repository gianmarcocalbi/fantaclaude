"""fantaclaude asta serve: the night's one process (spec, "Dashboard
architecture" and "One process in production"). Pins the run and names it,
loads the layer and the dossiers, chooses exactly one source — the live
feed, a replayed capture, or the state file — and serves the dashboard,
the REST API, the WebSocket and the fantaclaude-asta MCP from one uvicorn.

The feed dying is not the server dying: anything fatal to the source task —
a FeedError, but equally a SessionError out of a settings node that changed
mid-auction or an OSError out of the state file — is reported on stderr, the
feed dot goes red, and the board stands on its last state (the printed tier
board is the backstop). Transport drops reconnect with backoff inside the
adapter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx
import typer
import uvicorn

from fantaclaude.analysis.valuation import UnknownScenarioError
from fantaclaude.api.app import create_app
from fantaclaude.api.serve import AstaServer
from fantaclaude.asta.mcp import build_mcp
from fantaclaude.asta.snapshot import StateFileError, read_state
from fantaclaude.asta.state import Snapshot, SnapshotError, read_snapshots
from fantaclaude.commands.asta import (
    AstaPaths,
    UsageError,
    load_dossiers,
    load_layer,
    open_run,
    resolve_mapping,
)
from fantaclaude.commands.ingest import NotReady
from fantaclaude.ingest.asta_live import (
    OFFLINE,
    AstaLiveFeed,
    FeedError,
    check_session_code,
)
from fantaclaude.paths import asta_captures_dir, web_dist_dir
from fantaclaude.timeutil import utc_now

REPLAY_INTERVAL = 2.0


@dataclass(frozen=True)
class ServeOptions:
    session: str | None = None
    replay: Path | None = None
    speed: float = 1.0
    state: Path | None = None
    run_id: str | None = None
    scenario: str | None = None
    me: str | None = None
    maps: tuple[str, ...] = ()
    host: str = "127.0.0.1"
    port: int = 8765
    capture: bool = True


@dataclass(frozen=True)
class ServePlan:
    server: AstaServer
    mode: str
    session_code: str | None
    snapshots: tuple[Snapshot, ...]
    stored_snapshot: Snapshot | None
    capture_path: Path | None
    notes: tuple[str, ...]


def prepare(con: duckdb.DuckDBPyConnection, paths: AstaPaths, opts: ServeOptions) -> ServePlan:
    sources = [name for name, given in (("--session", opts.session), ("--replay", opts.replay),
                                        ("--state", opts.state)) if given]
    if len(sources) != 1:
        raise UsageError("serve takes exactly one source: --session (the live feed), "
                         "--replay (a captured session), or --state (the state file); got "
                         + (", ".join(sources) or "none"))
    if opts.speed <= 0:
        raise UsageError(f"--speed must be positive, got {opts.speed}")
    if opts.replay is None and opts.speed != 1.0:
        raise UsageError("--speed paces a --replay; it means nothing for a live feed")
    run = open_run(con, opts.run_id)
    try:
        scenario = None if opts.scenario is None else run.scenario(opts.scenario).name
    except UnknownScenarioError as exc:
        raise UsageError(str(exc)) from None
    layer = load_layer(paths.adjustments, run)
    participants = load_dossiers(paths.kb)
    common = {"run": run, "layer": layer, "participants": participants, "scenario": scenario, "paths": paths}
    notes: list[str] = []
    if opts.session is not None:
        try:
            code = check_session_code(opts.session)
        except FeedError as exc:
            raise UsageError(str(exc)) from None
        capture = (asta_captures_dir() / f"{code}-{utc_now():%Y%m%d}.jsonl") if opts.capture else None
        server = AstaServer(**common, mode="feed", session_code=code,
                            pending_me=opts.me, pending_maps=opts.maps)
        return ServePlan(server, "feed", code, (), None, capture, ())
    if opts.replay is not None:
        if not opts.replay.is_file():
            raise UsageError(f"--replay names {opts.replay}, which is not a file")
        try:
            snapshots = tuple(read_snapshots(opts.replay))
        except (OSError, UnicodeDecodeError, SnapshotError) as exc:
            raise NotReady(str(exc)) from None
        if not snapshots:
            raise UsageError(f"{opts.replay} holds no snapshots")
        mapping = None
        if opts.me is not None or opts.maps:
            mapping = resolve_mapping(snapshots[0].teams, me=opts.me, maps=opts.maps, participants=participants)
        server = AstaServer(**common, mode="replay", session_code=None, mapping=mapping)
        return ServePlan(server, "replay", None, snapshots, None, None, ())
    state_path = opts.state
    if not state_path.is_file():
        raise UsageError(f"--state names {state_path}, which is not a file")
    try:
        stored = read_state(state_path)
    except StateFileError as exc:
        raise NotReady(str(exc)) from None
    if stored.run_id != run.run_id:
        notes.append(f"the state file was written under run {stored.run_id}; this board prices run {run.run_id}")
    mapping = (stored.mapping if opts.me is None and not opts.maps
               else resolve_mapping(stored.snapshot.teams, me=opts.me or str(stored.mapping.mine),
                                    maps=opts.maps, participants=participants,
                                    remembered=stored.mapping.nicks))
    server = AstaServer(**common, mode="state", session_code=stored.session_code, mapping=mapping)
    return ServePlan(server, "state", stored.session_code, (), stored.snapshot, None, tuple(notes))


async def _died(server: AstaServer, message: str) -> None:
    """A source task has stopped for good. Say so on stderr and turn the dot
    red -- never leave it green.

    This is the whole point of the feed dot (spec: "a silently dead feed and a
    quiet auction look identical from across the table"). The mirror is fed by
    much more than the transport: on_snapshot -> Auction.mutate ->
    session_from_feed raises SessionError on a settings node it cannot read
    (the admin changes a league setting mid-auction), write_state raises
    OSError on a full disk, describe_event can raise on its own. None of those
    is a FeedError and none is caught inside AstaLiveFeed.run(); catching
    FeedError alone let them escape the task and die as an unretrieved
    exception, while run_serve -- which does not await the side task until
    shutdown -- kept uvicorn serving a green dot over a mirror that had
    stopped forever."""
    typer.echo(message, err=True)
    try:
        await server.set_feed_status(OFFLINE)
    except Exception as exc:                    # noqa: BLE001 -- the report is the last thing left; it must land
        typer.echo(f"and the feed status could not even be broadcast: {exc!r}", err=True)


async def _replay_task(server: AstaServer, snapshots: tuple[Snapshot, ...], speed: float) -> None:
    try:
        for snap in snapshots:
            await server.on_snapshot(snap)
            await asyncio.sleep(REPLAY_INTERVAL / speed)
    except asyncio.CancelledError:
        raise                                   # shutdown, not a failure
    except Exception as exc:                    # noqa: BLE001 -- see _died
        await _died(server, f"the replay stopped: {exc!r} — the board stands on its last state")


async def _feed_task(server: AstaServer, plan: ServePlan) -> None:
    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(plan.session_code, client=client, on_snapshot=server.on_snapshot,
                            on_status=server.set_feed_status, capture=plan.capture_path)
        try:
            await feed.run()
        except asyncio.CancelledError:
            raise                               # shutdown, not a failure
        except FeedError as exc:
            await _died(server, f"the feed is gone: {exc} — the board stands on its last state")
        except Exception as exc:                # noqa: BLE001 -- see _died
            await _died(server, f"the mirror stopped: {exc!r} — the board stands on its last state")


async def run_serve(plan: ServePlan, opts: ServeOptions, paths: AstaPaths) -> None:
    mcp_app = build_mcp(plan.server, paths.db).http_app(path="/", transport="http", stateless_http=True)
    app = create_app(plan.server, web_dist=web_dist_dir(), mcp_app=mcp_app)
    config = uvicorn.Config(app, host=opts.host, port=opts.port, log_level="warning")
    uv_server = uvicorn.Server(config)
    side: asyncio.Task | None = None
    if plan.mode == "feed":
        side = asyncio.create_task(_feed_task(plan.server, plan))
    elif plan.mode == "replay":
        side = asyncio.create_task(_replay_task(plan.server, plan.snapshots, opts.speed))
    else:
        await plan.server.on_snapshot(plan.stored_snapshot)
    try:
        await uv_server.serve()          # returns on Ctrl-C; uvicorn installs the signal handlers
    finally:
        if side is not None:
            side.cancel()
            try:
                await side
            except asyncio.CancelledError:
                pass
