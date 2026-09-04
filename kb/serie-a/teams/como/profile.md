---
updated: 2026-09-04
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it, tg24.sky.it (2026-08-29); dazn.com probabile formazione and goal.com on the Kean signing (2026-09-04); coach, squad and appearances from the listone and the voti workbook"
team: Como
team_short: COM
coach: Fabregas
module: 4-2-3-1
europe: none
rotation_factor: 0.8
takers:
  penalties: Da Cunha
  corners: Baturina
  free_kicks: Paz N.
---

# Como — 2026-27

## Tactics

Fabregas is confirmed and so is the 4-2-3-1: all three guides give the same
module, a double pivot behind a trequartista and two wide forwards, and a
single centre-forward. It is a possession side whose entire creative load sits
on the number ten.

Butez is first choice ahead of Vigorito and Tornqvist. The back four is Couto
right, Valle or Kaiki left, and Chalobah with Ramon in the middle, with
Goldaniga, Kempf, Kambwala and Cuenca as the depth — an unusually large
defensive squad for a club of this size, which is itself a rotation signal. The
pivot is two of four rather than a fixed pair: Da Cunha is the constant, with
Milla, Perrone and Ricci S. around him — the probable-formation guides start
Milla, the opening day used Milla, Da Cunha and Perrone, and Caqueret is
behind all of them. Nico Paz is
the trequartista and the player the whole side is arranged around; Baturina and
Diao are the wide forwards, with Kuhn, Addai, Rodriguez and Lahdo competing.
The centre-forward is a two-man duel and no longer a settled place. Douvikas
started the opening day and scored, and he is the one who reads the system —
that is his edge, and it is slight. Kean arrived late in the window on a loan
the club is obliged to convert, at a fee that says he was wanted rather than
accepted, and the reporting is unanimous that he was promised nothing: the
duel is called a tight one, the alternation is expected to be frequent, and
both are named as possible together in some games. Kean also has last
season's form and condition to recover. Azon and the transfer-flagged Morata
are behind them both. Treat the shirt as shared and neither man as safe.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Como' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

Our fixture list holds no European ties for Como, so `europe` is `none`. That
is our calendar snapshot being older than the 26–27 August 2026 Champions
League draw, which the reporting says Como is in — a first participation, and
one of the two facts that make this the hardest club in the league to project.

The factor is 0.8 for three compounding reasons, all written down so the number
can be argued with: a Champions League league phase this squad has never played
before; a coach whose guides already flag "frequent rotation expected given
Champions League commitments"; and a squad deliberately built two-deep in every
line over the summer. The forward line is where it will show — four or five
names for two wide slots — along with the second centre-forward and the pivot.
Paz is the one who should play everything; Butez would be, but see the
goalkeeper in "Watch".

## Set pieces

Da Cunha is the penalty taker: both squad guides name him first, and the
season-20 workbook has him converting from the spot repeatedly without a miss —
the strongest data corroboration of any penalty taker in this knowledge base.
Nico Paz and Douvikas are named behind him, and the workbook also records Paz
missing from the spot, which is presumably why he is not first. The
probable-formation guide names Douvikas and Kean as the two alternatives, so
whichever of them holds the shirt inherits the second call rather than the
first — the penalties stay with Da Cunha either way.

Corners go to Baturina first and free kicks to Nico Paz first, with Da Cunha
and Perrone in both lists. The two set-piece guides agree on the group; they
order the first two differently, so treat corners and free kicks as shared
between Paz and Baturina rather than as assigned.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Como' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch
- **The goalkeeper may be a contest, not a choice.** This profile has Butez
  first ahead of Vigorito and Tornqvist, and he did start the opening day —
  but the probable-formation guide calls it an open competition with a
  keeper this profile never named, whom the listone carries as
  `Sanchez Ro.`. Either the guide is stale or this profile is; the shirt is
  worth one query in a fortnight rather than a guess now.
- **Kean and Douvikas.** The one place where a wrong call costs real credits
  here: the two of them are priced as a shared shirt, and a settled starter
  would be worth half as much again as either currently is.

- **The calendar snapshot predates the European draws** (26–28 August 2026),
  but that snapshot is not what's blocking `europe`. A re-ingest has already
  come back empty: UEFA's feed carries only qualifying and play-off rounds,
  and Italy's entrants join straight into the league phase, so `europe`
  stays `none` until UEFA publishes that phase -- Como's Champions League --
  not merely after another re-ingest. `doctor` will flag this profile until
  it does.
- **Nico Paz.** He is the side. A transfer, an injury or a rest rotation
  changes the tactics, the free kicks and the value of everyone around him.
- **A first Champions League campaign.** No one, including these guides, knows
  how Fabregas will balance it. 0.8 is a guess with reasons, not a measurement.
