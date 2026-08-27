# kb/ — the knowledge base

DuckDB holds neutral numbers; this tree holds opinionated prose with
provenance. **Prose never restates a number** — it links to a query or a
`run_id`. "Lautaro averages 7.2" is a lie waiting to happen; "Lautaro takes
penalties unless Calhanoglu is on the pitch" is durable and no table has it.

```
kb/
├── rules/                     # near-static: mantra.md, house-rules.md, aliases.yml
├── serie-a/teams/<team>/      # profile.md (tactics, module, takers, rotation_factor)
│   └── players/<slug>.md      # sparse: only where prose changes a decision
└── league/
    ├── participants/<name>.md # opponent dossiers (fixed front-matter schema)
    ├── history/<season>.md
    └── season-2026-27/        # the journal, append-only: giornata-00-asta.md, giornata-01.md, …
```

## Front-matter contract

Every `.md` document except this README starts with a YAML block:

```yaml
---
updated: 2026-08-24        # ISO date of the last review
ttl: 30d                   # "<days>d" or "never"
confidence: high           # high | medium | low
source: regolamento        # where this came from
---
```

`fantaclaude kb audit` lists what has expired (`updated + ttl < today`), what
lacks front-matter, and what is malformed. An expired document is a notice for
the skill that would use it — the skill states low confidence or refuses;
the audit itself never refuses.

`fanta-kb bootstrap` (Phase 0b) fills this tree; `fanta-kb refresh` renews it.
