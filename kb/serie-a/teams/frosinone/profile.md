---
updated: 2026-08-29
ttl: 14d
confidence: low
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Frosinone
team_short: FRO
coach: Alvini
module: 4-2-3-1
europe: none
rotation_factor: 0.9
takers:
  penalties: Calò
  corners: Calò
  free_kicks: Calò
---

# Frosinone — 2026-27

## Tactics

**This is the least readable side in the league and the profile is marked
`low` because of it.** The guide-comparison page says so in as many words —
"la squadra meno leggibile del campionato" — and reports that Raimondo is the
only Frosinone player every guide starts. Two of the three guides give a
4-2-3-1, the third a 4-3-3, and none of them agrees with another on more than a
handful of the outfield names.

What can be supported: Alvini is the coach and this is a promoted side that
has rebuilt almost completely — it carries the largest listone squad in the
division, which is itself the symptom. Palmisani is the goalkeeper the guides
and the opening giornata agree on, ahead of Pisseri, Lolic and Desplanches. The
back four is drawn from Oyono, Bracaglia, Monterisi, Cittadini, Calvani,
Akpoguma and Terzic, and the opening round used a different combination from
the one the guides predicted. Calò is the deep midfielder and the one outfield
constant; Grillitsch arrived to play beside him but did not feature on the
opening day. Schmid, Hasa, Zerbin, Kvernadze, Fini and Ghedjemis compete for
the three attacking slots, and Raimondo leads the line with Birligea and Bobcek
behind him.

```
fantaclaude query --sql "SELECT name, classic_role, mantra_roles FROM v_players_current WHERE team_name = 'Frosinone' ORDER BY classic_role, name"
```

## Rotation

No European football — Frosinone is not among the seven Italian clubs the
26–28 August 2026 draws put into Europe — so the factor starts at 1.0. It comes
down to 0.9, the largest non-European discount in this knowledge base, for a
reason that is not turnover in the usual sense: a promoted coach with the
league's biggest squad and no settled eleven will change the side week to week
until he finds one. For a projection, an unsettled eleven and a rotating eleven
cost the same minutes.

Palmisani, Calò and Raimondo are the three the guides converge on. Everyone
else should be priced as a share of a slot.

## Set pieces

Calò takes everything the guides are willing to assign: penalties, corners and
direct free kicks, first choice in both set-piece sources. Kvernadze, Schmid,
Ghedjemis and Masini are named behind him.

There is no historical corroboration at all — Frosinone did not play in Serie A
in season 20, so the workbook has nothing to check this against:

```
fantaclaude query --sql "SELECT DISTINCT team FROM v_player_match_current WHERE season_id = 20 AND team = 'Frosinone'"
```

## Watch

- **Everything.** This profile is `low` on purpose. The module is split two-to-
  one, only three players are agreed on, and there is no Serie A history to
  fall back on. Re-read it after four or five giornate, when there is an actual
  eleven to describe.
- **Grillitsch.** Signed to be the other half of the midfield and absent from
  the opening round.
- **Whether the module is a 4-2-3-1 at all.** One guide reads the same squad as
  a 4-3-3.
