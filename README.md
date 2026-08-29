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
- **Auction (asta)** — league rules and roster constraints tracked in `league.yml`, live league state during the draft via the MCP server
- **MCP server** — read-only league API tools (account, league settings, my team, standings, competitions, server time) exposed directly to Claude Code
- **Doctor** — one command to check credentials, snapshots, and knowledge-base health

## Layout

```
fantaclaude/
├── core/                 fantaclaude CLI — sync, ingest, query, kb audit, doctor
├── mcp/fantacalcio/      MCP server — read-only league API tools for Claude Code
├── kb/                   knowledge base — team profiles, rules, aliases, season journal
├── records/              committed exports — valuations, league_settings, auction snapshot
├── docs/                 specs and implementation plans
├── league.yml            provenanced facts the API cannot express
├── preferences.yml       computation-affecting choices
└── data/                 gitignored — fanta.duckdb and raw dated snapshots
```

## Docs

Full documentation lives at **[gianmarcocalbi.github.io/fantaclaude](https://gianmarcocalbi.github.io/fantaclaude/)**.
