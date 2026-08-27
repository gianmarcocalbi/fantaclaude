import json
from datetime import UTC, datetime

import pytest
from fantaclaude.league.settings import (
    Change,
    latest_snapshot,
    record_snapshot,
    rules_hash,
    snapshot_from_payloads,
)


@pytest.fixture
def payloads(mcp_fixture_json):
    return {
        "profile": mcp_fixture_json("league_profile"),
        "status": mcp_fixture_json("league_status"),
        "rosters": mcp_fixture_json("roster_settings"),
        "lineup": mcp_fixture_json("lineup_settings"),
        "calculate": mcp_fixture_json("calculation_settings"),
        "teams": mcp_fixture_json("teams"),
    }


def test_snapshot_decodes_the_confirmed_fields(payloads):
    snap = snapshot_from_payloads(**payloads)
    assert snap.league_id == 2578630 and snap.budget == 500
    assert (snap.roster_min, snap.roster_max) == (23, 40)
    assert len(snap.modules) == 11 and snap.bench_size == 12 and snap.substitutions == 5
    assert snap.team_count == 8
    assert len(snap.rules_hash) == 16
    assert "parola" not in snap.payload["profile"]
    assert set(snap.payload) == {"profile", "status", "rosters", "lineup", "calculate", "teams"}


def test_rules_hash_ignores_volatile_fields_and_sees_rule_changes(payloads):
    base = rules_hash(payloads["rosters"], payloads["lineup"], payloads["calculate"], 8)
    bumped = dict(payloads["rosters"], count=99, version="v3")
    assert rules_hash(bumped, payloads["lineup"], payloads["calculate"], 8) == base
    richer = dict(payloads["rosters"], budg=1000)
    assert rules_hash(richer, payloads["lineup"], payloads["calculate"], 8) != base
    assert rules_hash(payloads["rosters"], payloads["lineup"], payloads["calculate"], 10) != base


def test_record_snapshot_appends_only_on_change(db, payloads):
    snap = snapshot_from_payloads(**payloads)
    first = record_snapshot(db, snap, fetched_at=datetime(2026, 8, 24, tzinfo=UTC))
    assert first.changed and first.snapshot_id == 1 and first.previous_hash is None
    again = record_snapshot(db, snap)
    assert not again.changed and again.snapshot_id == 1 and again.diff == []
    changed = snapshot_from_payloads(**{**payloads, "rosters": dict(payloads["rosters"], budg=1000)})
    second = record_snapshot(db, changed)
    assert second.changed and second.snapshot_id == 2 and second.previous_hash == first.rules_hash
    assert Change("rosters.budg", 500, 1000) in second.diff
    assert db.execute("SELECT count(*) FROM league_settings").fetchone()[0] == 2
    assert latest_snapshot(db).snapshot_id == 2
    assert db.execute("SELECT budget FROM v_league_settings_current").fetchone()[0] == 1000
    stored = db.execute("SELECT fetched_at FROM league_settings WHERE snapshot_id = 1").fetchone()[0]
    assert stored == datetime(2026, 8, 24)  # noqa: DTZ001 -- naive UTC is what to_db stores


def test_team_count_change_is_a_rule_change(db, payloads):
    record_snapshot(db, snapshot_from_payloads(**payloads))
    profile = json.loads(json.dumps(payloads["profile"]))
    profile["lega"]["n_s"] = 10
    result = record_snapshot(db, snapshot_from_payloads(**{**payloads, "profile": profile}))
    assert result.changed and Change("team_count", 8, 10) in result.diff


def test_team_payload_never_carries_an_email(payloads):
    teams = {"data": [{"id": 1, "n": "x", "all": [{"id": 2, "n": "y", "email": "someone@example.it"}]}],
             "divisions": []}
    snap = snapshot_from_payloads(**{**payloads, "teams": teams})
    assert "@" not in json.dumps(snap.payload["teams"])
    assert snap.payload["teams"]["data"][0]["all"][0] == {"id": 2, "n": "y"}


def test_email_shaped_values_are_redacted_regardless_of_key_name(payloads):
    teams = {
        "note": "reach me at someone@example.it please",
        "data": [{"id": 1, "contact": "someone@example.it",
                  "extra": [{"nickname": "someone@example.it"}]}],
    }
    snap = snapshot_from_payloads(**{**payloads, "teams": teams})
    dumped = json.dumps(snap.payload["teams"])
    assert "someone@example.it" not in dumped
    assert snap.payload["teams"]["note"] == "[email redacted]"
    assert snap.payload["teams"]["data"][0]["contact"] == "[email redacted]"
    assert snap.payload["teams"]["data"][0]["extra"][0]["nickname"] == "[email redacted]"


def test_non_email_values_survive_untouched(payloads):
    teams = {"data": [{"id": 1, "handle": "@bomber", "n": "KingNazzario"}]}
    snap = snapshot_from_payloads(**{**payloads, "teams": teams})
    assert snap.payload["teams"]["data"][0]["handle"] == "@bomber"
    assert snap.payload["teams"]["data"][0]["n"] == "KingNazzario"


def test_profile_and_status_are_scrubbed_too(payloads):
    profile = json.loads(json.dumps(payloads["profile"]))
    profile["lega"]["presidente_contact"] = "someone@example.it"
    status = json.loads(json.dumps(payloads["status"]))
    status["reported_by"] = "someone@example.it"
    snap = snapshot_from_payloads(**{**payloads, "profile": profile, "status": status})
    assert snap.payload["profile"]["presidente_contact"] == "[email redacted]"
    assert snap.payload["status"]["reported_by"] == "[email redacted]"


def test_settings_payloads_are_excluded_from_the_scrub(payloads):
    snap = snapshot_from_payloads(**payloads)
    # `is`, not `==`: the scrub must never even copy these three, so a later
    # change cannot quietly widen it and split the hash/diff invariant.
    assert snap.payload["rosters"] is payloads["rosters"]
    assert snap.payload["lineup"] is payloads["lineup"]
    assert snap.payload["calculate"] is payloads["calculate"]
