# The CLI

The reference every "Full flags" note points at: every `fantaclaude`
command, enumerated from the definitions, with the network column a fact
you can check rather than infer.

## sync-league, schema, query, kb, doctor, rank

| Command | What it does | Network |
| --- | --- | --- |
| `sync-league` | Refresh `league_settings` from the league API. Refuses (exit 4) if `league.yml` disagrees. | networked |
| `schema` | Tables, views and columns — the names `query --sql` may use. | local |
| `query --sql …` | Ad-hoc read-only SQL against the local database; prefer the `v_*` views. | local |
| `kb audit` | Knowledge-base documents expired, malformed, or missing front matter. | local |
| `doctor` | Readiness: credentials, caches, database, snapshot coverage, `league.yml`, kb, the pinned run, `adjustments.yml`, the auction state. | local |
| `rank` | One valuation run: project every player, price the board, write records and exports. Re-syncs the league unless `--offline`. | networked (`--offline`: local) |

## ingest

| Command | What it does | Network |
| --- | --- | --- |
| `ingest listone` | Fetch the listone and snapshot it. | networked |
| `ingest advanced` | Understat season totals matched onto the listone; `--rematch` re-derives from disk. | networked (`--rematch`: local) |
| `ingest calendar` | The Serie A calendar and every UEFA tie of an Italian club. | networked |
| `ingest probabili` | Published start probabilities for the next giornata. One request. | networked |
| `ingest news` | The squalificati and infortunati pages, one request each. | networked |
| `ingest rosters` | Every lega team's roster and what it paid. | networked |
| `ingest lineup` | The XI actually fielded, read back from the platform — and, once the round is calculated, the platform's own score of the match. `--from-disk` records the scores of read-backs already on disk. See below. | networked (`--from-disk`: local) |
| `ingest stats-web` | Per-giornata voti and event counts from the XLSX export; needs the website cookie. | networked |
| `ingest all` | Every source above in one pass; exit 3 if one was skipped. | networked |

`ingest lineup` refuses (exit 3) without `my_team` in `league.yml`, and
reads the competition id and its own giornata range live rather than
assuming they match the Serie A calendar. Run it once per round, in
Tuesday's refresh, when the platform has calculated the round: one read
records both the XI and the score.

## lineup

| Command | What it does | Network |
| --- | --- | --- |
| `lineup` | The giornata's forecast, and — when `league.yml` names your team — the XI and module maximizing points. | local |
| `lineup note` | Append a fact about the giornata (a start probability, factor, or exclusion) to the week's override file, with a reason. | local |
| `lineup record` | Record the XI actually fielded — the run's XI with `--swap` for deviations, or `--xi`/`--bench` in full. Appended, never edited. | local |

## calibrate

| Command | What it does | Network |
| --- | --- | --- |
| `calibrate` | Every finished giornata scored on read: the platform's score of my match beside the best eleven my roster had and the model's XI, the published start probability's reliability curve and Brier scores, the fantavoto bias per role, the page's surprises, and the platform's scores checked against the voti. `--giornata` to pick; nothing is stored. | local |

## asta

| Command | What it does | Network |
| --- | --- | --- |
| `asta board` | The pinned run priced against the mirrored auction: credits, slots, the completion, the tier board. | local |
| `asta explain` | One player's trace: band, expected price, walk/buy values, pressure, adjustments. | local |
| `asta replay` | A captured session through the whole pipeline — the rehearsal harness. | local |
| `asta adjust` | Append a belief to `data/adjustments.yml`; proxies to a running `asta serve` when one is listening. | local |
| `asta close` | Copy `data/asta-state.json` to `records/asta/` when the auction closes. | local |
| `asta verify-transfer` | Check the lega's rosters against the mirrored auction; needs `ingest rosters` first. | local |
| `asta market-prices` | What the room paid over what the run expected, per role class. | local |
| `asta refresh` | Tell a running `asta serve` to reread `adjustments.yml` and the dossiers, and re-price. | local |
| `asta serve` | Mirror the live FantaAstaLive session; serve the dashboard, WebSocket and `fantaclaude-asta` MCP. `--replay`/`--state` rehearse or review from a file, touching nothing live. | networked |

## Exit codes are a contract

The same everywhere: `0` ok, `1` error, `2` usage, `3` not ready, `4`
`league.yml` conflicts with the API. Script against these.

## Every read command takes `--json`

Every read command renders a human line by default, the same result as
JSON under `--json` — build against that, not the rendered text.

## What touches the network

Stated once:

- **Networked:** `sync-league`; every `ingest` subcommand — `listone`,
  `advanced`, `calendar`, `probabili`, `news`, `rosters`, `stats-web`,
  `lineup`, `all`; `rank` unless `--offline`; `asta serve`.
- **Local:** `schema`, `query`, `kb audit`, `doctor`, `lineup`, `lineup
  note`, `lineup record`, `calibrate`, `ingest lineup --from-disk`, and
  every `asta` subcommand except `serve` — `board`, `explain`, `replay`,
  `adjust`, `close`, `verify-transfer`, `market-prices`, `refresh`.

Everything local works against data already on disk, so it runs freely,
auction included.
