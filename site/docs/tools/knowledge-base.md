# The knowledge base

DuckDB holds neutral numbers — presenze, fantamedia, prices, run outputs. The
`kb/` tree beside it holds something different: opinionated prose with
provenance, for the facts a model needs but a table cannot honestly hold.
Which of the two you reach for is not a style choice; it follows from what
the fact is.

## The rule that carries it

**Prose never restates a number.** A knowledge-base document links to a
query or a `run_id` instead of quoting a figure, because a figure copied into
prose is a figure nobody will ever update. "Lautaro averages 7.2" is a lie
waiting to happen — the average moves every giornata, and the sentence
won't. "Lautaro takes penalties unless Calhanoglu is on the pitch" is a
different kind of fact: durable, conditional, and there is no table anywhere
that holds it, because "who takes them, and under what condition" is not a
column, it's a judgment. That is the whole reason this tree exists next to a
database instead of being folded into it.

## Front-matter

Every document in the tree — except its own README — opens with a YAML
block carrying four keys the audit checks on all of them: `updated`, `ttl`,
`confidence`, `source`. A team profile adds the keys the model actually
reads: `team`, `team_short` (the listone's three-letter code), `coach`,
`module`, `europe`, `rotation_factor`, plus a `takers` mapping of role to
player.

```yaml
---
updated: 2026-08-24
ttl: 30d
confidence: high
source: regolamento
team: Example FC
team_short: EXF
coach: Coach A
module: 4-4-2
europe: none
rotation_factor: 0.80
takers:
  penalties: Player A
  corners: Player B
---
```

The club above is invented on purpose — no real team, coach, module or
rotation factor should ever be read off this page. `ttl` is either
`"<days>d"` or `"never"`; a document expires when `updated + ttl` falls
before today. A player note carries a sparser set — `player_id`, `name`,
`team_short`, `depth`, `availability`, `prior_fantamedia` — because it only
exists where prose changes a decision, not for every roster player by
default.

## The audit

`fantaclaude kb audit` walks the tree and reports what has expired, what
front-matter is missing, and what a structured document — a profile, a note,
a dossier — got wrong in its own keys. It is a notice, nothing more: the
audit does not renew anything, does not fill in a missing key, and does not
touch a file. An expired document is a flag for whichever skill would
otherwise lean on it — the skill is the one that decides to state lower
confidence or refuse outright. Renewal is a skill's job (`fanta-kb refresh`
for the ordinary case), never the audit command's.

## The tree

Three subtrees, each with a different rate of change. `rules/` is near-static
— the mantra format, house rules, an alias file — reviewed rarely because it
rarely moves. `serie-a/teams/<slug>/` holds one `profile.md` per club plus
sparse player notes beneath it, written only where a note would change a
projection. Neither carries anything about this league or its members.

`league/` is different: it holds opponent dossiers, season history, and an
append-only journal of this league's own auction and giornate. None of it is
reproduced on this site, and nothing here is drawn from it — including the
front-matter sample above, which is invented.

## Aliases

`kb/rules/aliases.yml` is the one place a name gets reconciled by hand across
sources that spell a player differently — fantacalcio.it's "Martinez L."
against Understat's "Lautaro Martínez." The listone is the identity
(`player_id`); every other source is matched onto it by surname, then
initial, then club, and a human alias in this one file overrides all three
when the heuristic can't or shouldn't decide. That is deliberate
concentration: a spelling problem gets fixed once, in one file anyone can
read, instead of turning into a silent guess buried inside whichever adapter
happened to hit it first.

See [the ingest contract](ingest-contract.md) for how a raw fetch becomes the
rows this alias file joins, and [the skill pattern](skill-pattern.md) for how
a skill treats an expired document as a judgment call rather than a blocker.
