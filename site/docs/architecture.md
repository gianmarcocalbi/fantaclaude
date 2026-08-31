# Architecture

## A two-package uv workspace

fantaclaude is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
with two packages sharing one lockfile and one virtual environment:

| Package | Import name | Responsibility |
| --- | --- | --- |
| `core/` | `fantaclaude` | The assistant itself: data spine, ingestion, knowledge base, CLI |
| `mcp/fantacalcio/` | `fantacalcio_mcp` | A read-only MCP server over the league's live API |

`fantaclaude` depends on `fantacalcio-mcp` as a library — it calls the API client
directly rather than going through a second network hop, so there is exactly one
copy of "what the league API looks like" in the codebase.

## The data spine

League data — the player list ("listone"), statistics, and knowledge-base facts —
is ingested from a handful of sources (the league API, public web stats, manually
curated club notes) into a local store, rather than queried live on every
question. This keeps day-to-day questions ("who scored last week?", "what's this
player's role?") fast and offline, and keeps a record of what was known and when.

## League configuration is data, not constants

A league's rules — how many participants, the budget, which formations are legal,
how scoring works — are **mutable**: they can change between seasons and even
mid-season. Nothing in fantaclaude hardcodes them. They are ingested, versioned,
and read at run time exactly like player statistics, because every valuation
depends on the rules that were in force when it was computed.

## The live auction

`fantaclaude asta serve` is one process with one owner of state. Every
source of change converges on `AstaServer` before anything is broadcast:

```
FantaAstaLive → Firebase → SSE → ingest.asta_live ─┐
        adjustments.yml + dossiers (refresh) ──────┼→ AstaServer._mutate_and_write → state file
              dashboard form / CLI / MCP tool ─────┘   → recompute board → WebSocket
```

A feed snapshot, an adjustment from any surface, and a refresh all pass
through the same lock and the same worker thread, re-derive the board, write
`data/asta-state.json` atomically, and broadcast to every open WebSocket —
so no state change can escape the broadcast, whether it originated with the
admin two seats away or with a CLI command typed mid-auction. The dashboard
(Vite/React, `web/`), the REST API, the WebSocket and the `fantaclaude-asta`
MCP are one FastAPI process on one port; `asta_query` is the one path back
into `fanta.duckdb`, opened read-only per call, because auction state itself
never lives in the database.
