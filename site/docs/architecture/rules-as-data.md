# League rules as data

A Mantra league's own rules are not fixed for all time. The budget, the
roster composition, the scoring formula, which modules are legal — any of
these can change from one season to the next, and some can change
mid-season. A system that hardcoded any of them would be correct only until
the next change, and silently wrong after it. fantaclaude instead treats the
rules the league runs on as data: fetched from the league's own settings,
snapshotted, and versioned, the same way any other fact the system depends
on is handled.

## One hash per rule set

Every snapshot of the league's settings is reduced to a hash over exactly
the payloads a valuation depends on — the roster rules, the lineup rules,
the scoring rules, and the team count that sets the money supply. That
hash, `rules_hash`, identifies one rule set. A new snapshot is only
appended when the hash moves against the previous one; re-syncing against
an unchanged rule set is reported, not written, so the history of rule
changes stays a record of what actually changed rather than a row per
sync attempt.

## What the API cannot say

Not everything a valuation needs is something the league API reports.
`league.yml` is where those facts live — each one recorded with its value,
where it came from, and the date it was checked, rather than as a bare
number nobody could later trace. Where a fact in `league.yml` duplicates
something the API also reports, the two are expected to agree.

When they do not, the sync refuses outright: nothing is recorded, and the
command exits with a dedicated status (exit 4), distinct from a plain error.
A disagreement between a hand-verified fact and what the API says right now
means at least one of the two is wrong, and there is no principled way for
the system to guess which — silently preferring the API would throw away a
fact someone deliberately verified, and silently preferring `league.yml`
would let a rule change the league actually made go unnoticed. Refusing is
the only choice that does not risk building a valuation on the wrong
figure without anyone knowing.

## Read off the page, not from memory

Some rules go further than "not in the API" — they are published only as a
description of a mechanism, with a league free to configure the specifics
one way or another. The Mantra defensive modifier is one: the platform's
own rules explain the general mechanism but leave a league to set its own
thresholds, and those thresholds are not exposed anywhere a fetch could
read them automatically. `d_factor.yml` holds them, transcribed by hand off
the league's own settings page, with a source and a date attached — never
filled in from memory or assumed to match some default, because there is
no default that is guaranteed to match what this league actually
configured.

## Every run is stamped

The consequence of all of this is that a valuation is never just "a run" —
it is a run computed under a specific, identified rule set. When the rules
change, the runs made under the old ones are not deleted and not silently
treated as still current: they are superseded, a distinction the system can
state precisely because every run carries the hash of the rules it was
computed under. A number produced under rules that no longer hold is not
merely old; it is a correct answer to a question the league is no longer
asking.
