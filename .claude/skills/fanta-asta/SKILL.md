---
name: fanta-asta
description: The auction copilot's offline half with fantaclaude — read the board the pinned run gives against the mirrored auction (`asta board`), explain one price (`asta explain`), turn a fact from the room into an adjustment (`asta adjust`), rehearse on a captured session (`asta replay`), close the auction (`asta close`). Use before and during the auction, and to rehearse. The live feed, the dashboard and the MCP tools are Phase 2b and are not here yet.
---

# fanta-asta

Python does the math; this skill does the judgment. It never computes a max
price: it reads the board `fantaclaude asta board` prints, changes *inputs*
(an adjustment with a reason, a dossier, the scenario) and reads again.
Discover the CLI with `fantaclaude asta --help`; every command takes `--json`
and every one is local — no network, the database read-only — so it may be
run as often as needed, during the auction included.

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
`me:` credits, picks, what is still needed; `board:` inflation, reserve, the
completion it would buy; `lot:` the player on the block with his band and the
pressure against him; the tier board per class; every `problem:`.

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
`records/asta/<session>-<UTC stamp>.json`; commit `records/`. Nothing offline
knows the session code, so pass `--session`: without it the copy is named
`session-<UTC stamp>.json`, which is a record nobody can tie to a night. The
file is deleted only once `verify-transfer` (2b) confirms the lega.

## Worked example

**Ask:** "Bastoni is on the block, the room says he's limping — what do I do?"

**Good answer:** runs `fantaclaude asta board --json`, reads the lot: Bastoni
(Dc, INT) band 38/45/52, expected 40, pressure est. 47 (Marco keen up to 46);
runs `asta adjust --type value --player Bastoni --factor 0.85 --reason
"limping, reported in the room"`, reads the new band 32/38/44; tells the user
"38 is the number now, 44 at most; Marco will likely go to 46 — let him".

**Bad answer:** computes a discount by hand; edits `data/asta-state.json`;
writes "Bastoni is worth 38" into the knowledge base; connects to anything.
