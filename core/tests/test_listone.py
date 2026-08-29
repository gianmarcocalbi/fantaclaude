import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.ingest import ingest_listone
from fantaclaude.ingest.listone_api import (
    ListoneShapeError,
    load_listone,
    record_listone,
)
from fantaclaude.ingest.raw import RawStore
from fantaclaude.model.roles import ClassicRole, Role, UnknownRoleCode
from typer.testing import CliRunner


def test_raw_store_writes_immutable_dated_files(tmp_path):
    store = RawStore(tmp_path)
    when = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    first = store.write("listone", {"x": 1}, fetched_at=when)
    assert first.path.name == "20260824T100000000000Z-listone.json" and first.path.is_file()
    assert first.sha256 == RawStore.sha256_of(first.path) and first.kind == "listone"
    with pytest.raises(FileExistsError):
        store.write("listone", {"x": 2}, fetched_at=when)          # never overwritten
    second = store.write("listone", {"x": 1})
    assert store.list("listone") == sorted([first.path, second.path])
    assert first.sha256 == second.sha256                            # same bytes, same hash
    assert store.list("nothing") == []


def test_load_listone_decodes_every_role_code(fixture_path):
    rows = load_listone(fixture_path("listone_sample"))
    assert len(rows) == 17
    assert {c for r in rows for c in r.mantra_role_codes} == {6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19}
    by = {r.player_id: r for r in rows}
    assert by[5877].mantra_roles == {Role.B, Role.Ds, Role.E} and by[5877].classic_role is ClassicRole.D
    assert by[254].quot_current_mantra == 30 and by[254].quot_current_classic == 32
    assert by[2297].transfer_flag is True and by[2764].transfer_flag is False
    assert by[3].raw["lid"] == 21                                   # unnamed fields survive in raw
    assert by[2764].team_name == "Inter" and by[2764].team_short == "INT"


def test_unknown_role_code_names_the_player(tmp_path, fixture_json):
    payload = fixture_json("listone_sample")
    payload["players"][0]["marle"] = [6, 99]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(UnknownRoleCode, match=r"\[99\].*Radunovic"):
        load_listone(path)


def test_missing_confirmed_field_fails_loud(tmp_path, fixture_json):
    payload = fixture_json("listone_sample")
    del payload["players"][3]["icsma"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ListoneShapeError, match="icsma"):
        load_listone(path)
    path.write_text(json.dumps({"players": []}))
    with pytest.raises(ListoneShapeError):
        load_listone(path)


def test_record_listone_snapshots_and_dedupes(db, tmp_path, fixture_json):
    store = RawStore(tmp_path / "raw")
    raw = store.write("listone", fixture_json("listone_sample"))
    result = record_listone(db, load_listone(raw.path), raw)
    assert result.snapshot_id == 1 and result.inserted == 17 and not result.skipped_duplicate
    assert db.execute("SELECT count(*) FROM v_players_current").fetchone()[0] == 17
    assert db.execute("SELECT mantra_roles FROM v_players_current WHERE player_id = 5877").fetchone()[0] == ["Ds", "B", "E"]
    teams = {p["tid"] for p in fixture_json("listone_sample")["players"]}
    assert db.execute("SELECT count(*) FROM v_teams_current").fetchone()[0] == len(teams)

    again = record_listone(db, load_listone(raw.path), raw)
    assert again.skipped_duplicate and again.snapshot_id == 1 and again.inserted == 0

    changed = fixture_json("listone_sample")
    changed["players"][0]["acsma"] = 2
    raw2 = store.write("listone", changed)
    second = record_listone(db, load_listone(raw2.path), raw2)
    assert second.snapshot_id == 2
    assert db.execute("SELECT count(*) FROM players").fetchone()[0] == 34            # history kept
    assert db.execute("SELECT quot_current_mantra FROM v_players_current WHERE player_id = 3").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM listone_snapshots").fetchone()[0] == 2


def test_record_listone_rolls_back_on_partial_failure(db, tmp_path, fixture_json):
    """A failure partway through players/teams must not leave an orphan
    snapshot row -- v_players_current keys off the latest snapshot_id, so a
    committed snapshot with no players would make "current" report zero
    rows instead of falling back to the last complete snapshot."""
    store = RawStore(tmp_path / "raw")
    raw = store.write("listone", fixture_json("listone_sample"))
    first = record_listone(db, load_listone(raw.path), raw)
    assert first.snapshot_id == 1

    changed = fixture_json("listone_sample")
    changed["players"][0]["acsma"] = 2
    raw2 = store.write("listone", changed)
    rows = load_listone(raw2.path)
    rows = [*rows, rows[0]]                              # duplicate player_id -> PK violation mid-insert
    with pytest.raises(duckdb.Error):
        record_listone(db, rows, raw2)

    assert db.execute("SELECT count(*) FROM listone_snapshots").fetchone()[0] == 1
    assert db.execute("SELECT snapshot_id FROM listone_snapshots").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM v_players_current").fetchone()[0] == 17
    assert db.execute("SELECT count(*) FROM players").fetchone()[0] == 17           # no orphan rows
    assert db.execute("SELECT count(*) FROM teams").fetchone()[0] == len(
        {p["tid"] for p in fixture_json("listone_sample")["players"]})


async def test_ingest_listone_command_end_to_end(db, tmp_path, fake_api, fixture_json):
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    result = await ingest_listone(api, db, RawStore(tmp_path / "raw"))
    assert result.inserted == 17 and Path(result.raw_path).is_file()
    twice = await ingest_listone(api, db, RawStore(tmp_path / "raw"))
    assert twice.skipped_duplicate


def test_cli_ingest_listone_json(monkeypatch, tmp_path, fake_api, fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    api = fake_api(overrides={"players": fixture_json("listone_sample")})
    monkeypatch.setattr("fantaclaude.api_client.run_with_api", lambda fn: asyncio.run(fn(api)))
    result = CliRunner().invoke(app, ["ingest", "listone", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["inserted"] == 17 and payload["snapshot_id"] == 1
    assert list((tmp_path / "data" / "raw" / "listone").glob("*-listone.json"))


def test_a_failed_ingest_leaves_no_database_behind(monkeypatch, tmp_path):
    """Same contract as sync-league: no file until there is a snapshot."""
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))

    def boom(fn):
        raise RuntimeError("no credentials")

    monkeypatch.setattr("fantaclaude.api_client.run_with_api", boom)
    result = CliRunner().invoke(app, ["ingest", "listone"])
    assert result.exit_code != ExitCode.OK
    assert not (tmp_path / "data" / "fanta.duckdb").exists(), "phantom database created"
