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
from pathlib import Path

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
    lines += [f"warning: {w}" for w in payload.get("warnings", [])]
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


def _render_probabili(payload: dict) -> str:
    head = f"probabili {payload['season_id']} giornata {payload['giornata']}"
    if payload["skipped_duplicate"]:
        return f"{head}: duplicate of file {payload['file_id']} -- nothing new ({payload['raw_path']})"
    line = f"{head}: file {payload['file_id']}, {payload['inserted']} players over {payload['matches']} compiled match(es)"
    if payload["uncompiled"]:
        line += f", {payload['uncompiled']} not yet compiled"
    if payload["unknown_players"]:
        line += f"; {payload['unknown_players']} player ids not in the current listone"
    if payload["duplicates"]:
        line += f"; {payload['duplicates']} listed twice (first kept)"
    return f"{line} ({payload['raw_path']})"


GIORNATA_ONE_OPTION = typer.Option(None, "--giornata", help="The giornata (default: the next one on the calendar).")


@ingest_app.command("probabili")
def ingest_probabili_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = GIORNATA_ONE_OPTION,
) -> None:
    """The probabili formazioni page (fantacalcio.it, public): every player's published p_start for the next giornata. One request."""
    from fantaclaude.analysis.weekly import ForecastError, target_round
    from fantaclaude.commands.ingest import ensure_schema
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.http import run_web
    from fantaclaude.ingest.probabili import (
        fetch_probabili,
        parse_probabili_page,
        record_probabili,
    )
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir
    from fantaclaude.timeutil import utc_now

    ensure_schema()
    season_id = _seasons_or_exit(None)[-1]
    con = connect(read_only=True)                 # the round is a pre-read; the write lock must not span the request
    try:
        round_ = target_round(con, utc_now(), season_id=season_id, giornata=giornata)
    except ForecastError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    finally:
        con.close()
    store = RawStore(raw_dir())
    with _source_errors():
        raw = run_web(lambda http: fetch_probabili(http, store, label=f"{season_id}-{round_.giornata:02d}"))
        page = parse_probabili_page(raw.path.read_text(encoding="utf-8"))
        if page.giornata is not None and page.giornata != round_.giornata:
            typer.echo(f"the page is giornata {page.giornata}, not {round_.giornata} -- pass --giornata {page.giornata} "
                       f"if that is the round you want recorded", err=True)
            raise typer.Exit(code=ExitCode.CONFLICT)
        con = connect()
        try:
            apply_schema(con)
            result = record_probabili(con, season_id, round_.giornata, page, raw)
        finally:
            con.close()
    emit(result.to_dict(), json_=json_, render=_render_probabili)


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
    """Readiness check: credentials, token cache, website session, database, every snapshot's coverage, league.yml, kb, aliases, module table, scoring, pricing, valuations, the pinned run, adjustments.yml, the auction state file, the dashboard bundle."""
    from fantacalcio_mcp.config import env_path, token_cache_path

    from fantaclaude.commands.doctor import DoctorPaths, run_doctor
    from fantaclaude.paths import (
        adjustments_path,
        asta_state_path,
        db_path,
        kb_dir,
        league_yml_path,
        preferences_yml_path,
        pricing_yml_path,
        web_dist_dir,
    )
    from fantaclaude.timeutil import utc_now

    paths = DoctorPaths(env=env_path(), token_cache=token_cache_path(), db=db_path(),
                        league_yml=league_yml_path(), preferences=preferences_yml_path(), kb=kb_dir(),
                        pricing=pricing_yml_path(), adjustments=adjustments_path(), asta_state=asta_state_path(),
                        web_dist=web_dist_dir())
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
    from fantaclaude.analysis.exports import header_lines

    s = payload["summary"]
    lines = []
    if payload.get("sync") and payload["sync"]["changed"]:       # the rules moved under this run: say so, as sync-league would
        lines.append(_render_sync(payload["sync"]))
    lines += [*header_lines(payload["run_id"], payload["rules_hash"], payload["model_hash"], payload["inputs_hash"],
                            s, payload["warnings"]),
             payload["provisional"]]
    for name, sc in s["scenarios"].items():
        comp = ", ".join(f"{cls} {n}·{sc['credits_by_class'].get(cls, 0)}" for cls, n in sc["composition"].items() if n)
        departed = f" (departed from the target at {', '.join(sc['targets_departed'])})" if sc["targets_departed"] else ""
        lines.append(f"{name}: inflation {sc['inflation']:.2f}, reserve {sc['reserve']}, composition {comp}{departed}")
    for cls, entries in payload["top"].items():
        lines.append(f"  {cls}: " + ", ".join(f"{e['name']} ({e['team']}) {e['value_p50']} → max {e['max_p50']} t{e['tier']}"
                                             for e in entries))
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


def _render_lineup(payload: dict) -> str:
    r, page = payload["round"], payload["page"]
    lines = [(f"giornata {r['giornata']} · deadline {r['first_kickoff']} UTC · run {payload['run_id']} · page {page['fetched_at']} "
              f"({page['players']} players, {page['matches']} compiled)")]
    if payload["late"]:
        lines.append("LATE: written after the first kickoff -- marked, and calibration will exclude it")
    for role, rows in payload["top"].items():
        lines.append(f"  {role}: " + " · ".join(
            f"{x['name']} {x['p_start_published']}%×{x['fv_if_plays']:.2f}={x['expected_points']:.2f}" for x in rows))
    xi = payload.get("xi")
    if xi is None:
        lines.append(f"XI: none -- {payload['no_xi_reason']}")
    else:
        lines.append(f"XI: {xi['module']} · expected {xi['total']:.2f}")
        lines += [f"  {s['slot']:<6} {s['name']} ({s['fit']}, {s['expected_points']:.2f})" for s in xi["slots"]]
        others = " · ".join(f"{m} {v:.2f}" if v is not None else f"{m} -"
                            for m, v in xi["module_scores"].items() if m != xi["module"])
        lines.append(f"  other modules: {others}")
    lines.append(f"written: lineup_run {payload['lineup_run_id']}, {payload['predictions']} predictions"
                 + (" · " + ", ".join(payload["records"]) if payload["records"] else " · records already exist"))
    lines += [f"warning: {w}" for w in payload["warnings"]]
    return "\n".join(lines)


LINEUP_RUN_OPTION = typer.Option(None, "--run", help="Read projections from this valuation run (default: the newest not superseded).")


@app.command("lineup")
def lineup_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    giornata: int | None = GIORNATA_ONE_OPTION,
    run: str | None = LINEUP_RUN_OPTION,
    late: bool = typer.Option(False, "--late", help="Write even though the giornata has kicked off; the row is marked and calibration excludes it."),
) -> None:
    """Write the giornata's forecast -- p_start x expected fantavoto for every player the probabili page lists -- and, when league.yml names my team, the XI and module that maximise expected points. Local, no network."""
    from fantaclaude.analysis.weekly import ForecastError, LateForecast, lineup
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.paths import records_dir
    from fantaclaude.timeutil import utc_now

    entries = _league_yml_or_exit()
    my_team: int | None = None
    if entries and "my_team" in entries:
        try:
            my_team = int(entries["my_team"].value)
        except (TypeError, ValueError):
            typer.echo("league.yml: my_team.value must be the lega team id (an integer)", err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
    season_id = _seasons_or_exit(None)[-1]
    con = connect()
    try:
        apply_schema(con)
        try:
            report = lineup(con, now=utc_now(), season_id=season_id, giornata=giornata, run_id=run, late=late,
                            my_team=my_team, records_dir=records_dir())
        except LateForecast as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.CONFLICT) from None
        except ForecastError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=ExitCode.NOT_READY) from None
    finally:
        con.close()
    emit(report.to_dict(), json_=json_, render=_render_lineup)


asta_app = typer.Typer(name="asta", help="The auction core, offline: the pinned run priced against the mirrored session, "
                                         "adjustments, the state file. No network.", no_args_is_help=True)
app.add_typer(asta_app)

# Module-level singletons (B008), shared by the asta commands.
RUN_OPTION = typer.Option(None, "--run", help="Pin this valuation run (default: the newest not superseded).")
ONE_SCENARIO_OPTION = typer.Option(None, "--scenario", help="The run's scenario to price under (default: its first).")
STATE_OPTION = typer.Option(None, "--state", help="A state file to load instead of data/asta-state.json.")
FRESH_OPTION = typer.Option(False, "--fresh", help="Ignore any state file: an empty auction under the run's league settings.")
ME_OPTION = typer.Option(None, "--me", help="My team, by label or id (a state file remembers it).")
MAP_OPTION = typer.Option(None, "--map", help="team=nick -- bind a team to its dossier under kb/league/participants; repeatable.")
SESSION_FILE_ARGUMENT = typer.Argument(..., help="A captured session: one state node per line (JSON lines).")
# The literal is declared here, not imported from commands.asta, so the CLI module stays free of eager imports;
# a test asserts it matches commands.asta.SERVER_URL_DEFAULT.
SERVER_OPTION = typer.Option(
    "http://127.0.0.1:8765", "--server",
    help="The running asta serve to proxy through (adjust falls back to the offline path when nothing is listening).")
SERVE_REPLAY_OPTION = typer.Option(
    None, "--replay", help="Serve a captured session (JSON lines) instead of the live feed -- the rehearsal.")
SERVE_STATE_OPTION = typer.Option(
    None, "--state", help="Serve a state file with no feed -- the post-auction review.")


def _asta_paths():
    from fantaclaude.commands.asta import AstaPaths
    from fantaclaude.paths import (
        adjustments_path,
        asta_state_path,
        db_path,
        kb_dir,
        records_dir,
    )

    return AstaPaths(db=db_path(), adjustments=adjustments_path(), state=asta_state_path(), records=records_dir(),
                     kb=kb_dir())


@contextmanager
def _asta_errors():
    """The asta commands' half of the exit-code contract: a bad flag is 2, a missing or malformed input is 3."""
    import duckdb

    from fantaclaude.analysis.valuation import UnknownScenarioError
    from fantaclaude.commands.asta import UsageError
    from fantaclaude.commands.ingest import NotReady

    try:
        yield
    except NotReady as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    except duckdb.Error as exc:
        # _open_read_only answers for a duckdb.Error *at connect*; this answers
        # for one raised after it, at any query the command makes -- a database
        # at an older schema (no v_valuation_runs), or one built by other code.
        # That is "not ready", the same as no run at all: exit 1 tells a caller
        # "this crashed", and a caller that cannot tell a stale workspace from a
        # bug retries the wrong thing. doctor is where the state is diagnosed.
        typer.echo(f"the database cannot answer this: {exc}\n"
                   f"it may be at an older schema or built by other code -- run `fantaclaude doctor`", err=True)
        raise typer.Exit(code=ExitCode.NOT_READY) from None
    except (UsageError, UnknownScenarioError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=ExitCode.USAGE) from None


def _band(b: dict | None) -> str:
    return "-" if b is None else f"{b['p50']} [{b['p25']}-{b['p75']}]"


def _render_lot(payload: dict) -> str:
    lot = payload.get("lot")
    if lot is None:
        return "lot: none on the block"
    line = f"lot: {lot['name']} ({lot['role_class']}, {lot['team_short']}, t{lot['tier']}) band {_band(lot['band'])}"
    if lot.get("sold_to") is not None:
        line += f" · sold to team {lot['sold_to']}"
    elif lot.get("expected_price") is not None:
        line += f" · expected {lot['expected_price']}"
    pressure = payload.get("lot_pressure")
    if pressure and pressure["bidders"]:
        top = pressure["bidders"][0]
        line += (f" · pressure: est. {pressure['estimate']} ({top['label']} {top['intent']} up to {top['ceiling']}"
                 + (f", {len(pressure['bidders']) - 1} more" if len(pressure["bidders"]) > 1 else "") + ")")
    return line


def _render_board(payload: dict) -> str:
    s, me = payload["settings"], payload["me"]
    lines = [payload["run"], f"source: {payload['source']}",
             (f"session: {s['budget']} credits · goalkeepers {s['goalkeepers'][0]}-{s['goalkeepers'][1]} · outfield "
              f"{s['outfield'][0]}-{s['outfield'][1]} · roster {s['size'][0]}-{s['size'][1]} · {s['team_count']} teams "
              f"({s['source']}) · scenario {payload['scenario']}")]
    lines += [f"SESSION != LEAGUE: {c}" for c in payload["league_conflicts"]]
    classic = "/".join(f"{role}{me['classic'].get(role, 0)}" for role in ("P", "D", "C", "A")) if me.get("classic") else ""
    lines.append(f"me: {me['label']} (team {me['team_id']}) · {me['credits']} credits · {len(me['picks'])} picks "
                 f"(gk {me['goalkeepers']}, mov {me['outfield']}{' · ' + classic if classic else ''}) · still needed: "
                 f"gk {me['missing_goalkeepers']}, mov {me['missing_outfield']} · open slots {me['open_slots']} · "
                 f"market {payload['market_credits']} credits")
    comp = ", ".join(f"{cls} {n}·{payload['credits_by_class'].get(cls, 0)}" for cls, n in payload["composition"].items() if n)
    departed = f" · departed from the target at {', '.join(payload['targets_departed'])}" if payload["targets_departed"] else ""
    lines.append(f"board: inflation {payload['inflation']:.2f} · reserve {payload['reserve']} · budget {payload['budget']} "
                 f"· completion {comp}{departed}")
    # Per class, the ranks my squad covers over the ranks the pricer still has
    # open for it: "Por 3/3" is full, "Dc 2/5" has three to buy, "W 0/0" has
    # no rank left at all -- which is what a band of 0 means there.
    room = payload.get("room_by_class") or {}
    if room:
        occupancy = payload.get("occupancy") or {}
        lines.append("room: " + " · ".join(f"{cls} {occupancy.get(cls, 0)}/{occupancy.get(cls, 0) + n}"
                                          for cls, n in room.items()))
    block = payload.get("block")
    if block:
        lines.append(f"block: {block['classic_role']} · classes {', '.join(block['classes'])}")
    pins = payload.get("pins") or {}
    if pins:
        named = payload["prices"]
        lines.append("re-pinned: " + ", ".join(f"{named[pid]['name']} -> {cls}" for pid, cls in list(pins.items())[:12])
                     + (f" (+{len(pins) - 12} more)" if len(pins) > 12 else ""))
    lines.append(_render_lot(payload))
    for cls, rows in payload["tiers"].items():
        lines.append(f"  {cls}: " + " · ".join(
            f"{r['name']} {_band(r['band'])} t{r['tier']}" + (f" p{r['pressure']['estimate']}" if r.get("pressure") else "")
            for r in rows))
    adj = payload["adjustments"]
    lines.append(f"adjustments: {adj['count']} ({adj['applied']} applied)" + (f" · sha {adj['sha256'][:8]}" if adj["sha256"] else ""))
    lines += [f"note: {n}" for n in payload.get("notes", [])]
    lines += [f"problem: {p}" for p in payload["problems"]]
    return "\n".join(lines)


@asta_app.command("board")
def asta_board_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    state: Path | None = STATE_OPTION,
    fresh: bool = FRESH_OPTION,
    me: str | None = ME_OPTION,
    map_: list[str] | None = MAP_OPTION,
    top: int = typer.Option(5, "--top", help="Players per class on the tier board."),
) -> None:
    """Price the pinned run against the mirrored auction (data/asta-state.json if present, else an empty one): my credits and slots, the completion, the lot on the block, the tier board. Local."""
    from fantaclaude.commands.asta import board_report

    with _asta_errors():
        con = _open_read_only()
        try:
            report = board_report(con, paths=_asta_paths(), run_id=run, scenario=scenario, state_file=state, fresh=fresh,
                                  me=me, maps=tuple(map_ or ()), top=top)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_board)


def _render_explain(payload: dict) -> str:
    p = payload["player"]
    lines = [payload["run"], f"source: {payload['source']}",
             (f"{p['name']} ({p['team_short']}, {'/'.join(p['roles'])} -> {p['role_class']}, t{p['tier']}) · "
              f"value {p['value_p50']:.1f} [{p['value_p25']:.1f}-{p['value_p75']:.1f}] · quotazione {p['quotazione']}")]
    if payload["sold_to"] is not None:
        lines.append(f"sold to team {payload['sold_to']} for {payload['cost']}")
    trace = payload["trace"]
    if trace is None:
        lines.append("not priced: sold, or excluded by an adjustment")
    else:
        lines.append(f"band {_band(trace['band'])} · expected {trace['expected_price']} · rank weight {trace['rank_weight']:.3f} · "
                     f"walk {trace['walk_value']} · buy {trace['buy_value']}")
        lines.append(f"board: inflation {trace['inflation']:.2f} · reserve {trace['reserve']} · budget {trace['budget']} · "
                     f"slot price {trace['slot_price']:.2f} · completion " + ", ".join(
                         f"{cls} {n}" for cls, n in trace["composition"].items() if n))
    if payload["pressure"]:
        pr = payload["pressure"]
        lines.append(f"pressure: est. {pr['estimate']} (expected {pr['expected']}); " + "; ".join(
            f"{b['label']} {b['intent']} up to {b['ceiling']} (credits {b['credits']}, depth {b['depth']}"
            + (", " + ", ".join(b["reasons"]) if b["reasons"] else "") + ")" for b in pr["bidders"]))
    lines += [f"adjustment: {a}" for a in payload["adjustments"]]
    lines += [f"problem: {q}" for q in payload["problems"]]
    return "\n".join(lines)


@asta_app.command("explain")
def asta_explain_cmd(
    player: str = typer.Argument(..., help="A player, the listone's way (\"Martinez L.\") or by id."),
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    state: Path | None = STATE_OPTION,
    fresh: bool = FRESH_OPTION,
) -> None:
    """The trace behind one player's price on the current board -- for the model to read, never to recompute."""
    from fantaclaude.commands.asta import explain_report

    with _asta_errors():
        con = _open_read_only()
        try:
            report = explain_report(con, paths=_asta_paths(), player=player, run_id=run, scenario=scenario,
                                    state_file=state, fresh=fresh)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_explain)


def _render_replay(payload: dict) -> str:
    lines = [payload["run"], f"me: team {payload['mapping']['mine']}"]
    for step in payload["steps"]:
        events = "; ".join(step["events"]) or "(no change)"
        lot = f" · lot {step['lot']['name']} {_band(step['lot']['band'])}" if step["lot"] else ""
        lines.append(f"{step['index']:>3}: {events} · me {step['credits']} credits · {step['picks']} picks{lot}")
    lines.append("final " + _render_board({**payload, "source": "the last snapshot", "notes": []}).split("\n", 1)[1])
    if payload["written"]:
        lines.append(f"state written to {payload['written']}")
    return "\n".join(lines)


@asta_app.command("replay")
def asta_replay_cmd(
    file: Path = SESSION_FILE_ARGUMENT,
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    me: str | None = ME_OPTION,
    map_: list[str] | None = MAP_OPTION,
    write_state: bool = typer.Option(False, "--write-state", help="Write data/asta-state.json from the last snapshot."),
) -> None:
    """Run a captured session through the whole pipeline -- the rehearsal harness -- and print what every snapshot moved."""
    from fantaclaude.commands.asta import replay_report

    paths = _asta_paths()
    with _asta_errors():
        con = _open_read_only()
        try:
            report = replay_report(con, paths=paths, file=file, run_id=run, scenario=scenario, me=me,
                                   maps=tuple(map_ or ()), write_state_to=paths.state if write_state else None)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_replay)


def _render_adjust(payload: dict) -> str:
    before, after = payload["before"], payload["after"]
    lines = [f"appended to {payload['path']} ({payload['count']} entries): {payload['described']}"]
    if payload["player_id"] is not None:
        lines.append(f"his band: {_band(before['band'])} -> {_band(after['band'])}")
    # The class's top players, keyed by player: an adjustment reorders the class, so
    # pairing the two lists by position showed one player's band against another's --
    # and, since only a coincidental match survived, printed almost none of the rows.
    was = {r["player_id"]: r["band"] for r in before["top"]}
    lines.append(f"{after['class']}: " + " · ".join(
        f"{r['name']} " + (f"{_band(was[r['player_id']])} -> " if r["player_id"] in was else "") + _band(r["band"])
        for r in after["top"]))
    comp = ", ".join(f"{cls} {before['composition'].get(cls, 0)}->{n}" for cls, n in after["composition"].items()
                     if n != before["composition"].get(cls, 0))
    if comp:
        lines.append(f"composition moved: {comp}")
    if after["targets_departed"]:
        lines.append(f"departed from the target at {', '.join(after['targets_departed'])}")
    lines += [f"problem: {p}" for p in after["problems"]]
    return "\n".join(lines)


def _render_adjust_live(payload: dict) -> str:
    lines = [(f"applied via the running server at {payload['applied_via']} "
              f"({payload['count']} entries): {payload['described']}")]
    if payload["player_id"] is not None:
        lines.append(f"his band now: {_band(payload['band'])}")
    lines += [f"problem: {p}" for p in payload["problems"]]
    return "\n".join(lines)


@asta_app.command("adjust")
def asta_adjust_cmd(
    type_: str = typer.Option(..., "--type", help="value | exclude | target."),
    reason: str = typer.Option(..., "--reason", help="Why -- the auction record explains itself afterwards."),
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    player: str | None = typer.Option(None, "--player", help="The player, the listone's way (\"Martinez L.\")."),
    player_id: int | None = typer.Option(None, "--player-id", help="Or his listone id."),
    factor: float | None = typer.Option(None, "--factor", help="value: scale his projection by this (0, 2]."),
    class_: str | None = typer.Option(None, "--class", help="target: the role class."),
    count: int | None = typer.Option(None, "--count", help="target: the composition to start from."),
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    state: Path | None = STATE_OPTION,
    fresh: bool = FRESH_OPTION,
    server_: str = SERVER_OPTION,
) -> None:
    """Append a belief to data/adjustments.yml -- a value factor, an exclusion, a target -- and show what it moved on the board. Proxies to a running `asta serve` when one is listening: while the server runs it is the one writer of adjustments.yml, so this never appends behind its back."""
    from fantaclaude.asta.adjustments import AdjustmentsError, adjustment_from_entry
    from fantaclaude.commands.asta import UsageError, adjust, server_adjust

    raw = {k: v for k, v in (("player", player), ("player_id", player_id), ("type", type_), ("factor", factor),
                             ("class", class_), ("count", count), ("reason", reason)) if v is not None}
    with _asta_errors():
        try:
            adjustment = adjustment_from_entry(raw, "asta adjust")
        except AdjustmentsError as exc:
            raise UsageError(str(exc)) from None

        proxied = server_adjust(server_, adjustment)
        if proxied is not None:
            prices = proxied["board"].get("prices", {})
            row = None if proxied.get("player_id") is None else prices.get(str(proxied["player_id"]))
            emit({"applied_via": server_, "described": proxied["described"], "count": proxied["count"],
                  "player_id": proxied.get("player_id"),
                  "band": None if row is None else row["band"],
                  "problems": proxied["board"].get("problems", [])},
                 json_=json_, render=_render_adjust_live)
            return

        con = _open_read_only()
        try:
            report = adjust(con, paths=_asta_paths(), adjustment=adjustment, run_id=run, scenario=scenario,
                            state_file=state, fresh=fresh)
        finally:
            con.close()
    emit(report.to_dict(), json_=json_, render=_render_adjust)


@asta_app.command("close")
def asta_close_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    session: str | None = typer.Option(None, "--session", help="The session code to name the copy by (default: the file's)."),
) -> None:
    """Copy data/asta-state.json to records/asta/ when the auction closes -- the record of what the room paid, until the transfer is verified."""
    from fantaclaude.commands.asta import close_auction

    with _asta_errors():
        path = close_auction(_asta_paths(), session_code=session)
    emit({"records": str(path)}, json_=json_, render=lambda p: f"copied to {p['records']} -- commit records/")


@asta_app.command("refresh")
def asta_refresh_cmd(
    json_: bool = typer.Option(False, "--json", help="Machine-readable output."),
    server_: str = SERVER_OPTION,
) -> None:
    """Tell the running `asta serve` to reread data/adjustments.yml and the dossiers and re-price the board -- the hand-edited-file case (live-event requirement 6). Offline boards recompute on every command, so this needs the server."""
    from fantaclaude.commands.asta import server_refresh

    with _asta_errors():
        payload = server_refresh(server_)
    adj = payload["board"]["adjustments"]
    emit({"applied_via": server_, "adjustments": adj, "problems": payload["problems"]}, json_=json_,
         render=lambda p: f"refreshed via {p['applied_via']}: {p['adjustments']['count']} adjustment(s), "
                          f"{p['adjustments']['applied']} applied"
                          + ("".join(f"\nproblem: {q}" for q in p["problems"])))


@asta_app.command("serve")
def asta_serve_cmd(
    session: str | None = typer.Option(None, "--session", help="FantaAstaLive session code (FA-xxx-xxx); prompted for when no source is given."),
    replay: Path | None = SERVE_REPLAY_OPTION,
    speed: float = typer.Option(1.0, "--speed", help="Replay pace: one snapshot every 2/N seconds."),
    state: Path | None = SERVE_STATE_OPTION,
    run: str | None = RUN_OPTION,
    scenario: str | None = ONE_SCENARIO_OPTION,
    me: str | None = ME_OPTION,
    map_: list[str] | None = MAP_OPTION,
    no_capture: bool = typer.Option(False, "--no-capture", help="Live mode: do not append feed nodes to data/raw/asta_live/."),
) -> None:
    """Serve the live board: mirror the FantaAstaLive session, price every change, and expose the dashboard (/), the API (/api), the WebSocket (/ws) and the fantaclaude-asta MCP (/mcp/) from one process, on 127.0.0.1:8765 and nowhere else. The only network it touches is the Firebase session, read-only."""
    import asyncio

    from fantaclaude.commands.asta import SERVER_URL_DEFAULT
    from fantaclaude.commands.serve import ServeOptions, prepare, run_serve

    if session is None and replay is None and state is None:
        session = typer.prompt("FantaAstaLive session code (FA-xxx-xxx)")
    opts = ServeOptions(session=session, replay=replay, speed=speed, state=state, run_id=run,
                        scenario=scenario, me=me, maps=tuple(map_ or ()), capture=not no_capture)
    paths = _asta_paths()
    with _asta_errors():
        con = _open_read_only()
        try:
            plan = prepare(con, paths, opts)
        finally:
            con.close()
        typer.echo(plan.server.run.describe())
        for note in plan.notes:
            typer.echo(f"note: {note}")
        typer.echo(f"serving {plan.mode} on {SERVER_URL_DEFAULT}  (dashboard /, MCP /mcp/) — Ctrl-C to stop")
        asyncio.run(run_serve(plan, opts, paths))


def main() -> None:
    app()
