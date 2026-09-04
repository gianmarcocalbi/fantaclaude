# Asta night — runbook

The whole operating procedure is: pin the run, `fantaclaude asta serve`,
open localhost, answer the mapping screen. Everything else here is the
before, the drills, and the after.

## The day before (freeze, 3 Sep)

- `fantaclaude doctor` — all green, including `dashboard` (else
  `poe web-build`) and the pinned-run checks.
- `fantaclaude rank` after the league's rules are final; commit `records/`.
  The board names its run at startup — check it is the one you mean.
- **Check `n_s` reads exactly 10 before ranking.** Team count sets the market
  (`teams x budget`) and the demand, so a run priced for eight or twelve is
  priced for an auction that will not happen. `sync-league` immediately before
  `rank`, and read the team count it prints. This is the admin's field, not
  ours: there is no override, and `sync-league` refuses rather than lets
  `league.yml` disagree with it (spec, open questions 12 and 13). Do not rank
  until it is right — and do not trust the embedded team list either, which
  reads only the first page of ten.
- **Check the composition each scenario chose lands in 25-30 players** (the
  admin's house rule, 2026-09-02). The optimiser searches the *API* bound
  (23-40), which is wider, so a legal-to-the-API composition can still break the
  house rule. The 2026-08-31 run chose 27; ten teams may move it.
- Print the tier board (`fantaclaude asta board`) — the paper backstop.
- Rehearse: `fantaclaude asta serve --replay <capture> --speed 5` and run
  the drills below. A capture with picks comes from the rehearsal itself
  (`data/raw/asta_live/…`) or from `core/tests/fixtures/asta_session_sample.jsonl`.
- **The bundled fixture is a 3-team toy.** 8 snapshots, 3 picks, 3 teams
  against an 8-team run, so it fires `SESSION != LEAGUE` and prices roughly 3x
  high — Falcone maxed 210 on it against 75 on the real board (2026-09-02).
  Use it to exercise *mechanics* — sale, cost edit, undo, lot focus — and
  never to judge a number. Drill 1 cannot be run on it at all.
- **`asta serve --replay` writes `data/asta-state.json` too**, the same as
  `--state` and `replay --write-state`: every mutation the server makes writes
  the mirror. Park a real state file before rehearsing on top of it.
- **Never run `asta replay --write-state` while a server is running**: it is a
  second writer of `data/asta-state.json` and would clobber the server's
  mirror with the replayed board. Replay through `asta serve --replay`
  instead, or stop the server first.

## Drills (each proven once before the night)

1. Exhaust a budget in replay and watch the reserve pin prices down.
   (Needs a capture that drains a budget; the bundled fixture cannot.)
2. Admin undoes a lot → the sale reverses on the board (set-diff).
3. Exclude a player mid-run → the rest of his class re-prices.
4. Hand-edit `data/adjustments.yml` → `asta refresh` (or the dashboard
   button) lands it without a restart.
5. Kill the browser, reload → the gate pre-fills, the board returns.
6. Kill the server, restart with the same source → resubscribe rebuilds the
   same board (crash recovery).
7. Drop the network mid-replay (live: the feed dot goes amber, then green).
8. Ask `fantaclaude-asta` a question while the board is live
   (`asta_board`, `asta_explain`, one `asta_query`).
9. Stop the feed and reload from the state file:
   `fantaclaude asta serve --state data/asta-state.json`.

## The night

- Get the session code from the admin (and which mode they run — DRAFT or A
  RILANCI; open question 10 says read the bid fields at the rehearsal if the
  answer is A RILANCI).
- `fantaclaude asta serve --session FA-xxx-xxx` — the run is named on the
  status line; the mapping screen asks who is who (dossiers optional, they
  feed the pressure model); SESSION ≠ LEAGUE conflicts show before bidding.
- The feed dot is always on screen: green live, amber reconnecting, red
  offline. Red with the room still bidding = the printed tier board.
- Facts from the room go in as adjustments with reasons — dashboard form,
  `asta_adjust` through Claude, or `fantaclaude asta adjust`. The mirror is
  faithful: a mistyped price is the admin's to fix.
- **Read the band the adjust prints back — it is not proportional to the
  factor.** A max price is an indifference point against the next-best
  allocation, so in a flat class a small haircut can zero a target outright:
  `Falcone --factor 0.85` moved his max 75 -> 0 and lifted the rest of the
  class (2026-09-02). A tier-1 player sitting at max 0 is normal in this
  model, not a fault.

## After

- `fantaclaude asta close` — copies the state file to `records/asta/`;
  commit `records/`. Close only once the room has stopped: the file is named
  by the state's own `written_at`, so a state that moves again closes to a
  second record rather than overwriting the first.
- The bid ladder (A RILANCI's `currentBid` nodes) lives only in the raw
  capture under `data/raw/asta_live/`, which is gitignored and ~130 MB for a
  night. Extract the distinct bids per lot into
  `records/asta/<session>-<date>-bids.json` beside the closing state (done
  by hand on 2026-09-04; worth a command).
- Drop the `value` adjustments that stood in for missing player notes before
  the board is priced on a run that has the notes: they double-count.
- The state files are **kept** until `verify-transfer` (post-auction task,
  open question 9) confirms the lega matches the room. Review any time with
  `fantaclaude asta serve --state records/asta/<file>.json` — this
  overwrites `data/asta-state.json` with the archived board, because every
  mutation the server makes writes the state file; the durable copy in
  `records/` is untouched. Accepted behaviour, not a bug, but know it before
  reviewing a past auction between now and this one.

## Rehearsal log

**2026-09-02** (replay on the bundled fixture, `--speed 20`). Proven: the
live board reproduces the committed pre-auction plan exactly on the real
8-team settings (Falcone `75 [39-97]` vs the plan's `39/75/97`, Franjic
`116`, inflation `1.73`, identical composition) — the spec's `exact`/focused
property, for the whole board and not only the focused player. Also proven:
sale, cost edit (`40 -> 45`), undo, lot focus (drill 2); an adjust re-pricing
the rest of its class (drill 3); `asta adjust` proxying to the running server
(the CLI half of drill 4); the dashboard serving; the MCP handshaking as
`fantaclaude-asta` and answering `asta_board` (the first third of drill 8).

Still unproven: **drill 1** (no capture drains a budget — `reserve 0` at full
budget is untested), **5** and **6** (need a browser), **7** (live only), the
hand-edit + `asta refresh` half of **4**, `asta_explain`/`asta_query` in
**8**, and **9** (`serve --state` was never restarted, only read).

Note: the MCP serves six tools, not the five the `fanta-asta` skill lists —
`asta_status` is the extra one.

## Auction log

**2026-09-03** (FA-rb8-460, A RILANCI, ten teams, ~20:00 to 01:20, 289
sales). The mirror held the whole night — no disconnect, every sale and cost
edit reproduced; `asta serve` was still writing the state file at close and
the record under `records/asta/` is that file. Found live and fixed on
2026-09-04: the session's `roles` pairs are `[min, max]` (the mirror collapsed
`gk [2, 4]` to two and reported a full roster as still owing a player);
multi-role players pinned to a full class sat at band 0 while another of their
roles was wanted; the board had no notion of the block being called; a class
with an open slot but no pinned player vanished from the tier board; an
adjusted player sorted by his pre-adjustment value. Found live and fixed in the
model (model 2): the appearance rate had no prior and no sample-size term, so
five two-appearance players topped the board. Confirmed: A RILANCI publishes
`currentBid` (open question 10); the room's list differs from the listone in
both directions (open question 14). The night's account is
`kb/league/season-2026-27/giornata-00-asta.md`.
