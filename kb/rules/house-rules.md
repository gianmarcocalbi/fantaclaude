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

The voto source is `calculate.sourcev` in the settings payload; `fantaclaude
doctor` prints the sheet it resolves to (`1 → Fantacalcio` is the working
hypothesis, checked by the account holder against the league's calcolo page
— see "Watch"). The Mantra defence modifier is the **D-Factor**; its
thresholds are league data read off the league's settings page and kept in
`core/src/fantaclaude/model/d_factor.yml` with a date. While it is inactive
(every `smod*` field null) nothing is applied; if any other modifier is
switched on, `fantaclaude rank` refuses rather than price a rule it does not
model.

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
- **Open since 2026-08-29, unanswered — the voto source.** Only the account
  holder can check this: Leghe → *fantabalotelli3* → Impostazioni → Calcolo,
  the "Fonte voti" field. Expected to read **Fantacalcio** (the Redazione
  votes). If it reads Statistico or Italia instead, `VOTO_SOURCES` in
  `core/src/fantaclaude/model/scoring.py` maps `1` wrongly and must be
  swapped to what the page shows, with the date noted in the docstring, then
  `fantaclaude rank` re-run.
- **Open since 2026-08-29, unanswered — the D-Factor / modifiers.** Only the
  account holder can check this: the same settings area (Modificatori).
  Expected: every modifier off, which is what `doctor`'s `scoring` line
  currently reports. If the admin ever switches the D-Factor on,
  `fantaclaude sync-league` will show which `calculate.*` key moved (expected
  `smodd`; if a different key moves, set `D_FACTOR_KEY` in `model/scoring.py`
  to it and note the date), then the modifier's table must be transcribed
  into `core/src/fantaclaude/model/d_factor.yml` (`bands`, `with_goalkeeper`,
  `source`, `verified_on`). Watch this transcription step: the bands'
  `points` must **increase** with `floor`. Nothing validates this at load —
  `load_d_factor` checks only that the floors are numeric and unique — and a
  non-monotonic table silently yields a clamped-to-zero uplift instead of the
  intended one, so a transcription slip fails quietly rather than loudly.
