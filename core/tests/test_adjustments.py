import json

import pytest
from fantaclaude.asta.adjustments import (
    EMPTY_LAYER,
    Adjustment,
    AdjustmentLayer,
    AdjustmentsError,
    append_adjustment,
    apply_layer,
    file_sha256,
    load_adjustments,
    parse_adjustments,
    resolve,
)
from fantaclaude.asta.pricing import PoolPlayer
from fantaclaude.ingest.names import Candidate

EXAMPLE = """\
- player: Malen             # the listone's spelling, or player_id: 1234
  type: exclude
  reason: not buying him
- player: Bastoni
  type: value
  factor: 0.85              # (0, 2]
  reason: limping, reported in the room
- type: target
  class: Dc                 # a role class
  count: 4                  # the composition to start from
  reason: go heavier on Dc
"""

CANDIDATES = [Candidate(2764, "Martinez L.", "INT", "Inter"), Candidate(2120, "Bastoni", "INT", "Inter"),
              Candidate(5841, "Svilar", "ROM", "Roma"), Candidate(11, "Rossi", "GEN", "Genoa"),
              Candidate(12, "Rossi", "PAR", "Parma"), Candidate(13, "Malen", "ATA", "Atalanta")]


def test_the_documented_file_parses_into_three_kinds():
    got = parse_adjustments(EXAMPLE)
    assert got == [Adjustment("exclude", "not buying him", player="Malen"),
                   Adjustment("value", "limping, reported in the room", player="Bastoni", factor=0.85),
                   Adjustment("target", "go heavier on Dc", role_class="Dc", count=4)]
    assert [a.describe() for a in got] == ["exclude Malen (not buying him)", "value Bastoni x0.85 (limping, reported in the room)",
                                           "target Dc 4 (go heavier on Dc)"]
    assert got[1].to_entry() == {"player": "Bastoni", "type": "value", "factor": 0.85, "reason": "limping, reported in the room"}
    assert parse_adjustments("") == [] and parse_adjustments("# only a comment\n") == []
    assert Adjustment("exclude", "r", player_id=7).describe() == "exclude player_id 7 (r)"


def test_every_malformed_entry_is_refused_by_name():
    for text, match in (("- {player: X, type: bench, reason: r}", "type must be one of"),
                        ("- {player: X, type: exclude}", "reason"), ("- {player: X, type: exclude, reason: '  '}", "reason"),
                        ("- {player: X, type: value, reason: r}", "factor"), ("- {player: X, type: value, factor: 0, reason: r}", "factor"),
                        ("- {player: X, type: value, factor: 2.5, reason: r}", "factor"),
                        ("- {player: X, type: value, factor: heavy, reason: r}", "factor"),
                        ("- {player: X, type: exclude, factor: 0.5, reason: r}", "factor belongs"),
                        ("- {type: target, count: 4, reason: r}", "class must be"), ("- {type: target, class: Xy, count: 4, reason: r}", "class"),
                        ("- {type: target, class: Dc, count: -1, reason: r}", "count"), ("- {type: target, class: Dc, count: 2.5, reason: r}", "count"),
                        ("- {type: target, class: Dc, count: 4, player: X, reason: r}", "names a class"),
                        ("- {player: X, type: exclude, class: Dc, reason: r}", "belong to a target"),
                        ("- {player: X, type: exclude, foo: 1, reason: r}", "unknown key"),
                        ("- {player: X, player_id: 3, type: exclude, reason: r}", "name the player once"),
                        ("- {type: exclude, reason: r}", "name the player once"), ("- {player: '', type: exclude, reason: r}", "spelling"),
                        ("- {player_id: true, type: exclude, reason: r}", "player_id"), ("- {player_id: -1, type: exclude, reason: r}", "player_id"),
                        ("- 5", "must be a mapping"), ("player: X", "top level must be a list"), ("- {player: X, type: [", "adjustments.yml")):
        with pytest.raises(AdjustmentsError, match=match):
            parse_adjustments(text)
    with pytest.raises(AdjustmentsError, match="entry 2"):
        parse_adjustments("- {player: X, type: exclude, reason: r}\n- {player: Y, type: nope, reason: r}\n")


def test_append_keeps_the_text_and_replaces_atomically(tmp_path):
    path = tmp_path / "data" / "adjustments.yml"
    assert load_adjustments(path) == [] and file_sha256(path) == ""
    first = append_adjustment(path, Adjustment("exclude", "not buying him", player="Malen"))
    assert first == [Adjustment("exclude", "not buying him", player="Malen")]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# adjustments.yml") and "- player: Malen\n  type: exclude\n  reason: not buying him\n" in text
    path.write_text(text + "# a hand-written note stays\n", encoding="utf-8")
    second = append_adjustment(path, Adjustment("value", "limping", player="Bastoni", factor=0.85))
    assert second == first + [Adjustment("value", "limping", player="Bastoni", factor=0.85)]
    assert "# a hand-written note stays" in path.read_text(encoding="utf-8")
    assert load_adjustments(path) == second and len(file_sha256(path)) == 64
    assert sorted(p.name for p in path.parent.iterdir()) == ["adjustments.yml"]       # no temp file left behind
    third = append_adjustment(path, Adjustment("target", "go heavier", role_class="Dc", count=4))
    assert third[-1].to_entry() == {"type": "target", "class": "Dc", "count": 4, "reason": "go heavier"}
    # a hand edit missing its trailing newline is not glued onto the new entry
    no_trailing_newline = path.read_text(encoding="utf-8").rstrip("\n") + "\n# no trailing newline below this line"
    path.write_text(no_trailing_newline, encoding="utf-8")
    fourth = append_adjustment(path, Adjustment("exclude", "r", player="Svilar"))
    assert fourth == third + [Adjustment("exclude", "r", player="Svilar")]
    written = path.read_text(encoding="utf-8")
    assert "# no trailing newline below this line\n- player: Svilar\n  type: exclude\n  reason: r\n" in written
    # a file someone broke by hand is not appended to: the append would have hidden the break
    path.write_text("- {player: X, type: nope, reason: r}\n", encoding="utf-8")
    with pytest.raises(AdjustmentsError, match="entry 1"):
        append_adjustment(path, Adjustment("exclude", "r", player="Malen"))
    assert path.read_text(encoding="utf-8") == "- {player: X, type: nope, reason: r}\n"
    with pytest.raises(AdjustmentsError):
        load_adjustments(path)


def test_resolve_binds_names_to_the_run_and_names_what_it_cannot():
    adjustments = parse_adjustments(EXAMPLE) + parse_adjustments(
        "- {player: Nobody, type: exclude, reason: r}\n- {player: Rossi, type: value, factor: 0.5, reason: r}\n"
        "- {player_id: 424242, type: exclude, reason: r}\n- {player: Bastoni, type: value, factor: 0.7, reason: later wins}\n"
        "- {player: 'Rossi M.', type: exclude, reason: r}\n- {type: target, class: Dc, count: 3, reason: later wins}\n")
    layer = resolve(adjustments, CANDIDATES, sha256="abc")
    assert layer.excluded == {13} and layer.value_factor == {2120: 0.7} and layer.targets == {"Dc": 3}    # later entries win
    assert layer.factor(2120) == 0.7 and layer.factor(2764) == 1.0 and layer.sha256 == "abc"
    assert len(layer.problems) == 4
    assert "'Nobody' is not in the pinned run" in layer.problems[0] and "inert" in layer.problems[0]
    assert "'Rossi' is 2 players of the run ('Rossi', 'Rossi'); add the initial" in layer.problems[1]     # two clubs, no initial
    assert "player_id 424242 is not in the pinned run" in layer.problems[2]
    assert "'Rossi M.' is not how the listone spells 'Rossi', 'Rossi'" in layer.problems[3]
    assert [e.player_id for e in layer.entries] == [13, 2120, None, None, None, None, 2120, None, None]
    d = json.loads(json.dumps(layer.to_dict()))
    assert d["count"] == 9 and d["applied"] == 5 and d["excluded"] == [13] and d["value_factor"] == {"2120": 0.7}
    assert EMPTY_LAYER == AdjustmentLayer((), {}, frozenset(), {}, ()) and resolve([], CANDIDATES) == EMPTY_LAYER


def test_apply_layer_scales_the_three_quantiles_together():
    pool = (PoolPlayer(2120, "Bastoni", "Dc", 80.0, 100.0, 120.0, 14), PoolPlayer(2764, "Martinez L.", "Pc", 200.0, 240.0, 280.0, 35))
    layer = resolve([Adjustment("value", "limping", player="Bastoni", factor=0.85)], CANDIDATES)
    scaled = apply_layer(pool, layer)
    assert scaled[0] == PoolPlayer(2120, "Bastoni", "Dc", 68.0, 85.0, 102.0, 14) and scaled[1] == pool[1]
    assert apply_layer(pool, EMPTY_LAYER) is pool
