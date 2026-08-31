# Asta night — runbook

The whole operating procedure is: pin the run, `fantaclaude asta serve`,
open localhost, answer the mapping screen. Everything else here is the
before, the drills, and the after.

## The day before (freeze, 3 Sep)

- `fantaclaude doctor` — all green, including `dashboard` (else
  `poe web-build`) and the pinned-run checks.
- `fantaclaude rank` after the league's rules are final; commit `records/`.
  The board names its run at startup — check it is the one you mean.
- Print the tier board (`fantaclaude asta board`) — the paper backstop.
- Rehearse: `fantaclaude asta serve --replay <capture> --speed 5` and run
  the drills below. A capture with picks comes from the rehearsal itself
  (`data/raw/asta_live/…`) or from `core/tests/fixtures/asta_session_sample.jsonl`.

## Drills (each proven once before the night)

1. Exhaust a budget in replay and watch the reserve pin prices down.
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

## After

- `fantaclaude asta close` — copies the state file to `records/asta/`;
  commit `records/`.
- The state files are **kept** until `verify-transfer` (post-auction task,
  open question 9) confirms the lega matches the room. Review any time with
  `fantaclaude asta serve --state records/asta/<file>.json` — this
  overwrites `data/asta-state.json` with the archived board, because every
  mutation the server makes writes the state file; the durable copy in
  `records/` is untouched. Accepted behaviour, not a bug, but know it before
  reviewing a past auction between now and this one.
