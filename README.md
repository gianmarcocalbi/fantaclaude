# fantaclaude

A Claude Code-native assistant for a Fantacalcio Mantra league: it ingests
the listone, historical stats, calendar fixtures and per-giornata votes into
a local DuckDB, exposes the live league through an MCP server, and keeps a
prose knowledge base — team profiles, opponent dossiers, a season journal —
for everything a table can't hold, all in service of the auction and the
season that follows it.

## Capabilities

- **Ingestion** — listone, Understat history, Serie A/UEFA calendar, per-giornata votes, all deduped and re-runnable
- **Valuation** — projections and auction-ready pricing over the ingested history
- **Knowledge base (kb)** — team profiles, opponent dossiers, house rules, and a season journal, with front-matter TTLs and an audit for what's gone stale
- **Auction (asta)** — `fantaclaude asta board|explain|replay|adjust|close`: the pinned valuation run priced against the auction as last mirrored — the session's bounds read as ranges, every multi-role player re-pinned to the class my roster still has ranks open for, the room per class, the block the room is calling — one player's trace, a rehearsal over a captured session, an adjustment with its reason, and the closing copy into `records/`. All local — the database read-only, no network
- **Auction night** — `fantaclaude asta serve` mirrors the FantaAstaLive
  session over its Firebase feed and serves the live dashboard, the
  WebSocket and the `fantaclaude-asta` MCP from one localhost process;
  the board re-prices on every sale, adjustments land from the dashboard,
  the CLI or Claude through one path, and `--replay` rehearses the whole
  night from a captured session.
- **MCP server** — read-only league API tools (account, league settings, my team, standings, competitions, server time) exposed directly to Claude Code
- **Doctor** — one command to check credentials, snapshots, and knowledge-base health

## Layout

```
fantaclaude/
├── core/                 fantaclaude CLI — sync, ingest, query, kb audit, rank, asta, doctor
│   └── src/fantaclaude/api/  FastAPI: REST + WebSocket + the MCP mount, served by `asta serve`
├── mcp/fantacalcio/      MCP server — read-only league API tools for Claude Code
├── web/                  the Vite/React dashboard `asta serve` builds and mounts
├── kb/                   knowledge base — team profiles, rules, aliases, season journal
├── records/              committed exports — valuations, league_settings, asta/ state files
├── docs/                 specs and implementation plans
├── league.yml            provenanced facts the API cannot express
├── preferences.yml       computation-affecting choices
├── pricing.yml           the pricing knobs (they feed model_hash)
└── data/                 gitignored — fanta.duckdb, raw dated snapshots,
                          adjustments.yml (my auction beliefs, hand-editable)
                          and asta-state.json (the mirrored auction)
```

## Docs

Full documentation lives at **[gianmarcocalbi.github.io/fantaclaude](https://gianmarcocalbi.github.io/fantaclaude/)**.
