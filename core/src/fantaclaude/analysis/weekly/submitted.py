"""lineup_submitted: the XI actually fielded (spec, "Closing the loop").

Read back from the platform, never written to it; the hand path first.
`fantaclaude lineup record` defaults to the newest run before the lock, takes
`--swap Out=In` for the deviations and `--module`, or `--xi` and `--bench` in
full, and writes source `hand`; `ingest lineup` (Task 13) writes source
`platform` once the GET is mapped. A submission is checked the way the
platform would check it -- a permitted module, eleven distinct roster
players, every one of them a natural or adapted fit somewhere in it -- and
refused otherwise, because a record of an XI nobody could field is not a
record. Appended, never edited; the newest per giornata is current.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.exports import write_parquet
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.xi import RosterPlayer
from fantaclaude.ingest.names import AMBIGUOUS, Candidate, match_listone
from fantaclaude.model.modules import Fit, Module, assign
from fantaclaude.timeutil import to_db

SOURCES = ("hand", "platform")


class SubmissionError(ValueError):
    """The XI to record is not one the platform would accept, or names nobody on my roster."""


@dataclass(frozen=True)
class RunXi:
    lineup_run_id: int
    module: str
    xi: list[dict[str, Any]]
    bench: list[dict[str, Any]]
    my_team: int | None
    late: bool


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def load_run_xi(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int,
                lineup_run_id: int | None) -> RunXi:
    """The run whose XI was fielded: the one asked for, else the newest
    non-late run of the giornata that named one."""
    if lineup_run_id is None:
        row = con.execute(
            "SELECT lineup_run_id, module, xi, bench, my_team, late FROM lineup_runs "
            "WHERE season_id = ? AND giornata = ? AND NOT late AND xi IS NOT NULL "
            "ORDER BY lineup_run_id DESC LIMIT 1", [season_id, giornata]).fetchone()
        if row is None:
            raise ForecastError(f"no lineup run with an XI for giornata {giornata} before the lock -- pass --lineup-run <id>, "
                                f"or --xi and --bench in full")
    else:
        row = con.execute("SELECT lineup_run_id, module, xi, bench, my_team, late FROM lineup_runs WHERE lineup_run_id = ?",
                          [lineup_run_id]).fetchone()
        if row is None:
            raise ForecastError(f"lineup run {lineup_run_id} is not in lineup_runs")
        if row[2] is None:
            raise ForecastError(f"lineup run {lineup_run_id} named no XI")
    bench = _json(row[3]) or {}
    return RunXi(int(row[0]), str(row[1]), list(_json(row[2])), list(bench.get("order", [])), row[4], bool(row[5]))


@dataclass(frozen=True)
class Submission:
    module: str
    xi: list[dict[str, Any]]           # [{slot, player_id, name}] in the module's slot order
    bench: list[dict[str, Any]]        # [{player_id, name}] in bench order
    lineup_run_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "xi": list(self.xi), "bench": list(self.bench), "lineup_run_id": self.lineup_run_id}


def _resolve(name: str, roster: list[RosterPlayer]) -> RosterPlayer:
    """A roster player by the listone's spelling or by id; refused, never guessed."""
    by_id = {p.player_id: p for p in roster}
    if name.strip().isdigit():
        pid = int(name.strip())
        if pid not in by_id:
            raise SubmissionError(f"player_id {pid} is not on my roster")
        return by_id[pid]
    match = match_listone(name, [Candidate(p.player_id, p.name, "", "") for p in roster])
    if match.player_id is not None:
        return by_id[match.player_id]
    if match.status == AMBIGUOUS:
        close = ", ".join(repr(by_id[i].name) for i in match.candidates if i in by_id)
        raise SubmissionError(f"{name!r} is {len(match.candidates)} players of my roster ({close}); add the initial the listone uses")
    raise SubmissionError(f"{name!r} is not on my roster; write him the listone's way, or by id")


def build_submission(*, roster: list[RosterPlayer], run: RunXi | None, modules: dict[str, Module], allowed: Sequence[str],
                     module: str | None = None, swaps: Sequence[tuple[str, str]] = (),
                     xi_names: Sequence[str] | None = None, bench_names: Sequence[str] | None = None) -> Submission:
    """The submission the operator named, checked as the platform would.

    A `--swap` against the run's own, unchanged module replaces the outgoing
    player in his own exact slot and nowhere else -- re-solving the whole
    eleven from scratch would let a symmetry between two identically-labelled
    slots (two "Dc" slots, say) silently swap two players nobody touched: a
    legal XI, but not the one that stood. That narrowing is sound because
    `Slot.fit` is a pure per-slot predicate (no slot's fit depends on who is
    fielded in any other slot), so whole-XI legality decomposes exactly into
    "does every slot's occupant still fit it" plus "are the eleven distinct
    and disjoint from the bench" -- both checked below, the former freshly
    against whatever `modules` is loaded now rather than trusted from when
    `choose_xi`/`assign_weighted` originally validated the run's `xi`, in
    case modules.yml changed underneath a run written earlier. An explicit
    `--module` that differs from the run's own gives up that shortcut and
    re-solves fresh under it, since the run's per-slot layout means nothing
    under a different module. An outgoing player always lands on the
    recorded bench -- appended when he was not among the run's own
    (size-truncated) bench candidates -- so a swap never makes him vanish
    from the record.
    """
    by_id = {p.player_id: p for p in roster}
    if xi_names is not None:
        if swaps:
            raise SubmissionError("--swap is ignored with --xi: --xi already states the full eleven, so a --swap beside "
                                  "it can only be a mistake -- fold the change into --xi directly")
        if module is None:
            raise SubmissionError("--xi needs --module: the module fielded is part of the record")
        xi_ids = [_resolve(n, roster).player_id for n in xi_names]
        bench_ids = [_resolve(n, roster).player_id for n in (bench_names or [])]
        run_id = None if run is None else run.lineup_run_id
        preserve_slots = False
    else:
        if run is None:
            raise SubmissionError("no lineup run to record from -- pass --xi and --bench in full")
        module = module or run.module
        xi_ids = [int(s["player_id"]) for s in run.xi]
        bench_ids = [int(b["player_id"]) for b in run.bench]
        run_id = run.lineup_run_id
        preserve_slots = module == run.module     # unchanged module: the run's own placement still holds
        # The roster snapshot may have moved under this stored run (`ingest
        # rosters` is the one reason it runs at all): a player run.xi/run.bench
        # still names may no longer be in `by_id`. Caught here, before the
        # slot loop below ever indexes by_id with a stale id -- otherwise
        # this is an unguarded KeyError, not a SubmissionError the CLI maps
        # to an exit code (review finding, Important 2).
        missing = sorted((set(xi_ids) | set(bench_ids)) - set(by_id))
        if missing:
            raise SubmissionError(f"run {run.lineup_run_id}'s XI/bench names player_id(s) {missing} no longer on my "
                                  f"roster -- the roster moved since the run; pass --xi and --bench in full")
    if module not in allowed or module not in modules:
        raise SubmissionError(f"module {module!r} is not permitted (league_settings.modules: {list(allowed)})")
    chosen = modules[str(module)]
    if xi_names is None:
        for out_name, in_name in swaps:
            out_p, in_p = _resolve(out_name, roster), _resolve(in_name, roster)
            if out_p.player_id not in xi_ids:
                raise SubmissionError(f"{out_p.name} is not in run {run.lineup_run_id}'s XI")
            if in_p.player_id in xi_ids:
                raise SubmissionError(f"{in_p.name} is already in the XI")
            xi_ids[xi_ids.index(out_p.player_id)] = in_p.player_id
            if in_p.player_id in bench_ids:
                bench_ids = [out_p.player_id if b == in_p.player_id else b for b in bench_ids]
            else:
                bench_ids = [*bench_ids, out_p.player_id]         # not among the recommended bench: append, never drop him
        if preserve_slots:
            # Every slot, touched by a swap or not: `RunXi.xi` was legal when
            # written, but only this fresh check -- not that history -- is
            # what stands between an operator and a slot modules.yml no
            # longer allows.
            for slot_index, slot in enumerate(chosen.slots):
                occupant = by_id[xi_ids[slot_index]]
                if slot.fit(occupant.roles) not in (Fit.NATURAL, Fit.ADAPTED):
                    raise SubmissionError(f"{occupant.name} cannot field {slot.label} legally (natural or adapted fits "
                                          f"only) -- the platform would refuse it too")
    if len(xi_ids) != len(chosen.slots) or len(set(xi_ids)) != len(chosen.slots):
        raise SubmissionError(f"an XI is {len(chosen.slots)} distinct players, got {len(xi_ids)}")
    both = sorted(set(xi_ids) & set(bench_ids))
    if both:
        raise SubmissionError(f"{', '.join(by_id[i].name for i in both)}: both in the XI and on the bench")
    if preserve_slots:
        xi = [{"slot": chosen.slots[k].label, "player_id": xi_ids[k], "name": by_id[xi_ids[k]].name}
              for k in range(len(chosen.slots))]
    else:
        legal = assign(chosen, [by_id[i].roles for i in xi_ids], allow_adapted=True)
        if legal is None:
            raise SubmissionError(f"those {len(chosen.slots)} cannot field {chosen.label} legally (natural or adapted fits only) -- "
                                  f"the platform would refuse it too")
        xi = [{"slot": chosen.slots[k].label, "player_id": xi_ids[i], "name": by_id[xi_ids[i]].name} for k, i in enumerate(legal)]
    bench = [{"player_id": b, "name": by_id[b].name} for b in bench_ids]
    return Submission(str(module), xi, bench, run_id)


def record_submitted(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int, submission: Submission,
                     my_team: int | None, source: str, now: datetime) -> int:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    return int(con.execute(
        "INSERT INTO lineup_submitted (season_id, giornata, lineup_run_id, my_team, module, xi, bench, source, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?) RETURNING submitted_id",
        [season_id, giornata, submission.lineup_run_id, my_team, submission.module,
         json.dumps(submission.xi, ensure_ascii=False), json.dumps(submission.bench, ensure_ascii=False), source,
         to_db(now)]).fetchone()[0])


def export_submitted_record(con: duckdb.DuckDBPyConnection, submitted_id: int, records_dir: Path) -> list[Path]:
    """records/lineup_submitted/<season>-<giornata>-<recorded_at>-<submitted_id>.parquet, once."""
    season, giornata, recorded = con.execute(
        "SELECT season_id, giornata, recorded_at FROM lineup_submitted WHERE submitted_id = ?", [submitted_id]).fetchone()
    path = records_dir / "lineup_submitted" / f"{season}-{giornata:02d}-{recorded:%Y%m%dT%H%M%SZ}-{submitted_id}.parquet"
    return [path] if write_parquet(con, f"SELECT * FROM lineup_submitted WHERE submitted_id = {int(submitted_id)}", path) else []
