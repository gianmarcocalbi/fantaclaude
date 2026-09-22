---
updated: 2026-09-22
ttl: never
confidence: high
source: "lineup run 2 (valuation run 20260904T091947Z-7694bd6a); match_file 1, the platform read-back of 2026-09-22; fantaclaude calibrate --giornata 3"
---

# Giornata 3 — Fabio Borini, 4-7 September 2026

The first round of the calendario, and the only one of the first three with a
forecast. Lost 1-4, 67 to 82.5. The numbers below are `calibrate`'s and
reproduce with it:

```
fantaclaude calibrate --giornata 3
```

## What was fielded, against what the model named

The model's run 2, written on the Friday afternoon before the first kickoff,
named a 3-5-1-1: De Gea; Mancini, Vasquez, Idzes; Vlasic, Frendrup, Matic,
Ellertsson, Da Cunha; Pierotti; Zaccagni. I fielded a 3-4-2-1 instead and kept
eight of its eleven, swapping Caprile for De Gea, Rowe for Pierotti and
Douvikas for Matic.

All eleven of the model's players got a voto, so its score is exact rather
than a bound: 61.5. My eleven scored 57 on their own — Rowe did not play — and
the bench added 10: Adams C. came on and scored, the only bench fantavoto that
takes 57 to the platform's 67. On the eleven alone the model's choice was the
better one by four and a half points; the bench turned it around. Neither would
have won: the best eleven the roster could have fielded knowing every
fantavoto was a 4-2-3-1 worth 81 — Caprile; Doig, Idzes, Vasquez, Hainaut;
Karlstrom, Matic; Da Cunha, Zaccagni, Adams C.; Kean — still short of 82.5.
Fourteen points were left out: Doig, Hainaut, Karlstrom, Adams C. and Kean all
began on the bench and all scored 7.5 or more — Doig, Karlstrom and Adams C.
with a goal each.

## What the page got wrong

The page was read on the Friday afternoon for matches running to Monday, the
staleness open question 18 describes, and it shows. Nine players published at 80-90%
got no voto — two at Venezia, two at Monza, and one each at Parma, Frosinone,
Atalanta, Udinese and Sassuolo. Across the whole page, 473 players, the
published number was clearly informative (Brier 0.139 against 0.238 for
knowing only the base rate), and roughly calibrated at the top: 80-89% got a
voto 94% of the time, 90% and over 95%. The middle was not: players published
at 60% got a voto 76% of the time, while the few at 70-79% managed half.
Substitutes' cameos count as a voto, so the low bins read high by
construction; the 60% bin reading high is the one worth watching.

The fantavoto side, on a single round, is noise until proven otherwise: the
goalkeepers came in about half a point under the model's expectation, the
forwards a little over. On my own roster the three biggest misses were all
upside — Doig, Karlstrom and Adams C. each more than three points above what
the model expected of them — and the largest downside was Douvikas, a point
and a half below.

## What I learned

_Left for the operator._
