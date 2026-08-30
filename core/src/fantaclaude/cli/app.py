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
        if payload.get("superseded_runs"):
            lines.append(f"{payload['superseded_runs']} valuation run(s) computed under the old rules are now superseded "
                         f"-- re-run `fantaclaude rank`")
    else:
        lines.append(f"unchanged (snapshot {payload['snapshot_id']})")
    return "\n".join(lines)


def _league_yml_or_exit():
    """league.yml's provenanced entries, or None when there is no file. A
    malformed file is not-ready (exit 3) whichever command reads it -- it
    used to be a traceback from sync-league and exit 3 from rank."""
    import yaml

    from fantaclaude.league.league_yml import LeagueYmlError, load_league_yml
    from fantaclaude.paths import league_yml_path

    path = league_yml_path()
    if not path.is_file():
        return None
    try:
        return load_league_yml(path)
    except LeagueYmlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        typer.echo(f"{path}: {exc}", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None


def _fetch_league(entries, *, json_: bool, league: str | None):
    """The network half of a re-sync, before any database is opened. DuckDB
    is single-writer, so the write lock must not span six round-trips, and
    connect() creates the file, so a failed fetch must not leave an
    empty-but-valid database behind. A league.yml conflict is rendered here
    and exits 4: nothing is recorded and no database is created. One copy of
    this flow for every command that re-syncs -- sync-league and rank today;
    rank used to carry its own, which had already drifted (it dropped the
    SyncReport, so a rules change detected mid-rank superseded every earlier
    run without showing the diff or the count)."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.sync_league import apply_sync, prepare_sync

    snap, conflicts = run_with_api(lambda api: prepare_sync(api, entries, league=league))
    if conflicts:
        emit(apply_sync(None, snap, conflicts).to_dict(), json_=json_, render=_render_sync)
        raise typer.Exit(code=ExitCode.CONFLICT)
    return snap


@app.command("sync-league")
def sync_league_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh league_settings from the league API: profile, status, the three settings payloads and the team list."""
    from fantaclaude.commands.sync_league import apply_sync
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    snap = _fetch_league(_league_yml_or_exit(), json_=json_, league=league)
    con = connect()
    try:
        apply_schema(con)
        report = apply_sync(con, snap, [])
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_sync)


ingest_app = typer.Typer(name="ingest", help="Fetch a source into data/raw/ and snapshot it into DuckDB.",
                         no_args_is_help=True)
app.add_typer(ingest_app)


def _render_listone(payload: dict) -> str:
    if payload["skipped_duplicate"]:
        return f"listone: duplicate of snapshot {payload['snapshot_id']} -- nothing new ({payload['raw_path']})"
    return f"listone: snapshot {payload['snapshot_id']}, {payload['inserted']} rows ({payload['raw_path']})"


@ingest_app.command("listone")
def ingest_listone_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Fetch the listone (539 players, Mantra roles and quotazioni) and snapshot it."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.listone_api import (
        fetch_listone,
        load_listone,
        record_listone,
    )
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir

    store = RawStore(raw_dir())
    # Fetch into data/raw/ first; open the database only to record. Same reason
    # as sync-league: the write lock should not span the network call, and a
    # failed first run must not leave an empty database that looks ingested.
    raw = run_with_api(lambda api: fetch_listone(api, store, league=league))
    con = connect()
    try:
        apply_schema(con)
        result = record_listone(con, load_listone(raw.path), raw)
    finally:
        con.close()
    emit(result.to_dict(), json_=json_, render=_render_listone)


def _render_all(payload: dict) -> str:
    lines = [_render_listone(payload["listone"]), _render_advanced(payload), _render_calendar(payload)]
    if payload["stats_web"] is not None:
        lines.append(_render_stats_web(payload))
    for reason in payload["skipped"]:
        lines.append(f"SKIPPED {reason}")
    return "\n".join(line for line in lines if line)


@ingest_app.command("all")
def ingest_all_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Refresh every source: listone (league API), advanced (Understat), calendar (fantacalcio.it, UEFA), stats-web (voti XLSX). Exit 3 if one had to be skipped."""
    from fantaclaude.api_client import run_with_api
    from fantaclaude.commands.ingest import (
        ensure_schema,
        existing_giornate,
        fetch_everything,
        record_everything,
    )
    from fantaclaude.config import web_cookie
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import build_http
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    ensure_schema()          # a stale schema must not crash a future read-only pre-read
    seasons = _seasons_or_exit(None)
    store = RawStore(raw_dir())
    cookie = web_cookie()

    with _source_errors():
        # Finding F4: existing_giornate reads every *-voti-*.xlsx already on
        # disk (openpyxl.load_workbook) -- one truncated file must raise
        # BadZipFile *inside* _source_errors, not before it, or the whole
        # command dies with an unmapped traceback before any work happens.
        existing = existing_giornate(store, seasons)     # from disk, not the database (Ruling R8b)

        async def go(api):
            http = build_http()
            try:
                return await fetch_everything(api, http, store, seasons=seasons, cookie=cookie,
                                              existing_voti=existing, league=league)
            finally:
                await http.aclose()

        fetched = run_with_api(go)
        con = connect()
        try:
            apply_schema(con)
            payload = record_everything(con, store, fetched, aliases_path())
        finally:
            con.close()
    emit(payload, json_=json_, render=_render_all)
    if payload["skipped"]:
        raise typer.Exit(code=ExitCode.NOT_READY)


# Module-level singletons for list-valued options: ruff's B008 exempts only
# immutable annotations, and `list[int] | None` is not one.
SEASON_OPTION = typer.Option(
    None, "--season", help="Season id(s), e.g. 20; default: the current season and the three before it.")

COMPETITION_OPTION = typer.Option(
    None, "--competition", help="SA, UCL, UEL or UECL; repeatable. Default: all four.")

GIORNATA_OPTION = typer.Option(
    None, "--giornata", help="Giornata number(s), 1-38; repeatable. Default: every giornata.")


@contextmanager
def _source_errors():
    """Map the web sources' errors to the exit-code contract.

    An expired website session is "not ready" (3): the fix is a new cookie,
    not a bug. Anything else a source does wrong is an error (1).

    Finding F4: `zipfile.BadZipFile` -- a truncated `*-voti-*.xlsx` already
    on disk, read by `existing_giornate`'s pre-read -- is neither a
    `SourceError` nor a `ValueError`, so it is mapped here too instead of
    escaping as a raw, unmapped traceback.
    """
    import zipfile

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
    except zipfile.BadZipFile as exc:               # a truncated workbook already on disk
        typer.echo(f"source shape unexpected: corrupted workbook: {exc}", err=True)
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
            if r["ambiguous"]:
                lines.append(f"  resolve it with an `understat:` alias in kb/rules/aliases.yml -- it applies on the next "
                             f"`fantaclaude ingest advanced --season {r['season_id']} --rematch` (zero network)")
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
    rematch: bool = typer.Option(False, "--rematch",
                                 help="Re-record from the raw files already on disk, without fetching -- "
                                      "applies a new alias or listone move to a season already recorded "
                                      "(Ruling R11). Zero network."),
) -> None:
    """Understat season totals (games, minutes, xG, xA) for Serie A, matched onto the listone."""
    from fantaclaude.commands.ingest import (
        ensure_schema,
        fetch_advanced_seasons,
        has_listone_snapshot,
        record_advanced_seasons,
        rematch_advanced_seasons,
    )
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    schema_version = ensure_schema()          # a stale schema must not crash a future read-only pre-read
    seasons = _seasons_or_exit(season)
    store = RawStore(raw_dir())
    if rematch:
        from fantaclaude.commands.ingest import NotReady

        if schema_version is None:
            # Finding "the --rematch branch re-opens F2's phantom database":
            # connect() below is read-write and creates the file -- must not
            # run at all when there is nothing yet to rematch against.
            typer.echo("no database -- run `fantaclaude sync-league` and `fantaclaude ingest listone` first",
                      err=True)
            raise typer.Exit(code=ExitCode.NOT_READY)
        with _source_errors():                # load_aliases can raise AliasError (a ValueError)
            con = connect()
            try:
                apply_schema(con)
                try:
                    results = rematch_advanced_seasons(con, store, seasons, aliases_path())
                except NotReady as exc:
                    typer.echo(str(exc), err=True)
                    raise typer.Exit(code=ExitCode.NOT_READY) from None
            finally:
                con.close()
        emit({"advanced": [r.to_dict() for r in results]}, json_=json_, render=_render_advanced)
        return
    from fantaclaude.commands.ingest import NotReady

    if not has_listone_snapshot():
        # Finding 3: checked before the fetch below -- record_advanced_seasons
        # raises the same NotReady, but only after the Understat round-trips
        # already ran and wrote raw files to disk the caller cannot use yet.
        on_disk = [s for s in seasons if store.list("advanced", ext="json", label=str(s))]
        if on_disk:
            typer.echo("no listone snapshot -- run `fantaclaude ingest listone`, then `fantaclaude ingest advanced "
                      f"--rematch` to record season(s) {on_disk} from the raw files already on disk (zero network)",
                      err=True)
        else:
            typer.echo("no listone snapshot -- run `fantaclaude ingest listone` first", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY)

    with _source_errors():
        raws = run_web(lambda http: fetch_advanced_seasons(http, store, seasons))
        con = connect()
        try:
            apply_schema(con)
            try:
                results = record_advanced_seasons(con, raws, aliases_path())
            except NotReady as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=ExitCode.NOT_READY) from None
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
    from fantaclaude.commands.ingest import (
        ensure_schema,
        fetch_calendar,
        record_calendar,
    )
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.calendar import COMPETITIONS
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import aliases_path, raw_dir

    # Finding F7: dedupe after upper-casing, preserving order -- otherwise
    # `--competition SA --competition sa` fetches Serie A twice (76 requests
    # at one per second) and, because `raws` is a dict keyed by name, the
    # first 38 raw files are orphaned on disk and never recorded.
    competitions = list(dict.fromkeys(c.upper() for c in competition)) if competition else list(COMPETITIONS)
    unknown = [c for c in competitions if c not in COMPETITIONS]
    if unknown:
        typer.echo(f"unknown competition {unknown}; choose from {', '.join(COMPETITIONS)}", err=True)
        raise typer.Exit(code=ExitCode.USAGE)
    ensure_schema()          # a stale schema must not crash a future read-only pre-read
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


def _ranges(values: list[int]) -> str:
    """[1, 2, 3, 7] -> '1-3, 7'"""
    parts: list[tuple[int, int]] = []
    for value in sorted(values):
        if parts and value == parts[-1][1] + 1:
            parts[-1] = (parts[-1][0], value)
        else:
            parts.append((value, value))
    return ", ".join(f"{a}-{b}" if a != b else f"{a}" for a, b in parts)


def _render_stats_web(payload: dict) -> str:
    data = payload["stats_web"]
    not_yet_rated = data.get("not_yet_rated", {})
    lines = []
    seasons = {f["season_id"] for f in data["files"]} | {int(s) for s in data["skipped"]} \
        | {int(s) for s in not_yet_rated}
    for season in sorted(seasons):
        files = [f for f in data["files"] if f["season_id"] == season]
        new = [f for f in files if not f["skipped_duplicate"]]
        dupes = [f for f in files if f["skipped_duplicate"]]
        bits = [f"{len(new)} new file(s)" + (f" (giornate {_ranges([f['giornata'] for f in new])})" if new else "")]
        if dupes:
            bits.append(f"{len(dupes)} duplicate(s)")
        skipped = data["skipped"].get(str(season), [])
        if skipped:
            bits.append(f"skipped {_ranges(skipped)} (already on disk)")
        stop = data["not_published_from"].get(str(season))
        if stop is not None:
            bits.append(f"not published from {stop}")
        rated = not_yet_rated.get(str(season), [])
        if rated:
            bits.append(f"not yet rated: giornata {_ranges(rated)}")
        lines.append(f"voti {season}: " + ", ".join(bits))
        if new:
            rows = sum(f["inserted"] for f in new)
            unknown = sum(f["unknown_players"] for f in new)
            lines.append(f"  sheets {', '.join(new[0]['sheets'])}; {rows} rows; "
                         f"{unknown} player ids not in the current listone")
    return "\n".join(lines) or "nothing to do"


@ingest_app.command("stats-web")
def ingest_stats_web_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    season: list[int] | None = SEASON_OPTION,
    giornata: list[int] | None = GIORNATA_OPTION,
    refetch: bool = typer.Option(False, "--refetch", help="Download again what is already on disk."),
) -> None:
    """Per-giornata voti and event counts from fantacalcio.it's XLSX export (needs FANTACALCIO_WEB_COOKIE)."""
    from fantaclaude.commands.ingest import (
        ensure_schema,
        existing_giornate,
        fetch_voti_seasons,
        record_voti_files,
    )
    from fantaclaude.config import web_cookie
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.model.seasons import SERIE_A_GIORNATE
    from fantaclaude.paths import raw_dir

    cookie = web_cookie()
    if cookie is None:
        typer.echo("FANTACALCIO_WEB_COOKIE is not set -- capture the website session first "
                   "(core/README.md, 'The website session')", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY)
    giornate = sorted(set(giornata)) if giornata else list(range(1, SERIE_A_GIORNATE + 1))
    bad = [g for g in giornate if not 1 <= g <= SERIE_A_GIORNATE]
    if bad:
        typer.echo(f"--giornata must be between 1 and {SERIE_A_GIORNATE}, got {bad}", err=True)
        raise typer.Exit(code=ExitCode.USAGE)
    ensure_schema()          # a stale schema must not crash a future read-only pre-read
    seasons = _seasons_or_exit(season)
    store = RawStore(raw_dir())
    with _source_errors():
        # Finding F4: existing_giornate reads every *-voti-*.xlsx already on
        # disk (openpyxl.load_workbook) -- one truncated file must raise
        # BadZipFile *inside* _source_errors, not before it, or the whole
        # command dies with an unmapped traceback before any work happens.
        existing = existing_giornate(store, seasons)     # from disk, not the database (Ruling R8b)
        fetched = run_web(lambda http: fetch_voti_seasons(
            http, store, cookie=cookie, seasons=seasons, giornate=giornate, existing=existing, refetch=refetch))
        con = connect()
        try:
            apply_schema(con)
            results, not_yet_rated = record_voti_files(con, store, fetched, giornate)
        finally:
            con.close()
    payload = {"stats_web": {
        "files": [r.to_dict() for r in results],
        "skipped": {str(s): sorted(f.skipped) for s, f in fetched.items()},
        "not_published_from": {str(s): f.not_published_from for s, f in fetched.items()
                               if f.not_published_from is not None},
        "not_yet_rated": {str(s): sorted(g) for s, g in not_yet_rated.items()},
    }}
    emit(payload, json_=json_, render=_render_stats_web)


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
    """Readiness check: credentials, token cache, website session, database, every snapshot's coverage, league.yml, kb, aliases, module table, scoring, pricing, valuations."""
    from fantacalcio_mcp.config import env_path, token_cache_path

    from fantaclaude.commands.doctor import DoctorPaths, run_doctor
    from fantaclaude.paths import (
        db_path,
        kb_dir,
        league_yml_path,
        preferences_yml_path,
        pricing_yml_path,
    )
    from fantaclaude.timeutil import utc_now

    paths = DoctorPaths(env=env_path(), token_cache=token_cache_path(), db=db_path(),
                        league_yml=league_yml_path(), preferences=preferences_yml_path(), kb=kb_dir(),
                        pricing=pricing_yml_path())
    checks = run_doctor(paths, now=utc_now())
    payload = {"ok": all(c.ok for c in checks), "checks": [c.to_dict() for c in checks]}
    emit(payload, json_=json_, render=_render_doctor)
    if not payload["ok"]:
        raise typer.Exit(code=ExitCode.NOT_READY)


# Module-level singleton for a list-valued option: ruff's B008 exempts only
# immutable annotations, and `list[str] | None` is not one.
SCENARIO_OPTION = typer.Option(
    None, "--scenario", help="Only these scenarios from preferences.yml (repeatable). Default: all of them.")


def _render_rank(payload: dict) -> str:
    s = payload["summary"]
    lines = []
    if payload.get("sync") and payload["sync"]["changed"]:       # the rules moved under this run: say so, as sync-league would
        lines.append(_render_sync(payload["sync"]))
    lines += [(f"run {payload['run_id']} · rules {payload['rules_hash']} · model {payload['model_hash']} · "
               f"inputs {payload['inputs_hash']}"),
             (f"{payload['players']} players · {s['team_count']} teams × {s['budget']} credits · giornata "
              f"{s['giornate_played']} played · voti sheet {s['sheet']}"
              + (" · D-Factor active" if s.get("d_factor_active") else "")),
             payload["provisional"]]
    for name, sc in s["scenarios"].items():
        comp = ", ".join(f"{cls} {n}·{sc['credits_by_class'].get(cls, 0)}" for cls, n in sc["composition"].items() if n)
        departed = f" (departed from the target at {', '.join(sc['targets_departed'])})" if sc["targets_departed"] else ""
        lines.append(f"{name}: inflation {sc['inflation']:.2f}, reserve {sc['reserve']}, composition {comp}{departed}")
    for cls, entries in payload["top"].items():
        lines.append(f"  {cls}: " + ", ".join(f"{e['name']} ({e['team']}) {e['value_p50']} → max {e['max_p50']} t{e['tier']}"
                                             for e in entries))
    for w in payload["warnings"]:
        lines.append(f"warning: {w}")
    lines.append("exports: " + ", ".join(payload["exports"]))
    lines.append(("records: " + ", ".join(payload["records"]) + " -- commit records/") if payload["records"]
                 else "records: already present")
    return "\n".join(lines)


@app.command("rank")
def rank_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    offline: bool = typer.Option(False, "--offline", help="Do not re-sync league_settings from the league API first."),
    scenario: list[str] | None = SCENARIO_OPTION,
    league: str | None = typer.Option(None, "--league", help="League alias; only for multi-league accounts."),
) -> None:
    """Write a valuation run: project every listone player, price the board, render data/exports/ and records/. Re-syncs the league first unless --offline."""
    from fantaclaude.analysis.valuation import UnknownScenarioError
    from fantaclaude.commands.ingest import NotReady
    from fantaclaude.commands.rank import check_ready, rank
    from fantaclaude.commands.sync_league import apply_sync
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.paths import (
        exports_dir,
        kb_dir,
        preferences_yml_path,
        pricing_yml_path,
        records_dir,
    )
    from fantaclaude.timeutil import utc_now

    entries = _league_yml_or_exit()
    try:
        # Finding 2: preferences.yml, pricing.yml and d_factor.yml need no
        # database at all -- checked here, before connect() below creates and
        # schemas the file, so a never-synced workspace refuses cleanly
        # instead of leaving a phantom database that later reads as "ok".
        check_ready(preferences_yml_path(), pricing_yml_path())
    except NotReady as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    snap = None if offline else _fetch_league(entries, json_=json_, league=league)
    con = connect()
    try:
        apply_schema(con)
        sync = apply_sync(con, snap, []) if snap is not None else None
        try:
            report = rank(con, now=utc_now(), kb_dir=kb_dir(), preferences_path=preferences_yml_path(),
                          pricing_path=pricing_yml_path(), exports_dir=exports_dir(), records_dir=records_dir(),
                          league_yml=entries, scenarios=list(scenario) if scenario else None, sync=sync)
        except NotReady as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
        except UnknownScenarioError as exc:
            # The one genuine usage error here: `--scenario nope` is a bad
            # argument, not a bad file. A malformed preferences.yml is caught
            # by check_ready as NotReady, with pricing.yml and d_factor.yml
            # (finding 17).
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.USAGE) from None
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_rank)


def main() -> None:
    app()
