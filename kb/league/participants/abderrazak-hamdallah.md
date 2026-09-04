---
updated: 2026-09-04
ttl: 90d
confidence: medium
source: "interview 2026-09-02; auction FA-rb8-460, 2026-09-03 (records/asta)"
nick: Abderrazak Hamdallah
team: Repubblica Democratica del Congo
budget_style: steady
favourite_clubs: []
overpays: [M, Pc]
avoids: []
---

# Abderrazak Hamdallah

New to the league this season. The nick is a footballer's name used as a
handle, not the manager's own.

## How he bids

Plays fairly randomly, and nothing further is known. As with radyandre, a
random bidder is encoded as a neutral one, which means the board will hand him
an average ceiling on every lot and be wrong whenever he does something
arbitrary.

Two of nine opponents are modelled as neutral-because-unknown rather than
neutral-because-measured. That is worth holding in mind when the board's
pressure estimate looks confident.

## Last year

New to this league; nothing to record.

## Watch

- Everything. This is the thinnest dossier of the nine.
- Whether he is Pier or Gabriele — the mapping from the two new handles to the
  two new managers is unconfirmed.

## Observed: auction 2026-09-03

Facts from the mirrored session, not from an interview: the closing state is
`records/asta/FA-rb8-460-20260903T232031Z.json` and every raise the room made is `records/asta/FA-rb8-460-20260903-bids.json`. Read them with
`fantaclaude query --sql "SELECT * FROM read_json_auto('records/asta/FA-rb8-460-20260903-bids.json')"`
or plain `jq`; nothing below restates a price that those two files do not hold.

- Team 9 (`Congo`). The only manager to finish with credits unspent — fifty
  of them — on a full thirty players, fourteen of them defenders and four
  goalkeepers: the most defensive classic split in the room.
- His money went to midfielders: Calhanoglu well over the modelled
  expectation, Konè M. at more than twice it, plus Pinamonti at nearly
  twice. `overpays` now carries M and Pc. Kalulu, Ekkelenkamp, Taylor K.
  and Simeone went at or under expectation.
- Opened the fewest lots of anyone and contested a moderate number; lost
  them mostly to Gene, CavA and me.
