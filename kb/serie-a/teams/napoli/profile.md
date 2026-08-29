---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it, sport.sky.it, tg24.sky.it (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Napoli
team_short: NAP
coach: Allegri
module: 4-3-3
europe: none
rotation_factor: 0.85
takers:
  penalties: De Bruyne
  corners: De Bruyne
  free_kicks: De Bruyne
---

# Napoli — 2026-27

## Tactics

Allegri has taken over from Conte and, unusually for him, kept the 4-3-3 the
squad was built for rather than imposing a shape of his own; all three guides
agree on the module and on most of the eleven. What is recognisably Allegri is
the stated intent to change the game from the bench rather than from the
whiteboard — a balanced side that "cambia volto attraverso le sostituzioni".

Meret is first choice with Milinkovic-Savic behind him. The full-backs are Di
Lorenzo and Spinazzola and both are close to untouchable; the centre-back
pairing is the open question, with Rrahmani the fixed half and Buongiorno,
Beukema, Badiashile and Rafa Marin contesting the other — Badiashile's arrival
reordered that queue and the opening giornata used Marin, not the man the
guides expected. Midfield is Lobotka in front of the defence with McTominay and
one of Anguissa or De Bruyne alongside; the guides split on whether De Bruyne
plays as a mezzala or wide, and the opening giornata answered that he plays
wherever the ball is. Hojlund leads the line with Lucca as the alternative
centre-forward, Politano on one flank and Alisson Santos, Neres and Lang
competing on the other. Vergara is the academy midfielder who forced his way
into the picture on the opening day.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Napoli' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

Our fixture list holds no European ties for Napoli, so `europe` reads `none`;
that is our calendar snapshot being older than the draw, not a statement that
Napoli is out of Europe. The Champions League league phase was drawn on 26–27
August 2026 and the reporting puts Napoli in it. The factor is therefore set at
0.85 rather than 1.0, and the reason is written down here so the number is not
mistaken for a fixture-derived one: eight midweek European matches plus an
Allegri squad deep enough to change six players and a coach who has always
preferred to manage minutes rather than to burn an eleven.

Who loses Sunday minutes: the second centre-forward slot (Lucca for Hojlund),
the left flank of the front three, and the third midfielder. Meret, Di Lorenzo,
Rrahmani, Lobotka and McTominay are the spine that plays through it.

## Set pieces

De Bruyne is the whole set-piece department: first on direct free kicks, first
on corners, and the penalty taker in the two squad guides, with the season-20
workbook showing him converting from the spot. Politano and Neres are the
alternative deliverers, Alisson Santos, Vergara and Lobotka also take corners,
and Hojlund and McTominay are named behind De Bruyne on penalties.

One source dissents on penalties: it puts Lukaku first "when on the pitch and
in the right condition", with De Bruyne behind him. Lukaku carries the
listone's transfer flag, and the opening giornate have not featured him, so
`takers.penalties` records De Bruyne. If Lukaku settles and starts, revisit.

```
fantaclaude query --sql "SELECT name, transfer_flag FROM v_players_current WHERE team_name = 'Napoli' AND transfer_flag ORDER BY name"
```

## Watch

- **The calendar snapshot predates the European draws** (26–28 August 2026).
  Re-run the calendar ingest; when the Champions ties land in `v_european_ties`,
  `europe` becomes `UCL` and `doctor` will say so.
- **The second centre-back.** Four names, one slot, and a new signing who
  arrived after most guides were written.
- **Lukaku.** Transfer-flagged in the listone and absent from the opening
  giornate. His status changes the penalty line and the centre-forward pecking
  order at once.
