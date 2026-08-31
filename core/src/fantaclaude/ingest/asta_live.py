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

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from fantaclaude.asta.snapshot import session_code_is_path

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
            except (json.JSONDecodeError, AttributeError):
                pass
            raise FeedError(
                f"{what} answered {resp.status_code}" + (f" ({code})" if code else "")
            )
        return resp.json()
