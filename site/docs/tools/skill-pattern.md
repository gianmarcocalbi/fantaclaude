# The skill pattern

Of everything in this repository, this is the piece most worth taking with
you. It has nothing to do with fantasy football — it is a way of shaping any
Claude Code skill that sits on a deterministic program, and it holds
regardless of what that program computes.

## Python does the math; the skill does the judgment

A skill in this project never computes a number. It runs a command, reads
what that command wrote, changes one of its *inputs*, and runs the command
again. The arithmetic happens once, in ordinary deterministic code; the
skill's whole contribution is deciding which input to change and why.

This is not a style preference; it is the entire design, because of what a
model-produced number costs you. A number a model states in prose cannot be
reproduced — ask again tomorrow and you may get a different one from the
same facts. It cannot be audited — there is no trace of how it was reached,
only the sentence that asserted it. And it cannot be diffed against last
week's, since there is no run behind it. A deterministic command's output has
all three properties for free; the skill's judgment is worth having
precisely because it is judgment, not arithmetic dressed up as one.

## Modes

Every skill in this repository takes one argument that names its mode, and
declares that shape up front with `argument-hint` in its frontmatter — a
bare call still has to do something sensible, so each skill states a
default. `board | explain <player> | adjust <fact> | serve` names four
modes and lets a bare player name fall through to `explain`; a bare call
with nothing at all falls through to whichever mode answers the question
the moment already implies. The pattern generalizes past any single skill: a
small, named set of verbs, one obvious default, and a hint any caller —
human or model — can read without opening the file.

## What a skill must never infer

Some things a skill here will not guess, ever, no matter how strongly the
conversation implies them — because each is a write that outlives the moment
it was made:

- **An adjustment.** "He's injured, discount him" is a belief that outlives
  the auction it was made for.
- **Closing or pruning a record.** Ending an auction, or deleting working
  state once a transfer is verified, destroys something — not recoverable by
  asking again.
- **A note's reason, or a recorded lineup's facts.** A note without a reason
  is one nobody can later explain; an XI recorded without the operator's own
  confirmation is a guess wearing the shape of a record.

Each is a write the operator has to ask for in words, not a convenience the
skill extends on its own initiative. The line is not "is this helpful," it
is "did a person actually say this."

## Good answer, bad answer

The technique that pins this down is showing the failure next to the
success, in the skill's own document. One pair, adapted from this project's
auction skill, with the rival's name replaced by a neutral label ([Auction
night](../using/auction-night.md) walks it end to end):

**Ask:** "Bastoni is on the block, and the room says he's limping — what do I
do?"

**Good answer:** runs `fantaclaude asta board --json`, reads the lot —
Bastoni, band 38/45/52, expected 40, pressure estimate 47, a rival keen up to
46 — then runs `fantaclaude asta adjust --type value --player Bastoni
--factor 0.85 --reason "limping, reported in the room"`, reads the new band
back — 32/38/44 — and reports it plainly: "38 is the number now, 44 at
most; that rival will likely go to 46 — let them."

**Bad answer:** computes a discount by hand instead of running the
adjustment; edits `data/asta-state.json` directly instead of going through
the command that owns it; writes "Bastoni is worth 38" into the knowledge
base as settled fact.

The good answer never states a number `asta board` or `asta adjust` didn't
already print — 38, 44, 46 and 47 all came from the tool, not from arithmetic
done in the model's head. The bad answer's sharpest failure isn't the
hand-computed discount, it's the third clause: writing "38" into the
knowledge base as a fact instead of a number a query can reproduce is exactly
what [the knowledge base](knowledge-base.md)'s rule — prose never restates a
number — exists to catch. Reading the two side by side is worth more than a
paragraph of guidance: a transcript that matches the "bad" example is
recognizable at a glance in a way a description of the violation is not.

See [the ingest contract](ingest-contract.md) and [the knowledge
base](knowledge-base.md) for the disciplines a skill here reads before
deciding what to write.
