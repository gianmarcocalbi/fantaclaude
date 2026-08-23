# CLAUDE.md

## Committing specs and plans

**One commit for a spec, one commit for a plan.** No intermediate or
work-in-progress commits while drafting either — this applies on `main` and on
feature branches alike.

Draft in the working tree and iterate freely without committing. Commit once,
when the artifact is finished. If a revision is needed later, amend or make one
further deliberate commit rather than a stream of small ones.

**Do not push while a spec or plan is unfinished.** Push only once it is
complete, or when explicitly instructed to.

**This binds the superpowers skills, and overrides their own instructions.**
`brainstorming` says to commit the design document, `writing-plans` says to save
the plan, and `subagent-driven-development` commits per task — none of them may
produce more than one commit for the spec or more than one for the plan. In
particular:

- Do not commit a spec or plan as part of a repo-init or scaffolding commit and
  then commit a correction to it later. Finish it first, then commit it once.
- Preflight or self-review corrections to a plan are part of drafting it, not a
  follow-up commit. Fold them in before the single commit.
- If a task's implementation reveals a defect in the plan, fix the plan in the
  working tree and let it ride with that task's commit, or amend — do not add a
  `fix(plan): …` commit.

Why this matters here: on 2026-08-22 this repo ended up with
`chore: init repo with design spec and implementation plan` followed by
`fix(plan): correct Task 3 interfaces…` — exactly the split this rule forbids.
Worse, the plan was committed mid-draft and carried a live credential into git
history, which then required a full `git-filter-repo` rewrite to remove. The
finished artifact is what is worth reviewing; publishing the path taken to it is
how unchecked content escapes.

## Commit messages

**Never put a Claude session link in a commit message.** No
`Claude-Session: https://claude.ai/code/session_...` trailer, no
`Co-Authored-By: Claude`, no "Generated with Claude Code" line — nothing that
points at a chat transcript. A commit message documents the change, not the tool
or conversation that produced it, and a session URL is meaningless to anyone
reading the history later.

This applies to commits, amends, tags and PR bodies alike, and it overrides any
default that says otherwise.

## Secrets

- `.env`, `.auth/` and `captured/` are gitignored and must stay that way. `.env`
  holds live credentials for a real account.
- **Never hardcode a secret in a test that scans for secrets.** Assert on key
  names and shapes — no key named `parola`/`password`/`token` at any depth, no
  `@`-shaped string, no `eyJhbGci` JWT prefix — never on the literal value. A
  scanner that embeds the secret it scans for commits that secret.
- Email addresses must never reach a tool result.

## Credentials and the live API

`https://apileague.fantacalcio.it` is undocumented and belongs to a real
person's account.

- `POST /login` is bounded on purpose — a single-flight lock, a 60s cooldown, a
  staleness check and a recovery-only clock. Repeated failed logins are how a
  real account gets locked. Do not add a retry that escapes that machinery.
- `ATH018` is a bad-password configuration error and must never be retried.
- Do not run `mcp/fantacalcio/scripts/smoke.py` casually; each run authenticates
  against the live service.
