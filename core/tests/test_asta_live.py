import httpx
import pytest
import respx
from fantaclaude.ingest.asta_live import (
    FIREBASE_API_KEY,
    SIGNUP_URL,
    TOKEN_URL,
    AnonymousAuth,
    FeedError,
    check_session_code,
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
