---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Bologna
team_short: BOL
coach: Tedesco D.
module: 4-3-3
europe: none
rotation_factor: 0.95
takers:
  penalties: Orsolini
  corners: Orsolini
  free_kicks: Orsolini
---

# Bologna — 2026-27

## Tactics

Tedesco has taken over and kept the 4-3-3 — all three guides agree on the
module — but the guide-comparison page notes that he has redistributed the
roles inside it rather than inheriting the previous eleven wholesale.

Skorupski is first choice with Happonen and Pessina behind. The back four is
Zortea right, Miranda left, and two of Heggem, Helland, Vitik and Casale in the
middle; the guides disagree on the pairing and the opening giornata used Heggem
with Helland while Holm also featured, so the four is not settled. The midfield
is the most crowded in the league: the comparison page counts eight names —
Ferguson, Bernardeschi, Moro, Amondarain, Pobega, Odgaard, El Azzouzi and Rowe
— for three slots, with Ferguson the only one every guide starts.

Orsolini is the untouchable of the front three, cutting in from the right.
Dovbyk arrived to lead the line and Piccoli is the alternative; both played on
the opening day, which is itself a sign that the question is open. Rowe,
Cambiaghi and Odgaard share the left.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Bologna' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

No European ties in our fixture list, and none expected: the 26–28 August 2026
draws put seven Italian clubs into Europe and Bologna is not among them. The
factor therefore starts at 1.0 and comes down only slightly, to 0.95, for one
reason — the midfield. Eight players for three slots is not depth for Europe,
it is a coach who has not decided, and until he does, any single Bologna
midfielder is a rotation risk. The same applies, less sharply, to the two
centre-back slots and to the centre-forward.

Skorupski, Zortea, Miranda, Ferguson and Orsolini are the ones who project to
play whatever happens.

## Set pieces

Orsolini is first on all three: penalties, corners and direct free kicks. Both
squad guides name him as the penalty taker, the dedicated set-piece guide puts
him first on both dead-ball types, and the season-20 workbook shows him taking
by far the most penalties of any Bologna player — though also missing some,
which is worth knowing before pricing him.

Bernardeschi is second on everything and is the taker when Orsolini is off;
Miranda and Ferguson are also listed on corners, and Bernardeschi and Dovbyk
behind Orsolini on penalties.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Bologna' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The midfield three.** The single least predictable department in Serie A
  by guide agreement. Until Tedesco settles it, do not treat any of the eight
  as a starter.
- **Dovbyk or Piccoli.** Both played on the opening day; whoever wins is worth
  materially more than the other.
- **The centre-back pairing**, still open after the first round.
- Our calendar snapshot predates the European draws of 26–28 August 2026. It
  does not change `europe` here — Bologna is not in Europe — but re-ingest
  before comparing clubs.
