from datetime import date

import pytest
from fantaclaude.model.d_factor import (
    COUNTED,
    D_FACTOR_ROLES,
    D_FACTOR_YML,
    MIN_TRUE_DEFENDERS,
    TRUE_DEFENDERS,
    Band,
    DFactorTable,
    DFactorTableError,
    d_factor_points,
    defensive_average,
    load_d_factor,
)
from fantaclaude.model.roles import Role

R = frozenset
TABLE = DFactorTable(bands=(Band(7.0, 6.0), Band(6.5, 3.0), Band(6.0, 1.0), Band(5.5, 0.0), Band(0.0, -1.0)),
                     with_goalkeeper=False, source="synthetic", verified_on=date(2026, 8, 29))


def test_the_shipped_table_is_empty_and_says_so():
    """League data, not a constant: the regolamento does not publish the
    thresholds, so the file ships empty and rank refuses while the D-Factor
    is active (Task 9)."""
    table = load_d_factor(D_FACTOR_YML)
    assert table.is_empty and table.verified_on is None and table.points(7.5) == 0.0
    text = D_FACTOR_YML.read_text(encoding="utf-8")
    assert "verified_on: null" in text and "bands: []" in text


def test_a_table_is_loaded_sorted_and_validated(tmp_path):
    path = tmp_path / "d.yml"
    path.write_text("source: 'Leghe > Impostazioni > Calcolo > D-Factor (2026-09-01)'\nverified_on: 2026-09-01\n"
                    "with_goalkeeper: true\nbands:\n  - {min: 6.0, points: 1}\n  - {min: 7.0, points: 6}\n  - {min: 6.5, points: 3}\n")
    table = load_d_factor(path)
    assert [b.floor for b in table.bands] == [7.0, 6.5, 6.0] and table.with_goalkeeper
    assert table.points(7.2) == 6 and table.points(6.5) == 3 and table.points(6.49) == 1 and table.points(5.0) == 0.0
    assert table.to_dict()["bands"][0] == {"min": 7.0, "points": 6.0}
    assert table.slope(6.1) == pytest.approx((3 - 1) / 0.5)                  # from the 6.0 band up to the 6.5 band
    assert table.slope(7.5) == 0.0 and TABLE.slope(6.1) == pytest.approx(4.0)

    for bad in ("bands: 3\n", "bands:\n  - {min: 6, points: x}\n", "bands:\n  - {min: 6, points: 1}\n  - {min: 6, points: 2}\n",
                "bands:\n  - {min: 6, points: 1}\nverified_on: null\n", "- a list\n"):
        path.write_text(bad)
        with pytest.raises(DFactorTableError):
            load_d_factor(path)


def test_a_syntax_error_in_the_hand_transcribed_table_is_a_dfactortableerror(tmp_path):
    """Finding 7. d_factor.yml is the one file in this system a human
    transcribes by hand off a web page, so a YAML *syntax* error there is
    expected, not exotic -- and yaml.parser.ParserError is neither
    DFactorTableError nor even a ValueError. It escaped both callers: `rank`
    died with a traceback (exit 1) where the contract says exit 3, and
    `doctor` -- the command whose whole job is to say what is wrong --
    crashed instead of failing its `scoring` check. Caught in the loader,
    the way load_pricing_config already catches its own."""
    path = tmp_path / "d.yml"
    path.write_text("bands: [ {min: 6.0, points: 1 }\nwith_goalkeeper: false\n", encoding="utf-8")
    with pytest.raises(DFactorTableError, match="d.yml"):
        load_d_factor(path)
    with pytest.raises(DFactorTableError, match="gone.yml"):
        load_d_factor(tmp_path / "gone.yml")


def test_defensive_average_takes_the_best_five_with_three_true_defenders():
    assert D_FACTOR_ROLES == {Role.Dc, Role.B, Role.Dd, Role.Ds, Role.E, Role.M} and TRUE_DEFENDERS < D_FACTOR_ROLES
    assert (COUNTED, MIN_TRUE_DEFENDERS) == (5, 3)
    lineup = [(R({Role.Por}), 7.5), (R({Role.Dc}), 6.0), (R({Role.Dc}), 6.5), (R({Role.Ds, Role.E}), 5.5),
              (R({Role.E}), 7.0), (R({Role.M}), 7.0), (R({Role.E, Role.W}), 6.5), (R({Role.C}), 8.0),
              (R({Role.T}), 6.0), (R({Role.A}), 7.5), (R({Role.Pc}), 6.0)]
    # The five best among the D-Factor roles would be E 7.0, M 7.0, Dc 6.5, E/W 6.5, Dc 6.0 -- only two true
    # defenders, so the rule takes the best three true defenders (6.5, 6.0, 5.5) and the best two of the rest (7.0, 7.0).
    assert defensive_average(lineup) == pytest.approx((6.5 + 6.0 + 5.5 + 7.0 + 7.0) / 5)
    assert defensive_average(lineup, goalkeeper=7.5, with_goalkeeper=True) == pytest.approx((6.5 + 6.0 + 5.5 + 7.0 + 7.0 + 7.5) / 6)
    assert defensive_average(lineup, with_goalkeeper=True) is None            # 5+1 without a goalkeeper vote
    assert defensive_average(lineup[:5]) is None                              # four eligible: fewer than five
    two_defenders = [(R({Role.Dc}), 6.0), (R({Role.Dc}), 6.5), (R({Role.E}), 7.0), (R({Role.M}), 7.0), (R({Role.E}), 6.5), (R({Role.M}), 6.0)]
    assert defensive_average(two_defenders) is None                           # fewer than three true defenders
    assert d_factor_points(lineup, TABLE) == 1.0 and d_factor_points(two_defenders, TABLE) == 0.0   # 6.4 sits in the 6.0 band
    assert d_factor_points(lineup, DFactorTable((), False, None, None)) == 0.0
