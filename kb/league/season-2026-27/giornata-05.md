---
updated: 2026-09-22
ttl: never
confidence: high
source: "no lineup run (no forecast was written); match_file 3, the platform read-back of 2026-09-22; fantaclaude calibrate --giornata 5"
---

# Giornata 5 — Sanzimippi FC, 18-20 September 2026

Lost 1-3, 67.5 to 76.5, the last round before the international break. The
scores below are `calibrate`'s and reproduce with it:

```
fantaclaude calibrate --giornata 5
```

## No forecast

As in giornata 4, the weekly loop was not run: no forecast, no model XI, no
point on the calibration curve, and none can be written after the fact. The XI
below was read back from the platform on 2026-09-22.

## What was fielded, and what was possible

A 4-1-4-1 this time: Caprile; Doig, Mancini, Bertola, Hainaut; Karlstrom;
Zaccagni, Da Cunha, Thorstvedt, Rowe; Douvikas. The eleven scored 63 on their
own — Bertola did not play — and the bench added 4.5: Gallo came on in his
place through a forced substitution, with the one-point malus.

There is no "best possible" eleven for this week, and the reason is the week's
real story. Of the five players on the roster who can play Dc — Mancini,
Idzes, Vasquez, Bertola, Walukiewicz — only Mancini got a voto. Every permitted
module needs at least two, so no eleven made only of players who played could
have been submitted at all; the platform reached a legal one only through a
forced substitution, Gallo into a Dc slot at a point's cost. `calibrate` does
not simulate substitutions, so it says so rather than guess. Zaccagni's
converted penalty, worth 10, was the one bright line.

## What I learned

_Left for the operator._
