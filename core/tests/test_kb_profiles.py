from datetime import UTC, date, datetime

import pytest
from fantaclaude.kb.audit import audit
from fantaclaude.kb.profiles import (
    EUROPE,
    PROFILE_KEYS,
    ProfileError,
    load_profile,
    load_profiles,
    team_slug,
)

PROFILE = """---
updated: 2026-08-29
ttl: 14d
confidence: medium
source: "web: club site, Transfermarkt"
team: {team}
team_short: {short}
coach: Cristian Chivu
module: 3-5-2
europe: {europe}
rotation_factor: {rotation}
takers:
  penalties: Calhanoglu
  corners: Dimarco
---

# {team} — 2026-27

## Tactics
Prose.
"""


def _write(kb, team, short, *, europe="UCL", rotation="0.9", slug=None):
    folder = kb / "serie-a" / "teams" / (slug or team_slug(team))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "profile.md"
    path.write_text(PROFILE.format(team=team, short=short, europe=europe, rotation=rotation), encoding="utf-8")
    return path


def test_team_slug():
    assert team_slug("Inter") == "inter" and team_slug("Hellas Verona") == "hellas-verona"
    assert team_slug("Milan") == "milan" and team_slug("Cagliari ") == "cagliari"


def test_load_profile_reads_the_structured_front_matter(tmp_path):
    path = _write(tmp_path / "kb", "Inter", "INT")
    profile = load_profile(path)
    assert (profile.team, profile.team_short, profile.coach, profile.module) == ("Inter", "INT", "Cristian Chivu", "3-5-2")
    assert profile.europe == "UCL" and profile.rotation_factor == 0.9
    assert profile.takers == {"penalties": "Calhanoglu", "corners": "Dimarco"}
    assert profile.front_matter.updated == date(2026, 8, 29) and profile.path == path
    assert PROFILE_KEYS == ("team", "team_short", "coach", "module", "europe", "rotation_factor")
    assert EUROPE == ("none", "UCL", "UEL", "UECL")


@pytest.mark.parametrize("edit, message", [
    (lambda text: text.replace("europe: UCL", "europe: Champions"), "europe"),
    (lambda text: text.replace("rotation_factor: 0.9", "rotation_factor: 1.4"), "rotation_factor"),
    (lambda text: text.replace("rotation_factor: 0.9", "rotation_factor: high"), "rotation_factor"),
    (lambda text: text.replace("coach: Cristian Chivu\n", ""), "coach"),
    (lambda text: text.replace("team_short: INT", "team_short: int"), "team_short"),
    (lambda text: text.replace("takers:\n  penalties: Calhanoglu\n  corners: Dimarco\n", "takers: Calhanoglu\n"), "takers"),
    (lambda text: text.replace("---\nupdated", "updated", 1), "front-matter"),
])
def test_load_profile_fails_loud(tmp_path, edit, message):
    path = _write(tmp_path / "kb", "Inter", "INT")
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ProfileError, match=message):
        load_profile(path)


def test_the_folder_must_be_the_team_slug(tmp_path):
    path = _write(tmp_path / "kb", "Inter", "INT", slug="internazionale")
    with pytest.raises(ProfileError, match="internazionale"):
        load_profile(path)


def test_load_profiles_walks_the_tree_and_the_audit_flags_bad_ones(tmp_path):
    kb = tmp_path / "kb"
    _write(kb, "Inter", "INT")
    _write(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85")
    bad = _write(kb, "Milan", "MIL", europe="Europa")
    with pytest.raises(ProfileError, match="milan"):
        load_profiles(kb)
    statuses = {e.path: e.status for e in audit(kb, date(2026, 8, 30))}
    assert statuses["serie-a/teams/inter/profile.md"] == "ok"
    assert statuses["serie-a/teams/milan/profile.md"] == "invalid"
    bad.unlink()
    assert [p.team for p in load_profiles(kb)] == ["Atalanta", "Inter"]
    assert load_profiles(tmp_path / "nowhere") == []


def test_doctor_kb_profiles_check(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.commands.doctor import run_doctor
    from test_doctor import NAMES, _paths, _ready_workspace

    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)          # listone sample: 8 clubs; UECL ties for ATA
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert NAMES[-1] == "kb_profiles" and not by["kb_profiles"].ok
    assert "0/8 teams profiled" in by["kb_profiles"].detail and "Atalanta" in by["kb_profiles"].detail

    kb = tmp_path / "kb"
    for name, short in (("Cagliari", "CAG"), ("Roma", "ROM"), ("Inter", "INT"), ("Milan", "MIL"), ("Fiorentina", "FIO"),
                        ("Napoli", "NAP"), ("Genoa", "GEN")):
        _write(kb, name, short, europe="none", rotation="1.0")
    _write(kb, "Atalanta", "ATA", europe="none", rotation="1.0")        # disagrees with the UECL ties
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["kb_profiles"].ok and "8/8 teams profiled" in by["kb_profiles"].detail
    assert "Atalanta: profile says none, fixtures say UECL" in by["kb_profiles"].detail

    _write(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["kb_profiles"].ok and by["kb_profiles"].detail == "8/8 teams profiled; europe agrees with the fixtures"

    _write(kb, "Milan", "MIL", europe="Europa")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["kb_profiles"].ok and "milan" in by["kb_profiles"].detail


def test_committed_profiles_load(monkeypatch):
    """After the bootstrap run: every Serie A club has a profile that parses."""
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import kb_dir

    profiles = load_profiles(kb_dir())
    assert len(profiles) == 20
    assert all(len(p.team_short) == 3 and p.team_short.isupper() for p in profiles)
    assert all(0.5 <= p.rotation_factor <= 1.0 for p in profiles)
    assert {p.europe for p in profiles} & {"UCL", "UEL", "UECL"}                    # someone plays in Europe
    for name in ("mantra.md", "house-rules.md"):
        assert (kb_dir() / "rules" / name).is_file(), name
