"""One-shot: build listone_sample.json from captured/listone-2026-08-23.json.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_listone.py

Seventeen players chosen to cover every Mantra role code (6-16 and 19), a
transfer-flagged name, a three-role player without B, and a player whose
Classic and Mantra quotazioni differ. `img` (a CDN path) is dropped; nothing
else in the listone is a secret -- names, clubs and prices are public.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "listone-2026-08-23.json"
OUT = Path(__file__).with_name("listone_sample.json")

IDS = [3, 5841, 2120, 254, 5877, 2764, 2194, 2423, 2097, 6052,
       2517, 536, 309, 152, 2297, 791, 2640]


def main() -> None:
    players = {p["id"]: p for p in json.loads(CAPTURE.read_text(encoding="utf-8"))["players"]}
    rows = [{k: v for k, v in players[i].items() if k != "img"} for i in IDS]
    OUT.write_text(json.dumps({"players": rows, "timestamp": 1787517550778},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    codes = sorted({c for r in rows for c in r["marle"]})
    print(f"wrote {len(rows)} players, role codes {codes}")


if __name__ == "__main__":
    main()
