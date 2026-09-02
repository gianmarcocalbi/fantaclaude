# web — the asta dashboard

The auction-night dashboard (React + Vite + Tailwind), served by `fantaclaude
asta serve` from the same process and port as the API, the WebSocket and the
`fantaclaude-asta` MCP.

- `uv run poe types` — regenerate `src/api/schema.d.ts` from the FastAPI app's
  own OpenAPI document. Run it whenever `core/src/fantaclaude/api/models.py`
  changes; the payload types are never hand-written.
- `uv run poe web-build` — type-check and build into `web/dist/`.
- `uv run poe web-dev` — Vite's dev server alongside `asta serve --replay` on
  the sample capture, with `/api` and `/ws` proxied to it.
- `web/dist/` is what FastAPI mounts at `/`. It is gitignored, so a fresh
  clone serves a "run `poe web-build`" hint until you build it — which is what
  `fantaclaude doctor`'s `dashboard` check reports.
