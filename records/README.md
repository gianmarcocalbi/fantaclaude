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
  unchanged file writes one record rather than two identical ones); it and
  `data/asta-state.json` are deleted only once `verify-transfer` (a
  post-auction task, open question 9) confirms the lega matches the room.

Everything in `data/` is gitignored and rebuildable; commit this directory
after every `rank` you intend to keep. Read them back with
`fantaclaude query --sql "SELECT * FROM read_parquet('records/valuations/<run_id>.parquet')"`.
