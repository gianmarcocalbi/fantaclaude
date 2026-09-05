"""p_start by precedence, and the checks that never touch it (spec,
"Blending, and the rotation term that must not double-count").

A lineup-notes.yml entry for this giornata sets the number (source: note);
otherwise a squalifica in the current news file forces zero (source:
squalificato); otherwise the published number stands (source: published).
Every other source is a check: an infortunato the page still prices, a KB
note whose depth or availability disagrees with the page, a European tie
within the window at a rotating club -- each a named warning, none a term,
because the site's compilers already know what those sources know and
stacking fades a player twice. A diffida is carried into the trace and
named on the bench and contingency lines, because it prices next week.
Checks are silent once a note or a squalifica set the number: the
disagreement has been adjudicated.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.config import WeeklyConfig
from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.analysis.weekly.notes import (
    EMPTY_NOTES,
    LineupNotesError,
    NotesLayer,
    load_lineup_notes,
    resolve_notes,
)
from fantaclaude.ingest.names import load_candidates
from fantaclaude.kb.notes import NoteError, PlayerNote, load_player_notes
from fantaclaude.kb.profiles import ProfileError, load_profiles

SOURCE_PUBLISHED = "published"
SOURCE_NOTE = "note"
SOURCE_SQUALIFICATO = "squalificato"


@dataclass(frozen=True)
class BlendLayer:
    giornata: int
    notes: NotesLayer = EMPTY_NOTES
    squalificati: dict[int, str] = field(default_factory=dict)          # player_id -> the page's words
    infortunati: dict[int, str] = field(default_factory=dict)
    diffidati: dict[int, str] = field(default_factory=dict)
    kb_notes: dict[int, PlayerNote] = field(default_factory=dict)
    rotation: dict[str, float] = field(default_factory=dict)            # team_short -> rotation_factor, below 1.0 only
    european: dict[str, tuple[datetime, ...]] = field(default_factory=dict)   # team_short -> tie kickoffs, naive UTC
    giornate_remaining: int | None = None                               # of the run, for the season rate
    news_fetched: dict[str, str] = field(default_factory=dict)          # page -> fetched_at, for the report
    unmatched_news: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"giornata": self.giornata, "notes": self.notes.to_dict(), "squalificati": len(self.squalificati),
                "infortunati": len(self.infortunati), "diffidati": len(self.diffidati), "kb_notes": len(self.kb_notes),
                "rotating_clubs": sorted(self.rotation), "news_fetched": dict(self.news_fetched),
                "unmatched_news": self.unmatched_news, "giornate_remaining": self.giornate_remaining}


EMPTY_BLEND = BlendLayer(0)


def load_layer(con: duckdb.DuckDBPyConnection, *, season_id: int, giornata: int, run_id: str,
               notes_path: Path | None, kb_dir: Path | None, cfg: WeeklyConfig) -> tuple[BlendLayer, list[str]]:
    """Everything the blend reads besides the page, and the notices about
    what could not be read. A malformed notes file refuses the forecast (it
    would corrupt this week's answer); a malformed KB document skips its
    check with a notice (it only makes the answer poorer)."""
    warnings: list[str] = []
    notes = EMPTY_NOTES
    if notes_path is not None:
        try:
            notes = resolve_notes(load_lineup_notes(notes_path), load_candidates(con), giornata=giornata)
        except LineupNotesError as exc:
            raise ForecastError(f"{exc} -- fix the file; a forecast under a malformed override file is not a forecast") from None
        warnings += list(notes.problems)
    listed = con.execute("SELECT kind, player_id, coalesce(detail, '') FROM v_unavailable_current "
                         "WHERE season_id = ? AND giornata = ? ORDER BY file_id, position", [season_id, giornata]).fetchall()
    by_kind: dict[str, dict[int, str]] = defaultdict(dict)
    for kind, pid, detail in listed:
        if pid is not None:
            by_kind[str(kind)][int(pid)] = str(detail)
    unmatched = sum(1 for _, pid, _ in listed if pid is None)
    fetched = {str(kind): stamp.isoformat(sep=" ", timespec="minutes") for kind, stamp in con.execute(
        "SELECT kind, fetched_at FROM v_news_files_current WHERE season_id = ? AND giornata = ?", [season_id, giornata]).fetchall()}
    if "squalificati" not in fetched:
        warnings.append(f"no squalificati page for giornata {giornata} -- run `fantaclaude ingest news --page squalificati`; "
                        f"no squalifica can force a zero")
    if "infortunati" not in fetched:
        warnings.append(f"no infortunati page for giornata {giornata} -- run `fantaclaude ingest news --page infortunati`; "
                        f"infortunati checks are skipped")
    if unmatched:
        warnings.append(f"{unmatched} news entr{'y' if unmatched == 1 else 'ies'} for giornata {giornata} matched nobody in the "
                        f"listone -- `fantaclaude query --sql \"SELECT * FROM v_unavailable_current WHERE player_id IS NULL\"`")
    kb_notes: dict[int, PlayerNote] = {}
    rotation: dict[str, float] = {}
    if kb_dir is not None:
        try:
            kb_notes = load_player_notes(kb_dir)
        except NoteError as exc:
            warnings.append(f"KB notes not read, their check skipped: {exc}")
        try:
            rotation = {p.team_short: p.rotation_factor for p in load_profiles(kb_dir) if p.rotation_factor < 1.0}
        except ProfileError as exc:
            warnings.append(f"KB profiles not read, the European check skipped: {exc}")
    european: dict[str, list[datetime]] = defaultdict(list)
    for short, kickoff in con.execute("SELECT team_short, kickoff FROM v_european_ties WHERE season_id = ? AND kickoff IS NOT NULL",
                                      [season_id]).fetchall():
        european[str(short)].append(kickoff)
    summary = con.execute("SELECT summary FROM valuation_runs WHERE run_id = ?", [run_id]).fetchone()
    remaining = None
    if summary is not None:
        parsed = summary[0] if isinstance(summary[0], dict) else json.loads(summary[0])
        remaining = parsed.get("giornate_remaining")
    return BlendLayer(giornata, notes, dict(by_kind.get("squalificato", {})), dict(by_kind.get("infortunato", {})),
                      dict(by_kind.get("diffidato", {})), kb_notes, rotation,
                      {k: tuple(sorted(v)) for k, v in european.items()},
                      None if remaining is None else int(remaining), fetched, unmatched), warnings


@dataclass(frozen=True)
class Blended:
    p_start: float
    source: str
    value_factor: float
    excluded: bool
    trace: dict[str, Any]
    warnings: tuple[str, ...]


def blend(*, player_id: int, name: str, team_short: str | None, published: int, exp_presenze: float | None,
          kickoff: datetime | None, layer: BlendLayer, cfg: WeeklyConfig) -> Blended:
    label = f"{name} ({team_short or '?'})"
    warnings: list[str] = []
    trace: dict[str, Any] = {"published": published, "source": SOURCE_PUBLISHED, "note": None, "squalificato": None,
                             "infortunato": None, "diffidato": None, "value_factor": 1.0, "checks": []}
    p_start, source = published / 100.0, SOURCE_PUBLISHED
    note = layer.notes.p_start.get(player_id)
    if note is not None:
        p_start, source = note[0], SOURCE_NOTE
        trace["note"] = {"type": "p_start", "p_start": note[0], "reason": note[1]}
    elif player_id in layer.squalificati:
        p_start, source = 0.0, SOURCE_SQUALIFICATO
    if player_id in layer.squalificati:
        trace["squalificato"] = layer.squalificati[player_id]
    trace["source"] = source
    factor = layer.notes.value_factor.get(player_id)
    if factor is not None:
        trace["value_factor"], trace["value_note"] = factor
    excluded = player_id in layer.notes.excluded
    if excluded:
        trace["excluded"] = layer.notes.excluded[player_id]
    # From here on the number is never touched: everything below is a check.
    if player_id in layer.infortunati:
        detail = layer.infortunati[player_id]
        trace["infortunato"] = detail
        if source == SOURCE_PUBLISHED and published >= cfg.injured_page_threshold:
            trace["checks"].append("infortunato")
            warnings.append(f"disagreement: {label} is listed infortunato ({detail[:70]}) but the page has him at {published}%")
    if player_id in layer.diffidati:
        trace["diffidato"] = layer.diffidati[player_id]
    kb = layer.kb_notes.get(player_id)
    if kb is not None and source == SOURCE_PUBLISHED:
        if kb.depth == "out" and published >= cfg.kb_depth_out_threshold:
            trace["checks"].append("kb_depth_out")
            warnings.append(f"disagreement: {label} has depth 'out' in the KB note ({kb.path.name}) but the page has him at {published}%")
        elif published / 100.0 - kb.availability >= cfg.kb_availability_gap:
            trace["checks"].append("kb_availability")
            warnings.append(f"disagreement: {label} has availability {kb.availability:.2f} in the KB note ({kb.path.name}) "
                            f"but the page has him at {published}%")
    if (team_short in layer.rotation and kickoff is not None and source == SOURCE_PUBLISHED
            and published >= cfg.european_min_published and exp_presenze is not None and layer.giornate_remaining):
        window = timedelta(days=cfg.european_window_days)
        ties = [t for t in layer.european.get(team_short, ()) if abs(t - kickoff) <= window]
        if ties:
            rate = min(1.0, exp_presenze / layer.giornate_remaining)
            model_p = rate * layer.rotation[team_short]
            trace["european"] = {"tie": ties[0].isoformat(sep=" ", timespec="minutes"), "rate": round(rate, 3),
                                 "rotation_factor": layer.rotation[team_short], "model_p": round(model_p, 3)}
            if published / 100.0 - model_p >= cfg.european_gap:
                trace["checks"].append("european")
                warnings.append(f"disagreement: {label} at {published}% with a European tie on {ties[0]:%a %d %b}; the season rate "
                                f"under rotation {layer.rotation[team_short]:.2f} expects {model_p:.0%} -- adjudicate, never fade twice")
    return Blended(p_start, source, factor[0] if factor is not None else 1.0, excluded, trace, tuple(warnings))
