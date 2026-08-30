---
name: fanta-kb
description: Build and maintain the fantaclaude knowledge base under kb/ — `bootstrap` writes the rules documents and one profile per Serie A club, `refresh` renews what `fantaclaude kb audit` reports as expired, `interview` writes an opponent dossier. Use when the knowledge base is empty, stale, or a club changed coach, module or European status.
---

# fanta-kb

The knowledge base holds opinionated prose with provenance; DuckDB holds the
numbers. Every document starts with the front-matter `fantaclaude kb audit`
checks (`updated`, `ttl`, `confidence`, `source`), and a team profile adds the
keys `fantaclaude.kb.profiles` validates (`team`, `team_short`, `coach`,
`module`, `europe`, `rotation_factor`, `takers`). Discover the CLI with
`fantaclaude --help`; never parse a table out of prose you wrote.

Two rules, defended hard:

- **Prose never restates a number.** A profile says *why* a striker is
  first choice, not what he averaged; it links to a query
  (`fantaclaude query --sql "SELECT … FROM v_player_season WHERE …"`) or a
  `run_id`. A number in prose is a claim that will be wrong by November and
  nothing will catch it.
- **State what you do not know.** `confidence: low` and a short "Watch"
  section beat a confident guess; the weekly manager refuses to lean on an
  expired or low-confidence profile, which is the behaviour we want.

## Modes

### `bootstrap`

Run once, on an empty tree (Phase 0b), or to add a promoted club.

1. `fantaclaude doctor` — the listone and the calendar must be ingested; the
   `kb_profiles` check lists the clubs that still need a profile.
2. `fantaclaude query --sql "SELECT name, short FROM v_teams_current ORDER BY name" --json`
   — the clubs, spelled as the listone spells them. Never invent a club.
3. `fantaclaude query --sql "SELECT team_short, competition, count(*) AS ties FROM v_european_ties GROUP BY 1, 2" --json`
   — who plays in Europe, from the fixtures, which is what `europe:` must agree with.
4. Write `kb/rules/mantra.md` from the official regolamento
   (`https://www.fantacalcio.it/regolamenti/sistema-mantra`): the twelve
   roles and what each means on the pitch, how modules constrain the eleven,
   adaptation and the forced-substitution rule, in prose; the module table
   itself lives in `core/src/fantaclaude/model/modules.yml` and is linked,
   not copied. `ttl: never`, `source:` the URL, `confidence: high`.
5. Write `kb/rules/house-rules.md`: this league's deviations and the admin's
   verbal rules — read `league.yml` (every key carries its source) and link
   `fantaclaude query --sql "SELECT * FROM v_league_settings_current"` for
   the numbers. `ttl: 30d`, `source: admin, league.yml`.
6. For every club, research on the web (the club's site, Transfermarkt for
   the squad, two Italian outlets for the coach's habits) and write
   `kb/serie-a/teams/<slug>/profile.md` from the template below, where
   `<slug>` is `fantaclaude.kb.profiles.team_slug(name)` — lower-case ASCII,
   words joined by `-`. `team` and `team_short` are copied from step 2;
   `europe` from step 3 (`none` when the club has no ties); `rotation_factor`
   starts at `1.0` for a club without Europe, `0.9` with Champions League,
   `0.85` with Europa or Conference League, then moves for the coach (a
   rotator lower, a fixed-eleven coach higher) and squad depth — and the
   "Rotation" section says why. `ttl: 14d`, `confidence: medium` when two
   sources agree, `low` otherwise.
7. `fantaclaude kb audit` must report 0 invalid; `fantaclaude doctor` must
   report `kb_profiles` and `kb_takers` ok. `kb_takers` resolves every
   `takers:` name against the listone and names the fix for each that does
   not: several players of that surname (add the initial the listone uses),
   or a spelling the listone does not have (use the listone's). Commit the
   tree once.

### `refresh`

1. `fantaclaude kb audit --json` — the expired and invalid documents.
2. For each expired profile: re-research only what can have changed (coach,
   module, injuries that alter the pecking order, European status after a
   draw or an exit), rewrite the affected sections, bump `updated`, keep the
   rest. For an invalid one: fix the front-matter; the audit message names
   the key.
3. Never lower `ttl` to silence the audit; never touch `kb/league/season-*/`
   (the journal is append-only) or `kb/rules/aliases.yml` (that file belongs
   to ingestion).

### `interview`

Opponent dossiers, one per rival manager, elicited conversationally. Output
is `kb/league/participants/<nick>.md` in the fixed schema
`fantaclaude.kb.participants` validates, plus one line in `league.yml`.

1. `fantaclaude query --sql "SELECT payload->'teams' AS teams FROM v_league_settings_current" --json`
   — the league's team names and owner nicks (`n`, `nu`); never invent a
   nick, and never write an email address anywhere.
2. Ask, for one rival at a time, only what predicts auction behaviour: who
   they support; whether they spend early, steadily, or hoard; the roles
   they overpay and the ones they neglect; the biggest single buy you have
   seen them make, as a share of the budget; last year's regrets. Ten
   minutes per rival; stop when the answers repeat.
3. Write the dossier from the template below. Front-matter: `nick`, `team`
   (the league team name, or omit until the auction assigns one),
   `budget_style` (`early | steady | hoarder`), `favourite_clubs` (listone
   spellings), `overpays` / `avoids` (role classes: Por, Dd, Ds, Dc, E, M,
   C, W, T, A, Pc), `max_single_share` (optional, 0–1). `ttl: 90d`,
   `confidence: medium` when the user is sure, `low` when guessing.
4. Add to `league.yml` under `participants:` —
   `<nick>: {value: kb/league/participants/<nick>.md, source: interview, verified_on: <date>}`.
5. `fantaclaude kb audit` → 0 invalid; `fantaclaude doctor` → `kb_participants` ok. One commit per interview session.

Dossier template:

```markdown
---
updated: 2026-09-01
ttl: 90d
confidence: medium
source: "interview 2026-09-01"
nick: Marco
team: Sanzimippi FC
budget_style: early
favourite_clubs: [Juventus]
overpays: [Pc, A]
avoids: [Por]
max_single_share: 0.3
---

# Marco

## How he bids
Two to four sentences: when he spends, what he chases, what he never buys.

## Last year
The buys he regrets and the ones he brags about — prose, no prices.

## Watch
What would change this dossier.
```

**Ask:** "let's do the dossier for Marco." **Good answer:** lists the nicks
from the settings payload, asks the six questions in turn, writes the file
above, adds the `league.yml` line, runs `kb audit` and `doctor`, commits.
**Bad answer:** a dossier with a price table, an email address, a role
`avoids: [striker]`, or a nick the league does not have.

## Profile template

```markdown
---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: inter.it, transfermarkt.it, gazzetta.it (2026-08-29)"
team: Inter
team_short: INT
coach: <name>
module: 3-5-2
europe: UCL
rotation_factor: 0.9
takers:
  penalties: <player>          # as the listone writes him: surname first,
                               # then the initial it uses to tell two of them
                               # apart ("Martinez L.", not "Lautaro Martinez")
  corners: <player>
  free_kicks: <player>
---

# Inter — 2026-27

## Tactics
Two to five sentences: the module, the style, who is untouchable and who is
cover. No statistics — the reader can query them.

## Rotation
Why `rotation_factor` is what it is: the competition, the coach's habit,
the depth behind the starters. Name the players who lose minutes to Europe.

## Set pieces
The takers and the contested ones ("takes penalties unless X is on the pitch").

## Watch
What would change this profile — an injury, a signing, a coach on the brink.
```

## Worked example

**Ask:** "bootstrap the knowledge base".

**Good answer:** runs `doctor`, lists the 20 clubs from `v_teams_current`,
reads the European ties, writes `mantra.md` and `house-rules.md`, then
twenty profiles; for Atalanta it writes `europe: UECL`, `rotation_factor:
0.8` ("Conference League Thursdays plus a coach who rotates the front three
on principle; the back line and the keeper play everything") and lists the
penalty taker with the caveat that a January signing may take over; ends
with `kb audit` → 0 invalid and `doctor` → `kb_profiles ok`, `kb_takers ok`,
and one commit.

**Bad answer:** a profile that says "Lookman averaged 7.1 last season" (a
number, unqueryable, soon wrong), `europe: Europa` (not a valid label —
`kb audit` would have said so), or a `rotation_factor` with no "Rotation"
section explaining it.
