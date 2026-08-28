"""fantaclaude doctor: is the workspace ready for the night?

Every check reports existence, parseability, coverage or age -- never a
value. A token is "present, expires in N days", an app key is "set", the
website cookie is "set", and nothing here can leak into a terminal log.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import yaml
from fantacalcio_mcp.auth import AuthError, is_expired
from fantacalcio_mcp.config import ConfigurationError, load_dotenv, resolve_credentials

from fantaclaude.config import WEB_COOKIE_KEY
from fantaclaude.db.schema import SCHEMA_VERSION
from fantaclaude.ingest.names import AliasError, load_aliases
from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
from fantaclaude.model.modules import ModuleTableError, load_modules

CORE_DB_CHECKS = ("database", "extensions", "league_settings", "listone")
HISTORY_DB_CHECKS = ("player_match", "advanced", "fixtures")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DoctorPaths:
    env: Path
    token_cache: Path
    db: Path
    league_yml: Path
    preferences: Path
    kb: Path


def _age(then: datetime, now: datetime) -> str:
    hours = (now.replace(tzinfo=None) - then.replace(tzinfo=None)).total_seconds() / 3600
    return f"{hours / 24:.1f} days old" if hours >= 48 else f"{hours:.0f} hours old"


def _token_cache(path: Path, now: datetime) -> Check:
    if not path.is_file():
        return Check("token_cache", True, "no cache yet; the first API call logs in")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        leagues = (data.get("leagues") or {}) if isinstance(data, dict) else {}
        jwts = [entry["jwt"] for entry in leagues.values() if isinstance(entry, dict) and entry.get("jwt")]
    except (ValueError, KeyError, AttributeError):
        return Check("token_cache", True, "unreadable cache; it will be treated as cold and rebuilt")
    if not jwts:
        return Check("token_cache", True, "cache holds no league token yet")
    live = 0
    unreadable = 0
    for jwt in jwts:
        try:
            if not is_expired(jwt, now=now.timestamp()):
                live += 1
        except AuthError:
            # A corrupted cached token is treated the same as expired: the
            # next call re-logs in and heals it, rather than doctor raising.
            unreadable += 1
    suffix = f" ({unreadable} unreadable, treated as expired)" if unreadable else ""
    if live == 0:
        return Check("token_cache", False,
                     f"{len(jwts)} league token(s), all expired -- the next call must log in{suffix}")
    return Check("token_cache", True, f"{live}/{len(jwts)} league token(s) valid{suffix}")


def _skipped(reason: str) -> tuple[list[Check], list[Check]]:
    return ([Check(name, False, reason) for name in CORE_DB_CHECKS],
            [Check(name, False, reason) for name in HISTORY_DB_CHECKS])


def _history_checks(con: duckdb.DuckDBPyConnection, now: datetime) -> list[Check]:
    checks: list[Check] = []
    coverage = con.execute(
        "SELECT season_id, count(*), max(fetched_at) FROM v_voti_files_current "
        "GROUP BY season_id ORDER BY season_id").fetchall()
    if not coverage:
        checks.append(Check("player_match", False, "no voti yet -- run `fantaclaude ingest stats-web`"))
    else:
        detail = "; ".join(f"season {row[0]}: giornate {row[1]}" for row in coverage)
        checks.append(Check("player_match", True, f"{detail}; newest {_age(coverage[-1][2], now)}"))
    seasons = con.execute(
        "SELECT season_id, row_count, matched, ambiguous, unmatched, fetched_at FROM advanced_snapshots "
        "WHERE snapshot_id IN (SELECT max(snapshot_id) FROM advanced_snapshots GROUP BY season_id) "
        "ORDER BY season_id").fetchall()
    if not seasons:
        checks.append(Check("advanced", False, "no Understat rows yet -- run `fantaclaude ingest advanced`"))
    else:
        detail = "; ".join(f"season {r[0]}: {r[1]} rows, {r[2]} matched, {r[3]} ambiguous, {r[4]} unmatched"
                           for r in seasons)
        checks.append(Check("advanced", True, f"{detail}; newest {_age(seasons[-1][5], now)}"))
    current = con.execute("SELECT max(season_id) FROM v_league_settings_current").fetchone()[0]
    serie_a = con.execute(
        "SELECT count(DISTINCT giornata) FROM v_fixtures_current WHERE competition = 'SA' AND season_id = ?",
        [current]).fetchone()[0]
    ties = con.execute(
        "SELECT count(*), count(DISTINCT team_short) FROM v_european_ties WHERE season_id = ?",
        [current]).fetchone()
    if not serie_a:
        checks.append(Check("fixtures", False,
                            f"no Serie A calendar for season {current} -- run `fantaclaude ingest calendar`"))
    else:
        checks.append(Check("fixtures", True,
                            f"season {current}: {serie_a} giornate; {ties[0]} European ties for {ties[1]} clubs"))
    return checks


def _database_checks(path: Path, now: datetime) -> tuple[list[Check], list[Check]]:
    """(the Phase 0a checks, the history checks) -- reported in two places so the
    check order stays the documented one."""
    if not path.is_file():
        core, history = _skipped("skipped: no database")
        core[0] = Check("database", False,
                        f"no database at {path} -- run `fantaclaude sync-league` and `fantaclaude ingest listone`")
        return core, history
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        core, history = _skipped("skipped: database unavailable")
        core[0] = Check("database", False, f"cannot open database at {path}: {exc}")
        return core, history
    core: list[Check] = []
    history: list[Check] = []
    try:
        version = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
        note = (" -- any ingest or sync-league migrates it forward"
                if version is not None and version < SCHEMA_VERSION else "")
        core.append(Check("database", version == SCHEMA_VERSION,
                          f"schema version {version}, code expects {SCHEMA_VERSION}{note}"))
        installed = {r[0] for r in con.execute(
            "SELECT extension_name FROM duckdb_extensions() WHERE installed").fetchall()}
        needed = {"json", "parquet"}
        core.append(Check("extensions", needed <= installed,
                          f"installed: {', '.join(sorted(needed & installed)) or 'none'}; "
                          f"missing: {', '.join(sorted(needed - installed)) or 'none'}"))
        row = con.execute("SELECT fetched_at, rules_hash, budget, team_count FROM v_league_settings_current").fetchone()
        if row is None:
            core.append(Check("league_settings", False, "no snapshot -- run `fantaclaude sync-league`"))
        else:
            core.append(Check("league_settings", True,
                              f"rules {row[1]}, budget {row[2]}, {row[3]} teams, {_age(row[0], now)}"))
        row = con.execute("SELECT fetched_at, player_count FROM listone_snapshots "
                          "ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        if row is None:
            core.append(Check("listone", False, "no snapshot -- run `fantaclaude ingest listone`"))
        else:
            core.append(Check("listone", True, f"{row[1]} players, {_age(row[0], now)}"))
        if version != SCHEMA_VERSION:
            history = [Check(name, False, f"skipped: schema version {version}, expected {SCHEMA_VERSION}")
                       for name in HISTORY_DB_CHECKS]
        else:
            history = _history_checks(con, now)
    except duckdb.Error as exc:
        # The file can exist and still not carry the schema: connect() creates
        # it before apply_schema runs, so an interrupted first sync-league
        # leaves exactly this state. Report the checks that did not run rather
        # than raising out of doctor -- the check names are a contract.
        done = {c.name for c in core} | {c.name for c in history}
        for name in CORE_DB_CHECKS:
            if name not in done:
                core.append(Check(name, False, f"database at {path} is unusable: {exc}" if name == "database"
                                  else "skipped: database unusable"))
        for name in HISTORY_DB_CHECKS:
            if name not in done:
                history.append(Check(name, False, "skipped: database unusable"))
    finally:
        con.close()
    return core, history


def _yaml_check(name: str, path: Path, required_key: str) -> Check:
    if not path.is_file():
        return Check(name, False, f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return Check(name, False, f"does not parse: {exc}")
    if not isinstance(data, dict) or required_key not in data:
        return Check(name, False, f"no `{required_key}` key")
    return Check(name, True, f"{len(data)} top-level keys")


def run_doctor(paths: DoctorPaths, *, now: datetime) -> list[Check]:
    # Mirror load_settings() exactly -- same merge, same resolver. Deriving
    # this independently made doctor disagree with the commands it exists to
    # predict, in both directions: it passed a username whose password did not
    # resolve, and failed a workspace configured through the environment.
    env = {**(load_dotenv(paths.env) if paths.env.is_file() else {}), **os.environ}
    app_key = (env.get("FANTACALCIO_APP_KEY") or "").strip()
    checks = [Check("env", bool(app_key),
                    "FANTACALCIO_APP_KEY set" if app_key
                    else f"FANTACALCIO_APP_KEY not set in {paths.env} or the environment")]
    try:
        credentials = resolve_credentials(env)
    except ConfigurationError as exc:
        checks.append(Check("credentials", False, str(exc).split(".")[0]))
    else:
        checks.append(Check("credentials", True,
                            "login mode (password from the keychain or .env)"
                            if credentials.can_login
                            else "token-only mode (no self-healing on expiry)"))
    checks.append(_token_cache(paths.token_cache, now))
    core, history = _database_checks(paths.db, now)
    checks.extend(core)
    try:
        entries = load_league_yml(paths.league_yml) if paths.league_yml.is_file() else None
        checks.append(Check("league_yml", entries is not None,
                            f"{len(entries)} provenanced keys" if entries is not None else f"{paths.league_yml} is missing"))
    except (LeagueYmlError, yaml.YAMLError) as exc:
        checks.append(Check("league_yml", False, str(exc)))
    checks.append(_yaml_check("preferences", paths.preferences, "target_composition"))
    kb_ok = (paths.kb / "README.md").is_file() and (paths.kb / "rules" / "aliases.yml").is_file()
    checks.append(Check("kb", kb_ok, f"{paths.kb}" + ("" if kb_ok else " lacks README.md or rules/aliases.yml")))
    try:
        checks.append(Check("modules", True, f"{len(load_modules())} modules"))
    except (ModuleTableError, OSError, ValueError, yaml.YAMLError) as exc:
        checks.append(Check("modules", False, str(exc)))
    cookie = (env.get(WEB_COOKIE_KEY) or "").strip()
    checks.append(Check("web_session", bool(cookie),
                        f"{WEB_COOKIE_KEY} set" if cookie
                        else f"{WEB_COOKIE_KEY} not set -- `fantaclaude ingest stats-web` will be skipped"))
    checks.extend(history)
    aliases_file = paths.kb / "rules" / "aliases.yml"
    try:
        aliases = load_aliases(aliases_file) if aliases_file.is_file() else None
        checks.append(Check("aliases", aliases is not None,
                            f"{len(aliases.players) + len(aliases.teams)} sections" if aliases is not None
                            else f"{aliases_file} is missing"))
    except (AliasError, yaml.YAMLError) as exc:
        checks.append(Check("aliases", False, str(exc)))
    return checks
