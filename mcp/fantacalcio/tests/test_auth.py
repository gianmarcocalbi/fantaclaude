import asyncio
import base64
import fcntl
import json
import os
import time

import httpx
import pytest
import respx

from fantacalcio_mcp.auth import Auth, AuthError, decode_claims, is_expired
from fantacalcio_mcp.auth import _safe_json
from fantacalcio_mcp.config import ConfigurationError, Credentials

BASE = "https://apileague.fantacalcio.it"


def make_jwt(**claims) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.signature"


def league_jwt(exp_offset=31_536_000):
    return make_jwt(user_id="10426252", l_id="2578630", t_id="11560832",
                    role="user_league", exp=int(time.time()) + exp_offset)


@pytest.fixture
def login_response(fixture_json):
    payload = fixture_json("login")
    payload["data"]["jwt"] = make_jwt(user_id="10426252", role="user",
                                      exp=int(time.time()) + 31_536_000)
    payload["data"]["leghe"][0]["jwt"] = league_jwt()
    return payload


def test_decode_claims_reads_league_context():
    claims = decode_claims(league_jwt())
    assert claims["l_id"] == "2578630"
    assert claims["t_id"] == "11560832"
    assert claims["role"] == "user_league"


def test_is_expired_uses_skew():
    nearly = make_jwt(exp=int(time.time()) + 30)
    assert is_expired(nearly, skew=60) is True
    assert is_expired(nearly, skew=0) is False


async def test_login_caches_league_tokens(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "APPKEY", BASE)
            token = await auth.token_for()
    assert route.called
    assert decode_claims(token)["l_id"] == "2578630"
    saved = json.loads(cache.read_text())
    assert "fantabalotelli3" in saved["leagues"]
    assert cache.stat().st_mode & 0o777 == 0o600


async def test_login_sends_app_key_and_credentials(tmp_path, login_response):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), tmp_path / "t.json",
                       http, "APPKEY", BASE).token_for()
    request = route.calls[0].request
    assert request.headers["app_key"] == "APPKEY"
    assert json.loads(request.content) == {"username": "u", "password": "p"}


async def test_cached_token_avoids_second_login(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
            await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
    assert route.call_count == 1


async def test_expired_cached_token_triggers_relogin(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    cache.write_text(json.dumps({
        "account": None,
        "leagues": {"fantabalotelli3": {
            "alias": "fantabalotelli3", "league_id": "2578630",
            "team_id": "11560832", "name": "Fantabalotelli3",
            "jwt": make_jwt(exp=int(time.time()) - 10),
        }},
    }))
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
    assert route.called


async def test_bad_credentials_raise_configuration_error(tmp_path):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(
            400, json={"code": "ATH018", "message": "Invalid username or password"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "bad"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.token_for()
    # I10: pin "never retried" -- a retry wrapper added later must not keep
    # this test green while hammering login with a wrong password.
    assert route.call_count == 1


async def test_token_only_mode_never_logs_in(tmp_path):
    token = league_jwt()
    # assert_all_called=False: this test's whole point is that the route is
    # registered but must NEVER be hit, so respx's default "all routes must
    # be called" check would otherwise fail this test for the right reason.
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials(token=token), tmp_path / "t.json", http, "K", BASE)
            assert await auth.token_for() == token
    assert not route.called


async def test_token_only_mode_cannot_recover(tmp_path):
    async with httpx.AsyncClient(base_url=BASE) as http:
        auth = Auth(Credentials(token=make_jwt(exp=int(time.time()) - 1)),
                    tmp_path / "t.json", http, "K", BASE)
        with pytest.raises(AuthError, match="expired"):
            await auth.token_for()


async def test_unknown_alias_lists_available(tmp_path, login_response):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(AuthError, match="fantabalotelli3"):
                await auth.token_for("nonexistent")


# ---------------------------------------------------------------------------
# Fix round 1 regression tests
# ---------------------------------------------------------------------------

async def test_unknown_alias_does_not_relogin_within_cooldown(tmp_path, login_response):
    """C1: a plain lookup miss (unknown/unspecified alias) must not force a
    fresh login on every single call. Without the fix, `_pick` returning
    None for "not found" looked identical to "cache empty", so 3 calls
    produced 3 logins even with a warm, valid cache.
    """
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            for _ in range(3):
                with pytest.raises(AuthError, match="fantabalotelli3"):
                    await auth.token_for("nonexistent")
    assert route.call_count == 1


async def test_concurrent_cold_start_single_flights_login(tmp_path, login_response):
    """I2: MCP clients parallelise tool calls, so the first prompt after a
    restart can call token_for() many times concurrently against a cold
    cache. Without single-flight locking, each one races ahead and posts
    its own login before any of them sees the cache populated.

    The side_effect adds a real `await asyncio.sleep(0)` before responding,
    so the mocked request actually yields control back to the event loop
    -- without it, a fully synchronous mock resolves within one scheduling
    slot and never gives the other 7 tasks a chance to interleave, which
    would make this test pass even against the old, unlocked code for the
    wrong reason.
    """
    cache = tmp_path / "tokens.json"

    async def slow_login(request):
        await asyncio.sleep(0)
        return httpx.Response(200, json=login_response)

    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(side_effect=slow_login)
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            tokens = await asyncio.gather(*(auth.token_for() for _ in range(8)))
    assert route.call_count == 1
    assert len(set(tokens)) == 1


async def test_cache_directory_and_file_are_owner_only(tmp_path, login_response):
    """I3: the cache directory must not be left world/group readable (it
    was created 0755), and the file itself must never pass through a 0644
    window (write_text() then chmod leaves exactly that window open if the
    process dies in between).
    """
    cache = tmp_path / "nested" / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
    assert cache.parent.stat().st_mode & 0o777 == 0o700
    assert cache.stat().st_mode & 0o777 == 0o600
    # No leftover temp files from the atomic-write dance -- only the cache and
    # the two cross-process sidecars, every one of them owner-only.
    assert sorted(p.name for p in cache.parent.iterdir()) == [
        "login-attempt.json", "tokens.json", "tokens.json.lock"]
    for entry in cache.parent.iterdir():
        assert entry.stat().st_mode & 0o777 == 0o600, entry.name


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="permission checks are bypassed when running as root",
)
async def test_cache_write_failure_does_not_fail_login(tmp_path, login_response):
    """I6: caching is an optimisation. A read-only .auth/ directory must
    not turn a successful network login into a raised exception.
    """
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    cache = readonly_root / "sub" / "tokens.json"
    readonly_root.chmod(0o500)
    try:
        with respx.mock(base_url=BASE) as mock:
            mock.post("/onboarding/v1/login").mock(
                return_value=httpx.Response(200, json=login_response))
            async with httpx.AsyncClient(base_url=BASE) as http:
                token = await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
        assert decode_claims(token)["l_id"] == "2578630"
        assert not cache.exists()
    finally:
        readonly_root.chmod(0o700)


@pytest.mark.parametrize("garbage", [
    "null", "[]", '"just a string"',
    '{"leagues": {"x": {"alias": "x"}}}',  # LeagueToken entry missing required keys
])
async def test_corrupt_cache_is_treated_as_cold_start(tmp_path, login_response, garbage):
    """I4: schema drift or a hand-edited/partial cache file must never
    crash server startup -- fail closed to a cold start instead.
    """
    cache = tmp_path / "tokens.json"
    cache.write_text(garbage)
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)  # must not raise
            token = await auth.token_for()
    assert route.called
    assert decode_claims(token)["l_id"] == "2578630"


async def test_unreadable_cached_token_triggers_relogin(tmp_path, login_response):
    """I5: a cached jwt that fails to decode (corruption, truncation) must
    be treated as a cache miss and healed by a fresh login, not raised as
    an unhandled AuthError on every call.
    """
    cache = tmp_path / "tokens.json"
    cache.write_text(json.dumps({
        "account": None, "user_id": None, "username": "u",
        "leagues": {"fantabalotelli3": {
            "alias": "fantabalotelli3", "league_id": "2578630",
            "team_id": "11560832", "name": "Fantabalotelli3",
            "jwt": "not-a-jwt-at-all",
        }},
    }))
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            token = await Auth(Credentials("u", "p"), cache, http, "K", BASE).token_for()
    assert route.called
    assert decode_claims(token)["l_id"] == "2578630"


def test_is_expired_fails_closed_without_exp_claim():
    """I7: every real token from this API carries `exp`; a token that
    doesn't must not be trusted as eternal.
    """
    assert is_expired(make_jwt(role="user")) is True


def test_is_expired_fails_closed_on_non_numeric_exp():
    """I8: a non-numeric exp claim must fail closed, not crash with a bare
    ValueError/TypeError out of float(exp).
    """
    assert is_expired(make_jwt(exp="soon")) is True


def test_decode_claims_rejects_non_dict_payload():
    """I8: a JWT whose payload decodes to a scalar/array/string (not an
    object) must raise AuthError, not silently return something whose
    .get("exp") blows up later with a bare AttributeError.
    """
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    token = f"{seg({'alg': 'RS256'})}.{seg([1, 2, 3])}.sig"
    with pytest.raises(AuthError):
        decode_claims(token)


def test_decode_claims_rejects_none():
    """I8: decode_claims(None) must surface as AuthError, not a raw
    AttributeError -- a mangled FANTACALCIO_LEAGUE_TOKEN paste should fail
    loudly and clearly, not crash a tool call.
    """
    with pytest.raises(AuthError):
        decode_claims(None)  # type: ignore[arg-type]


def test_decode_claims_rejects_unreadable_token():
    with pytest.raises(AuthError):
        decode_claims("not-a-jwt")


async def test_cache_is_discarded_when_username_changes(tmp_path, login_response):
    """I9: the on-disk cache lives at a fixed workspace path, independent
    of credentials. If .env is re-pointed at a different account, the
    stale cache must not be served -- it must be discarded and a fresh
    login forced. (This is not hypothetical: this project's own .env was
    re-pointed at a different account during this work.)
    """
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("alice", "p1"), cache, http, "K", BASE).token_for()
            assert route.call_count == 1
            saved = json.loads(cache.read_text())
            assert saved["username"] == "alice"

            auth_bob = Auth(Credentials("bob", "p2"), cache, http, "K", BASE)
            # The stale cache must not be trusted at construction time.
            assert auth_bob.list_leagues() == []
            await auth_bob.token_for()
    assert route.call_count == 2  # bob forced a real second login


async def test_account_token_logs_in_and_caches(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            token = await auth.account_token()
            token2 = await auth.account_token()
    assert route.call_count == 1
    claims = decode_claims(token)
    assert claims["role"] == "user"
    assert "l_id" not in claims
    assert token == token2


async def test_invalidate_forces_fresh_login_and_removes_cache_file(tmp_path, login_response):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            await auth.token_for()
            assert route.call_count == 1
            auth.invalidate()
            assert auth.list_leagues() == []
            assert not cache.exists()
            # Task 5's 401 recovery is invalidate() + token_for()/
            # account_token(): this must force a real second login, not be
            # swallowed by the cooldown that guards C1/I2.
            await auth.token_for()
    assert route.call_count == 2


async def test_list_leagues_reflects_login(tmp_path, login_response):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            assert auth.list_leagues() == []
            await auth.token_for()
    leagues = auth.list_leagues()
    assert [lg.alias for lg in leagues] == ["fantabalotelli3"]
    assert leagues[0].league_id == "2578630"
    assert leagues[0].team_id == "11560832"


def test_safe_json_returns_empty_dict_for_non_json_body():
    response = httpx.Response(400, text="<html>not json</html>")
    assert _safe_json(response) == {}


# ---------------------------------------------------------------------------
# Fix round 2 regression tests
# ---------------------------------------------------------------------------

async def test_bad_credentials_stay_configuration_error_within_cooldown(tmp_path):
    """N1: a failed login must keep its original exception type on a later
    cooldown-suppressed call. ATH018 must stay a ConfigurationError (never
    retried) on every call, not just the first -- an AuthError on call 2
    looks retryable, which is exactly the account-lockout path this whole
    cooldown mechanism exists to avoid.
    """
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(
            400, json={"code": "ATH018", "message": "Invalid username or password"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "bad"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.token_for()
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.token_for()
    assert route.call_count == 1


async def test_transient_login_failure_is_preserved_within_cooldown(tmp_path):
    """N1: a login failure that isn't a bad-credentials error (HTTP 500)
    must also keep reporting the original failure on a cooldown-suppressed
    retry, instead of falling through to a misleading "league None not
    found" AuthError.
    """
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(500, text="boom"))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(AuthError, match="HTTP 500"):
                await auth.token_for()
            with pytest.raises(AuthError, match="HTTP 500"):
                await auth.token_for()
    assert route.call_count == 1


async def test_cooldown_expires_and_allows_rediscovery(tmp_path, login_response):
    """N2: pins that the cooldown actually expires. A bug that leaves
    _last_login_at permanently set would silently make a newly-joined
    league undiscoverable for the life of a long-running server, with
    nothing to catch it.
    """
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE,
                        login_cooldown=0.05)
            with pytest.raises(AuthError, match="fantabalotelli3"):
                await auth.token_for("nonexistent")
            assert route.call_count == 1
            await asyncio.sleep(0.1)
            with pytest.raises(AuthError, match="fantabalotelli3"):
                await auth.token_for("nonexistent")
    assert route.call_count == 2


# ---------------------------------------------------------------------------
# Fix round 3 regression tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="permission checks are bypassed when running as root",
)
async def test_cache_directory_is_tightened_without_a_login(tmp_path):
    """M7: `.auth/` was only tightened to 0700 as a side effect of writing
    the cache after a *successful login*. Token-only mode never logs in and
    never writes, so a directory created by anything else (mkdir, a git
    checkout, an earlier version) stayed 0755 -- world-readable, and about
    to hold year-long JWTs. Tighten it whenever the cache location is
    resolved, not only when we happen to write to it.
    """
    existing = tmp_path / "already-there"
    existing.mkdir(mode=0o755)
    os.chmod(existing, 0o755)   # defeat any umask interference
    async with httpx.AsyncClient(base_url=BASE) as http:
        Auth(Credentials(token=league_jwt()), existing / "tokens.json",
             http, "K", BASE)
    assert existing.stat().st_mode & 0o777 == 0o700


async def test_cache_directory_is_created_owner_only_without_a_login(tmp_path):
    """M7, cold variant: a `.auth/` that does not exist yet must be created
    0700 up front, not left to the first successful login to create.
    """
    missing = tmp_path / "not-yet" / "auth"
    async with httpx.AsyncClient(base_url=BASE) as http:
        Auth(Credentials(token=league_jwt()), missing / "tokens.json",
             http, "K", BASE)
    assert missing.is_dir()
    assert missing.stat().st_mode & 0o777 == 0o700


async def test_unwritable_cache_directory_does_not_break_construction(tmp_path):
    """M7 must stay best-effort: an unwritable parent is a reason to skip
    the tightening, never a reason to fail to build the server.
    """
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    readonly_root.chmod(0o500)
    try:
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials(token=league_jwt()),
                        readonly_root / "sub" / "tokens.json", http, "K", BASE)
            assert await auth.token_for()   # must not raise
    finally:
        readonly_root.chmod(0o700)


# ---- cross-process coordination ------------------------------------------
# Two Auth instances on one cache path stand in for two processes: flock is
# per open file description, so two opens of the same sidecar contend exactly
# as two processes would (verified on this platform before writing these).


def _cache_with(jwt: str) -> str:
    return json.dumps({"account": None, "user_id": None, "username": "u", "leagues": {
        "fantabalotelli3": {"alias": "fantabalotelli3", "league_id": "2578630",
                            "team_id": "11560832", "name": "Fantabalotelli3", "jwt": jwt}}})


async def test_two_cold_instances_share_one_login(tmp_path, login_response):
    cache = tmp_path / "tokens.json"

    async def slow_login(request):
        await asyncio.sleep(0.01)   # long enough for the second instance to reach the lock
        return httpx.Response(200, json=login_response)

    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(side_effect=slow_login)
        async with httpx.AsyncClient(base_url=BASE) as http:
            first = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            second = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            tokens = await asyncio.gather(first.token_for(), second.token_for())
    assert route.call_count == 1
    assert len(set(tokens)) == 1
    assert (tmp_path / "tokens.json.lock").stat().st_mode & 0o777 == 0o600


async def test_cross_process_lock_closes_fd_on_cancellation_during_poll(tmp_path, monkeypatch):
    """Fix round 2, finding A: a task cancelled while parked in the poll's
    `asyncio.sleep` must not leak the lock-sidecar fd. Closing it there is
    safe -- and required -- because the acquire is a non-blocking poll
    running synchronously on the event loop: unlike the earlier
    blocking-thread design, nothing is ever parked inside flock() on this
    descriptor for a close to race against.
    """
    cache = tmp_path / "tokens.json"
    lock_path = tmp_path / "tokens.json.lock"
    real_open, real_close = os.open, os.close

    # Hold the flock ourselves first, with the *real* os.open/close, so
    # Auth's poll spins on BlockingIOError long enough to be cancelled
    # mid-sleep instead of acquiring on its first try.
    holder_fd = real_open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder_fd, fcntl.LOCK_EX)

    opened: list[int] = []
    closed: list[int] = []

    def recording_open(path, flags, mode=0o777):
        fd = real_open(path, flags, mode)
        if str(path) == str(lock_path):
            opened.append(fd)
        return fd

    def recording_close(fd):
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "close", recording_close)
    monkeypatch.setattr("fantacalcio_mcp.auth._CROSS_PROCESS_LOCK_POLL_SECONDS", 0.001)

    try:
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)

            async def contend():
                async with auth._cross_process_lock():
                    pass  # never reached -- cancelled while polling

            task = asyncio.create_task(contend())
            await asyncio.sleep(0.02)   # let it open the fd and enter the poll
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        fcntl.flock(holder_fd, fcntl.LOCK_UN)
        real_close(holder_fd)

    assert opened, "Auth never reached the poll loop"
    assert closed == opened, "the fd opened for the poll must be closed on cancellation"


async def test_failed_login_in_one_instance_holds_the_cooldown_for_another(tmp_path):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(
            400, json={"code": "ATH018", "message": "Invalid username or password"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            first = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await first.token_for()
            second = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await second.token_for()
    assert route.call_count == 1
    stamp_path = tmp_path / "login-attempt.json"
    stamp = json.loads(stamp_path.read_text())
    assert set(stamp) == {"at", "kind", "error_type", "message"}
    assert stamp["kind"] == "login" and stamp["error_type"] == "ConfigurationError"
    assert "eyJhbGci" not in stamp_path.read_text()
    assert stamp_path.stat().st_mode & 0o777 == 0o600


async def test_shared_cooldown_expires(tmp_path):
    cache = tmp_path / "tokens.json"
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(
            400, json={"code": "ATH018", "message": "Invalid username or password"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            first = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError):
                await first.token_for()
            stamp_path = tmp_path / "login-attempt.json"
            stamp = json.loads(stamp_path.read_text())
            stamp["at"] = time.time() - 120          # older than the 60 s cooldown
            stamp_path.write_text(json.dumps(stamp))
            second = Auth(Credentials("u", "bad"), cache, http, "K", BASE)
            with pytest.raises(ConfigurationError):
                await second.token_for()
    assert route.call_count == 2


@pytest.mark.parametrize("garbage", [
    "null", "[]", '{"at": "soon"}', "{not json",
    # The four payloads above all bail at the isinstance guard and never
    # reach the delta check -- a future-dated "at" (or NaN) needs its own
    # case: a one-sided ">= cooldown" comparison gives a non-positive delta
    # for either, which reads as "recent" forever instead of being ignored.
    json.dumps({"at": time.time() + 86_400}),
])
async def test_corrupt_stamp_is_ignored(tmp_path, login_response, garbage):
    (tmp_path / "login-attempt.json").write_text(garbage)
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), tmp_path / "tokens.json", http, "K", BASE).token_for()
    assert route.call_count == 1


async def test_recovery_adopts_a_token_another_process_already_refreshed(tmp_path):
    cache = tmp_path / "tokens.json"
    stale = league_jwt(exp_offset=3_600)
    fresh = league_jwt(exp_offset=7_200)      # a different string, still valid
    cache.write_text(_cache_with(stale))
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            assert await auth.token_for() == stale
            cache.write_text(_cache_with(fresh))    # "another process" recovered meanwhile
            assert await auth.refresh_if_stale(stale) == fresh
    assert not route.called


async def test_recovery_honours_a_failed_recovery_from_another_process(tmp_path):
    cache = tmp_path / "tokens.json"
    stale = league_jwt(exp_offset=3_600)
    cache.write_text(_cache_with(stale))
    (tmp_path / "login-attempt.json").write_text(json.dumps({
        "at": time.time(), "kind": "recovery", "error_type": "ConfigurationError",
        "message": "ATH018: Invalid username or password"}))
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            assert await auth.token_for() == stale
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.refresh_if_stale(stale)
            assert cache.exists(), "a refusal must leave the cache intact"
    assert not route.called


async def test_recovery_honours_a_failed_ordinary_login_from_another_process(tmp_path):
    """The never-retry rule for ATH018 does not care which kind of login
    found the bad password: an *ordinary* login that just failed elsewhere
    must stop a recovery from posting the same known-bad credentials again,
    the same way a failed recovery stops another recovery above."""
    cache = tmp_path / "tokens.json"
    stale = league_jwt(exp_offset=3_600)
    cache.write_text(_cache_with(stale))
    (tmp_path / "login-attempt.json").write_text(json.dumps({
        "at": time.time(), "kind": "login", "error_type": "ConfigurationError",
        "message": "ATH018: Invalid username or password"}))
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), cache, http, "K", BASE)
            assert await auth.token_for() == stale
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.refresh_if_stale(stale)
            assert cache.exists(), "a refusal must leave the cache intact"
    assert not route.called


async def test_ordinary_login_is_not_blocked_by_a_recent_recovery_stamp(tmp_path, login_response):
    """A recovery elsewhere must not stop a cold process from logging in when
    the cache it re-reads has nothing usable -- only an ordinary attempt or a
    failure holds an ordinary login back."""
    (tmp_path / "login-attempt.json").write_text(json.dumps({
        "at": time.time(), "kind": "recovery", "error_type": None, "message": None}))
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login_response))
        async with httpx.AsyncClient(base_url=BASE) as http:
            await Auth(Credentials("u", "p"), tmp_path / "tokens.json", http, "K", BASE).token_for()
    assert route.call_count == 1


async def test_ordinary_login_honours_a_failed_recovery_stamp_from_another_process(tmp_path):
    """The never-retry rule for ATH018 does not care which kind of login
    found the bad password: a *recovery* that just failed elsewhere must
    stop a cold ordinary login from posting the same known-bad credentials
    again, and it must see the original ConfigurationError -- contrast with
    the success case above, where only a same-kind success suppresses the
    call."""
    (tmp_path / "login-attempt.json").write_text(json.dumps({
        "at": time.time(), "kind": "recovery", "error_type": "ConfigurationError",
        "message": "ATH018: Invalid username or password"}))
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboarding/v1/login")
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "bad"), tmp_path / "tokens.json", http, "K", BASE)
            with pytest.raises(ConfigurationError, match="ATH018"):
                await auth.token_for()
    assert not route.called
