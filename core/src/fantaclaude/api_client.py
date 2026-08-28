"""Build the MCP's API client for the CLI, and run coroutines from sync code.

One client, one endpoint map: the MCP's config, auth and api are imported as a
library, so the credentials, the token cache and its cross-process lock are
the very files the server uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from fantacalcio_mcp.api import FantacalcioAPI
from fantacalcio_mcp.auth import Auth
from fantacalcio_mcp.config import load_settings, token_cache_path


@dataclass
class ApiHandle:
    api: FantacalcioAPI
    http: httpx.AsyncClient

    async def aclose(self) -> None:
        await self.http.aclose()


def build_api(*, timeout: float = 20.0) -> ApiHandle:
    settings = load_settings()
    http = httpx.AsyncClient(timeout=timeout)
    auth = Auth(settings.credentials, token_cache_path(), http, settings.app_key, settings.base_url)
    return ApiHandle(FantacalcioAPI(http, auth, settings.base_url, settings.app_key), http)


def run_with_api[T](fn: Callable[[FantacalcioAPI], Awaitable[T]]) -> T:
    """Run `fn(api)` to completion on one event loop and close the client on
    that same loop -- the MCP's __main__ explains why closing on a second
    loop is not safe."""
    async def go() -> T:
        handle = build_api()
        try:
            return await fn(handle.api)
        finally:
            await handle.aclose()
    return asyncio.run(go())
