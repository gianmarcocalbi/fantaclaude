# The `fantaclaude` CLI

The `fantaclaude` command wraps the assistant's day-to-day, non-conversational
work: pulling data in, building the knowledge base. Four groups of commands:

## `fantaclaude sync-league`

Pulls the current state of the league — settings, roster composition rules,
teams — from the live league API into the local data spine.

## `fantaclaude ingest`

Brings outside data into the data spine: the player list from the league API,
and statistics and advanced metrics from public web sources. Web ingestion is
deliberately polite — one request at a time, paced, no retries — because it reads
hosts fantaclaude doesn't control.

## `fantaclaude kb`

`fantaclaude kb audit` reports which knowledge-base documents under `kb/` have
gone stale — for example a club changed coach, formation, or European
competition status. It does not build or refresh anything itself; that work is
done by the `fanta-kb` Claude skill, using the audit's report to decide what
needs renewing.

## `fantaclaude asta`

The auction core, offline: `asta board` prices the newest valuation run
against the auction as last mirrored (or an empty one), `asta explain` reads
one player's trace, `asta replay` runs a captured FantaAstaLive session
through the whole pipeline as a rehearsal, `asta adjust` appends a belief —
a value factor, an exclusion, a target composition — and shows what it moved,
and `asta close` copies the state file to `records/` when the auction ends.
The live feed and the dashboard that sit on top of these are Phase 2b.

Each command only touches the network when it says so in its name —
`sync-league` and `ingest` call live services; everything else in the CLI,
`asta` included, works against data already on disk.
