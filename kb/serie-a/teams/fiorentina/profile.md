---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Fiorentina
team_short: FIO
coach: Grosso
module: 4-3-2-1
europe: none
rotation_factor: 0.95
takers:
  penalties: Gudmundsson A.
  corners: Gudmundsson A.
  free_kicks: Gudmundsson A.
---

# Fiorentina — 2026-27

## Tactics

Grosso has taken over and two of the three guides read his side as a 4-3-2-1 —
a back four, three in midfield, two behind a single centre-forward — while the
third reads the same players as a 4-3-3. As with Cagliari, note that 4-3-2-1 is
not among the modules this league permits; the nearest permitted shapes are
4-3-1-2 and 4-2-3-1, and one guide's 4-3-3 is permitted as it stands.

De Gea is first choice with Christensen and Lezzerini behind. The defence is the
department the guide-comparison page calls the most rebuilt squad in the
league: Dragusin is the one name every guide starts, with Pongracic, Ranieri,
Valdepenas and Viery contesting beside him, Jimenez on one flank and Dodò and
Joao Mario contesting the other. Midfield is Fagioli and Mandragora competing
for the deep role with Ndour, Oulai, Brescianini and Atta around them.
Mastantuono is the summer's marquee arrival and plays behind the striker, and
Kean leads the line with Pellegrino as the alternative.

The opening giornata was poor across the board, which tells you the shape is not
yet working; it does not tell you which eleven Grosso believes in.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Fiorentina' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

No European football — the 26–28 August 2026 draws put seven Italian clubs into
Europe and Fiorentina is not among them — so the factor starts at 1.0 and comes
down only to 0.95. The move is not for a rotating coach; it is for a squad that
was rebuilt so heavily that the guides count eight players competing for four
slots across defence and midfield. That is churn rather than turnover, but for
a projection the effect is the same: individual minutes are less predictable
than at a settled club.

De Gea, Dragusin, Mastantuono and Kean are the four who should play whatever
happens.

## Set pieces

Gudmundsson is first on all three — penalties, corners and direct free kicks —
in both set-piece sources, and the season-20 workbook shows him converting his
penalties without a miss, which is the strongest corroboration available for
any Fiorentina taker. Mastantuono, Mandragora and Fagioli are the alternative
deliverers, and Kean and Mandragora are named behind Gudmundsson on penalties.

The caveat is large and belongs here rather than in a footnote: Gudmundsson did
not appear in the opening giornata. Everything in this section assumes he plays.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Fiorentina' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **Gudmundsson's availability.** He is the entire set-piece department on
  paper and did not play the first round. If he is out, penalties most likely
  go to Kean and free kicks to Mandragora — but no source says so, so that is
  an inference, not a fact.
- **The rebuilt defence.** Five names for two central slots, two for the right
  flank; the guides do not converge.
- **Grosso's module.** Two guides say 4-3-2-1, one says 4-3-3, and neither is
  what the league's module list calls a shape until he settles it.
