---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: fantacalcio-online.com, howtechismade.com, fantamaster.it, sosfanta.com (2026-08-29); coach, squad and appearances from the listone and the voti workbook"
team: Sassuolo
team_short: SAS
coach: Aquilani
module: 4-3-3
europe: none
rotation_factor: 1.0
takers:
  penalties: Berardi
  corners: Berardi
  free_kicks: Berardi
---

# Sassuolo — 2026-27

## Tactics

Aquilani is in charge and all three guides give a 4-3-3, described as a
possession side rather than a counter-attacking one — which for a club at this
end of the table is a choice, not an inheritance.

Muric is first choice with Turati, Satalino and Russo behind. The back four is
where the guides diverge most: Missori or Cinquegrano on the right, Doig or
Obrador on the left, and two of Idzes, Leysen, Odenthal, Macchioni, Candè and
Walukiewicz in the middle — Idzes is the only central defender every guide
starts, and the opening round used Leysen and Macchioni with Odenthal scoring.
Matic anchors the midfield with Thorstvedt and Adzic beside him, Adzic cast as
the creative one; Boloca, Lipani, Iannoni, Bakola and Konè are the depth.

Berardi is the side — the right-sided forward everything is built around —
with Laurientè on the left and Bowie leading the line after Pinamonti's
departure; Volpato and Dominguez are the other attacking options. Berardi did
not play the opening round, which is the reason to read the rest of this
profile carefully rather than confidently.

```
fantaclaude query --sql "SELECT name, classic_role, voto, goals, assists FROM v_player_match_current WHERE season_id = 21 AND team = 'Sassuolo' AND sheet = 'Fantacalcio' ORDER BY giornata, classic_role"
```

## Rotation

`rotation_factor` stays at 1.0. Sassuolo is not among the seven Italian clubs
the 26–28 August 2026 draws put into Europe, Aquilani has no record as a
rotator, and a squad at this level plays its best eleven every week. The back
four moves around because the coach has not decided, not because he is resting
anyone — and that is unsettledness rather than rotation, so it belongs in
"Watch" rather than in this number.

## Set pieces

Berardi is the whole department and the sources are unusually emphatic about
it: first on penalties in both squad guides, first on corners and direct free
kicks in both set-piece sources, and described by one of them as the absolute
left-footed specialist for any dead ball. Adzic, Laurientè and Thorstvedt are
behind him on free kicks; Adzic, Laurientè, Volpato and Doig on corners;
Laurientè on penalties. The season-20 workbook corroborates Berardi from the
spot, misses included.

The obvious risk is concentration: if Berardi is out, no source says who takes
over, and the honest answer is that we do not know.

```
fantaclaude query --sql "SELECT name, sum(pen_scored), sum(pen_missed) FROM v_player_match_current WHERE season_id = 20 AND sheet = 'Fantacalcio' AND team = 'Sassuolo' AND (pen_scored > 0 OR pen_missed > 0) GROUP BY 1"
```

## Watch

- **Berardi's availability.** He is the tactics section and the whole set-piece
  section, and he missed the opening round. Nothing else in this profile
  matters as much.
- **The back four.** Six names for two central slots and no guide agreement;
  the opening round contradicted all of them.
- **The centre-forward.** Bowie is promoted into the role rather than bought
  for it.
