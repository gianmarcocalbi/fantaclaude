# Scope and non-goals

fantaclaude is built for one narrow job, and it stops short of several
things it could otherwise be extended to do. Each boundary below is
deliberate, not a gap waiting to be filled.

## It never writes to the platform

!!! warning
    fantaclaude never submits a lineup, a bid, or any other action to the
    league platform. The XI it recommends is typed in by hand — the
    asymmetry is deliberate: a manual entry costs about ninety seconds,
    against the risk of an automated one going wrong at 18:44 on a Friday
    and fielding a broken team with no time left to notice. The read-back
    that later checks what was actually fielded does not soften this rule: it
    is a single read of a page the league already renders, not a write in
    disguise.

## Read-only wherever it touches a live service

Every point where the system reaches a live service — the league's own API,
the auction feed, the public pages it reads for news and team form — is
read-only by construction. There is no write surface anywhere in the
codebase, and none should be added. The tools that reach these services,
covered under [Tools & patterns](../tools/mcp-servers.md), expose reading the
league, never acting on it.

## One league, one operator

fantaclaude is built around a single league and a single manager inside it.
The league's own rules are treated as configuration to be read at the start
of a run, not as an identity baked into the code, which is why nothing about
a specific league, its scoring, or the people in it is hardcoded anywhere in
the system.

## Not a general fantasy-football tool

The system solves for one Mantra league's own scoring and roster rules, not
for fantasy football as a category. Supporting another format or another
game would mean rebuilding the assumptions underneath it — how a roster is
scored, how a module is legal, how a price is formed — not flipping a
configuration setting.
