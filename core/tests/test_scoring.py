import pytest
from fantaclaude.model.scoring import (
    ASSIST_KEYS,
    BONUS_KEYS,
    D_FACTOR_KEY,
    MODIFIER_KEYS,
    VOTO_SOURCES,
    BonusMalus,
    Events,
    ScoringError,
    event_points,
    fantavoto,
    modifier_status,
    voto_sheet,
)


def test_bonus_malus_is_read_from_the_settings_payload(mcp_fixture_json):
    bm = BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))
    assert bm == BonusMalus(goal=3, penalty_goal=3, assist=1, goal_conceded=-1, penalty_saved=3,
                            penalty_missed=-2, yellow=-0.5, red=-1, own_goal=-1)
    assert bm.to_dict()["penalty_missed"] == -2
    assert BONUS_KEYS["goal"] == "bmgs" and ASSIST_KEYS == ("bmass", "bmasf", "bmasg")


def test_fantavoto_is_hand_computed_under_the_league_rules(mcp_fixture_json):
    bm = BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))
    # an open-play goal, a penalty goal (Gf excludes it, Rf carries it), an assist, a booking
    assert fantavoto(6.5, Events(goals=1, pen_scored=1, assists=1, yellow=1), bm) == pytest.approx(13.0)
    # a goalkeeper: two conceded, one penalty saved
    assert fantavoto(6.0, Events(goals_conceded=2, pen_saved=1), bm) == pytest.approx(7.0)
    assert event_points(Events(pen_missed=1, own_goals=1, red=1), bm) == pytest.approx(-4.0)
    assert event_points(Events(), bm) == 0.0


def test_scoring_is_league_configurable(mcp_fixture_json):
    """The same event counts under two different league_settings must yield
    two different fantavoti -- the test that would catch a stored fantavoto
    silently baking in fantacalcio.it's defaults."""
    calculate = mcp_fixture_json("calculation_settings")
    other = mcp_fixture_json("calculation_settings")
    other["bnMls"]["bmgs"] = [4, 4]
    other["bnMls"]["bmog"] = [-2, -2]
    events = Events(goals=1, own_goals=1)
    a = fantavoto(6.0, events, BonusMalus.from_calculate(calculate))
    b = fantavoto(6.0, events, BonusMalus.from_calculate(other))
    assert a == pytest.approx(8.0) and b == pytest.approx(8.0)                 # +1 on the goal, -1 on the own goal: they cancel
    goal_only = Events(goals=1)
    assert fantavoto(6.0, goal_only, BonusMalus.from_calculate(calculate)) == pytest.approx(9.0)
    assert fantavoto(6.0, goal_only, BonusMalus.from_calculate(other)) == pytest.approx(10.0)


def test_a_pair_whose_values_differ_is_refused(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmgs"] = [3, 2]
    with pytest.raises(ScoringError, match="bmgs"):
        BonusMalus.from_calculate(calculate)
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmasf"] = [2, 2]
    with pytest.raises(ScoringError, match="assist"):
        BonusMalus.from_calculate(calculate)
    calculate = mcp_fixture_json("calculation_settings")
    del calculate["bnMls"]["bmrc"]
    with pytest.raises(ScoringError, match="bmrc"):
        BonusMalus.from_calculate(calculate)
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmyc"] = "half"
    with pytest.raises(ScoringError, match="bmyc"):
        BonusMalus.from_calculate(calculate)


def test_a_nan_bonus_is_refused_rather_than_poisoning_every_fantavoto(mcp_fixture_json):
    """`_number` here checked isinstance and nothing else, and no range check
    stands behind it, so a NaN in bnMls was accepted and every fantavoto in
    the run -- and so every projection, every value and every price -- came
    out NaN. json.loads reads a bare `NaN` literal happily, so this is not
    unreachable. is_number refuses the non-finite floats at all nine sites
    that ask "is this a number?"."""
    for value in (float("nan"), float("inf")):
        calculate = mcp_fixture_json("calculation_settings")
        calculate["bnMls"]["bmgs"] = value
        with pytest.raises(ScoringError, match="bmgs"):
            BonusMalus.from_calculate(calculate)


def test_a_scalar_bonus_is_accepted_too(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    calculate["bnMls"]["bmgs"] = 3
    assert BonusMalus.from_calculate(calculate).goal == 3.0


def test_events_add_and_scale():
    total = Events(goals=1, assists=2) + Events(goals=2, yellow=1)
    assert total == Events(goals=3, assists=2, yellow=1)
    assert Events(goals=3, assists=2).scaled(0.5) == Events(goals=1.5, assists=1.0)


def test_voto_sheet_follows_sourcev(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    assert calculate["sourcev"] == 1 and voto_sheet(calculate) == "Fantacalcio"
    assert VOTO_SOURCES == {1: "Fantacalcio", 2: "Statistico", 3: "Italia"}
    calculate["sourcev"] = 9
    with pytest.raises(ScoringError, match="sourcev"):
        voto_sheet(calculate)
    calculate["sourcev"] = True
    with pytest.raises(ScoringError):
        voto_sheet(calculate)


def test_modifier_status_reads_the_nine_flags(mcp_fixture_json):
    calculate = mcp_fixture_json("calculation_settings")
    assert MODIFIER_KEYS == ("stbdf", "smodg", "smodd", "smodm", "skodm", "smodf", "smodl", "smodp", "smodcp")
    status = modifier_status(calculate)
    assert not status.d_factor and status.unknown_active == () and not status.any_active
    assert status.to_dict() == {"d_factor": False, "d_factor_raw": None, "unknown_active": []}

    calculate[D_FACTOR_KEY] = 1
    status = modifier_status(calculate)
    assert status.d_factor and status.d_factor_raw == 1 and status.unknown_active == () and status.any_active

    calculate["smodf"] = {"on": True}
    status = modifier_status(calculate)
    assert status.d_factor and status.unknown_active == ("smodf",)

    calculate[D_FACTOR_KEY] = 0                              # a falsy value reads as off
    calculate["smodf"] = None
    assert not modifier_status(calculate).any_active
