"""Resolving a competition's own calendar: which round matches a Serie A
championship matchday, and which match within that round involves a given
team.

Pure data logic over plain dicts/tuples/ints -- no HTTP, no fastmcp. Lives
here, not under `fantaclaude`, so it can be shared rather than duplicated:
`server.py`'s `get_lineup` tool and `fantaclaude.ingest.lineup_api` (Phase
3b, Task 13) both need it, `core` already depends on this package (never
the reverse -- see `pyproject.toml`), and this function has nothing
core-specific about it. `lineup_api.resolve_match` imports this the same
way it already imports `FantacalcioAPI` from here, rather than keeping a
second, independently-maintained copy of the same matching loop.
"""

from __future__ import annotations

from typing import Any


class MatchNotFoundError(ValueError):
    """No round or match in the calendar matches what was asked for."""


def resolve_match(calendar: Any, *, championship_matchday: int, team_id: int) -> tuple[int, int, int, int]:
    """(matchDay, championshipMatchDay, home tid, away tid) for the one
    round of `calendar` at `championship_matchday` whose match involves
    `team_id`.

    The competition's own `matchDay` and the Serie A `championshipMatchDay`
    it maps to are different numbers, and neither substitutes for the
    other (a *calendario*'s round 1 can be championship matchday 3) -- both
    are read straight off the matching round, never derived from one
    another.

    More than one round can share a `championship_matchday` (a
    recovery/doubleheader round, or a competition that plays two of its own
    rounds on one Serie A giornata) -- every such round is checked for
    `team_id`'s match before this refuses, so a first round that happens
    not to involve `team_id` cannot mask a second one that does.
    """
    matched_matchday = False
    for round_ in calendar or []:
        if round_.get("championshipMatchDay") != championship_matchday:
            continue
        matched_matchday = True
        for match in round_.get("matches") or []:
            home, away = match.get("tIdH"), match.get("tIdA")
            if team_id in (home, away):
                return int(round_["matchDay"]), int(round_["championshipMatchDay"]), int(home), int(away)
    if matched_matchday:
        raise MatchNotFoundError(f"championship matchday {championship_matchday} has no match for team {team_id}")
    raise MatchNotFoundError(f"championship matchday {championship_matchday} is not in this competition's calendar")
