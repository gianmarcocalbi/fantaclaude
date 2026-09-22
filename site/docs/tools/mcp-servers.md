# MCP servers

fantaclaude exposes two Model Context Protocol servers to Claude, and they are
deliberately different in almost every way that matters: lifetime, transport,
and what they let you touch. One is a standalone, read-only window onto your
league that exists whenever you configure it. The other exists only for the
span of one auction, because there is no board to answer questions about
otherwise. Knowing which one you are talking to — and why it is shaped the
way it is — is most of what you need to use either well.

## fantacalcio-mcp

This server talks to the real Leghe Fantacalcio.it API over stdio, as a
standalone process Claude Code launches per `.mcp.json`. Every tool is
read-only, and every tool is scoped to your signed-in account's league; you
only pass a `league` alias if that account belongs to more than one.

It exposes exactly eight tools:

- **`get_account`** — your account's id and username, and every league it
  belongs to. The natural first call when you need a league alias.
- **`get_league`** — one league's identity (name, id, alias, founding year,
  president, admins, team count) and its live status (season, matchday,
  kickoff time).
- **`get_league_settings`** — roster budget and size limits, lineup rules
  (bench size, allowed formations), substitutions allowed, and the
  bonus/malus point table.
- **`get_my_team`** — your own team: name, division, credits, roster
  composition by role, co-managers.
- **`list_teams`** — every team in the league with its managers, credits and
  division; optionally the pending, unaccepted invitations too. This is a
  team list, not a standings table — there is no league table or fixtures
  tool anywhere in this server.
- **`list_competitions`** — the competitions configured in the league.
- **`get_server_time`** — Fantacalcio's own server clock, for reasoning about
  a deadline relative to a matchday's kickoff.
- **`get_lineup`** — the XI both sides fielded for one match, module and
  ordered bench included, read the way the lega's own formazioni page reads
  it.

`core` imports this server's package as an ordinary library rather than
spawning it as a subprocess, so the CLI and this MCP server share one API
client instead of running two independent ones against the same account.

## Resolving a matchday

`get_lineup` is worth its own section because the number you give it is not
the number the platform actually keys the match by. A competition has its
own round number, `matchDay`; the Serie A calendar has its own
`championshipMatchDay`. These are different numbers, and neither derives from
the other — a *calendario* competition's round one can be championship
matchday three, with no arithmetic that gets you from one to the other. Worse,
more than one of a competition's own rounds can share the same championship
matchday (a recovery round, a doubleheader), so resolving a match means
checking every round at that championship matchday for the team you asked
about, rather than assuming the first match is the right one.

That resolver is pure data logic — no HTTP, no MCP framework — living in the
`fantacalcio-mcp` package rather than in `core`. `core`'s own lineup ingestion
imports it from there rather than keeping a second copy of the same matching
loop, which is the dependency direction made visible: `core` depends on this
MCP package, never the other way around.

!!! warning
    No email address reaches the result of any of these eight tools. It is
    an invariant over the whole server, not a special case handled only
    where a payload happens to carry one. The scrub is two-pronged:
    every email-bearing key is dropped at any depth of the result, and every
    value shaped like an email address is redacted regardless of the
    (possibly innocuous) key it sits under — because a free-text field can
    carry an address a key-only scrub would never catch.

## fantaclaude-asta

The second server is nothing like the first. It is session-scoped, served
over HTTP, and mounted at `/mcp/` on the same process and the same port as
the auction dashboard — not a separate process, so its six tools read the
same in-memory board the dashboard is showing at that instant. It exists
only while `asta serve` is running an auction; there is no board to answer
questions about otherwise, so that is correct behavior, not a limitation
to work around.

The trailing slash in `.mcp.json`'s URL for this server is load-bearing, not
a stylistic choice. The dashboard mounts a static file server at `/` that
answers a bare `/mcp` itself before the redirect to `/mcp/` ever gets a
chance to fire — so a client configured without the trailing slash silently
talks to the wrong thing.
