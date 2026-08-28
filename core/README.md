# fantaclaude (core)

The data spine and CLI behind the Fantacalcio Mantra assistant. Design:
`docs/superpowers/specs/2026-08-22-fantaclaude-design.md`.

## Commands

Every read command takes `--json`; exit codes are a contract
(`0` ok, `1` error, `2` usage, `3` not ready, `4` league.yml conflicts with the API).

| command | does |
| --- | --- |
| `fantaclaude sync-league` | appends a `league_settings` snapshot when the rules hash moves; refuses (exit 4) if `league.yml` disagrees with the API |
| `fantaclaude ingest listone` | the listone through the league API → `data/raw/listone/`, `players` |
| `fantaclaude ingest advanced [--season N]… [--rematch]` | Understat season totals (games, minutes, xG, xA) matched onto listone ids → `advanced_stats`; ambiguous and unmatched names are reported, never dropped; `--rematch` re-derives from the raw files already on disk (zero network) after an alias is added -- the only way to fix an already-recorded season, back seasons especially |
| `fantaclaude ingest calendar [--competition …]…` | the current season's Serie A giornate (fantacalcio.it) and every UEFA tie of an Italian club → `fixtures`, `v_european_ties` |
| `fantaclaude ingest stats-web [--season N]… [--giornata N]… [--refetch]` | per-giornata voti and event counts from the XLSX export → `player_match`, `v_player_season`, `v_player_form`; needs the website session below |
| `fantaclaude ingest all` | every source above; exit 3 if one had to be skipped |
| `fantaclaude schema` | tables, views, columns — what `query` may name |
| `fantaclaude query --sql …` | read-only SQL; prefer the `v_*` views |
| `fantaclaude kb audit` | expired or malformed knowledge-base documents |
| `fantaclaude doctor` | readiness: credentials, token cache, website session, database, every snapshot's coverage, `league.yml`, `kb/`, aliases, module table |

`sync-league` and `ingest` call the live league API with the account in `.env`.
**Run them when you need fresh data, once — never in a loop.** Everything else
is local.

`ingest advanced`, `ingest calendar` and `ingest stats-web` read public web
hosts (Understat, fantacalcio.it, UEFA) one request at a time with a one-second
pause between pages and an honest `User-Agent`. Run them when data is needed,
not to check whether anything changed: an unchanged source is reported as a
duplicate and costs the host a request all the same.

## The website session

The voti export (`/api/v1/Excel/votes/<season>/<giornata>`) is behind the
fantacalcio.it *website* login — a different session from the league API's.
Nothing in this repository logs in to it. The account holder logs in once in
their own browser, copies the `Cookie` request header of the Excel download
from the developer tools, and puts it in `.env`:

    FANTACALCIO_WEB_COOKIE="name=value; name2=value2"

`fantaclaude doctor` reports whether it is set, never its value; `ingest
stats-web` exits 3 with a re-capture hint when the site rejects it. Names,
lifetime and the workbook layout are recorded in the design spec, open
question 5.

## Layout

`data/` (gitignored) holds `fanta.duckdb` and the immutable dated raw files;
`data/raw/` holds `listone/`, `advanced/`, `calendar/` (one HTML page per
giornata, one JSON page per UEFA competition) and `voti/` (one workbook per
giornata); `records/` (committed) will hold durable exports from Phase 1;
`kb/` is the knowledge base -- `kb/rules/aliases.yml` is where an ambiguous
Understat name or a UEFA club spelling is resolved by hand. Adding an alias
there does not, by itself, change anything already recorded: `ingest
advanced` dedupes each season's Understat payload by its raw bytes, so a
plain re-run of an already-fetched season is a no-op regardless of the
alias -- run `fantaclaude ingest advanced --rematch` afterward (zero
network) to apply it, which is the only way to fix a back season, since its
Understat content will never change again on its own. `league.yml` carries
provenanced facts the API cannot express; `preferences.yml` the user's
computation-affecting choices.

## Development

```bash
uv sync                # once, at the workspace root
uv run poe test        # both suites: mcp/fantacalcio/tests then core/tests
uv run poe lint
```

The `fantacalcio_mcp` package is imported as a library (`fantaclaude.api_client`);
its `.env`, `.auth/tokens.json` and the cross-process lock beside it are shared.
