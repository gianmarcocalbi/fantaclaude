from datetime import date

import pytest
import yaml
from fantaclaude.league.league_yml import (
    Conflict,
    LeagueYmlError,
    Provenanced,
    cross_check,
    load_league_yml,
)
from fantaclaude.league.settings import snapshot_from_payloads
from fantaclaude.paths import league_yml_path, preferences_yml_path

GOOD = """
auction:
  platform: {value: FantaAstaLive, source: admin, verified_on: 2026-08-23}
roster:
  min_goalkeepers: {value: 2, source: admin, verified_on: 2026-08-24, note: "verbal"}
participants: {}
"""


def test_loads_provenanced_leaves_with_dotted_keys(tmp_path):
    path = tmp_path / "league.yml"
    path.write_text(GOOD)
    entries = load_league_yml(path)
    assert entries["auction.platform"] == Provenanced(
        "auction.platform", "FantaAstaLive", "admin", date(2026, 8, 23))
    assert entries["roster.min_goalkeepers"].note == "verbal"
    assert "participants" not in entries          # an empty mapping is allowed, it holds nothing


@pytest.mark.parametrize("bad", [
    "auction: {platform: FantaAstaLive}",                                   # bare value
    "x: {value: 1, source: admin}",                                          # no verified_on
    "x: {value: 1, source: admin, verified_on: soon}",                       # not a date
    "x: {value: 1, source: '', verified_on: 2026-08-24}",                    # empty source
    "x: {value: 1, source: admin, verified_on: 2026-08-24, extra: 1}",       # unknown key
    "- just\n- a list",                                                      # not a mapping
])
def test_missing_or_malformed_provenance_fails_loud(tmp_path, bad):
    path = tmp_path / "league.yml"
    path.write_text(bad)
    with pytest.raises(LeagueYmlError):
        load_league_yml(path)


def test_cross_check_flags_only_disagreements(mcp_fixture_json, tmp_path):
    snap = snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams"))
    path = tmp_path / "league.yml"
    path.write_text(
        "budget: {value: 500, source: admin, verified_on: 2026-08-24}\n"
        "roster:\n  min_goalkeepers: {value: 3, source: admin, verified_on: 2026-08-24}\n"
        "auction:\n  mode: {value: draft, source: admin, verified_on: 2026-08-24}\n")
    assert cross_check(load_league_yml(path), snap) == [Conflict("roster.min_goalkeepers", 3, 2)]


def test_the_committed_files_load():
    entries = load_league_yml(league_yml_path())
    assert entries["auction.platform"].value == "FantaAstaLive"
    assert entries["roster.min_goalkeepers"].value == 2
    assert all(e.source and e.verified_on for e in entries.values())
    prefs = yaml.safe_load(preferences_yml_path().read_text(encoding="utf-8"))
    assert isinstance(prefs, dict) and "target_composition" in prefs
