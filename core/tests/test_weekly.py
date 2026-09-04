from datetime import UTC, datetime, timedelta

import pytest
from conftest import seed_fixtures, seed_probabili
from fantaclaude.analysis.weekly import (
    ForecastError,
    LateForecast,
    Round,
    export_lineup_records,
    forecast,
    newest_probabili_file,
    target_round,
    write_lineup_run,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
G3 = [datetime(2026, 9, 4, 18, 45, tzinfo=UTC), datetime(2026, 9, 5, 16, 0, tzinfo=UTC), datetime(2026, 9, 7, 18, 45, tzinfo=UTC)]
G4 = [datetime(2026, 9, 11, 18, 45, tzinfo=UTC), datetime(2026, 9, 14, 18, 45, tzinfo=UTC)]


def _run(db, run_id="20260904T090510Z-7694bd6a", players=((2764, "Martinez L.", "INT", "A", ["Pc"], 8.1),
                                                         (5841, "Svilar", "ROM", "P", ["Por"], 5.6),
                                                         (2640, "Kolasinac", "ATA", "D", ["Ds", "Dc"], 6.0))):
    db.execute("INSERT INTO valuation_runs VALUES (?, ?, 'r', 'm3', 'i', 1, 1, 21, 2, ['balanced'], '{}', '{}')",
               [run_id, datetime(2026, 9, 4, 9, 5)])  # noqa: DTZ001 -- naive UTC, as stored
    for pid, name, short, role, roles, fm in players:
        db.execute("INSERT INTO valuations VALUES (?, ?, ?, ?, ?, ?, ?, 30.0, ?, 6.2, 10, 12, 14, 5.0, 7.0, 1, 20, NULL, NULL, '{}')",
                   [run_id, pid, name, short, role, roles[0], roles, fm])
    return run_id


def test_target_round_is_the_first_giornata_whose_last_kickoff_is_ahead(db):
    seed_fixtures(db, 21, {3: G3, 4: G4})
    r = target_round(db, NOW, season_id=21)
    assert r == Round(21, 3, datetime(2026, 9, 4, 18, 45), datetime(2026, 9, 7, 18, 45), 3)  # noqa: DTZ001 -- naive UTC, as fixtures stores it
    assert target_round(db, datetime(2026, 9, 5, 10, 0, tzinfo=UTC), season_id=21).giornata == 3   # in progress: still 3
    assert target_round(db, datetime(2026, 9, 8, 10, 0, tzinfo=UTC), season_id=21).giornata == 4
    assert target_round(db, NOW, season_id=21, giornata=4).giornata == 4
    with pytest.raises(ForecastError, match="giornata 9"):
        target_round(db, NOW, season_id=21, giornata=9)
    with pytest.raises(ForecastError, match="kicked off"):
        target_round(db, datetime(2026, 9, 20, tzinfo=UTC), season_id=21)


def test_target_round_needs_a_calendar(db):
    with pytest.raises(ForecastError, match="ingest calendar"):
        target_round(db, NOW, season_id=21)


def test_forecast_joins_the_page_to_the_run_for_every_listed_priced_player(db):
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90), (5841, "Svilar", "roma", 55), (777777, "Nobody", "roma", 5)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    assert [r.player_id for r in rows] == [2764, 5841]                # the unpriced id is not a row; Kolasinac unlisted is not a row
    lautaro = rows[0]
    assert lautaro.p_start_published == 90 and lautaro.p_start == pytest.approx(0.9)
    assert lautaro.fv_if_plays == pytest.approx(8.1) and lautaro.expected_points == pytest.approx(0.9 * 8.1)
    assert lautaro.fv_sd is None and lautaro.source == "published" and lautaro.roles == ("Pc",)
    assert newest_probabili_file(db, 21, 3)[0] == file_id and newest_probabili_file(db, 21, 4) is None


def test_write_refuses_after_the_first_kickoff_unless_late_and_marks_the_row(db, tmp_path):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    r = target_round(db, NOW, season_id=21)
    first = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    after = datetime(2026, 9, 4, 19, 0, tzinfo=UTC)
    with pytest.raises(LateForecast, match="--late"):
        write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=after, late=False)
    second = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=after, late=True)
    assert second != first
    assert db.execute("SELECT late, deadline FROM lineup_runs ORDER BY lineup_run_id").fetchall() == \
        [(False, datetime(2026, 9, 4, 18, 45)), (True, datetime(2026, 9, 4, 18, 45))]  # noqa: DTZ001 -- naive UTC, as stored
    assert db.execute("SELECT lineup_run_id FROM v_lineup_runs_current").fetchall() == [(first,)]
    assert db.execute("SELECT p_start_published, p_start, expected_points, source FROM predictions WHERE lineup_run_id = ?",
                      [first]).fetchone() == (90, pytest.approx(0.9), pytest.approx(0.9 * 8.1), "published")
    # --late before the deadline is not late: the flag permits, the clock decides
    third = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=True)
    assert db.execute("SELECT late FROM lineup_runs WHERE lineup_run_id = ?", [third]).fetchone() == (False,)
    assert db.execute("SELECT lineup_run_id FROM v_lineup_runs_current").fetchall() == [(third,)]


def test_a_second_run_before_the_deadline_is_a_second_row_and_nothing_is_touched(db):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    r = target_round(db, NOW, season_id=21)
    a = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    b = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW + timedelta(hours=1), late=False)
    assert db.execute("SELECT count(*) FROM lineup_runs").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM predictions").fetchone()[0] == 2
    assert db.execute("SELECT written_at FROM lineup_runs WHERE lineup_run_id = ?", [a]).fetchone()[0] == \
        datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 -- naive UTC, as stored
    assert b > a


def test_write_refuses_an_empty_forecast(db):
    seed_fixtures(db, 21, {3: G3})
    r = target_round(db, NOW, season_id=21)
    with pytest.raises(ForecastError, match="nothing to forecast"):
        write_lineup_run(db, round_=r, run_id="x", model_hash="m", probabili_file_id=1, rows=[], now=NOW, late=False)


def test_records_are_exported_once_by_giornata_and_write_time(db, tmp_path):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id)
    lineup_run_id = write_lineup_run(db, round_=target_round(db, NOW, season_id=21), run_id=run_id, model_hash="m3",
                                     probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    written = export_lineup_records(db, lineup_run_id, tmp_path / "records")
    assert [p.relative_to(tmp_path / "records").as_posix() for p in written] == \
        ["lineup_runs/21-03-20260904T120000Z.parquet", "predictions/21-03-20260904T120000Z.parquet"]
    assert export_lineup_records(db, lineup_run_id, tmp_path / "records") == []          # never rewritten
    assert db.execute("SELECT count(*) FROM read_parquet(?)", [str(written[1])]).fetchone()[0] == 1
