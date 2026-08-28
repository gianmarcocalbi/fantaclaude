"""One-shot: build calendario_sample.html and uefa_sample.json from the captures.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_calendar.py

calendario_sample.html keeps the three large pills of giornata 2, 2026-27
(Milan-Venezia 17971, Fiorentina-Frosinone 17967, Monza-Udinese 17972)
inside a minimal document; feeding it twice exercises the dedupe the page's
compact pills need. uefa_sample.json is what fetch_uefa writes, for two
pages: UCL 2025-26 (two Italian league-phase matches, one Juventus match to
trip the unresolved-club error against the 17-player listone, one Paris-
Arsenal match to be filtered out) and UECL 2026-27 (Atalanta's qualifying
play-off, both legs). Matches are slimmed the way the raw column is
(translations, player events, referees, related matches and logo URLs
dropped) so the fixture stays small. Public schedules, nothing to scrub.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "captured" / "calendario-2026-27-giornata-2.html"
UCL = ROOT / "captured" / "uefa-ucl-2026-page0.json"
UECL = ROOT / "captured" / "uefa-uecl-2027-page0.json"
OUT_HTML = Path(__file__).with_name("calendario_sample.html")
OUT_JSON = Path(__file__).with_name("uefa_sample.json")

SERIE_A_IDS = ("17971", "17967", "17972")
UCL_IDS = ("2048058", "2047774", "2047742", "2047770")
UECL_IDS = ("2049260", "2049284")
DROP = {"playerEvents", "referees", "relatedMatches", "translations"}


def slim(value):
    if isinstance(value, dict):
        return {k: slim(v) for k, v in value.items() if k not in DROP and not k.endswith("LogoUrl")}
    if isinstance(value, list):
        return [slim(v) for v in value]
    return value


def main() -> None:
    html = PAGE.read_text(encoding="utf-8")
    blocks = []
    for match_id in SERIE_A_IDS:
        anchor = html.index(f"/{match_id}\"")
        start = html.rfind('<li class="match', 0, anchor)
        end = html.index("</li>", anchor) + len("</li>")
        block = html[start:end]
        assert block.count("SportsEvent") == 1 and "size-large" in block, match_id
        blocks.append(block)
    OUT_HTML.write_text('<!doctype html>\n<html><body>\n<ul class="match-list">\n' + "\n".join(blocks)
                        + "\n</ul>\n</body></html>\n", encoding="utf-8")
    pages = []
    for path, competition, season_id, ids in ((UCL, "UCL", 20, UCL_IDS), (UECL, "UECL", 21, UECL_IDS)):
        matches = {str(m["id"]): m for m in json.loads(path.read_text(encoding="utf-8"))}
        pages.append({"competition": competition, "season_id": season_id, "offset": 0,
                      "matches": [slim(matches[i]) for i in ids]})
    OUT_JSON.write_text(json.dumps(pages, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(blocks)} pills ({OUT_HTML.stat().st_size} bytes) and "
          f"{sum(len(p['matches']) for p in pages)} UEFA matches ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
