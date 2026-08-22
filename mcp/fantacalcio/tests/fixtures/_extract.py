"""One-shot extraction of test fixtures from captured/api-dump.json.

Run from the workspace root:  uv run python mcp/fantacalcio/tests/fixtures/_extract.py
Scrubs every secret: JWTs, app_key, emails, and the league join password.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DUMP = ROOT / "captured" / "api-dump.json"
OUT = Path(__file__).parent

KEY_MAP = {
    "profile": "profile",
    "leagueProfile": "league_profile",
    "leagueStatus": "league_status",
    "competitions": "competitions",
    "myTeam": "my_team",
    "teams": "teams",
    "rosterSettings": "roster_settings",
    "lineupSettings": "lineup_settings",
    "calculationSettings": "calculation_settings",
    "participants": "participants",
    "invitees": "invitees",
    "serverTime": "server_time",
}

SECRET_KEYS = {"jwt", "token", "token_auth", "utente_token", "sendbird_token",
               "email", "parola", "app_key"}
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def scrub(node, key=""):
    if isinstance(node, dict):
        return {k: ("<scrubbed>" if k in SECRET_KEYS else scrub(v, k))
                for k, v in node.items() if k != "parola"}
    if isinstance(node, list):
        return [scrub(v, key) for v in node]
    if isinstance(node, str):
        node = JWT_RE.sub("<scrubbed>", node)
        if "@" in node:
            return "<scrubbed>"
    return node


def main() -> None:
    dump = json.loads(DUMP.read_text(encoding="utf-8"))
    for src, dest in KEY_MAP.items():
        if src not in dump:
            raise SystemExit(f"missing {src} in {DUMP}")
        (OUT / f"{dest}.json").write_text(
            json.dumps(scrub(dump[src]), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("wrote", dest)

    # The login response was never dumped wholesale; synthesise it from the
    # observed shape so auth tests have a realistic envelope.
    login = {
        "state": 1787414858653,
        "success": True,
        "update": True,
        "data": {
            "state_auth": 1724789741307,
            "token_auth": "<scrubbed>",
            "utente": {"id": 10426252, "username": "grimid3v", "confermato": 1},
            "leghe": [{
                "visibile": True, "ordine": 1, "admin": -1,
                "id": 2578630, "id_squadra": 11560832,
                "tipo_lega": 0, "tipo_gioco": 2,
                "nome": "Fantabalotelli3", "alias": "fantabalotelli3",
                "link": "https://leghe.fantacalcio.it/fantabalotelli3",
                "jwt": "<scrubbed>", "token": "<scrubbed>",
            }],
            "jwt": "<scrubbed>",
        },
        "error_msgs": None,
    }
    (OUT / "login.json").write_text(
        json.dumps(login, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote login")


if __name__ == "__main__":
    main()
