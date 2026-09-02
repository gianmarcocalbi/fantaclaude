---
updated: 2026-09-02
ttl: 90d
confidence: medium
source: "interview 2026-09-02"
nick: CavA
team: Rickymaravilla FC
budget_style: hoarder
favourite_clubs: []
overpays: []
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
