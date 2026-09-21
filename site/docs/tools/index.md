# Tools & patterns

The three sections before this one told you what fantaclaude is, how it is
built, and how to run it through a season. This one looks underneath those
skills, at the surfaces and disciplines they stand on. Some of what you find
here belongs to this league alone; some of it does not, and would survive
being lifted whole into a different project.

## Liftable into another project

These are disciplines and contracts, not this league's furniture. Nothing
about them names a team, a rule, or a player — you could hand each one to a
different codebase built around a different game and it would still hold.

- **The standalone MCP server** — `fantacalcio-mcp` talks to a private
  Leghe Fantacalcio.it league over stdio and nothing else; any project
  wrapping that same API could reuse it unchanged. See [MCP
  servers](mcp-servers.md).
- **[The ingest contract](ingest-contract.md)** — the shape every source
  module honors before its numbers are trusted: fetch raw first, record it
  verbatim, then derive, never the reverse. It has nothing to do with
  football.
- **[The knowledge-base pattern](knowledge-base.md)** — plain files with
  front matter and a freshness date, audited rather than trusted forever, is
  a way to hold facts a model should read but never silently assume are
  still current.
- **[The skill pattern](skill-pattern.md)** — a skill that owns one recurring
  moment, reads the system's own outputs, and only ever changes an input, is
  a shape any Claude Code project can repeat for its own recurring moment.

## Components of this one

These are surfaces onto this specific system. Move them elsewhere and they
carry the league's own commands, schema, and rules with them — they are not
meant to generalize.

- **The CLI** — `fantaclaude`'s own commands: what fetches, what computes,
  what stays local. See [The CLI](cli.md).
- **The session-scoped auction MCP** — `fantaclaude-asta`, which exists only
  while `asta serve` is running an auction, answering questions about the
  board being served at that moment. See [MCP servers](mcp-servers.md).
- **[The records format](records.md)** — the append-only parquet and JSON
  this system writes under `records/` for every run, every submitted lineup
  and every closed auction, so a season can be checked after the fact
  against what it actually did.

## Reading order

If you came here from a "Full flags" note on a *Using fantaclaude* page, go
straight to [the CLI](cli.md). If you are trying to understand what a Claude session actually
sees when it calls into this system, start with [MCP servers](mcp-servers.md)
— the two servers differ enough in lifetime and transport that the contrast
is worth reading before either tool list. The remaining pages in this
section cover the ingest contract, the knowledge-base pattern, the skill
pattern, and the records format in turn.
