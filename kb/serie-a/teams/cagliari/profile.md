---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Cagliari
team_short: CAG
coach: Pisacane
module: 4-3-2-1
europe: none
rotation_factor: 1.0
takers:
  penalties: Mina
  corners: Winks
  free_kicks: Maldini
---

# Cagliari — 2026-27

## Tactics

Pisacane is confirmed and plays a 4-3-2-1 — a back four, a three-man midfield,
two trequartisti behind a single centre-forward. Note for lineup purposes that
this shape is **not** among the modules our league permits; the nearest
permitted ones are 4-3-1-2 and 4-2-3-1, and the choice between them changes
which listone roles are fieldable:

```
fantaclaude query --sql "SELECT modules FROM v_league_settings_current"
```

One guide adds that Pisacane alternates the 4-3-2-1 with a 3-5-2, which would
make the wing-backs (E) worth considerably more than a back four does.

This is, by the guide-comparison page, the most settled side in the league: no
contested slot passes its threshold and every one of the eleven is above
roughly four fifths agreement. Caprile is first choice in goal. The back four is
Zappa or Zè Pedro right, Obert left, and Mina with Rodriguez in the middle.
Winks is the deep midfielder with Adopo and Romano beside him and Deiola as the
alternative. Fazzini and Maldini play behind the striker, with Felici and Fadera
competing, and the centre-forward is contested between Kevin Carlos, Mendy,
Borrelli and Esposito.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Cagliari' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

`rotation_factor` stays at 1.0 and the reason is worth stating plainly rather
than moving the number for the sake of it: Cagliari plays no European football
— the 26–28 August 2026 draws put seven Italian clubs into Europe and this is
not one — the guides agree on the eleven more than for any other club, and the
squad is not deep enough to rotate even if the coach wanted to. One competition,
one settled eleven, no reason to discount minutes.

The one genuinely shared slot is the centre-forward, where four names compete
and none has separated.

## Set pieces

Both squad guides name Mina as the penalty taker — a centre-back on penalties,
which is unusual enough to be worth a second look before pricing it. Borrelli
and Fazzini are named behind him.

Corners go to Winks first, with Fazzini and Obert behind; free kicks to Maldini
first, with Winks and Fazzini behind. The two set-piece sources name the same
three men and order them differently, so read corners and free kicks as shared
between Winks, Maldini and Fazzini.

The season-20 workbook offers almost no corroboration here — Cagliari's
penalties last season went to players who are no longer the first choice:

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Cagliari' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **Mina on penalties.** Named by both guides, but he did not play the opening
  giornata and a centre-back penalty taker is the kind of claim that quietly
  stops being true. Watch an actual penalty.
- **The centre-forward.** Four names, no separation.
- **Whether the 3-5-2 appears.** If Pisacane alternates as one guide suggests,
  Obert and Zappa become wing-backs and their Mantra value changes.
