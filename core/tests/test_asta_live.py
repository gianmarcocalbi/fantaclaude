import asyncio
import json

import httpx
import pytest
import respx
from fantaclaude.ingest.asta_live import (
    FIREBASE_API_KEY,
    LIVE,
    RECONNECTING,
    SIGNUP_URL,
    TOKEN_URL,
    AnonymousAuth,
    AstaLiveFeed,
    FeedError,
    apply_patch,
    apply_put,
    check_session_code,
    sse_events,
)


def test_session_codes_are_names_never_paths():
    assert check_session_code(" FA-nri-okm ") == "FA-nri-okm"
    for bad in ("", "  ", "FA/okm", "..", "FA\\okm", "FA\x00okm"):
        with pytest.raises(FeedError):
            check_session_code(bad)


@respx.mock
async def test_signup_once_then_cached_until_the_margin():
    respx.post(SIGNUP_URL).respond(
        200,
        json={
            "idToken": "tok-1",
            "refreshToken": "ref-1",
            "expiresIn": "3600",
            "localId": "anon",
        },
    )
    clock = [0.0]
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client, now=lambda: clock[0])
        assert await auth.token() == "tok-1"
        clock[0] = 3600 - 301  # still inside the margin
        assert await auth.token() == "tok-1"
    assert respx.calls.call_count == 1
    assert respx.calls.last.request.url.params["key"] == FIREBASE_API_KEY


@respx.mock
async def test_refresh_ahead_of_expiry_uses_the_refresh_token():
    respx.post(SIGNUP_URL).respond(
        200,
        json={
            "idToken": "tok-1",
            "refreshToken": "ref-1",
            "expiresIn": "3600",
            "localId": "anon",
        },
    )
    refresh = respx.post(TOKEN_URL).respond(
        200, json={"id_token": "tok-2", "refresh_token": "ref-2", "expires_in": "3600"}
    )
    clock = [0.0]
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client, now=lambda: clock[0])
        await auth.token()
        clock[0] = 3600 - 299  # past the margin: refresh fires
        assert await auth.token() == "tok-2"
    body = refresh.calls.last.request.content.decode()
    assert "grant_type=refresh_token" in body and "refresh_token=ref-1" in body


@respx.mock
async def test_a_failed_refresh_falls_back_to_a_fresh_anonymous_signup():
    signup = respx.post(SIGNUP_URL)
    signup.side_effect = [
        httpx.Response(
            200,
            json={
                "idToken": "tok-1",
                "refreshToken": "ref-1",
                "expiresIn": "3600",
                "localId": "a",
            },
        ),
        httpx.Response(
            200,
            json={
                "idToken": "tok-3",
                "refreshToken": "ref-3",
                "expiresIn": "3600",
                "localId": "b",
            },
        ),
    ]
    respx.post(TOKEN_URL).respond(400, json={"error": {"message": "TOKEN_EXPIRED"}})
    clock = [0.0]
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client, now=lambda: clock[0])
        await auth.token()
        clock[0] = 3600.0
        assert (
            await auth.token() == "tok-3"
        )  # anonymous: a new user is as good as the old one
    assert signup.call_count == 2


@respx.mock
async def test_a_refused_signup_is_a_feed_error_that_names_no_token():
    respx.post(SIGNUP_URL).respond(
        403, json={"error": {"message": "ADMIN_ONLY_OPERATION"}}
    )
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client)
        with pytest.raises(FeedError) as err:
            await auth.token()
    assert "403" in str(err.value) and "tok" not in str(err.value)


async def test_invalidate_forces_the_next_token_to_be_fetched_again():
    with respx.mock:
        respx.post(SIGNUP_URL).respond(
            200,
            json={
                "idToken": "tok-1",
                "refreshToken": "ref-1",
                "expiresIn": "3600",
                "localId": "anon",
            },
        )
        respx.post(TOKEN_URL).respond(
            200,
            json={"id_token": "tok-2", "refresh_token": "ref-2", "expires_in": "3600"},
        )
        async with httpx.AsyncClient() as client:
            auth = AnonymousAuth(client, now=lambda: 0.0)
            await auth.token()
            auth.invalidate()  # auth_revoked mid-stream lands here
            assert await auth.token() == "tok-2"


NODE = {
    "picks": [{"playerId": 100, "teamId": 0, "cost": 10, "index": 0}],
    "teams": [
        {"id": 0, "connection": {"label": "me"}},
        {"id": 1, "connection": {"label": "rival"}},
    ],
    "settings": {
        "budget": 500,
        "game": 2,
        "roles": {"gk": [3, 3], "mov": [22, 22], "size": [25, 25]},
    },
    "selectedPlayerId": None,
    "turnTeamId": 0,
    "status": "live",
    "locked": False,
}


def test_put_and_patch_maintain_the_node_the_way_firebase_documents_them():
    node = apply_put(None, "/", {"a": {"b": 1}, "c": 2})
    assert node == {"a": {"b": 1}, "c": 2}
    node = apply_put(node, "/a/b", 5)
    assert node["a"]["b"] == 5
    node = apply_put(node, "/d/0", {"x": 1})  # intermediate keys are created
    assert node["d"] == {"0": {"x": 1}}
    node = apply_patch(node, "/", {"c": 3, "e": 4})  # patch merges keys, put replaces
    assert node["c"] == 3 and node["e"] == 4 and node["a"] == {"b": 5}
    node = apply_put(node, "/e", None)  # null deletes
    assert "e" not in node


async def test_sse_events_parses_frames_and_ignores_comments():
    async def lines():
        for line in [
            "event: put",
            'data: {"path":"/","data":1}',
            "",
            ": keepalive comment",
            "event: keep-alive",
            "data: null",
            "",
            "data: no event name",
            "",
        ]:
            yield line

    events = [e async for e in sse_events(lines())]
    assert events == [
        ("put", '{"path":"/","data":1}'),
        ("keep-alive", "null"),
        ("message", "no event name"),
    ]


def _stream_response(frames: list[str]) -> httpx.Response:
    async def agen():
        for frame in frames:
            yield frame.encode()

    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=agen()
    )


def _frames(*events: tuple[str, dict | None]) -> list[str]:
    return [
        f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events
    ]


async def _run_feed(feed: AstaLiveFeed, until: asyncio.Event, timeout: float = 5.0):
    task = asyncio.create_task(feed.run())
    try:
        await asyncio.wait_for(until.wait(), timeout)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError, FeedError:
            pass


@respx.mock
async def test_the_stream_puts_patches_and_emits_snapshots(tmp_path):
    respx.post(SIGNUP_URL).respond(
        200,
        json={
            "idToken": "tok",
            "refreshToken": "ref",
            "expiresIn": "3600",
            "localId": "anon",
        },
    )
    respx.get("https://db.example/sessions/FA-nri-okm/state.json").mock(
        return_value=_stream_response(
            _frames(
                ("put", {"path": "/", "data": NODE}),
                ("keep-alive", None),
                ("patch", {"path": "/", "data": {"selectedPlayerId": 200}}),
                (
                    "put",
                    {
                        "path": "/picks/1",
                        "data": {"playerId": 200, "teamId": 1, "cost": 7, "index": 1},
                    },
                ),
            )
        )
    )
    seen: list = []
    statuses: list[str] = []
    done = asyncio.Event()

    async def on_snapshot(snap):
        seen.append(snap)
        if len(seen) == 3:
            done.set()

    async def on_status(status):
        statuses.append(status)

    capture = tmp_path / "cap" / "FA-nri-okm.jsonl"
    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-nri-okm",
            client=client,
            on_snapshot=on_snapshot,
            on_status=on_status,
            database_url="https://db.example",
            capture=capture,
            sleep=lambda s: asyncio.sleep(0),
        )
        await _run_feed(feed, done)
    assert statuses[0] == LIVE
    assert len(seen[0].picks) == 1 and seen[0].selected is None
    assert seen[1].selected == 200
    assert len(seen[2].picks) == 2 and seen[2].picks[1].player_id == 200
    lines = capture.read_text().strip().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["picks"][0]["playerId"] == 100
    auth_param = respx.calls[1].request.url.params["auth"]
    assert auth_param == "tok"


@respx.mock
async def test_a_dropped_stream_reconnects_with_backoff_and_a_full_snapshot_resumes(
    tmp_path,
):
    respx.post(SIGNUP_URL).respond(
        200,
        json={
            "idToken": "tok",
            "refreshToken": "ref",
            "expiresIn": "3600",
            "localId": "anon",
        },
    )
    route = respx.get("https://db.example/sessions/FA-nri-okm/state.json")
    route.side_effect = [
        _stream_response(
            _frames(("put", {"path": "/", "data": NODE}))
        ),  # ends: reconnect
        httpx.ConnectError("down"),  # still down
        _stream_response(_frames(("put", {"path": "/", "data": NODE}))),  # back
    ]
    slept: list[float] = []
    statuses: list[str] = []
    seen: list = []
    done = asyncio.Event()

    async def on_snapshot(snap):
        seen.append(snap)
        if len(seen) == 2:
            done.set()

    async def on_status(status):
        statuses.append(status)

    async def fake_sleep(seconds):
        slept.append(seconds)

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-nri-okm",
            client=client,
            on_snapshot=on_snapshot,
            on_status=on_status,
            database_url="https://db.example",
            sleep=fake_sleep,
        )
        await _run_feed(feed, done)
    assert statuses.count(LIVE) == 2 and RECONNECTING in statuses
    assert slept[:2] == [1.0, 2.0]  # backoff grew while it was down


@respx.mock
async def test_auth_revoked_invalidates_and_reconnects_with_a_fresh_token():
    respx.post(SIGNUP_URL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "idToken": "tok-1",
                    "refreshToken": "ref-1",
                    "expiresIn": "3600",
                    "localId": "a",
                },
            ),
        ]
    )
    respx.post(TOKEN_URL).respond(
        200, json={"id_token": "tok-2", "refresh_token": "ref-2", "expires_in": "3600"}
    )
    route = respx.get("https://db.example/sessions/FA-nri-okm/state.json")
    route.side_effect = [
        _stream_response(
            _frames(("put", {"path": "/", "data": NODE}), ("auth_revoked", None))
        ),
        _stream_response(_frames(("put", {"path": "/", "data": NODE}))),
    ]
    seen: list = []
    done = asyncio.Event()

    async def on_snapshot(snap):
        seen.append(snap)
        if len(seen) == 2:
            done.set()

    async def on_status(status):
        pass

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-nri-okm",
            client=client,
            on_snapshot=on_snapshot,
            on_status=on_status,
            database_url="https://db.example",
            sleep=lambda s: asyncio.sleep(0),
        )
        await _run_feed(feed, done)
    assert route.calls[0].request.url.params["auth"] == "tok-1"
    assert route.calls[1].request.url.params["auth"] == "tok-2"


@respx.mock
async def test_no_such_session_and_cancel_are_fatal():
    respx.post(SIGNUP_URL).respond(
        200,
        json={
            "idToken": "tok",
            "refreshToken": "ref",
            "expiresIn": "3600",
            "localId": "anon",
        },
    )
    respx.get("https://db.example/sessions/FA-none/state.json").mock(
        return_value=_stream_response(_frames(("put", {"path": "/", "data": None})))
    )

    async def nothing(_):
        pass

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-none",
            client=client,
            on_snapshot=nothing,
            on_status=nothing,
            database_url="https://db.example",
            sleep=lambda s: asyncio.sleep(0),
        )
        with pytest.raises(FeedError) as err:
            await feed.run()
    assert "FA-none" in str(err.value)

    respx.get("https://db.example/sessions/FA-shut/state.json").mock(
        return_value=_stream_response(
            _frames(("put", {"path": "/", "data": NODE}), ("cancel", None))
        )
    )
    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-shut",
            client=client,
            on_snapshot=nothing,
            on_status=nothing,
            database_url="https://db.example",
            sleep=lambda s: asyncio.sleep(0),
        )
        with pytest.raises(FeedError):
            await feed.run()


@respx.mock
async def test_a_5xx_from_the_edge_is_retried_but_another_4xx_is_still_fatal():
    # FeedError is reserved for what can never recover by retrying (module
    # docstring). A 503 from Google's edge is the textbook case that *does*
    # recover: raising FeedError there ended the mirror for good on one bad
    # response, on a night that happens once.
    respx.post(SIGNUP_URL).respond(
        200,
        json={
            "idToken": "tok",
            "refreshToken": "ref",
            "expiresIn": "3600",
            "localId": "anon",
        },
    )
    route = respx.get("https://db.example/sessions/FA-nri-okm/state.json")
    route.side_effect = [
        httpx.Response(503, text="upstream unavailable"),  # the edge, briefly
        httpx.Response(429, text="slow down"),  # rate-limited, also transient
        _stream_response(_frames(("put", {"path": "/", "data": NODE}))),  # back
    ]
    statuses: list[str] = []
    slept: list[float] = []
    done = asyncio.Event()

    async def on_snapshot(_snap):
        done.set()

    async def on_status(status):
        statuses.append(status)

    async def fake_sleep(seconds):
        slept.append(seconds)

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-nri-okm",
            client=client,
            on_snapshot=on_snapshot,
            on_status=on_status,
            database_url="https://db.example",
            sleep=fake_sleep,
        )
        await _run_feed(feed, done)
    assert done.is_set()  # the mirror survived both and resumed
    assert statuses[:2] == [RECONNECTING, RECONNECTING] and LIVE in statuses
    assert slept[:2] == [1.0, 2.0]  # the existing backoff, not a new retry loop

    respx.get("https://db.example/sessions/FA-gone/state.json").respond(404)
    async def nothing(_):
        pass

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-gone",
            client=client,
            on_snapshot=nothing,
            on_status=nothing,
            database_url="https://db.example",
            sleep=lambda s: asyncio.sleep(0),
        )
        with pytest.raises(FeedError) as err:
            await feed.run()
    assert "404" in str(err.value) and "FA-gone" in str(err.value)


@respx.mock
async def test_a_5xx_from_the_sign_in_endpoint_is_retried_not_fatal():
    # The same class of bug as the 5xx on the stream, one endpoint over. The
    # scenario it killed: the token refresh ~55 minutes in meets a 503 from
    # identitytoolkit, _refresh raises, token() falls through to _signup(),
    # which meets the same 503 -- FeedError out of _stream_once, and run()
    # never retries a FeedError, so the mirror was dead for the rest of a
    # night that happens once.
    signup = respx.post(SIGNUP_URL)
    signup.side_effect = [
        httpx.Response(503, text="identity toolkit unavailable"),  # the edge, briefly
        httpx.Response(429, json={"error": {"message": "QUOTA_EXCEEDED"}}),
        httpx.Response(
            200,
            json={
                "idToken": "tok",
                "refreshToken": "ref",
                "expiresIn": "3600",
                "localId": "anon",
            },
        ),
    ]
    respx.get("https://db.example/sessions/FA-nri-okm/state.json").mock(
        return_value=_stream_response(_frames(("put", {"path": "/", "data": NODE})))
    )
    statuses: list[str] = []
    slept: list[float] = []
    done = asyncio.Event()

    async def on_snapshot(_snap):
        done.set()

    async def on_status(status):
        statuses.append(status)

    async def fake_sleep(seconds):
        slept.append(seconds)

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-nri-okm",
            client=client,
            on_snapshot=on_snapshot,
            on_status=on_status,
            database_url="https://db.example",
            sleep=fake_sleep,
        )
        await _run_feed(feed, done)
    assert done.is_set()  # the mirror survived both and signed in on the third try
    assert statuses[:2] == [RECONNECTING, RECONNECTING] and LIVE in statuses
    assert slept[:2] == [1.0, 2.0]  # the existing backoff, not a new retry loop

    # and a refused sign-in is still fatal: 403 can only ever answer 403
    respx.post(SIGNUP_URL).mock(
        return_value=httpx.Response(
            403, json={"error": {"message": "ADMIN_ONLY_OPERATION"}}
        )
    )
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client)
        with pytest.raises(FeedError):
            await auth.token()


@respx.mock
async def test_a_5xx_on_the_refresh_still_leaves_the_400_fallback_alone():
    """The retry must not swallow the fallback that makes an expired token
    recover: a 400 TOKEN_EXPIRED is still a FeedError, which token() catches
    to sign up afresh, while a 503 propagates as a transport error for run()
    to back off over -- retrying is right there, signing up a new anonymous
    user against a broken edge is not."""
    signup = respx.post(SIGNUP_URL)
    signup.side_effect = [
        httpx.Response(
            200,
            json={
                "idToken": "tok-1",
                "refreshToken": "ref-1",
                "expiresIn": "3600",
                "localId": "a",
            },
        ),
        httpx.Response(
            200,
            json={
                "idToken": "tok-3",
                "refreshToken": "ref-3",
                "expiresIn": "3600",
                "localId": "b",
            },
        ),
    ]
    refresh = respx.post(TOKEN_URL)
    refresh.side_effect = [
        httpx.Response(503, text="securetoken unavailable"),
        httpx.Response(400, json={"error": {"message": "TOKEN_EXPIRED"}}),
    ]
    clock = [0.0]
    async with httpx.AsyncClient() as client:
        auth = AnonymousAuth(client, now=lambda: clock[0])
        await auth.token()
        clock[0] = 3600.0
        with pytest.raises(httpx.HTTPStatusError):  # retryable: run() backs off
            await auth.token()
        assert signup.call_count == 1  # and no new user was signed up behind it
        assert await auth.token() == "tok-3"  # the 400 fallback, still intact
    assert signup.call_count == 2


@respx.mock
async def test_a_torn_frame_reconnects_but_a_node_this_mirror_cannot_read_is_fatal():
    """A put/patch frame that will not decode is damaged transport: the next
    connect refetches a fresh full `put`, so it must reconnect rather than end
    the mirror. The node itself failing to parse stays fatal -- reconnecting
    would only deliver the same shape again, and the mirror never guesses."""
    respx.post(SIGNUP_URL).respond(
        200,
        json={
            "idToken": "tok",
            "refreshToken": "ref",
            "expiresIn": "3600",
            "localId": "anon",
        },
    )
    torn = [
        "event: put\ndata: {\"path\": \"/\", \"dat\n\n",           # json.JSONDecodeError
        'event: patch\ndata: {"path": "/"}\n\n',                    # KeyError: no "data"
        'event: put\ndata: ["path", "/"]\n\n',                      # TypeError: not an object
    ]
    route = respx.get("https://db.example/sessions/FA-nri-okm/state.json")
    route.side_effect = [
        _stream_response([frame]) for frame in torn
    ] + [_stream_response(_frames(("put", {"path": "/", "data": NODE})))]
    seen: list = []
    slept: list[float] = []
    done = asyncio.Event()

    async def on_snapshot(snap):
        seen.append(snap)
        done.set()

    async def on_status(_status):
        pass

    async def fake_sleep(seconds):
        slept.append(seconds)

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-nri-okm",
            client=client,
            on_snapshot=on_snapshot,
            on_status=on_status,
            database_url="https://db.example",
            sleep=fake_sleep,
        )
        await _run_feed(feed, done)
    assert len(seen) == 1 and slept[:3] == [1.0, 2.0, 4.0]  # three torn frames, three backoffs

    # the node itself, on the other hand, is fatal and stays fatal
    respx.get("https://db.example/sessions/FA-junk/state.json").mock(
        return_value=_stream_response(
            _frames(("put", {"path": "/", "data": {"picks": "not a list"}}))
        )
    )

    async def nothing(_):
        pass

    async with httpx.AsyncClient() as client:
        feed = AstaLiveFeed(
            "FA-junk",
            client=client,
            on_snapshot=nothing,
            on_status=nothing,
            database_url="https://db.example",
            sleep=lambda s: asyncio.sleep(0),
        )
        with pytest.raises(FeedError) as err:
            await feed.run()
    assert "FA-junk" in str(err.value)


def test_asta_captures_dir_is_under_raw(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    from fantaclaude.paths import asta_captures_dir, raw_dir

    assert asta_captures_dir() == raw_dir() / "asta_live"
