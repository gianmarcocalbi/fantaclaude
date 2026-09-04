---
updated: 2026-09-04
ttl: 90d
confidence: low
source: "interview 2026-09-02; auction FA-rb8-460, 2026-09-03 (records/asta)"
nick: radyandre
team: Bangleville-sur-Lez
budget_style: steady
favourite_clubs: []
overpays: [C, M]
avoids: []
---

# radyandre

## How he bids

Supports no big club and, in the author's words, does weird stuff. There is no
pattern to encode, and `favourite_clubs` is empty because there is genuinely no
allegiance to exploit rather than because none has been asked about.

An unpredictable rival is modelled as a neutral one. That is a real limitation
and not a description: the board will give him an average ceiling on every lot,
which will be wrong in both directions on the lots where he does something
strange. Expect him to be the source of surprises the board did not see coming.

## Last year

Not recorded.

## Watch

- Any pattern at all. One observed oddity that repeats is worth more here than
  a general impression.

## Observed: auction 2026-09-03

Facts from the mirrored session, not from an interview: the closing state is
`records/asta/FA-rb8-460-20260903T232031Z.json` and every raise the room made is `records/asta/FA-rb8-460-20260903-bids.json`. Read them with
`fantaclaude query --sql "SELECT * FROM read_json_auto('records/asta/FA-rb8-460-20260903-bids.json')"`
or plain `jq`; nothing below restates a price that those two files do not hold.

- Team 7 (`radyandre`). Selective — fewer than half the lots the busiest
  bidders contested — and midfield-heavy: McTominay, Modric (two and a
  half times the modelled expectation), Barella and Berardi took most of
  his budget. `overpays` now carries C and M.
- Four goalkeepers and only twenty-seven players at the close, with two
  credits left: he bought fewer, dearer players and a spare keeper.
- Took Falcone and Politano for six credits each — two of the auction-night
  run's tier-one players that the room, and I, let go.
- Lost his contested lots mostly to Gene, CavA and Patri.
