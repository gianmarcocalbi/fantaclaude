import json
import time
from datetime import UTC, datetime

from conftest import FIXTURE_DIR, make_jwt
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.commands.doctor import DoctorPaths, run_doctor
from fantaclaude.db.connection import connect
from fantaclaude.db.schema import apply_schema
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.raw import RawStore
from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
from typer.testing import CliRunner

NAMES = ["env", "credentials", "token_cache", "database", "extensions", "league_settings",
         "listone", "league_yml", "preferences", "kb", "modules",
         "web_session", "player_match", "advanced", "fixtures", "aliases",
         "kb_profiles", "kb_notes", "kb_participants", "scoring", "pricing", "valuations"]


def _paths(root):
    return DoctorPaths(env=root / ".env", token_cache=root / ".auth" / "tokens.json",
                       db=root / "data" / "fanta.duckdb", league_yml=root / "league.yml",
                       preferences=root / "preferences.yml", kb=root / "kb", pricing=root / "pricing.yml")


def _ready_workspace(root, fixture_json, mcp_fixture_json, *, token_exp_offset=31_536_000):
    from fantaclaude.ingest.advanced import load_advanced, record_advanced
    from fantaclaude.ingest.calendar import load_uefa, record_fixtures
    from fantaclaude.ingest.names import Aliases, load_candidates, load_teams
    from fantaclaude.ingest.stats_web import parse_voti, record_voti

    token = make_jwt(user_id="1", l_id="2578630", t_id="1", role="user_league",
                     exp=int(time.time()) + token_exp_offset)
    (root / ".env").write_text("FANTACALCIO_APP_KEY=K\nFANTACALCIO_USERNAME=u\nFANTACALCIO_PASSWORD=synthetic\n"
                               "FANTACALCIO_WEB_COOKIE=\"session=synthetic\"\n")
    (root / ".auth").mkdir()
    (root / ".auth" / "tokens.json").write_text(json.dumps({
        "account": None, "user_id": None, "username": "u",
        "leagues": {"fantabalotelli3": {"alias": "fantabalotelli3", "league_id": "2578630",
                                        "team_id": "1", "name": "F3", "jwt": token}}}))
    (root / "league.yml").write_text("budget: {value: 500, source: admin, verified_on: 2026-08-24}\n")
    (root / "preferences.yml").write_text("target_composition: {Por: 2}\n")
    (root / "pricing.yml").write_text("bench_weight: 0.12\n")
    (root / "kb" / "rules").mkdir(parents=True)
    (root / "kb" / "README.md").write_text("# kb\n")
    (root / "kb" / "rules" / "aliases.yml").write_text("understat: {}\nuefa_teams: {}\n")
    con = connect(root / "data" / "fanta.duckdb")
    apply_schema(con)
    record_snapshot(con, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    store = RawStore(root / "data" / "raw")
    raw = store.write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    known = {r[0] for r in con.execute("SELECT player_id FROM v_players_current").fetchall()}
    voti = store.write_bytes("voti", (FIXTURE_DIR / "voti_sample.xlsx").read_bytes(), ext="xlsx", label="21-01")
    record_voti(con, 21, 1, parse_voti(voti.path), voti, known_ids=known)
    advanced = store.write("advanced", fixture_json("understat_sample"), label="20")
    season_id, rows = load_advanced(advanced.path)
    record_advanced(con, season_id, rows, advanced, candidates=load_candidates(con), teams=load_teams(con),
                    aliases=Aliases(teams={"understat": {"AC Milan": "Milan"}}),
                    aliases_sha256="a1", listone_snapshot_id=1)
    uefa = store.write("calendar", fixture_json("uefa_sample")[1], label="uecl-21-00")
    record_fixtures(con, "UECL", 21, load_uefa([uefa.path]), [uefa], teams=load_teams(con), team_aliases={})
    con.close()


def test_every_check_passes_on_a_ready_workspace(tmp_path, fixture_json, mcp_fixture_json):
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES
    assert [c.name for c in checks if not c.ok] == ["fixtures", "kb_profiles", "valuations"]
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


def test_credentials_check_agrees_with_load_settings(monkeypatch, tmp_path):
    """doctor must predict what the real commands do. Re-deriving credentials
    from .env alone disagreed with load_settings in both directions."""
    for var in ("FANTACALCIO_USERNAME", "FANTACALCIO_PASSWORD", "FANTACALCIO_LEAGUE_TOKEN",
                "FANTACALCIO_APP_KEY", "FANTACALCIO_API_BASE_URL"):
        monkeypatch.delenv(var, raising=False)

    # username with no resolvable password: load_settings raises, so doctor must fail
    (tmp_path / ".env").write_text("FANTACALCIO_APP_KEY=K\nFANTACALCIO_USERNAME=nobody-has-this-keychain-entry\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["credentials"].ok, by["credentials"].detail

    # credentials exported in the environment, no .env: load_settings succeeds,
    # so doctor must not report the workspace unconfigured
    (tmp_path / ".env").unlink()
    monkeypatch.setenv("FANTACALCIO_APP_KEY", "K")
    monkeypatch.setenv("FANTACALCIO_LEAGUE_TOKEN", "header.payload.sig")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["env"].ok and by["credentials"].ok, (by["env"].detail, by["credentials"].detail)


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
    assert result.exit_code == ExitCode.NOT_READY
    assert "FAIL  fixtures" in result.stdout and "listone" in result.stdout


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


def test_non_utf8_aliases_file_is_reported_not_raised(tmp_path):
    """Finding F8: load_aliases calls path.read_text(encoding="utf-8"), so a
    non-UTF-8 aliases.yml raises UnicodeDecodeError, and a file doctor
    cannot read at all raises OSError -- neither is an AliasError or a
    yaml.YAMLError, so the old except tuple let either one propagate and
    take the whole `fantaclaude doctor` command down, unlike every other
    check here, which reports a failure as a failed check rather than
    raising."""
    (tmp_path / "kb" / "rules").mkdir(parents=True)
    (tmp_path / "kb" / "rules" / "aliases.yml").write_bytes(b"understat:\n  \xff\xfe: 1\n")
    checks = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert list(checks) == NAMES                     # run_doctor completed, did not raise
    assert not checks["aliases"].ok


def test_advanced_check_surfaces_alias_resolved_players(tmp_path, fixture_json):
    """Finding F9: advanced_snapshots.matched stores counts["matched"]
    alone -- alias-resolved players (the whole purpose of aliases.yml) are
    counted separately with no column of their own, so the printed numbers
    under-counted matched by the alias count and never closed against
    row_count. Confirmed live: season 19 was reported "599 rows, 291
    matched, 9 ambiguous, 298 unmatched" = 598, one short. Reproduced here
    with the fixture test_advanced.py itself uses for the alias mechanism
    (Pietro Terracciano -> listone id 3): matched=5, alias=1, ambiguous=1,
    unmatched=3, which must close against the 10 recorded rows."""
    from fantaclaude.ingest.advanced import load_advanced, record_advanced
    from fantaclaude.ingest.names import Aliases, load_candidates, load_teams

    con = connect(tmp_path / "data" / "fanta.duckdb")
    apply_schema(con)
    raw = RawStore(tmp_path / "data" / "raw").write("listone", fixture_json("listone_sample"))
    record_listone(con, load_listone(raw.path), raw)
    store = RawStore(tmp_path / "data" / "raw")
    advanced_raw = store.write("advanced", fixture_json("understat_sample"), label="20")
    season_id, rows = load_advanced(advanced_raw.path)
    aliases = Aliases(players={"understat": {"Pietro Terracciano": 3}},
                      teams={"understat": {"AC Milan": "Milan"}})
    result = record_advanced(con, season_id, rows, advanced_raw, candidates=load_candidates(con),
                             teams=load_teams(con), aliases=aliases,
                             aliases_sha256="a1", listone_snapshot_id=1)
    assert (result.matched, result.alias, result.ambiguous, result.unmatched) == (5, 1, 1, 3)
    con.close()

    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["advanced"].ok
    assert "5 matched" in by["advanced"].detail and "1 alias" in by["advanced"].detail
    assert "1 ambiguous" in by["advanced"].detail and "3 unmatched" in by["advanced"].detail
    assert "10 rows" in by["advanced"].detail
    # the numbers must close: matched + alias + ambiguous + unmatched == row_count
    assert 5 + 1 + 1 + 3 == 10


def test_history_checks_describe_coverage(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    monkeypatch.delenv("FANTACALCIO_WEB_COOKIE", raising=False)   # isolate from a developer's exported cookie
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["web_session"].ok and by["web_session"].detail == "FANTACALCIO_WEB_COOKIE set"
    assert "synthetic" not in by["web_session"].detail
    assert by["player_match"].ok and "season 21: giornate 1" in by["player_match"].detail
    assert by["advanced"].ok and "season 20" in by["advanced"].detail and "ambiguous" in by["advanced"].detail
    assert by["fixtures"].ok is False and "no Serie A calendar" in by["fixtures"].detail   # UECL only, no SA yet
    assert by["aliases"].ok and "2 sections" in by["aliases"].detail


def test_history_checks_on_an_empty_database(monkeypatch, tmp_path, fixture_json, mcp_fixture_json):
    monkeypatch.delenv("FANTACALCIO_WEB_COOKIE", raising=False)   # isolate from a developer's exported cookie
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    for table in ("player_match", "voti_files", "advanced_stats", "advanced_snapshots", "fixtures", "fixture_snapshots"):
        con.execute(f"DELETE FROM {table}")
    con.close()
    (tmp_path / ".env").write_text("FANTACALCIO_APP_KEY=K\nFANTACALCIO_USERNAME=u\nFANTACALCIO_PASSWORD=synthetic\n")
    (tmp_path / "kb" / "rules" / "aliases.yml").write_text("understat: [1, 2\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["web_session"].ok and "not set" in by["web_session"].detail
    assert not by["player_match"].ok and "ingest stats-web" in by["player_match"].detail
    assert not by["advanced"].ok and "ingest advanced" in by["advanced"].detail
    assert not by["fixtures"].ok and "ingest calendar" in by["fixtures"].detail
    assert not by["aliases"].ok


def test_the_phase_1_checks(tmp_path, fixture_json, mcp_fixture_json):
    from test_kb_participants import _write as write_dossier
    from test_kb_profiles import _write as write_profile
    from test_valuation import PREFS, run

    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["kb_notes"].ok and by["kb_notes"].detail == "0 notes"
    assert by["kb_participants"].ok and by["kb_participants"].detail == "0 dossiers; league.yml maps 0"
    assert by["scoring"].ok and "sheet Fantacalcio" in by["scoring"].detail and "no modifier active" in by["scoring"].detail
    assert by["pricing"].ok and "bench_weight 0.12" in by["pricing"].detail
    assert not by["valuations"].ok and "fantaclaude rank" in by["valuations"].detail

    kb = tmp_path / "kb"
    note_dir = kb / "serie-a" / "teams" / "napoli" / "players"
    note_dir.mkdir(parents=True)
    (note_dir / "martinez-l.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                            "player_id: 2764\nname: Martinez L.\nteam_short: INT\ndepth: starter\n---\n# n\n")
    write_dossier(kb, "Marco")
    (tmp_path / "league.yml").write_text("budget: {value: 500, source: admin, verified_on: 2026-08-24}\n"
                                         "participants:\n  Anna: {value: kb/league/participants/anna.md, source: interview, verified_on: 2026-09-01}\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["kb_notes"].ok and "napoli" in by["kb_notes"].detail and "inter" in by["kb_notes"].detail
    assert not by["kb_participants"].ok and "Anna" in by["kb_participants"].detail
    (tmp_path / "pricing.yml").write_text("bench_weight: heavy\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["pricing"].ok

    for name, short in (("Cagliari", "CAG"), ("Roma", "ROM"), ("Inter", "INT"), ("Milan", "MIL"), ("Fiorentina", "FIO"),
                        ("Napoli", "NAP"), ("Genoa", "GEN")):
        write_profile(kb, name, short, europe="none", rotation="1.0")
    write_profile(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85")
    (tmp_path / "pricing.yml").write_text("bench_weight: 0.12\n")
    (note_dir / "martinez-l.md").unlink()
    result, con = run(tmp_path, preferences=PREFS)
    from fantaclaude.analysis.valuation import record_run

    record_run(con, result)
    con.close()
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert by["valuations"].ok and result.run_id in by["valuations"].detail and "not superseded" in by["valuations"].detail

    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["smodf"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON, rules_hash = 'ffffffffffffffff' WHERE snapshot_id = 1",
                [json.dumps(payload)])
    con.close()
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    assert not by["scoring"].ok and "smodf" in by["scoring"].detail
    assert not by["valuations"].ok and "superseded" in by["valuations"].detail


def test_the_scoring_check_reports_an_unparsable_d_factor_table_instead_of_crashing(monkeypatch, tmp_path,
                                                                                     fixture_json, mcp_fixture_json):
    """Finding 7. d_factor.yml is transcribed by hand off the league's
    settings page, so a YAML syntax error there is the expected mistake --
    and doctor is the command meant to name it. yaml.parser.ParserError is
    neither DFactorTableError nor ValueError, so the whole run_doctor call
    died on it: no `scoring` verdict, and none of the checks after it."""
    import fantaclaude.commands.doctor as doctor_module
    from fantaclaude.model.d_factor import load_d_factor

    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["smodd"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    bad = tmp_path / "d_factor.yml"
    bad.write_text("bands: [ {min: 6.0, points: 1 }\n", encoding="utf-8")
    monkeypatch.setattr(doctor_module, "load_d_factor", lambda: load_d_factor(bad))
    checks = run_doctor(_paths(tmp_path), now=datetime.now(UTC))
    assert [c.name for c in checks] == NAMES                       # the run finished; nothing after scoring was lost
    scoring = next(c for c in checks if c.name == "scoring")
    assert not scoring.ok and "D-Factor active" in scoring.detail and "d_factor.yml" in scoring.detail


def test_kb_notes_flags_an_orphan_and_a_misdeclared_team_short(tmp_path, fixture_json, mcp_fixture_json):
    """An orphan note (player_id the listone does not have) has no effect --
    build_inputs never looks it up -- but it still enters inputs_hash, so an
    unwarned one is the silent wrong number this tool exists to avoid. A
    team_short that disagrees with the listone is validated as well-formed
    at load time but never checked against the player it names."""
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    kb = tmp_path / "kb"
    note_dir = kb / "serie-a" / "teams" / "napoli" / "players"
    note_dir.mkdir(parents=True)
    (note_dir / "nobody.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                        "player_id: 999999\nname: Nobody\nteam_short: NAP\ndepth: starter\n---\n# n\n")
    (note_dir / "hojlund.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                         "player_id: 6052\nname: Hojlund\nteam_short: INT\ndepth: starter\n---\n# n\n")
    by = {c.name: c for c in run_doctor(_paths(tmp_path), now=datetime.now(UTC))}
    detail = by["kb_notes"].detail
    assert not by["kb_notes"].ok
    assert "orphan" in detail and "Nobody" in detail
    assert "team_short disagrees" in detail and "Hojlund" in detail and "NAP" in detail
