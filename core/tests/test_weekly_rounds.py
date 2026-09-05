from datetime import UTC, datetime, timedelta

import pytest
from conftest import seed_matches, seed_probabili
from fantaclaude.analysis.weekly import (
    ForecastRow,
    LateForecast,
    Round,
    player_fixtures,
    write_lineup_run,
)

T0 = datetime(2026, 9, 11, 18, 45, tzinfo=UTC)          # Friday
SUNDAY = T0 + timedelta(days=2, hours=-4)                # 14:45 UTC Sunday
MONDAY = T0 + timedelta(days=3)


def _round():
    return Round(21, 4, T0.replace(tzinfo=None), MONDAY.replace(tzinfo=None), 3)


def _rows(kickoffs):
    return [ForecastRow(pid, f"p{pid}", short, "A", ("A",), 90, 0.9, 7.0, None, 6.3, "published", kickoff=k)
            for pid, short, k in kickoffs]


def _seed(db):
    seed_matches(db, 21, [(4, T0, "INT", "ROM"), (4, SUNDAY, "ATA", "GEN"), (4, MONDAY, "MIL", "NAP")])
    return seed_probabili(db, 21, 4, [(2764, "Martinez L.", "inter", 90, "INT"), (5841, "Svilar", "roma", 100, "ROM"),
                                      (2640, "Kolasinac", "atalanta", 55, "ATA"), (999, "Ghost", "nowhere", 50, None)])


def test_player_fixtures_join_by_team_short_and_say_home_and_opponent(db):
    file_id = _seed(db)
    fixtures = player_fixtures(db, file_id)
    assert set(fixtures) == {2764, 5841, 2640}                                   # the unmatched club has no fixture
    assert (fixtures[2764].kickoff, fixtures[2764].home, fixtures[2764].opponent_short) == (T0.replace(tzinfo=None), True, "ROM")
    assert (fixtures[5841].home, fixtures[5841].opponent_short) == (False, "INT")
    assert fixtures[2640].kickoff == SUNDAY.replace(tzinfo=None)


def test_a_run_between_the_first_and_last_kickoff_marks_rows_per_player_and_the_xi_late(db):
    file_id = _seed(db)
    rows = _rows([(2764, "INT", T0.replace(tzinfo=None)), (2640, "ATA", SUNDAY.replace(tzinfo=None)), (999, None, None)])
    now = T0 + timedelta(hours=3)                                                # Friday night: Inter played, Atalanta not yet
    run_id, is_late = write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id,
                                       rows=rows, now=now, late=False)
    assert is_late is True                                                       # the XI lock passed at the first kickoff
    got = dict(db.execute("SELECT player_id, late FROM predictions WHERE lineup_run_id = ?", [run_id]).fetchall())
    assert got == {2764: True, 2640: False, 999: True}                           # no fixture: the round's first kickoff rules
    assert db.execute("SELECT kickoff FROM predictions WHERE player_id = 999").fetchone()[0] is None
    assert db.execute("SELECT count(*) FROM v_predictions_current").fetchone()[0] == 1     # Kolasinac's row is the honest one


def test_a_run_before_the_first_kickoff_is_on_time_for_everyone(db):
    file_id = _seed(db)
    rows = _rows([(2764, "INT", T0.replace(tzinfo=None)), (2640, "ATA", SUNDAY.replace(tzinfo=None))])
    _run_id, is_late = write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id,
                                        rows=rows, now=T0 - timedelta(hours=1), late=False)
    assert is_late is False
    assert {r[0] for r in db.execute("SELECT late FROM predictions").fetchall()} == {False}


def test_a_run_after_every_kickoff_is_refused_unless_late_and_then_every_row_is_late(db):
    file_id = _seed(db)
    rows = _rows([(2764, "INT", T0.replace(tzinfo=None)), (2640, "ATA", SUNDAY.replace(tzinfo=None))])
    with pytest.raises(LateForecast, match="every match"):
        write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id, rows=rows,
                         now=MONDAY + timedelta(minutes=1), late=False)
    _run_id, is_late = write_lineup_run(db, round_=_round(), run_id="r", model_hash="m", probabili_file_id=file_id,
                                        rows=rows, now=MONDAY + timedelta(minutes=1), late=True)
    assert is_late and {r[0] for r in db.execute("SELECT late FROM predictions").fetchall()} == {True}
    assert db.execute("SELECT count(*) FROM v_predictions_current").fetchone()[0] == 0
