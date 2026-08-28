import json
import time
from datetime import UTC, datetime

from conftest import make_jwt
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.doctor import DoctorPaths, run_doctor
from fantaclaude.db.connection import connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from typer.testing import CliRunner

NAMES = ["env", "credentials", "token_cache", "database", "extensions", "league_settings",
         "listone", "league_yml", "preferences", "kb", "modules"]


def _paths(root):
    return DoctorPaths(env=root / ".env", token_cache=root / ".auth" / "tokens.json",
                       db=root / "data" / "fanta.duckdb", league_yml=root / "league.yml",
                       preferences=root / "preferences.yml", kb=root / "kb")


def _ready_workspace(root, fixture_json, mcp_fixture_json, *, token_exp_offset=31_536_000):
    token = make_jwt(user_id="1", l_id="2578630", t_id="1", role="user_league",
                     exp=int(time.time()) + token_exp_offset)
    (root / ".env").write_text("FANTACALCIO_APP_KEY=K\nFANTACALCIO_USERNAME=u\n")
    (root / ".auth").mkdir()
    (root / ".auth" / "tokens.json").write_text(json.dumps({
        "account": None, "user_id": None, "username": "u",
        "leagues": {"fantabalotelli3": {"alias": "fantabalotelli3", "league_id": "2578630",
                                        "team_id": "1", "name": "F3", "jwt": token}}}))
    (root / "league.yml").write_text("budget: {value: 500, source: admin, verified_on: 2026-08-24}\n")
    (root / "preferences.yml").write_text("target_composition: {Por: 2}\n")
    (root / "kb" / "rules").mkdir(parents=True)
    (root / "kb" / "README.md").write_text("# kb\n")
    (root / "kb" / "rules" / "aliases.yml").write_text("fbref: {}\n")
    con = connect(root / "data" / "fanta.duckdb")
    apply_schema(con)
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    raw = RawStore(root / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    con.close()


def test_every_check_passes_on_a_ready_workspace(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert "17 players" in next(c.detail for c in checks if c.name == "listone")
    assert "login mode" in next(c.detail for c in checks if c.name == "credentials")
    joined = " ".join(c.detail for c in checks)
    assert "eyJhbGci" not in joined and "K\n" not in joined           # never a secret value


def test_missing_pieces_are_named(tmp_path):
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not checks["env"].ok and not checks["database"].ok and not checks["league_yml"].ok
    assert not checks["kb"].ok and not checks["credentials"].ok
    assert checks["modules"].ok
    assert "sync-league" in checks["database"].detail


def test_expired_token_cache_is_flagged(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json, token_exp_offset=-10)
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not checks["token_cache"].ok and "expired" in checks["token_cache"].detail


def test_schema_less_database_is_reported_not_raised(tmp_path):
    """connect() creates the file before apply_schema runs and the DDL is not
    transactional, so an interrupted first sync-league leaves a valid DuckDB
    file with no schema. doctor must report that, not raise out of every check."""
    import duckdb

    (tmp_path / "data").mkdir()
    duckdb.connect(str(tmp_path / "data" / "fanta.duckdb")).close()
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    by = {c.name: c for c in checks}
    assert not by["database"].ok and not by["extensions"].ok
    assert not by["league_settings"].ok and not by["listone"].ok


def test_doctor_cli_exit_codes(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == ExitCode.NOT_READY
    payload = json.loads(result.stdout)
    assert payload["ok"] is False and [c["name"] for c in payload["checks"]] == NAMES
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == ExitCode.OK, result.output
    assert "ok" in result.stdout


def test_malformed_league_yml_is_reported_not_raised(tmp_path):
    # Unbalanced bracket: yaml.safe_load raises yaml.YAMLError (ParserError),
    # not LeagueYmlError -- doctor must catch that too, not just its own type.
    (tmp_path / "league.yml").write_text("budget: [1, 2\n")
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    league_yml_check = next(c for c in checks if c.name == "league_yml")
    assert not league_yml_check.ok


def test_corrupted_cached_jwt_is_reported_not_raised(tmp_path):
    # A cached token that isn't a readable JWT makes is_expired() raise
    # AuthError; doctor must count it as unusable, not crash.
    (tmp_path / ".auth").mkdir()
    (tmp_path / ".auth" / "tokens.json").write_text(json.dumps({
        "account": None, "user_id": None, "username": "u",
        "leagues": {"fantabalotelli3": {"alias": "fantabalotelli3", "league_id": "2578630",
                                        "team_id": "1", "name": "F3", "jwt": "not-a-jwt"}}}))
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    token_check = next(c for c in checks if c.name == "token_cache")
    assert not token_check.ok
    assert "unreadable" in token_check.detail


def test_unavailable_database_is_reported_not_raised(tmp_path):
    # A file at the db path that isn't a valid DuckDB database makes
    # duckdb.connect() raise; doctor must report it and still return all
    # eleven checks, with the three dependent checks marked skipped.
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "fanta.duckdb").write_text("not a duckdb file")
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    by_name = {c.name: c for c in checks}
    assert not by_name["database"].ok
    assert not by_name["extensions"].ok and not by_name["league_settings"].ok and not by_name["listone"].ok
    assert "skipped" in by_name["extensions"].detail


def test_malformed_modules_yml_is_reported_not_raised(monkeypatch, tmp_path):
    # load_modules() also calls yaml.safe_load internally; point doctor's
    # reference at the real function pinned to a temp malformed file so the
    # test exercises the actual yaml.YAMLError path, not a mocked raise.
    from functools import partial

    from fantaclaude.commands import doctor as doctor_module
    from fantaclaude.model.modules import load_modules as real_load_modules

    broken = tmp_path / "modules.yml"
    broken.write_text("modules: [1, 2\n")
    monkeypatch.setattr(doctor_module, "load_modules", partial(real_load_modules, path=broken))
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    modules_check = next(c for c in checks if c.name == "modules")
    assert not modules_check.ok
