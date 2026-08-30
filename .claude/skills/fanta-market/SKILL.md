---
name: fanta-market
description: Pre-auction analysis with fantaclaude — run `fantaclaude rank`, read the rankings and the asta plan, argue with the model on the user's behalf (a note, a taker, a rotation factor, a preference) and re-run under stated constraints. Use before the auction, whenever the listone, the rules or the knowledge base changed, and to draft the auction's journal entry.
---

# fanta-market

Python does the math; this skill does the judgment. It never computes a
value, a price or a tier itself — it runs `fantaclaude rank`, reads what the
run wrote, and changes *inputs* (a note, a profile, a preference) when it has
a reason to. Discover the CLI with `fantaclaude --help`; every read command
takes `--json`.

Three rules, defended hard:

- **The run_id is the record.** `data/exports/` is a rendering; `records/`
  holds the parquet copy; the journal links the run_id and restates no
  number. A run before the freeze is provisional and the report says so.
- **Change inputs, never outputs.** If the model likes a player the
  knowledge base doubts, write the doubt where the model reads it — a
  player note (`depth`, `availability`), a team profile (`rotation_factor`,
  `takers`), `preferences.yml` — and re-run. Never edit a ranking by hand.
- **The quotazione is a price.** The divergence list in `asta-plan.md` is
  where we disagree with the market: each line is either the edge or a bug,
  and it is read by hand before the auction.

## Modes

### `rank`

1. `fantaclaude doctor` — `scoring`, `pricing`, `kb_profiles`, `kb_takers`,
   `kb_notes` must be ok (`kb_takers` catches, before the re-sync, the taker
   who transferred or whom the listone re-spelt — otherwise his whole club
   quietly falls back to historical penalty splits); `valuations` says
   whether a run exists and whether a rules change superseded it.
2. `fantaclaude rank` — re-syncs the league first (one API call set; pass
   `--offline` when re-running after an edit of your own, since the rules
   did not change). Read the status line: the composition per scenario,
   the inflation, the reserve, any `departed from the target`, every
   `warning:` (a club without a profile, a penalty taker the warning
   could not resolve — it says which way: not how the listone spells him
   (fix the profile's spelling to the listone's) or several players of
   that surname (add the initial the listone uses) — then re-run).
3. Read the freeze status from `freeze`, never by parsing the prose.
   `--json` carries `provisional` (always true — the freeze is what makes a
   run final and the CLI cannot see the freeze), `note` (the same sentence
   the plain output prints, for a human), `auction_date`,
   `days_to_auction` (negative once the date is past),
   `auction_passed`, `inside_pre_freeze_window`, `pre_freeze_window_days`,
   `teams_present` and `teams_expected` (null when league.yml has no
   `team_count` leaf). Compare the numbers; do not regex "in 2 days" or
   "8 of 10 expected teams" out of `note`.
4. Read `data/exports/rankings.md` by class and `asta-plan.md` by scenario.
   For any surprise, read the trace rather than guessing:
   `fantaclaude query --sql "SELECT name, explain FROM v_valuations_current WHERE player_id = <id>" --json`
   and
   `fantaclaude query --sql "SELECT scenario, explain FROM v_valuation_prices_current WHERE player_id = <id>" --json`.
5. Argue. "It likes him, but the profile says he is cover" → write the
   note (`kb/serie-a/teams/<slug>/players/<name>.md`, front-matter
   `player_id`, `name`, `team_short`, `depth`, `availability`; prose says
   why; `ttl: 7d`), re-run with `--offline`, compare the two run_ids.
6. Commit `records/` with the run you intend to keep.

### `plan`

Draft `kb/league/season-2026-27/giornata-00-asta.md` (front-matter as any
kb document; `ttl: never`): the run_id, the scenario chosen and why, the
three or four calls you expect to be close, what would change your mind.
No number tables — link the run_id and the query that reproduces any number.

## Worked example

**Ask:** "rank the listone; I think Scamacca is overrated this year."

**Good answer:** runs `doctor` (all ok, `valuations` not yet), runs
`fantaclaude rank`, reports "run 20260903T101500Z-…, 553 players, balanced:
inflation 1.18, composition Por 2·9, Dc 3·61, … , reserve 6; provisional,
auction in 2 days"; reads `rankings.md` for Pc and sees Scamacca tier 1 with
max 48/55/63; queries his `explain` — `rate_source history`, 31 presenze
weighted, `penalties_per_presenza 0.16` because Atalanta's profile names him
taker; asks what the doubt is; the user says a knee; writes
`kb/serie-a/teams/atalanta/players/scamacca.md` with `availability: 0.8`,
`depth: starter`, prose "knee flagged 2 Sep, two weeks of doubt", re-runs
with `--offline`, reports the new band (41/47/54) and both run_ids; commits
`records/`.

**Bad answer:** edits `rankings.md`; writes "Scamacca averaged 7.1" into a
kb document; re-runs without `--offline` five times "to check"; treats a
run made before the freeze as final.
