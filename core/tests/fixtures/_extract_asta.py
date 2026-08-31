"""One-shot: build asta_session_sample.jsonl from captured/fantaastalive-state-2026-08-23.json.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_asta.py

The capture is FantaAstaLive's local state before any auction -- no picks --
encoded as JSON twice (json.loads(json.load(f))). Its `settings` and its two
`teams` are kept as the session node carries them (the spec's node shape:
picks[], lastPick, selectedPlayerId, turnTeamId, status, locked, teams[],
settings, options, pickOrder, hostId, playerListHash); the peer ids and
uids are dropped, being opaque and read by nothing. `currentBudget` is kept
at its stale 500 on purpose: it is the field the mirror must never trust.

Team labels are scrubbed *here*, at extraction, and not only at
parse_snapshot: an @-shaped label becomes "team <id>" before it is ever
written to a committed file, so no future capture can leak an address into
the fixture even if the reader's scrubber were to change. The two scrubs
share one definition of the shape (league.settings.EMAIL_PATTERN), which is
deliberately narrower than a bare "@" so a nick like "@bomber" survives.

The picks are scripted here over listone_sample.json's ids, so the sequence
exercises everything the diff engine has to handle: a sale, a second sale,
a cost edit, an undo, the same player re-sold to another team while a lot
is on the block, the same snapshot twice, and a playerId the listone does
not have. A third team is added with an @-shaped label that is not an
address (no domain): the case the scrub must leave alone.
"""

import json
from pathlib import Path

from fantaclaude.league.settings import EMAIL_PATTERN

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "fantaastalive-state-2026-08-23.json"
OUT = Path(__file__).with_name("asta_session_sample.jsonl")

MARTINEZ, BASTONI, SVILAR, UNKNOWN = 2764, 2120, 5841, 999999
T0 = 1787600000000                                   # ms; the capture's own stamps are of this size


def scrub(label: object, team_id: int) -> str:
    """The same rule state.scrub_label applies, one step earlier: an
    address-shaped or empty label never reaches the committed fixture."""
    text = label.strip() if isinstance(label, str) else ""
    return f"team {team_id}" if not text or EMAIL_PATTERN.search(text) else text


def pick(player_id: int, team_id: int, cost: int, value: int, index: int) -> dict:
    return {"playerId": player_id, "teamId": team_id, "cost": cost, "value": value, "index": index,
            "timestamp": T0 + index * 60_000}


def main() -> None:
    local = json.loads(json.loads(CAPTURE.read_text(encoding="utf-8")))["_users"]["-1"]
    prices = {p["id"]: p["price"] for p in local["players"]}
    teams = [{"id": t["id"], "connection": {"label": scrub(t["connection"]["label"], t["id"]),
                                            "host": t["connection"]["host"]},
              "currentBudget": t["currentBudget"], "missingPlayers": t["missingPlayers"], "picksCount": t["picksCount"]}
             for t in local["teams"]]
    teams.append({"id": 2, "connection": {"label": scrub("@bomber", 2), "host": False}, "currentBudget": 500,
                  "missingPlayers": dict(teams[0]["missingPlayers"]), "picksCount": 0})
    a = pick(MARTINEZ, 0, 120, prices[MARTINEZ], 0)
    b = pick(BASTONI, 1, 40, prices[BASTONI], 1)
    b_edited = {**b, "cost": 45}
    b_resold = pick(BASTONI, 0, 45, prices[BASTONI], 2)               # re-sold: a new lot, a new stamp
    unknown = pick(UNKNOWN, 2, 3, 1, 3)
    steps = [([], None), ([a], None), ([a, b], None), ([a, b_edited], None), ([a], None),
             ([a, b_resold], SVILAR), ([a, b_resold], SVILAR), ([a, b_resold, unknown], None)]
    lines = []
    for picks, selected in steps:
        node = {"picks": picks, "lastPick": picks[-1] if picks else None, "selectedPlayerId": selected,
                "turnTeamId": len(picks) % 3, "status": "live", "locked": False, "teams": teams,
                "settings": local["settings"], "options": local["options"], "pickOrder": [0, 1, 2], "hostId": 0,
                "playerListHash": "sample"}
        lines.append(json.dumps(node, ensure_ascii=False, sort_keys=True))
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} snapshots, {len(teams)} teams, settings.roles {local['settings']['roles']}")


if __name__ == "__main__":
    main()
