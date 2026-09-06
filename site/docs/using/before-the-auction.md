# Before the auction

The moment: the listone, the league's rules, or the knowledge base changed,
and you want a price on every player before you sit down at the auction. You
say something like "rank the listone" and `fanta-market` runs.

## Readiness first

Before anything else, run `fantaclaude doctor`. Its checks are local — no
network — and they have to be green before a run means anything: `scoring`,
`pricing`, `kb_profiles`, `kb_takers` and `kb_notes` all need to say ok, and
`valuations` tells you whether a run already exists and whether a rules
change has since superseded it.

`kb_takers` is the one worth understanding, not just clearing. It resolves
every set-piece taker a club profile names against the listone the same way
the ranker will — and it does this *before* the live re-sync, because a
taker who transferred, or whom the listone re-spelt (a "Martinez" who is now
"Martinez L."), otherwise drops his whole club back to historical penalty
splits with nothing telling you it happened. If `kb_takers` names a problem,
it also names the fix: either the profile's spelling is wrong and the
listone's is right, or the surname is shared and needs the initial the
listone uses.

Once `doctor` is clean, `fantaclaude rank` re-syncs the league's settings
from the live API and then computes entirely locally. Pass `--offline` on
any re-run that follows an edit of your own — the rules have not moved, so
there is nothing to re-sync.

## Reading what comes back

`fantaclaude rank` prices every scenario `preferences.yml` names in one run.
Read `data/exports/rankings.md` by class — the tiers, the bands, who sits
where — and `asta-plan.md` scenario by scenario.

The part worth reading most carefully is the divergence list: the players
where the model's number and the market's quotazione disagree. Every line on
it is either the edge you came for or a bug in an input, and there is no way
to tell which without reading it by hand.

## Arguing with a number

Say you think a striker the model rates highly is overrated this year, and
it turns out you know something the knowledge base does not yet. That is
the shape of the Scamacca case: the run has him tier 1 at a band of
48/55/63, his profile names him his club's penalty taker on a healthy
sample of appearances — and you know he picked up a knee knock two weeks
ago. You do not lower his number. You write a player note — `depth: starter`, `availability: 0.8`,
and a line of prose saying why — and run `fantaclaude rank --offline` again.
The band moves to 41/47/54, and you now have two run_ids: the one before
your note and the one after, both on record, so the change is a fact you can
point to rather than an edit nobody could reconstruct.

## The freeze

A run made before the auction rules and the team count are actually final
is provisional, and the report says so in plain language rather than
leaving you to guess from a date. There is no way for the code to observe
the freeze happening — that is a fact about the league, not about the
run — so treat every run before it as a draft, and re-run once it has
passed.

## Commit the run you keep

`records/` holds a permanent parquet copy of every ranking run; `rank`
writes to it every time. Once you have a run you intend to carry into the
auction, commit that copy — it is what any later reference to the run_id
resolves against, even if `data/` itself is ever lost.

??? note "what ran"

    ```
    fantaclaude doctor
    fantaclaude rank
    fantaclaude rank --offline      # after an edit of your own
    ```

    Full flags: Tools › The CLI.
