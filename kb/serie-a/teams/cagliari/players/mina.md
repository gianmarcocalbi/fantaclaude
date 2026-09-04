---
updated: 2026-09-04
ttl: 7d
confidence: medium
source: "kb/serie-a/teams/cagliari/profile.md (updated 2026-08-29); listone snapshot 3"
player_id: 4210
name: "Mina"
team_short: CAG
depth: starter
availability: 1.0
---

# Mina — starter

The profile has Mina in the middle with Rodriguez, part of the most settled eleven in the league, and names him as the penalty taker. He did not play the opening round — the appearances query confirms it — and the profile gives no reason, so availability stays whole while the watch item on him stands. His rate, from seasons with absences, undersells a first-choice centre-back at a club with no depth to rotate. Starter.

```
fantaclaude query --sql "SELECT exp_presenze, explain FROM read_parquet('records/valuations/20260902T213819Z-8210bd6a.parquet') WHERE player_id = 4210"
```
