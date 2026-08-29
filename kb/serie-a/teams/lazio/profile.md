---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Lazio
team_short: LAZ
coach: Gattuso
module: 4-3-3
europe: none
rotation_factor: 1.0
takers:
  penalties: Zaccagni
  corners: Zaccagni
  free_kicks: Zaccagni
---

# Lazio — 2026-27

## Tactics

Gattuso has taken over and two of the three guides give a 4-3-3, the third a
4-2-3-1; the players are largely the same either way, and the difference is
whether Dele-Bashiru plays as a trequartista or as a mezzala.

Mandas is first choice, with Motta and Renzetti as the alternatives. The
defence has been reshuffled hard: Marusic on the right, Pedraza
or Tavares on the left, and two of Doekhi, Sutalo, Provstgaard, Romagnoli and
Patric in the middle — the guides name Doekhi as one half and disagree on the
other, and the opening round used Provstgaard. Rovella is the deep midfielder
with Frattesi and Taylor beside him and Cataldi and Belahyane in reserve;
Frattesi is the one the guides call the guarantee, and he scored on the opening
day.

The front three is Zaccagni on the left, Isaksen on the right, and a
centre-forward the guides cannot agree on: Pinamonti arrived and one page notes
that most guides had not yet rated him, while Dia started the opening round and
Noslin and Ratkov are also listed. Cancellieri is the other wide option.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Lazio' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

`rotation_factor` stays at 1.0. Lazio is not among the seven Italian clubs the
26–28 August 2026 draws put into Europe, so there is one competition and a
Sunday-only calendar; Gattuso's record is a demanding but settled eleven rather
than a rotating one; and the squad, while wide, is not deep in the positions
that matter. The number stays where it starts and the reason is written here
rather than dressed up as a judgment.

The exception is the centre-forward, which is a shared slot in all but name
until Pinamonti or Dia separates.

## Set pieces

Zaccagni is first on penalties in both squad guides and first on corners and
direct free kicks in the dedicated set-piece guide, with Taylor and Rovella
behind him on both. The other set-piece list orders the same three men
differently, putting Rovella first, so read the corner and free-kick entries as
"Zaccagni or Rovella" rather than as settled.

The season-20 workbook is a caution rather than a corroboration: Lazio's
penalties then went to Cataldi and to a player no longer in the listone, and
Zaccagni's only recorded involvement was a miss.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Lazio' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The centre-forward.** Pinamonti arrived late enough that the guides had not
  priced him and did not play the opening round; Dia did. Whoever wins is one
  of the more valuable unsettled slots in the league.
- **The second centre-back**, where the guides and the opening lineup
  disagreed.
- **Penalties.** Zaccagni is named by everyone but has a miss and no
  conversions in the recent record. Watch the first one.
