import json

import numpy as np
import pytest
from fantaclaude.asta.state import (
    AuctionState,
    CostEdited,
    LotSelected,
    Pick,
    SaleAdded,
    SaleRemoved,
    SettingsChanged,
    Snapshot,
    SnapshotError,
    StatusChanged,
    Team,
    apply_snapshot,
    parse_snapshot,
    read_snapshots,
    scrub_label,
)

SETTINGS = {"budget": 500, "game": 2, "roles": {"gk": [2, 2], "mov": [6, 6], "size": [8, 8]}}


def node(picks, *, selected=None, teams=(0, 1, 2, 3), settings=SETTINGS, status="live", locked=False):
    return {"picks": [{"playerId": pid, "teamId": tid, "cost": cost, "value": 1, "index": i, "timestamp": 1000 + i}
                      for i, (pid, tid, cost) in enumerate(picks)],
            "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams], "settings": settings,
            "selectedPlayerId": selected, "turnTeamId": 0, "status": status, "locked": locked}


def replay(snapshots):
    state, log = AuctionState.empty(), []
    for snap in snapshots:
        state, events = apply_snapshot(state, snap)
        log.append(events)
    return state, log


def test_parse_snapshot_reads_the_capture_shaped_node(fixture_file):
    first = read_snapshots(fixture_file("asta_session_sample.jsonl"))[0]
    assert first.picks == () and [t.team_id for t in first.teams] == [0, 1, 2]
    assert [t.label for t in first.teams] == ["host", "Claude", "@bomber"]     # an @ without a domain is a nick, not an address
    assert first.settings["budget"] == 500 and first.settings["roles"]["gk"] == [3, 3]
    assert first.selected is None and first.turn_team == 0 and first.status == "live" and first.locked is False
    assert first.player_list_hash == "sample"


def test_a_sale_an_edit_an_undo_a_resale_a_duplicate_and_an_unknown_player(fixture_file):
    """The scripted fixture, one snapshot per line, and the events each one
    is worth against the one before -- the cases the spec's diff-engine test
    names, plus a re-sale to another team."""
    state, log = replay(read_snapshots(fixture_file("asta_session_sample.jsonl")))
    assert log[0] == (StatusChanged("live", False),)                      # the first snapshot: a baseline, not a sale
    assert log[1] == (SaleAdded(2764, 0, 120),)
    assert log[2] == (SaleAdded(2120, 1, 40),)
    assert log[3] == (CostEdited(2120, 1, 40, 45),)                        # the admin corrected the price
    assert log[4] == (SaleRemoved(2120, 1, 45),)                           # and then undid the lot
    assert log[5] == (SaleAdded(2120, 0, 45), LotSelected(5841))           # re-sold to the host, Svilar on the block
    assert log[6] == ()                                                    # the same snapshot twice is a no-op
    assert log[7] == (SaleAdded(999999, 2, 3), LotSelected(None))          # an id the listone lacks is the advisor's fault to name
    assert state.spent(0) == 165 and state.spent(1) == 0 and state.spent(2) == 3
    assert [p.player_id for p in state.picks_of(0)] == [2764, 2120] and state.team_ids() == (0, 1, 2)
    assert state.picks[2120] == Pick(2120, 0, 45, 2, 1787600120000)


def test_the_state_is_the_last_snapshots_whatever_came_before(fixture_file):
    snapshots = read_snapshots(fixture_file("asta_session_sample.jsonl"))
    replayed, _ = replay(snapshots)
    direct, _ = apply_snapshot(AuctionState.empty(), snapshots[-1])
    assert replayed == direct
    again, events = apply_snapshot(replayed, snapshots[-1])
    assert events == () and again == replayed
    # an undo restores exactly the state before the lot: snapshot 4 is snapshot 1 again
    after_undo, _ = replay(snapshots[:5])
    before_sale, _ = replay(snapshots[:2])
    assert after_undo.picks == before_sale.picks


def test_any_sequence_of_snapshots_converges_on_the_last_one():
    """Property, over seeded random sale sequences: the board is a pure
    function of the feed, so applying every snapshot, applying them in any
    order, and applying only the last one all end in the same state; and
    the credits a team spent are exactly the costs of its picks."""
    rng = np.random.default_rng(11)
    players = list(range(100, 130))
    for _ in range(20):
        snapshots = []
        for _ in range(int(rng.integers(1, 12))):
            chosen = rng.choice(players, size=int(rng.integers(0, 12)), replace=False).tolist()
            picks = [(pid, int(rng.integers(0, 4)), int(rng.integers(1, 60))) for pid in chosen]
            snapshots.append(parse_snapshot(node(picks, selected=int(rng.choice(players)) if rng.random() < 0.5 else None)))
        forward, log = replay(snapshots)
        shuffled = [snapshots[i] for i in rng.permutation(len(snapshots) - 1)] + [snapshots[-1]]
        assert replay(shuffled)[0] == forward == apply_snapshot(AuctionState.empty(), snapshots[-1])[0]
        for team in range(4):
            assert forward.spent(team) == sum(p.cost for p in forward.picks_of(team)) >= 0
        assert all(isinstance(e, (SaleAdded, SaleRemoved, CostEdited, LotSelected, StatusChanged)) for evs in log for e in evs)
        # the events of a step are the exact difference: replaying them onto the picks reproduces the picks
        picks: dict[int, tuple[int, int]] = {}
        for events in log:
            for e in events:
                if isinstance(e, SaleAdded):
                    picks[e.player_id] = (e.team_id, e.cost)
                elif isinstance(e, SaleRemoved):
                    del picks[e.player_id]
                elif isinstance(e, CostEdited):
                    picks[e.player_id] = (e.team_id, e.after)
        assert picks == {pid: (p.team_id, p.cost) for pid, p in forward.picks.items()}


def test_a_pick_moved_to_another_team_and_a_player_listed_twice():
    moved, events = apply_snapshot(apply_snapshot(AuctionState.empty(), parse_snapshot(node([(7, 0, 10)])))[0],
                                   parse_snapshot(node([(7, 1, 12)])))
    assert events == (SaleRemoved(7, 0, 10), SaleAdded(7, 1, 12)) and moved.picks[7].team_id == 1
    twice, _ = apply_snapshot(AuctionState.empty(), parse_snapshot(node([(7, 0, 10), (8, 1, 5), (7, 2, 30)])))
    assert twice.picks[7] == Pick(7, 2, 30, 2, 1002) and twice.duplicates == (7,)     # the later pick by index stood


def test_settings_and_status_changes_are_events_after_the_first_snapshot():
    first, events = apply_snapshot(AuctionState.empty(), parse_snapshot(node([])))
    assert events == (StatusChanged("live", False),)                     # the settings are a baseline the first time
    richer = parse_snapshot(node([], settings={**SETTINGS, "budget": 1000}, status="closed", locked=True))
    second, events = apply_snapshot(first, richer)
    assert events == (SettingsChanged((("budget", 500, 1000),)), StatusChanged("closed", True))
    assert second.settings["budget"] == 1000 and second.status == "closed" and second.locked is True
    _, events = apply_snapshot(second, richer)
    assert events == ()


def test_a_settings_node_that_differs_but_changes_nothing_is_not_an_event():
    """diff_payloads walks with .get(), so {"a": None} and {} are unequal
    dicts holding no change; an event announcing zero changes is a false
    alarm and must not be raised."""
    first, _ = apply_snapshot(AuctionState.empty(), parse_snapshot(node([])))
    hollow = parse_snapshot(node([], settings={**SETTINGS, "cursor": None}))
    same, events = apply_snapshot(first, hollow)
    assert same.settings != first.settings and events == ()
    real, events = apply_snapshot(same, parse_snapshot(node([], settings={**SETTINGS, "cursor": 3})))
    assert events == (SettingsChanged((("cursor", None, 3),)),) and real.settings["cursor"] == 3


def test_labels_are_scrubbed_and_firebase_shaped_lists_are_read():
    raw = {"picks": {"0": {"playerId": 7, "teamId": 0, "cost": 10, "index": 0}, "1": None,
                     "2": {"playerId": 8, "teamId": 1, "cost": 5, "index": 2}},
           "teams": [{"id": 0, "connection": {"label": "someone@example.invalid"}}, {"id": 1, "nick": "  "},
                     {"id": 2, "name": "Marco"}, {"id": 3}],
           "settings": SETTINGS}
    snap = parse_snapshot(raw)
    assert [p.player_id for p in snap.picks] == [7, 8] and snap.picks[1].index == 2
    assert [t.label for t in snap.teams] == ["team 0", "team 1", "Marco", "team 3"]
    assert scrub_label("x@y.invalid", 9) == "team 9" and scrub_label("@bomber", 9) == "@bomber" and scrub_label(None, 9) == "team 9"
    assert "@example" not in json.dumps(snap.to_node())


def test_the_snapshot_round_trips_through_the_feed_shape():
    snap = parse_snapshot(node([(7, 0, 10), (8, 1, 5)], selected=9))
    assert parse_snapshot(snap.to_node()) == snap
    state, _ = apply_snapshot(AuctionState.empty(), snap)
    assert state.to_snapshot() == snap and parse_snapshot(state.to_snapshot().to_node()) == snap
    assert snap.teams[0] == Team(0, "t0")


def test_malformed_nodes_are_refused(tmp_path):
    for bad, text in (({"picks": 5}, "picks is int"), ({"picks": [{"teamId": 0, "cost": 1}]}, "playerId"),
                      ({"picks": [{"playerId": 1, "teamId": 0, "cost": -1}]}, "cost"),
                      ({"picks": [{"playerId": True, "teamId": 0, "cost": 1}]}, "playerId"),
                      ({"picks": [], "locked": "no"}, "locked"), ({"picks": [], "settings": []}, "settings"),
                      ({"picks": [], "teams": [{"connection": {"label": "x"}}]}, "teams\\[0\\].id"),
                      ({"picks": {"a": {}}}, "list indexes"), ([], "not a mapping")):
        with pytest.raises(SnapshotError, match=text):
            parse_snapshot(bad)
    path = tmp_path / "session.jsonl"
    path.write_text(json.dumps(node([])) + "\n\n{not json\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="session.jsonl:3"):
        read_snapshots(path)
    path.write_text(json.dumps(node([])) + "\n" + json.dumps({"picks": 5}) + "\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="session.jsonl:2: picks"):
        read_snapshots(path)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    assert read_snapshots(empty) == []
    assert isinstance(parse_snapshot(node([])), Snapshot)
