---
updated: 2026-08-29
ttl: 14d
confidence: low
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Genoa
team_short: GEN
coach: De Rossi
module: 3-4-2-1
europe: none
rotation_factor: 1.0
takers:
  penalties: Colombo
  corners: Baldanzi
  free_kicks: Baldanzi
---

# Genoa — 2026-27

## Tactics

De Rossi is confirmed and plays a back three; **which back three is where the
sources split evenly, and that split is why this profile is `low`.** Two guides
read the side as a 3-4-2-1, two as a 3-4-1-2 — one trequartista behind two
strikers rather than two behind one. Both are permitted modules in this league,
and the difference decides whether Vitinha is a starter or a rotation option.

Everything else is comparatively settled: the guide-comparison page reports
five Genoa positions with no meaningful contest. Bijlow is the goalkeeper, with
Stolz and Sommariva behind. The three at the back are Vasquez, Ostigard and
Marcandalli, with Otoa — who played the opening round — as the fourth. The
wing-backs are Norton-Cuffy on the right and Martin or Mitaj on the left, with
Sabelli and Puczka as cover. Frendrup is the fixed midfielder and Sow the
summer arrival beside him, with Amorim and Ellertsson the alternatives.
Baldanzi plays behind the striker and is the creative hub; Messias and Meichtry
are the wide options. Colombo leads the line, with Vitinha and Osmajic the
other forwards.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Genoa' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

`rotation_factor` stays at 1.0. Genoa is not among the seven Italian clubs the
26–28 August 2026 draws put into Europe, De Rossi is not a habitual rotator,
and the squad is not deep enough to rotate meaningfully outside the front
three. Leaving the number where it starts, with a sentence saying why, is more
honest here than inventing a move.

The only genuinely shared slots are the left wing-back and the second forward.

## Set pieces

Colombo is the penalty taker in both squad guides, with Vitinha, Ostigard and
Messias named behind him. The season-20 workbook is of limited help: Genoa's
main takers last season were Malinovskyi and Stanciu, and neither is in the
current listone, which is precisely the situation where historical penalty data
misleads.

Baldanzi is first on corners and on direct free kicks in both set-piece
sources, with Messias, Frendrup, Traorè and Ellertsson behind on free kicks and
Messias, Frendrup and Ellertsson on corners; one of the two lists also puts
Martin among the first three deliverers.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Genoa' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **3-4-2-1 or 3-4-1-2.** A genuine two-against-two split among the guides,
  and the reason this profile is `low`. One televised lineup settles it.
- **The penalty taker.** Colombo is named by the guides but has no penalty
  record at this club to speak of, and the men who took them last season have
  gone.
- **The left wing-back**, Martin against Mitaj, still open.
- Our calendar snapshot predates the European draws of 26–28 August 2026; it
  does not change `europe` here. A re-ingest has already come back empty:
  UEFA's feed carries only qualifying and play-off rounds, and Italy's
  entrants join straight into the league phase, so no Italian club appears
  yet. The trigger for a cross-club European comparison is UEFA publishing
  that phase, not another re-ingest.
