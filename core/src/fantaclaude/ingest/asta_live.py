"""FantaAstaLive over Firebase: the live feed (spec, "The live feed:
FantaAstaLive over Firebase" and "The adapter, and the rules that keep it
safe").

Transport only. This module signs in anonymously, holds the SSE stream,
refreshes the token ahead of expiry, reconnects with backoff, maintains the
raw state node, and hands each new state to a callback as a parsed Snapshot.
The set-diff lives in asta/state.py; nothing here knows about boards,
dashboards or tools. Exactly one subscriber exists — the server owns the
stream; no CLI and no MCP tool connects here (spec, "Exactly one
subscriber").

The client config below is FantaAstaLive's own public web-app configuration,
read from the app's bundle (main-VJKJAFYQ.js → chunk-E2X65QDE.js) on
2026-08-31. It is configuration, not a credential: sign-in is anonymous
(accounts:signUp with returnSecureToken and no email), exactly the way the
app itself connects, and the token it yields can read only what the app's
own security rules let any participant read. If FantaAstaLive re-deploys
against a different project, connect fails loud at startup — re-read the
bundle and update these two constants.

The session code is refused at ingestion if it is not a name (spec: it
becomes a path component under records/asta/ and a key in the stream URL);
the guard is the same predicate the snapshot sink uses, applied where the
value arrives.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from fantaclaude.asta.snapshot import session_code_is_path
from fantaclaude.asta.state import Snapshot, SnapshotError, parse_snapshot

FIREBASE_API_KEY = "AIzaSyAji5aMonqYhjfCnHU6YW4TgwOIh8x302Y"  # verified 2026-08-31
FIREBASE_DATABASE_URL = "https://leghe-fantagazzetta-app.firebaseio.com"
SIGNUP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signUp"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
TOKEN_REFRESH_MARGIN = (
    300.0  # refresh this many seconds before expiry (spec: "refreshed ahead of expiry")
)
BACKOFF = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
READ_TIMEOUT = (
    90.0  # keep-alives arrive every ~30-45s; silence past this is a dead stream
)

LIVE, RECONNECTING, OFFLINE = "live", "reconnecting", "offline"


class FeedError(RuntimeError):
    """The feed cannot be read: a refused sign-in, a session that does not
    exist, security rules that deny the read, or a node this code cannot
    parse. The message never carries a token."""


def check_session_code(code: str) -> str:
    """The session code as a name: stripped, non-empty, never a path."""
    code = (code or "").strip()
    if not code:
        raise FeedError("the session code is empty")
    if session_code_is_path(code):
        raise FeedError(f"session code {code!r} is a path, not a session code")
    return code


@dataclass
class _Token:
    id_token: str
    refresh_token: str
    expires_at: float


class AnonymousAuth:
    """One anonymous Firebase user: sign up once, refresh ahead of expiry,
    fall back to a fresh sign-up when the refresh is refused (anonymous —
    a new user reads exactly what the old one read)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str = FIREBASE_API_KEY,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._now = now
        self._token: _Token | None = None

    def invalidate(self) -> None:
        """Drop the cached token (the stream said auth_revoked)."""
        if self._token is not None:
            self._token = _Token(
                self._token.id_token, self._token.refresh_token, self._now()
            )

    async def token(self) -> str:
        tok = self._token
        if tok is not None and self._now() < tok.expires_at - TOKEN_REFRESH_MARGIN:
            return tok.id_token
        if tok is not None:
            try:
                return await self._refresh(tok.refresh_token)
            except FeedError:
                pass  # refused: fall through to a fresh sign-up
        return await self._signup()

    async def _signup(self) -> str:
        resp = await self._client.post(
            SIGNUP_URL, params={"key": self._api_key}, json={"returnSecureToken": True}
        )
        payload = self._payload(resp, "anonymous sign-in")
        self._token = _Token(
            str(payload["idToken"]),
            str(payload["refreshToken"]),
            self._now() + float(payload.get("expiresIn") or 3600),
        )
        return self._token.id_token

    async def _refresh(self, refresh_token: str) -> str:
        resp = await self._client.post(
            TOKEN_URL,
            params={"key": self._api_key},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        payload = self._payload(resp, "token refresh")
        self._token = _Token(
            str(payload["id_token"]),
            str(payload["refresh_token"]),
            self._now() + float(payload.get("expires_in") or 3600),
        )
        return self._token.id_token

    @staticmethod
    def _payload(resp: httpx.Response, what: str) -> dict[str, Any]:
        if resp.status_code != 200:
            code = None
            try:
                code = resp.json().get("error", {}).get("message")
            except json.JSONDecodeError, AttributeError:
                pass
            raise FeedError(
                f"{what} answered {resp.status_code}" + (f" ({code})" if code else "")
            )
        return resp.json()


def _segments(path: str) -> list[str]:
    return [seg for seg in path.split("/") if seg]


def apply_put(node: Any, path: str, data: Any) -> Any:
    """Firebase streaming `put`: replace the subtree at `path`; null deletes."""
    segs = _segments(path)
    if not segs:
        return data
    root = node if isinstance(node, dict) else {}
    here = root
    for seg in segs[:-1]:
        nxt = here.get(seg)
        if isinstance(
            nxt, list
        ):  # Firebase's own holed-array shape: reindex, don't discard
            nxt = {str(i): v for i, v in enumerate(nxt) if v is not None}
            here[seg] = nxt
        elif not isinstance(nxt, dict):
            nxt = {}
            here[seg] = nxt
        here = nxt
    if data is None:
        here.pop(segs[-1], None)
    else:
        here[segs[-1]] = data
    return root


def apply_patch(node: Any, path: str, data: Mapping) -> Any:
    """Firebase streaming `patch`: merge each key of `data` at `path`."""
    root = node if isinstance(node, dict) else {}
    for key, value in data.items():
        root = apply_put(root, f"{path.rstrip('/')}/{key}", value)
    return root


async def sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    """(event, data) frames from an SSE line stream; comments are skipped and
    multi-line data joined the way the protocol says."""
    event, data = "message", []
    async for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].strip())


class AstaLiveFeed:
    """The one subscriber. run() streams `/sessions/<code>/state`, maintains
    the raw node, and emits a parsed Snapshot per change; it returns only by
    cancellation, and raises FeedError only when the feed can never recover
    by retrying (no such session, rules deny the read, a node shape this
    code cannot parse)."""

    def __init__(
        self,
        session_code: str,
        *,
        client: httpx.AsyncClient,
        on_snapshot: Callable[[Snapshot], Awaitable[None]],
        on_status: Callable[[str], Awaitable[None]],
        auth: AnonymousAuth | None = None,
        database_url: str = FIREBASE_DATABASE_URL,
        capture: Path | None = None,
        backoff: Sequence[float] = BACKOFF,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.session_code = check_session_code(session_code)
        self._client = client
        self._on_snapshot = on_snapshot
        self._on_status = on_status
        self._auth = auth or AnonymousAuth(client)
        self._url = f"{database_url}/sessions/{self.session_code}/state.json"
        self._capture = capture
        self._backoff = tuple(backoff)
        self._sleep = sleep
        self._node: Any = None

    async def run(self) -> None:
        attempt = 0
        while True:
            await asyncio.sleep(0)  # a real checkpoint: a caller-injected `sleep`
            # (the tests use one) need not yield control itself for cancel() to land
            # before a new connect starts.
            try:
                if await self._stream_once():
                    attempt = (
                        0  # the stream was healthy: the next drop starts backoff afresh
                    )
                # clean end of stream: the server closed it; reconnect
            except httpx.HTTPError, TimeoutError:
                pass
            attempt = min(attempt, len(self._backoff) - 1)
            await self._on_status(RECONNECTING)
            await self._sleep(self._backoff[attempt])
            attempt += 1

    async def _stream_once(self) -> bool:
        """Stream until the connection ends; True if at least one event was
        applied (the connect was healthy)."""
        token = await self._auth.token()
        timeout = httpx.Timeout(10.0, read=READ_TIMEOUT)
        async with self._client.stream(
            "GET",
            self._url,
            params={"auth": token},
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
            follow_redirects=True,
        ) as resp:
            if resp.status_code != 200:
                await resp.aread()
                if resp.status_code in (401, 403):
                    self._auth.invalidate()
                    raise httpx.HTTPStatusError(
                        "unauthorized", request=resp.request, response=resp
                    )
                raise FeedError(
                    f"the feed answered {resp.status_code} for session {self.session_code}"
                )
            first = True
            async for event, data in sse_events(resp.aiter_lines()):
                if event == "keep-alive":
                    continue
                if event == "auth_revoked":
                    self._auth.invalidate()
                    return not first  # reconnect with a fresh token
                if event == "cancel":
                    raise FeedError(
                        f"the feed cancelled session {self.session_code}: the rules deny the read"
                    )
                if event not in ("put", "patch"):
                    continue
                body = json.loads(data)
                if event == "put":
                    if body.get("path") in ("/", "") and body.get("data") is None:
                        raise FeedError(
                            f"no session {self.session_code} is being served"
                        )
                    self._node = apply_put(self._node, body["path"], body["data"])
                else:
                    self._node = apply_patch(self._node, body["path"], body["data"])
                try:
                    snap = parse_snapshot(self._node)
                except SnapshotError as exc:
                    raise FeedError(
                        f"session {self.session_code}: the node is not a shape this mirror reads: {exc}"
                    ) from None
                if first:
                    await self._on_status(LIVE)
                    first = False
                self._write_capture()
                await self._on_snapshot(snap)
            return not first

    def _write_capture(self) -> None:
        if self._capture is None:
            return
        self._capture.parent.mkdir(parents=True, exist_ok=True)
        with self._capture.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(self._node, ensure_ascii=False) + "\n")
