"""HTTP for the web sources: one client, one User-Agent, one error vocabulary.

fantacalcio.it, Understat and UEFA are public hosts read politely -- an
honest User-Agent, one request at a time, a pause between pages of the same
host, never a retry. Errors map to three classes the callers act on
differently: an expired website session (stop and ask for a new cookie), a
resource that does not exist yet (stop this loop, not the run), and anything
else (fail loud). Verified 2026-08-28 that all three hosts answer this
User-Agent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from fantaclaude import __version__

USER_AGENT = f"fantaclaude/{__version__} (personal Fantacalcio assistant; one request at a time)"
POLITE_DELAY_SECONDS = 1.0


class SourceError(RuntimeError):
    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class WebSessionExpired(SourceError):
    """401/403, or a redirect to a login page: the session no longer authenticates."""


class NotPublished(SourceError):
    """404: the resource is not there (yet)."""


def build_http(*, timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT},
                             follow_redirects=False)


async def fetch_bytes(http: httpx.AsyncClient, url: str, *, method: str = "GET",
                      headers: dict[str, str] | None = None,
                      params: dict[str, Any] | None = None,
                      data: dict[str, Any] | None = None) -> bytes:
    response = await http.request(method, url, headers=headers, params=params, data=data)
    status = response.status_code
    if status in (401, 403):
        raise WebSessionExpired(f"{url} -> HTTP {status}", url=url, status=status)
    if 300 <= status < 400:
        target = response.headers.get("location", "")
        if "login" in target.lower():
            raise WebSessionExpired(f"{url} -> HTTP {status} to {target}", url=url, status=status)
        raise SourceError(f"{url} -> unexpected redirect to {target!r}", url=url, status=status)
    if status == 404:
        raise NotPublished(f"{url} -> HTTP 404", url=url, status=status)
    if status >= 400:
        raise SourceError(f"{url} -> HTTP {status}: {response.text[:200]}", url=url, status=status)
    return response.content


async def polite_pause(seconds: float = POLITE_DELAY_SECONDS) -> None:
    await asyncio.sleep(seconds)


def run_web[T](fn: Callable[[httpx.AsyncClient], Awaitable[T]]) -> T:
    """Run `fn(http)` to completion on one event loop and close the client on
    that same loop -- the sync bridge the CLI uses, mirroring run_with_api."""
    async def go() -> T:
        http = build_http()
        try:
            return await fn(http)
        finally:
            await http.aclose()
    return asyncio.run(go())
