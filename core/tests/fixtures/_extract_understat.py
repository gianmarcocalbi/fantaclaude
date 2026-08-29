"""One-shot: build understat_sample.json from captured/understat-serie-a-2025.json.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_understat.py

Ten rows of the 2025-26 season chosen so that, matched against the
17-player listone_sample, every outcome appears: five matches (an initial
decides one, an accent another, a multi-token surname a third, a club alias
resolves Pulisic's "AC Milan"), one ambiguous (Josep Martínez against a
listone that only has Martinez L.), and four with no candidate at all
(Sulemana is also a mid-season mover, "Bologna,Cagliari"). The wrapper is
what fetch_advanced writes. Public statistics, nothing to scrub.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "understat-serie-a-2025.json"
OUT = Path(__file__).with_name("understat_sample.json")

NAMES = ["Lautaro Martínez", "Josep Martínez", "Rasmus Højlund", "Kevin De Bruyne", "Christian Pulisic",
         "Sead Kolasinac", "Sulemana", "Pietro Terracciano", "Jamie Vardy", "M&#039;Bala Nzola"]


def main() -> None:
    players = {p["player_name"]: p for p in json.loads(CAPTURE.read_text(encoding="utf-8"))["players"]}
    rows = [players[name] for name in NAMES]
    doc = {"season_id": 20, "understat_season": 2025, "payload": {"success": True, "players": rows}}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} players: {[r['id'] for r in rows]}")


if __name__ == "__main__":
    main()
