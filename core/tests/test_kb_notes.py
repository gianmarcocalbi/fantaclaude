from datetime import date

import pytest
from fantaclaude.kb.audit import audit
from fantaclaude.kb.notes import (
    DEPTHS,
    NoteError,
    PlayerNote,
    load_note,
    load_player_notes,
    misdeclared_team_notes,
    misplaced_notes,
    orphan_notes,
)

NOTE = """---
updated: 2026-08-30
ttl: 7d
confidence: medium
source: "sky.it 2026-08-30"
player_id: {player_id}
name: {name}
team_short: {short}
depth: {depth}
availability: {availability}
{extra}---

# {name}

Why the number above is what it is.
"""


def _write(kb, slug, *, player_id=2764, name="Martinez L.", short="INT", depth="starter", availability="1.0",
           extra="", filename=None):
    folder = kb / "serie-a" / "teams" / slug / "players"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (filename or f"{name.lower().replace(' ', '-').replace('.', '')}.md")
    path.write_text(NOTE.format(player_id=player_id, name=name, short=short, depth=depth,
                                availability=availability, extra=extra), encoding="utf-8")
    return path


def test_load_note_reads_the_structured_front_matter(tmp_path):
    path = _write(tmp_path / "kb", "inter", extra="prior_fantamedia: 6.8\n")
    note = load_note(path)
    assert isinstance(note, PlayerNote)
    assert (note.player_id, note.name, note.team_short, note.depth) == (2764, "Martinez L.", "INT", "starter")
    assert note.availability == 1.0 and note.prior_fantamedia == 6.8 and note.path == path
    assert note.front_matter.updated == date(2026, 8, 30)
    assert DEPTHS == ("starter", "contested", "cover", "out")


def test_depth_is_optional_and_availability_defaults_to_one(tmp_path):
    path = _write(tmp_path / "kb", "inter")
    text = path.read_text(encoding="utf-8").replace("depth: starter\n", "").replace("availability: 1.0\n", "")
    path.write_text(text, encoding="utf-8")
    note = load_note(path)
    assert note.depth is None and note.availability == 1.0 and note.prior_fantamedia is None


@pytest.mark.parametrize("edit, message", [
    (lambda t: t.replace("depth: starter", "depth: titolare"), "depth"),
    (lambda t: t.replace("availability: 1.0", "availability: 1.5"), "availability"),
    (lambda t: t.replace("player_id: 2764", "player_id: lautaro"), "player_id"),
    (lambda t: t.replace("team_short: INT", "team_short: Inter"), "team_short"),
    (lambda t: t.replace("---\nupdated", "updated", 1), "front-matter"),
    (lambda t: t.replace("name: Martinez L.\n", ""), "name"),
])
def test_load_note_fails_loud(tmp_path, edit, message):
    path = _write(tmp_path / "kb", "inter")
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(NoteError, match=message):
        load_note(path)


def test_prior_fantamedia_must_be_a_plausible_voto(tmp_path):
    path = _write(tmp_path / "kb", "inter", extra="prior_fantamedia: 12\n")
    with pytest.raises(NoteError, match="prior_fantamedia"):
        load_note(path)


def test_load_player_notes_keys_by_id_and_refuses_duplicates(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "inter")
    _write(kb, "napoli", player_id=6052, name="Hojlund", short="NAP", depth="contested", availability="0.8")
    notes = load_player_notes(kb)
    assert set(notes) == {2764, 6052} and notes[6052].availability == 0.8
    assert load_player_notes(tmp_path / "nowhere") == {}
    _write(kb, "milan", player_id=2764, name="Martinez L.", short="INT", filename="dupe.md")
    with pytest.raises(NoteError, match="2764"):
        load_player_notes(kb)


def test_misplaced_notes_name_the_folder_the_note_should_be_in(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "inter")
    _write(kb, "napoli", player_id=6052, name="Hojlund", short="NAP")
    notes = load_player_notes(kb)
    moved = misplaced_notes(notes, {2764: "Inter", 6052: "Atalanta"})            # Hojlund moved club in the listone
    assert [(n.player_id, slug) for n, slug in moved] == [(6052, "atalanta")]
    assert misplaced_notes(notes, {2764: "Inter"}) == []                          # a player no longer in the listone is not misplaced


def test_orphan_notes_name_a_player_id_the_listone_does_not_have(tmp_path):
    """A note for an id the listone lacks is never looked up by build_inputs
    -- it has no effect -- but it still enters inputs_hash, so a run with it
    looks like a new run even though nothing in it applied."""
    kb = tmp_path / "kb"
    _write(kb, "inter")
    _write(kb, "napoli", player_id=999999, name="Nobody", short="NAP")
    notes = load_player_notes(kb)
    assert [n.player_id for n in orphan_notes(notes, {2764: "Inter"})] == [999999]
    assert orphan_notes(notes, {2764: "Inter", 999999: "Napoli"}) == []


def test_misdeclared_team_notes_name_the_listones_own_code(tmp_path):
    """team_short is validated as a well-formed code at load time but never
    checked against the player it names; a transfer the profile missed
    leaves a note that reads as the wrong club."""
    kb = tmp_path / "kb"
    _write(kb, "inter", short="INT")
    _write(kb, "napoli", player_id=6052, name="Hojlund", short="NAP")
    notes = load_player_notes(kb)
    mismatched = misdeclared_team_notes(notes, {2764: "ATA", 6052: "NAP"})   # Martinez L. moved to Atalanta
    assert [(n.player_id, short) for n, short in mismatched] == [(2764, "ATA")]
    assert misdeclared_team_notes(notes, {2764: "INT", 6052: "NAP"}) == []
    assert misdeclared_team_notes(notes, {6052: "NAP"}) == []               # a player the listone no longer has is not checked


def test_the_audit_validates_notes(tmp_path):
    kb = tmp_path / "kb"
    good = _write(kb, "inter")
    bad = _write(kb, "napoli", player_id=6052, name="Hojlund", short="NAP", depth="titolare")
    statuses = {e.path: e.status for e in audit(kb, date(2026, 8, 31))}
    assert statuses[str(good.relative_to(kb))] == "ok"
    assert statuses[str(bad.relative_to(kb))] == "invalid"
