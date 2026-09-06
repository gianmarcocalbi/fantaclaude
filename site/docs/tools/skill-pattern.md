# The skill pattern

Of everything in this repository, this is the piece most worth taking with
you. It has nothing to do with fantasy football or roster budgets — it is a
way of shaping any Claude Code skill that sits on top of a deterministic
program, and it holds regardless of what that program computes.

## Python does the math; the skill does the judgment

A skill in this project never computes a number. It runs a command, reads
what that command wrote, changes one of its *inputs*, and runs the command
again. The arithmetic — a price band, a projected score, a lineup's fit
against a module — happens once, in ordinary deterministic code; the skill's
whole contribution is deciding which input to change and why.

This is not a style preference; it is the entire design, because of what a
model-produced number costs you. A number a model states in prose cannot be
reproduced — ask again tomorrow and you may get a different one from the
same facts. It cannot be audited — there is no trace of how it was reached,
only the sentence that asserted it. And it cannot be diffed against last
week's, because there is no run behind it to diff. A number a deterministic
command writes has all three properties for free. The skill's judgment is
worth having precisely because it is judgment, not arithmetic dressed up as
one.

## Modes

Every skill in this repository takes one argument that names its mode, and
declares that shape up front with `argument-hint` in its frontmatter — a
bare call still has to do something sensible, so each skill states a
default rather than asking what you meant. `board | explain <player> |
adjust <fact> | serve` names four modes and lets a bare player name fall
through to `explain`; a bare call with nothing at all falls through to
whichever mode answers the question the moment is already implying. The
pattern generalizes past any single skill: a small, named set of verbs, one
obvious thing a bare call should do, and a hint any caller — human or model
— can read without opening the file.

## What a skill must never infer

Some things a skill here will not guess, ever, no matter how strongly the
conversation implies them — because each is a write that outlives the moment
it was made:

- **An adjustment.** Writing "he's injured, discount him" into the pricing
  model is a belief that outlives the auction it was made for.
- **Closing or pruning a record.** Ending an auction, or deleting working
  state once a transfer is verified, destroys something — a destructive
  action taken on inference is not recoverable by asking again.
- **A note's reason, or a recorded lineup's facts.** A note without a reason
  is one nobody can later explain; an XI recorded without the operator's own
  confirmation is a guess wearing the shape of a record.

Each is a write the operator has to ask for in words, not a convenience the
skill extends on its own initiative. The line is not "is this helpful" — it
almost always would be — it is "did a person actually say this, or did the
skill decide it was implied."

## Good answer, bad answer

The technique that pins this behavior down is showing the failure next to the
success, in the skill's own document, so a future run can be checked against
both. One pair, adapted from this project's auction skill, with the other
team's name replaced by a neutral label:

**Ask:** "This player is on the block, and the room says he's carrying a
knock — what do I do?"

**Good answer:** reads the board the pricing command already printed, runs
the adjustment command with a concrete factor and a written reason, reads
the new band back, and reports both numbers: "the price is now X, a rival
team is likely to go higher — let them."

**Bad answer:** computes a discount by hand and states it in prose; edits the
program's own state file directly instead of going through the command that
owns it; writes an opinion into the durable knowledge base as if it were
established fact.

The good answer never states a number the program didn't already compute; the
bad answer invents one, or reaches around the program to change state it
doesn't own. Reading the two side by side is worth more than a paragraph of
guidance: a transcript that matches the "bad" example is recognizable at a
glance in a way a description of the violation is not.

See [the ingest contract](ingest-contract.md) and [the knowledge base](knowledge-base.md)
for the two disciplines a skill here most often reads from before deciding
what to write.
