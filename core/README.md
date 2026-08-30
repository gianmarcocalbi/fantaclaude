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
| `fantaclaude rank [--offline] [--scenario NAME]…` | one valuation run: every listone player projected from his own history under the league's scoring, priced against the best completion of a roster whose composition the optimiser chooses; writes `valuation_runs`/`valuations`/`valuation_prices`, renders `data/exports/rankings.md`, `rankings.csv`, `asta-plan.md`, and copies the run to `records/` as parquet. Re-syncs `league_settings` first unless `--offline` |
| `fantaclaude asta board [--run ID] [--scenario NAME] [--state FILE] [--fresh] [--me TEAM] [--map TEAM=NICK]… [--top N]` | the pinned run priced against the mirrored auction (`data/asta-state.json` when it exists, else an empty auction under the run's league settings): my credits and slots, the completion, the lot on the block with its band and the pressure against it, the tier board per class |
| `fantaclaude asta explain PLAYER` | one player's trace on the current board — band, expected price, walk/buy values, the completion, the pressure, the adjustments applied to him |
| `fantaclaude asta replay FILE --me TEAM [--map TEAM=NICK]… [--write-state]` | a captured session (one FantaAstaLive state node per line) through the whole pipeline: what every snapshot moved, the final board — the rehearsal harness |
| `fantaclaude asta adjust --type value\|exclude\|target [--player NAME \| --player-id ID] [--factor F] [--class CLS --count N] --reason WHY` | append a belief to `data/adjustments.yml` and show what it moved |
| `fantaclaude asta close [--session CODE]` | copy `data/asta-state.json` to `records/asta/` when the auction closes |
| `fantaclaude doctor` | readiness: credentials, token cache, website session, database, every snapshot's coverage, `league.yml`, `kb/`, aliases, module table, the pinned run, `data/adjustments.yml`, the auction state file |

`sync-league`, `ingest` and `rank` (unless `--offline`) call the live league API with the account in `.env`.
**Run them when you need fresh data, once — never in a loop.** Everything else
is local.

Every `fantaclaude asta` command is local: it opens the database read-only and
touches no network, so it may be run freely — during the auction included.

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
giornata); `kb/` is the knowledge base -- `kb/rules/aliases.yml` is where an ambiguous
Understat name or a UEFA club spelling is resolved by hand. Adding an alias
there does not, by itself, change anything already recorded: `ingest
advanced` dedupes each season's Understat payload by its raw bytes, so a
plain re-run of an already-fetched season is a no-op regardless of the
alias -- run `fantaclaude ingest advanced --rematch` afterward (zero
network) to apply it, which is the only way to fix a back season, since its
Understat content will never change again on its own. `league.yml` carries
provenanced facts the API cannot express; `preferences.yml` the user's
computation-affecting choices. `data/exports/` holds the regenerable
renderings of the newest run; `records/` (committed) the parquet copies of
every run; `pricing.yml` the pricing knobs (they feed `model_hash`);
`data/adjustments.yml` is the auction's adjustment file — mine, hand-editable,
appended by `fantaclaude asta adjust`, every entry with a `reason`;
`data/asta-state.json` is the mirrored auction as last seen, written atomically
and never edited by hand; `records/asta/` holds its copy from `fantaclaude asta
close` until the transfer into the lega is verified;
`core/src/fantaclaude/model/d_factor.yml` the D-Factor table, empty until
the league activates the modifier and the account holder transcribes its
bands from the league's settings page.

## Development

```bash
uv sync                # once, at the workspace root
uv run poe test        # both suites: mcp/fantacalcio/tests then core/tests
uv run poe lint
```

The `fantacalcio_mcp` package is imported as a library (`fantaclaude.api_client`);
its `.env`, `.auth/tokens.json` and the cross-process lock beside it are shared.
