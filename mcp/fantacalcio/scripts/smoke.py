"""Live read-only check against the real league. Not part of the test suite."""

import asyncio

import httpx
from fantacalcio_mcp.api import FantacalcioAPI
from fantacalcio_mcp.auth import Auth
from fantacalcio_mcp.config import load_settings, token_cache_path


async def main() -> None:
    settings = load_settings()
    mode = ("login (username/password)" if settings.credentials.can_login
            else "token-only (no login path exercised)")
    print(f"mode: {mode}")
    async with httpx.AsyncClient(timeout=20.0) as http:
        auth = Auth(settings.credentials, token_cache_path(), http,
                    settings.app_key, settings.base_url)
        api = FantacalcioAPI(http, auth, settings.base_url, settings.app_key)
        for name, call in [
            ("league_profile", api.league_profile()),
            ("league_status", api.league_status()),
            ("my_team", api.my_team()),
            ("teams", api.teams()),
            ("participants", api.participants()),
            ("server_time", api.server_time()),
        ]:
            try:
                result = await call
                size = len(result.get("data", result)) if isinstance(result, dict) else len(result)
                print(f"OK   {name:<16} ({size} keys/rows)")
            except Exception as exc:  # noqa: BLE001 - smoke script reports everything
                print(f"FAIL {name:<16} {exc}")


if __name__ == "__main__":
    asyncio.run(main())
