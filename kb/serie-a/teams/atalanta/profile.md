---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it, sport.sky.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Atalanta
team_short: ATA
coach: Sarri
module: 4-3-3
europe: UECL
rotation_factor: 0.9
takers:
  penalties: Scamacca
  corners: Samardzic
  free_kicks: De Ketelaere
---

# Atalanta — 2026-27

## Tactics

The Gasperini era is over and Sarri has replaced its man-marking three with his
own 4-3-3: a back four, a single pivot flanked by two mezzali, and a front
three built around a centre-forward rather than around wing-backs. Three
independent guides put the same module on the board, which for a club that has
played a back three for a decade is the single most important fact in this
profile — the roles that were worth most here last year (the E wing-backs) are
worth less in a four, and the full-backs are worth more.

Carnesecchi is untouchable in goal. Zappacosta is the right-back the guides
converge on ahead of Bellanova; on the left the slot is shared between
Bernasconi and Ahanor. In the middle Scalvini is the fixed point, with
Kristensen, Kossounou, Hien and Kolasinac all credible as the partner — the
opening giornata used Kolasinac and Kossounou, not the Kristensen the guides
predicted, so treat that pairing as genuinely open. Midfield is Ederson as the
deep man with Gaetano and Pasalic ahead of him and De Roon as the alternative;
Samardzic is the creative option who plays when Sarri wants passing over legs.
Up front Scamacca is the reference and De Ketelaere and Raspadori the two
around him, with Krstovic the other centre-forward and Elmas, Zalewski and
Sulemana K. the width in reserve. Both goals of the opening day came from
outside the predicted front three, which is the honest summary of how settled
this attack is.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Atalanta' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

Atalanta is the one club whose European commitment is already in our own
fixture list — Conference League ties, which is why `europe` is `UECL` and the
factor starts at 0.85. It moves *up* to 0.9 for the coach: Sarri's whole
managerial record is a fixed eleven and a resistance to turnover, and the
Conference is the competition where a coach of that temperament is most likely
to field a second team on Thursday and his own on Sunday. The men who will lose
Sunday minutes to Thursday are the ones already sharing a slot — the second
centre-back, the third midfielder, the two wide forwards — not Carnesecchi,
Scalvini, Ederson or Scamacca, who project to play everything.

Confirm the tie count rather than trusting this paragraph:

```
fantaclaude query --sql "SELECT competition, count(*) FROM v_european_ties WHERE team_short = 'ATA' GROUP BY 1"
```

## Set pieces

Scamacca is the penalty taker: both squad guides name him first, and the
season-20 workbook has him converting from the spot without a miss. De
Ketelaere and Samardzic are the two behind him.

Direct free kicks go to De Ketelaere first, with Samardzic, Gaetano and
Raspadori behind. Corners are genuinely contested: one set-piece guide puts
Samardzic first and the other puts Gaetano first, with Bernasconi, Bellanova
and Ederson also listed. `takers.corners` records Samardzic because two of the
three sources have him at or near the top on both dead-ball types, but treat it
as "Samardzic or Gaetano", not as a hierarchy.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Atalanta' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The centre-back pairing.** The guides predicted Kristensen; the opening
  giornata played Kolasinac and Kossounou. Whoever settles there is a different
  buy from whoever does not.
- **Sarri's first months.** A new module at a club built for the old one is the
  standard reason a profile like this goes stale inside a fortnight. If the
  back four does not survive September, everything above is wrong.
- **Corners.** Two guides, two different first names. Watch an actual corner.
- The Conference ties are in `fixtures`; the Europa and Champions phases for
  the other Italian clubs were drawn on 26–28 August 2026, after our calendar
  snapshot was taken. Re-run the calendar ingest before trusting any
  cross-club European comparison.
