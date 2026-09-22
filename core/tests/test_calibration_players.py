import pytest
from conftest import seed_lineup_run, seed_listone, seed_voti
from fantaclaude.analysis.calibration.actuals import (
    Actual,
    Scored,
    clubs_with_voti,
    load_actuals,
    load_scored,
)
from fantaclaude.analysis.calibration.fantavoto import fantavoto_bias, surprises
from fantaclaude.analysis.calibration.pstart import bin_index, reliability, wilson
from fantaclaude.model.scoring import BonusMalus


def _row(pid, published, blend, *, voto=None, fantavoto=None, fv=6.0, fv_sd=None, role="C", model="m1", weekly=None,
         giornata=3, absent=False):
    actual = None if absent else Actual(giornata, pid, "Inter", role, voto, fantavoto)
    return Scored(giornata, pid, f"p{pid}", "Inter", 1, model, weekly, published, blend, fv, fv_sd, actual)


# Five predictions, hand-scored: three published at 90 (two got a voto; the
# third was noted out, blend 0, and did not play), one at 15, one at 5.
FIVE = [_row(1, 90, 0.9, voto=6.5, fantavoto=7.5), _row(2, 90, 0.9, voto=6.0, fantavoto=6.0),
        _row(3, 90, 0.0, absent=True), _row(4, 15, 0.15, absent=True), _row(5, 5, 0.05)]


def test_wilson_matches_the_closed_form():
    assert wilson(2, 3) == pytest.approx((0.2077, 0.9385), abs=1e-4)
    assert wilson(0, 1) == pytest.approx((0.0, 0.7935), abs=1e-4)
    assert wilson(0, 0) == (0.0, 1.0)


def test_a_published_100_joins_the_nineties():
    assert [bin_index(p) for p in (0, 5, 9, 10, 55, 90, 100)] == [0, 0, 0, 1, 5, 9, 9]


def test_reliability_bins_and_brier_scores_are_the_hand_computed_ones():
    report = reliability(FIVE)
    assert report.n == 5
    assert [(b.low, b.high, b.n) for b in report.bins] == [(0, 9, 1), (10, 19, 1), (90, 100, 3)]
    top = report.bins[-1]
    assert top.mean_predicted == pytest.approx(0.9) and top.observed == pytest.approx(2 / 3)
    assert (top.ci_low, top.ci_high) == pytest.approx((0.2077, 0.9385), abs=1e-4)
    assert report.base_rate == pytest.approx(0.4)
    assert report.brier_published == pytest.approx(0.171)
    assert report.brier_blend == pytest.approx(0.009)
    assert report.brier_base_rate == pytest.approx(0.24)


def test_reliability_scores_only_rows_with_a_published_number():
    report = reliability([*FIVE, _row(6, None, 0.0, absent=True)])
    assert report.n == 5 and report.brier_published == pytest.approx(0.171)
    assert reliability([]).n == 0 and reliability([]).bins == []


def test_fantavoto_bias_by_role_overall_and_spread():
    rows = [_row(1, 90, 0.9, voto=6.5, fantavoto=7.5, fv=6.0, fv_sd=1.0, role="C"),
            _row(2, 90, 0.9, voto=6.0, fantavoto=6.0, fv=7.0, fv_sd=2.0, role="A"),
            _row(3, 90, 0.9, absent=True)]
    [model] = fantavoto_bias(rows)
    assert (model.model_hash, model.weekly_hash) == ("m1", None)
    groups = {g.group: g for g in model.groups}
    assert [g.group for g in model.groups] == ["C", "A", "all"]
    assert (groups["C"].n, groups["C"].mean_error, groups["C"].se, groups["C"].mae) == (1, 1.5, None, 1.5)
    assert (groups["A"].n, groups["A"].mean_error, groups["A"].mae) == (1, -1.0, 1.0)
    assert groups["all"].n == 2 and groups["all"].mean_error == pytest.approx(0.25)
    assert groups["all"].se == pytest.approx(1.25) and groups["all"].mae == pytest.approx(1.25)
    assert (model.spread_n, model.within_1sd, model.within_2sd) == (2, 0.5, 1.0)


def test_fantavoto_bias_splits_by_model_and_weekly_hash():
    rows = [_row(1, 90, 0.9, voto=6.0, fantavoto=6.0, model="m1"),
            _row(2, 90, 0.9, voto=6.0, fantavoto=6.0, model="m1", weekly="w1"),
            _row(3, 90, 0.9, voto=6.0, fantavoto=6.0, model="m2")]
    assert [(m.model_hash, m.weekly_hash) for m in fantavoto_bias(rows)] == [("m1", None), ("m1", "w1"), ("m2", None)]
    assert fantavoto_bias([_row(1, 90, 0.9, absent=True)]) == []


def test_surprises_name_the_confident_no_shows_the_long_shots_and_my_misses():
    rows = [_row(1, 90, 0.9, absent=True), _row(2, 85, 0.85, voto=None, fantavoto=None),
            _row(3, 15, 0.15, voto=7.0, fantavoto=10.0), _row(4, 60, 0.6, voto=6.0, fantavoto=4.0, fv=6.5),
            _row(5, 60, 0.6, voto=6.0, fantavoto=6.0, fv=6.2)]
    found = surprises(rows, my_roster=frozenset({4, 5}))
    assert [s.player_id for s in found["no_shows"]] == [1, 2]
    assert [(s.player_id, s.fantavoto) for s in found["long_shots"]] == [(3, 10.0)]
    assert [(s.player_id, s.error) for s in found["my_misses"]] == [(4, -2.5), (5, pytest.approx(-0.2))]


def test_load_scored_reads_the_honest_rows_and_drops_a_postponed_club(db, mcp_fixture_json):
    bm = BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))
    seed_listone(db, [(1, "Uno", "Inter", "C", ["C"]), (2, "Due", "Inter", "C", ["C"]),
                      (3, "Tre", "Inter", "A", ["A"]), (4, "Quattro", "Genoa", "D", ["Dc"])])
    seed_voti(db, 21, 3, [(1, "Uno", "Inter", "C", 6.5, {"assists": 1}), (2, "Due", "Inter", "C", None, {})])
    seed_lineup_run(db, 21, 3, [(1, 90, 0.9, 6.0, None), (2, 60, 0.6, 6.0, None), (3, 55, 0.55, 6.5, None),
                                (4, 70, 0.7, 6.0, None)])
    seed_lineup_run(db, 21, 3, [(1, 90, 0.1, 6.0, None)], late=True, run_id="r2")          # late: never read
    actuals = load_actuals(db, season_id=21, giornate=[3], sheet="Fantacalcio", bm=bm)
    assert actuals[(3, 1)].fantavoto == 7.5 and not actuals[(3, 2)].voted
    clubs = clubs_with_voti(db, season_id=21, giornate=[3], sheet="Fantacalcio")
    assert clubs == {3: frozenset({"Inter"})}
    scored, dropped = load_scored(db, season_id=21, giornate=[3], actuals=actuals, clubs=clubs)
    assert dropped == 1                                       # Genoa has no voti at all: a postponed match
    by = {s.player_id: s for s in scored}
    assert set(by) == {1, 2, 3}
    assert by[1].voted and by[1].p_start == 0.9 and by[1].error == pytest.approx(1.5)
    assert not by[2].voted and by[2].actual is not None       # senza voto: in the sheet, no voto
    assert not by[3].voted and by[3].actual is None and by[3].error is None     # absent from the sheet
    assert by[1].name == "Uno" and by[1].model_hash == "m1"
