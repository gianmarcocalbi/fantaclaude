# Auction night

The moment: the room is filling, the admin is about to open, and you need
the board to keep up with what happens live. You say "start the auction"
and `fanta-asta` runs `fantaclaude asta serve --session FA-xxx-xxx` — the
one command in the auction toolkit that touches the network. It subscribes
read-only to the FantaAstaLive feed, as the session's one allowed
subscriber, and mirrors it; everything else runs against that mirror.

## The mapping screen, before anything else

The first thing the process asks, before a board exists at all, is who is
yours and which dossier each rival at the table maps to. The feed can tell
you a room has ten seats; it cannot tell you which seat is which manager,
because FantaAstaLive's own labels are free text, not the league's. Answer
it honestly and out loud with the room: nothing later corrects a wrong
mapping on its own, and the pressure estimates in
[the auction engine](../architecture/auction-engine.md) are only as good as
knowing whose bidding you are actually reading.

## Reading the board

`fantaclaude asta board` ("what's the board?") is the question the night
keeps asking. Every `asta` command except `serve` is local — no network —
so ask as often as you like. Read it top to bottom: your credits and
picks, and what your roster still needs; the board's inflation and
reserve, and the completion those numbers would currently buy; the room
per class, as the ranks your squad already covers over the ranks the
pricer still has open; the block — the role class the room is calling for,
read off the lot or the latest pick; the players the board
[re-pins](../architecture/auction-engine.md) as your own roster fills out;
the lot, with its band and the pressure against it — what beating the room
for this player costs, distinct from what he is worth; the tier board per
class; and every `problem:` line.

## One price, explained

When a number surprises you, ask for the explanation rather than
re-deriving it — the trace is read, never recomputed. "Why is he at 62 when
I valued him at 30?" is answered by his walk value, his buy value, the
completion around him and the inflation applied — facts already recorded in
the run, not a fresh calculation.

## An adjustment is a fact with a reason

Say the room reports that a defender on the block is carrying a knock. You
do not do arithmetic on his price in your head. You give the fact a reason
and let the pricer apply it: the board has Bastoni's band at 38/45/52,
expected 40, pressure estimated at 47 because another manager at the table
is known to go to 46 for him. You adjust — a value factor of 0.85, reason
"limping, reported in the room" — and the band comes back at 32/38/44. Now
you can tell the room's number for what it is: 38 is the number, 44 the
most it is worth going to, and if the other manager pushes to 46 anyway,
that is his call.

## The dashboard, and the MCP while it runs

The dashboard at the address `asta serve` prints is the same board
rendered for a browser. While the server runs, prefer its MCP tools over
the CLI — they read the exact same in-memory board the dashboard shows.
More on the server: Tools › [MCP servers](../tools/mcp-servers.md).

## Closing the night

Once the room has stopped, close the auction: the state file is copied
permanently into `records/`, and you commit that copy.

Once the admin has moved the auction into the league, run `fantaclaude
ingest rosters` first — a live call against the league API, made now, not
"to check." Only then verify the transfer: it matches teams to the
league's rosters by roster overlap, never by name, since table names are
not guaranteed to match. Then `fantaclaude asta market-prices` reads what
the room paid against what the run expected, per class.

!!! warning
    Two things fantaclaude never infers on its own. An adjustment outlives
    the auction — it stays in `data/adjustments.yml` until you remove it,
    long after the player is sold. And closing the auction, or pruning the
    working state afterward, ends or deletes the night's live record — both
    are actions only you take, never a side effect of anything else.

For the drills to rehearse beforehand and the pre-flight checklist, see
`docs/asta-night-runbook.md` in the repository — it is not part of this
published site.

??? note "what ran"

    ```
    fantaclaude asta serve --session FA-xxx-xxx
    fantaclaude asta board
    fantaclaude asta explain "<player>"
    fantaclaude asta adjust --type value --player "<player>" --factor <n> --reason "<why>"
    fantaclaude asta close --session FA-xxx-xxx
    fantaclaude ingest rosters
    fantaclaude asta verify-transfer
    fantaclaude asta market-prices
    ```

    Full flags: Tools › [The CLI](../tools/cli.md).
