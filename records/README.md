# records/

Durable, committed exports — what a journal entry links to by `run_id` must
be resolvable from here even if `data/` is lost:

- `valuation_runs/<run_id>.parquet`, `valuations/<run_id>.parquet`,
  `valuation_prices/<run_id>.parquet` — one valuation run, written by
  `fantaclaude rank`, never rewritten.
- `league_settings/<rules_hash>.parquet` — the settings row a run used.
- `asta/<session>-<UTC stamp>.json` — the auction state file as it stood when
  the auction closed, copied by `fantaclaude asta close` (`<session>` is the
  code passed as `--session`, and the literal `session` when none was; the
  stamp is the state file's own `written_at`, so closing twice over an
  unchanged file writes one record rather than two identical ones). The copy
  is permanent: `fantaclaude asta verify-transfer` checks the lega against it
  once the admin has transferred the auction, and `--prune` then removes
  `data/asta-state.json` alone, never this file (open question 9, resolved
  2026-09-04).
- `asta/<session>-<date>-bids.json` — the bid ladder of an A RILANCI night:
  every distinct `currentBid` the session published, per lot, with who won
  it and for how much, plus the status transitions. Extracted from the raw
  Firebase capture in `data/raw/asta_live/` (gitignored, ~130 MB a night)
  because the closing state alone says what was paid, never what was bid.

Everything in `data/` is gitignored and rebuildable; commit this directory
after every `rank` you intend to keep. Read them back with
`fantaclaude query --sql "SELECT * FROM read_parquet('records/valuations/<run_id>.parquet')"`.
