# Published docs — rework

**Date:** 2026-09-05
**Status:** Draft for review
**Scope:** the content of the mkdocs site under `site/`, restructured into four
sections; `site/mkdocs.yml` edited only where the structure requires it

## Purpose

The published site (`gianmarcocalbi.github.io/fantaclaude`) is four flat pages
written on 2026-08-29, when the project was a data spine, a CLI and one MCP
server. It has not moved since. `architecture.md` is 52 lines and predates the
dashboard (phase 2b) and the whole weekly loop (phase 3); `cli.md` describes a
command surface that `core/README.md` now documents more accurately; nothing on
the site mentions the four `fanta-*` skills, which are how the project is
actually operated.

This replaces the site's information architecture and rewrites every page. Four
sections, in this order:

1. **What it is** — functional, by capability and outcome.
2. **Architecture** — technical.
3. **Using fantaclaude** — the season phase by phase, through the skills.
4. **Tools & patterns** — the reusable pieces, the MCP servers among them.

`docs/superpowers/` is unaffected: it holds specs and plans for working *with
Claude* on this repo and is never scanned by mkdocs, which resolves `docs_dir`
relative to `site/mkdocs.yml`.

## Decisions taken

Recorded here because each one closes an alternative that would otherwise be
reopened during implementation.

| Decision | Chosen | Rejected |
| --- | --- | --- |
| Audience | Layered — §1–2 public, §3–4 operator | One voice throughout |
| Shape | Four folders, each an `index.md` plus children | Four long pages; a hybrid |
| Usage style | Conversation first, commands in a collapsed block beneath | Pure conversation; commands first |
| Architecture depth | Mechanism plus the vocabulary the tools print | Mechanism only; full formulas and constants |
| `docs/asta-night-runbook.md` | Stays private; the site's auction-night page is the narrative and links to it | Folding it in; publishing it as-is |
| Formatting | A small set of `markdown_extensions` (no plugin, no new dependency) | Callouts only; plain CommonMark |

No mkdocs plugin is added. `mkdocs-material` is already a dev dependency and it
ships `pymdown-extensions`; everything below is configuration.

## Structure

```
site/docs/
  index.md                            §1 overview  (also the site root)
  what-it-is/
    capabilities.md
    scope.md
  architecture/
    index.md
    data-spine.md
    rules-as-data.md
    valuation.md
    weekly.md
    auction-engine.md
  using/
    index.md
    before-the-auction.md
    auction-night.md
    the-week.md
    arguing-with-the-model.md
  tools/
    index.md
    mcp-servers.md
    cli.md
    ingest-contract.md
    knowledge-base.md
    skill-pattern.md
    records.md
```

21 pages, 300–800 words each. `index.md` is both the site root and §1's landing
page, so §1 has no folder of its own for its overview; its two children live
under `what-it-is/`.

`navigation.indexes` makes each folder's `index.md` the page its tab lands on.
Without it a tab click expands the section without opening anything, and the
four `index.md` files become unreachable except from the sidebar.

§1 is shaped differently from the other three and it is deliberate: its landing
page is `site/docs/index.md`, the site root, while its two children live under
`what-it-is/`. `nav:` binds them into one section explicitly —

```yaml
- What it is:
    - index.md
    - what-it-is/capabilities.md
    - what-it-is/scope.md
```

— so the first tab and the site's home page are the same document. Do **not**
create `what-it-is/index.md`: that would give the section its own landing page
and leave `index.md` as a second, orphaned root.

## Content

### §1 What it is — public, functional

**`index.md`** — what fantaclaude is in a paragraph: a Claude Code-native
assistant for one Fantacalcio Mantra league, where Python does the math and the
model does the judgment. The season arc as a mermaid diagram (build the
knowledge base → value the listone → the auction → the weekly loop, repeating).
Links into the other three sections. No commands.

**`capabilities.md`** — what it can do, stated as outcomes rather than
commands, and not one command named:

- know the league's own rules, as the league currently states them;
- value every player in the listone under those rules, and price a whole roster
  rather than a list of players;
- price a live auction as it happens, against the room's remaining credits;
- pick a legal XI every week, with the bench in the platform's order, a
  contingency for every doubtful starter, and the close calls named;
- hold opinionated prose with provenance and an expiry date;
- answer questions about the live league, read-only.

**`scope.md`** — non-goals, each with its reason:

- it never writes to the platform — the XI is typed by hand, against a bug at
  18:44 on a Friday;
- read-only wherever it touches a live service, with no write surface anywhere
  in the codebase;
- one league, one operator; the league's rules are configuration, not identity;
- not a general fantasy-football tool.

### §2 Architecture — public, technical

**`index.md`** — the whole system in one mermaid diagram: sources → ingest →
DuckDB → the three engines (valuation, weekly, auction) → the four surfaces
(CLI, MCP, dashboard, skills). Plus the two-package uv workspace (`core/` =
`fantaclaude`, `mcp/fantacalcio/` = `fantacalcio_mcp`) and why `core` imports
the MCP package as a library: exactly one copy of "what the league API looks
like".

**`data-spine.md`** — raw-first ingestion (every fetch lands in a dated
snapshot under `data/raw/` before anything is derived, so re-derivation needs
zero network — `ingest advanced --rematch` is the worked case), DuckDB as the
derived store, the `v_*` views as the query surface, and the split between what
is committed (`records/`) and what is rebuildable (`data/`). The immutability
rule: a run is written once and never rewritten.

**`rules-as-data.md`** — league rules are mutable and therefore ingested:
`league_settings` snapshots, `rules_hash`, `league.yml` for the provenanced
facts the API cannot express, and the refusal (exit 4) when the two disagree
rather than a silent merge. `d_factor.yml` is read off the league's own
settings page and never filled from memory. Why every valuation is stamped with
the rules in force when it was computed.

**`valuation.md`** — projection → price. Each listone player projected from his
own history under the league's scoring; the pricer solving for the best
*completion* of a roster rather than ranking players independently;
`walk_value` against `buy_value`; `expected_price` and the band around it;
`inflation` and the `reserve`; tiers by the largest gaps within a class;
scenarios from `preferences.yml`; `rank_weight`. `model_hash` as the identity of
a model, and the rule that a change in `pricing.yml` or `preferences.yml` is a
new model, not a tweak. Names the knobs and the files; states no values.

**`weekly.md`** — the giornata forecast. `p_start` by precedence — a note, else
a squalifica from the news pages, else the published number — and the sources
that only ever disagree out loud (the knowledge base, the infortunati list, a
European week). The matchup term, shrunk and capped; `fv_sd` pooled with the
role prior. Expected points as the product. The exact XI solve per permitted
module; the bench in the platform's order with its `coverage` and what it
cannot cover; the `contingencies` by re-solve; the close calls. Per-player
deadlines: a prediction is late against its own kickoff, the XI against the
first. `weekly_hash`.

**`auction-engine.md`** — the single-writer process. The mermaid version of the
diagram already in today's `architecture.md`: the feed, `adjustments.yml` and
the dossiers, and the dashboard/CLI/MCP surfaces all converging on
`AstaServer._mutate_and_write` before anything is broadcast. The mirror is
faithful — the board shows what the admin recorded, and a mistyped price is the
admin's to fix. Pressure per rival. Re-pinning a multi-role player to the class
the roster still has ranks open for. Why auction state is not in the database,
and why `asta_query` therefore opens `fanta.duckdb` read-only per call.

### §3 Using fantaclaude — operator, skills first

Every page in this section follows one shape: the moment in the season, what
you say to Claude, which skill answers and in which mode, what comes back and
how to read it, and what to do with it. Beneath each, a collapsed
`??? note "what ran"` block naming the commands, so the page stays usable when
something breaks. Full flags live in `tools/cli.md`, linked once per page.

**`index.md`** — the switch of address stated in the first sentence. The season
end to end as a timeline: build the knowledge base → rank → the freeze → the
auction → verify the transfer → the weekly loop, every giornata. Which skill
owns which moment (`fanta-kb`, `fanta-market`, `fanta-asta`, `fanta-manager`),
and the rule that spans all four: you change inputs; the model never edits an
output.

**`before-the-auction.md`** — `fanta-kb` (`bootstrap`, `refresh`, `interview`)
and `fanta-market` (`rank`, `plan`). Running `doctor` first and what each check
gates. Reading `rankings.md` by class and `asta-plan.md` by scenario, and the
divergence list as the place where the model disagrees with the market — each
line either the edge or a bug, read by hand. Arguing: a player note, a team
profile, `preferences.yml`; re-running `--offline`; comparing the two run_ids;
committing `records/` with the run you intend to keep. The freeze, and why a run
before it is provisional.

**`auction-night.md`** — `fanta-asta`. Starting `serve` and answering the
mapping screen before the board exists. Reading the board section by section
(`me`, `board`, `room`, `block`, `re-pinned`, `lot`, the tier board, every
`problem`). `explain` for one price. `adjust` as a fact from the room with a
reason, never a number computed by hand. The dashboard, and preferring the MCP
tools while the server runs because they read the same in-memory board. `close`,
then `verify-transfer` once the admin has transferred, then `market-prices`.
Links to `docs/asta-night-runbook.md` for the drills and the pre-flight
checklist, which stay private.

**`the-week.md`** — `fanta-manager`. Tuesday's `refresh` (the finished
giornata's voti, the probabili and news pages, an early forecast so calibration
has a point per player). Friday's `lineup`, read top to bottom, with what each
band of the report means and which warnings are adjudicated rather than
absorbed. Notes as the only way to move a number. The hand submission. `record`
immediately after, because that is what calibration scores.

**`arguing-with-the-model.md`** — the cross-cutting page, and new. One table of
every input surface: a `kb` team profile, a `kb` player note, `preferences.yml`,
`pricing.yml`, `data/adjustments.yml`, `data/lineup-notes.yml`, `league.yml` —
what each one moves, which engine reads it, whether it is durable or scoped to
one giornata, and whether changing it is a new model. Then the traps, stated
plainly: `rotation_factor` is not a club-wide cut but a shift down the depth
chart, so lowering it makes a club's fringe players dearer; `availability` is
the per-player multiplier that says "this squad will play less"; a
disagreement is adjudicated once and never faded twice. Closes with the rule
the whole project rests on — never edit an output.

### §4 Tools & patterns — operator, liftable first

**`index.md`** — what in here is liftable into another project (the standalone
MCP server, the ingest contract, the knowledge-base pattern, the skill pattern)
and what is a component of this one (the CLI, the session-scoped MCP, the
records format).

**`mcp-servers.md`** — two servers, deliberately different. `fantacalcio-mcp`:
standalone, read-only, stdio, seven tools over a private Leghe Fantacalcio.it
league, and also imported by `core/` as an ordinary library so there is one API
client rather than two. `fantaclaude-asta`: session-scoped, HTTP at `/mcp/` on
the same process and port as the dashboard, six tools over the live board, only
existing while an auction is served — and why that is correct rather than a
limitation. The trailing slash in `.mcp.json` is load-bearing and the reason is
stated.

**`cli.md`** — the full reference by group (`sync-league`, `ingest`, `schema`,
`query`, `kb`, `doctor`, `rank`, `lineup`, `asta`), each command one row: what
it does, and whether it touches the network. Exit codes as a contract (0 ok,
1 error, 2 usage, 3 not ready, 4 `league.yml` conflicts with the API). `--json`
on every read command. The section ends with the network split stated once as a
list, because it is the fact most worth being able to check quickly.

**`ingest-contract.md`** — polite by construction: one request at a time, a
pause between pages, no retries, named hosts, and the standing rule against
fetching "to check" or during a match. Raw-first, so a fix to an alias
re-derives offline. The bounded login — single-flight lock, cooldown,
staleness check, recovery-only clock — and why a retry that escapes it locks a
real account. Written so someone could adopt the discipline without this
codebase.

**`knowledge-base.md`** — prose with provenance for a model to read. The
front-matter contract (`updated`, `ttl`, `confidence`, `source`, plus the
profile keys), `fantaclaude kb audit` reporting what expired, the tree
(`rules/`, `serie-a/teams/`, `league/`), aliases as the one place a name is
reconciled, and the rule that carries the whole idea: prose never restates a
number — it links a query or a `run_id`.

**`skill-pattern.md`** — Python does the math; the skill does the judgment. A
skill runs a deterministic CLI, reads what it wrote, changes an input, and runs
it again; it never computes the number. Modes named by the argument, with an
`argument-hint` and a stated default for a bare call. What a skill must never
infer, and why each one is on that list (`adjust` writes a belief that outlives
the auction; `close` and `verify-transfer --prune` end or delete the night's
record; `note` and `record` need a reason or a fact only the operator has). The
good-answer/bad-answer pair as a technique for pinning behaviour.

**`records.md`** — `records/` is committed and permanent; `data/exports/` is a
rendering and gitignored. What a valuation run writes as parquet, what a lineup
run and a recorded XI write, what `asta close` copies. Naming by `run_id` and
why the identifier — not the rendering — is the record a journal entry links.
Never rewritten, and what that buys.

## Content rules

These bind every page and are the reason the site can be trusted after the code
moves again.

**Voice.** §1–2 third person, present tense, no "you" — a stranger evaluating
the project. §3–4 second person, imperative where it is a procedure. §3's
`index.md` states the switch in its first sentence. Throughout, the repo's own
voice — concrete, unhedged, no marketing — matching `CLAUDE.md` and the skills
rather than a product page.

**The privacy boundary.** The site is public.

- No league name, no league id, no participant nicknames. Nothing from
  `kb/league/` — dossiers, journal and history are all out.
- Nothing from `captured/`, from `data/`, or from the contents of `records/`.
- `.env` keys may be named as required settings; no value is ever shown.
- Real Serie A player names are fine — public players, public data. Rivals are
  anonymised: "a rival", "team 3", "the admin".

**Example output reuses the skills' own worked examples** — the Scamacca
re-rank, the Bastoni adjustment, the giornata-4 XI — rather than inventing new
ones or pasting a real run. They are already written, already public-safe, and
reusing them keeps the site and the skills saying the same thing. The single
rival name occurring in them becomes a neutral label.

**Prose never restates a number.** The rule `kb/` already enforces, applied to
the docs: no coefficient tables copied out of `pricing.yml`, `preferences.yml`
or `d_factor.yml`. Name the knob, name the file, let the file be the source.
This is the one rule that keeps these pages from being wrong the day a knob is
tuned.

**Network honesty.** Any page naming a command says whether it touches a live
service. `tools/cli.md` carries the split as a column; elsewhere it is a
warning admonition where it matters.

**One canonical home per fact.** Cross-link rather than repeat — the
single-writer diagram lives in `architecture/auction-engine.md` and
`using/auction-night.md` links to it. `--strict` turning a broken link into a
build failure is what makes this enforceable across 21 pages.

**Written from the code, not from the current pages.** `architecture.md` is
52 lines and predates phases 2b and 3; `cli.md` is behind `core/README.md`.
Both are source material to check against, not to paraphrase.

## Configuration

Three edits to `site/mkdocs.yml`. No plugin, no new dependency.

```yaml
theme:
  features:
    - navigation.tabs        # already present
    - navigation.top         # already present
    - navigation.indexes     # add — a tab lands on its folder's index.md
    - content.code.copy      # add
    - search.suggest         # already present

markdown_extensions:         # the file currently has none
  - admonition
  - attr_list
  - md_in_html
  - toc:
      permalink: true
  - pymdownx.details
  - pymdownx.tabbed:
      alternate_style: true      # see the note below
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
```

`nav:` is rewritten to the four sections, listing all 21 pages — `--strict`
fails on any page absent from it.

`navigation.indexes` is required by the structure, not cosmetic: without it a
tab click expands its section without opening a page, and the four `index.md`
files are reachable only from the sidebar.

`pymdownx.tabbed` has exactly one intended use: the two tool tables in
`tools/mcp-servers.md`, one tab per server. It is the only extension in the set
without a use on every page, so the rule is — if that page reads better as two
plain headed subsections while it is being written, the extension comes out of
`mkdocs.yml` in the same change. An enabled extension nothing uses is config
debt.

`site_name`, `site_url`, `repo_url`, `site_dir` and the palette are untouched.

## Files

- Rewritten: `site/docs/index.md`.
- Deleted: `site/docs/architecture.md`, `site/docs/cli.md`, `site/docs/mcp.md` —
  their content is redistributed, not carried over.
- Added: the 18 remaining pages listed under **Structure**.
- Edited: `site/mkdocs.yml`.

`/architecture/`, `/cli/` and `/mcp/` stop resolving. Accepted rather than
redirected: the only referrer is the root `README.md`, which links the site
root.

## Testing

- `uv run poe docs-build` — `mkdocs build --strict` is the pass/fail gate. Under
  `--strict` a page missing from `nav`, a broken internal link and a bad anchor
  are all build failures. There is no unit suite for markdown; this is the
  correctness signal.
- `uv run poe docs-serve`, then read all four tabs. Two things `--strict`
  cannot catch and a human must:
  - **the mermaid diagrams must actually render.** A misconfigured custom fence
    shows them as code blocks, silently and successfully.
  - **each tab must land on its `index.md`**, which verifies
    `navigation.indexes` took.
- A privacy pass over the diff before the commit: grep the added pages for the
  league name, the league id, every participant nickname, and any `@`-shaped
  string. No page may reference `captured/`, `.env` values, or `kb/league/`
  content.

CI needs no change: `.github/workflows/docs.yml` already triggers on
`push` to `main` with `paths: ["site/**"]`.

## Out of scope

- Theme and palette work, a dark-mode toggle included.
- `docs/asta-night-runbook.md` — stays private, linked from
  `using/auction-night.md`.
- `docs/superpowers/`.
- The root `README.md`. Once §1 is the canonical functional description,
  README's `## Capabilities` block is a second copy of it that will drift.
  Leaving it is defensible — it is accurate today — but shrinking it to a pitch
  plus a link would be cheap. That is a separate, deliberate change after the
  site lands, not part of this one.
