"""The `fantaclaude` CLI: the single interface skills call.

Every read command takes --json and prints one JSON document on stdout; the
human rendering is the same payload passed through a small renderer. Exit codes
are part of the contract (see ExitCode) so a caller can tell "nothing ingested
yet" from "this crashed" without parsing a traceback. Commands are thin: each
one calls an importable function under fantaclaude.commands.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from enum import IntEnum

import typer

from fantaclaude import __version__


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1
    USAGE = 2          # Typer/Click's own code for bad arguments
    NOT_READY = 3      # database missing, nothing ingested yet, doctor failed
    CONFLICT = 4       # league.yml disagrees with the API


app = typer.Typer(
    name="fantaclaude",
    help="Fantacalcio Mantra assistant — data spine and auction tooling.",
    no_args_is_help=True,
)


def emit(payload: dict, *, json_: bool, render: Callable[[dict], str]) -> None:
    """Print `payload` as JSON (--json) or through `render` (human)."""
    if json_:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
    else:
        typer.echo(render(payload))


def _version(value: bool) -> None:
    if value:
        typer.echo(f"fantaclaude {__version__}")
        raise typer.Exit(code=ExitCode.OK)


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True,
        help="Print the version and exit."),
) -> None:
    """Fantacalcio Mantra assistant — data spine and auction tooling."""


def _render_sync(payload: dict) -> str:
    lines = [(f"league {payload['league_id']} · season {payload['season_id']} · "
              f"{payload['team_count']} teams · rules {payload['rules_hash']}")]
    for c in payload["conflicts"]:
        lines.append(f"CONFLICT {c['key']}: league.yml says {c['league_yml']!r}, the API says {c['api']!r}")
    if payload["conflicts"]:
        lines.append("nothing recorded -- fix league.yml (it must never override the API) and re-run")
        return "\n".join(lines)
    if payload["changed"]:
        was = f" (was {payload['previous_hash']})" if payload["previous_hash"] else " (first snapshot)"
        lines.append(f"changed: snapshot {payload['snapshot_id']}{was}")
        for c in payload["diff"]:
            lines.append(f"  {c['path']}: {c['before']!r} -> {c['after']!r}")
    else:
        lines.append(f"unchanged (snapshot {payload['snapshot_id']})")
    return "\n".join(lines)


@app.command("sync-league")
def sync_league_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh league_settings from the league API: profile, status, the three settings payloads and the team list."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.sync_league import apply_sync, prepare_sync
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.league.league_yml import load_league_yml
    from fantaclaude.paths import league_yml_path

    entries = load_league_yml(league_yml_path()) if league_yml_path().is_file() else None
    # Fetch before opening the database. connect() creates the file, and DuckDB
    # is single-writer: opening first would hold the lock across six round-trips
    # and leave an empty-but-valid database behind if any of them failed.
    snap, conflicts = run_with_api(lambda api: prepare_sync(api, entries, league=league))
    if conflicts:
        report = apply_sync(None, snap, conflicts)
    else:
        con = connect()
        try:
            apply_schema(con)
            report = apply_sync(con, snap, conflicts)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_sync)
    if report.conflicts:
        raise typer.Exit(code=ExitCode.CONFLICT)


ingest_app = typer.Typer(name="ingest", help="Fetch a source into data/raw/ and snapshot it into DuckDB.",
                         no_args_is_help=True)
app.add_typer(ingest_app)


def _render_ingest(payload: dict) -> str:
    lines = []
    for name, result in payload.items():
        if result["skipped_duplicate"]:
            lines.append(f"{name}: duplicate of snapshot {result['snapshot_id']} -- nothing new ({result['raw_path']})")
        else:
            lines.append(f"{name}: snapshot {result['snapshot_id']}, {result['inserted']} rows ({result['raw_path']})")
    return "\n".join(lines)


def _run_ingest(names: list[str], json_: bool, league: str | None) -> None:
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.ingest import fetch_all, record_all
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.listone_api import fetch_listone
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir

    store = RawStore(raw_dir())
    # Fetch into data/raw/ first; open the database only to record. Same reason
    # as sync-league: the write lock should not span the network call, and a
    # failed first run must not leave an empty database that looks ingested.
    if names == ["all"]:
        raws = run_with_api(lambda api: fetch_all(api, store, league=league))
    else:
        # Only what was asked for: every fetch is a live call against a real
        # account, so `ingest listone` must not pull the other sources too.
        raws = {"listone": run_with_api(lambda api: fetch_listone(api, store, league=league))}
    con = connect()
    try:
        apply_schema(con)
        results = record_all(con, raws)
    finally:
        con.close()
    payload = {name: r.to_dict() for name, r in results.items()}
    if names != ["all"]:
        emit(payload["listone"], json_=json_, render=lambda p: _render_ingest({"listone": p}))
    else:
        emit(payload, json_=json_, render=_render_ingest)


@ingest_app.command("listone")
def ingest_listone_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Fetch the listone (539 players, Mantra roles and quotazioni) and snapshot it."""
    _run_ingest(["listone"], json_, league)


@ingest_app.command("all")
def ingest_all_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh every source (listone; advanced, calendar and stats-web join in Task 8)."""
    _run_ingest(["all"], json_, league)


# Module-level singletons for list-valued options: ruff's B008 exempts only
# immutable annotations, and `list[int] | None` is not one.
SEASON_OPTION = typer.Option(
    None, "--season", help="Season id(s), e.g. 20; default: the current season and the three before it.")

COMPETITION_OPTION = typer.Option(
    None, "--competition", help="SA, UCL, UEL or UECL; repeatable. Default: all four.")


@contextmanager
def _source_errors():
    """Map the web sources' errors to the exit-code contract.

    An expired website session is "not ready" (3): the fix is a new cookie,
    not a bug. Anything else a source does wrong is an error (1).
    """
    from fantaclaude.ingest.http import SourceError, WebSessionExpired

    try:
        yield
    except WebSessionExpired as exc:
        typer.echo(f"website session rejected: {exc} -- re-capture FANTACALCIO_WEB_COOKIE "
                   f"(core/README.md, 'The website session')", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    except SourceError as exc:
        typer.echo(f"source failed: {exc}", err=True)
        raise typer.Exit(code=ExitCode.ERROR) from None
    except ValueError as exc:                      # *ShapeError: the source changed under us
        typer.echo(f"source shape unexpected: {exc}", err=True)
        raise typer.Exit(code=ExitCode.ERROR) from None


def _seasons_or_exit(season: list[int] | None) -> list[int]:
    from fantaclaude.commands.ingest import NotReady, default_seasons

    try:
        return list(season) if season else default_seasons()
    except NotReady as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None


def _render_advanced(payload: dict) -> str:
    lines = []
    for r in payload["advanced"]:
        if r["skipped_duplicate"]:
            lines.append(f"advanced {r['season_id']}: duplicate of snapshot {r['snapshot_id']} -- nothing new "
                         f"({r['matched']} matched, {r['ambiguous']} ambiguous, {r['unmatched']} unmatched)")
            continue
        lines.append(f"advanced {r['season_id']}: snapshot {r['snapshot_id']}, {r['inserted']} rows -- "
                     f"{r['matched']} matched, {r['alias']} alias, {r['ambiguous']} ambiguous, "
                     f"{r['unmatched']} unmatched ({r['raw_path']})")
        for a in r["ambiguous_names"]:
            options = ", ".join(f"{c['player_id']} {c['name']}" for c in a["candidates"])
            lines.append(f"  ambiguous: {a['name']} ({', '.join(a['teams'])}) -> {options}")
        if r["unresolved_teams"]:
            lines.append(f"  clubs not in the listone: {', '.join(r['unresolved_teams'])}")
    return "\n".join(lines)


@ingest_app.command("advanced")
def ingest_advanced_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    season: list[int] | None = SEASON_OPTION,
) -> None:
    """Understat season totals (games, minutes, xG, xA) for Serie A, matched onto the listone."""
    from fantaclaude.commands.ingest import (
        fetch_advanced_seasons,
        record_advanced_seasons,
    )
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    seasons = _seasons_or_exit(season)
    store = RawStore(raw_dir())
    with _source_errors():
        raws = run_web(lambda http: fetch_advanced_seasons(http, store, seasons))
        con = connect()
        try:
            apply_schema(con)
            results = record_advanced_seasons(con, raws, aliases_path())
        finally:
            con.close()
    emit({"advanced": [r.to_dict() for r in results]}, json_=json_, render=_render_advanced)


def _render_calendar(payload: dict) -> str:
    lines = []
    for r in payload["calendar"]:
        if r["skipped_unchanged"]:
            lines.append(f"calendar {r['competition']} {r['season_id']}: unchanged (snapshot {r['snapshot_id']})")
        else:
            lines.append(f"calendar {r['competition']} {r['season_id']}: snapshot {r['snapshot_id']}, "
                         f"{r['inserted']} fixtures ({len(r['raw_paths'])} raw files)")
    return "\n".join(lines)


@ingest_app.command("calendar")
def ingest_calendar_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    competition: list[str] | None = COMPETITION_OPTION,
) -> None:
    """The current season's Serie A calendar (fantacalcio.it) and every UEFA tie of an Italian club."""
    from fantaclaude.commands.ingest import fetch_calendar, record_calendar
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.calendar import COMPETITIONS
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    competitions = [c.upper() for c in competition] if competition else list(COMPETITIONS)
    unknown = [c for c in competitions if c not in COMPETITIONS]
    if unknown:
        typer.echo(f"unknown competition {unknown}; choose from {', '.join(COMPETITIONS)}", err=True)
        raise typer.Exit(code=ExitCode.USAGE)
    season_id = _seasons_or_exit(None)[-1]           # the season the league is in
    store = RawStore(raw_dir())
    with _source_errors():
        raws = run_web(lambda http: fetch_calendar(http, store, season_id, competitions))
        con = connect()
        try:
            apply_schema(con)
            results = record_calendar(con, season_id, raws, aliases_path())
        finally:
            con.close()
    emit({"calendar": [r.to_dict() for r in results]}, json_=json_, render=_render_calendar)


def _open_read_only():
    import duckdb

    from fantaclaude.db.connection import DatabaseMissing, connect

    try:
        return connect(read_only=True)
    except DatabaseMissing as exc:
        typer.echo(f"no database at {exc} -- run `fantaclaude sync-league` or "
                   f"`fantaclaude ingest listone` first", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY)
    except duckdb.Error as exc:
        # A writer holds the file for the duration of its work. "Not ready" is
        # the honest answer -- exit 1 means "this crashed", and a caller that
        # cannot tell a transient lock from a bug will retry the wrong thing.
        typer.echo(f"database is not available right now (a writer may hold it): {exc}",
                   err=True)
        raise typer.Exit(code=ExitCode.NOT_READY)


def _render_schema(payload: dict) -> str:
    lines = [f"schema version {payload['version']}"]
    for t in payload["tables"]:
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        lines.append(f"{t['kind']} {t['name']} ({t['rows']} rows): {cols}")
    return "\n".join(lines)


@app.command("schema")
def schema_cmd(json_: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """List tables, views and columns -- the names `query --sql` may use. Prefer the v_* views."""
    from fantaclaude.db.schema import schema_report

    con = _open_read_only()
    try:
        report = schema_report(con)
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_schema)


def _render_rows(payload: dict) -> str:
    columns, rows = payload["columns"], payload["rows"]
    if not columns:
        return "(no result set)"
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    line = lambda values: "  ".join(v.ljust(w) for v, w in zip(values, widths))
    out = [line(columns), line(["-" * w for w in widths]), *(line(r) for r in cells)]
    if payload["truncated"]:
        out.append(f"... truncated at {len(rows)} rows (raise --limit)")
    return "\n".join(out)


@app.command("query")
def query_cmd(
    sql: str = typer.Option(..., "--sql", help="A read-only SQL statement."),
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    limit: int = typer.Option(200, "--limit", help="Maximum rows returned."),
) -> None:
    """Run ad-hoc read-only SQL against fanta.duckdb. Query the v_* views by name; raw table shapes may change."""
    import duckdb

    con = _open_read_only()
    try:
        try:
            cursor = con.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(limit + 1) if columns else []
        except duckdb.Error as exc:
            typer.echo(f"query failed: {exc}", err=True)
            raise typer.Exit(code=ExitCode.ERROR)
    finally:
        con.close()
    truncated = len(rows) > limit
    payload = {"columns": columns, "rows": [list(r) for r in rows[:limit]], "truncated": truncated}
    emit(payload, json_=json_, render=_render_rows)


kb_app = typer.Typer(name="kb", help="Knowledge-base maintenance.", no_args_is_help=True)
app.add_typer(kb_app)


def _render_audit(payload: dict) -> str:
    lines = [f"{e['status']:<20} {e['path']}  ({e['detail']})" for e in payload["entries"]]
    lines.append(f"{len(payload['entries'])} documents: {payload['expired']} expired, "
                 f"{payload['invalid']} invalid, {payload['missing_front_matter']} without front-matter")
    return "\n".join(lines)


@kb_app.command("audit")
def kb_audit_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    today: str | None = typer.Option(None, "--today", help="ISO date to audit against (default: today)."),
) -> None:
    """List knowledge-base documents that have expired, lack front-matter, or are malformed."""
    from datetime import date

    from fantaclaude.kb.audit import audit
    from fantaclaude.paths import kb_dir
    from fantaclaude.timeutil import utc_now

    if today is None:
        as_of = utc_now().date()
    else:
        try:
            as_of = date.fromisoformat(today)
        except ValueError:
            typer.echo(f"--today must be an ISO date (YYYY-MM-DD), got {today!r}", err=True)
            raise typer.Exit(code=ExitCode.USAGE) from None

    entries = audit(kb_dir(), as_of)
    payload = {
        "entries": [e.to_dict() for e in entries],
        "expired": sum(e.status == "expired" for e in entries),
        "invalid": sum(e.status == "invalid" for e in entries),
        "missing_front_matter": sum(e.status == "missing_front_matter" for e in entries),
    }
    emit(payload, json_=json_, render=_render_audit)


def _render_doctor(payload: dict) -> str:
    lines = [f"{'ok ' if c['ok'] else 'FAIL'}  {c['name']:<16} {c['detail']}" for c in payload["checks"]]
    lines.append("ready" if payload["ok"] else "not ready")
    return "\n".join(lines)


@app.command("doctor")
def doctor_cmd(json_: bool = typer.Option(False, "--json", help="Machine-readable output.")) -> None:
    """Readiness check: credentials, token cache, database, snapshots, league.yml, kb, module table."""
    from fantacalcio_mcp.config import env_path, token_cache_path

    from fantaclaude.commands.doctor import DoctorPaths, run_doctor
    from fantaclaude.paths import db_path, kb_dir, league_yml_path, preferences_yml_path
    from fantaclaude.timeutil import utc_now

    paths = DoctorPaths(env=env_path(), token_cache=token_cache_path(), db=db_path(),
                        league_yml=league_yml_path(), preferences=preferences_yml_path(), kb=kb_dir())
    checks = run_doctor(paths, now=utc_now())
    payload = {"ok": all(c.ok for c in checks), "checks": [c.to_dict() for c in checks]}
    emit(payload, json_=json_, render=_render_doctor)
    if not payload["ok"]:
        raise typer.Exit(code=ExitCode.NOT_READY)


def main() -> None:
    app()
