# The week

The moment: it is a giornata week, and `fanta-manager` runs the same two
beats every time — a refresh early in the week, a lineup before the lock.
The forecast and the XI it builds are described in
[the weekly forecast](../architecture/weekly.md); this page is about reading
what that engine hands back and arguing with it before Friday.

## Tuesday — refresh

Say "refresh the week" and three things run: the finished giornata's voti
land first, then the probabili and news pages — each a single, polite read
of a public web page — then an early forecast, which is entirely local, so
a prediction exists for every player while the week is still young. Each
prediction is written honestly against that player's own kickoff and is
never revised afterward — a Thursday-night player's number does not wait
for Sunday's news to catch up.

Worth being precise about: nothing in fantaclaude scores a forecast against
what actually happened. The record this run writes is what a forecast
*can* be checked against later — that is why it is written honestly and
early — but no command in this codebase performs that check today. Running
early is valuable in its own right, not because something downstream grades
it.

If a name in the ingest output goes unmatched, it is an alias to add to the
knowledge base's alias list, never a guess about who it might be.

## Friday — the lineup

Say "what do I field?" close to the lock and read the report top to bottom:

- the header — the deadline and how many of the round's matches are
  compiled;
- `UNCOMPILED` matches and per-match staleness: a Tuesday compilation for a
  Sunday match is a number to distrust, not to use;
- the blend counts — how many `p_start` values came from the page, from a
  squalifica, from a note you wrote;
- every disagreement between sources — you adjudicate each one, with a note
  or with nothing, and say which;
- the XI and what every rejected module scored beside it;
- the bench, in the platform's own order, with a diffidato marked because a
  yellow card this week means a suspension next week — his call to make,
  never the model's — and any slot the bench cannot legally fill;
- the contingency for every doubtful starter — who enters if he does not
  play, and what it costs;
- the close calls — the slots decided by a margin thin enough to be worth a
  second look.

**Giornata 4, worked**: the page compiled 10 of 10 matches at 11:05, blend
471 published · 2 squalificato, one disagreement — Éderson priced by the
page at 90% for a Conference-League week, where the season rate under
rotation expects 63%. You know his coach rested him in Thursday's
training, so you leave it as is — no note. The XI comes back 3-5-1-1, bench
led by Svilar, nothing uncovered; the contingency says a doubtful Kean
(55%) is replaced by Hojlund, costing about 1.4 expected points; one close
call, decided by 0.2, between a wide option in and the alternative left
out. You tell Claude what you are fielding and what changes if Kean does
not play, and move on to actually submitting it.

## Then you type it in

!!! warning
    The XI goes on the platform by hand. Nothing in fantaclaude submits a
    lineup, a bid, or anything else — this command only tells you what to
    type in, never types it for you.

## And record it

Right after you submit, record the XI as fielded — the run's XI as-is, or
with a swap for every deviation from it; this is local, no network. Once
the lock for the round has passed, `fantaclaude ingest lineup` calls the
live league API to read the same fact back off the platform itself. Both
land in the same append-only record; the read-back is run once, after the
round, and never as a way to double-check the hand record you already
wrote.

??? note "what ran"

    ```
    fantaclaude ingest stats-web --giornata <finished>
    fantaclaude ingest probabili
    fantaclaude ingest news
    fantaclaude lineup
    fantaclaude lineup note --type p_start --player "<name>" --p-start 0 --reason "<why>"
    fantaclaude lineup record --swap "Out=In"
    fantaclaude ingest lineup      # once, after the round
    ```

    Full flags: Tools › The CLI.
