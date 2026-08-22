"""Entrypoint. stdio by default; HTTP binds loopback unless told otherwise.

`FastMCP.run()` is a synchronous wrapper that internally does
`anyio.run(self.run_async, ...)`: it creates its own event loop, runs the
server to completion in it, and tears that loop down before returning. The
shared `httpx.AsyncClient` is first used *inside* that loop (every tool call
goes through `Auth`/`FantacalcioAPI`, both driven from the server's own
async handlers), so its connections are bound to that loop.

Closing it afterwards with a second, separate `asyncio.run(http.aclose())`
would hand those loop-bound resources to a brand new event loop -- the
original loop is already closed by then, so this is not just untidy but can
raise (or silently fail to actually close anything) depending on what the
transport still holds open. Instead we drive the whole lifetime -- server
run *and* client close -- through a single `asyncio.run()` call, using
`run_async` (the coroutine `run()` itself wraps) so both happen in the same
loop.
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from .api import FantacalcioAPI
from .auth import Auth
from .config import load_settings, token_cache_path
from .server import build_server


async def _serve(http: httpx.AsyncClient, api: FantacalcioAPI,
                  transport: str, host: str, port: int) -> None:
    server = build_server(api)
    try:
        if transport == "http":
            await server.run_async(transport="http", host=host, port=port)
        else:
            # stdio talks newline-delimited JSON-RPC on stdout; FastMCP's
            # decorative startup banner only ever goes to stderr, so it
            # cannot corrupt the protocol stream. It is still pure noise in
            # an MCP client's logs (Claude Code included), so it's suppressed
            # here. HTTP keeps the banner: it runs attended, not spawned by
            # a client parsing structured output.
            await server.run_async(transport="stdio", show_banner=False)
    finally:
        await http.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="fantacalcio-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    settings = load_settings()
    http = httpx.AsyncClient(timeout=20.0)
    auth = Auth(settings.credentials, token_cache_path(), http,
                settings.app_key, settings.base_url)
    api = FantacalcioAPI(http, auth, settings.base_url, settings.app_key)

    asyncio.run(_serve(http, api, args.transport, args.host, args.port))


if __name__ == "__main__":
    main()
