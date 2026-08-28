"""One-shot: build calendario_sample.html, calendario_two_giornate_sample.html
and uefa_sample.json from the captures.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_calendar.py

calendario_sample.html keeps the three large pills of giornata 2, 2026-27
(Milan-Venezia 17971, Fiorentina-Frosinone 17967, Monza-Udinese 17972)
inside a minimal document; feeding it twice exercises the dedupe the page's
compact pills need.

calendario_two_giornate_sample.html is built from the season 21 giornata-1
page (captured 2026-08-28, the fetch that first surfaced Ruling R8a): a page
whose giornata has already been played also advertises the next one, so the
real page carries ten giornata-1 matches and ten giornata-2 matches, not one
giornata as Task 5 assumed from the giornata-2 capture alone (giornata 2
hadn't been played yet when that one was taken, so it never showed a third
giornata). This sample keeps two matches of each: Atalanta-Sassuolo (17955)
and Bologna-Lazio (17956) for giornata 1, Atalanta-Bologna (17965) and
Cagliari-Inter (17966) for giornata 2 -- enough to exercise "filter to the
giornata this page was fetched for" without a 6000-line fixture.

uefa_sample.json is what fetch_uefa writes, for two pages: UCL 2025-26 (two
Italian league-phase matches, one Juventus match to trip the unresolved-club
error against the 17-player listone, one Paris-Arsenal match to be filtered
out) and UECL 2026-27 (Atalanta's qualifying play-off, both legs). Matches
are slimmed the way the raw column is (translations, player events,
referees, related matches and logo URLs dropped) so the fixture stays small.
Public schedules, nothing to scrub.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "captured" / "calendario-2026-27-giornata-2.html"
PAGE1 = ROOT / "captured" / "calendario-2026-27-giornata-1.html"
UCL = ROOT / "captured" / "uefa-ucl-2026-page0.json"
UECL = ROOT / "captured" / "uefa-uecl-2027-page0.json"
OUT_HTML = Path(__file__).with_name("calendario_sample.html")
OUT_TWO_GIORNATE_HTML = Path(__file__).with_name("calendario_two_giornate_sample.html")
OUT_JSON = Path(__file__).with_name("uefa_sample.json")

SERIE_A_IDS = ("17971", "17967", "17972")
TWO_GIORNATE_IDS = ("17955", "17956", "17965", "17966")     # giornata 1 x2, giornata 2 x2, one page
UCL_IDS = ("2048058", "2047774", "2047742", "2047770")
UECL_IDS = ("2049260", "2049284")
DROP = {"playerEvents", "referees", "relatedMatches", "translations"}


def slim(value):
    if isinstance(value, dict):
        return {k: slim(v) for k, v in value.items() if k not in DROP and not k.endswith("LogoUrl")}
    if isinstance(value, list):
        return [slim(v) for v in value]
    return value


def blocks_for(html: str, match_ids) -> list[str]:
    blocks = []
    for match_id in match_ids:
        anchor = html.index(f"/{match_id}\"")
        start = html.rfind('<li class="match', 0, anchor)
        end = html.index("</li>", anchor) + len("</li>")
        block = html[start:end]
        assert block.count("SportsEvent") == 1, match_id
        blocks.append(block)
    return blocks


def write_page(out: Path, blocks: list[str]) -> None:
    out.write_text('<!doctype html>\n<html><body>\n<ul class="match-list">\n' + "\n".join(blocks)
                   + "\n</ul>\n</body></html>\n", encoding="utf-8")


def main() -> None:
    blocks = blocks_for(PAGE.read_text(encoding="utf-8"), SERIE_A_IDS)
    write_page(OUT_HTML, blocks)

    two_giornate_blocks = blocks_for(PAGE1.read_text(encoding="utf-8"), TWO_GIORNATE_IDS)
    write_page(OUT_TWO_GIORNATE_HTML, two_giornate_blocks)

    pages = []
    for path, competition, season_id, ids in ((UCL, "UCL", 20, UCL_IDS), (UECL, "UECL", 21, UECL_IDS)):
        matches = {str(m["id"]): m for m in json.loads(path.read_text(encoding="utf-8"))}
        pages.append({"competition": competition, "season_id": season_id, "offset": 0,
                      "matches": [slim(matches[i]) for i in ids]})
    OUT_JSON.write_text(json.dumps(pages, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(blocks)} pills ({OUT_HTML.stat().st_size} bytes), "
          f"{len(two_giornate_blocks)} two-giornate pills ({OUT_TWO_GIORNATE_HTML.stat().st_size} bytes) and "
          f"{sum(len(p['matches']) for p in pages)} UEFA matches ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
