---
updated: 2026-09-04
ttl: 7d
confidence: low
source: "kb/serie-a/teams/fiorentina/profile.md (updated 2026-09-04); Kean's move to Como confirmed by the account holder (2026-09-04); listone snapshot 3"
player_id: 5694
name: "Beto"
team_short: FIO
depth: contested
availability: 1.0
---

# Beto — contested

Fiorentina's centre-forward shirt came open when Kean left for Como, and Beto
is one of the two men who can wear it. His statistical rate is the worst
possible guide to that: it averages a season in which he barely featured at
another club, and says nothing about a forward signed to lead a line. The
listone prices him level with [[pellegrino-m]], which is the market declining
to separate them too. Contested rather than starter, because no source names
either as first choice — this is the encoding of a genuine unknown, not a
prediction.

```
fantaclaude query --sql "SELECT exp_presenze, explain FROM read_parquet('records/valuations/20260904T090510Z-7694bd6a.parquet') WHERE player_id = 5694"
```
