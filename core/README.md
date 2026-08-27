# fantaclaude (core)

The data spine and CLI behind the Fantacalcio Mantra assistant. Design:
`docs/superpowers/specs/2026-08-22-fantaclaude-design.md`.

## Commands

Every read command takes `--json`; exit codes are a contract
(`0` ok, `1` error, `2` usage, `3` not ready, `4` league.yml conflicts with the API).

| command | does |
| --- | --- |
| `fantaclaude sync-league` | appends a `league_settings` snapshot when the rules hash moves; refuses (exit 4) if `league.yml` disagrees with the API |
| `fantaclaude ingest listone` / `ingest all` | fetches the listone into `data/raw/listone/` and snapshots it into DuckDB |
| `fantaclaude schema` | tables, views, columns — what `query` may name |
| `fantaclaude query --sql …` | read-only SQL; prefer the `v_*` views |
| `fantaclaude kb audit` | expired or malformed knowledge-base documents |
| `fantaclaude doctor` | readiness: credentials, token cache, database, snapshots, `league.yml`, `kb/`, module table |

`sync-league` and `ingest` call the live league API with the account in `.env`.
**Run them when you need fresh data, once — never in a loop.** Everything else
is local.

## Layout

`data/` (gitignored) holds `fanta.duckdb` and the immutable dated raw files;
`records/` (committed) will hold durable exports from Phase 1; `kb/` is the
knowledge base; `league.yml` carries provenanced facts the API cannot express;
`preferences.yml` the user's computation-affecting choices.

## Development

```bash
uv sync                # once, at the workspace root
uv run poe test        # both suites: mcp/fantacalcio/tests then core/tests
uv run poe lint
```

The `fantacalcio_mcp` package is imported as a library (`fantaclaude.api_client`);
its `.env`, `.auth/tokens.json` and the cross-process lock beside it are shared.
