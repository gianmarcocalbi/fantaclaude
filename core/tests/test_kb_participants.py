from datetime import date

import pytest
from fantaclaude.kb.audit import audit
from fantaclaude.kb.participants import (
    BUDGET_STYLES,
    Participant,
    ParticipantError,
    load_participant,
    load_participants,
)

DOSSIER = """---
updated: 2026-09-01
ttl: 90d
confidence: medium
source: "interview 2026-09-01"
nick: {nick}
team: {team}
budget_style: {style}
favourite_clubs: [Juventus]
overpays: [Pc, A]
avoids: [Por]
{extra}---

# {nick}

Spends early, chases Juventus players, never pays for a goalkeeper.
"""


def _write(kb, nick, *, team="Sanzimippi FC", style="early", extra="", filename=None):
    folder = kb / "league" / "participants"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (filename or f"{nick.lower()}.md")
    path.write_text(DOSSIER.format(nick=nick, team=team, style=style, extra=extra), encoding="utf-8")
    return path


def test_load_participant_reads_the_fixed_schema(tmp_path):
    path = _write(tmp_path / "kb", "Marco", extra="max_single_share: 0.3\n")
    p = load_participant(path)
    assert isinstance(p, Participant)
    assert (p.nick, p.team, p.budget_style) == ("Marco", "Sanzimippi FC", "early")
    assert p.favourite_clubs == ("Juventus",) and p.overpays == ("Pc", "A") and p.avoids == ("Por",)
    assert p.max_single_share == 0.3 and p.front_matter.updated == date(2026, 9, 1)
    assert BUDGET_STYLES == ("early", "steady", "hoarder")
    assert p.to_dict()["overpays"] == ["Pc", "A"]


def test_team_and_share_are_optional(tmp_path):
    path = _write(tmp_path / "kb", "Marco")
    text = path.read_text(encoding="utf-8").replace("team: Sanzimippi FC\n", "")
    path.write_text(text, encoding="utf-8")
    p = load_participant(path)
    assert p.team is None and p.max_single_share is None


@pytest.mark.parametrize("edit, message", [
    (lambda t: t.replace("budget_style: early", "budget_style: wild"), "budget_style"),
    (lambda t: t.replace("overpays: [Pc, A]", "overpays: [Bomber]"), "overpays"),
    (lambda t: t.replace("avoids: [Por]", "avoids: Por"), "avoids"),
    (lambda t: t.replace("nick: Marco\n", ""), "nick"),
    (lambda t: t.replace("favourite_clubs: [Juventus]", "favourite_clubs: [Juventus, 3]"), "favourite_clubs"),
    (lambda t: t.replace("---\nupdated", "updated", 1), "front-matter"),
])
def test_load_participant_fails_loud(tmp_path, edit, message):
    path = _write(tmp_path / "kb", "Marco")
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ParticipantError, match=message):
        load_participant(path)


def test_an_email_shaped_value_is_refused_anywhere_in_the_front_matter(tmp_path):
    path = _write(tmp_path / "kb", "Marco", extra="contact: marco@example.it\n")
    with pytest.raises(ParticipantError, match="email"):
        load_participant(path)
    path = _write(tmp_path / "kb", "marco@example.it")
    with pytest.raises(ParticipantError, match="email"):
        load_participant(path)


def test_max_single_share_is_a_share(tmp_path):
    path = _write(tmp_path / "kb", "Marco", extra="max_single_share: 30\n")
    with pytest.raises(ParticipantError, match="max_single_share"):
        load_participant(path)


def test_load_participants_sorts_by_nick_and_refuses_a_duplicate_nick(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "Marco")
    _write(kb, "Anna", style="hoarder")
    assert [p.nick for p in load_participants(kb)] == ["Anna", "Marco"]
    assert load_participants(tmp_path / "nowhere") == []
    _write(kb, "Marco", filename="marco-bis.md")
    with pytest.raises(ParticipantError, match="Marco"):
        load_participants(kb)


def test_the_audit_validates_dossiers(tmp_path):
    kb = tmp_path / "kb"
    good = _write(kb, "Marco")
    bad = _write(kb, "Anna", style="wild")
    statuses = {e.path: e.status for e in audit(kb, date(2026, 9, 2))}
    assert statuses[str(good.relative_to(kb))] == "ok" and statuses[str(bad.relative_to(kb))] == "invalid"
