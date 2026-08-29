---
updated: 2026-08-29
ttl: 30d
confidence: medium
source: admin, league.yml
---

# House rules — fantabalotelli3

What this league does that the regolamento does not decide for it. Two sources
feed this page and they are kept apart on purpose:

- **The league API** decides everything it can express — budget, squad size,
  bench, substitutions, the permitted modules, the bonus/malus table. It is
  snapshotted into `league_settings` and read as numbers, never retyped here:

  ```
  fantaclaude query --sql "SELECT * FROM v_league_settings_current"
  ```

- **`league.yml`** carries only what the API cannot express, and every leaf in
  it carries `value` / `source` / `verified_on`. A key there that duplicates an
  API value must agree with it, or `fantaclaude sync-league` exits 4. So the
  rule for this document is simple: **nothing is hardcoded here as if it were
  fixed.** Where a number belongs, a query or a `league.yml` key is named
  instead.

## The auction

The league drafts on **FantaAstaLive**, not on the Fantacalcio.it platform —
an admin decision, provenanced in `league.yml` under `auction.platform`. The
consequence for us is architectural: our own tooling never owns the auction
state, it mirrors what FantaAstaLive holds. Nothing we write is authoritative
about who bought whom.

The **auction mode is not yet known**. FantaAstaLive offers a draft and a
rilanci (open-outcry) format, and the admin has not said which; `league.yml`
records this as `unknown` rather than guessing, and the note there says to ask
when asking for the session code. This is the single most consequential open
rule for the auction strategy: a draft and a rilanci auction reward completely
different bidding behaviour, and no plan that assumes one is safe until the
admin answers.

The **date** is in `league.yml` under `auction.date`, flagged `approximate` by
the admin. Treat it as a planning horizon, not a deadline, until confirmed.

## Squad composition

Squad composition is otherwise **free**: the league does not impose a
department split (so many goalkeepers, so many defenders) beyond what the API
enforces. The one composition rule the admin stated verbally — a minimum
number of goalkeepers — is in `league.yml` under `roster.min_goalkeepers`, and
it happens to equal the API's own minimum for the goalkeeper role, which is
exactly why the cross-check in `sync-league` keeps the two from drifting apart.

Everything else about the squad — the budget, the minimum and maximum squad
size, the bench depth, how many substitutions are made — comes from the API
snapshot. Read it; do not remember it. When a rule "feels" familiar from a
previous season, that is precisely the moment to run the query.

## Scoring and modules

The bonus/malus table and the list of permitted modules are league settings,
carried in the settings payload and hashed into `rules_hash`. A change to the
hash means the admin changed a rule, and `fantaclaude doctor` will show the
settings snapshot ageing; a new `sync-league` picks up the new one. What the
roles and modules *mean* is in `kb/rules/mantra.md`.

Which voto source the league scores with is likewise a setting, not a choice
of ours — the projection reads it rather than assuming Fantacalcio's own.

## Participants

`league.yml` has a `participants` map, keyed by nickname, for the opponent
dossiers. It is empty: the dossiers are elicited conversationally in Phase 1
(`/fanta-kb interview`), and nothing should be written into it by guesswork.
The nicknames themselves are in the league settings payload, alongside the
team names, and can be listed from the snapshot.

## Watch

- The auction mode, still `unknown`. Ask the admin.
- The auction date, still `approximate`.
- Any admin message that changes a rule mid-season: the API's `rules_hash`
  moves, and this document's `ttl` is the reminder to come back and check that
  `league.yml` still agrees with it.
