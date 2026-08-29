# The `fantaclaude` CLI

The `fantaclaude` command wraps the assistant's day-to-day, non-conversational
work: pulling data in, building the knowledge base. Three groups of commands:

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

Each command only touches the network when it says so in its name —
`sync-league` and `ingest` call live services; everything else in the CLI works
against data already on disk.
