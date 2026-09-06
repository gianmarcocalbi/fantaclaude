# The weekly forecast

`fantaclaude lineup` forecasts every player the probabili page lists and the
pinned valuation run priced, then builds the XI that maximises expected points.
It is local: what it reads was fetched by `fantaclaude ingest probabili` and
`fantaclaude ingest news`.

## p_start by precedence

A player's probability of starting has exactly one source. An entry in
`data/lineup-notes.yml` for this giornata sets the number outright (source
`note`); failing that, a squalifica on the current squalificati page forces it
to zero (source `squalificato`); failing both, the number the probabili page
published stands (source `published`). Which one won is recorded on the row.

## Sources that only ever disagree out loud

Everything else the forecast reads is a check, never a term: a player listed as
infortunato whom the probabili page still prices; a knowledge-base note whose
depth or availability disagrees with the page; a European tie inside the window
at a club the knowledge base marks as rotating. Each raises a named
disagreement and moves no number.

That is deliberate: the page's compilers already know about the injury, the tie
and the depth chart, and folding those facts in again would fade the same
player twice. It goes to a human instead, who settles it with a `lineup note` —
which does move the number, and records why. Once a note or a squalifica has
set `p_start`, the checks fall silent. Their thresholds live in
`core/src/fantaclaude/analysis/weekly/config.py`.

## The matchup term

Expected points is `p_start` times the expected fantavoto if he plays — two
factors, not one blended number.

The fantavoto side carries one fixture-dependent adjustment, `matchup_term`:
two deltas off this season's rated rows — one for the venue, one for what the
opponent concedes to the role — each against the role's own season mean, each
shrunk toward zero by how few rows back it (`matchup_shrink_k`), their sum
capped either way (`matchup_cap`). It is deliberately small: only this season's
rows have fixtures.

`fv_sd`, the spread of a player's own fantavoti, is pooled with a prior from
the role's back seasons, so few rated matches do not read as unusual
predictability.

## The XI

The optimiser runs one exact solve per permitted module and takes the best
total; every module's score is reported, not only the winner's. A player out of
position scores his voto minus one, applied inside the solve rather than after
it.

The bench is ordered the way the platform will read it: the best remaining
goalkeeper first, since the platform substitutes him separately, then by
`coverage` — for each candidate, summed over the starters he legally fits, that
starter's chance of not playing times what he would score in it. A slot no
bench player can fill is named.

`contingencies` are computed, not written by hand: for every starter whose
`p_start` falls below the threshold, the XI is re-solved without him and the
difference reported, module change included. The close calls are the slots
decided by less than the margin: the chosen player against the best excluded
player who fits it.

## Honest against its own kickoff

Lateness is recorded per row: the run is late once the round's first kickoff
has passed — when the platform locks the XI — and a prediction once *its own*
player's kickoff has. The write is refused once every match of the round has
started, unless `--late`, which marks the rows so the current-predictions view
skips them.

Nothing is revised afterwards: runs are appended, never edited. Each carries
`weekly_hash`, a digest over the weekly layer's version and every constant the
blend, the checks, the bench and the terms read, so results can be split by
weekly model.

## The loop closes

The XI actually fielded reaches one append-only table, `lineup_submitted`, by
two routes. `fantaclaude lineup record` writes it by hand at submission time —
the run's XI with `--swap` for the deviations, or the eleven and bench in full
— as source `hand`; it is local. `fantaclaude ingest lineup` reads the
platform's answer back after the lock as source `platform`, calling the live
league API.

Neither edits the other. Both are checked before they are recorded — eleven
distinct roster players, each a natural or adapted fit somewhere in the module
— because a record of an XI nobody could field is not a record; a hand-written
one must also name a module the league permits; the read-back records whatever
module was fielded. The newest row per giornata is the current one — the record
a forecast can be checked against.

Reading the platform's answer is not one lookup: the request is per match, so
finding it means resolving which competition, then which round of *its*
calendar the Serie A giornata maps to — a competition's own matchday is not the
giornata. The MCP servers page covers the resolver.
