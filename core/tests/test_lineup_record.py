from datetime import UTC, datetime

import pytest
from fantaclaude.analysis.weekly import RosterPlayer
from fantaclaude.analysis.weekly.submitted import (
    RunXi,
    SubmissionError,
    build_submission,
    export_submitted_record,
    record_submitted,
)
from fantaclaude.model.modules import Module, Slot
from fantaclaude.model.roles import Role

R = frozenset
SMALL = Module(code="t", label="test", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R({Role.B}), R({Role.Ds})),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("A/Pc", R({Role.A, Role.Pc}), R({Role.W}), R({Role.T}))))
MODULES = {"t": SMALL}
ROSTER = [RosterPlayer(1, "Svilar", R({Role.Por}), 1, True), RosterPlayer(2, "Radunovic", R({Role.Por}), 1, True),
          RosterPlayer(3, "Bastoni", R({Role.Dc}), 1, True), RosterPlayer(4, "Kolasinac", R({Role.B}), 1, True),
          RosterPlayer(5, "Zielinski", R({Role.M}), 1, True), RosterPlayer(6, "Calhanoglu", R({Role.C, Role.T}), 1, True),
          RosterPlayer(7, "Martinez L.", R({Role.A}), 1, True), RosterPlayer(8, "Politano", R({Role.W}), 1, True),
          RosterPlayer(9, "Kean", R({Role.A}), 1, True), RosterPlayer(10, "Sabelli", R({Role.Ds}), 1, True)]
RUN = RunXi(7, "t", [{"slot": "Por", "player_id": 1, "name": "Svilar"}, {"slot": "Dc", "player_id": 3, "name": "Bastoni"},
                     {"slot": "M/C", "player_id": 6, "name": "Calhanoglu"}, {"slot": "A/Pc", "player_id": 7, "name": "Martinez L."}],
            [{"player_id": 2, "name": "Radunovic"}, {"player_id": 9, "name": "Kean"}, {"player_id": 4, "name": "Kolasinac"}], 4242, False)


def test_the_runs_xi_is_recorded_as_it_stood():
    s = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"])
    assert s.module == "t" and s.lineup_run_id == 7
    assert [(x["slot"], x["player_id"]) for x in s.xi] == [("Por", 1), ("Dc", 3), ("M/C", 6), ("A/Pc", 7)]
    assert [b["player_id"] for b in s.bench] == [2, 9, 4]


def test_a_swap_replaces_the_starter_and_sends_him_to_the_bench_place_of_the_man_who_came_in():
    s = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("Martinez L.", "Kean")])
    assert [x["player_id"] for x in s.xi] == [1, 3, 6, 9] and [b["player_id"] for b in s.bench] == [2, 7, 4]
    by_id = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("7", "9")])
    assert [x["player_id"] for x in by_id.xi] == [1, 3, 6, 9]
    adapted = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("Bastoni", "Kolasinac")])
    assert [x["player_id"] for x in adapted.xi] == [1, 4, 6, 7]                     # B at Dc is an adapted, legal fit
    assert [b["player_id"] for b in adapted.bench] == [2, 9, 3]


def test_every_illegal_submission_is_refused_by_name():
    for kw, match in (({"swaps": [("Kean", "Martinez L.")]}, "is not in run 7's XI"),
                      ({"swaps": [("Martinez L.", "Bastoni")]}, "already in the XI"),
                      ({"swaps": [("Martinez L.", "Nobody")]}, "not on my roster"),
                      ({"swaps": [("Martinez L.", "Radunovic")]}, "cannot field"),          # a second Por at A/Pc: no fit
                      ({"swaps": [("Bastoni", "Sabelli")]}, "cannot field"),                # Ds at Dc is forced-only
                      ({"module": "352"}, "not permitted"),
                      ({"xi_names": ["Svilar", "Bastoni", "Calhanoglu", "Martinez L."]}, "--xi needs --module"),
                      ({"module": "t", "xi_names": ["Svilar", "Bastoni", "Calhanoglu"]}, "distinct players"),
                      ({"module": "t", "xi_names": ["Svilar", "Bastoni", "Calhanoglu", "Martinez L."], "bench_names": ["Bastoni"]}, "both in the XI and on the bench")):
        with pytest.raises(SubmissionError, match=match):
            build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], **kw)
    with pytest.raises(SubmissionError, match="no lineup run"):
        build_submission(roster=ROSTER, run=None, modules=MODULES, allowed=["t"])


def test_a_full_xi_needs_no_run_and_takes_its_slots_from_the_module():
    s = build_submission(roster=ROSTER, run=None, modules=MODULES, allowed=["t"], module="t",
                         xi_names=["Kean", "Svilar", "Kolasinac", "Zielinski"], bench_names=["Radunovic"])
    assert s.lineup_run_id is None and [(x["slot"], x["name"]) for x in s.xi] == [("Por", "Svilar"), ("Dc", "Kolasinac"),
                                                                                    ("M/C", "Zielinski"), ("A/Pc", "Kean")]


def test_record_appends_and_the_newest_is_current(db, tmp_path):
    s = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"])
    first = record_submitted(db, season_id=21, giornata=4, submission=s, my_team=4242, source="hand",
                             now=datetime(2026, 9, 11, 17, 0, tzinfo=UTC))
    swapped = build_submission(roster=ROSTER, run=RUN, modules=MODULES, allowed=["t"], swaps=[("Martinez L.", "Kean")])
    second = record_submitted(db, season_id=21, giornata=4, submission=swapped, my_team=4242, source="hand",
                              now=datetime(2026, 9, 11, 18, 0, tzinfo=UTC))
    assert second == first + 1 and db.execute("SELECT count(*) FROM lineup_submitted").fetchone()[0] == 2
    current = db.execute("SELECT submitted_id, module, source, lineup_run_id FROM v_lineup_submitted_current").fetchone()
    assert current == (second, "t", "hand", 7)
    paths = export_submitted_record(db, second, tmp_path / "records")
    assert [p.parent.name for p in paths] == ["lineup_submitted"] and paths[0].name.endswith(f"-{second}.parquet")
    assert export_submitted_record(db, second, tmp_path / "records") == []                     # never rewritten
