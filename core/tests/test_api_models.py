"""The wire contract: BoardPayload mirrors Board.to_dict() field for field.

A field the advisor emits that the model does not know is a validation error
(extra="forbid"); a field the model names that the advisor stopped emitting
is a missing-field error. Either way the drift is a red test here, not a
blank dashboard on auction night.
"""
from fantaclaude.api.models import AdjustIn, BoardPayload, HelloPayload, board_payload
from fantaclaude.asta.adjustments import Adjustment, resolve
from fantaclaude.asta.advisor import TeamMapping, derive
from test_advisor import node, pinned_run


def _rich_board(tmp_path, fixture_json, mcp_fixture_json):
    """A board with every optional branch populated: picks, a lot on the
    block, pressure, adjustments of all three kinds, session settings."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    pids = sorted(pinned.players)
    layer = resolve([Adjustment("value", "limping", player_id=pids[0], factor=0.9),
                     Adjustment("exclude", "not buying him", player_id=pids[1]),
                     Adjustment("target", "heavier here", role_class="Pc", count=2)],
                    pinned.candidates(), sha256="ab" * 32)
    state = node([(pids[2], 1, 30), (pids[3], 0, 12)], selected=pids[4])
    return derive(state, run=pinned, settings=pinned.league, layer=layer,
                  mapping=TeamMapping(mine=0, nicks={1: "Marco"}), participants={})


def test_board_payload_round_trips_the_advisors_own_dict(tmp_path, fixture_json, mcp_fixture_json):
    board = _rich_board(tmp_path, fixture_json, mcp_fixture_json)
    raw = board.to_dict()
    payload = board_payload(board)
    assert payload.model_dump(by_alias=True, mode="json") == raw
    assert payload.lot is not None and payload.lot_pressure is not None
    assert payload.adjustments.count == 3 and len(payload.adjustments.excluded) == 1
    some_row = next(iter(payload.prices.values()))
    assert some_row.pressure is not None and some_row.band.p25 <= some_row.band.p75


def test_an_unknown_field_is_a_red_test_not_a_silent_pass(tmp_path, fixture_json, mcp_fixture_json):
    import pytest
    board = _rich_board(tmp_path, fixture_json, mcp_fixture_json)
    raw = board.to_dict()
    raw["a_field_2b_does_not_know"] = 1
    with pytest.raises(Exception):  # noqa: B017 -- pydantic's own ValidationError, deliberately unqualified
        BoardPayload.model_validate(raw)


def test_hello_and_adjust_models_carry_the_envelope():
    hello = HelloPayload.model_validate({
        "phase": "pending", "mode": "feed", "session_code": "FA-nri-okm", "feed": "offline",
        "run": "run 20260830 · …", "scenario": None, "settings": None, "league_conflicts": [], "note": None,
        "teams": [{"team_id": 0, "label": "me"}], "participants": ["Marco"], "mapping": None, "board": None})
    assert hello.phase == "pending" and hello.board is None
    adj = AdjustIn.model_validate({"type": "target", "class": "Dc", "count": 4, "reason": "go heavier"})
    assert adj.role_class == "Dc"
    assert AdjustIn.model_validate({"type": "value", "player": "Bastoni", "factor": 0.85,
                                    "reason": "limping"}).factor == 0.85
