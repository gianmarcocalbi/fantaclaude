---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it, sport.sky.it, tg24.sky.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Milan
team_short: MIL
coach: Amorim R.
module: 3-4-2-1
europe: none
rotation_factor: 0.8
takers:
  penalties: Nkunku
  corners: Modric
  free_kicks: Modric
---

# Milan — 2026-27

## Tactics

Amorim has brought his 3-4-2-1 with him and all three guides give it: a back
three, two wing-backs who cover the whole flank, two central midfielders, two
players in the half-spaces behind a single centre-forward. It is the most
role-specific shape in the league — the two "10" slots and the two wing-back
slots are not interchangeable with anything else — which is why the squad looks
overloaded in exactly those positions.

Maignan is untouchable. The back three is Gila and Pavlovic with De Winter and
Gabbia contesting the third slot; the guides split on which, and the opening two
giornate have used both. Tomori and Diawara are behind them. The two central
midfielders are Modric and Rabiot, with Jashari, Ricci, Fofana and Loftus-Cheek
in reserve — a queue four deep for two slots.

The trequarti is the most contested group in the league: the guide-comparison
page counts nine names across four slots, spanning Pulisic, Leao, Cissè,
Chukwueze, Saelemaekers, Moreira, Loftus-Cheek, Bartesaghi and Estupinan
between the two half-spaces and the two flanks. Gonçalo Ramos is the
centre-forward, with the transfer-flagged Nkunku, Gimenez and Camarda behind
him. There is no honest way to name a settled eleven here; the guides name a
spine and then argue.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Milan' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

Our fixture list holds no European ties for Milan, so `europe` reads `none` —
the calendar snapshot predates the 28 August 2026 draw, which put Milan in the
Europa League league phase.

The factor is 0.8. Europa League Thursdays account for part of it; the rest is
that this is the squad the guides themselves single out for turnover, with one
of them naming Camarda, Chukwueze, Leao and Diawara as players who will all get
minutes and calling turnover "uno degli aspetti da monitorare con maggiore
attenzione". Amorim's shape needs specialists in each of its four attacking
slots and Milan has bought two for each, which is what a rotating side looks
like before it rotates.

Maignan, Modric and Rabiot are the closest to guaranteed. Everyone from the
third centre-back forward is sharing.

## Set pieces

Modric takes the corners and the direct free kicks — the set-piece guide puts
him first on both, with Pulisic, Jashari and Bartesaghi behind.

Penalties are contested and the entry here is a judgment. One squad guide names
Nkunku outright; the other lists Pulisic first, then Leao, then Nkunku, then
Gonçalo Ramos. The season-20 workbook is the tiebreaker in Nkunku's favour — he
took and converted more of Milan's penalties than anyone else, while Pulisic's
only involvement was a miss — so `takers.penalties` records Nkunku. Two
qualifications, both material: the listone carries him with the transfer flag,
and he has not appeared in the opening giornate. If he leaves or stays out,
Pulisic is the name to fall back on.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Milan' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The calendar snapshot predates the European draws** (26–28 August 2026),
  but that snapshot is not what's blocking `europe`. A re-ingest has already
  come back empty: UEFA's feed carries only qualifying and play-off rounds,
  and Italy's entrants join straight into the league phase, so `europe`
  stays `none` until UEFA publishes that phase -- Milan's Europa League --
  not merely after another re-ingest. `doctor` will flag this profile until
  it does.
- **Nkunku.** Transfer-flagged and unused so far, yet the penalty taker on the
  evidence. This is the single most fragile line in the profile.
- **The trequarti.** Nine names, four slots, and no guide agreement. Until
  September settles it, treat every one of those players as a rotation risk
  rather than a starter.
- **The third centre-back**, De Winter or Gabbia, still open after two rounds.
