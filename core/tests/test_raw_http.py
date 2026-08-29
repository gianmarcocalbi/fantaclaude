import asyncio
from datetime import UTC, datetime

import httpx
import pytest
import respx
from fantaclaude.config import WEB_COOKIE_KEY, load_env, web_cookie
from fantaclaude.ingest.http import (
    USER_AGENT,
    NotPublished,
    SourceError,
    WebSessionExpired,
    build_http,
    fetch_bytes,
    run_web,
)
from fantaclaude.ingest.raw import RawStore


def test_write_bytes_names_and_lists_like_write(tmp_path):
    store = RawStore(tmp_path)
    when = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
    raw = store.write_bytes("voti", b"PK\x03\x04binary", ext="xlsx", label="21-01", fetched_at=when)
    assert raw.path.name == "20260828T100000000000Z-voti-21-01.xlsx" and raw.path.read_bytes() == b"PK\x03\x04binary"
    assert raw.kind == "voti" and raw.sha256 == RawStore.sha256_of(raw.path)
    with pytest.raises(FileExistsError):
        store.write_bytes("voti", b"x", ext="xlsx", label="21-01", fetched_at=when)   # never overwritten
    other = store.write_bytes("voti", b"y", ext="xlsx", label="21-02", fetched_at=when)
    assert store.list("voti", ext="xlsx") == sorted([raw.path, other.path])
    assert store.list("voti", ext="xlsx", label="21-01") == [raw.path]
    assert store.list("voti") == []                                     # json by default, as before
    json_raw = store.write("advanced", {"a": 1}, label="20", fetched_at=when)
    assert json_raw.path.name == "20260828T100000000000Z-advanced-20.json"
    assert store.list("advanced", label="20") == [json_raw.path]
    plain = store.write("listone", {"a": 1}, fetched_at=when)
    assert plain.path.name == "20260828T100000000000Z-listone.json"    # Phase 0a naming unchanged


@respx.mock
async def test_fetch_bytes_maps_statuses_to_the_three_errors():
    respx.get("https://example.test/ok").mock(return_value=httpx.Response(200, content=b"body"))
    respx.get("https://example.test/gone").mock(return_value=httpx.Response(404))
    respx.get("https://example.test/expired").mock(return_value=httpx.Response(401))
    respx.get("https://example.test/forbidden").mock(return_value=httpx.Response(403))
    respx.get("https://example.test/to-login").mock(
        return_value=httpx.Response(302, headers={"location": "https://example.test/login?from=x"}))
    respx.get("https://example.test/elsewhere").mock(
        return_value=httpx.Response(302, headers={"location": "https://example.test/other"}))
    respx.get("https://example.test/boom").mock(return_value=httpx.Response(500, text="server says no"))
    respx.post("https://example.test/form").mock(return_value=httpx.Response(200, content=b"posted"))
    async with build_http() as http:
        assert await fetch_bytes(http, "https://example.test/ok") == b"body"
        assert await fetch_bytes(http, "https://example.test/form", method="POST",
                                 data={"league": "Serie_A"}) == b"posted"
        with pytest.raises(NotPublished):
            await fetch_bytes(http, "https://example.test/gone")
        for path in ("expired", "forbidden", "to-login"):
            with pytest.raises(WebSessionExpired):
                await fetch_bytes(http, f"https://example.test/{path}")
        with pytest.raises(SourceError) as excinfo:
            await fetch_bytes(http, "https://example.test/elsewhere")
        assert excinfo.value.status == 302 and not isinstance(excinfo.value, WebSessionExpired)
        with pytest.raises(SourceError, match="server says no"):
            await fetch_bytes(http, "https://example.test/boom")
    sent = respx.calls[0].request
    assert sent.headers["user-agent"] == USER_AGENT and USER_AGENT.startswith("fantaclaude/")
    form = respx.calls[1].request
    assert b"league=Serie_A" in form.content


@respx.mock
def test_run_web_runs_a_coroutine_with_one_client_and_closes_it():
    respx.get("https://example.test/ok").mock(return_value=httpx.Response(200, content=b"1"))

    async def go(http):
        return await fetch_bytes(http, "https://example.test/ok", params={"q": "z"})

    assert run_web(go) == b"1"
    assert str(respx.calls[0].request.url) == "https://example.test/ok?q=z"


def test_web_cookie_reads_env_over_dotenv_and_never_returns_blank(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    monkeypatch.delenv(WEB_COOKIE_KEY, raising=False)
    assert web_cookie() is None
    (tmp_path / ".env").write_text('FANTACALCIO_WEB_COOKIE="a=1; b=2"\n')
    assert web_cookie() == "a=1; b=2" and load_env()[WEB_COOKIE_KEY] == "a=1; b=2"
    monkeypatch.setenv(WEB_COOKIE_KEY, "   ")
    assert web_cookie() is None
    monkeypatch.setenv(WEB_COOKIE_KEY, "c=3")
    assert web_cookie() == "c=3"
    assert web_cookie({"FANTACALCIO_WEB_COOKIE": "d=4"}) == "d=4"


def test_aliases_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    from fantaclaude.paths import aliases_path

    assert aliases_path() == tmp_path.resolve() / "kb" / "rules" / "aliases.yml"


def test_polite_pause_is_a_real_sleep(monkeypatch):
    from fantaclaude.ingest import http as http_module

    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(http_module.asyncio, "sleep", fake_sleep)
    asyncio.run(http_module.polite_pause())
    asyncio.run(http_module.polite_pause(0.2))
    assert slept == [http_module.POLITE_DELAY_SECONDS, 0.2] and http_module.POLITE_DELAY_SECONDS >= 1.0
