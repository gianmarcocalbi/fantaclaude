"""The HTTP surface of `asta serve`: REST + WebSocket + the built dashboard
+ the mounted MCP (spec, "Dashboard architecture"). One process serves all
four; every route reads or mutates through the one AstaServer, so the
dashboard, the CLI proxy, and the MCP can never disagree about state.

The WebSocket is one-directional: the server pushes `hello`, `board` and
`feed` messages; mutations arrive over REST (and are broadcast back over
the socket), which keeps exactly one mutation path and makes the socket a
pure renderer's feed.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from fantaclaude.api.models import (
    AdjustIn,
    AdjustResult,
    BoardPayload,
    HelloPayload,
    MappingIn,
    RefreshResult,
)
from fantaclaude.api.serve import AstaServer, PhaseError
from fantaclaude.asta.adjustments import AdjustmentsError, adjustment_from_entry
from fantaclaude.asta.mcp import MCP_PATH, MCP_URL_PATH
from fantaclaude.asta.session import SessionError
from fantaclaude.commands.asta import UsageError


def create_app(server: AstaServer | None, *, web_dist: Path | None = None,
               mcp_app: Any | None = None) -> FastAPI:
    lifespan = None
    if mcp_app is not None:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with mcp_app.lifespan(mcp_app):
                yield
    app = FastAPI(title="fantaclaude asta", lifespan=lifespan)

    def live() -> AstaServer:
        if server is None:
            raise HTTPException(503, "no auction is being served")
        return server

    @app.exception_handler(PhaseError)
    async def _phase(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(UsageError)
    async def _usage(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(AdjustmentsError)
    async def _adjustments(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(SessionError)
    async def _session(request, exc):
        # A session's settings node cannot be read: broken domain data found
        # while assembling a response, not a bad client input (422), not an
        # auction-phase conflict (409), and not "no server is being served"
        # (503, reserved for that alone). It is the same shape of problem as
        # a malformed adjustments.yml -- broken persisted/mirrored data
        # discovered mid-request -- so it shares that class's 400, rather
        # than adding a fifth code to the contract.
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/hello", response_model=HelloPayload)
    async def hello() -> Any:
        return live().hello()

    @app.get("/api/board", response_model=BoardPayload)
    async def board() -> Any:
        s = live()
        if s.auction is None:
            raise PhaseError("the mapping screen has not been answered; the board does not exist yet")
        return s.auction.board.to_dict()

    @app.post("/api/mapping", response_model=HelloPayload)
    async def mapping(body: MappingIn) -> Any:
        return await live().set_mapping(body.mine, dict(body.nicks))

    @app.post("/api/adjust", response_model=AdjustResult)
    async def adjust(body: AdjustIn) -> Any:
        try:
            adjustment = adjustment_from_entry(body.to_entry(), "api adjust")
        except AdjustmentsError as exc:                 # bad *input*, not a bad file: 422
            raise HTTPException(422, str(exc)) from None
        return await live().adjust(adjustment)

    @app.post("/api/refresh", response_model=RefreshResult)
    async def refresh() -> Any:
        return await live().refresh()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        s = live()
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "hello", "hello": s.hello()}, ensure_ascii=False))
        unsubscribe = s.subscribe(websocket.send_text)
        try:
            while True:
                await websocket.receive_text()          # the socket is one-directional; drain and ignore
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    if mcp_app is not None:
        # Registered *before* the mount, and before the static mount below:
        # a bare /mcp matches no route otherwise, and in production the
        # dashboard's catch-all StaticFiles answers it (404/405) before
        # Starlette's redirect_slashes can. Ergonomics for a hand-typed URL
        # only -- the URL that ships is MCP_URL_PATH, because httpx-based MCP
        # clients default to follow_redirects=False.
        @app.get(MCP_PATH, include_in_schema=False)
        async def _mcp_slash() -> Any:
            return RedirectResponse(MCP_URL_PATH, status_code=307)

        app.mount(MCP_PATH, mcp_app)
    if web_dist is not None and (web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist, html=True))
    else:
        @app.get("/", response_class=PlainTextResponse)
        async def hint() -> str:
            return "fantaclaude asta serve is running, but the dashboard is not built: run `poe web-build`.\n"
    return app
