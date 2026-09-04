---
updated: 2026-09-04
ttl: 7d
confidence: medium
source: "kb/serie-a/teams/como/profile.md (updated 2026-09-04); dazn.com probabile formazione Como and goal.com on the Kean signing (2026-09-04); listone snapshot 3"
player_id: 7017
name: "Douvikas"
team_short: COM
depth: contested
availability: 1.0
---

# Douvikas — contested

Downgraded from starter on 2026-09-04, which is what the previous version of
this note asked for: it flagged that the listone carried Kean at Como while
the profile did not mention him, and said it would be wrong if Kean were a
centre-forward for Fabregas. He is. Douvikas keeps the edge — he started the
opening day, scored, and is the one who interprets the role inside the system
— but the guides call the duel tight and expect frequent alternation, so a
starter's rate overstates a shirt he has to keep winning. Contested. He is
also a penalty alternative behind Da Cunha, which changes nothing while Da
Cunha plays. Paired with [[kean]].

```
fantaclaude query --sql "SELECT exp_presenze, explain FROM read_parquet('records/valuations/20260903T233449Z-7694bd6a.parquet') WHERE player_id = 7017"
```
