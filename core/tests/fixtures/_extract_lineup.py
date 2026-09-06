"""One-shot: build lineup_sample.json from captured/lineup-03-2026-09-05.json.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_lineup.py

The capture is one teamLineup response for giornata 3 (Phase 3b, Task 13,
Step 1): both sides of one match, home tid 11560187 and away tid 19717181 --
my own team, per league.yml's my_team leaf. The whole match is kept, not
only my own side: `load_lineup` resolves which side is mine by team id, and
a fixture carrying only one side could never catch a version that instead
assumed a fixed position (Task 13's Ruling 2) -- my team being `away` here
is exactly what makes that mistake visible. The capture was already scrubbed
with `without_emails` and verified to carry zero email addresses and zero
JWTs; nothing here needs to scrub it again.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = ROOT / "captured" / "lineup-03-2026-09-05.json"
OUT = Path(__file__).with_name("lineup_sample.json")

MY_TEAM = 19717181                # league.yml's my_team leaf


def main() -> None:
    payload = json.loads(CAPTURE.read_text(encoding="utf-8"))
    for side in ("home", "away"):
        for key in ("tid", "mdl", "starts", "bench"):
            assert key in payload[side], f"{side}.{key} missing from the capture"
        for entry in payload[side]["starts"] + payload[side]["bench"]:
            assert "pid" in entry, f"{side}: an entry is missing pid: {entry!r}"
    assert payload["away"]["tid"] == MY_TEAM and payload["home"]["tid"] != MY_TEAM, (
        "the capture's own match must keep my team on the away side -- see the module docstring")
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}: idcomp {payload['idcomp']} mday {payload['mday']} cmday {payload['cmday']} -- "
         f"home {payload['home']['tid']} ({payload['home']['mdl']}), away {payload['away']['tid']} ({payload['away']['mdl']})")


if __name__ == "__main__":
    main()
