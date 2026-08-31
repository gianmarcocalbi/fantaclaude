"""fantaclaude asta serve: the night's one process (spec, "Dashboard
architecture" and "One process in production"). Pins the run and names it,
loads the layer and the dossiers, chooses exactly one source — the live
feed, a replayed capture, or the state file — and serves the dashboard,
the REST API, the WebSocket and the fantaclaude-asta MCP from one uvicorn.

The feed dying is not the server dying: a fatal FeedError is reported and
the board stands on its last state (the printed tier board is the
backstop); transport drops reconnect with backoff inside the adapter.
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


async def _replay_task(server: AstaServer, snapshots: tuple[Snapshot, ...], speed: float) -> None:
    for snap in snapshots:
        await server.on_snapshot(snap)
        await asyncio.sleep(REPLAY_INTERVAL / speed)


async def _feed_task(server: AstaServer, plan: ServePlan) -> None:
    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(plan.session_code, client=client, on_snapshot=server.on_snapshot,
                            on_status=server.set_feed_status, capture=plan.capture_path)
        try:
            await feed.run()
        except FeedError as exc:
            typer.echo(f"the feed is gone: {exc} — the board stands on its last state", err=True)
            await server.set_feed_status(OFFLINE)


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
