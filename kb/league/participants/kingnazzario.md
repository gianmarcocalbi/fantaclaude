---
updated: 2026-09-04
ttl: 90d
confidence: medium
source: "interview 2026-09-02; auction FA-rb8-460, 2026-09-03 (records/asta)"
nick: KingNazzario
team: KingKlavan FC
budget_style: steady
favourite_clubs: [Inter]
overpays: [Pc, W]
avoids: []
max_single_share: 0.3
---

# KingNazzario

Known to the room as Patri. League president and admin.

## How he bids

The most knowledgeable and the most rational manager in the league, and that
makes him the dangerous one — not because he overpays but because he does not.
An irrational rival is an opportunity; a rational one is competition. He will
identify the same undervalued players our own run identifies, and he will be
there on the lots where the model says to pay up, which is exactly where it
hurts most.

Treat a bidding war with him as evidence the player is genuinely worth it, not
as a reason to walk — but also as the case where our maximum is most likely to
be tested to the last credit.

## Last year

Not recorded. Supports Inter and Liverpool; only Inter appears in
`favourite_clubs`, because that field is joined against the listone's clubs and
a Premier League side cannot appear in a Serie A auction.

## Watch

- `max_single_share` is an estimate, not an observation — replace it the first
  time a real figure is seen.
- Whether being league president changes how he bids in A RILANCI: an admin
  running the room has less attention for the ladder than a pure bidder.

## Observed: auction 2026-09-03

Facts from the mirrored session, not from an interview: the closing state is
`records/asta/FA-rb8-460-20260903T232031Z.json` and every raise the room made is `records/asta/FA-rb8-460-20260903-bids.json`. Read them with
`fantaclaude query --sql "SELECT * FROM read_json_auto('records/asta/FA-rb8-460-20260903-bids.json')"`
or plain `jq`; nothing below restates a price that those two files do not hold.

- Team 0 (`host`) in the session, ran the room and bid a great deal: over a
  hundred lots contested, the second-highest number of raises of anyone,
  and roughly a quarter of them opened by him. He finished one player short
  of a full thirty and with a handful of credits unspent.
- Paid well over the modelled expectation for a striker (Ramos G.) and a
  winger (Goncalves P.), and at the expectation for the rest of his big
  lots (Woltemade, Bremer, Laurientè, Butez). `overpays` now carries Pc and
  W on that evidence; his largest single lot stayed under a fifth of the
  budget, comfortably inside the `max_single_share` stated above.
- Lost his contested lots mostly to Patri, Gene and CavA — the three other
  high-volume bidders — so the four of them set most of the room's prices
  between them.
