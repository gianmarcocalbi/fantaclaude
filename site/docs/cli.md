# The `fantaclaude` CLI

The `fantaclaude` command wraps the assistant's day-to-day, non-conversational
work: pulling data in, building the knowledge base. Five groups of commands:

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

## `fantaclaude lineup`

The weekly loop. `fantaclaude lineup` writes the giornata's forecast — every
player the probabili page lists, p_start by precedence, an XI when
`league.yml` names my team, the bench, the contingencies, the close calls —
immutably, each prediction against its player's own kickoff. `lineup note`
appends a fact for the week with its reason; `lineup record` appends the XI
actually fielded. `ingest news` reads the squalificati/diffidati and
infortunati lists beside `ingest probabili`. All local except the two ingests,
which are one polite request per page.

## `fantaclaude asta`

The auction core: `asta board` prices the newest valuation run against the
auction as last mirrored (or an empty one), `asta explain` reads one
player's trace, `asta replay` runs a captured FantaAstaLive session through
the whole pipeline as a rehearsal, `asta adjust` appends a belief — a value
factor, an exclusion, a target composition — and shows what it moved, and
`asta close` copies the state file to `records/` when the auction ends.

`asta serve` is the auction-night process. It has three sources — `--session
FA-xxx-xxx` for the live FantaAstaLive feed over Firebase, `--replay <capture>
--speed N` to rehearse from a captured session, `--state <file>` to review a
finished one (`data/asta-state.json`, or an archived copy under
`records/asta/`) — and exactly one must be given: with no source at all it
prompts for a session code, because that is what auction night is. One process
serves all of it: the dashboard at `/`, the REST API under `/api`, the
WebSocket at `/ws`, and the `fantaclaude-asta` MCP at `/mcp/`, all on
`127.0.0.1:8765` — one address, with no `--host`/`--port` to move it. That is
deliberate: the number has to agree in `.mcp.json`, in the CLI's `--server`
default, and in the dashboard's dev proxy, and a flag is the only thing that
could make them disagree — which breaks the MCP, the `asta adjust` proxy and
`poe web-dev` at once, silently. Serving the room over the LAN is a spec
non-goal. The first thing it asks, live or replayed, is the mapping screen —
who is mine (`--me`), which dossier each rival maps to (`--map team=nick`) —
before the board exists; giving either flag on the command line answers the
screen against the first snapshot, and a pair the session cannot satisfy says
so on the screen rather than being dropped. Live mode captures every feed node to
`data/raw/asta_live/<code>-<UTC date>.jsonl` unless `--no-capture` is given;
capture is the rehearsal's own source material for the next one.

`asta refresh` is server-only: it tells a running `asta serve` to reread
`data/adjustments.yml` and the dossiers and re-price the board, for the
hand-edited-file case — offline boards recompute on every command anyway, so
there is nothing to refresh without a server. `asta adjust` proxies to a
running server when one is listening, since while `asta serve` runs it is
the one writer of `data/adjustments.yml`; with nothing listening it falls
back to writing the file itself, exactly as it always did.

Each command only touches the network when it says so in its name —
`sync-league`, `ingest` and `asta serve` call live services (the last one
read-only, to FantaAstaLive's Firebase session); everything else in the CLI,
`asta` included, works against data already on disk.
