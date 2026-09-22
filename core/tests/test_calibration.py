import json
from datetime import UTC, datetime

import pytest
from conftest import (
    FIXTURE_DIR,
    seed_fixtures,
    seed_lineup_run,
    seed_listone,
    seed_rosters,
    seed_voti_matching,
)
from fantaclaude.analysis.calibration import (
    CalibrationError,
    NothingToCalibrate,
    calibrate,
)
from fantaclaude.db.connection import connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.match_scores import record_match
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from test_lineup_api import AWAY_BENCH, AWAY_TID, AWAY_XI, ROLES

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))


def _settings(con, mcp_fixture_json, *, calculate=None):
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=calculate or mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))


def _database(tmp_path, mcp_fixture_json, *, with_run=True, calculate=None):
    """Giornata 3 as it happened: the calculated match recorded, voti agreeing
    with it, my roster, and -- unless not `with_run` -- a forecast naming an
    XI and pricing three players: Zaccagni (got a voto), Rowe (absent from
    the sheet, his club played) and a Genoa player whose club has no voti."""
    path = tmp_path / "c.duckdb"
    con = connect(path)
    apply_schema(con)
    _settings(con, mcp_fixture_json, calculate=calculate)
    seed_listone(con, [(pid, f"p{pid}", "club19717181", "C", [r.value for r in ROLES[pid]])
                       for pid in AWAY_XI + AWAY_BENCH] + [(9999, "Nove", "Genoa", "D", ["Dc"])])
    seed_rosters(con, 2578630, 21, {AWAY_TID: ("Mine", {pid: 1 for pid in AWAY_XI + AWAY_BENCH})})
    seed_fixtures(con, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    record_match(con, RawStore(tmp_path / "raw").write("lineup", CALCULATED, label=f"{AWAY_TID}-03"), CALCULATED,
                 season_id=21)
    seed_voti_matching(con, 21, CALCULATED)
    if with_run:
        xi = [{"slot": "X", "player_id": pid, "name": f"p{pid}", "fit": "natural"} for pid in AWAY_XI]
        seed_lineup_run(con, 21, 3, [(632, 90, 0.9, 6.5, 1.0), (6844, 60, 0.6, 6.0, 1.0), (9999, 70, 0.7, 6.0, 1.0)],
                        module="3421", xi=xi, my_team=AWAY_TID)
    con.close()
    return connect(path, read_only=True)          # calibrate must work on a read-only handle: it writes nothing


def test_calibrate_scores_the_giornata_on_a_read_only_handle(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    report = calibrate(con, season_id=21, my_team=AWAY_TID)
    con.close()
    assert report.giornate == [3] and report.predictions == 2 and report.dropped == 1
    assert report.p_start.n == 2 and report.p_start.base_rate == pytest.approx(0.5)
    [w] = report.weeks
    assert (w.my_total, w.result, w.eleven_total) == (67.0, "1-4", 57.0)
    assert not w.model_xi.exact and w.model_xi.missing == ["p6844"]
    assert report.scoring.checked == 46 and report.scoring.ok
    assert [s.player_id for s in report.surprises["my_misses"]] == [632]
    assert report.warnings == []
    payload = report.to_dict()
    assert json.loads(json.dumps(payload, default=str))["weeks"][0]["result"] == "1-4"


def test_calibrate_warns_for_a_giornata_without_voti_and_scores_the_rest(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    report = calibrate(con, season_id=21, giornate=[3, 4], my_team=AWAY_TID)
    con.close()
    assert report.giornate == [3] and any("giornata 4 has no voti yet" in w for w in report.warnings)


def test_calibrate_without_my_team_still_scores_the_page(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    report = calibrate(con, season_id=21)
    con.close()
    assert report.weeks == [] and report.p_start.n == 2 and any("my_team" in w for w in report.warnings)


def test_calibrate_refuses_the_best_and_the_model_under_a_modifier(tmp_path, mcp_fixture_json):
    calculate = {**mcp_fixture_json("calculation_settings"), "smodd": 1}
    con = _database(tmp_path, mcp_fixture_json, calculate=calculate)
    [w] = calibrate(con, season_id=21, my_team=AWAY_TID).weeks
    con.close()
    assert w.best is None and "modifier" in w.best_note and w.my_total == 67.0


def test_calibrate_has_nothing_to_score_without_voti(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    with pytest.raises(NothingToCalibrate, match="giornata 5"):
        calibrate(con, season_id=21, giornate=[5], my_team=AWAY_TID)
    con.close()


def test_calibrate_refuses_a_database_at_an_older_schema(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    con.close()
    writer = connect(tmp_path / "c.duckdb")
    writer.execute("DELETE FROM schema_version")
    writer.execute("INSERT INTO schema_version (version) VALUES (5)")
    writer.close()
    con = connect(tmp_path / "c.duckdb", read_only=True)
    with pytest.raises(CalibrationError, match="schema 5"):
        calibrate(con, season_id=21, my_team=AWAY_TID)
    con.close()


def test_calibrate_names_a_giornata_predicted_under_other_rules(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json)
    con.close()
    writer = connect(tmp_path / "c.duckdb")
    writer.execute(
        "INSERT INTO valuation_runs VALUES ('r1', now(), 'deadbeef', 'm1', 'i1', 1, 1, 21, 3, ['balanced'], "
        "'{}', '{}')")
    writer.close()
    con = connect(tmp_path / "c.duckdb", read_only=True)
    report = calibrate(con, season_id=21, my_team=AWAY_TID)
    con.close()
    matches = [w for w in report.warnings if "giornata 3 was predicted under rules deadbeef" in w]
    assert len(matches) == 1 and report.warnings == matches


def test_calibrate_scores_a_week_without_a_forecast(tmp_path, mcp_fixture_json):
    con = _database(tmp_path, mcp_fixture_json, with_run=False)
    report = calibrate(con, season_id=21, my_team=AWAY_TID)
    con.close()
    assert report.predictions == 0 and report.p_start.n == 0 and report.fantavoto == []
    [w] = report.weeks
    assert w.my_total == 67.0 and w.model_xi is None and "no forecast named an XI" in w.model_note
