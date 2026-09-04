---
name: fanta-asta
description: The auction copilot with fantaclaude — read the board the pinned run gives against the mirrored auction (`asta board`), explain one price (`asta explain`), turn a fact from the room into an adjustment (`asta adjust`), rehearse on a captured session (`asta replay`), close the auction (`asta close`). Use before and during the auction, and to rehearse. During the auction, `asta serve` mirrors the live session and serves the dashboard and the `fantaclaude-asta` MCP; `adjust` and `refresh` write through it.
---

# fanta-asta

Python does the math; this skill does the judgment. It never computes a max
price: it reads the board `fantaclaude asta board` prints, changes *inputs*
(an adjustment with a reason, a dossier, the scenario) and reads again.
Discover the CLI with `fantaclaude asta --help`; every command takes `--json`
and every one except `serve` is local — no network, the database read-only —
so it may be run as often as needed, during the auction included. `asta
serve` is the one networked command: it subscribes to the FantaAstaLive
Firebase session (anonymous sign-in, read-only, exactly one subscriber,
reconnect with backoff) and serves the dashboard, the WebSocket and the
`fantaclaude-asta` MCP on localhost.

Three rules, defended hard:

- **The model changes inputs and interprets outputs; it never computes the
  number.** A max price is a band the pricer solved; "why 62 for a player I
  valued at 30?" is answered by `asta explain`, which reads the trace —
  `walk_value`, `buy_value`, the completion, the inflation — never by
  re-deriving it.
- **A fact from the room is an adjustment with a reason.** "He's limping" →
  `asta adjust --type value --player "Bastoni" --factor 0.85 --reason "limping,
  reported in the room"`. "I will not buy him" → `--type exclude`. "Go heavier
  on Dc" → `--type target --class Dc --count 4`. The file is
  `data/adjustments.yml`; it outlives the auction, and every entry says why.
- **The mirror is faithful.** The board shows what the admin recorded; a
  mistyped price is the admin's to fix, never ours. The one input the feed
  cannot supply is which team is mine (`--me`) and which dossier each rival
  maps to (`--map host=Marco`); a state file remembers them.

## Modes

### `board`

`fantaclaude asta board` — the pinned run (the newest not superseded; `--run`
to pin another; `--scenario` to price under another of its scenarios) against
`data/asta-state.json` when one exists, else an empty auction under the run's
league settings. Read: the `session:` line and any `SESSION != LEAGUE` line
(the session wins for the night; a mismatch is announced, never absorbed);
`me:` credits, picks (with the classic P/D/C/A split), what is still needed,
open slots; `board:` inflation, reserve, the completion it would buy; `room:`
per class, the ranks my squad covers over the ranks the pricer still has open
(`Por 2/2` is full, `W 0/0` has no rank at all — which is what a band of 0
means there); `block:` the classic-role block the room is calling, read off
the lot or the latest pick, and its classes, which lead the tier board;
`re-pinned:` the unsold players priced under another of their roles because
my roster covers the class the run pinned them to; `lot:` the player on the
block with his band and the pressure against him; the tier board per class
as priced; every `problem:`.

With no state file there is no session, so nothing has a label yet: `--me` and
`--map`'s key are team *numbers* there (`--me 3 --map 0=Marco`). Once a state
file exists they are labels or numbers, and it remembers both.

### `explain`

`fantaclaude asta explain "Martinez L."` (or by id) — his band, expected
price, rank weight, walk and buy values, the completion around him, the
pressure (each rival's ceiling and why), the adjustments applied to him.

### `adjust`

Resolve the player the listone's way (`"Martinez L."`, with the initial the
listone uses) or by `--player-id`; an entry that resolves to nobody is
refused, never appended. The command prints his band before and after, and
the class's top players before and after: `exclude` raises the class, `value`
moves him alone, `target` moves the composition (and says when the optimiser
departed from it).

### `replay`

`fantaclaude asta replay captured/<session>.jsonl --me Claude --map host=Marco`
— one FantaAstaLive state node per line, through the whole pipeline: per
snapshot the events (a sale, an undo, a cost edit, the lot), my credits, the
lot's band; then the final board. `--write-state` writes `data/asta-state.json`
from the last snapshot, so `asta board` then reads it. This is the rehearsal
harness: run it before the night with the capture from the rehearsal session.

### `close`

`fantaclaude asta close --session FA-xxx-xxx` — copies the state file to
`records/asta/<session>-<the state file's written_at, UTC>.json`; commit
`records/`. The name comes from the state file, not from the clock at close,
so closing twice over an unchanged state file writes one record and not two
identical ones under two names. Nothing offline knows the session code, so
pass `--session`: without it the copy is named `session-<UTC stamp>.json`,
which is a record nobody can tie to a night (and it names one file, so it may
not contain `/`). The copy is permanent; once the admin has transferred the
auction, `fantaclaude asta verify-transfer` checks the lega against it and
`--prune` removes `data/asta-state.json` alone (Phase 3a).

### `serve`

`fantaclaude asta serve --session FA-xxx-xxx` — the night's process: the
live mirror, the dashboard on http://127.0.0.1:8765, and the
`fantaclaude-asta` MCP at `/mcp/` (the trailing slash is load-bearing).
`--replay <capture> --speed N` rehearses it; `--state <file>` reviews a
finished auction. The address is fixed: there is no `--host`/`--port`. While it runs, prefer the MCP
tools (`asta_status`, `asta_board`, `asta_explain`, `asta_adjust`,
`asta_refresh`, `asta_query`) over the CLI: they read the same in-memory board the
dashboard shows. `asta adjust` from the CLI proxies to the server by
itself; a hand edit of `data/adjustments.yml` needs `asta refresh` (or the
dashboard's refresh button) to land.

## Worked example

**Ask:** "Bastoni is on the block, the room says he's limping — what do I do?"

**Good answer:** runs `fantaclaude asta board --json`, reads the lot: Bastoni
(Dc, INT) band 38/45/52, expected 40, pressure est. 47 (Marco keen up to 46);
runs `asta adjust --type value --player Bastoni --factor 0.85 --reason
"limping, reported in the room"`, reads the new band 32/38/44; tells the user
"38 is the number now, 44 at most; Marco will likely go to 46 — let him".

**Bad answer:** computes a discount by hand; edits `data/asta-state.json`;
writes "Bastoni is worth 38" into the knowledge base; connects to anything.

**Ask, with `asta serve` running:** "he's limping" (Bastoni, on the block).

**Good answer:** calls `asta_adjust {type: "value", player: "Bastoni", factor:
0.85, reason: "limping, reported in the room"}`; reads the returned
`band_after`; tells the user what moved, same as the CLI case above but
without leaving the conversation.
