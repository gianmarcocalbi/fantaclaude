---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Venezia
team_short: VEN
coach: Stroppa
module: 3-5-2
europe: none
rotation_factor: 0.95
takers:
  penalties: Adams A.
  corners: Busio
  free_kicks: Busio
---

# Venezia — 2026-27

## Tactics

Stroppa has brought a promoted side up and set it out as a 3-5-2 — all three
guides agree — with a back three, two wing-backs and three central midfielders
behind a strike pair. It is the conservative shape for a side expected to
defend, and Venezia is one of only two clubs to have played two rounds so far,
so there is more evidence here than for most.

The goalkeeper was the summer's open question: the guides name Stankovic and
note that Montipò arrived to compete, and Stankovic has played both rounds.
The back three has rotated already — Bella-Kotchap has started throughout,
with Schingtienne, Halhal, Franjic, Moreno, Sverko and Gomes cycling around
him. The wing-backs are Correia on the right and Haps or Hainaut on the left,
and all three have played.

The midfield is Busio, Basic and one of Sohm, Kike Perez, Helgason, Duncan or
Dagasso — the guides name different thirds and the two rounds used different
combinations. Up front the guides pair Adams with Yeboah or with Rrahmani, and
both rounds fielded Adams with Yeboah, with Rrahmani and Lauberbach coming on.

```
fantaclaude query --sql "SELECT name, classic_role, giornata, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Venezia' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

No European football — Venezia is not among the seven Italian clubs drawn on
26–28 August 2026 — so the factor starts at 1.0 and moves to 0.95. The reason
is visible in our own data rather than borrowed from a guide: across the two
rounds played, the back three and the midfield have already changed, while the
goalkeeper, the strike pair and Busio have not. A promoted coach settling a new
squad is the ordinary cause, and it should fade by October.

Stankovic, Bella-Kotchap, Correia, Busio, Adams and Yeboah are the six with the
most stable minutes so far.

## Set pieces

Adams is the penalty taker in both squad guides, with Yeboah and Rrahmani named
behind him. Busio is first on corners and on direct free kicks, with Basic and
Yeboah behind on free kicks and Kike Perez, Basic, Helgason and Yeboah on
corners.

There is no historical corroboration: Venezia did not play in Serie A in season
20, so nothing in this section can be checked against the workbook. It rests on
the two set-piece sources agreeing with each other.

```
fantaclaude query --sql "SELECT DISTINCT season_id FROM v_player_match_current WHERE team = 'Venezia' ORDER BY 1"
```

## Watch

- **Montipò.** Signed to compete for the goalkeeper's shirt and yet to play.
  A goalkeeper change would be the most expensive single event here.
- **The third midfielder**, where five names have a claim and two rounds have
  given two different answers.
- **No Serie A history.** Every set-piece and penalty line rests on guides
  alone until this season produces its own record.
