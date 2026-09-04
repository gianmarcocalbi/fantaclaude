---
updated: 2026-09-02
ttl: 30d
confidence: medium
source: "admin (2026-09-02), league.yml"
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

The **auction mode is A RILANCI** (open outcry), confirmed by the admin on
2026-09-02 and provenanced in `league.yml` under `auction.mode`. Anyone bids at
any time and the lot goes to the last offer when the countdown expires. Two
consequences for us. First, bidding is continuous rather than turn-based, so
the max price is the only number that matters in the moment — there is no turn
in which to deliberate. Second, **nothing in this repo reads a live bid**: the
board shows the modelled band and the modelled pressure (who *could* bid and
how deep), never the current offer on the table. The offer and the countdown
are read off FantaAstaLive itself; the dashboard supplies the ceiling. Whether
the shared session node even carries the live ladder is open question 10 and is
answerable only against a live rilanci session.

The **date** is in `league.yml` under `auction.date`, flagged `approximate` by
the admin. Treat it as a planning horizon, not a deadline, until confirmed.

## Squad composition

Squad composition is **free by department**: the league imposes no split
(so many defenders, so many midfielders) beyond what the API enforces. The one
department rule the admin stated verbally — a minimum number of goalkeepers —
is in `league.yml` under `roster.min_goalkeepers`, and it happens to equal the
API's own minimum for the goalkeeper role, which is exactly why the cross-check
in `sync-league` keeps the two from drifting apart.

**Squad size is a house rule narrower than the platform's.** The admin stated
on 2026-09-02: **25 to 30 players, at least 2 goalkeepers, 500 credits each.**
The API's own bound is wider (`roster_min` / `roster_max`, currently 23-40), so
the two do not agree — and that is why the house rule **cannot** be written into
`league.yml`: `roster.min_size` and `roster.max_size` are both in the
`COMPARABLE` cross-check, and a narrower value there would make
`fantaclaude sync-league` exit 4 on every run. It lives here as prose instead.

Two things follow. The optimiser searches within the *API* bound, so a
composition it proposes is only valid if it also lands inside 25-30 — the
2026-08-31 run chose 27 and does, but that is a coincidence to re-check on
every run, especially once the league reaches ten teams and the optimum moves.
And the FantaAstaLive session's own `options.bids.roles` overrides the league
on the night: the 2026-08-23 capture carried a rigid `gk [3,3] def [8,8]
mid [8,8] atk [6,6] size [25,25]`, which is **not** this rule. That capture was
a two-participant test session, so it is probably FantaAstaLive's default
rather than the admin's setup — but it must be confirmed against the real
session before bidding, because the session's numbers win.

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
dossiers. Nine were elicited on 2026-09-02 (`/fanta-kb interview`) and are
mapped there; the nicknames come from the league settings payload, never from
guesswork.

**The room is four-ninths Inter.** `Gene`, `Chuck`, `KingNazzario` and
`Fantacristo` all support Inter — the single most important structural fact
about this auction. Inter players will be bid above their worth by four
independent rivals, and the pinned run wants very few of them, so most Inter
lots are a place to let opponents drain each other rather than a place to
compete. The exceptions are the Inter players the run actually rates; check
which those are on the night rather than trusting this sentence, because the
answer moves with every run.

Two dossiers are `confidence: low` for the honest reason that the managers are
new and unobserved (`Abderrazak Hamdallah`, and `radyandre` for a different
reason — he has no pattern to encode). Both carry `budget_style: steady`, which
is the **neutral** value rather than a claim about their timing: `early` and
`hoarder` each move a rival's ceiling, `steady` does not. Read a confident-
looking pressure estimate with that in mind.

One dossier deliberately withholds a fact from the model. `CavA` supports
Juventus but historically does not buy Juventus players, so his
`favourite_clubs` is **empty**: `asta/pressure.py` treats a lot's club appearing
there as evidence a rival is keen and raises his ceiling, which for him would be
backwards. The allegiance lives in his dossier's prose instead, where it informs
a human without misleading the board.

## Watch

- **The night's session configuration.** `options.bids.roles` in the real
  FantaAstaLive session must show a 25-30 squad with a 2-goalkeeper minimum,
  not the rigid default the 2026-08-23 capture carried. The session wins on
  the night, so a mismatch re-prices the plan.
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
