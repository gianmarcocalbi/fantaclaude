"""The lega's rosters against the mirrored auction (spec, open question 9).

Teams are matched by roster overlap, never by name: four of ten FantaAstaLive
labels matched no lega owner on 2026-09-03. The diff is never literally
clean, so what is tolerated is named -- a lega team overlapping no mirror
roster is "not in the room" (the eleventh registered team) and fine when
empty; a player the lega added after the close at the session's minimum bid
is "added after the room"; an id the listone lacks reconciles by id. A cost
that differs, a mirror pick the lega lacks, or a dear extra fails the check.
The mirror's `me` reconciles with exactly one lega team: that is the
`my_team` leaf `league.yml` needs (open question 17). A team that bought
nothing in the room has no overlap to match by -- so when `me` is the one
still unmatched after every other pairing, and exactly one lega team with
players is left over, that is mine by elimination, its whole roster read as
bought after the room. Two teams left over is genuinely ambiguous and stays
unnamed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


def reconcile(mirror: dict[int, dict[int, int]], lega: dict[int, dict[int, int]], *, me: int,
              labels: dict[int, str], names: dict[int, str], min_bid: int = 1) -> Reconciliation:
    pairs = sorted(((len(set(mp) & set(lp)), mid, lid) for mid, mp in mirror.items() for lid, lp in lega.items()),
                   key=lambda p: (-p[0], p[1], p[2]))
    used_mirror: set[int] = set()
    used_lega: set[int] = set()
    chosen: dict[int, int] = {}
    ambiguous: list[str] = []
    for overlap, mid, lid in pairs:
        if overlap == 0:
            break
        if mid in used_mirror or lid in used_lega:
            continue
        ties = [l2 for o2, m2, l2 in pairs if m2 == mid and o2 == overlap and l2 != lid and l2 not in used_lega]
        if ties:
            ambiguous.append(f"mirror team {mid} ({labels.get(mid, mid)}) overlaps lega teams {lid} and "
                             f"{', '.join(str(t) for t in ties)} equally ({overlap} players)")
        chosen[mid] = lid
        used_mirror.add(mid)
        used_lega.add(lid)
    if me in mirror and me not in chosen:
        # Overlap cannot match a team that bought nothing in the room -- every
        # pairing with it scores 0, indistinguishable from any other team the
        # room never touched. But `me` is not just any team: the mirror's own
        # side is always mine, and once every other team has claimed its lega
        # match, at most one lega team with players can be left over for it.
        # Two or more, and there is no way to tell which is mine -- that stays
        # unnamed, honestly, rather than guessed.
        leftover = [lid for lid, lp in lega.items() if lid not in used_lega and lp]
        if len(leftover) == 1:
            chosen[me] = leftover[0]
            used_mirror.add(me)
            used_lega.add(leftover[0])
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
