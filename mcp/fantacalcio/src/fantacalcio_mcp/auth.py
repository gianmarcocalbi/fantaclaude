"""Credentials in, valid league JWT out.

League context lives inside the token (claims l_id / t_id), so switching
leagues means switching tokens. This module is the only place that knows that.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import ConfigurationError, Credentials

LOGIN_PATH = "/onboarding/v1/login"


class AuthError(Exception):
    """Authentication failed in a way retrying will not fix."""


def decode_claims(jwt: str) -> dict[str, Any]:
    try:
        payload = jwt.split(".")[1]
        padding = "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload + padding))
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        # AttributeError: jwt is None/not a str. IndexError: no "." segment.
        # TypeError/ValueError: bad base64 or bad JSON.
        raise AuthError("token is not a readable JWT") from exc
    if not isinstance(claims, dict):
        raise AuthError("token is not a readable JWT")
    return claims


def is_expired(jwt: str, *, now: float | None = None, skew: int = 60) -> bool:
    exp = decode_claims(jwt).get("exp")
    if exp is None:
        # Fail closed: every real token from this API carries `exp` (both
        # account and league tokens do), so a missing claim means something
        # is wrong with the token, not that it is eternal.
        return True
    try:
        exp = float(exp)
    except (TypeError, ValueError):
        return True  # non-numeric exp: fail closed rather than crash
    return (now if now is not None else time.time()) + skew >= exp


def _cache_token_expired(jwt: str | None) -> bool:
    """Expiry check for a token we ourselves cached and can heal by
    re-logging in. An unreadable cached token (disk corruption, a
    truncated write, schema drift) must be treated the same as "not
    cached" so the normal re-login path heals it, instead of raising an
    unhandled AuthError on every call forever.
    """
    if not jwt:
        return True
    try:
        return is_expired(jwt)
    except AuthError:
        return True


@dataclass
class LeagueToken:
    alias: str
    league_id: str
    team_id: str
    name: str
    jwt: str


class Auth:
    # How long we trust "we just (tried to) log in" before allowing another
    # login attempt. Shared by the single-flight guard (concurrent callers
    # collapse onto one login) and the repeated-lookup-miss guard (an
    # unknown alias, or an ambiguous default on a multi-league account,
    # does not force a fresh login on every single call).
    _LOGIN_COOLDOWN_SECONDS = 60.0

    def __init__(self, credentials: Credentials, cache_path: Path,
                 http: httpx.AsyncClient, app_key: str, base_url: str, *,
                 login_cooldown: float = _LOGIN_COOLDOWN_SECONDS) -> None:
        self._credentials = credentials
        self._cache_path = cache_path
        self._http = http
        self._app_key = app_key
        self._base_url = base_url.rstrip("/")
        self._account_jwt: str | None = None
        self._account_user_id: str | None = None
        self._leagues: dict[str, LeagueToken] = {}
        self._last_login_at: float | None = None
        # Separate clock for 401-recovery logins, deliberately NOT cleared
        # by invalidate() -- see _begin_recovery_login for why the ordinary
        # cooldown cannot bound the sequential case on its own.
        self._last_recovery_login_at: float | None = None
        # Test hook only: production always gets the 60s class default.
        # Nothing pins that the cooldown actually expires without this.
        self._login_cooldown_seconds = login_cooldown
        self._last_login_error: BaseException | None = None
        # The exact token value (league or account JWT) the most recent
        # 401-recovery attempt was for. Lets a concurrent waiter tell "no
        # one has tried to recover from *this* failure yet" from "someone
        # already tried and it failed" -- see refresh_if_stale /
        # refresh_account_if_stale.
        self._recovery_attempted_for: str | None = None
        self._login_lock = asyncio.Lock()
        self._secure_cache_dir()
        self._load_cache()

    # ---- cache ---------------------------------------------------------
    def _secure_cache_dir(self) -> None:
        """Make sure the directory that holds (or will hold) the token
        cache is owner-only, 0700.

        Called whenever the cache location is used -- at construction, and
        again on every write -- not only after a successful login. The
        tightening used to happen solely as a side effect of `_save_cache`,
        so a `.auth/` created by anything else (a plain mkdir, a checkout,
        an older build) stayed at 0755 indefinitely in token-only mode,
        which never logs in and therefore never writes. That directory is
        where year-long JWTs land, so it must not be world-readable while
        we wait for a write that may never come.

        Best-effort by design, like `_save_cache`: a read-only parent must
        never stop the server from starting.
        """
        try:
            parent = self._cache_path.parent
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(parent, 0o700)
        except OSError:
            pass

    def _load_cache(self) -> None:
        if not self._cache_path.is_file():
            return
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("token cache root is not a JSON object")
            account_jwt = data.get("account")
            cached_user_id = data.get("user_id")
            cached_username = data.get("username")
            leagues = {
                alias: LeagueToken(**entry)
                for alias, entry in (data.get("leagues") or {}).items()
            }
        except Exception:
            # Any corruption -- schema drift, a hand-edited file, a partial
            # write, an unexpected shape -- must never crash the server.
            # Fail closed: treat it as a cold cache and carry on.
            return

        if self._cache_belongs_to_someone_else(cached_username, cached_user_id):
            # The cache file lives at a fixed workspace path, independent
            # of credentials. If .env got re-pointed at a different
            # account, serving the old account's league tokens would be
            # silently wrong. Discard it entirely and start cold.
            self._discard_cache_file()
            return

        self._account_jwt = account_jwt
        self._account_user_id = str(cached_user_id) if cached_user_id is not None else None
        self._leagues = leagues

    def _cache_belongs_to_someone_else(
        self, cached_username: str | None, cached_user_id: Any
    ) -> bool:
        """Best-effort pre-login account binding. We can know the *new*
        identity before any network call only in two cases: username/
        password mode knows its own username, and token-only mode can
        decode its token's user_id claim locally. A cache with no identity
        recorded (older format, or nothing to compare against) is trusted.
        """
        if self._credentials.username:
            return cached_username is not None and cached_username != self._credentials.username
        if self._credentials.token:
            uid = self._decode_user_id(self._credentials.token)
            return (uid is not None and cached_user_id is not None
                    and uid != str(cached_user_id))
        return False

    def _discard_cache_file(self) -> None:
        try:
            self._cache_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _save_cache(self) -> None:
        """Best-effort: caching is an optimisation, so a write failure
        (read-only .auth/, out of disk, etc.) must never undo a login that
        already succeeded against the server. Written atomically via a
        same-directory temp file + os.replace, with the temp file created
        0600 from the very first byte (never a window at the default
        0644), and the parent directory tightened to 0700.
        """
        try:
            self._secure_cache_dir()
            parent = self._cache_path.parent
            payload = json.dumps({
                "account": self._account_jwt,
                "user_id": self._account_user_id,
                "username": self._credentials.username,
                "leagues": {alias: asdict(tok) for alias, tok in self._leagues.items()},
            }, indent=2).encode("utf-8")
            fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=".tokens-", suffix=".tmp")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self._cache_path)
            except OSError:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError:
            pass  # see docstring: a cache write failure must not fail login

    def invalidate(self) -> None:
        """Drop cached tokens, in memory and on disk, so the next call
        re-logs in for real. Also clears the login cooldown: invalidate()
        means the server just told us our tokens are bad (401/403), so the
        "we just refreshed, don't hammer login" guard must not swallow
        this forced refresh -- that would turn a single 401 into a
        cooldown-length outage instead of one retry. Also clears
        `_recovery_attempted_for`: callers of `refresh_if_stale` /
        `refresh_account_if_stale` re-arm it themselves, immediately
        after this call, for the specific failure they're recovering
        from -- see those methods.

        `_last_recovery_login_at` is deliberately NOT cleared: it is the
        one piece of state that survives an invalidate() and therefore the
        only thing that can bound *sequential* recoveries, each of which
        arrives with a different token. See `_begin_recovery_login`.
        """
        self._account_jwt = None
        self._account_user_id = None
        self._leagues = {}
        self._last_login_at = None
        self._last_login_error = None
        self._recovery_attempted_for = None
        self._discard_cache_file()

    def list_leagues(self) -> list[LeagueToken]:
        return list(self._leagues.values())

    # ---- login ---------------------------------------------------------
    async def login(self) -> dict[str, Any]:
        if not self._credentials.can_login:
            raise AuthError(
                "Cached token is expired or missing and no username/password is "
                "configured. Set FANTACALCIO_USERNAME and FANTACALCIO_PASSWORD, "
                "or refresh FANTACALCIO_LEAGUE_TOKEN."
            )
        response = await self._http.post(
            f"{self._base_url}{LOGIN_PATH}",
            headers={"app_key": self._app_key, "Accept": "application/json"},
            json={"username": self._credentials.username,
                  "password": self._credentials.password},
        )
        if response.status_code >= 400:
            body = _safe_json(response)
            code = body.get("code", "")
            message = body.get("message", response.text[:200])
            if code in {"ATH006", "ATH018", "ATH000", "ATH007"}:
                raise ConfigurationError(f"{code}: {message}")
            raise AuthError(f"login failed (HTTP {response.status_code}): {message}")

        data = (response.json() or {}).get("data") or {}
        self._account_jwt = data.get("jwt")
        self._account_user_id = self._decode_user_id(self._account_jwt)
        self._leagues = {
            lg["alias"]: LeagueToken(
                alias=lg["alias"], league_id=str(lg.get("id", "")),
                team_id=str(lg.get("id_squadra", "")), name=lg.get("nome", ""),
                jwt=lg["jwt"],
            )
            for lg in data.get("leghe") or [] if lg.get("alias") and lg.get("jwt")
        }
        self._save_cache()
        return data

    @staticmethod
    def _decode_user_id(jwt: str | None) -> str | None:
        if not jwt:
            return None
        try:
            uid = decode_claims(jwt).get("user_id")
        except AuthError:
            return None
        return str(uid) if uid is not None else None

    async def _login_and_record(self) -> None:
        """Call `login()` and record the attempt's time/outcome for the
        cooldown machinery. Caller must hold `_login_lock`. Shared by
        `_maybe_login` (cooldown-gated, for an ordinary lookup) and
        `refresh_if_stale`/`refresh_account_if_stale` (unconditional, for
        a confirmed-stale 401 recovery) so both paths preserve a failed
        login's exception type identically -- see `_maybe_login`'s
        docstring for why that matters.
        """
        self._last_login_at = time.time()
        try:
            await self.login()
        except Exception as exc:
            self._last_login_error = exc
            raise
        else:
            self._last_login_error = None

    def _begin_recovery_login(self) -> None:
        """Gate a 401-recovery login on its own clock, or raise.

        `invalidate()` clears the ordinary login cooldown on purpose, so a
        genuine 401 heals on the very next call instead of waiting out a
        cooldown-length outage. The cost is that the ordinary cooldown can
        bound only *concurrent* recoveries: sequential ones each arrive
        carrying a different, freshly-minted token, so
        `_recovery_attempted_for` never matches and nothing suppresses the
        next login. Measured against that shape -- a login that *succeeds*
        against an endpoint that keeps answering 401 (server-side token
        revocation, a WAF, a league state transition) -- 20 sequential tool
        calls produced 21 logins: login gets hammered exactly when doing so
        is most harmful, because nothing ever fails in a way that stops the
        loop.

        This clock survives `invalidate()`, so at most one recovery login
        runs per cooldown window. Refusing loudly (rather than returning
        the same rejected token for another doomed attempt) is what keeps
        the caller from silently looping; the first recovery after any
        quiet window is always allowed, so ordinary 401-healing is
        unaffected. Caller must hold `_login_lock`, and must call this
        *before* `invalidate()` so a refusal leaves the cache intact.
        """
        now = time.time()
        if (self._last_recovery_login_at is not None
                and now - self._last_recovery_login_at < self._login_cooldown_seconds):
            raise AuthError(
                "token rejected immediately after a fresh login -- refusing to "
                "log in again inside the cooldown window. The server is "
                "rejecting a token it just issued (revoked session, a WAF, or a "
                "league state change); try again in a minute."
            )
        self._last_recovery_login_at = now

    async def _maybe_login(self, still_needed: Callable[[], bool]) -> None:
        """Single-flight, rate-limited login.

        `still_needed` is re-evaluated once the lock is held: if a
        concurrent caller already logged in while we were waiting, we skip
        the network call entirely (fixes N concurrent cold-cache calls
        fanning out into N logins). If it is still needed but a login
        attempt (success or failure) happened within the cooldown window,
        we also skip the network call -- that attempt already answered the
        question, and repeating it on every call (e.g. for an unknown
        alias, or an ambiguous default on a multi-league account) is how a
        real account gets rate limited or locked.

        A *failed* attempt still arms the cooldown (we don't want to
        hammer a broken login either), so a suppressed call must re-raise
        the original failure -- with its original exception type -- rather
        than silently falling through to the generic "not found" error a
        genuine cache miss would produce. Losing the type is the sharp
        edge: ATH018 must stay a ConfigurationError (never retried) on
        every call, not just the first, or it starts looking retryable.
        """
        async with self._login_lock:
            if not still_needed():
                return
            now = time.time()
            if (self._last_login_at is not None
                    and now - self._last_login_at < self._login_cooldown_seconds):
                if self._last_login_error is not None:
                    raise self._last_login_error
                return
            await self._login_and_record()

    # ---- token access --------------------------------------------------
    async def account_token(self) -> str:
        def needs_login() -> bool:
            return _cache_token_expired(self._account_jwt)

        if needs_login():
            await self._maybe_login(needs_login)
        if needs_login():
            raise AuthError("login did not return a valid account token")
        return self._account_jwt

    async def refresh_account_if_stale(self, failed_token: str) -> str:
        """Recover from a 401 on the account token, collapsing any number
        of concurrent recoveries for the *same* failure onto one login --
        including when that login itself keeps failing.

        Call this only with the token that just failed. If the cached
        account token has already changed to something else, and that
        something else isn't itself already expired, it's returned
        directly: another concurrent caller's recovery already covered
        this failure, so no invalidation, no login. (This depends on
        every successful login producing a distinct token string -- true
        of the real server, and deliberately engineered into the
        concurrency tests, but a structural assumption worth flagging.)

        Otherwise, only the *first* waiter for this exact `failed_token`
        invalidates and logs in -- `_recovery_attempted_for` records which
        failure the most recent attempt covered, so every other
        concurrent waiter for the *same* failure finds that marker
        already set and skips straight to the shared outcome below
        instead of also hammering /login. This is what a bare
        cache-still-empty check gets wrong: a *failing* recovery login
        leaves the account token cache empty, so every waiter's fast-path
        check above would fail and each would fall through to attempt
        its own login -- turning the exact scenario a burst of concurrent
        401s is most likely to co-occur with (credentials just went bad)
        into the worst case for login volume instead of the bound this
        method exists to hold. A failed attempt's exception
        (`_last_login_error`, shared with `_maybe_login`) is instead
        re-raised, with its original type, to every waiter -- a
        rotated/bad password surfaces as `ConfigurationError` for all of
        them, not just the first, and not downgraded to something
        generic.
        """
        async with self._login_lock:
            if (self._account_jwt is not None and self._account_jwt != failed_token
                    and not _cache_token_expired(self._account_jwt)):
                return self._account_jwt

            if self._recovery_attempted_for != failed_token:
                # Before invalidate(), so a refusal leaves the cache intact.
                self._begin_recovery_login()
                self.invalidate()
                self._recovery_attempted_for = failed_token
                try:
                    await self._login_and_record()
                except Exception:
                    pass  # outcome is read from _last_login_error below,
                          # the same way for us and every piggybacking waiter

            if self._last_login_error is not None:
                raise self._last_login_error
            if self._account_jwt is None or _cache_token_expired(self._account_jwt):
                raise AuthError("login did not return a valid account token")
            return self._account_jwt

    async def token_for(self, alias: str | None = None) -> str:
        if self._credentials.token and not self._credentials.can_login:
            if is_expired(self._credentials.token):
                raise AuthError(
                    "FANTACALCIO_LEAGUE_TOKEN is expired and token-only mode "
                    "cannot refresh it. Add FANTACALCIO_USERNAME/PASSWORD or "
                    "paste a fresh token."
                )
            return self._credentials.token

        def find() -> LeagueToken | None:
            token = self._pick(alias)
            if token is not None and not _cache_token_expired(token.jwt):
                return token
            return None

        token = find()
        if token is None:
            await self._maybe_login(lambda: find() is None)
            token = find()
        if token is None:
            raise AuthError(
                f"league {alias!r} not found. Available: "
                f"{', '.join(sorted(self._leagues)) or 'none'}"
            )
        return token.jwt

    async def refresh_if_stale(self, failed_token: str, alias: str | None = None) -> str:
        """Recover from a 401 on a league token -- see
        `refresh_account_if_stale` for the full rationale on collapsing
        concurrent recoveries (including failing ones) onto a single
        login; this is API-identical except it reads/writes one league's
        cache entry instead of the account token.

        Call this only with the token that just failed (e.g. the bearer a
        request was just rejected with).

        Token-only mode (`FANTACALCIO_LEAGUE_TOKEN`, no username/password)
        mirrors `token_for`'s own short-circuit: there is no login to
        retry, so a still-unexpired pasted token is simply handed back
        for one more attempt (which will surface the server's real 401
        body if it 401s again), and an expired one raises the same
        "cannot refresh it" error `token_for` would.

        An ambiguous default alias (`alias=None` with more than one
        cached league) falls out of the same fix as a failing login:
        `_pick(alias)` returns `None` either way, so every concurrent
        waiter -- whichever one actually ran the recovery, and every
        piggybacking waiter after it -- converges on the same final
        `current is None` check below and raises the same "not found"
        `AuthError`, instead of only the one waiter that happened to run
        the login noticing the ambiguity.
        """
        if self._credentials.token and not self._credentials.can_login:
            if is_expired(self._credentials.token):
                raise AuthError(
                    "FANTACALCIO_LEAGUE_TOKEN is expired and token-only mode "
                    "cannot refresh it. Add FANTACALCIO_USERNAME/PASSWORD or "
                    "paste a fresh token."
                )
            return self._credentials.token

        async with self._login_lock:
            current = self._pick(alias)
            # Depends on every successful login minting a distinct token
            # string for this alias (true of the real server, and
            # deliberately engineered into the concurrency tests below) --
            # otherwise a "fresher" token identical to failed_token would
            # look stale forever and every waiter would fall through to
            # recover.
            if (current is not None and current.jwt != failed_token
                    and not _cache_token_expired(current.jwt)):
                return current.jwt

            if self._recovery_attempted_for != failed_token:
                # Before invalidate(), so a refusal leaves the cache intact.
                self._begin_recovery_login()
                self.invalidate()
                self._recovery_attempted_for = failed_token
                try:
                    await self._login_and_record()
                except Exception:
                    pass  # outcome is read from _last_login_error below,
                          # the same way for us and every piggybacking waiter

            if self._last_login_error is not None:
                raise self._last_login_error
            current = self._pick(alias)
            if current is None or _cache_token_expired(current.jwt):
                raise AuthError(
                    f"league {alias!r} not found after recovery login. Available: "
                    f"{', '.join(sorted(self._leagues)) or 'none'}"
                )
            return current.jwt

    def _pick(self, alias: str | None) -> LeagueToken | None:
        if alias:
            return self._leagues.get(alias)
        if len(self._leagues) == 1:
            return next(iter(self._leagues.values()))
        return None


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
