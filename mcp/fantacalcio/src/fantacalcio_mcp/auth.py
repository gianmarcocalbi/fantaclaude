"""Credentials in, valid league JWT out.

League context lives inside the token (claims l_id / t_id), so switching
leagues means switching tokens. This module is the only place that knows that.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import ConfigurationError, Credentials

LOGIN_PATH = "/onboarding/v1/login"

# How long to poll for the flock sidecar before giving up and proceeding
# unlocked. Must comfortably exceed a real login round-trip (the POST to
# /login plus the atomic cache write) so a legitimately slow peer is waited
# for rather than raced, while still being finite -- an unbounded wait is
# exactly the "wedge forever on cancellation" failure mode this replaces.
_CROSS_PROCESS_LOCK_TIMEOUT_SECONDS = 30.0
_CROSS_PROCESS_LOCK_POLL_SECONDS = 0.01


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
        # Cross-process coordination lives beside the cache: a flock sidecar
        # serialises login-and-write across processes (fantaclaude sync-league
        # and the MCP server both drive this class), and a stamp records the
        # last attempt so the cooldown holds for a process that was not the
        # one to try. See _cross_process_lock and _recent_shared_attempt.
        # Tokens the server has already answered 401 to. The cache on disk can
        # be older than memory when a write failed, so re-reading it under the
        # lock could otherwise hand back a token we know is dead.
        self._rejected_tokens: list[str] = []
        self._lock_path = cache_path.with_name(cache_path.name + ".lock")
        self._stamp_path = cache_path.with_name("login-attempt.json")
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
                raise ValueError("token cache root is not a JSON object")  # noqa: TRY004 -- caught two lines below; the type is the corruption
            account_jwt = data.get("account")
            cached_user_id = data.get("user_id")
            cached_username = data.get("username")
            leagues = {
                alias: LeagueToken(**entry)
                for alias, entry in (data.get("leagues") or {}).items()
            }
        except Exception:  # noqa: BLE001 -- fail closed on any corruption; see comment below
            # Any corruption -- schema drift, a hand-edited file, a partial
            # write, an unexpected shape -- must never crash the server.
            # Fail closed: treat it as a cold cache and carry on.
            return

        if self._cache_belongs_to_someone_else(cached_username, cached_user_id):
            # The cache file lives at a fixed workspace path, independent
            # of credentials. If .env got re-pointed at a different
            # account, serving the old account's league tokens would be
            # silently wrong. Discard it entirely and start cold. The
            # shared attempt stamp goes with it -- see invalidate() -- or a
            # stale success recorded for the old identity would be read by
            # the cross-process re-check as "someone already logged in" and
            # silently suppress the new identity's own login.
            self._discard_cache_file()
            self._discard_stamp_file()
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

    def _credential_id(self) -> str:
        """A stable, non-reversible tag for the credentials in play.

        The attempt stamp bounds *those* credentials: an ATH018 means this
        password is wrong, not that logins are barred, so a corrected password
        must not inherit the refusal. Hashed and truncated rather than stored
        plainly -- FANTACALCIO_USERNAME is an email address for this service,
        and an email must never reach a stored payload.
        """
        material = "\x00".join((self._credentials.username or "",
                                 self._credentials.password or "",
                                 self._credentials.token or ""))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def _note_rejected(self, token: str | None) -> None:
        if token and token not in self._rejected_tokens:
            self._rejected_tokens.append(token)
            del self._rejected_tokens[:-8]      # bounded; only the recent past matters

    def _usable(self, token: str | None, failed_token: str | None) -> bool:
        """A token worth returning: not the one that just failed, not one an
        earlier 401 disproved, and not expired."""
        return (token is not None and token != failed_token
                and token not in self._rejected_tokens
                and not _cache_token_expired(token))

    def _discard_stamp_file(self) -> None:
        try:
            self._stamp_path.unlink(missing_ok=True)
        except OSError:
            pass

    @contextlib.asynccontextmanager
    async def _cross_process_lock(self) -> AsyncIterator[None]:
        """Hold the flock sidecar for the duration of a login-and-write.

        `_login_lock` serialises coroutines inside one process and nothing
        else; two processes racing a login is how a real account gets
        locked. flock is taken on a sidecar rather than on the cache file,
        because the cache is replaced atomically (os.replace) and a lock on
        it would end up attached to an unlinked inode.

        The acquire is a bounded, non-blocking poll on the event loop --
        not a blocking LOCK_EX handed to a worker thread. asyncio.
        CancelledError is a BaseException, so a cancellation while awaiting
        a blocking acquire would propagate out of this generator before
        the try/finally that owns the release is even entered: the fd is
        discarded with the frame, the worker thread is not cancelled, and
        it goes on to take LOCK_EX with nothing left able to release it --
        every later login in every process then blocks forever. Polling
        keeps the acquire cancellable and bounded, and closes the "no
        timeout" gap the blocking form also had. Best-effort like every
        other filesystem step here: if the sidecar cannot be opened, or
        the lock is not acquired within the timeout, the login proceeds
        unlocked rather than not at all -- the attempt stamp still guards
        the cooldown even without the lock.

        A cancellation can still land during the poll's own
        `asyncio.sleep`, though, and that is not an OSError -- see the
        `except BaseException` below for why closing the fd there is safe
        (and load-bearing), unlike closing it out from under the old
        blocking-thread acquire.
        """
        fd: int | None = None
        try:
            self._secure_cache_dir()
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            deadline = time.monotonic() + _CROSS_PROCESS_LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        os.close(fd)
                        fd = None
                        break
                    await asyncio.sleep(_CROSS_PROCESS_LOCK_POLL_SECONDS)
        except OSError:
            # A filesystem problem opening or polling the sidecar: fail
            # open like every other best-effort step here and proceed
            # unlocked.
            if fd is not None:
                os.close(fd)
            fd = None
        except BaseException:
            # Cancellation (or any other BaseException) delivered while
            # parked in the poll's asyncio.sleep. Closing fd here is safe
            # -- and required -- specifically because the acquire above is
            # a non-blocking poll running synchronously on the event loop:
            # at the instant a cancellation can land, no thread is blocked
            # inside flock() on this descriptor for us to race. That is
            # what made closing unsafe in the old blocking-thread design
            # this replaced (a worker could still be parked in flock() on
            # the same fd) and it does not apply here. fd never held a
            # successful flock() on this path either, so no other process
            # is waiting on it -- only the descriptor needs closing. The
            # cancellation itself must keep propagating: swallowing it
            # here would corrupt asyncio's cancellation machinery.
            if fd is not None:
                os.close(fd)
            raise
        try:
            yield
        finally:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _recent_shared_attempt(self) -> tuple[str, BaseException | None] | None:
        """The last login attempt any process recorded, if it is still inside
        the cooldown window: (kind, exception-or-None). A missing, stale or
        unreadable stamp is None -- fail open to "no recent attempt", the
        same way a corrupt cache is treated as a cold start. Unknown error
        types come back as AuthError so a transient failure elsewhere is not
        mistaken for a success.
        """
        try:
            data = json.loads(self._stamp_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("at"), (int, float)):
            return None
        # A one-sided ">= cooldown" check fails *closed* on a future-dated
        # or NaN "at": both give a non-positive delta, so the stamp reads
        # as recent forever (a bad-credentials error re-raised until the
        # wall clock catches up, or a login silently skipped). Requiring
        # the delta to sit in [0, cooldown) rejects a future timestamp and
        # NaN alike (any comparison with NaN is False, so "not (...)"
        # returns None) instead of trusting either.
        cred = data.get("cred")
        if cred is not None and cred != self._credential_id():
            return None      # another credential's attempt; says nothing about ours
        delta = time.time() - float(data["at"])
        if not (0.0 <= delta < self._login_cooldown_seconds):
            return None
        kind = data.get("kind") if data.get("kind") in ("login", "recovery") else "login"
        message = str(data.get("message") or "")
        error_type = data.get("error_type")
        if error_type is None:
            return kind, None
        if error_type == "ConfigurationError":
            return kind, ConfigurationError(message)
        return kind, AuthError(message)

    def _write_stamp(self, at: float, kind: str, error: BaseException | None) -> None:
        """Record an attempt for other processes -- the same atomic, owner-only,
        best-effort write as the cache. The message is the exception text (an
        error code and a hint), never a token or a credential.
        """
        payload = json.dumps({
            "at": at,
            "kind": kind,
            "error_type": type(error).__name__ if error is not None else None,
            "message": str(error)[:500] if error is not None else None,
            "cred": self._credential_id(),
        }).encode("utf-8")
        try:
            self._secure_cache_dir()
            fd, tmp_name = tempfile.mkstemp(dir=self._stamp_path.parent,
                                            prefix=".stamp-", suffix=".tmp")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self._stamp_path)
            except OSError:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
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

        The shared attempt stamp goes with the cache file: invalidate()
        means the next login is wanted, in this process or another.
        """
        self._account_jwt = None
        self._account_user_id = None
        self._leagues = {}
        self._last_login_at = None
        self._last_login_error = None
        self._recovery_attempted_for = None
        self._discard_cache_file()
        self._discard_stamp_file()

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

    async def _login_and_record(self, *, kind: str = "login") -> None:
        """Call `login()` and record the attempt's time/outcome for the
        cooldown machinery. Caller must hold `_login_lock`. Shared by
        `_maybe_login` (cooldown-gated, for an ordinary lookup) and
        `refresh_if_stale`/`refresh_account_if_stale` (unconditional, for
        a confirmed-stale 401 recovery) so both paths preserve a failed
        login's exception type identically -- see `_maybe_login`'s
        docstring for why that matters.
        """
        if not self._credentials.can_login:
            # login() would refuse this before opening a socket. A local
            # configuration fact is not a failed attempt: stamping it would
            # arm a *network* cooldown -- for this process and every other --
            # over a request that was never made.
            await self.login()
        self._last_login_at = time.time()
        try:
            await self.login()
        except Exception as exc:
            self._last_login_error = exc
            self._write_stamp(self._last_login_at, kind, exc)
            raise
        else:
            self._last_login_error = None
            self._write_stamp(self._last_login_at, kind, None)

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

        The attempt stamp extends this clock across processes: another
        process's recovery inside the window is refused the same way,
        and its failure is re-raised with its own type. That failure
        check is kind-agnostic, like `_maybe_login`'s: an *ordinary*
        login that just failed with ATH018 means the password is bad, and
        a recovery attempting it again a moment later would just fail
        again -- the never-retry rule does not care which kind of login
        found the bad password. Only the cooldown extension below (a
        *recent attempt* forcing this recovery to wait, as opposed to a
        confirmed-bad password forcing it to stop) stays recovery-specific,
        because an ordinary login succeeding elsewhere says nothing about
        whether a 401 recovery is currently in its own cooldown.
        """
        now = time.time()
        recent = self._recent_shared_attempt()
        if isinstance(recent[1] if recent else None, ConfigurationError):
            # ATH018 is a permanent fact about the password: whichever kind of
            # login found it, retrying now would just find it again. A
            # transient failure (5xx, a dropped connection) says nothing about
            # whether this 401 can be recovered, and must not bar the attempt.
            raise recent[1]
        if ((self._last_recovery_login_at is not None
                and now - self._last_recovery_login_at < self._login_cooldown_seconds)
                or (recent is not None and recent[0] == "recovery")):
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

        Across processes the same two guards are the flock sidecar and the
        attempt stamp: once the lock is held the cache is re-read, so the
        loser of a race uses the winner's token instead of logging in
        again, and a recent attempt recorded by any process answers the
        way an in-process one does -- a failure re-raised with its
        original type, a success taken as already done. The failure half
        of that check is kind-agnostic on purpose: a recovery login that
        just failed with ATH018 means the password is bad, and an ordinary
        login retrying it a moment later would just fail again -- "never
        retry ATH018" does not care which kind of login found that out.
        Only a *success* is kind-specific, because a recent recovery
        succeeding says nothing about whether an ordinary lookup here is
        still needed.
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
            async with self._cross_process_lock():
                self._load_cache()          # adopt what another process wrote meanwhile
                if not still_needed():
                    return
                recent = self._recent_shared_attempt()
                if recent is not None:
                    if recent[1] is not None:      # any recent failure, whatever its kind
                        raise recent[1]
                    if recent[0] == "login":        # a recent success only counts if ordinary
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
        self._note_rejected(failed_token)
        async with self._login_lock:
            if self._usable(self._account_jwt, failed_token):
                return self._account_jwt

            async with self._cross_process_lock():
                self._load_cache()
                if self._usable(self._account_jwt, failed_token):
                    return self._account_jwt     # another process already recovered

                if self._recovery_attempted_for != failed_token:
                    # Before invalidate(), so a refusal leaves the cache intact.
                    self._begin_recovery_login()
                    self.invalidate()
                    self._recovery_attempted_for = failed_token
                    try:
                        await self._login_and_record(kind="recovery")
                    except Exception:  # noqa: BLE001, S110 -- outcome is read from _last_login_error below
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
        self._note_rejected(failed_token)
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
            if current is not None and self._usable(current.jwt, failed_token):
                return current.jwt

            async with self._cross_process_lock():
                self._load_cache()
                current = self._pick(alias)
                if current is not None and self._usable(current.jwt, failed_token):
                    return current.jwt           # another process already recovered

                if self._recovery_attempted_for != failed_token:
                    # Before invalidate(), so a refusal leaves the cache intact.
                    self._begin_recovery_login()
                    self.invalidate()
                    self._recovery_attempted_for = failed_token
                    try:
                        await self._login_and_record(kind="recovery")
                    except Exception:  # noqa: BLE001, S110 -- outcome is read from _last_login_error below
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
