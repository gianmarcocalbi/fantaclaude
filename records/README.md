# records/

Durable, committed exports — what a journal entry links to by `run_id` must
be resolvable from here even if `data/` is lost:

- `valuation_runs/<run_id>.parquet`, `valuations/<run_id>.parquet`,
  `valuation_prices/<run_id>.parquet` — one valuation run, written by
  `fantaclaude rank`, never rewritten.
- `league_settings/<rules_hash>.parquet` — the settings row a run used.
- the auction snapshot between the auction and the confirmed transfer into
  the lega (Phase 2).

Everything in `data/` is gitignored and rebuildable; commit this directory
after every `rank` you intend to keep. Read them back with
`fantaclaude query --sql "SELECT * FROM read_parquet('records/valuations/<run_id>.parquet')"`.
