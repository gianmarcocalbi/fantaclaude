# Records

`records/` is committed to the repository and permanent. `data/exports/` is
gitignored and disposable — it holds a rendering, rewritten by every run,
never itself the source of truth. [The data spine](../architecture/data-spine.md)
covers why the split exists; this page covers what actually lands under
`records/` and in what shape.

A valuation run writes three parquet files — the run's own row, every
player's valuation, and the price every scenario assigned — plus one more
for the league-settings row it used, keyed by its own hash. A `fantaclaude
lineup` invocation writes a forecast: published start probability, expected
score if fielded, their product, for every player the probabili page listed.
Closing an auction copies the mirrored auction state into `records/asta/`,
named by the session and the moment it closed. [Written
once](../architecture/data-spine.md#written-once) means something concrete
here: the export step checks whether the target path already exists and, if
it does, leaves it alone rather than overwriting it.

## One table, two commands

The XI actually fielded for a giornata reaches the same table by two
different paths, and the table keeps both. `fantaclaude lineup record`
writes it by hand, at submission time, when the operator confirms — with
swaps against a run, or the full eleven and bench — what they are about to
send; that row's source is `hand`. Separately, once the platform's own lock
has closed and the lineup is public, an ingest command reads it back from
the lega itself and writes a second row with source `platform`.

Neither path edits the other. Both are appends to the same table, checked
the way the platform itself would — a legal module, eleven distinct roster
players, each a fit somewhere in it — before either lands. When more than
one row exists for a giornata, the newest counts as current; nothing deletes
the older row, it simply stops being the one anything reads.

!!! note
    Records exist so a forecast **can** be checked against what actually
    happened — the two-source table above is built precisely so a fielded
    XI and a predicted one sit side by side, resolvable from committed
    files alone. Nothing in this project scores that comparison today.
    Reaching for that check is future work, not a feature this page can
    point at running.

## Named by the run, not by the clock

Every file under `records/` is named by an identifier the run itself
produced, not by the moment you happened to look. That is what a journal
entry actually links to — a `run_id`, not "the export from Tuesday" — because
the identifier is the thing guaranteed to still mean the same run a year from
now.

Naming by the run rather than the clock buys two things a clock-based name
cannot. Two invocations landing in the same second are still two distinct
files, because the run's own identifier — not the timestamp alone — makes
the name unique. And a stale or deleted rendering under `data/exports/` can
always be regenerated from the parquet in `records/` — the rendering is a
view, the parquet is the record, and only one of the two is worth
committing.

See [the CLI](cli.md) for `fantaclaude lineup`, `lineup note` and `lineup
record`, and [the skill pattern](skill-pattern.md) for why recording an XI is
a write the operator has to ask for, never one a skill infers on its own.
