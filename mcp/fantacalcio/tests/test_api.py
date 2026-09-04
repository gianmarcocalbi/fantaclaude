import asyncio
import base64
import json
import time

import httpx
import pytest
import respx
from fantacalcio_mcp.api import ApiError, FantacalcioAPI
from fantacalcio_mcp.auth import Auth, AuthError
from fantacalcio_mcp.config import ConfigurationError, Credentials

BASE = "https://apileague.fantacalcio.it"


def make_jwt(**claims):
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.sig"


@pytest.fixture
def valid_token():
    return make_jwt(l_id="2578630", t_id="11560832", role="user_league",
                    exp=int(time.time()) + 31_536_000)


@pytest.fixture
async def api(tmp_path, valid_token):
    async with httpx.AsyncClient(base_url=BASE) as http:
        auth = Auth(Credentials(token=valid_token), tmp_path / "t.json",
                    http, "APPKEY", BASE)
        yield FantacalcioAPI(http, auth, BASE, "APPKEY")


async def test_get_sends_both_auth_headers(api, fixture_json, valid_token):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/league/profile").mock(
            return_value=httpx.Response(200, json=fixture_json("league_profile")))
        await api.league_profile()
    request = route.calls[0].request
    assert request.headers["app_key"] == "APPKEY"
    assert request.headers["Authorization"] == f"Bearer {valid_token}"


async def test_teams_passes_page_parameter(api, fixture_json):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/league/teams").mock(
            return_value=httpx.Response(200, json=fixture_json("teams")))
        await api.teams(page=3)
    assert route.calls[0].request.url.params["page"] == "3"


async def test_participants_passes_pagination(api, fixture_json):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/invitation/participants").mock(
            return_value=httpx.Response(200, json=fixture_json("participants")))
        await api.participants(page_number=2, page_size=50)
    params = route.calls[0].request.url.params
    assert params["pageNumber"] == "2" and params["pageSize"] == "50"


async def test_known_error_code_is_mapped(api):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/market/v1/time").mock(return_value=httpx.Response(
            401, json={"code": "ATH000", "message": "No Appkey authorized"}))
        with pytest.raises(ApiError) as excinfo:
            await api.server_time()
    assert excinfo.value.code == "ATH000"
    assert "app_key" in str(excinfo.value)


async def test_unknown_error_passes_through_verbatim(api):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/market/v1/time").mock(return_value=httpx.Response(
            500, json={"code": "ZZZ999", "message": "boom"}))
        with pytest.raises(ApiError, match="boom") as excinfo:
            await api.server_time()
    assert excinfo.value.status == 500


async def test_401_retries_once_after_relogin(tmp_path, fixture_json, valid_token):
    login = fixture_json("login")
    login["data"]["jwt"] = make_jwt(role="user", exp=int(time.time()) + 3600)
    login["data"]["leghe"][0]["jwt"] = valid_token

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login))
        time_route = mock.get("/market/v1/time").mock(side_effect=[
            httpx.Response(401, json={"code": "ATH001", "message": "expired"}),
            httpx.Response(200, json={"secs": "1", "mins": "1"}),
        ])
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            result = await FantacalcioAPI(http, auth, BASE, "K").server_time()

    assert result == {"secs": "1", "mins": "1"}
    assert time_route.call_count == 2
    assert login_route.call_count == 2   # initial token fetch + recovery


async def test_401_does_not_retry_twice(tmp_path, fixture_json, valid_token):
    login = fixture_json("login")
    login["data"]["leghe"][0]["jwt"] = valid_token
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(200, json=login))
        time_route = mock.get("/market/v1/time").mock(
            return_value=httpx.Response(401, json={"code": "ATH001", "message": "nope"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(ApiError):
                await FantacalcioAPI(http, auth, BASE, "K").server_time()
    assert time_route.call_count == 2


async def test_profile_resolves_user_id_from_account_token(api, fixture_json):
    account_jwt = make_jwt(user_id="10426252", role="user",
                           exp=int(time.time()) + 31_536_000)
    api._auth._account_jwt = account_jwt
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v2/profile/10426252").mock(
            return_value=httpx.Response(200, json=fixture_json("profile")))
        await api.profile()
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {account_jwt}"


async def test_profile_401_retries_once_after_relogin(tmp_path, fixture_json):
    login = fixture_json("login")
    account_jwt_1 = make_jwt(user_id="10426252", role="user", exp=int(time.time()) + 3600)
    account_jwt_2 = make_jwt(user_id="10426252", role="user",
                             exp=int(time.time()) + 31_536_000)
    login["data"]["jwt"] = account_jwt_1
    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=[
            httpx.Response(200, json=login),
            httpx.Response(200, json={**login, "data": {**login["data"], "jwt": account_jwt_2}}),
        ])
        profile_route = mock.get("/onboarding/v2/profile/10426252").mock(side_effect=[
            httpx.Response(401, json={"code": "ATH001", "message": "expired"}),
            httpx.Response(200, json=fixture_json("profile")),
        ])
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            await FantacalcioAPI(http, auth, BASE, "K").profile()
    assert profile_route.call_count == 2
    assert login_route.call_count == 2


async def test_configuration_error_is_not_retried(tmp_path, fixture_json):
    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(
            return_value=httpx.Response(
                401, json={"code": "ATH018", "message": "bad credentials"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(ConfigurationError):
                await FantacalcioAPI(http, auth, BASE, "K").server_time()
    assert login_route.call_count == 1


async def test_concurrent_401s_collapse_onto_single_recovery_login(tmp_path, fixture_json):
    """N1: 6 different league-scoped endpoints, all 401ing, called
    concurrently against one shared Auth/FantacalcioAPI, must collapse
    onto exactly one recovery login -- not one per concurrent 401.

    Per-request the "at most one invalidate()+relogin+retry" rule always
    held; the bug was in the aggregate: a bare `invalidate()` clears the
    login cooldown, so every concurrent 401 forced its *own* fresh login
    against the real server (measured against the pre-fix code: 6
    concurrent 401s produced 7 logins total, one per request plus the
    initial). `asyncio.sleep(0)` in every mocked response forces genuine
    interleaving -- without it respx's mocked transport resolves each
    request synchronously within one scheduling slot and this test would
    pass vacuously even against the buggy code, the same trap Task 4's
    concurrency test (test_concurrent_cold_start_single_flights_login)
    already had to avoid.
    """
    login = fixture_json("login")
    login_calls = {"n": 0}

    async def slow_login(request):
        await asyncio.sleep(0)
        # Each call mints a genuinely fresh league token. Reusing one fixed
        # token across every login response would make refresh_if_stale's
        # "has the cache already moved past the token that just failed?"
        # comparison always see "no" (old == new), defeating the very
        # short-circuit this test exists to pin -- every concurrent
        # recoverer would (wrongly) conclude it still needs to log in.
        login_calls["n"] += 1
        fresh_league_jwt = make_jwt(l_id="2578630", t_id="11560832", role="user_league",
                                    exp=int(time.time()) + 31_536_000,
                                    nonce=login_calls["n"])
        body = json.loads(json.dumps(login))
        body["data"]["jwt"] = make_jwt(role="user", exp=int(time.time()) + 31_536_000)
        body["data"]["leghe"][0]["jwt"] = fresh_league_jwt
        return httpx.Response(200, json=body)

    async def slow_401(request):
        await asyncio.sleep(0)
        return httpx.Response(401, json={"code": "ATH001", "message": "expired"})

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=slow_login)
        mock.get("/onboarding/v1/league/profile").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/status").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/competitions").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/teams/my").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/settings/rosters").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/settings/lineup").mock(side_effect=slow_401)

        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            api = FantacalcioAPI(http, auth, BASE, "K")
            results = await asyncio.gather(
                api.league_profile(), api.league_status(), api.competitions(),
                api.my_team(), api.roster_settings(), api.lineup_settings(),
                return_exceptions=True,
            )

    assert len(results) == 6
    assert all(isinstance(r, ApiError) for r in results), results
    assert login_route.call_count == 2   # one initial (single-flighted) + one shared recovery


async def test_concurrent_profile_401s_collapse_onto_single_recovery_login(tmp_path,
                                                                           fixture_json):
    """N1, account-token path: `profile()` resolves its bearer via
    `Auth.account_token()`, not `token_for()`, and has the identical
    concurrent-login-storm exposure. 6 concurrent `profile()` calls, all
    401ing, must also collapse onto exactly one recovery login.
    """
    login = fixture_json("login")
    login_calls = {"n": 0}

    async def slow_login(request):
        await asyncio.sleep(0)
        # Same reasoning as the league-token test: a fresh account jwt per
        # call is required, or refresh_account_if_stale's staleness check
        # can never observe "someone already refreshed this".
        login_calls["n"] += 1
        fresh_account_jwt = make_jwt(user_id="10426252", role="user",
                                     exp=int(time.time()) + 31_536_000,
                                     nonce=login_calls["n"])
        body = json.loads(json.dumps(login))
        body["data"]["jwt"] = fresh_account_jwt
        return httpx.Response(200, json=body)

    async def slow_401(request):
        await asyncio.sleep(0)
        return httpx.Response(401, json={"code": "ATH001", "message": "expired"})

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=slow_login)
        mock.get("/onboarding/v2/profile/10426252").mock(side_effect=slow_401)

        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            api = FantacalcioAPI(http, auth, BASE, "K")
            results = await asyncio.gather(
                *(api.profile() for _ in range(6)), return_exceptions=True,
            )

    assert len(results) == 6
    assert all(isinstance(r, ApiError) for r in results), results
    assert login_route.call_count == 2


async def test_profile_raises_when_account_token_has_no_user_id(tmp_path, fixture_json):
    """Minor: api.py:97's `user_id` guard was untested."""
    login = fixture_json("login")
    login["data"]["jwt"] = make_jwt(role="user", exp=int(time.time()) + 31_536_000)  # no user_id
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboarding/v1/login").mock(return_value=httpx.Response(200, json=login))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            with pytest.raises(ApiError, match="user_id"):
                await FantacalcioAPI(http, auth, BASE, "K").profile()


async def test_concurrent_401s_with_failing_recovery_login_attempt_once(tmp_path, fixture_json):
    """N2: if the recovery login itself keeps failing -- exactly the
    scenario a burst of concurrent 401s is most likely to co-occur with
    (credentials just rotated/went bad) -- only the *first* waiter for a
    given stale token may attempt it. Every other concurrent waiter must
    reuse that attempt's outcome instead of also hammering /login, and
    every one of them must see the real error with its real type
    (ConfigurationError here, from ATH018), not a generic failure and not
    one login attempt per waiter.

    Scenario matches the coordinator's repro: warm the cache with one
    successful login, then fire 6 concurrent 401s while every subsequent
    login attempt permanently fails.
    """
    login = fixture_json("login")
    login_calls = {"n": 0}

    async def login_then_always_fail(request):
        await asyncio.sleep(0)
        login_calls["n"] += 1
        if login_calls["n"] == 1:
            fresh_league_jwt = make_jwt(l_id="2578630", t_id="11560832", role="user_league",
                                        exp=int(time.time()) + 31_536_000, nonce=0)
            body = json.loads(json.dumps(login))
            body["data"]["jwt"] = make_jwt(role="user", exp=int(time.time()) + 31_536_000)
            body["data"]["leghe"][0]["jwt"] = fresh_league_jwt
            return httpx.Response(200, json=body)
        return httpx.Response(401, json={"code": "ATH018", "message": "credentials rotated"})

    async def slow_401(request):
        await asyncio.sleep(0)
        return httpx.Response(401, json={"code": "ATH001", "message": "expired"})

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=login_then_always_fail)
        mock.get("/onboarding/v1/league/profile").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/status").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/competitions").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/teams/my").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/settings/rosters").mock(side_effect=slow_401)
        mock.get("/onboarding/v1/league/settings/lineup").mock(side_effect=slow_401)

        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            api = FantacalcioAPI(http, auth, BASE, "K")
            await auth.token_for()   # warm the cache with one successful login
            results = await asyncio.gather(
                api.league_profile(), api.league_status(), api.competitions(),
                api.my_team(), api.roster_settings(), api.lineup_settings(),
                return_exceptions=True,
            )

    assert len(results) == 6
    assert all(isinstance(r, ConfigurationError) for r in results), results
    assert login_route.call_count == 2   # warm-up + exactly one failed recovery attempt


async def test_concurrent_profile_401s_with_failing_recovery_login_attempt_once(tmp_path,
                                                                                fixture_json):
    """N2, account-token path: identical guarantee for `refresh_account_if_stale`."""
    login = fixture_json("login")
    login_calls = {"n": 0}

    async def login_then_always_fail(request):
        await asyncio.sleep(0)
        login_calls["n"] += 1
        if login_calls["n"] == 1:
            fresh_account_jwt = make_jwt(user_id="10426252", role="user",
                                         exp=int(time.time()) + 31_536_000, nonce=0)
            body = json.loads(json.dumps(login))
            body["data"]["jwt"] = fresh_account_jwt
            return httpx.Response(200, json=body)
        return httpx.Response(401, json={"code": "ATH018", "message": "credentials rotated"})

    async def slow_401(request):
        await asyncio.sleep(0)
        return httpx.Response(401, json={"code": "ATH001", "message": "expired"})

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=login_then_always_fail)
        mock.get("/onboarding/v2/profile/10426252").mock(side_effect=slow_401)

        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            api = FantacalcioAPI(http, auth, BASE, "K")
            await auth.account_token()   # warm the cache with one successful login
            results = await asyncio.gather(
                *(api.profile() for _ in range(6)), return_exceptions=True,
            )

    assert len(results) == 6
    assert all(isinstance(r, ConfigurationError) for r in results), results
    assert login_route.call_count == 2


async def test_concurrent_ambiguous_default_alias_recovery_attempts_login_once(tmp_path,
                                                                                fixture_json):
    """N2 follow-up: an ambiguous default alias (`alias=None` with more
    than one cached league) has the identical `current is None` shape as
    a failing recovery login, so it must collapse onto the same
    single-login guarantee. Verified with a standalone script during the
    N2 review; committed here per the reviewer's follow-up so a future
    refactor of `_pick`/the final-check logic in `refresh_if_stale` has
    something in CI that would actually catch a regression.

    The two-league login body is built inline from the login fixture (a
    second `leghe` entry appended), the same technique the other N2
    concurrency tests already use -- no fixture file is touched. Because
    the account always has two leagues, `alias=None` can never resolve via
    `Auth._pick`, even after a successful recovery login: every concurrent
    `refresh_if_stale(stale_token, alias=None)` waiter must converge on
    the identical "league None not found" `AuthError`, with exactly one
    login call total.
    """
    login = fixture_json("login")
    body = json.loads(json.dumps(login))
    body["data"]["jwt"] = make_jwt(role="user", exp=int(time.time()) + 31_536_000)
    body["data"]["leghe"][0]["jwt"] = make_jwt(l_id="2578630", t_id="11560832",
                                               role="user_league",
                                               exp=int(time.time()) + 31_536_000)
    body["data"]["leghe"].append({
        "id": 9999999, "id_squadra": 8888888, "nome": "Second League",
        "alias": "second-league",
        "jwt": make_jwt(l_id="9999999", t_id="8888888", role="user_league",
                        exp=int(time.time()) + 31_536_000),
    })
    stale_token = make_jwt(l_id="stale", t_id="stale", role="user_league",
                           exp=int(time.time()) + 31_536_000)

    async def slow_login(request):
        await asyncio.sleep(0)
        return httpx.Response(200, json=body)

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=slow_login)
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            results = await asyncio.gather(
                auth.refresh_if_stale(stale_token, alias=None),
                auth.refresh_if_stale(stale_token, alias=None),
                auth.refresh_if_stale(stale_token, alias=None),
                return_exceptions=True,
            )

    assert len(results) == 3
    assert all(isinstance(r, AuthError) for r in results), results
    assert all("not found" in str(r) for r in results), results
    assert login_route.call_count == 1


async def test_sequential_401s_do_not_relogin_once_per_tool_call(tmp_path, fixture_json):
    """N3: the *sequential* twin of the concurrency guarantee above.

    The five earlier fix rounds bounded concurrent recoveries only. Because
    `invalidate()` deliberately wipes the login cooldown, and each recovery
    login mints a *different* token, `_recovery_attempted_for` never
    matched on the next tool call and nothing suppressed the next login:
    20 sequential tool calls against a permanently-401ing endpoint with a
    *succeeding* login produced 21 logins (measured against the pre-fix
    code) -- the exact number the concurrency work eliminated.

    A succeeding login plus a persistently rejecting endpoint is the
    dangerous combination (server-side token revocation, a WAF answering
    401, a league state transition): the credentials are fine, so nothing
    ever fails in a way that stops the loop, and login gets hammered
    precisely when that is most harmful. At most one recovery login may
    happen per cooldown window, so 20 calls must cost 2 logins total: the
    initial token fetch plus one recovery.
    """
    login = fixture_json("login")
    login_calls = {"n": 0}

    def fresh_login(request):
        # A genuinely distinct token per login, like the real server: this
        # is what defeated `_recovery_attempted_for` in the first place.
        login_calls["n"] += 1
        body = json.loads(json.dumps(login))
        body["data"]["jwt"] = make_jwt(user_id="10426252", role="user",
                                       exp=int(time.time()) + 31_536_000,
                                       nonce=login_calls["n"])
        body["data"]["leghe"][0]["jwt"] = make_jwt(
            l_id="2578630", t_id="11560832", role="user_league",
            exp=int(time.time()) + 31_536_000, nonce=login_calls["n"])
        return httpx.Response(200, json=body)

    errors = []
    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=fresh_login)
        mock.get("/market/v1/time").mock(
            return_value=httpx.Response(401, json={"code": "ATH001", "message": "expired"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            api = FantacalcioAPI(http, auth, BASE, "K")
            for _ in range(20):
                with pytest.raises((ApiError, AuthError)) as excinfo:
                    await api.server_time()
                errors.append(excinfo.value)

    assert login_route.call_count == 2, login_route.call_count
    # Every call after the one allowed recovery must say *why* it refused,
    # rather than silently degrading to a generic "not found".
    assert isinstance(errors[-1], AuthError)
    assert "fresh login" in str(errors[-1])


async def test_sequential_profile_401s_do_not_relogin_once_per_tool_call(tmp_path,
                                                                         fixture_json):
    """N3, account-token path: `refresh_account_if_stale` shares the same
    recovery clock, so 20 sequential 401ing `profile()` calls cost the same
    2 logins.
    """
    login = fixture_json("login")
    login_calls = {"n": 0}

    def fresh_login(request):
        login_calls["n"] += 1
        body = json.loads(json.dumps(login))
        body["data"]["jwt"] = make_jwt(user_id="10426252", role="user",
                                       exp=int(time.time()) + 31_536_000,
                                       nonce=login_calls["n"])
        return httpx.Response(200, json=body)

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=fresh_login)
        mock.get("/onboarding/v2/profile/10426252").mock(
            return_value=httpx.Response(401, json={"code": "ATH001", "message": "expired"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE)
            api = FantacalcioAPI(http, auth, BASE, "K")
            for _ in range(20):
                with pytest.raises((ApiError, AuthError)):
                    await api.profile()

    assert login_route.call_count == 2, login_route.call_count


async def test_recovery_cooldown_expires_and_allows_a_later_recovery(tmp_path,
                                                                      fixture_json):
    """N3: the recovery clock must be a cooldown, not a one-shot latch.

    A token that legitimately goes stale again an hour later must still be
    recoverable -- a bug that latched the guard permanently would make the
    server unable to heal itself for the rest of its lifetime, with
    nothing to catch it.
    """
    login = fixture_json("login")
    login_calls = {"n": 0}

    def fresh_login(request):
        login_calls["n"] += 1
        body = json.loads(json.dumps(login))
        body["data"]["jwt"] = make_jwt(role="user", exp=int(time.time()) + 31_536_000,
                                       nonce=login_calls["n"])
        body["data"]["leghe"][0]["jwt"] = make_jwt(
            l_id="2578630", t_id="11560832", role="user_league",
            exp=int(time.time()) + 31_536_000, nonce=login_calls["n"])
        return httpx.Response(200, json=body)

    with respx.mock(base_url=BASE) as mock:
        login_route = mock.post("/onboarding/v1/login").mock(side_effect=fresh_login)
        mock.get("/market/v1/time").mock(
            return_value=httpx.Response(401, json={"code": "ATH001", "message": "expired"}))
        async with httpx.AsyncClient(base_url=BASE) as http:
            auth = Auth(Credentials("u", "p"), tmp_path / "t.json", http, "K", BASE,
                        login_cooldown=0.05)
            api = FantacalcioAPI(http, auth, BASE, "K")
            with pytest.raises((ApiError, AuthError)):
                await api.server_time()
            assert login_route.call_count == 2   # initial + one recovery
            with pytest.raises((ApiError, AuthError)):
                await api.server_time()
            assert login_route.call_count == 2   # suppressed inside the window
            await asyncio.sleep(0.1)
            with pytest.raises((ApiError, AuthError)):
                await api.server_time()
    assert login_route.call_count == 3   # window elapsed: one more recovery allowed


async def test_players_hits_the_listone_endpoint_with_league_token(api, fixture_json, valid_token):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/onboarding/v1/league/players").mock(
            return_value=httpx.Response(200, json=fixture_json("players")))
        payload = await api.players()
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {valid_token}"
    assert [p["id"] for p in payload["players"]] == [3, 254, 5877]
