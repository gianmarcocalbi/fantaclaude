"""HTTP transport for the private Leghe Fantacalcio.it API.

Must never import fastmcp: keeping this module framework-free is what makes
the client testable against fixtures.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

# _safe_json is imported, not redefined: it lived here as a byte-identical
# second copy, and two copies of a "never raise on a non-JSON error body"
# helper is two places to fix. auth.py owns it (it needs the same handling
# for the login response).
from .auth import Auth, _safe_json, decode_claims

ERROR_HINTS = {
    "ATH000": "app_key rejected -- it may have rotated; re-capture it",
    "ATH006": "credentials missing -- set FANTACALCIO_USERNAME and FANTACALCIO_PASSWORD",
    "ATH007": "app_key missing -- set FANTACALCIO_APP_KEY",
    "ATH018": "invalid username or password",
}


class ApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None,
                 code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class FantacalcioAPI:
    def __init__(self, http: httpx.AsyncClient, auth: Auth,
                 base_url: str, app_key: str) -> None:
        self._http = http
        self._auth = auth
        self._base_url = base_url.rstrip("/")
        self._app_key = app_key

    async def _get(self, path: str, *, params: dict[str, Any] | None = None,
                   league: str | None = None, account: bool = False) -> Any:
        """GET `path`, resolving a bearer token via `Auth`.

        By default the bearer comes from `Auth.token_for(league)` (a
        league-scoped token); pass `account=True` to use
        `Auth.account_token()` instead (e.g. for `profile()`).

        On a 401/403 this recovers and retries exactly once before giving
        up -- never more than once per call, regardless of how the retry
        itself resolves. Recovery goes through `Auth.refresh_if_stale` /
        `Auth.refresh_account_if_stale` rather than a bare
        `invalidate()` + re-fetch: those collapse any number of *concurrent*
        401s against the same stale token onto a single login (each caller
        checks, under `Auth`'s login lock, whether the cache already moved
        past the token that failed -- if it has, another concurrent
        recovery already covered it, so this one skips straight to the
        fresher token instead of also invalidating and logging in). A bare
        `invalidate()` would clear the login cooldown on every single 401,
        so N concurrent tool calls hitting an expired token would each
        force their own real login -- exactly the login-hammering that
        `Auth`'s cooldown exists to prevent. Sequential 401s are bounded
        separately, by the recovery clock in `Auth._begin_recovery_login`:
        after one recovery login inside the cooldown window, a still-401ing
        endpoint raises rather than logging in again.
        """
        if account:
            bearer = await self._auth.account_token()
        else:
            bearer = await self._auth.token_for(league)
        response = await self._request(path, params, bearer)

        if response.status_code in (401, 403):
            if account:
                bearer = await self._auth.refresh_account_if_stale(bearer)
            else:
                bearer = await self._auth.refresh_if_stale(bearer, league)
            response = await self._request(path, params, bearer)

        if response.status_code >= 400:
            body = _safe_json(response)
            code = body.get("code")
            message = ERROR_HINTS.get(code or "", body.get("message") or response.text[:200])
            raise ApiError(f"{path} -> HTTP {response.status_code}: {message}",
                           status=response.status_code, code=code)
        return response.json()

    async def _request(self, path: str, params: dict[str, Any] | None,
                       bearer: str) -> httpx.Response:
        return await self._http.get(
            f"{self._base_url}{path}",
            params=params,
            headers={"Accept": "application/json", "app_key": self._app_key,
                     "Authorization": f"Bearer {bearer}"},
        )

    # ---- endpoints -----------------------------------------------------
    async def profile(self, user_id: str | None = None) -> Any:
        """Read the account profile.

        The endpoint was only ever observed with a numeric id, so the id is
        read from the account token's `user_id` claim rather than guessed.
        """
        if user_id is None:
            token = await self._auth.account_token()
            user_id = decode_claims(token).get("user_id")
            if not user_id:
                raise ApiError("account token carries no user_id claim", code=None)
        return await self._get(f"/onboarding/v2/profile/{quote(str(user_id))}", account=True)

    async def league_profile(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/profile", league=league)

    async def league_status(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/status", league=league)

    async def competitions(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/competitions", league=league)

    async def my_team(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/teams/my", league=league)

    async def teams(self, page: int = 1, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/teams",
                               params={"page": max(1, page)}, league=league)

    async def roster_settings(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/settings/rosters", league=league)

    async def lineup_settings(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/settings/lineup", league=league)

    async def calculation_settings(self, league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/league/settings/calculate", league=league)

    async def participants(self, page_number: int = 1, page_size: int = 1000,
                           league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/invitation/participants", league=league,
                               params=_pagination(page_number, page_size))

    async def invitees(self, page_number: int = 1, page_size: int = 1000,
                       league: str | None = None) -> Any:
        return await self._get("/onboarding/v1/invitation/invitees", league=league,
                               params=_pagination(page_number, page_size))

    async def server_time(self, league: str | None = None) -> Any:
        return await self._get("/market/v1/time", league=league)

    async def players(self, league: str | None = None) -> Any:
        """The listone: every Serie A player with Classic role, Mantra role
        codes and both quotazioni. ~515 KB, 539 rows — a library call for
        ingestion, deliberately not exposed as a tool. See the spec, "The
        listone".
        """
        return await self._get("/onboarding/v1/league/players", league=league)


def _pagination(page_number: int, page_size: int) -> dict[str, int]:
    return {"pageNumber": max(1, page_number), "pageSize": min(max(1, page_size), 1000)}
