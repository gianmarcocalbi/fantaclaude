"""One-shot: build the two lineup fixtures from their captures in captured/.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_lineup.py

lineup_sample.json, from captured/lineup-03-2026-09-05.json: one teamLineup
response for giornata 3 taken mid-round (Phase 3b, Task 13, Step 1) -- `cal`
false, every `scr` 56, `b` null, a partial `tot`: the response a read-back
made before the platform calculates the round.

lineup_calculated_sample.json, from captured/lineup-03-2026-09-22.json: the
same match read back on 2026-09-22, after the round was calculated (Phase
3c) -- `cal` true, every listed player's `scr`/`cscr`/`m`/`b`, both sides'
`tot` and `points`, the match's `res` and `sign`. It is a raw file
`fantaclaude ingest lineup` wrote, copied as-is: already scrubbed with
`without_emails`.

Both keep the whole match, not only my own side: `load_lineup` and the
match-scores parser resolve which side is mine by team id, and a fixture
carrying only one side could never catch a version that instead assumed a
fixed position (Task 13's Ruling 2) -- my team being `away` in both is
exactly what makes that mistake visible.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
MY_TEAM = 19717181                # league.yml's my_team leaf
FIXTURES = (
    (ROOT / "captured" / "lineup-03-2026-09-05.json", HERE / "lineup_sample.json", False),
    (ROOT / "captured" / "lineup-03-2026-09-22.json", HERE / "lineup_calculated_sample.json", True),
)


def check(payload: dict, *, calculated: bool) -> None:
    for side in ("home", "away"):
        for key in ("tid", "mdl", "starts", "bench"):
            assert key in payload[side], f"{side}.{key} missing from the capture"
        for entry in payload[side]["starts"] + payload[side]["bench"]:
            assert "pid" in entry, f"{side}: an entry is missing pid: {entry!r}"
    assert payload["away"]["tid"] == MY_TEAM and payload["home"]["tid"] != MY_TEAM, (
        "the capture's own match must keep my team on the away side -- see the module docstring")
    assert bool(payload.get("cal")) is calculated, f"expected cal={calculated}, the capture says {payload.get('cal')!r}"
    text = json.dumps(payload)
    assert "@" not in text, "an email-shaped string survived the scrub"
    assert "eyJhbGci" not in text, "a JWT-shaped string is in the capture"


def main() -> None:
    for capture, out, calculated in FIXTURES:
        payload = json.loads(capture.read_text(encoding="utf-8"))
        check(payload, calculated=calculated)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {out.name}: idcomp {payload['idcomp']} mday {payload['mday']} cmday {payload['cmday']} "
              f"cal {payload.get('cal')} -- home {payload['home']['tid']} ({payload['home']['mdl']}), "
              f"away {payload['away']['tid']} ({payload['away']['mdl']})")


if __name__ == "__main__":
    main()
