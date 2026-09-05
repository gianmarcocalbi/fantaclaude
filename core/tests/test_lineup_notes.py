import pytest
from fantaclaude.analysis.weekly.notes import (
    EMPTY_NOTES,
    LineupNote,
    LineupNotesError,
    append_lineup_note,
    load_lineup_notes,
    parse_lineup_notes,
    resolve_notes,
)
from fantaclaude.ingest.names import Candidate

EXAMPLE = """\
- player: Kean               # the listone's spelling, or player_id: 2097
  giornata: 4
  type: p_start
  p_start: 0.0               # 0..1: the probability of a voto, set outright
  reason: out, club statement on Thursday
- player: Bastoni
  giornata: 4
  type: value
  factor: 0.85               # (0, 2]: scales the expected fantavoto if he plays
  reason: carrying a knock, played through it in Europe
- player_id: 2764
  giornata: 3
  type: exclude
  reason: rested against my better judgement last week
"""

CANDIDATES = [Candidate(2764, "Martinez L.", "INT", "Inter"), Candidate(2120, "Bastoni", "INT", "Inter"),
              Candidate(2097, "Kean", "FIO", "Fiorentina"), Candidate(11, "Rossi", "GEN", "Genoa"),
              Candidate(12, "Rossi", "PAR", "Parma")]


def test_the_documented_file_parses_into_three_kinds():
    got = parse_lineup_notes(EXAMPLE)
    assert got == [LineupNote("p_start", 4, "out, club statement on Thursday", player="Kean", p_start=0.0),
                   LineupNote("value", 4, "carrying a knock, played through it in Europe", player="Bastoni", factor=0.85),
                   LineupNote("exclude", 3, "rested against my better judgement last week", player_id=2764)]
    assert [n.describe() for n in got] == ["p_start Kean -> 0.00 for giornata 4 (out, club statement on Thursday)",
                                           "value Bastoni x0.85 for giornata 4 (carrying a knock, played through it in Europe)",
                                           "exclude player_id 2764 for giornata 3 (rested against my better judgement last week)"]
    assert got[0].to_entry() == {"player": "Kean", "giornata": 4, "type": "p_start", "p_start": 0.0,
                                 "reason": "out, club statement on Thursday"}
    assert parse_lineup_notes("") == [] and parse_lineup_notes("# only a comment\n") == []


def test_every_malformed_entry_is_refused_by_name():
    for text, match in (("- {player: X, giornata: 4, type: bench, reason: r}", "type must be one of"),
                        ("- {player: X, type: exclude, reason: r}", "giornata"),
                        ("- {player: X, giornata: 0, type: exclude, reason: r}", "giornata"),
                        ("- {player: X, giornata: 4.5, type: exclude, reason: r}", "giornata"),
                        ("- {player: X, giornata: 4, type: exclude}", "reason"),
                        ("- {player: X, giornata: 4, type: p_start, reason: r}", "p_start must be"),
                        ("- {player: X, giornata: 4, type: p_start, p_start: 1.5, reason: r}", "p_start must be"),
                        ("- {player: X, giornata: 4, type: value, reason: r}", "factor must be"),
                        ("- {player: X, giornata: 4, type: value, factor: 0, reason: r}", "factor must be"),
                        ("- {player: X, giornata: 4, type: exclude, factor: 0.5, reason: r}", "factor belongs"),
                        ("- {player: X, giornata: 4, type: exclude, p_start: 0.5, reason: r}", "p_start belongs"),
                        ("- {player: X, giornata: 4, type: exclude, foo: 1, reason: r}", "unknown key"),
                        ("- {player: X, player_id: 3, giornata: 4, type: exclude, reason: r}", "name the player once"),
                        ("- {giornata: 4, type: exclude, reason: r}", "name the player once"),
                        ("- {player: '', giornata: 4, type: exclude, reason: r}", "spelling"),
                        ("- {player_id: -1, giornata: 4, type: exclude, reason: r}", "player_id"),
                        ("- 5", "must be a mapping"), ("player: X", "top level must be a list"),
                        ("- {player: X, type: [", "lineup-notes.yml")):
        with pytest.raises(LineupNotesError, match=match):
            parse_lineup_notes(text)
    with pytest.raises(LineupNotesError, match="entry 2"):
        parse_lineup_notes("- {player: X, giornata: 4, type: exclude, reason: r}\n- {player: Y, giornata: 4, type: nope, reason: r}\n")


def test_append_keeps_the_text_and_replaces_atomically(tmp_path):
    path = tmp_path / "data" / "lineup-notes.yml"
    assert load_lineup_notes(path) == []
    first = append_lineup_note(path, LineupNote("exclude", 4, "not this week", player="Kean"))
    assert first == [LineupNote("exclude", 4, "not this week", player="Kean")]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# lineup-notes.yml") and "- player: Kean\n  giornata: 4\n  type: exclude\n  reason: not this week\n" in text
    path.write_text(text + "# a hand-written note stays\n", encoding="utf-8")
    second = append_lineup_note(path, LineupNote("p_start", 4, "confirmed", player="Bastoni", p_start=1.0))
    assert len(second) == 2 and "# a hand-written note stays" in path.read_text(encoding="utf-8")
    path.write_text("- {player: X, giornata: 4, type: nope, reason: r}\n", encoding="utf-8")
    with pytest.raises(LineupNotesError, match="type must be one of"):
        append_lineup_note(path, LineupNote("exclude", 4, "r", player="Kean"))      # a broken file is not appended to


def test_resolve_binds_this_giornata_and_leaves_the_others_inert():
    notes = parse_lineup_notes(EXAMPLE) + [LineupNote("p_start", 4, "later word: fit", player="Kean", p_start=0.6),
                                           LineupNote("exclude", 4, "typo", player="Rossi"),
                                           LineupNote("value", 4, "gone", player="Nobody", factor=0.5)]
    layer = resolve_notes(notes, CANDIDATES, giornata=4)
    assert layer.giornata == 4 and layer.inert == 1                                     # the giornata-3 exclusion
    assert layer.p_start == {2097: (0.6, "later word: fit")}                             # the later entry wins
    assert layer.value_factor == {2120: (0.85, "carrying a knock, played through it in Europe")}
    assert layer.excluded == {}
    assert len(layer.problems) == 2
    assert "add the initial the listone uses" in layer.problems[0] and "'Nobody' is not in the listone" in layer.problems[1]
    everything = resolve_notes(notes, CANDIDATES, giornata=None)
    assert everything.inert == 0 and everything.excluded == {2764: "rested against my better judgement last week"}
    assert EMPTY_NOTES.p_start == {} and EMPTY_NOTES.inert == 0
