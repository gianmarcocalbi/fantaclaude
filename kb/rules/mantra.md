---
updated: 2026-08-29
ttl: never
confidence: high
source: https://www.fantacalcio.it/regolamenti/sistema-mantra
---

# Mantra — the role system this league plays under

Mantra replaces the four classic roles (P, D, C, A) with twelve, and replaces
"pick eleven players" with "fill eleven labelled slots". A player is bought for
the slots he can occupy, not for the department he belongs to. Everything below
is the official regolamento in prose; the machine-readable module table is
`core/src/fantaclaude/model/modules.yml`, transcribed from the *Tabella
sostituzioni per schema* the regolamento links, and is **linked, never copied
here** — a second copy is a second thing to keep right.

## The twelve roles

The regolamento's glossary, with what each label means on the pitch.

**Por** — goalkeepers. The only role with a slot of its own in every module,
and the only one substituted before any outfield reshuffle.

**Dc** — central defenders, "indipendentemente se impiegati in una linea
difensiva a 3 o a 4": the label does not care whether the club plays a back
three or a back four.

**B** — fullbacks who can be a third of a back three, but are unsuited to, or
unpractised at, playing as a central defender. B is the bridge between a
four-man and a three-man line; it is not a Dc.

**Dd** / **Ds** — fullbacks of a back four, right and left respectively. The
side matters: the regolamento forbids inserting one where the other belongs.

**E** — wing-backs, the men who complete a back three. Defensive duty first,
attacking output second; this is the role a 3-5-2 lives or dies on.

**M** — holding midfielders in the strict sense, and deep playmakers: the
defensive half of the middle.

**C** — central midfielders who join the build-up and support the attack. The
regolamento's balance point: C is a midfielder who is expected to arrive.

**T** — the attacking midfielder, "con spiccate doti offensive e minore
dedizione alla fase di copertura". A trequartista, judged on chances created.

**W** — pure offensive wingers on the trequarti line. Not a wing-back; W is a
forward who starts wide.

**A** — the linking forward, who "partecipa organicamente alla manovra
offensiva": a second striker or a wide forward who comes inside.

**Pc** — the centre-forward, stationed more or less permanently around the
penalty area.

A player usually carries two or three of these, in the order the listone gives
them; `v_players_current.mantra_roles` is that list. The first is the one he is
bought for, the rest are the flexibility.

## How a module constrains the eleven

A module is eleven labelled slots — one Por and ten outfield, split five
defensively-minded (Dd, Ds, Dc, B, E, M) and five offensively-minded (C, T, W,
A, Pc) in every one of them, which is why every Mantra module reads as a
back-and-midfield arithmetic rather than as a free shape. Many slots are
hybrids: a slot written `M/C` takes either without penalty, a slot written
`A/Pc` takes either. Which modules this league permits is a league setting, not
a constant — read it, never assume it:

```
fantaclaude query --sql "SELECT modules FROM v_league_settings_current"
```

The slot-by-slot table — which roles are natural in a slot, which are adapted,
and which are reachable only through a forced substitution — is
`core/src/fantaclaude/model/modules.yml`, keyed by the same module strings the
league setting uses.

## Adaptation and the malus

A player may be placed in a slot his roles do not cover: that is *adattamento*,
and it costs a one-point malus on his fantavoto. The regolamento blocks the
adaptations it considers abusive at the moment the lineup is submitted — a B,
Dd or Ds cannot be dropped into a Dc slot; a Dd and a Ds cannot stand in for
each other; an E cannot fill a pure M slot, nor an M a pure E slot, unless the
slot is one of the hybrids; a W cannot fill a pure T slot. These are lineup-time
prohibitions, not universal ones: the forced-substitution algorithm may still
reach such a placement when nothing legal is left.

In `modules.yml` this is the three-way distinction: `natural` (no malus),
`adapted` (allowed at insertion, with the malus), `forced_only` (refused at
insertion, reachable only by the algorithm, with the malus).

## Forced substitutions

When a fielded player has no rating, the algorithm replaces him from the bench;
the bench order decides who comes on when several combinations are legal, and
all absent players are solved together rather than one at a time. The
goalkeeper is handled first and separately.

Three modes exist, and which one applies is a league setting — again, read it
rather than assume:

- **BASIC**, the default, prefers first a solution that keeps the module, then
  one that changes module, then one that adapts a player and pays the malus.
- **EASY** never changes the module: an optimal solution inside it, otherwise
  an adapted one.
- **MASTER** honours the bench order above everything and will change module
  freely to field the next man on the bench.

How many substitutions this league grants, and the bench size they draw from,
are in `v_league_settings_current` — see `kb/rules/house-rules.md`.

## Why this document exists

The projection needs to know what a player *can* be fielded as before it is
worth anything at auction: a Dc who is only ever a Dc is a narrower buy than a
Dd/Dc, and an E in a league that permits 3-5-2 is worth more than in one that
does not. Roles come from the listone, modules from the league settings, and
the mapping between them from `modules.yml`. This file explains the mapping; it
does not restate it.
