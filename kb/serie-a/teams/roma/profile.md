---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it, tg24.sky.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Roma
team_short: ROM
coach: Gasperini
module: 3-4-2-1
europe: none
rotation_factor: 0.8
takers:
  penalties: Malen
  corners: Dybala
  free_kicks: Dybala
---

# Roma — 2026-27

## Tactics

Gasperini is confirmed for a second season and the shape is the one he has
coached for a decade: a back three, two wing-backs who are the entire width,
two central midfielders, two trequartisti and a centre-forward. Three guides
agree on the module and on nine of the eleven, which makes Roma the most
legible side in the league this year — the comparison page that scores guide
agreement puts Roma at the top of it, with only the third centre-back genuinely
in doubt.

Svilar is untouchable. Mancini and N'Dicka are two thirds of the defence and
Hermoso and Koulierakis contest the last slot, roughly two to one in Hermoso's
favour across the guides. The wing-backs are Wesley and Molina, with Rensch and
Angelino — the latter transfer-flagged in the listone — as cover. Konè and
Cristante are the midfield pair and Pisilli and El Aynaoui the alternatives.
The two behind the striker are Dybala and one of Soulè, Mora or Castro, and
Malen is the centre-forward: the opening giornata was emphatically his and
Dybala's, which is the clearest single piece of evidence in this profile.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Roma' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

Our fixture list holds no European ties for Roma, so `europe` is `none` — the
calendar snapshot predates the 26–27 August 2026 Champions League draw, which
the reporting says Roma is in. The factor is 0.8, the lowest in this knowledge
base, and it is a coach judgment rather than a fixture one: Gasperini's whole
career is heavy, deliberate rotation, and a Champions League league phase gives
him eight extra fixtures to spread across a squad he has just been given depth
in. This is the club where "he started last week" predicts least.

The players it costs: the third centre-back, both wing-backs (four names for
two slots), the second trequartista, and the centre-forward, where Castro and
Vaz exist precisely so Malen does not play ninety minutes twice a week. Svilar,
Mancini, N'Dicka and Konè are the ones who play through it.

Because the number is low, it deserves the strongest caveat in this file: 0.8
is an estimate of a habit, not a measurement. Two giornate cannot confirm it.
Re-derive it from minutes once there are enough of them.

## Set pieces

Malen takes the penalties — both squad guides name him first and the season-20
workbook has him taking and mostly scoring them — with Dybala second. Dybala
takes the direct free kicks and the corners, first choice on both in the
set-piece guides, with Mora, Soulè, Wesley and Molina behind him. The one
sensible reading is that Dybala is the dead-ball specialist and Malen the
penalty specialist, and that when Dybala is off the pitch the free kicks go to
Mora or Soulè rather than to Malen.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Roma' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The calendar snapshot predates the European draws** (26–28 August 2026).
  Re-ingest the calendar; `europe` should become `UCL` and the rotation
  reasoning above stops being an inference.
- **Dybala's availability.** Everything in "Set pieces" assumes he is on the
  pitch, and his recent seasons say that is not a safe assumption.
- **The rotation factor itself.** 0.8 is the boldest number here. If Gasperini
  fields a settled eleven through September, raise it.
