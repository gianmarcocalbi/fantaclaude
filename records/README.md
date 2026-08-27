# records/

Durable, committed exports: parquet copies of `valuations` and `league_settings`
(from Phase 1), and the auction snapshot between the auction and the confirmed
transfer into the lega. Everything in `data/` is gitignored and rebuildable;
what a journal entry links to by `run_id` must be resolvable from here.
