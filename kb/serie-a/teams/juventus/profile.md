---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it, tg24.sky.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Juventus
team_short: JUV
coach: Spalletti
module: 4-2-3-1
europe: none
rotation_factor: 0.85
takers:
  penalties: Kolo Muani
  corners: Conceicao
  free_kicks: Douglas Luiz
---

# Juventus — 2026-27

## Tactics

Spalletti's second season starts with a 4-2-3-1 that all three guides agree on:
a back four, a double pivot, a trequartista between two wide players, and a
single centre-forward.

The goalkeeper is the summer's clearest change — Vicario arrived and started
the opening giornata, with Di Gregorio transfer-flagged in the listone and
Perin, Grabara and Pinsoglio behind. The back four is Kalulu and Cambiaso as
full-backs and Bremer plus one of Kelly, Lucumì, Gatti or Rugani in the middle;
Bremer is the fixed point and scored on the opening day. The pivot is Locatelli
with McKennie, Thuram or Douglas Luiz beside him — four names, two slots, and
the guides do not agree on which two.

Ahead of them Yildiz and Conceicao take the flanks, Alajbegovic is the guides'
choice as trequartista, and Koopmeiners and Zhegrova are the alternatives. Kolo
Muani leads the line with David and Milik behind him. Two of the three guides
put Yildiz wide rather than central, which matters for a Mantra squad because
his listone role is a forward, not a midfielder.

```
fantaclaude query --sql "SELECT name, classic_role, mantra_roles FROM v_players_current WHERE team_name = 'Juventus' ORDER BY classic_role, name"
```

## Rotation

Our fixture list holds no European ties for Juventus, so `europe` reads `none`
— the snapshot predates the 28 August 2026 draw, which put Juventus in the
Europa League league phase.

0.85: Thursday football plus a squad that is genuinely two-deep in the pivot,
in central defence and at centre-forward, under a coach who has historically
preferred a recognisable eleven to a rotating one. The move is smaller than
Milan's or Roma's precisely because Spalletti is not a habitual rotator; it is
the calendar doing the work, not the coach.

Who shares: the second centre-back, the second pivot slot, the trequartista
(Alajbegovic and Koopmeiners), and the centre-forward. Vicario, Bremer,
Cambiaso, Locatelli and Yildiz project to play through it.

## Set pieces

Penalties are the one clear line: both squad guides name Kolo Muani first, with
Locatelli and Yildiz behind him. The season-20 workbook shows Juventus spreading
penalty duty across several takers and missing a fair share, so treat the
hierarchy as soft.

Corners and free kicks are genuinely contested between the two set-piece
sources. The dedicated set-piece guide gives free kicks to Douglas Luiz ahead of
Alajbegovic and Locatelli, and corners to Conceicao ahead of Alajbegovic,
Cambiaso and Zhegrova; the other list puts Yildiz first on both, then Locatelli
and Cambiaso. `takers` records the dedicated guide's order because it is the
more specific source, but this is the weakest set-piece attribution in the
knowledge base — read it as "Douglas Luiz, Conceicao or Yildiz".

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Juventus' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The calendar snapshot predates the European draws** (26–28 August 2026),
  but that snapshot is not what's blocking `europe`. A re-ingest has already
  come back empty: UEFA's feed carries only qualifying and play-off rounds,
  and Italy's entrants join straight into the league phase, so `europe`
  stays `none` until UEFA publishes that phase -- Juventus's Europa League --
  not merely after another re-ingest. `doctor` will flag this profile until
  it does.
- **Corners and free kicks.** Two sources, two different first names on both.
  One televised set piece settles it; until then treat these entries as low.
- **The pivot.** Four midfielders for two slots, with the guides split. This is
  where Juventus minutes will be hardest to predict.
- **Di Gregorio.** Transfer-flagged; if he stays, the goalkeeper line reopens.
