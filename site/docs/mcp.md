# The `fantacalcio-mcp` server

`fantacalcio-mcp` is a small [MCP](https://modelcontextprotocol.io) server that
gives an LLM read-only access to a Leghe Fantacalcio.it league: account details,
league settings, team rosters, and the competitions on offer. It talks to the
league's API over stdio and exposes it as a set of typed tools rather than as
raw HTTP.

It is deliberately narrow: no writes, no auction actions, nothing that could
change league state. Its only job is answering "what does the league API say
right now?" so that both a conversational assistant and fantaclaude's own
ingestion code can ask that question without duplicating the API client.

`fantaclaude` depends on it as an ordinary Python library — `core/`'s ingestion
code imports `fantacalcio_mcp.api` directly rather than spawning the MCP server
and talking to it over stdio, so there is exactly one implementation of "what
the league API looks like" in this codebase.

## The fantaclaude-asta server

`fantaclaude asta serve` runs a second MCP server, `fantaclaude-asta`, over
HTTP at `/mcp` on the same process and port as the dashboard. It is not a
separate command and not always available: it exists only while an auction
is being served, and that is correct rather than a limitation — there is no
board to answer questions about otherwise. Six tools, all reading or writing
the same in-memory board the dashboard shows:

- **`asta_status`** — the serve process's own state: phase, feed status,
  session, run, picks so far, problem count.
- **`asta_board`** — the board in summary: my ledger, every team's credits
  and slots, the lot on the block with its band and pressure, the top
  unsold players per role class, composition and inflation.
- **`asta_explain`** — one player's price from the pricer's own trace: band,
  walk/buy values, pressure, and any adjustment touching him — to read,
  never to recompute.
- **`asta_adjust`** — turns a fact from the room into an adjustment (value,
  exclude, or target) and applies it at once, through the same
  single-writer path as the dashboard form and the CLI proxy.
- **`asta_refresh`** — rereads `data/adjustments.yml` and the dossiers,
  re-prices the board, and broadcasts it — the hand-edited-file case.
- **`asta_query`** — one read-only SQL query against `fanta.duckdb`. Auction
  state is not in the database, so this is for players, history and
  valuations, not the live board.

`asta_query` is the one tool that touches the database: it opens
`fanta.duckdb` read-only, per call, inside a threadpool, so an analytical
scan never blocks the WebSocket. `.mcp.json` carries the server as
`{"type": "http", "url": "http://127.0.0.1:8765/mcp/"}` — the trailing slash
is load-bearing, because the dashboard's static mount at `/` answers a bare
`/mcp` before Starlette's redirect can. It resolves once `asta serve` is up
and answers connection refused otherwise.
