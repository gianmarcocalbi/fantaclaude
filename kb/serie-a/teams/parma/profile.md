---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Parma
team_short: PAR
coach: Cuesta
module: 4-3-3
europe: none
rotation_factor: 0.95
takers:
  penalties: Bernabè
  corners: Bernabè
  free_kicks: Bernabè
---

# Parma — 2026-27

## Tactics

Cuesta is confirmed and two of the three guides give a 4-3-3; the third reads
the same side as a 4-3-2-1, a shape this league's module list does not contain,
so for lineup purposes the 4-3-3 is the reading to work from.

The goalkeeper is the most balanced contest in the league by the
guide-comparison page's own measure — Daffara and Corvi are separated by
essentially nothing, with the transfer-flagged Suzuki a third name in one guide
— and Corvi played the opening round. The back four is Delprato and Britschgi
contesting the right, Valeri on the left, and two of Troilo, Valenti, Ndiaye and
the transfer-flagged Circati in the middle; the opening round used Ndiaye,
whom no guide started.

Bernabè is the creative midfielder the side runs through, with Keita and
Nicolussi Caviglia or Ordonez beside him and Fabbian and Sorensen in reserve.
The front three is the loosest part: Romero, Tourè, Frigan, Almqvist,
Diallo, Lontani and Elphege all appear in one guide or another, and the opening
round fielded a combination none of them predicted.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Parma' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

No European football — Parma is not among the seven Italian clubs drawn on
26–28 August 2026 — so the factor starts at 1.0 and moves to 0.95 only for the
unsettledness the guides themselves document: a goalkeeper contest that is
effectively a coin toss, a centre-back pairing the opening round contradicted,
and a front three with seven candidates. Bernabè, Valeri, Delprato and Troilo
are the four who project to play regardless.

## Set pieces

Bernabè is first on all three — penalties, corners and direct free kicks — in
both set-piece sources, with Valeri second on all of them and Tourè
named on free kicks. This is one of the cleaner set-piece attributions in the
knowledge base, because the two sources agree on both the name and the order.

The season-20 workbook does not corroborate it: Parma's penalties then went to
players who have since left, which is a caution about the taker rather than
about Bernabè's set-piece role.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Parma' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The goalkeeper.** Daffara against Corvi, with Suzuki transfer-flagged.
  Genuinely undecided, and a goalkeeper is an all-or-nothing buy.
- **The front three.** Seven names, three slots, and no guide agreement.
- **Circati and Suzuki**, both transfer-flagged in the listone; either could
  leave before the window shuts.
