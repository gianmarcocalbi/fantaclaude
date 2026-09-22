import copy
import json
from datetime import UTC, datetime

import pytest
from conftest import FIXTURE_DIR, seed_fixtures
from fantaclaude.ingest.match_scores import (
    STATUS_ABSENT,
    STATUS_SV,
    STATUS_VOTO,
    MatchScoresShapeError,
    NoSeasonCalendar,
    oriented_result,
    parse_match,
    record_from_disk,
    record_match,
)
from fantaclaude.ingest.raw import RawStore

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))
MID_ROUND = json.loads((FIXTURE_DIR / "lineup_sample.json").read_text(encoding="utf-8"))
HOME_TID, AWAY_TID = 11560187, 19717181           # my team is away


def _statuses(match, team_id):
    counts = {STATUS_VOTO: 0, STATUS_SV: 0, STATUS_ABSENT: 0}
    for p in match.players:
        if p.team_id == team_id:
            counts[p.status] += 1
    return counts


def test_parse_match_reads_both_sides_of_the_calculated_round():
    m = parse_match(CALCULATED)
    assert (m.giornata, m.competition_id, m.matchday) == (3, 539860, 1)
    assert (m.home_team, m.away_team, m.home_module, m.away_module) == (HOME_TID, AWAY_TID, "343", "3421")
    assert (m.home_total, m.away_total, m.home_points, m.away_points) == (82.5, 67.0, 3, 0)
    assert (m.result, m.sign) == ("4-1", "1")
    assert len(m.players) == 46
    assert _statuses(m, AWAY_TID) == {STATUS_VOTO: 20, STATUS_SV: 1, STATUS_ABSENT: 2}
    assert _statuses(m, HOME_TID) == {STATUS_VOTO: 20, STATUS_SV: 0, STATUS_ABSENT: 3}
    by_id = {(p.team_id, p.player_id): p for p in m.players}
    bertola, rowe, zaccagni = by_id[(AWAY_TID, 5820)], by_id[(AWAY_TID, 6844)], by_id[(AWAY_TID, 632)]
    assert (bertola.status, bertola.part, bertola.voto, bertola.fantavoto) == (STATUS_SV, "bench", None, None)
    assert (rowe.status, rowe.part, rowe.position) == (STATUS_ABSENT, "xi", 7)
    assert (zaccagni.voto, zaccagni.fantavoto, zaccagni.malus) == (6.5, 7.5, 0)
    assert sum(p.fantavoto for p in m.players if p.team_id == AWAY_TID and p.part == "xi" and p.status == STATUS_VOTO) == 57.0


def test_parse_match_returns_none_for_a_round_not_yet_calculated():
    assert parse_match(MID_ROUND) is None


def test_oriented_result_puts_my_goals_first():
    assert (oriented_result("4-1", True), oriented_result("4-1", False), oriented_result(None, False)) == ("4-1", "1-4", None)


def _with(entry_changes, *, part="starts", index=0):
    payload = copy.deepcopy(CALCULATED)
    payload["away"][part][index].update(entry_changes)
    return payload


def test_parse_match_refuses_an_unknown_sentinel_by_name():
    with pytest.raises(MatchScoresShapeError, match="57.*sentinel"):
        parse_match(_with({"scr": 57, "cscr": 100}))


def test_parse_match_refuses_a_sentinel_beside_a_real_fantavoto():
    with pytest.raises(MatchScoresShapeError, match="sentinel"):
        parse_match(_with({"scr": 56, "cscr": 6}))


def test_parse_match_refuses_a_voto_beside_the_missing_fantavoto():
    with pytest.raises(MatchScoresShapeError, match="cscr 100"):
        parse_match(_with({"scr": 6, "cscr": 100}))


def test_parse_match_keeps_the_malus():
    payload = _with({"m": 1, "cscr": 4.5, "scr": 5.5}, part="bench", index=6)      # Gallo, 4502
    gallo = next(p for p in parse_match(payload).players if p.player_id == 4502)
    assert (gallo.voto, gallo.fantavoto, gallo.malus) == (5.5, 4.5, 1)


def test_record_match_writes_once_per_raw_file(db, tmp_path):
    raw = RawStore(tmp_path / "raw").write("lineup", CALCULATED, label=f"{AWAY_TID}-03")
    first = record_match(db, raw, CALCULATED, season_id=21)
    again = record_match(db, raw, CALCULATED, season_id=21)
    assert first.calculated and not first.duplicate and first.players == 46 and first.giornata == 3
    assert again.duplicate and again.file_id == first.file_id and again.players == 0
    assert db.execute("SELECT count(*) FROM match_files").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM match_scores").fetchone()[0] == 46
    assert db.execute("SELECT DISTINCT season_id, giornata FROM v_match_scores_current").fetchall() == [(21, 3)]
    assert db.execute("SELECT home_total, away_total, result FROM v_match_files_current").fetchone() == (82.5, 67.0, "4-1")


def test_record_match_skips_a_round_not_yet_calculated(db, tmp_path):
    raw = RawStore(tmp_path / "raw").write("lineup", MID_ROUND, label=f"{AWAY_TID}-03")
    result = record_match(db, raw, MID_ROUND, season_id=21)
    assert (result.calculated, result.file_id, result.giornata) == (False, None, 3)
    assert db.execute("SELECT count(*) FROM match_files").fetchone()[0] == 0


def test_record_from_disk_walks_the_raw_directory_and_skips_what_predates_the_season(db, tmp_path):
    seed_fixtures(db, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    store = RawStore(tmp_path / "raw")
    store.write("lineup", CALCULATED, label=f"{AWAY_TID}-03", fetched_at=datetime(2026, 9, 22, 6, 34, tzinfo=UTC))
    store.write("lineup", MID_ROUND, label=f"{AWAY_TID}-03", fetched_at=datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    store.write("lineup", MID_ROUND, label=f"{AWAY_TID}-03", fetched_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC))
    sweep = record_from_disk(db, store, season_id=21)
    assert [f.calculated for f in sweep.files] == [False, True]          # name order: 5 Sep, then 22 Sep
    assert sweep.before_season == 1
    assert sweep.to_dict()["recorded"] == 1 and sweep.to_dict()["not_calculated"] == 1
    assert record_from_disk(db, store, season_id=21).to_dict()["duplicates"] == 1
    assert db.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 0


def test_record_from_disk_needs_the_seasons_calendar(db, tmp_path):
    with pytest.raises(NoSeasonCalendar, match="ingest calendar"):
        record_from_disk(db, RawStore(tmp_path / "raw"), season_id=21)
