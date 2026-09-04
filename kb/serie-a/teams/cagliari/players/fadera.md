---
updated: 2026-09-04
ttl: 7d
confidence: medium
source: "kb/serie-a/teams/cagliari/profile.md (updated 2026-08-29); listone snapshot 3"
player_id: 6815
name: "Fadera"
team_short: CAG
depth: cover
availability: 1.0
---

# Fadera — cover

The profile has Fazzini and Maldini in the two trequartista slots, with Felici and Fadera competing for them — and says the only genuinely shared slot at Cagliari is the centre-forward. Fadera's rate comes from a season of regular minutes and reads him as a starter; the profile does not. Cover.

```
fantaclaude query --sql "SELECT exp_presenze, explain FROM read_parquet('records/valuations/20260902T213819Z-8210bd6a.parquet') WHERE player_id = 6815"
```
