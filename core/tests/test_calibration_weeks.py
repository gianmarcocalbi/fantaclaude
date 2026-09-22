import itertools
import json
from datetime import UTC, datetime

import pytest
from conftest import (
    FIXTURE_DIR,
    seed_fixtures,
    seed_lineup_run,
    seed_listone,
    seed_rosters,
)
from fantaclaude.analysis.calibration.errors import CalibrationError
from fantaclaude.analysis.calibration.weeks import best_xi, score_run_xi, week
from fantaclaude.analysis.weekly.xi import RosterPlayer
from fantaclaude.ingest.match_scores import STATUS_VOTO, parse_match, record_match
from fantaclaude.ingest.raw import RawStore
from fantaclaude.model.modules import Fit, Module, Slot, load_modules
from fantaclaude.model.roles import Role
from test_lineup_api import AWAY_BENCH, AWAY_TID, AWAY_XI, HOME_TID, ROLES

CALCULATED = json.loads((FIXTURE_DIR / "lineup_calculated_sample.json").read_text(encoding="utf-8"))
R = frozenset
TINY = Module("t", "tiny", (Slot("Por", R({Role.Por}), R(), R()), Slot("Dc", R({Role.Dc}), R({Role.Ds}), R()),
                            Slot("A", R({Role.A}), R({Role.Pc}), R())))


def _player(pid, *roles):
    return RosterPlayer(pid, f"p{pid}", frozenset(roles), 1, True)


def _brute_force(roster, fantavoti, module):
    available = [p for p in roster if p.player_id in fantavoti]
    best = None
    for chosen in itertools.permutations(available, len(module.slots)):
        total = 0.0
        for slot, p in zip(module.slots, chosen, strict=True):
            fit = slot.fit(p.roles)
            if fit is Fit.NATURAL:
                total += fantavoti[p.player_id]
            elif fit is Fit.ADAPTED:
                total += fantavoti[p.player_id] - 1.0
            else:
                break
        else:
            best = total if best is None else max(best, total)
    return best


def test_best_xi_agrees_with_brute_force_on_a_small_roster():
    roster = [_player(1, Role.Por), _player(2, Role.Por), _player(3, Role.Dc), _player(4, Role.Ds),
              _player(5, Role.A), _player(6, Role.Pc)]
    fantavoti = {1: 6.0, 3: 5.5, 4: 8.0, 5: 6.0, 6: 7.5}              # 2 got no voto
    best = best_xi(roster, fantavoti, {"t": TINY}, ["t"])
    assert best.total == pytest.approx(_brute_force(roster, fantavoti, TINY)) == pytest.approx(19.5)
    assert [(s.player_id, s.fit) for s in best.slots] == [(1, "natural"), (4, "adapted"), (6, "adapted")]
    assert best.exact and best.missing == []


def test_best_xi_is_none_when_the_players_who_played_cannot_fill_a_module():
    roster = [_player(3, Role.Dc), _player(5, Role.A), _player(1, Role.Por)]
    assert best_xi(roster, {3: 6.0, 5: 6.0}, {"t": TINY}, ["t"]) is None


def test_best_xi_refuses_a_permitted_module_the_table_lacks():
    with pytest.raises(CalibrationError, match="zz"):
        best_xi([_player(1, Role.Por)], {1: 6.0}, {"t": TINY}, ["zz"])


def test_score_run_xi_is_exact_with_every_voto_and_a_lower_bound_otherwise():
    xi = [{"slot": "Por", "player_id": 1, "name": "Uno", "fit": "natural"},
          {"slot": "Dc", "player_id": 4, "name": "Quattro", "fit": "adapted"},
          {"slot": "A", "player_id": 5, "name": "Cinque", "fit": "natural"}]
    full = score_run_xi(xi, {1: 6.0, 4: 8.0, 5: 6.0}, "t")
    assert full.exact and full.total == pytest.approx(19.0) and full.missing == []
    short = score_run_xi(xi, {1: 6.0, 4: 8.0}, "t")
    assert not short.exact and short.total == pytest.approx(13.0) and short.missing == ["Cinque"]
    assert short.slots[2].fantavoto is None


def _my_week(db, tmp_path, *, refusal=None):
    seed_listone(db, [(pid, f"p{pid}", "Club", "C", [r.value for r in ROLES[pid]]) for pid in ROLES])
    seed_rosters(db, 2578630, 21, {AWAY_TID: ("Mine", {pid: 1 for pid in AWAY_XI + AWAY_BENCH}),
                                   HOME_TID: ("Theirs", {5116: 1})})
    seed_fixtures(db, 21, {3: [datetime(2026, 9, 4, 18, 45, tzinfo=UTC)]})
    raw = RawStore(tmp_path / "raw").write("lineup", CALCULATED, label=f"{AWAY_TID}-03")
    record_match(db, raw, CALCULATED, season_id=21)
    fantavoti = {p.player_id: p.fantavoto for p in parse_match(CALCULATED).players
                 if p.team_id == AWAY_TID and p.status == STATUS_VOTO}
    modules = load_modules()
    return week(db, season_id=21, giornata=3, my_team=AWAY_TID, fantavoti=fantavoti, modules=modules,
                allowed=sorted(modules), refusal=refusal)


def test_week_reads_my_side_orients_the_result_and_simulates_no_substitution(db, tmp_path):
    w = _my_week(db, tmp_path)
    assert (w.my_total, w.opponent_total, w.result, w.points) == (67.0, 82.5, "1-4", 0)
    assert (w.opponent, w.opponent_name, w.module) == (HOME_TID, "Theirs", "3421")
    assert w.eleven_total == 57.0 and w.eleven_missing == ["p6844"] and w.bench_added == 10.0
    assert w.best is not None and w.best.total >= w.my_total           # what the platform fielded was one legal eleven
    assert w.left_on_bench == pytest.approx(w.best.total - 67.0)
    assert w.model_xi is None and "no forecast" in w.model_note
    assert "earliest" in w.roster_note                                 # the seeded snapshot postdates the kickoff
    assert len(w.fielded) == 23 and [f.part for f in w.fielded[:11]] == ["xi"] * 11
    rowe = next(f for f in w.fielded if f.player_id == 6844)
    assert rowe.part == "xi" and rowe.status == "absent"
    adams = next(f for f in w.fielded if f.player_id == 6646)
    assert adams.part == "bench" and adams.fantavoto == 10.0


def test_week_scores_the_models_xi_from_the_newest_honest_run(db, tmp_path):
    xi = [{"slot": "X", "player_id": pid, "name": f"p{pid}", "fit": "natural"} for pid in AWAY_XI]
    seed_lineup_run(db, 21, 3, [], module="3421", xi=xi, my_team=AWAY_TID)
    w = _my_week(db, tmp_path)
    assert w.model_xi.module == "3421" and not w.model_xi.exact
    assert w.model_xi.missing == ["p6844"] and w.model_xi.total == pytest.approx(57.0)
    assert w.lineup_run_id == 1


def test_week_refuses_the_best_and_the_model_under_a_modifier(db, tmp_path):
    w = _my_week(db, tmp_path, refusal="a scoring modifier is active (D-Factor)")
    assert w.best is None and w.best_note == "a scoring modifier is active (D-Factor)"
    assert w.model_xi is None and w.model_note == w.best_note and w.my_total == 67.0


def test_week_is_none_without_a_recorded_match(db):
    assert week(db, season_id=21, giornata=3, my_team=AWAY_TID, fantavoti={}, modules={}, allowed=[],
                refusal=None) is None
