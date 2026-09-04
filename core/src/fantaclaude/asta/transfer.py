"""The lega's rosters against the mirrored auction (spec, open question 9).

Teams are matched by roster overlap, never by name: four of ten FantaAstaLive
labels matched no lega owner on 2026-09-03. The diff is never literally
clean, so what is tolerated is named -- a lega team overlapping no mirror
roster is "not in the room" (the eleventh registered team) and fine when
empty; a player the lega added after the close at the session's minimum bid
is "added after the room"; an id the listone lacks reconciles by id. A cost
that differs, a mirror pick the lega lacks, or a dear extra fails the check.
The mirror's `me` reconciles with exactly one lega team when it overlaps
one -- that is the `my_team` leaf `league.yml` needs (open question 17).
Deliberately not guessed: a `me` that bought nothing in the room has no
overlap to match by, and elimination cannot stand in for it, because the
algorithm is forbidden to read names -- it cannot tell "my own empty team"
from "a stranger's empty team", nor, worse, from a stranger's team it simply
has not matched for some other reason. `my_team` stays `None` in that case;
naming it is left to the one party who actually knows which team is his.

The matching itself is an exact maximum-overlap assignment, not a greedy
scan: `_hungarian` (`model/modules.py`) solves it over a padded cost matrix
-- one dummy "stay unmatched" column per mirror team and one dummy row per
lega team, so every team always has a zero-cost alternative to a zero-overlap
pair. That padding is what makes zero overlap unmatchable structurally, the
same guarantee `assign_weighted`'s `_FORBIDDEN` sentinel gives the XI solver,
not merely a greedy preference for something better (review finding 3,
2026-09-04): a greedy descending-overlap scan can strand a team an exact
assignment would have matched, and its ambiguity check only ever looked on
one side of a tie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fantaclaude.model.modules import _FORBIDDEN, _hungarian


@dataclass(frozen=True)
class TeamDiff:
    mirror_team_id: int
    mirror_label: str
    lega_team_id: int
    lega_team_name: str
    overlap: int
    mirror_size: int
    lega_size: int
    missing_in_lega: tuple[int, ...]
    cost_differences: tuple[tuple[int, int, int], ...]     # (player_id, mirror cost, lega cost)
    added_after_room: tuple[tuple[int, int], ...]          # (player_id, cost) at or under the minimum bid
    extra_in_lega: tuple[tuple[int, int], ...]             # (player_id, cost) above it

    @property
    def clean(self) -> bool:
        return not (self.missing_in_lega or self.cost_differences or self.extra_in_lega)

    def to_dict(self) -> dict[str, Any]:
        return {"mirror_team_id": self.mirror_team_id, "mirror_label": self.mirror_label,
                "lega_team_id": self.lega_team_id, "lega_team_name": self.lega_team_name, "overlap": self.overlap,
                "mirror_size": self.mirror_size, "lega_size": self.lega_size,
                "missing_in_lega": list(self.missing_in_lega),
                "cost_differences": [list(c) for c in self.cost_differences],
                "added_after_room": [list(a) for a in self.added_after_room],
                "extra_in_lega": [list(e) for e in self.extra_in_lega], "clean": self.clean}


@dataclass(frozen=True)
class Reconciliation:
    teams: tuple[TeamDiff, ...]
    lega_not_in_room: tuple[tuple[int, str, int], ...]     # (team_id, name, roster size)
    mirror_unmatched: tuple[tuple[int, str], ...]
    ambiguous: tuple[str, ...]
    my_team: tuple[int, str] | None

    @property
    def clean(self) -> bool:
        return (all(t.clean for t in self.teams) and not self.mirror_unmatched and not self.ambiguous
                and all(size == 0 for _, _, size in self.lega_not_in_room))


def _matching(mirror: dict[int, dict[int, int]], lega: dict[int, dict[int, int]]) -> dict[int, int]:
    """Maximum-overlap matching, mirror team id -> lega team id. A cost matrix
    padded with a per-mirror-team and a per-lega-team dummy ("stay
    unmatched") lets `_hungarian` treat opting out as a real, zero-cost move
    -- so a zero-overlap pair is never the only way to fill a row or column,
    and can never be chosen (review finding 3, invariant 1: the whole command
    rests on a wrongly-matched `my_team` never happening silently)."""
    mirror_ids, lega_ids = sorted(mirror), sorted(lega)
    m, l = len(mirror_ids), len(lega_ids)
    if m == 0 or l == 0:
        return {}
    size = m + l
    cost = [[0.0] * size for _ in range(size)]
    for i, mid in enumerate(mirror_ids):
        mp = set(mirror[mid])
        for j, lid in enumerate(lega_ids):
            overlap = len(mp & set(lega[lid]))
            cost[i][j] = -float(overlap) if overlap > 0 else _FORBIDDEN
    result = _hungarian(cost)
    chosen: dict[int, int] = {}
    for i, mid in enumerate(mirror_ids):
        j = result[i]
        if j < l and cost[i][j] < 0:
            chosen[mid] = lega_ids[j]
    return chosen


def _ambiguous_ties(pairs: list[tuple[int, int, int]], chosen: dict[int, int],
                    labels: dict[int, str], names: dict[int, str]) -> list[str]:
    """A tie the solve had to break arbitrarily, checked in both directions:
    another lega team the same mirror team overlapped just as much (as
    before), and -- the half the old greedy scan never looked at -- another
    mirror team that overlapped the same lega team just as much. Either way
    the candidate must still be free: a tie against a team the solve matched
    elsewhere isn't a live ambiguity, it's just the runner-up."""
    overlap_of = {(mid, lid): o for o, mid, lid in pairs}
    chosen_lega = set(chosen.values())
    ambiguous: list[str] = []
    for mid, lid in sorted(chosen.items()):
        overlap = overlap_of[(mid, lid)]
        mirror_ties = sorted(l2 for o2, m2, l2 in pairs
                             if m2 == mid and o2 == overlap and l2 != lid and l2 not in chosen_lega)
        if mirror_ties:
            ambiguous.append(f"mirror team {mid} ({labels.get(mid, mid)}) overlaps lega teams {lid} and "
                             f"{', '.join(str(t) for t in mirror_ties)} equally ({overlap} players)")
        lega_ties = sorted(m2 for o2, m2, l2 in pairs
                           if l2 == lid and o2 == overlap and m2 != mid and m2 not in chosen)
        if lega_ties:
            ambiguous.append(f"lega team {lid} ({names.get(lid, lid)}) is overlapped by mirror teams {mid} and "
                             f"{', '.join(str(t) for t in lega_ties)} equally ({overlap} players)")
    return ambiguous


def reconcile(mirror: dict[int, dict[int, int]], lega: dict[int, dict[int, int]], *, me: int,
              labels: dict[int, str], names: dict[int, str], min_bid: int = 1) -> Reconciliation:
    pairs = sorted(((len(set(mp) & set(lp)), mid, lid) for mid, mp in mirror.items() for lid, lp in lega.items()),
                   key=lambda p: (-p[0], p[1], p[2]))
    chosen = _matching(mirror, lega)
    ambiguous = _ambiguous_ties(pairs, chosen, labels, names)
    used_mirror, used_lega = set(chosen), set(chosen.values())
    # No elimination fallback for `me`: a mirror team that bought nothing has
    # zero overlap with everything, exactly like a stranger's empty team --
    # the two are structurally indistinguishable without reading names, which
    # this function is deliberately forbidden to do for matching. Naming the
    # wrong lega team as `my_team` is worse than naming none (open question
    # 17 / review finding 1, 2026-09-04): downstream, `fantaclaude lineup`
    # would compute the XI over another manager's roster with nothing to
    # catch it. `my_team` below is `None` whenever `me` has no overlap match.
    teams: list[TeamDiff] = []
    for mid, lid in sorted(chosen.items()):
        mp, lp = mirror[mid], lega[lid]
        extra = [(pid, cost) for pid, cost in lp.items() if pid not in mp]
        teams.append(TeamDiff(
            mid, labels.get(mid, str(mid)), lid, names.get(lid, str(lid)), len(set(mp) & set(lp)), len(mp), len(lp),
            tuple(sorted(pid for pid in mp if pid not in lp)),
            tuple(sorted((pid, mp[pid], lp[pid]) for pid in mp if pid in lp and mp[pid] != lp[pid])),
            tuple(sorted((pid, cost) for pid, cost in extra if cost <= min_bid)),
            tuple(sorted((pid, cost) for pid, cost in extra if cost > min_bid))))
    not_in_room = tuple(sorted((lid, names.get(lid, str(lid)), len(lp)) for lid, lp in lega.items() if lid not in used_lega))
    # A mirror team that bought nothing in the room has nothing to reconcile
    # by overlap and is not a problem the way a genuinely stray room team is
    # (spec, the not-in-room tolerance, mirrored here): it is reported only
    # when it actually held picks the lega diff never accounted for.
    unmatched = tuple(sorted((mid, labels.get(mid, str(mid))) for mid in mirror if mid not in used_mirror and mirror[mid]))
    mine = (chosen[me], names.get(chosen[me], str(chosen[me]))) if me in chosen else None
    return Reconciliation(tuple(teams), not_in_room, unmatched, tuple(ambiguous), mine)
