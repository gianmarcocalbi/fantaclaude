---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Lecce
team_short: LEC
coach: Di Francesco
module: 4-2-3-1
europe: none
rotation_factor: 1.0
takers:
  penalties: Stulic
  corners: Gallo
  free_kicks: Pierotti
---

# Lecce — 2026-27

## Tactics

Di Francesco is confirmed and the guides describe continuity: two of three give
a 4-2-3-1 — a double pivot, three behind a striker — and the third reads the
same eleven as a 4-3-3.

Falcone is first choice with Bleve, Penev, Fruchtl and Samooja behind, none of
them a real threat to him. The back four is Veiga on the right, Gallo on the
left, and Gaspar with Tiago Gabriel in the middle; Siebert, Jean and Ndaba are
the cover, and the opening round used Ndaba and Siebert, so the pairing is less
fixed than the guides suggest. The pivot is Coulibaly with Ilic, the summer
signing, beside him — though Ilic did not play the opening round, where Gorter
and Ngom did, and Gorter scored. Maleh, Kaba, Fofana and Gandelman are the rest
of a large midfield.

Ahead of them Pierotti is the constant, with N'Dri, Berisha, Laerke and Fatah
competing for the other two attacking slots, and the centre-forward is
contested between Stulic and Geubbels; both played on the opening day.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Lecce' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

`rotation_factor` stays at 1.0. Lecce plays no European football — not among
the seven Italian clubs drawn on 26–28 August 2026 — and Di Francesco is
described by the guides as the most tactically consistent coach in this part of
the table. A club fighting relegation with one competition does not rotate; it
picks its best eleven and repeats it.

The genuinely shared slots are the centre-forward and the two wide attacking
positions, where five names compete.

## Set pieces

Stulic is the penalty taker in both squad guides, with Berisha named behind
him; the season-20 workbook shows Stulic taking and scoring, which is thin but
consistent corroboration.

Corners go to Gallo first, with Pierotti and Berisha behind; free kicks to
Pierotti first, with Berisha and Gallo behind. The second set-piece source
names the same three men — Pierotti, Berisha, Gandelman — with a different
third, so the pair Pierotti/Gallo is safe and the ordering is not.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Lecce' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **Stulic or Geubbels.** Both started the season on the pitch; the penalty
  entry above assumes Stulic keeps the shirt.
- **Ilic.** Signed to hold the midfield and absent from the opening round.
- **The module.** Two guides say 4-2-3-1, one says 4-3-3; both are permitted
  here, and the difference is one attacking slot.
