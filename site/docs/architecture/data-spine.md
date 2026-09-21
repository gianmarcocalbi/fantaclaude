# The data spine

Everything the system knows starts as a fetch from somewhere else — the
league API, a public stats page, a calendar. What turns that fetch into
something the engines can build on is a small set of rules about how it is
stored, applied the same way regardless of the source.

## Raw first

Every fetch is written to a dated, immutable file under `data/raw/` before
anything is derived from it. The file is created so it can never be
overwritten, and it is named by what it holds and when it was fetched, so a
directory listing says what is there without opening anything. Nothing
downstream reads the network directly — every table and view in the
database is derived from files already on disk.

That separation pays for itself the moment a source turns out to have been
misread. A player's name matched against an external stats source can be
wrong — an alias missing, a diacritic mismatched — and the fix is not a
re-fetch: it is adding the missing alias and re-deriving from the raw files
already sitting under `data/raw/`, with zero network calls. That is the only
way to correct an already-recorded season, back seasons especially. Raw-first
ingestion is what makes that correction possible at all.

## DuckDB is the derived store

Everything derived from the raw files lands in one DuckDB database. Tables
hold the facts as ingested; a layer of `v_*` views sits on top of them as
the query surface — the current league settings, the current player pool,
a player's rolling form — so that querying the system means querying a
view, not reconstructing a join across raw tables by hand. `fantaclaude
schema` lists every table and view the database holds, with its columns,
which is the map for anything read back with `fantaclaude query`.

## Committed against rebuildable

The repository draws a line between two kinds of derived data. `records/` is
committed to version control and permanent: a valuation run, the league
settings it was computed under, a lineup forecast, the XI actually fielded.
`data/` — the raw snapshots and the DuckDB database built from them — is
gitignored and rebuildable from `data/raw/`.

The split exists because a run that a journal entry or a later calibration
points at by name has to be resolvable even if `data/` is ever lost — a
machine wiped, a database file corrupted. Whatever is worth referring back to
later is copied into `records/` and committed at that moment; everything
else stays in `data/`, disposable because it can always be re-derived, and
not committed because committing it would only add churn without adding
anything that `records/` does not already guarantee.

## Written once

A run is never rewritten in place. A valuation run, a lineup forecast, a
read-back of the fielded XI — each is its own file, named by when it was
produced, and once written it is not edited or replaced. Running the same
command twice before one deadline does not overwrite the first attempt with
the second; it produces two files. That matters for a lineup forecast in
particular, because a note argued into the model partway through the week
is a legitimate reason to run again before the same deadline — the newest row
for that giornata is the one a later check would read, not the only one, and
the earlier one is not lost in order to make room for it.
