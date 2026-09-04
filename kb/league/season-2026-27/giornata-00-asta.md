---
updated: 2026-09-04
ttl: never
confidence: high
source: "records/asta/FA-rb8-460-20260903T232031Z.json; records/asta/FA-rb8-460-20260903-bids.json; runs 20260902T213819Z-8210bd6a, 20260903T233432Z-8210bd6a, 20260903T233449Z-7694bd6a"
---

# Giornata 0 — the auction, 3 September 2026

Session `FA-rb8-460`, A RILANCI, ten teams, 500 credits each, roster 25–30
with 2–4 goalkeepers. It opened just before 20:00 and the last lot closed a
little after 01:20; the room recorded 289 sales. The closing state is
`records/asta/FA-rb8-460-20260903T232031Z.json` and every raise anyone made
is `records/asta/FA-rb8-460-20260903-bids.json`. The board was priced against
run `20260902T213819Z-8210bd6a` (model 1, no player notes); the two runs made
the morning after are the measurement of what was wrong with it.

```
fantaclaude query --sql "SELECT * FROM read_json_auto('records/asta/FA-rb8-460-20260903T232031Z.json')"
fantaclaude query --sql "SELECT run_id, model_hash, inputs_hash FROM v_valuation_runs ORDER BY created_at"
```

## What I bought, and how

Thirty players for 480 credits, twenty left over: three goalkeepers, eleven
defenders, thirteen midfielders, three forwards by the classic split. I bid on
49 lots and won 30 — the fewest raises of anyone in the room; the busiest
rivals contested well over a hundred lots each.

Where I followed the board it was right: Vasquez, Mancini, Karlstrom,
Frendrup, Matic, Keita M., Pierotti, Gallo, Vlasic, Thorstvedt and Da Cunha
were all tier one or two on the night and came at or under their max, several
for a single credit. Where I overrode it, I overrode it the same way the whole
room did — towards the attack. Douvikas and Kean were bought well above a max
the board had at zero; I chased McTominay, Pulisic, Yildiz, De Ketelaere and
Soulè far past their max and lost every one of them, so no damage was done,
but the direction is worth remembering. And I let two of the board's tier-one
goalkeepers go for a fraction of their max — Falcone to radyandre, Maignan to
Patri — after bidding once or not at all.

Under the corrected run (`20260903T233449Z-7694bd6a`) Douvikas is a starter
worth every credit and Kean is the weakest buy on the roster: the Como profile
never mentions Kean at all, which is a knowledge-base gap, not a model verdict.

## What the room did

The realised price level was well under the model's: paid over quotazione
came out around 1.74 against a modelled inflation of 2.15, because the room
bought more quotazione than the credible pool held. But the average hides the
shape. By class, paid over the model's expected price ran from about 1.25 for
Pc down to about 0.63 for Dc, E and W, with C near parity and A, M, Por around
0.75–0.8. The room pays a premium for strikers and for midfield names and lets
defenders go at two thirds of expectation. A next-year expected-price model
needs a class multiplier, which is the `market_prices` calibration table the
spec leaves to Phase 3 — and now has data for.

The three biggest lots were Malen (Edo, more than half his budget), Martinez
L. (Pier) and Hojlund (gio). Edo's dossier predicted the Malen bid to the
player; it is the strongest single confirmation the dossiers got. The
per-rival observations are in each dossier under "Observed: auction
2026-09-03"; three teams (Patri, Pier, gio) have no dossier because no nick in
`league.yml` binds them.

Two players never crossed: Zappa was in our listone and never offered, and
Gene bought a player (id 795) our listone has never carried. The room's list
is not our listone, and the mirror stores only its hash.

## What was wrong with the model, and what fixed it

Five two-appearance players (Franjic, Cissè A., Ramos G., Correia T., Adams
A.) topped the auction-night board with zero-width bands, because the
appearance rate was a raw quotient and its variance had no sample-size term.
Their phantom bargains also zeroed the Pc band for every real striker — the
completion preferred the cheap "certain" men — which is why Douvikas and Kean
read as max 0. The night was handled with five `value` adjustments.

Two runs the morning after measure the fix in two steps:

- `20260903T233432Z-8210bd6a` — the 271 player depth notes written from the
  club profiles, under the old model. The notes alone remove all five from
  the top tier and move every roster's valuation by hundreds of points;
  Montipò, Milinkovic-Savic V., Ellertsson, Konè I., Krstovic and Adams C.
  drop to cover, Malen, Martinez L., Douvikas and Stankovic F. rise to
  starters.
- `20260903T233449Z-7694bd6a` — the same notes under model 2, where the rate
  shrinks toward the role's rate with `prior_presenze` and the band carries
  the estimation variance. On top of the notes this mainly lowers the
  long-history certainties (Falcone, Politano, Hojlund) and lifts a player
  with one appearance in a season (Beto) off zero.

Under the auction-night run my roster valued first in the room by a wide
margin; under model 2 it is first by a hair over CavA, with Pier third. The
margin was an artefact of the defect. The five value adjustments in
`data/adjustments.yml` now double-count against any board priced on a run
with notes and must be dropped before the board is used again.

```
fantaclaude query --sql "SELECT name, role_class, round(value_p50) AS v, tier FROM read_parquet('records/valuations/20260903T233449Z-7694bd6a.parquet') ORDER BY value_p50 DESC LIMIT 30"
```

## What the tooling got wrong on the night

The session's `roles` pairs are ranges, not `[classic, mantra]` — the room
finished with two, three and four keepers on rosters of twenty-seven to
thirty — so the mirror read a full roster as still owing a player. Multi-role
players sat pinned to a full class at band 0 while another of their roles was
still wanted; the board had no idea which block the room was calling; and a
class with an open slot but no pinned player vanished from the tier board.
All four are fixed as of 2026-09-04 (`fantaclaude asta board` now prints
`room:`, `block:` and `re-pinned:` lines). A RILANCI does publish the live
bid — `currentBid {playerId, teamId, value, timestamp}` — which is how the
ladder above exists; the board still does not read it live.

## Open

- **Transfer verification** (spec, open question 9): the admin transfers the
  results into the lega after the auction. Until the league API is shown to
  expose rosters, the two files under `records/asta/` are the only record of
  what the room paid, and nothing deletes `data/asta-state.json`.
- **Profiles to refresh** before the notes are trusted for the season: Como
  (Kean is absent), Atalanta (Rowe), Fiorentina (Njie, the striker line),
  Roma (De Roon), Monza (Mota, Tourè I.), Sassuolo (Esposito Se.), Inter
  (Provedel), Juventus (Woltemade). The note-writing pass listed every
  unmentioned listone player of note per club.
- **Room facts not in the knowledge base**: Djimsiti leaving, Thuram K.
  injured, Sorensen O. left — reported in the room, excluded from my bidding,
  never verified.
