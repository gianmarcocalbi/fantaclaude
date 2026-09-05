# kb/ — the knowledge base

DuckDB holds neutral numbers; this tree holds opinionated prose with
provenance. **Prose never restates a number** — it links to a query or a
`run_id`. "Lautaro averages 7.2" is a lie waiting to happen; "Lautaro takes
penalties unless Calhanoglu is on the pitch" is durable and no table has it.

```
kb/
├── rules/                     # near-static: mantra.md, house-rules.md, aliases.yml
├── serie-a/teams/<slug>/      # profile.md: front-matter (team, team_short, coach, module, europe,
│   │                          #   rotation_factor, takers) read by fantaclaude.kb.profiles; prose for the model
│   └── players/<name>.md      # sparse: front-matter (player_id, name, team_short, depth, availability,
│                              #   prior_fantamedia) read by fantaclaude.kb.notes -- only where prose changes a decision
└── league/
    ├── participants/<nick>.md # opponent dossiers: front-matter (nick, team, budget_style, favourite_clubs,
    │                          #   overpays, avoids, max_single_share) read by fantaclaude.kb.participants
    ├── history/<season>.md
    └── season-2026-27/        # the journal, append-only: giornata-00-asta.md, giornata-01.md, …
        # the weekly loop's own file is data/lineup-notes.yml, not here: a note is a fact for one giornata, not knowledge
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
lacks front-matter, and what is malformed — for a profile, a player note or a
dossier, "malformed" includes its structured keys. An expired document is a
notice for the skill that would use it — the skill states low confidence or
refuses; the audit itself never refuses.

## The numbers the code reads

- **Team profile** (`fantaclaude.kb.profiles`): `rotation_factor` (0.5–1.0, the
  European load and the coach's habit, applied to every player of the club
  through his presenze), `takers.penalties` (the player the projection gives the
  club's penalties to), `europe`, `module`, `coach`.
- **Player note** (`fantaclaude.kb.notes`): `player_id` is the join — the folder
  is a mirror of the club, and `fantaclaude doctor` says when a note sits under
  the wrong club. `depth` (`starter | contested | cover | out`) *replaces* the
  statistical presenze rate: it is a statement about now, not a multiplier on
  last season. `availability` (0–1) multiplies presenze. `prior_fantamedia` is
  read only for a player with no Serie A history.
- **Participant dossier** (`fantaclaude.kb.participants`): `budget_style`
  (`early | steady | hoarder`), `favourite_clubs`, `overpays`/`avoids` (role
  classes), `max_single_share` — what the auction's pressure model loads at
  startup. No field ever carries an email address.

`/fanta-kb bootstrap` fills this tree, `/fanta-kb refresh` renews it and
`/fanta-kb interview` writes the dossiers (`.claude/skills/fanta-kb/SKILL.md`).
A profile's `europe` must agree with `v_european_ties`; `fantaclaude doctor`
says when it does not.
