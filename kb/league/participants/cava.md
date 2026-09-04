---
updated: 2026-09-04
ttl: 90d
confidence: medium
source: "interview 2026-09-02; auction FA-rb8-460, 2026-09-03 (records/asta)"
nick: CavA
team: Rickymaravilla FC
budget_style: hoarder
favourite_clubs: []
overpays: [A, E]
avoids: []
---

# CavA

## How he bids

A hoarder, and the clearest case of one in the league: he does not pay up, and
he reliably finishes the auction with credits still in hand. Money left over at
the final lot is money that was never used to buy anything, so he is a weak
rival on any single contested lot — but a dangerous one late, when everyone
else is spent and he can take good players uncontested at the minimum.

The lots to fear from him are the last ones, not the first.

## Last year

Supports Juventus but, notably, **often does not buy Juventus players**. This
is why `favourite_clubs` is deliberately **empty** rather than listing
Juventus. The pressure model treats a lot's club appearing in `favourite_clubs`
as evidence the rival is keen and raises his ceiling accordingly
(`asta/pressure.py`); for CavA that would be backwards, and would make the
board expect competition on Juventus lots that history says will not come.
The allegiance is recorded here in prose, where it informs a human and does not
mislead the model.

## Watch

- `max_single_share` is deliberately absent: "doesn't pay a lot" is qualitative
  and no real figure has been observed. Fill it the first time one is, rather
  than guessing — an invented cap changes every ceiling he is given.
- Whether the Juventus aversion holds. It is the kind of habit that reverses
  without warning, and if it does, this dossier is actively harmful.

## Observed: auction 2026-09-03

Facts from the mirrored session, not from an interview: the closing state is
`records/asta/FA-rb8-460-20260903T232031Z.json` and every raise the room made is `records/asta/FA-rb8-460-20260903-bids.json`. Read them with
`fantaclaude query --sql "SELECT * FROM read_json_auto('records/asta/FA-rb8-460-20260903-bids.json')"`
or plain `jq`; nothing below restates a price that those two files do not hold.

- Team 5 (`CavA Goat`). Spent the least of anyone in the first third of the
  auction, then all five hundred credits by the end, on twenty-nine
  players — the hoarder's pace, but not a hoarder's finish.
- His two big lots went far past the modelled expectation: Paz N. (nearly
  twice it) and Dimarco. `overpays` now carries A and E. Davis K. and
  Carnesecchi were paid a little over expectation, Yildiz and McKennie
  under it.
- Took Adams A. for one credit — a player the auction-night run had in its
  top tier — so he also picks up what the room overlooks.
- Under both post-auction runs his roster values second in the room, a
  few points behind mine; under the auction-night run it was second by a
  wide margin. The most complete rival roster of the night.
- Lost his contested lots mostly to KingNazzario, Pier and Patri.
