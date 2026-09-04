---
updated: 2026-09-04
ttl: 90d
confidence: medium
source: "interview 2026-09-02; auction FA-rb8-460, 2026-09-03 (records/asta)"
nick: Gene
team: pipponi GENErazionali
budget_style: steady
favourite_clubs: [Inter]
overpays: [A, W]
avoids: []
---

# Gene

## How he bids

Irrational — emphatically so, in the author's words. An Inter supporter whose
allegiance drives his bidding more than value does. No `max_single_share` is
recorded, and that is the right representation: a cap would tell the board he
restrains himself on one player, and nothing suggests he does.

He is the reason the Inter names matter. Of the Inter players in the listone
the pinned run wants exactly one, and Gene is likely to contest it while also
bidding up the many it does not want. The second half of that is a gift —
every credit he spends on an Inter player the model prices at zero is a credit
he cannot spend against us elsewhere.

## Last year

Not recorded.

## Watch

- `budget_style` is `steady` because it is **unknown**, not because he is
  measured. `steady` is the neutral value — `early` and `hoarder` both move his
  ceiling — so it is the honest placeholder until his timing is observed.
- Which Inter players specifically. `fantaclaude asta explain` on the Inter
  names on the night will say which are traps and which are the one to fight for.

## Observed: auction 2026-09-03

Facts from the mirrored session, not from an interview: the closing state is
`records/asta/FA-rb8-460-20260903T232031Z.json` and every raise the room made is `records/asta/FA-rb8-460-20260903-bids.json`. Read them with
`fantaclaude query --sql "SELECT * FROM read_json_auto('records/asta/FA-rb8-460-20260903-bids.json')"`
or plain `jq`; nothing below restates a price that those two files do not hold.

- Team 6 (`Gene`): the most active bidder in the room by a distance — the
  most lots contested and the most raises of anyone — yet he opened fewer
  lots than most. He bids on other people's lots rather than calling his
  own: a sniper's pattern, and the pressure model should read him as keen
  on almost everything at the second tier.
- Paid more than twice the modelled expectation for Dybala and nearly
  twice for De Bruyne: he pays for the name. `overpays` now carries A and
  W. Scamacca, Krstovic, Ederson, Chalobah and Meret went at or a little
  over expectation.
- Bought one player our listone never carried (id 795, three credits):
  the room's list is not ours, see the journal.
- Finished with a full thirty and four credits; lost his contested lots
  mostly to gio, Congo and KingNazzario.
