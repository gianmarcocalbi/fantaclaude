import pytest
from fantacalcio_mcp.calendar import MatchNotFoundError, resolve_match

# A calendario's own round number and the Serie A championship matchday it
# maps to are different numbers -- round 1 here is championship matchday 3,
# exactly as captured 2026-09-05 -- and one round carries several matches,
# only one of which involves any given team.
CALENDAR = [
    {"matchDay": 1, "championshipMatchDay": 3, "calculated": False,
     "matches": [{"tIdH": 11560832, "tIdA": 19689008}, {"tIdH": 11560187, "tIdA": 19717181}]},
    {"matchDay": 2, "championshipMatchDay": 4, "calculated": False,
     "matches": [{"tIdH": 19717181, "tIdA": 11560636}]},
]


def test_resolve_match_maps_the_championship_matchday_to_the_rounds_own_numbers():
    """A version confusing the two matchday numbers would return
    (3, 3, ...) instead of (1, 3, ...)."""
    assert resolve_match(CALENDAR, championship_matchday=3, team_id=19717181) == (1, 3, 11560187, 19717181)
    assert resolve_match(CALENDAR, championship_matchday=4, team_id=19717181) == (2, 4, 19717181, 11560636)


def test_resolve_match_refuses_a_championship_matchday_not_in_the_calendar():
    with pytest.raises(MatchNotFoundError, match="99"):
        resolve_match(CALENDAR, championship_matchday=99, team_id=19717181)


def test_resolve_match_refuses_a_team_absent_from_that_rounds_matches():
    with pytest.raises(MatchNotFoundError, match=str(11560636)):
        resolve_match(CALENDAR, championship_matchday=3, team_id=11560636)


# Two rounds sharing one championshipMatchDay -- a recovery/doubleheader round,
# or a competition playing two of its own rounds on one Serie A giornata. The
# first round here does not involve 19717181 at all; only the second does.
DOUBLEHEADER = [
    {"matchDay": 1, "championshipMatchDay": 3, "calculated": False,
     "matches": [{"tIdH": 11560832, "tIdA": 19689008}]},
    {"matchDay": 2, "championshipMatchDay": 3, "calculated": False,
     "matches": [{"tIdH": 11560187, "tIdA": 19717181}]},
]


def test_resolve_match_checks_every_round_at_that_matchday_before_refusing():
    """A version that raised as soon as the first round matching this
    championshipMatchDay finished its own inner loop without a match --
    rather than only after every such round was checked -- would abort here
    with "has no match for team 19717181", even though the second round of
    this same matchday has exactly that match."""
    assert resolve_match(DOUBLEHEADER, championship_matchday=3, team_id=19717181) == (2, 3, 11560187, 19717181)
