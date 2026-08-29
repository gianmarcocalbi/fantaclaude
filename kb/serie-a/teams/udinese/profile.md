---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Udinese
team_short: UDI
coach: Runjaic
module: 3-5-2
europe: none
rotation_factor: 1.0
takers:
  penalties: Davis K.
  corners: Zaniolo
  free_kicks: Zaniolo
---

# Udinese — 2026-27

## Tactics

Runjaic is confirmed and two of the three guides keep the 3-5-2 he has coached
here throughout; the third reads the same squad as a 3-4-2-1, which is the same
back three and wing-backs with Zaniolo pushed behind a lone striker instead of
alongside him.

Okoye is first choice with Padelli, Mrozek and Piana behind. The back three is
Solet — the one name every guide starts — with two of Kabasele, Ebosse,
Bertola, Palma and Abankwah beside him; the opening round used Ebosse, Palma
and Abankwah, so the trio is not settled. The wing-backs are Vojvoda on the
right and Kamara on the left, with Zanoli the alternative; Kamara scored on the
opening day. The midfield three is Karlstrom as the anchor with Ekkelenkamp
and one of Piotrowski, Miller or Zarraga.

Up front, Zaniolo is the constant and Davis the centre-forward the guides pair
him with — but Davis did not play the opening round, where Bayo and Gueye did.
Treat the strike pairing as open rather than as the settled thing the guides
describe.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Udinese' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

`rotation_factor` stays at 1.0. Udinese is not among the seven Italian clubs
the 26–28 August 2026 draws put into Europe; Runjaic runs an established system
that the guides describe as maintained rather than rebuilt; and the squad,
though wide in defence, has no obvious rotation logic outside it. Leaving the
number at its starting point with a reason is better than a move this profile
cannot defend.

The one department that genuinely shares minutes is the back three, where five
names compete for two slots beside Solet.

## Set pieces

Davis is the penalty taker in both squad guides, and the season-20 workbook
supports it — he took Udinese's penalties last season and converted them.
Zaniolo and Solet are named behind him.

Zaniolo is first on corners and on direct free kicks in the set-piece guide,
with Vojvoda, Ekkelenkamp and Miller behind him on both. The second set-piece
source names the same group.

The tension to be aware of: the penalty taker did not play the opening round
and the corner taker did. If Davis loses the shirt, no source says who takes
penalties instead.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Udinese' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **Davis.** Named as the starting centre-forward and the penalty taker by
  every guide, and absent from the opening round. The most consequential open
  question here.
- **The back three**, where the opening lineup matched no guide.
- **The module.** 3-5-2 or 3-4-2-1 changes whether Zaniolo is a second striker
  or a trequartista, and with it his Mantra slot.
