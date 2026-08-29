# Docs site — Design

**Date:** 2026-08-29
**Status:** Draft for review
**Scope:** a public-facing mkdocs site for `fantaclaude`, deployed to GitHub Pages

## Purpose

`gianmarcocalbi/fantaclaude` has no public-facing documentation. Anyone landing on
the repo sees `CLAUDE.md` (agent instructions) and a source tree, nothing that
explains what the project is or how the pieces fit together. This adds a small
mkdocs site — project overview, workspace layout, CLI, MCP server — built and
deployed to GitHub Pages on every push to `main`.

This is separate from `docs/superpowers/`, which holds specs and plans for working
*with Claude* on this repo and is not meant for a public audience.

## Structure

```
site/
  mkdocs.yml
  docs/
    index.md          # what fantaclaude is, at a glance
    architecture.md   # the uv workspace, the data spine, league config as data
    cli.md            # the fantaclaude CLI: sync-league, ingest, kb
    mcp.md            # the fantacalcio MCP server: what it exposes, to whom
```

mkdocs resolves `docs_dir` relative to `mkdocs.yml`'s own location, so pointing
`mkdocs.yml` at `site/` and leaving `docs_dir` at its default means mkdocs only ever
reads `site/docs/`. `docs/superpowers/` sits under a different top-level folder
entirely and is never scanned — no ignore-list or exclude pattern to maintain, and
nothing to break if `docs/superpowers/` grows new subfolders later.

## Content

Four pages, drawn from what already exists in the repo and in `docs/superpowers/`
specs — no new decisions about the project, just a public restatement of it:

- **index.md** — what fantaclaude is (a Fantacalcio Mantra assistant), the
  season/league framing kept generic (no league name, no id — that's
  configuration, not identity for a public audience).
- **architecture.md** — the two-package uv workspace (`core/` = `fantaclaude`,
  `mcp/fantacalcio/` = `fantacalcio_mcp`), the data spine and ingest pipeline at a
  high level, and the "league configuration is data, not constants" principle from
  the fantaclaude design spec.
- **cli.md** — the `fantaclaude` CLI surface: what `sync-league`, `ingest`, and
  `kb` do, described as capabilities rather than a full flag reference.
- **mcp.md** — what `fantacalcio-mcp` is and exposes (read-only league API access
  over stdio), and its relationship to `fantaclaude` as a library dependency.

Nothing from `captured/`, `.env`, `kb/league/`, or any real league/player data goes
into `site/docs/` — this content is served publicly. `kb/rules/` and
`kb/serie-a/` (club profiles) are out of scope for this pass; they can become their
own mkdocs section later if wanted, per the "skeleton first" option this design
didn't take, but that's a separate decision, not implied here.

## Tooling

Add `mkdocs` and `mkdocs-material` to the root `pyproject.toml`'s
`[dependency-groups].dev` — same lockfile, same `.venv` as `core/` and
`mcp/fantacalcio/`, no second Python environment to manage. Two `poe` tasks
alongside the existing `test`/`lint`/`fmt`:

```
docs-serve = "mkdocs serve -f site/mkdocs.yml"
docs-build = "mkdocs build -f site/mkdocs.yml --strict"
```

`site/mkdocs.yml` sets `site_name`, `theme.name: material`, and an explicit `nav:`
listing the four pages above in order. `--strict` turns broken internal links,
missing nav entries, and other mkdocs warnings into build failures — the only
verification a docs site like this needs, run identically locally and in CI.

## Deploy

`.github/workflows/docs.yml`:

- **Triggers:** `push` to `main` with a `paths: ["site/**"]` filter, plus
  `workflow_dispatch` for manual re-runs.
- **Permissions:** `pages: write`, `id-token: write` (required by
  `actions/deploy-pages`).
- **Concurrency:** a `pages` concurrency group with `cancel-in-progress: false`, so
  a second push while a deploy is running queues rather than racing it.
- **Steps:** check out, install `uv`, `uv sync --group dev`, then
  `uv run mkdocs build -f site/mkdocs.yml -d site/_build --strict`, then
  `actions/configure-pages`, `actions/upload-pages-artifact` (path `site/_build`),
  `actions/deploy-pages`.

`site/_build` is a build output, not source — it must be added to `.gitignore`
alongside the existing `data/`, `.venv/`, etc.

### Manual step, outside this repo

GitHub Pages is not yet enabled on `gianmarcocalbi/fantaclaude` — querying the
Pages API for this repo currently returns 404. Before the workflow's first run can
succeed, whoever holds admin on the repo needs to open
**Settings → Pages → Source** and select **GitHub Actions**. This is a one-time,
real change to a real repo's settings, so it's called out here rather than done by
an agent as part of implementation; the plan that follows this spec should end with
a reminder of this step rather than an attempt to script it.

## Testing

- `uv run poe docs-build` (wrapping `mkdocs build --strict`) is the pass/fail gate,
  run manually during implementation and by the CI workflow on every push. There is
  no unit-test suite for markdown content — `--strict` build success is the
  correctness signal for a docs site.
- The workflow itself is verified by pushing to `main` and confirming a successful
  Pages deployment once the manual Settings step above has been done; that
  end-to-end check cannot happen before then.
