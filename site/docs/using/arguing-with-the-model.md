# Arguing with the model

Every page before this one has shown you one version of the same move:
something a run produced looked wrong, and the fix was never to touch the
output. **The model changes inputs and interprets outputs.** If you
disagree with a number, you write the fact where the code that computes it
actually reads it, and you run again.

## Every input surface, in one place

| Input | What it moves | Read by | Scope | New model? |
| --- | --- | --- | --- | --- |
| `kb` team profile | rotation, penalty takers, module, European status | valuation; the weekly engine reads it as a check | until edited | no |
| `kb` player note | one player's depth and availability | valuation; the weekly engine reads it as a check | until its TTL expires | no |
| `preferences.yml` | targets, risk appetite, scenarios | valuation | until edited | **yes** |
| `pricing.yml` | the pricer's knobs | valuation, auction | until edited | **yes** |
| `data/adjustments.yml` | one player's value, an exclusion, a target | auction | outlives the auction | no |
| `data/lineup-notes.yml` | one player's `p_start`, value or exclusion | weekly | one giornata | no |
| `league.yml` | facts the API cannot express, `my_team` | all three | until edited | no |

Two columns are worth reading twice before you write anything. **New
model?** marks `preferences.yml` and `pricing.yml` because both feed
`model_hash` — changing either one is a new model, not a tweak, and a
before/after comparison across that boundary is comparing two different
things. **Scope** marks how long a change lasts unattended: a lineup note
is inert again the moment its giornata passes, an auction adjustment sits
in its file until you remove it by hand, and a knowledge-base note expires
on its own TTL. More on the knowledge base's own document schema: Tools ›
[Knowledge base](../tools/knowledge-base.md).

## Three traps

**`rotation_factor` is not a club-wide cut.** It shifts matches *down* the
depth chart: an untouchable first choice barely notices it move, the tier
directly below him loses most of it, and the backups behind them *gain*
minutes. Lowering a club's `rotation_factor` to say "this team plays a lot
of cup football" therefore makes its fringe players **dearer**, not
cheaper — the opposite of what the number seems to suggest.

**To say "this whole squad will play less," say it per player.**
`availability` is a plain multiplier on one player's presenze. It has no
club-wide equivalent, because the model does not have a lever shaped that
way — only `rotation_factor`, which does something else entirely (above).

**A disagreement is adjudicated once, never faded twice.** When the
knowledge base and the probabili page disagree, or two sources both hint
the same way, that is one decision for you to make, not two independent
votes for a note that quietly lowers a number further each time it comes
up. Decide, write it down if it needs a note, and move on — coming back to
the same disagreement later and shading the number again is exactly the
kind of edit this whole page exists to rule out.

## Never edit an output

A ranking, a board, a lineup report, and anything already written to
`records/` are outputs. None of them is a place to make a correction by
hand, no matter how obviously wrong a single line looks — the correction
belongs in whichever input produced that line, and the run that follows is
what shows the fix actually took effect.

??? note "what ran"

    ```
    fantaclaude kb audit
    fantaclaude lineup note --type value --player "<name>" --factor <n> --reason "<why>"
    fantaclaude asta adjust --type exclude --player "<name>" --reason "<why>"
    fantaclaude rank --offline
    ```

    Full flags: Tools › [The CLI](../tools/cli.md).
