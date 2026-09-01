import asyncio
import json

import pytest
from fantaclaude.api.serve import AstaServer, PhaseError
from fantaclaude.asta.adjustments import EMPTY_LAYER, Adjustment, load_adjustments
from fantaclaude.asta.snapshot import read_state
from fantaclaude.asta.state import parse_snapshot
from fantaclaude.commands.asta import AstaPaths, UsageError
from test_advisor import SESSION, pinned_run


def snap(picks, *, selected=None, teams=(0, 1, 2), settings=SESSION, status="live"):
    return parse_snapshot({
        "picks": [{"playerId": pid, "teamId": tid, "cost": cost, "index": i}
                  for i, (pid, tid, cost) in enumerate(picks)],
        "teams": [{"id": t, "connection": {"label": f"t{t}"}} for t in teams],
        "settings": settings, "selectedPlayerId": selected, "status": status, "locked": False})


@pytest.fixture
def server_kit(tmp_path, fixture_json, mcp_fixture_json):
    _result, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    paths = AstaPaths(db=tmp_path / "data" / "fanta.duckdb", adjustments=tmp_path / "data" / "adjustments.yml",
                       state=tmp_path / "data" / "asta-state.json", records=tmp_path / "records", kb=tmp_path / "kb")

    def make(**kw):
        kw.setdefault("run", pinned)
        kw.setdefault("layer", EMPTY_LAYER)
        kw.setdefault("participants", {})
        kw.setdefault("scenario", None)
        kw.setdefault("paths", paths)
        kw.setdefault("mode", "feed")
        kw.setdefault("session_code", "FA-nri-okm")
        return AstaServer(**kw)
    return make, pinned, paths


def sent(server):
    """Subscribe a recording sender; returns the list of decoded messages."""
    messages = []

    async def sender(text):
        messages.append(json.loads(text))
    server.subscribe(sender)
    return messages


async def test_pending_until_the_mapping_screen_answers_then_live(server_kit):
    make, pinned, paths = server_kit
    server = make()
    messages = sent(server)
    assert server.hello()["phase"] == "pending" and server.hello()["board"] is None
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)]))
    assert server.hello()["phase"] == "pending"                 # a snapshot alone does not open the board
    assert messages[-1]["type"] == "hello"
    assert [t["team_id"] for t in server.hello()["teams"]] == [0, 1, 2]
    hello = await server.set_mapping(0, {})
    assert hello["phase"] == "live"
    board = server.hello()["board"]
    assert board is not None and board["picks"] == 1 and board["me"]["credits"] == 500
    assert paths.state.is_file()                                # the state file exists from the first live board
    assert read_state(paths.state).mapping.mine == 0


async def test_snapshots_mutate_broadcast_and_write_the_state_file(server_kit):
    make, pinned, paths = server_kit
    server = make(mapping=None)
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    messages = sent(server)
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)], selected=pids[1]))
    board_msg = messages[-1]
    assert board_msg["type"] == "board"
    assert any("+" in e for e in board_msg["events"]) and any(e.startswith("lot:") for e in board_msg["events"])
    assert board_msg["board"]["selected"] == pids[1]
    stored = read_state(paths.state)
    assert len(stored.snapshot.picks) == 1


async def test_crash_recovery_a_fresh_server_on_the_last_snapshot_equals_the_long_way(server_kit):
    make, pinned, _ = server_kit
    pids = sorted(pinned.players)
    s1, s2, s3 = (snap([(pids[0], 1, 30)]), snap([(pids[0], 1, 30), (pids[1], 0, 12)]),
                  snap([(pids[1], 0, 12)], selected=pids[2]))     # an undo happened in s3
    a = make()
    await a.set_mapping(0, {})
    for s in (s1, s2, s3):
        await a.on_snapshot(s)
    b = make()
    await b.set_mapping(0, {})
    await b.on_snapshot(s3)                                       # the resubscribe's full snapshot
    assert a.auction.board.to_dict() == b.auction.board.to_dict()


async def test_two_concurrent_adjusts_both_land_and_reprice(server_kit):
    make, pinned, paths = server_kit
    server = make()
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    pids = sorted(pinned.players)
    a = Adjustment("value", "limping", player_id=pids[0], factor=0.8)
    b = Adjustment("exclude", "not buying", player_id=pids[1])
    r1, r2 = await asyncio.gather(server.adjust(a), server.adjust(b))
    assert {r1["count"], r2["count"]} == {1, 2}                   # serialised: one saw one entry, the other two
    assert len(load_adjustments(paths.adjustments)) == 2
    assert str(pids[1]) not in server.auction.board.to_dict()["prices"]


async def test_adjust_refuses_an_inert_entry_and_the_pending_phase(server_kit):
    make, _pinned, _ = server_kit
    server = make()
    with pytest.raises(PhaseError):
        await server.adjust(Adjustment("exclude", "why", player_id=1))
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    with pytest.raises(UsageError):
        await server.adjust(Adjustment("exclude", "why", player_id=999_999))


async def test_refresh_rereads_the_file_and_a_malformed_file_leaves_the_layer_standing(server_kit):
    make, pinned, paths = server_kit
    server = make()
    await server.on_snapshot(snap([]))
    await server.set_mapping(0, {})
    pids = sorted(pinned.players)
    paths.adjustments.parent.mkdir(parents=True, exist_ok=True)
    paths.adjustments.write_text(f"- player_id: {pids[0]}\n  type: exclude\n  reason: hand-written\n", encoding="utf-8")
    out = await server.refresh()
    assert str(pids[0]) not in out["board"]["prices"]
    paths.adjustments.write_text("]: not yaml", encoding="utf-8")
    from fantaclaude.asta.adjustments import AdjustmentsError
    with pytest.raises(AdjustmentsError):
        await server.refresh()
    assert str(pids[0]) not in server.auction.board.to_dict()["prices"]   # the previous layer stands


async def test_pending_flags_answer_the_screen_when_the_first_snapshot_arrives(server_kit):
    make, _pinned, _ = server_kit
    server = make(pending_me="t1")
    await server.on_snapshot(snap([]))
    assert server.hello()["phase"] == "live" and server.hello()["mapping"]["mine"] == 1


async def test_bad_pending_flags_fall_back_to_the_screen_with_a_note(server_kit):
    make, _pinned, _ = server_kit
    server = make(pending_me="nobody-by-this-name")
    await server.on_snapshot(snap([]))
    assert server.hello()["phase"] == "pending"
    assert "nobody-by-this-name" in (server.pending_note or "")


async def test_a_map_without_a_me_is_loud_rather_than_dropped(server_kit):
    """`asta serve --session FA-xxx-xxx --map 1=Marco` used to discard every
    --map silently: the pending branch was entered only for --me, so the flags
    vanished, no note appeared, and the pressure model ran with no priors while
    the screen looked exactly like a normal start. Replay mode already refuses
    the same pair loudly; the two modes must not disagree about identical
    flags.

    The dossier here is a membership marker, not a real Participant: nothing
    reads it, because resolve_mapping refuses the missing --me before an
    Auction is ever built -- which is the point being pinned."""
    make, _pinned, _ = server_kit
    server = make(participants={"Marco": None}, pending_maps=("1=Marco",))
    await server.on_snapshot(snap([]))
    assert server.hello()["phase"] == "pending"
    assert "which team is mine?" in (server.pending_note or ""), server.pending_note
    assert "--me/--map" in server.pending_note

    # and a --map that names a dossier nobody has is just as loud
    unknown = make(pending_maps=("1=Nobody",))
    await unknown.on_snapshot(snap([]))
    assert unknown.hello()["phase"] == "pending" and "Nobody" in (unknown.pending_note or "")

    # the flags together still go straight to live, as they always did
    both = make(participants={"Marco": None}, pending_me="0", pending_maps=())
    await both.on_snapshot(snap([]))
    assert both.hello()["phase"] == "live"


async def test_a_dead_sender_is_dropped_not_fatal(server_kit):
    make, _pinned, _ = server_kit
    server = make()

    async def dead(text):
        raise RuntimeError("browser gone")
    server.subscribe(dead)
    messages = sent(server)
    await server.on_snapshot(snap([]))
    assert messages[-1]["type"] == "hello"                        # the healthy sender still heard it


async def test_remapping_mid_run_rebuilds_on_the_same_state(server_kit):
    make, pinned, _ = server_kit
    server = make()
    pids = sorted(pinned.players)
    await server.on_snapshot(snap([(pids[0], 1, 30)]))
    await server.set_mapping(0, {})
    before = server.auction.board.to_dict()
    await server.set_mapping(2, {})
    after = server.auction.board.to_dict()
    assert after["me"]["team_id"] == 2 and after["picks"] == before["picks"]
