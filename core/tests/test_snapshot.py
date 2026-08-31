import json
import os
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fantaclaude.asta.advisor import TeamMapping, derive
from fantaclaude.asta.session import session_from_feed
from fantaclaude.asta.snapshot import (
    STATE_VERSION,
    StateFileError,
    StoredState,
    copy_to_records,
    read_state,
    render_state,
    write_state,
)
from fantaclaude.asta.state import AuctionState, apply_snapshot
from test_advisor import pinned_run, replayed

WHEN = datetime(2026, 9, 5, 22, 30, tzinfo=UTC)


def test_the_state_file_reads_on_its_own_and_reloads_the_same_board(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    """The post-auction path (spec, "Crash recovery is a test"): loading the
    state file with no feed available must reproduce the board."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    state = replayed(fixture_file, 6)
    settings = session_from_feed(state.settings, team_count=len(state.teams))
    mapping = TeamMapping(mine=1, nicks={0: "Marco"})
    board = derive(state, run=pinned, settings=settings, mapping=mapping)
    payload = render_state(board, session_code="FA-nri-okm", written_at=WHEN)
    assert payload["version"] == STATE_VERSION and payload["written_at"] == "2026-09-05T22:30:00+00:00"
    assert payload["session"] == {"code": "FA-nri-okm", "status": "live", "locked": False, "settings": settings.to_dict()}
    assert payload["run_id"] == pinned.run_id and payload["scenario"] == "balanced" and payload["me"] == 1
    host = payload["teams"][0]
    assert host["label"] == "host" and host["nick"] == "Marco" and host["spent"] == 165 and host["credits"] == 335
    assert host["budget"] == 500                                          # the session's budget, not a hardcoded one
    assert [p["name"] for p in host["picks"]] == ["Martinez L.", "Bastoni"] and host["picks"][0]["roles"] == ["Pc"]
    assert [p["team_short"] for p in host["picks"]] == ["INT", "INT"]
    assert payload["selected"]["name"] == "Svilar" and payload["selected"]["band"]["p50"] > 0
    assert payload["feed"]["picks"][0] == {"playerId": 2764, "teamId": 0, "cost": 120, "index": 0, "timestamp": 1787600000000}
    assert payload["adjustments_sha256"] == ""                            # no adjustments layer supplied: EMPTY_LAYER's sha256
    assert payload["problems"] == [] and payload["league_conflicts"] == ["teams: 3 in the session, 8 in the league"]

    path = tmp_path / "data" / "asta-state.json"
    write_state(path, payload)
    assert path.read_bytes() == (json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    stored = read_state(path)
    assert isinstance(stored, StoredState) and stored.mapping == mapping and stored.session_code == "FA-nri-okm"
    assert stored.run_id == pinned.run_id and stored.scenario == "balanced" and stored.written_at == payload["written_at"]
    reloaded, _ = apply_snapshot(AuctionState.empty(), stored.snapshot)
    again = derive(reloaded, run=pinned, settings=session_from_feed(stored.snapshot.settings, team_count=len(stored.snapshot.teams)),
                   mapping=stored.mapping)
    assert again.to_dict() == board.to_dict()
    assert render_state(again, session_code="FA-nri-okm", written_at=WHEN) == payload


def test_render_state_scrubs_a_caller_supplied_nick_before_it_reaches_the_payload(tmp_path, fixture_json, mcp_fixture_json,
                                                                                   fixture_file):
    """TeamMapping.nicks is offline, caller-supplied input (spec: "the browser
    pre-fills it; offline it comes from flags or the state file") -- it never
    passes through the feed, so it never passes through state.scrub_label.
    render_state is the last place before a nick reaches a stored payload, so
    it must not reintroduce what Task 4's scrub already keeps out of a
    label."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    state = replayed(fixture_file, 6)
    settings = session_from_feed(state.settings, team_count=len(state.teams))
    mapping = TeamMapping(mine=1, nicks={0: "someone@example.invalid"})
    board = derive(state, run=pinned, settings=settings, mapping=mapping)
    payload = render_state(board, session_code="FA-nri-okm", written_at=WHEN)
    assert payload["teams"][0]["nick"] is None
    assert "@example" not in json.dumps(payload, allow_nan=False)


def test_a_state_file_this_code_did_not_write_is_refused(tmp_path):
    path = tmp_path / "asta-state.json"
    for text, match in (("{not json", "asta-state.json"), ("[]", "version"), ('{"version": 99}', "version"),
                        ('{"version": 1, "me": 0}', "asta-state.json"),
                        ('{"version": 1, "me": 0, "teams": [], "run_id": "r", "scenario": "s", "written_at": "w", "feed": {"picks": 5}}',
                         "picks"),
                        # torn shapes that used to escape as AttributeError instead of StateFileError:
                        ('{"version": 1, "me": 0, "teams": [], "run_id": "r", "scenario": "s", "written_at": "w", "feed": {"picks": []}, "session": 5}',
                         "session"),
                        ('{"version": 1, "me": 0, "teams": {"a": 1, "b": 2}, "run_id": "r", "scenario": "s", "written_at": "w", "feed": {"picks": []}}',
                         "asta-state.json"),
                        ('{"version": 1, "me": 0, "teams": ["x", "y"], "run_id": "r", "scenario": "s", "written_at": "w", "feed": {"picks": []}}',
                         "asta-state.json")):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StateFileError, match=match):
            read_state(path)
    with pytest.raises(StateFileError):
        read_state(tmp_path / "missing.json")


def test_the_records_copy_is_written_once(tmp_path):
    path = tmp_path / "data" / "asta-state.json"
    write_state(path, {"version": STATE_VERSION, "me": 0})
    records = tmp_path / "records"
    copy = copy_to_records(path, records, session_code="FA-nri-okm", written_at=WHEN)
    assert copy == records / "asta" / "FA-nri-okm-20260905T223000Z.json" and copy.read_bytes() == path.read_bytes()
    assert copy_to_records(path, records, session_code="FA-nri-okm", written_at=WHEN) == copy       # the same bytes again: fine
    write_state(path, {"version": STATE_VERSION, "me": 1})
    with pytest.raises(StateFileError, match="never rewritten"):
        copy_to_records(path, records, session_code="FA-nri-okm", written_at=WHEN)
    assert copy_to_records(path, records, session_code=None, written_at=WHEN).name == "session-20260905T223000Z.json"


def test_the_records_stamp_is_the_utc_instant_not_the_caller_s_clock(tmp_path):
    """records/ is committed and never rewritten -- a filename stamped in a
    local zone would name the wrong instant forever."""
    path = tmp_path / "data" / "asta-state.json"
    write_state(path, {"version": STATE_VERSION, "me": 0})
    records = tmp_path / "records"
    local_noon = datetime(2026, 9, 6, 0, 30, tzinfo=timezone(timedelta(hours=2)))     # 2026-09-05T22:30:00Z, same instant as WHEN
    copy = copy_to_records(path, records, session_code="FA-nri-okm", written_at=local_noon)
    assert copy.name == "FA-nri-okm-20260905T223000Z.json"


def test_the_records_copy_refuses_a_missing_source_loudly(tmp_path):
    with pytest.raises(StateFileError, match="asta-state.json"):
        copy_to_records(tmp_path / "data" / "asta-state.json", tmp_path / "records", session_code="FA-nri-okm", written_at=WHEN)



def test_the_records_copy_refuses_a_session_code_that_is_a_path(tmp_path):
    """The name becomes one path component under records/asta/, so the check
    belongs here, where both routes to it end: the --session flag (guarded a
    layer up, where it is a usage error) and the state file's own
    session.code, which nothing else validates and 2b's live mirror writes."""
    path = tmp_path / "data" / "asta-state.json"
    write_state(path, {"version": STATE_VERSION, "me": 0})
    records = tmp_path / "records"
    for code in ("../FA-nri-okm", "nested/FA-nri-okm", "..", ".", r"back\slash"):
        with pytest.raises(StateFileError, match="is a path, not a session code"):
            copy_to_records(path, records, session_code=code, written_at=WHEN)
    assert not records.exists()                                  # refused before anything was written
    assert copy_to_records(path, records, session_code="FA-nri-okm", written_at=WHEN).exists()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="TZ is not settable at runtime on this platform")
def test_a_written_at_without_an_offset_is_read_as_utc_not_as_local_time(tmp_path):
    """A state file's written_at is UTC by construction -- render_state writes
    `utc_now().isoformat()`. Read back with `astimezone(UTC)`, a value that
    somehow lost its offset (a hand-edited file) was interpreted in the
    machine's local zone instead, and records/ -- committed, never rewritten
    -- got a filename naming an instant hours away from the one it holds, in
    a zone nothing in the file records."""
    path = tmp_path / "data" / "asta-state.json"
    write_state(path, {"version": STATE_VERSION, "me": 0})
    records = tmp_path / "records"
    # exactly what close_auction hands the sink: datetime.fromisoformat over a hand-edited written_at with no offset on it
    naive = datetime.fromisoformat("2026-09-05T22:30:00")
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Tokyo"                             # UTC+9 all year: no DST to make this read either way
    time.tzset()
    try:
        copy = copy_to_records(path, records, session_code="FA-nri-okm", written_at=naive)
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()
    # read as UTC: 22:30. Read as local Tokyo time it would be 13:30Z, and the record would name the wrong instant.
    assert copy.name == "FA-nri-okm-20260905T223000Z.json"
    assert copy.name == f"FA-nri-okm-{naive.replace(tzinfo=UTC):%Y%m%dT%H%M%SZ}.json"
