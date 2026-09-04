---
updated: 2026-09-04
ttl: 7d
confidence: medium
source: "kb/serie-a/teams/bologna/profile.md (updated 2026-08-29); listone snapshot 3"
player_id: 4359
name: "Piccoli"
team_short: BOL
depth: contested
availability: 1.0
---

# Piccoli — contested

The profile says Dovbyk arrived to lead the line and Piccoli is the alternative, then notes that both played on the opening day and calls the question open — "Dovbyk or Piccoli" is on the watch list. Piccoli's rate comes from seasons as a regular and reads him as near ever-present, which the profile does not support. Contested.

```
fantaclaude query --sql "SELECT exp_presenze, explain FROM read_parquet('records/valuations/20260902T213819Z-8210bd6a.parquet') WHERE player_id = 4359"
```
