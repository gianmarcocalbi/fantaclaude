# fantaclaude

A Claude Code-native assistant for a Fantacalcio Mantra league: it ingests
the listone, historical stats, calendar fixtures and per-giornata votes into
a local DuckDB, exposes the live league through an MCP server, and keeps a
prose knowledge base — team profiles, opponent dossiers, a season journal —
for everything a table can't hold, all in service of the auction and the
season that follows it.

## Capabilities

- **Ingestion** — listone, Understat history, Serie A/UEFA calendar, per-giornata votes, the probabili formazioni page (public), the lega's rosters and purchase prices — all deduped and re-runnable
- **Valuation** — projections and auction-ready pricing over the ingested history
- **Knowledge base (kb)** — team profiles, opponent dossiers, house rules, and a season journal, with front-matter TTLs and an audit for what's gone stale
- **Auction (asta)** — `fantaclaude asta board|explain|replay|adjust|close|verify-transfer|market-prices`: the pinned valuation run priced against the auction as last mirrored — the session's bounds read as ranges, every multi-role player re-pinned to the class my roster still has ranks open for, the room per class, the block the room is calling — one player's trace, a rehearsal over a captured session, an adjustment with its reason, and the closing copy into `records/`, the lega checked against the room by roster overlap, and what the room paid over what the run expected, per class. All local — the database read-only, no network
- **Auction night** — `fantaclaude asta serve` mirrors the FantaAstaLive
  session over its Firebase feed and serves the live dashboard, the
  WebSocket and the `fantaclaude-asta` MCP from one localhost process;
  the board re-prices on every sale, adjustments land from the dashboard,
  the CLI or Claude through one path, and `--replay` rehearses the whole
  night from a captured session.
- **Weekly (lineup)** — `fantaclaude lineup`: the giornata's forecast for every player the probabili page lists (p_start by precedence, a `lineup note`, else a squalifica from the news pages, else the published number; the KB, the infortunati list and a European week only ever disagree out loud), a small matchup term and a spread, each prediction honest against its player's own kickoff and never revised — and, once `league.yml` names `my_team`, the XI and module that maximise expected points (an exact solve per permitted module), the bench in the platform's order with what it cannot cover, a re-solve for every doubtful starter and the close calls. `lineup note` writes a fact with its reason; `lineup record` writes the XI actually fielded; `ingest news` reads the two public lists, matched by name within the club
- **MCP server** — read-only league API tools (account, league settings, my team, standings, competitions, server time) exposed directly to Claude Code
- **Doctor** — one command to check credentials, snapshots, and knowledge-base health

## Layout

```
fantaclaude/
├── core/                 fantaclaude CLI — sync, ingest, query, kb audit, rank, lineup, asta, doctor
│   └── src/fantaclaude/api/  FastAPI: REST + WebSocket + the MCP mount, served by `asta serve`
├── mcp/fantacalcio/      MCP server — read-only league API tools for Claude Code
├── web/                  the Vite/React dashboard `asta serve` builds and mounts
├── kb/                   knowledge base — team profiles, rules, aliases, season journal
├── records/              committed exports — valuations, league_settings, lineup_runs, lineup_submitted, predictions, asta/ state files and bid ladders
├── docs/                 specs and implementation plans
├── league.yml            provenanced facts the API cannot express
├── preferences.yml       computation-affecting choices
├── pricing.yml           the pricing knobs (they feed model_hash)
└── data/                 gitignored — fanta.duckdb, raw dated snapshots
                          (raw/probabili, raw/news and raw/rosters among them),
                          adjustments.yml (my auction beliefs) and lineup-notes.yml
                          (my facts for the week), both hand-editable,
                          and asta-state.json (the mirrored auction)
```

## Docs

Full documentation lives at **[gianmarcocalbi.github.io/fantaclaude](https://gianmarcocalbi.github.io/fantaclaude/)**.
