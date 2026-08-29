# fantaclaude

A Claude Code-native assistant for a Fantacalcio Mantra league: it ingests
the listone, historical stats, calendar fixtures and per-giornata votes into
a local DuckDB, exposes the live league through an MCP server, and keeps a
prose knowledge base — team profiles, opponent dossiers, a season journal —
for everything a table can't hold, all in service of the auction and the
season that follows it.

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
