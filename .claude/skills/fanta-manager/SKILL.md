---
name: fanta-manager
description: The weekly loop with fantaclaude — `refresh` early in the week (the finished giornata's voti, the probabili and news pages), `lineup` before the lock (`fantaclaude lineup`, read top to bottom, argue with a `lineup note`, re-run), `note` for a fact from the week, `record` for the XI actually fielded. Use every giornata, from the Tuesday refresh to the Friday XI; never to submit, never to fetch "to check".
---

# fanta-manager

Python does the math; this skill does the judgment. It never computes a
p_start, a bench order or an expected score: it runs `fantaclaude lineup`,
reads what the run wrote, changes *inputs* (a note with a reason) and reads
again. Discover the CLI with `fantaclaude lineup --help` and
`fantaclaude ingest --help`; every command takes `--json`; `lineup`, `lineup
note` and `lineup record` are local (no network), the `ingest` commands are
the only fetches and each one is a single polite request per page.

Four rules, defended hard:

- **Change inputs, never outputs.** The number is a precedence the code
  applies — a note, else a squalifica, else the page — and everything else
  is a check that names a disagreement. To move a number, write the fact
  where the code reads it: `fantaclaude lineup note --type p_start --player
  "Kean" --p-start 0 --reason "out, club statement"`; `--type value --factor
  0.85` for a knock or a position change; `--type exclude` to keep him off
  the XI and the bench this week. Every note carries the giornata and a
  reason; `data/lineup-notes.yml` is the record.
- **A disagreement is adjudicated, never faded twice.** `warning:
  disagreement: …` lines are the infortunati list, the KB note or a European
  tie disagreeing with the page. The page's compilers usually already know
  what those sources know. Decide — a note, or nothing — and say which in the
  conversation; never lower a number because two sources hint the same way.
- **Never submit, never write to the platform.** The XI goes on the
  platform by hand (Non-goals): ninety seconds of typing, against a bug at
  18:44 on a Friday. Then `fantaclaude lineup record` writes what was
  fielded, and that record is what calibration scores.
- **Fetch at the two moments, not "to check".** `ingest probabili` and
  `ingest news` run in `refresh` and in `lineup`, and at most once more
  before a later kickoff day of the same round. `ingest stats-web` runs once,
  for the finished giornata. `ingest rosters` runs only when the operator
  says the lega changed. Never during a match.

## Modes

### `refresh` — early in the week (Tuesday)

1. `fantaclaude ingest stats-web --giornata <the finished giornata>` — the
   voti; needs `FANTACALCIO_WEB_COOKIE`. If it reports "not yet rated", stop
   and try again later in the day; do not loop.
2. `fantaclaude ingest probabili` then `fantaclaude ingest news` — one request
   each (news is two). Read the `unmatched` count: a name the listone does not
   resolve is `fantaclaude query --sql "SELECT * FROM v_unavailable_current
   WHERE player_id IS NULL"`, and the fix is an alias in
   `kb/rules/aliases.yml` under `fantacalcio_teams` (a club) or a spelling the
   listone uses (a player) — never a guess in the adapter.
3. `fantaclaude lineup` — Tuesday's forecast, so calibration has an early
   point per player (each prediction is honest against its own kickoff).
   Read every `warning:` and every `disagreement:`; write the notes that are
   already known (a suspension the page still prices, a confirmed absence).
4. `fantaclaude kb audit` and `fantaclaude doctor` — expired profiles and
   notes, the `lineup_notes` check. An unwritten journal entry for the
   finished giornata is a notice, not a refusal (the draft is 3c's).
5. `fantaclaude ingest rosters` only if told the lega changed (a trade, a
   free agent). Never to check.

### `lineup` — before the lock (Friday)

1. `fantaclaude ingest probabili` and `fantaclaude ingest news` once more.
2. `fantaclaude lineup`. Read it top to bottom:
   - the header: the deadline, the run, the page's stamp and how many
     matches are compiled; `LATE XI` means the lock has passed and only the
     rows for matches not yet started are honest;
   - `UNCOMPILED` and the per-match staleness warnings: a Tuesday
     compilation for a Sunday match is a number to distrust, not to use;
   - `blend:` how many p_start came from the page, a note, a squalifica; the
     news pages' stamps; the weekly hash;
   - every `warning: disagreement:` — adjudicate;
   - `XI:` the module and the eleven, `other modules:` what the rejected
     ones scored;
   - `bench:` in the platform's order, `[roles]` and the coverage value; `!`
     after a name is a diffidato (a yellow this week is a suspension next
     week — his call, not the model's); `uncovered:` a slot the bench cannot
     legally fill, which the platform's own algorithm will then fill by
     changing the module or adapting someone;
   - `if out:` for each doubtful starter, who enters and what it costs — the
     re-solve, ready before the news lands;
   - `close:` the slots decided by less than the margin, with each side's
     spread and where its number came from (`published vs note` says the
     call turned on something the operator wrote).
3. Argue with it through notes, re-run, read again. Then the operator
   submits on the platform by hand.
4. `fantaclaude lineup record` — the XI as fielded: the run's, with
   `--swap "Out=In"` for every deviation, or `--xi` and `--bench` in full.
   Run it right after submitting, while the round is the target.

### `note`

`fantaclaude lineup note --type p_start|value|exclude --player "<listone
spelling>" [--p-start 0..1 | --factor (0,2]] --reason "<why>" [--giornata N]`
— resolved against the listone, refused when nobody matches (add the
initial the listone uses). A note is for one giornata; next week it is
inert and stays in the file. The command prints the entry and the count;
re-run `fantaclaude lineup` to see what moved.

### `record`

`fantaclaude lineup record [--lineup-run <id>] [--swap Out=In ...] [--module
<code>] [--xi "a,b,..." --bench "c,d,..."] [--giornata N]` — appended, never
edited; the newest per giornata is current. After the round, pass
`--giornata` (the target has moved on).

## Worked example

**Ask:** "Friday, giornata 4 — what do I field?"

**Good answer:** runs `ingest probabili` and `ingest news` once each, then
`fantaclaude lineup --json`; reads: page compiled 10/10 at 11:05, blend
published 471 · squalificato 2, one disagreement (Ederson at 90% in a
Conference week, the season rate under rotation expects 63%); asks the
operator, who knows Gasperini rested him on Thursday — no note; XI 3-5-1-1,
bench Svilar first, uncovered none; `if out: Kean (55%) -> Hojlund at Pc,
-1.4`; close call at W/A by 0.2 with a wider spread on the man left out.
Tells the operator the eleven, the bench order, and what to do if Kean is
out; the operator submits; runs `fantaclaude lineup record`.

**Bad answer:** multiplies Ederson's 90% by the rotation factor; edits
`records/`; fetches the probabili page again "to see if it changed";
submits anything anywhere.
