# The ingest contract

## Two kinds of ingest

Everything `fantaclaude ingest` fetches falls into one of two disciplines, and
they are not interchangeable. One set of sources is public web hosts you have
no relationship with beyond being a polite reader; getting that wrong means
annoying a webmaster. The other is a real person's account on fantacalcio.it's
private league API; getting that wrong means a locked account. The code
treats them differently on purpose, and if you adapt either discipline
elsewhere, keep them separate there too.

## Against public web hosts

`ingest advanced`, `ingest calendar`, `ingest probabili`, `ingest news` and
`ingest stats-web` read fantacalcio.it's own public pages, Understat and
UEFA's match feed. All five go through one HTTP layer built around a single
client, a single honest `User-Agent` string, and one error vocabulary: an
expired website session, a resource not published yet, and anything else,
mapped so the caller can act on each differently instead of treating every
failure as the same shrug.

Politeness here is not a suggestion layered on top — it is the mechanism. One
request is in flight at a time, a fixed pause separates pages of the same
host, and there is no retry loop anywhere in this layer. That last part is
deliberate: a retry against a host you do not control is exactly how a polite
reader turns into a problem the host has to deal with. If the fetch fails,
the run fails, and you run it again yourself later.

The standing rule that goes with this: never run these "to check," and never
run them during a match. A page already on disk answers most questions
without another request, and a live match is when a host's own traffic is
highest and your curiosity is least justified.

## Against the league API

`ingest listone`, `ingest rosters`, `ingest lineup`, and `sync-league`
alongside them all speak to `apileague.fantacalcio.it` using a real person's
credentials. This is a different discipline because the failure mode differs
in kind, not degree: a webmaster notices excess traffic; a login system that
sees too many failed attempts locks the account, and nobody gets back in
until it decides to unlock.

So the login path is bounded, not left to retry its way through trouble. A
single-flight lock collapses concurrent callers onto one login attempt
instead of racing several. A cooldown after any attempt — success or failure
— stops a caller from hammering the endpoint again a moment later. A
staleness check decides whether a cached token is still worth trusting before
reaching for the network at all. And a 401-recovery path runs on its own
separate clock, deliberately distinct from the ordinary login cooldown, so
recovering from one rejected token doesn't inherit or reset a cooldown meant
for something else.

Sitting inside all of that is one non-negotiable case: the API can answer a
login attempt with a code that means the configured password is simply
wrong. That is a bad-password configuration error, and it is never retried —
not on the next call, not after the cooldown expires, not by any path in the
system.

!!! warning
    None of this machinery is decorative. A retry loop that escapes the
    single-flight lock, the cooldown, or the never-retry rule on a
    configuration error is how a real account gets locked — the direct,
    intended consequence of the login server's own defenses.

## Raw first, cutting across both

One rule holds for every source regardless of which discipline it lives
under: every fetch lands on disk, verbatim, before anything derived is
computed from it. Ingest writes the raw response; a separate step reads that
raw file and produces rows, aliases, matches. Nothing skips the disk in
between.

This is what makes `--rematch` possible on the sources that support it. If a
name-matching alias is added later — a player whose surname the automatic
matcher couldn't place — you do not need to touch the network again to fix
last month's data. The raw page is still sitting where it landed; re-running
the derivation step against it, with the new alias in place, reproduces a
corrected join with zero requests to anyone.

## The transferable claim

Nothing above depends on football, a listone, or this league. "Public hosts
get politeness enforced in the transport layer, not left to author
discipline" and "a login you do not fully control gets bounded by a lock, a
cooldown and a never-retry list, not a naive retry helper" are contracts any
project talking to someone else's servers can adopt as written. So is
raw-first: land the response before you interpret it, and every later fix is
a re-read instead of a re-fetch.

See [the CLI](cli.md) for the full `ingest` command table, and [MCP
servers](mcp-servers.md) for the account this discipline protects on the read
side.
