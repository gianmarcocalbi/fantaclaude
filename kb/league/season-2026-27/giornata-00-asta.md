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

The three biggest lots were Malen, Martinez L. and Hojlund — more than half,
two fifths and a quarter of their buyers' budgets. Edo's dossier predicted the
Malen bid to the player; it is the strongest single confirmation the dossiers
got, and piantaz's Milan preference is the second. The per-rival observations
are in each dossier under "Observed: auction 2026-09-03", and all nine now
have one.

## Who was actually who

The room's team names are free text and four of them did not match the lega at
all. The morning after, every lega roster reconciled against exactly one
FantaAstaLive team, player for player and credit for credit, which identifies
each manager beyond doubt:

| room | lega team | manager |
| --- | --- | --- |
| 0 (host) | Due amici al VAR | Chuck (co-admin; ran the room) |
| 1 | KingKlavan FC | KingNazzario |
| 2 | Sanzimippi FC | Edo |
| 3 | *not on page 1 of the team list* | me |
| 4 | Fantambrosiana | Fantacristo |
| 5 | Rickymaravilla FC | CavA |
| 6 | pipponi GENErazionali | Gene |
| 7 | Bangleville-sur-Lez | radyandre |
| 8 | Fabio Borini | piantaz |
| 9 | Repubblica Democratica del Congo | Abderrazak Hamdallah |

**One of the six dossier bindings made on the night was wrong.** `--map
0=KingNazzario` bound his dossier to the team that hosted the room, which is
Chuck's; the real KingNazzario was team 1, bound to nobody. So the pressure
model spent the auction attributing one manager's habits to another and
running three teams (1, 4, 8) with no dossier at all when all three had one.
The other five bindings were right.

The lesson is that a FantaAstaLive label is not evidence of identity. Before
bidding, the mapping has to be confirmed with the admin rather than read off
the screen; afterwards, the rosters settle it for free.

Two players never crossed: Zappa was in our listone and never offered, and
Gene bought a player (id 795) our listone has never carried — in any of the
three snapshots, and the lega has since accepted him onto Gene's roster. So
the difference is not that their list is newer than ours; the league's own
player endpoint does not return every player the league will let you buy. The
mirror stores only the room's list hash, never the list.

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

## The transfer, verified

Checked on 2026-09-04, and it answers a question the spec had left open since
August: **the league API does expose rosters with their purchase costs.** Each
team object carries the player ids it bought and the price paid for each,
alongside the credits it spent. That is open question 9 resolved, and
`verify-transfer` is now buildable rather than blocked.

The transfer itself is done and it reconciles. Every one of the nine rival
teams visible in the API matches its FantaAstaLive counterpart exactly — same
players, same prices, same total — with two differences that are not errors:
two teams each gained a one-credit player after the room closed, so the lega
is one ahead of the mirror where a manager was short of thirty. Nothing the
admin typed disagrees with what the room recorded.

None of the seven players I refused ended up on any rival's roster, so the
exclusions cost nothing — including the three the room told me about
(Djimsiti leaving, Thuram K. injured, Sorensen O. gone), which remain
unverified as claims but are consistent with nobody having bought them.

Two things the check turned up that are worth keeping:

- **My own team is invisible to the team list.** The endpoint pages by ten,
  the league now registers eleven teams (one of them never played the
  auction), and mine is the one on page two: not one of my thirty players
  appears on any page-one roster. Both readers of that endpoint were fixed on
  2026-09-04 — the valuation's own fetch and the MCP tool — but the running
  MCP process still holds the old code, so confirming it live needs a
  restart.
- **The account the tooling signs in as is not my team.** `get_my_team`
  returns Sanzimippi FC, which is Edo's. League settings are league-wide so
  nothing computed here is affected, but anything that trusts "my team" from
  the API would be answering about a rival. Worth settling before Phase 3
  reads a roster.

## Open

- `verify-transfer` as a command: the comparison above was done by hand and
  belongs in the CLI, now that the API is known to carry the costs. The two
  files under `records/asta/` stay until it exists.
- **Profiles to refresh** before the notes are trusted for the season: Como
  (Kean is absent), Atalanta (Rowe), Fiorentina (Njie, the striker line),
  Roma (De Roon), Monza (Mota, Tourè I.), Sassuolo (Esposito Se.), Inter
  (Provedel), Juventus (Woltemade). The note-writing pass listed every
  unmentioned listone player of note per club.
- **Room facts not in the knowledge base**: Djimsiti leaving, Thuram K.
  injured, Sorensen O. left — reported in the room, excluded from my bidding,
  never verified.
