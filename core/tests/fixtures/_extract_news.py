"""One-shot: build the two news fixtures from the captures.

Run from the workspace root:  uv run python core/tests/fixtures/_extract_news.py

Each page is twenty club cards, `<div id="team-N" class="card team-card">`,
in listone order; the fixture keeps the document head, the first two cards
whole (Atalanta and Bologna on both captures) and the last 4000 characters
of the document -- the closing tags and scripts, which the parser ignores --
so the fixture is a real page with two clubs instead of twenty.

Observed on the captures (2026-09-05, one anonymous request each):
- a club card opens with CARD_OPEN below and carries the club's name as
  `<span class="team-name">Atalanta</span>` inside `header.team-info` --
  the listone's spelling of the club, no slug, no id;
- the injuries page lists its entries as `<ul class="unstyled"><li><strong
  class="item-name">Sulemana K.</strong><div class="item-description"><p>...
  </p></div></li>`: the name written the listone's way (surname, then the
  initial), no link, no player id anywhere on the page; forty-three entries
  over seventeen clubs, three clubs with `<div class="empty-list-message">
  Nessuno</div>` instead;
- the suspensions page has two columns per club, each opened by
  `<header><strong class="label label-danger">Squalificati</strong></header>`
  or `<strong class="label label-warn">Diffidati</strong>`, and on this
  capture EVERY column is `<div class="empty-list-message">Nessuno</div>`
  (giornata 3 in progress, no Giudice Sportivo ruling yet, nobody on four
  yellows after two rounds). The shape of a suspension entry is therefore
  INFERRED to be the injuries page's `li > strong.item-name +
  div.item-description`; Task 12 captures the page again on Tuesday 8
  September and this docstring is corrected if the ruling shows otherwise.
- the team menu above the cards repeats every club as
  `<a href="#team-N" data-team="atalanta">` with a badge, and a match
  widget elsewhere on the page uses `team-name team-link` anchors: neither
  is a card, and the parser reads `team-name` only inside a card.

Public pages, nothing to scrub.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPTURES = {"infortunati": ROOT / "captured" / "infortunati-2026-09-05.html",
            "squalificati": ROOT / "captured" / "squalificati-2026-09-05.html"}
CARD_OPEN = 'class="card team-card"'
KEEP = 2


def _card_starts(html: str) -> list[int]:
    """The index of each card's `<div`, found from its class attribute."""
    starts = []
    i = html.find(CARD_OPEN)
    while i != -1:
        starts.append(html.rfind("<div", 0, i))
        i = html.find(CARD_OPEN, i + 1)
    return starts


def main() -> None:
    for page, capture in CAPTURES.items():
        html = capture.read_text(encoding="utf-8")
        starts = _card_starts(html)
        assert len(starts) == 20, f"{page}: expected twenty club cards, found {len(starts)} for {CARD_OPEN!r}"
        out = Path(__file__).with_name(f"news_{page}_sample.html")
        out.write_text(html[:starts[0]] + html[starts[0]:starts[KEEP]] + html[-4000:], encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size} bytes, {KEEP} clubs)")


if __name__ == "__main__":
    main()
