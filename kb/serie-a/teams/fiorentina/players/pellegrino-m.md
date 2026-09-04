---
updated: 2026-09-04
ttl: 7d
confidence: low
source: "kb/serie-a/teams/fiorentina/profile.md (updated 2026-09-04); Kean's move to Como confirmed by the account holder (2026-09-04); listone snapshot 3"
player_id: 7023
name: "Pellegrino M."
team_short: FIO
depth: contested
availability: 1.0
---

# Pellegrino M. — contested

The other half of Fiorentina's open centre-forward question. He played the
opening round beside Kean rather than behind him, and Kean has since gone to
Como, so the shirt is his to contest with [[beto]] — same quotazione, no
source separating them. His own rate already sits close to a contested share,
so this note mostly pins a number that was right for the wrong reason: it is a
statement about a shared shirt now, not an average of seasons elsewhere.

```
fantaclaude query --sql "SELECT exp_presenze, explain FROM read_parquet('records/valuations/20260904T090510Z-7694bd6a.parquet') WHERE player_id = 7023"
```
