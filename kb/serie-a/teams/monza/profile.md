---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Monza
team_short: MON
coach: Juric
module: 3-4-2-1
europe: none
rotation_factor: 0.95
takers:
  penalties: Pessina
  corners: Colpani
  free_kicks: Colpani
---

# Monza — 2026-27

## Tactics

Juric has taken a promoted side and set it up as he always does: a back three,
two wing-backs, two central midfielders and two players behind a striker. Two
of the three guides give exactly that 3-4-2-1; the third reads it as a 3-4-3,
which is the same personnel with the second trequartista pushed wide.

The goalkeeper is already an open question. The guides name Thiam; the opening
round was played by Pizzignacco, whom the listone carries with the transfer
flag, and Strajnar is the third. The back three is drawn from Carboni,
Lucchesi, Delli Carri, Maye, Antov and Kouadio, and the guides name three
different combinations. The wing-backs are Birindelli or Bakoune on the right
and Mangas on the left, with Ciurria the other specialist. Pessina is the
midfield anchor and captain, with Akinsanmiro, Colombo, Mout and Foe Ondoa
around him.

Colpani is the creative player the side is built around; Folorunsho, Forson and
Ngonge are the alternatives behind the striker, and the centre-forward is
contested between Cutrone, Varela and the transfer-flagged Petagna — Varela
scored on the opening day and Cutrone started it, which is the clearest thing
this squad has told us so far.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Monza' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

No European football — Monza is not among the seven Italian clubs drawn on
26–28 August 2026 — so the factor starts at 1.0 and moves only to 0.95, for
the reason that applies to every promoted side: the coach has a new squad and
has not yet chosen. The goalkeeper differed from every guide's prediction in
round one, three centre-backs compete for three slots that keep changing, and
the centre-forward is a two- or three-way contest. That is unsettledness rather
than turnover, but it costs the same predicted minutes.

Pessina, Colpani and Mangas are the three the guides and the opening round
agree on.

## Set pieces

Pessina takes the penalties in both squad guides, with Cutrone named behind
him. Colpani is first on corners and on direct free kicks, with Ciurria second
on both and Folorunsho third on corners.

There is no historical corroboration: Monza did not play in Serie A in season
20, so the workbook has no penalty record to check against. Every line in this
section rests on the two guides alone.

```
fantaclaude query --sql "SELECT DISTINCT season_id, team FROM v_player_match_current WHERE team = 'Monza'"
```

## Watch

- **The goalkeeper.** The guides say Thiam, the opening round said Pizzignacco,
  and Pizzignacco is transfer-flagged in the listone. Unresolved.
- **The centre-forward**, Cutrone against Varela, with Petagna transfer-flagged
  behind them.
- **The back three**, where no two guides name the same trio.
- **No Serie A history.** Nothing in this profile can be checked against the
  workbook until this season generates enough of its own.
