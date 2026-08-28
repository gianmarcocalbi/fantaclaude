"""Environment for the web sources -- the same .env the MCP reads.

FANTACALCIO_WEB_COOKIE is the fantacalcio.it *website* session, a different
login from the league API's (spec, open question 5). It is captured from a
browser by the account holder and pasted into .env; no code obtains it, so
there is no login here to hammer and nothing to lock. It is a secret: it is
read, sent, and never printed.
"""

from __future__ import annotations

import os

from fantacalcio_mcp.config import env_path, load_dotenv

WEB_COOKIE_KEY = "FANTACALCIO_WEB_COOKIE"


def load_env() -> dict[str, str]:
    """.env merged under the process environment, exactly as load_settings does."""
    return {**load_dotenv(env_path()), **os.environ}


def web_cookie(env: dict[str, str] | None = None) -> str | None:
    env = load_env() if env is None else env
    value = (env.get(WEB_COOKIE_KEY) or "").strip()
    return value or None
