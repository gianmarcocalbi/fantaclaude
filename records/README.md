# records/

Durable, committed exports — what a journal entry links to by `run_id` must
be resolvable from here even if `data/` is lost:

- `valuation_runs/<run_id>.parquet`, `valuations/<run_id>.parquet`,
  `valuation_prices/<run_id>.parquet` — one valuation run, written by
  `fantaclaude rank`, never rewritten.
- `league_settings/<rules_hash>.parquet` — the settings row a run used.
- `lineup_runs/<season>-<giornata>-<UTC stamp>-<lineup_run_id>.parquet` and
  `predictions/<same stem>.parquet` — one `fantaclaude lineup` invocation:
  the forecast it wrote (published `p_start`, expected fantavoto if he
  plays, their product) for every player the probabili page listed and the
  run priced, the deadline it was written against, whether it was late, and
  the XI and module when one was named. Never rewritten; several
  invocations before one deadline are several files, and calibration reads
  the latest non-late one per giornata. The `lineup_run_id` suffix is there
  because the UTC stamp alone is second-precision: two invocations in the
  same second are two immutable rows and must be two files, not one
  silently skipped as "already exists" (older committed files predate the
  suffix and are not renamed — the stem shape is not itself meaningful,
  only that it names one run without collision).
- `lineup_submitted/<season>-<giornata>-<UTC stamp>-<submitted_id>.parquet` — the
  XI actually fielded for that giornata, as `fantaclaude lineup record` wrote
  it by hand (source `hand`) or `fantaclaude ingest lineup` read it back from
  the platform (source `platform`), with the run it came from where one
  applies. Never rewritten; the newest per giornata is the one calibration
  scores my own week against.
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
