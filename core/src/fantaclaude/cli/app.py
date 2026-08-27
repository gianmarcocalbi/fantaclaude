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
    from fantaclaude.commands.sync_league import sync_league
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.league.league_yml import load_league_yml
    from fantaclaude.paths import league_yml_path

    entries = load_league_yml(league_yml_path()) if league_yml_path().is_file() else None
    con = connect()
    try:
        apply_schema(con)
        report = run_with_api(lambda api: sync_league(api, con, entries, league=league))
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
    from fantaclaude.commands.ingest import ingest_all, ingest_listone
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema
    from fantaclaude.ingest.raw import RawStore
    from fantaclaude.paths import raw_dir

    store = RawStore(raw_dir())
    con = connect()
    try:
        apply_schema(con)
        if names == ["all"]:
            results = run_with_api(lambda api: ingest_all(api, con, store, league=league))
        else:
            results = {"listone": run_with_api(lambda api: ingest_listone(api, con, store, league=league))}
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
    """Refresh every source (only the listone in Phase 0a)."""
    _run_ingest(["all"], json_, league)


def main() -> None:
    app()
