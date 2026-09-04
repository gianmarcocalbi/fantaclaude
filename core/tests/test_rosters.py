import asyncio
import json
from datetime import UTC, datetime

import pytest
from conftest import seed_rosters
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import fetch_rosters
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.ingest.rosters_api import (
    RosterShapeError,
    parse_rosters,
    record_rosters,
)
from typer.testing import CliRunner

runner = CliRunner()


def _teams(*teams):
    return {"nextPage": False, "prevPage": False, "page": 1, "item": len(teams), "pages": 1,
            "data": list(teams), "divisions": [{"division": "A", "count": len(teams)}]}


def _team(team_id, name, cal, cs, *, crs=None, owner="nick"):
    return {"id": team_id, "n": name, "nu": owner, "idu": 1, "cri": 500, "crs": crs if crs is not None else 0,
            "cr": 500, "cal": cal, "cs": cs, "pl": None, "r": {"p": 0, "d": 0, "c": 0, "a": 0}, "d": "A",
            "all": [{"id": 9, "n": "Coach", "e": "coach@example.com"}]}


def test_parse_reads_ids_and_costs_in_order_and_an_empty_roster_is_empty():
    rows, warnings = parse_rosters(_teams(_team(1, "A", "2764;5841;", "120;30;", crs=150),
                                          _team(2, "B", "", "", crs=0)))
    assert [(r.team_id, r.player_id, r.cost, r.position) for r in rows] == [(1, 2764, 120, 0), (1, 5841, 30, 1)]
    assert rows[0].team_name == "A" and rows[0].owner == "nick" and warnings == []


def test_parse_warns_when_cs_does_not_sum_to_crs_and_names_the_team():
    _, warnings = parse_rosters(_teams(_team(1, "A", "2764;5841", "120;30", crs=151)))
    assert warnings == ["team 'A': cs sums to 150 but crs says 151"]


def test_parse_fails_loud_on_a_shape_it_cannot_read():
    with pytest.raises(RosterShapeError, match="2 ids"):
        parse_rosters(_teams(_team(1, "A", "2764;5841", "120")))
    with pytest.raises(RosterShapeError, match="not an integer"):
        parse_rosters(_teams(_team(1, "A", "2764;x", "1;2")))
    with pytest.raises(RosterShapeError, match="no data list"):
        parse_rosters({"data": None})


def _raw(tmp_path, payload, stamp="1"):
    path = tmp_path / f"rosters-{stamp}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return RawFile(path, f"sha-{stamp}", datetime(2026, 9, 4, 12, 0, tzinfo=UTC), "rosters")


def test_record_appends_a_snapshot_with_the_status_read_and_dedupes_on_bytes(db, tmp_path):
    payload = {"teams": _teams(_team(1, "A", "2764;795", "120;1", crs=121), _team(2, "B", "", "")),
               "status": {"sId": 21, "mday": 3, "mstr": "2026-09-04T18:45:00", "activ": True}, "fetch_warnings": []}
    first = record_rosters(db, payload, _raw(tmp_path, payload), league_id=2578630)
    assert not first.skipped_duplicate and first.inserted == 2 and first.teams == 2
    assert first.matchday == 3 and first.season_id == 21
    assert db.execute("SELECT matchday, matchday_start, team_count, row_count FROM roster_snapshots").fetchone() == \
        (3, datetime(2026, 9, 4, 18, 45), 2, 2)  # noqa: DTZ001 -- naive UTC, as stored
    teams = json.loads(db.execute("SELECT teams FROM roster_snapshots").fetchone()[0])
    assert teams == [{"id": 1, "name": "A", "owner": "nick", "size": 2}, {"id": 2, "name": "B", "owner": "nick", "size": 0}]
    assert db.execute("SELECT player_id, cost FROM v_rosters_current WHERE team_id = 1 ORDER BY position").fetchall() == \
        [(2764, 120), (795, 1)]                                     # 795 is not in any listone and is kept
    again = record_rosters(db, payload, _raw(tmp_path, payload), league_id=2578630)
    assert again.skipped_duplicate and again.snapshot_id == first.snapshot_id
    later = record_rosters(db, payload, _raw(tmp_path, payload, stamp="2"), league_id=2578630)
    assert later.snapshot_id != first.snapshot_id
    assert db.execute("SELECT snapshot_id FROM v_rosters_first").fetchone()[0] == first.snapshot_id


def test_an_empty_league_is_a_snapshot_with_no_rows(db, tmp_path):
    payload = {"teams": _teams(_team(1, "A", "", "")), "status": {"sId": 21, "mday": 1, "mstr": None}, "fetch_warnings": []}
    result = record_rosters(db, payload, _raw(tmp_path, payload), league_id=1)
    assert result.inserted == 0 and result.teams == 1
    assert db.execute("SELECT count(*) FROM v_rosters_first").fetchone()[0] == 0     # never the "earliest" for market prices


async def test_fetch_rosters_pages_the_teams_reads_the_status_and_scrubs_emails(tmp_path, fake_api):
    api = fake_api(overrides={"teams": _teams(_team(1, "A", "2764", "120", crs=120))})
    raw, payload = await fetch_rosters(api, RawStore(tmp_path / "raw"))
    assert api.calls == ["teams", "league_status"]
    assert raw.path.parent.name == "rosters" and raw.kind == "rosters"
    text = raw.path.read_text(encoding="utf-8")
    assert "@" not in text and "[email redacted]" in text
    assert payload["status"]["mday"] == 1 and payload["teams"]["data"][0]["cal"] == "2764"


def test_cli_ingest_rosters_needs_a_synced_league_and_records_once(monkeypatch, tmp_path, fake_api, mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    api = fake_api(overrides={"teams": _teams(_team(1, "A", "2764;5841", "120;30", crs=150))})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    result = runner.invoke(app, ["ingest", "rosters"])
    assert result.exit_code == ExitCode.NOT_READY and "sync-league" in result.stderr and api.calls == []
    assert runner.invoke(app, ["sync-league"]).exit_code == ExitCode.OK
    result = runner.invoke(app, ["ingest", "rosters", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["inserted"] == 2 and payload["teams"] == 1 and payload["warnings"] == []
    assert list((tmp_path / "data" / "raw" / "rosters").glob("*-rosters.json"))
    plain = runner.invoke(app, ["ingest", "rosters"])
    assert plain.exit_code == ExitCode.OK and "duplicate" in plain.stdout


def test_seed_rosters_matches_what_record_writes(db):
    seed_rosters(db, 1, 21, {10: ("Mine", {2764: 120, 5841: 30}), 11: ("Empty", {})}, matchday=3)
    assert db.execute("SELECT count(*), max(matchday) FROM v_rosters_current").fetchone() == (2, 3)
