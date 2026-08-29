# fantaclaude

A Fantacalcio **Mantra** assistant: it is being built to maintain a knowledge
base of Serie A clubs and players, value them ahead of an auction, and help run
a live auction and pick a lineup every week.

fantaclaude is not a general fantasy-football tool — it is built against a
specific Leghe Fantacalcio.it league, using that league's live rules (budget,
roster composition, scoring) as configuration rather than as hardcoded constants,
because those rules can change season to season.

## What's here

- **[Architecture](architecture.md)** — the two-package workspace, the data
  spine, and why league rules are data, not code.
- **[CLI](cli.md)** — the `fantaclaude` command line: syncing league data,
  ingesting statistics, and building the knowledge base.
- **[MCP server](mcp.md)** — `fantacalcio-mcp`, the read-only bridge between
  Claude and the league API.
