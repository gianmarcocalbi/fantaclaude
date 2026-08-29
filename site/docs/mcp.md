# The `fantacalcio-mcp` server

`fantacalcio-mcp` is a small [MCP](https://modelcontextprotocol.io) server that
gives an LLM read-only access to a Leghe Fantacalcio.it league: account details,
league settings, team rosters, and the competitions on offer. It talks to the
league's API over stdio and exposes it as a set of typed tools rather than as
raw HTTP.

It is deliberately narrow: no writes, no auction actions, nothing that could
change league state. Its only job is answering "what does the league API say
right now?" so that both a conversational assistant and fantaclaude's own
ingestion code can ask that question without duplicating the API client.

`fantaclaude` depends on it as an ordinary Python library — `core/`'s ingestion
code imports `fantacalcio_mcp.api` directly rather than spawning the MCP server
and talking to it over stdio, so there is exactly one implementation of "what
the league API looks like" in this codebase.
