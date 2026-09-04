"""One-shot: build probabili_sample.html from the capture.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_probabili.py

Keeps the document up to the first match card, the first two match cards
whole (four clubs, both lists each, their `Ultimo aggiornamento`), and the
document tail after the last card, so the fixture is a real page with two
matches instead of ten. Captured 2026-09-04 (Friday of giornata 3, every
match compiled); the "not yet compiled" case is produced in the tests by
rewriting this sample, until an early-week capture replaces it.

Observed on the capture (Task 1, Step 2):
- aria-valuenow sits on: a child -- the `div.progress-bar` inside the
  player-item's `div.progress`, not the `li.player-item` itself. (A separate
  pitch-diagram widget earlier in each match card uses `li.player` with a
  `data-formation` on its enclosing `ul.team-lineup`; that is not this list.)
- one match card opens with: MATCH_OPEN below -- `<li class="match
  match-item  "` (two spaces before the closing quote, more attributes
  follow before `>`) -- occurs exactly ten times, once per giornata-3 match.
- Ultimo aggiornamento comes: AFTER the lists -- both `ul.player-list
  starters` and `ul.player-list reserves` for both clubs are emitted, then
  one `div.label label-dark last-update` holding "Ultimo aggiornamento
  <span class="date">dd/mm/yyyy - HH:MM</span>" for the whole match.
- the bench list is marked by: `<ul class="player-list reserves">` (the
  starters list is `<ul class="player-list starters">`; both are siblings
  under the same club's `div.card team-card`).
- the page names its giornata as: "3&#xB0; giornata" (a degree sign, not an
  ordinal "a"/"ª") -- but only inside a per-match `<meta itemprop="name"
  content="Serie A 2026-27 - 3&#xB0; giornata - <home>-<away>">` (schema.org
  SportsEvent microdata), not as plain visible text anywhere else on the
  page or in <title>.

Public page, nothing to scrub.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "captured" / "probabili-2026-27-giornata-3.html"
OUT = Path(__file__).with_name("probabili_sample.html")

MATCH_OPEN = '<li class="match match-item  "'
KEEP = 2


def main() -> None:
    html = PAGE.read_text(encoding="utf-8")
    starts = []
    i = html.find(MATCH_OPEN)
    while i != -1:
        starts.append(i)
        i = html.find(MATCH_OPEN, i + 1)
    assert len(starts) == 10, f"expected ten match cards, found {len(starts)} for {MATCH_OPEN!r}"
    head = html[:starts[0]]
    kept = html[starts[0]:starts[KEEP]]
    # everything after the last card: find where the last card's siblings end is
    # not knowable without a DOM, so keep the last 4000 characters of the
    # document -- the closing tags and scripts -- which the parser ignores.
    tail = html[-4000:]
    OUT.write_text(head + kept + tail, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {KEEP} matches)")


if __name__ == "__main__":
    main()
