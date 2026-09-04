---
updated: 2026-09-04
ttl: 7d
confidence: medium
source: "kb/serie-a/teams/como/profile.md (updated 2026-09-04); dazn.com probabile formazione Como and goal.com on the Kean signing (2026-09-04); listone snapshot 3"
player_id: 7412
name: "Milla"
team_short: COM
depth: contested
availability: 1.0
---

# Milla — contested

Corrected from cover on 2026-09-04. The profile had him behind the pivot, but
the probable-formation guide starts him beside Da Cunha and he played the
opening round, so "behind them" is not what the season has shown. The pivot is
two places from four — Da Cunha the constant, Milla, Perrone and Ricci S.
around him — which is contested, not cover. His own history is a single round
and gives the rate no weight either way.

```
fantaclaude query --sql "SELECT exp_presenze, explain FROM read_parquet('records/valuations/20260903T233449Z-7694bd6a.parquet') WHERE player_id = 7412"
```
