---
updated: 2026-09-04
ttl: 90d
confidence: medium
source: "interview 2026-09-02; auction FA-rb8-460, 2026-09-03 (records/asta)"
nick: Edo
team: Sanzimippi FC
budget_style: early
favourite_clubs: [Roma]
overpays: [E, M, C, W, T, A, Pc]
avoids: [Por, Dd, Ds, Dc]
max_single_share: 0.55
---

# Edo

## How he bids

Commits early and heavily: most of the budget is gone before the room has
settled, which leaves him thin for the closing lots. He pays up in midfield and
attack and treats goalkeeper and defence as filler, taking whatever is left
late and cheap. He will let a single name take more than a third of everything,
so one early lot he badly wants can effectively end the auction for him as a
bidder — and end his pressure on every lot after it.

That last point is the one to exploit. An early-spender who has just paid a
third of his budget is no longer a rival for the rest of the night, so the
lots immediately after a big Edo purchase are cheaper than they look.

## Last year

Co-managed Sanzimippi FC with the author until this season; the split is why he
is a rival rather than a team-mate, and why this dossier is first-hand rather
than observed. His own summary of last season is that the attack was the
weakness — which is consistent with the way he now overpays for it. A manager
correcting last year's mistake tends to overcorrect.

## Watch

- **Roma supporter, and expected to go all in on Malen (Roma, Pc) this year.**
  That is a stated intention rather than an observed habit, so treat it as the
  strongest single prediction in this dossier and the first thing to re-check
  in the room. It collides directly with the Pc class — though the pinned
  run's own read of Malen is not flattering, and is worth re-checking
  against whatever run is pinned on the night:
  `fantaclaude asta explain "Malen"`.
- Whether the early-spending habit survives **A RILANCI**. Open outcry has no
  turn order to protect a plan, and an early spender in a rilanci auction is
  more exposed than in a draft.
- Whether losing a co-manager changes him. Two people talk each other out of
  bad bids; one person does not.

## Observed: auction 2026-09-03

Facts from the mirrored session, not from an interview: the closing state is
`records/asta/FA-rb8-460-20260903T232031Z.json` and every raise the room made is `records/asta/FA-rb8-460-20260903-bids.json`. Read them with
`fantaclaude query --sql "SELECT * FROM read_json_auto('records/asta/FA-rb8-460-20260903-bids.json')"`
or plain `jq`; nothing below restates a price that those two files do not hold.

- **The prediction held exactly.** He went all in on Malen and paid more
  than half of his budget for him — beyond the two-fifths this dossier
  allowed, so `max_single_share` is raised to what he actually did. The
  room let him: the ladder shows CavA and Pier pushing him most of the way.
- After Malen he bought a first-choice goalkeeper and two centre-backs at
  about the expectation and filled eleven places at one credit; he finished
  with twenty-eight players and two credits. His classic split is
  attack-heavy (seven forwards, seven midfielders).
- Spent about a quarter of his budget in the first third of the auction,
  the same share as everyone else, so "early" was not visible as a pace —
  the early commitment was the one lot, which is what the dossier meant.
- Under the auction-night run his roster valued lowest in the room; under
  run `20260903T233449Z-7694bd6a` it is mid-table, because that run makes
  Malen the single most valuable player in the league. Whether he overpaid
  is now a question about Malen, not about Edo.
