---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: sport.sky.it, tuttofantacalcio.it, fantacalcio-online.com, howtechismade.com, fantamaster.it, tg24.sky.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Inter
team_short: INT
coach: Chivu
module: 3-5-2
europe: none
rotation_factor: 0.85
takers:
  penalties: Calhanoglu
  corners: Calhanoglu
  free_kicks: Calhanoglu
---

# Inter — 2026-27

## Tactics

Chivu keeps the 3-5-2 the club has played for years, and every guide agrees:
a back three in front of Josep Martinez, two wing-backs who are the whole width
of the side, three central midfielders, and two strikers who play as a pair
rather than as a striker and a support man.

Bastoni is the untouchable of the back three and its left-sided outlet; Akanji
and Stones are the summer arrivals who make it a different line from last
season's, with Bisseck and Pavard the cover. Dimarco on the left is the
tactical centre of gravity — the deliveries come from him. The right wing-back
is the one genuinely open slot after Dumfries left, and the guides give three
different answers: Diouf, Luis Henrique or Spence. In midfield Barella and
Calhanoglu are fixed; the third slot was Zielinski's until Curtis Jones arrived
and the guide-agreement page has Jones overtaking him within a week, with Sucic
and Mkhitaryan behind both. Up front Lautaro Martinez is the constant and the
second striker is a three-way question between Thuram, Bonny and Pio Esposito, whom
the club is explicitly building minutes for.

Who actually took the field in the opening giornata is in the workbook rather
than in this paragraph:

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Inter' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

Our fixture list holds no European ties for Inter, so `europe` reads `none`.
That is our calendar snapshot being older than the 26–27 August 2026 Champions
League draw, which the reporting says Inter is in — not a claim that Inter is
out of Europe.

The factor is 0.85, and both halves of the move are deliberate. Down from 1.0
because a Champions League league phase adds eight midweek fixtures the fixture
table does not yet know about; down a little further because Chivu has said, in
as many words, that he intends to rotate more in his second season, midfield
first. That is a stated intention rather than an observed habit, so the move is
kept small.

Who loses minutes: the third midfielder, where Zielinski, Jones, Sucic and
Mkhitaryan share one slot; the right wing-back, contested three ways; and the
second striker, where Esposito is being brought in against the weaker
opponents. Bastoni, Dimarco, Barella, Calhanoglu and Lautaro are the five who
play everything.

## Set pieces

Calhanoglu is the whole dead-ball department — penalties, corners and direct
free kicks — and every source that names a first choice names him. Zielinski is
the vice-rigorista and Lautaro the third option; Dimarco is the other corner
and free-kick taker and takes the left-sided deliveries in practice, with
Barella and Sucic listed behind on corners. Season-20 penalty involvement
corroborates the order:

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Inter' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **The calendar snapshot predates the European draws** (26–28 August 2026).
  A re-ingest has already come back empty: UEFA's feed carries only
  qualifying and play-off rounds, and Italy's entrants join straight into the
  league phase, so `europe` stays `none` until UEFA publishes that phase, not
  merely after another re-ingest. `doctor` will flag this profile until it
  does.
- **The right wing-back.** Three guides, three different starters, and no
  direct replacement for Dumfries. A signing there rewrites the tactics
  section.
- **The third midfielder.** Jones arrived after most guides were written and
  the ordering moved within days; do not treat Zielinski as settled.
- **Whether Chivu's stated rotation actually appears.** Two giornate is not
  evidence. If the same eleven keeps starting, the coach half of the 0.85 move
  should be given back.
