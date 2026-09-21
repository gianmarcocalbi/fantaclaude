# Capabilities

## Know the league's own rules

The scoring system, roster limits and modifiers a Mantra league runs on are
read directly from the league's own settings rather than assumed from memory
or from a generic ruleset. Every valuation and every forecast that follows is
stamped with the rules in force at the moment it was computed, so a rule
change never quietly invalidates work already done under the old one.

## Value every player in the listone

Every player in the auction pool is projected from his own playing history
under those rules, then priced against the best way to complete a full
roster built around him. The unit of value is a whole squad, not a ranked
list of individual players, because a striker's price depends on what money
is left for a defence once he is bought — a coupling a name-by-name ranking
cannot represent on its own.

## Price a live auction as it happens

The same [valuation](../architecture/valuation.md) carries into the auction room and is re-priced against
each participant's remaining credits and open roster spots every time a
player sells. A price standing alone before the auction starts is only a
starting point; what a player is worth on the night depends on what is left
of the market around him, and that figure moves with every sale.

## Pick a legal XI every week

Given the players available for a giornata, a lineup is chosen from the
modules the league permits, with the bench ordered the way the platform
itself would order it and a contingency prepared for every player whose
start is in doubt. The result names the close calls explicitly — the players
near the cutoff whose inclusion or omission barely changes the expected
score — rather than presenting one XI as though no other choice came close.

## Read back what was actually fielded

Once a giornata locks, what was actually put on the pitch — not merely what
was forecast — is captured from the platform's own record. Both that record
and the [forecast](../architecture/weekly.md) it followed are written to the
same store, immutably and side by side, so the forecast can be scored
against the outcome it preceded. This is what makes a forecast improvable in
principle, not a step that improves it today.

## Hold opinionated prose with provenance and an expiry date

Not everything worth knowing about a club or an opponent survives being put
into a table: a coach's habit, a set-piece taker, a rivalry that changes how
a manager rotates. Those facts live as prose with a source and a freshness
date attached, so a stale belief is visible as stale rather than trusted
forever by default.

## Answer questions about the live league

Questions about the state of the league — a team's roster and credits, the
scoring and roster rules in force, or the XI both sides fielded in a given
match — can be answered directly and read-only, without a separate trip to
the platform's own pages. Nothing here writes back to the league; the value
is in the answer arriving inside the same conversation.
