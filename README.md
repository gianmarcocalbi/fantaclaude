# fantaclaudio

Personal assistant for a Fantacalcio Mantra auction and season. It ingests
player lists, historical stats, calendar fixtures and per-giornata votes
into a local DuckDB, surfaces the data to Claude Code through an MCP server,
and keeps a prose knowledge base of team profiles, opponent dossiers, and
league journal entries that no table can hold.

## Layout

```
core/              fantaclaude CLI — sync, ingest, query, kb audit, doctor
mcp/fantacalcio/   MCP server — read-only league API tools for Claude Code
kb/                knowledge base — team profiles, rules, aliases, season journal
records/           committed exports — valuations, league_settings, auction snapshot
docs/              specs and implementation plans
league.yml         provenanced facts the API cannot express (auction date, roster rules…)
preferences.yml    computation-affecting choices (scoring weights, projection params)
data/              gitignored — fanta.duckdb and raw dated snapshots
```

## Quick start

```bash
uv sync             # once, at the workspace root — creates .venv
uv run poe test     # both suites (no network)
uv run poe lint
```

The MCP server (`mcp/fantacalcio/`) is registered via `.mcp.json`; Claude Code
picks it up automatically when the workspace root is open.

## Docs

| Document | What it covers |
| --- | --- |
| [`docs/superpowers/specs/2026-08-22-fantaclaude-design.md`](docs/superpowers/specs/2026-08-22-fantaclaude-design.md) | Full system design — data model, CLI contract, knowledge-base schema, Phase 0–1 scope |
| [`docs/superpowers/specs/2026-08-22-fantacalcio-mcp-design.md`](docs/superpowers/specs/2026-08-22-fantacalcio-mcp-design.md) | MCP server design — auth machinery, tools, error contract |
| [`docs/superpowers/specs/2026-08-28-fantaclaude-phase-0b-history.md`](docs/superpowers/specs/2026-08-28-fantaclaude-phase-0b-history.md) | Phase 0b spec — history adapters, name matching, knowledge-base contracts |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Implementation plans per phase |
| [`core/README.md`](core/README.md) | CLI command reference and ingestion rules |
| [`mcp/fantacalcio/README.md`](mcp/fantacalcio/README.md) | MCP server setup, auth modes, tool list, smoke test |
| [`kb/README.md`](kb/README.md) | Knowledge-base structure and front-matter contract |
| [`records/README.md`](records/README.md) | What lives in `records/` and why |
