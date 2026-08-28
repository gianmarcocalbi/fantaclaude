"""fantaclaude doctor: is the workspace ready for the night?

Every check reports existence, parseability or age -- never a value. A token
is "present, expires in N days", an app key is "set", and nothing here can
leak into a terminal log.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import yaml
from fantacalcio_mcp.auth import AuthError, is_expired
from fantacalcio_mcp.config import load_dotenv

from fantaclaude.db.schema import SCHEMA_VERSION
from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
from fantaclaude.model.modules import ModuleTableError, load_modules


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


def _database_checks(path: Path, now: datetime) -> list[Check]:
    if not path.is_file():
        missing = Check("database", False, f"no database at {path} -- run `fantaclaude sync-league` and `fantaclaude ingest listone`")
        skipped = "skipped: no database"
        return [missing, Check("extensions", False, skipped), Check("league_settings", False, skipped),
                Check("listone", False, skipped)]
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        failed = Check("database", False, f"cannot open database at {path}: {exc}")
        skipped = "skipped: database unavailable"
        return [failed, Check("extensions", False, skipped), Check("league_settings", False, skipped),
                Check("listone", False, skipped)]
    checks: list[Check] = []
    try:
        version = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
        checks.append(Check("database", version == SCHEMA_VERSION,
                            f"schema version {version}, code expects {SCHEMA_VERSION}"))
        installed = {r[0] for r in con.execute(
            "SELECT extension_name FROM duckdb_extensions() WHERE installed").fetchall()}
        needed = {"json", "parquet"}
        checks.append(Check("extensions", needed <= installed,
                            f"installed: {', '.join(sorted(needed & installed)) or 'none'}; "
                            f"missing: {', '.join(sorted(needed - installed)) or 'none'}"))
        row = con.execute("SELECT fetched_at, rules_hash, budget, team_count FROM v_league_settings_current").fetchone()
        if row is None:
            checks.append(Check("league_settings", False, "no snapshot -- run `fantaclaude sync-league`"))
        else:
            checks.append(Check("league_settings", True,
                                f"rules {row[1]}, budget {row[2]}, {row[3]} teams, {_age(row[0], now)}"))
        row = con.execute("SELECT fetched_at, player_count FROM listone_snapshots "
                          "ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        if row is None:
            checks.append(Check("listone", False, "no snapshot -- run `fantaclaude ingest listone`"))
        else:
            checks.append(Check("listone", True, f"{row[1]} players, {_age(row[0], now)}"))
    except duckdb.Error as exc:
        # The file can exist and still not carry the schema: connect() creates
        # it before apply_schema runs, and the DDL is applied statement by
        # statement without a transaction, so an interrupted first sync-league
        # leaves exactly this state. Report the checks that did not run rather
        # than raising out of doctor -- the eleven names are a contract.
        done = {c.name for c in checks}
        for name in ("database", "extensions", "league_settings", "listone"):
            if name in done:
                continue
            detail = (f"database at {path} is unusable: {exc}" if name == "database"
                      else "skipped: database unusable")
            checks.append(Check(name, False, detail))
    finally:
        con.close()
    return checks


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
    env = load_dotenv(paths.env) if paths.env.is_file() else {}
    checks = [Check("env", paths.env.is_file() and bool(env.get("FANTACALCIO_APP_KEY")),
                    "FANTACALCIO_APP_KEY set" if env.get("FANTACALCIO_APP_KEY") else f"{paths.env} missing or without FANTACALCIO_APP_KEY")]
    if env.get("FANTACALCIO_USERNAME"):
        checks.append(Check("credentials", True, "login mode (password from the keychain or .env)"))
    elif env.get("FANTACALCIO_LEAGUE_TOKEN"):
        checks.append(Check("credentials", True, "token-only mode (no self-healing on expiry)"))
    else:
        checks.append(Check("credentials", False, "neither FANTACALCIO_USERNAME nor FANTACALCIO_LEAGUE_TOKEN in .env"))
    checks.append(_token_cache(paths.token_cache, now))
    checks.extend(_database_checks(paths.db, now))
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
    return checks
