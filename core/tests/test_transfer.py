from fantaclaude.asta.transfer import reconcile

LABELS = {0: "KingNazzario", 1: "G8 E CLAUDIO", 2: "random label"}
NAMES = {100: "KingKlavan FC", 101: "Sanzimippi FC", 102: "Claudio", 103: "Empty eleventh"}
MIRROR = {0: {1: 50, 2: 10, 3: 1}, 1: {4: 80, 5: 20}, 2: {6: 7, 7: 1}}


def test_teams_are_matched_by_overlap_never_by_name():
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}, 103: {}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.clean
    assert {(t.mirror_team_id, t.lega_team_id) for t in result.teams} == {(0, 101), (1, 102), (2, 100)}
    assert result.my_team == (102, "Claudio")
    assert result.lega_not_in_room == ((103, "Empty eleventh", 0),) and result.mirror_unmatched == ()


def test_post_room_additions_at_the_minimum_bid_are_tolerated_and_named():
    lega = {100: {6: 7, 7: 1, 99: 1}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    team = next(t for t in result.teams if t.lega_team_id == 100)
    assert team.added_after_room == ((99, 1),) and team.extra_in_lega == () and team.clean and result.clean


def test_a_cost_that_differs_a_missing_pick_or_a_dear_extra_fails_the_check():
    lega = {100: {6: 7, 7: 1, 98: 5}, 101: {1: 51, 2: 10}, 102: {4: 80, 5: 20}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    by_lega = {t.lega_team_id: t for t in result.teams}
    assert by_lega[100].extra_in_lega == ((98, 5),) and not by_lega[100].clean
    assert by_lega[101].cost_differences == ((1, 50, 51),) and by_lega[101].missing_in_lega == (3,)
    assert by_lega[102].clean and not result.clean


def test_a_lega_team_with_players_that_matches_nothing_is_not_clean():
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}, 104: {55: 9}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.lega_not_in_room == ((104, "104", 1),) and not result.clean


def test_an_equal_overlap_is_ambiguous_and_said():
    lega = {100: {6: 7}, 105: {6: 7}, 101: {1: 50, 2: 10, 3: 1}, 102: {4: 80, 5: 20}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.ambiguous and "2" in result.ambiguous[0] and not result.clean


def test_me_unmatched_gives_no_my_team():
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}}
    result = reconcile(MIRROR, lega, me=1, labels=LABELS, names=NAMES)
    assert result.my_team is None and result.mirror_unmatched == ((1, "G8 E CLAUDIO"),) and not result.clean


def test_my_team_with_no_room_picks_still_reconciles_when_it_is_the_only_lega_team_left():
    """A team that bought nothing in the room has no overlap to match by, so
    overlap alone would leave it -- and the transfer -- unnamed forever. The
    mirror's `me` is the one team the check must always be able to name
    (spec, open question 17): when every other team has matched and exactly
    one lega team with players remains, that is `me`'s, whatever it holds --
    the whole roster reads as bought after the room."""
    mirror = {0: {1: 50, 2: 10, 3: 1}, 1: {}, 2: {6: 7, 7: 1}}
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}, 200: {}, 201: {8: 1}}
    result = reconcile(mirror, lega, me=1, labels=LABELS, names=NAMES, min_bid=1)
    assert result.my_team == (201, "201")
    team = next(t for t in result.teams if t.mirror_team_id == 1)
    assert team.lega_team_id == 201 and team.mirror_size == 0 and team.added_after_room == ((8, 1),) and team.clean
    assert result.lega_not_in_room == ((200, "200", 0),) and result.clean

    # more than one team-with-players remains: which is genuinely ambiguous, so no guess
    ambiguous_lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}, 200: {8: 1}, 201: {9: 1}}
    unresolved = reconcile(mirror, ambiguous_lega, me=1, labels=LABELS, names=NAMES, min_bid=1)
    assert unresolved.my_team is None


def test_a_room_team_that_bought_nothing_is_not_reported_unmatched():
    """The counterpart to the not-in-room tolerance on the lega side: a
    mirror team with zero picks has nothing an overlap diff could ever
    reconcile, and unlike a lega team it cannot even be named "the eleventh"
    -- it is simply not a finding, whether or not the lega happens to have
    an empty team left over for it too."""
    mirror = {0: {1: 50, 2: 10, 3: 1}, 1: {}, 2: {6: 7, 7: 1}}
    lega = {100: {6: 7, 7: 1}, 101: {1: 50, 2: 10, 3: 1}, 200: {}, 201: {}}
    result = reconcile(mirror, lega, me=1, labels=LABELS, names=NAMES, min_bid=1)
    assert result.mirror_unmatched == () and result.my_team is None
    assert result.lega_not_in_room == ((200, "200", 0), (201, "201", 0)) and result.clean
