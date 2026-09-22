import copy
import json

from conftest import FIXTURE_DIR, seed_voti_matching
from fantaclaude.analysis.calibration.scoring_check import check_scoring
from fantaclaude.ingest.match_scores import record_match
from fantaclaude.ingest.raw import RawStore
from fantaclaude.model.scoring import BonusMalus

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))


def _record(db, tmp_path, payload):
    raw = RawStore(tmp_path / "raw").write("lineup", payload, label="19717181-03")
    record_match(db, raw, payload, season_id=21)


def _check(db, mcp_fixture_json):
    return check_scoring(db, sheet="Fantacalcio", bm=BonusMalus.from_calculate(mcp_fixture_json("calculation_settings")),
                         season_id=21)


def test_check_scoring_agrees_with_a_voti_sheet_that_matches_the_platform(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED)
    check = _check(db, mcp_fixture_json)
    assert (check.checked, check.skipped, check.disagreements, check.ok) == (46, 0, [], True)


def test_check_scoring_names_a_voto_the_sheet_disagrees_with(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED, overrides={632: (7.0, {"assists": 1})})     # Zaccagni: the platform says 6.5
    [d] = _check(db, mcp_fixture_json).disagreements
    assert (d.player_id, d.field, d.platform, d.ours) == (632, "voto", 6.5, 7.0)
    assert "player 632" in d.describe() and "voto" in d.describe()


def test_check_scoring_names_a_fantavoto_the_bonus_table_disagrees_with(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED, overrides={632: (6.5, {"goals": 1})})       # the platform scored an assist
    [d] = _check(db, mcp_fixture_json).disagreements
    assert (d.player_id, d.field, d.platform, d.ours) == (632, "fantavoto", 7.5, 9.5)


def test_check_scoring_applies_the_malus(db, tmp_path, mcp_fixture_json):
    payload = copy.deepcopy(CALCULATED)
    payload["away"]["bench"][6].update({"m": 1, "scr": 5.5, "cscr": 4.5})            # Gallo, adapted
    _record(db, tmp_path, payload)
    seed_voti_matching(db, 21, payload)
    assert _check(db, mcp_fixture_json).ok


def test_check_scoring_names_a_status_mismatch(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    seed_voti_matching(db, 21, CALCULATED, overrides={5820: (6.0, {})})              # Bertola: senza voto on the platform
    [d] = _check(db, mcp_fixture_json).disagreements
    assert (d.player_id, d.field, d.platform, d.ours) == (5820, "status", "sv", "voto")


def test_check_scoring_skips_a_giornata_without_voti(db, tmp_path, mcp_fixture_json):
    _record(db, tmp_path, CALCULATED)
    check = _check(db, mcp_fixture_json)
    assert (check.checked, check.skipped, check.ok) == (0, 46, True)
