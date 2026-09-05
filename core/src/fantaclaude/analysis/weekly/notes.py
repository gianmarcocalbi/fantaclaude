"""The override file: my facts for the week, applied on top of the page and
never inside it (spec, "The override file").

adjustments.yml's shape and machinery, with three kinds of its own and a
giornata on every entry. `p_start` sets the probability of a voto outright
-- "confirmed in the press conference", "out, club statement", the two
facts the page is slowest to carry. `value` scales the expected fantavoto
if he plays -- playing out of position, carrying a knock. `exclude` keeps
him out of the XI and the bench this week. An entry for another giornata is
inert and stays in the file as the record; a later entry for the same
player, kind and giornata wins; every entry carries a reason, so the
week's record explains itself afterwards. Appending is text-first (a
hand-written comment survives) and atomic; a malformed file is a
LineupNotesError the caller reports; a player nobody resolves to is a
problem the layer names, never a silent no-op.

    - player: Kean               # the listone's spelling, or player_id: 2097
      giornata: 4
      type: p_start
      p_start: 0.0               # 0..1
      reason: out, club statement on Thursday
    - player: Bastoni
      giornata: 4
      type: value
      factor: 0.85               # (0, 2]
      reason: carrying a knock
    - player_id: 2764
      giornata: 4
      type: exclude
      reason: not this week
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.atomic import write_atomic
from fantaclaude.ingest.names import AMBIGUOUS, Candidate, Match, match_listone
from fantaclaude.values import is_number

KINDS = ("p_start", "value", "exclude")
FACTOR_RANGE = (0.0, 2.0)             # exclusive of 0
KEYS = frozenset({"player", "player_id", "giornata", "type", "p_start", "factor", "reason"})
HEADER = "# lineup-notes.yml -- my facts for the week (fantaclaude lineup note); one giornata and one reason per entry\n"


class LineupNotesError(ValueError):
    """lineup-notes.yml is malformed; the message names the entry."""


@dataclass(frozen=True)
class LineupNote:
    kind: str
    giornata: int
    reason: str
    player: str | None = None
    player_id: int | None = None
    p_start: float | None = None
    factor: float | None = None

    def to_entry(self) -> dict[str, Any]:
        """The file's own shape, keys in reading order."""
        entry: dict[str, Any] = {}
        if self.player is not None:
            entry["player"] = self.player
        if self.player_id is not None:
            entry["player_id"] = self.player_id
        entry["giornata"] = self.giornata
        entry["type"] = self.kind
        if self.kind == "p_start":
            entry["p_start"] = self.p_start
        if self.kind == "value":
            entry["factor"] = self.factor
        entry["reason"] = self.reason
        return entry

    def describe(self) -> str:
        who = self.player if self.player is not None else f"player_id {self.player_id}"
        if self.kind == "p_start":
            return f"p_start {who} -> {self.p_start:.2f} for giornata {self.giornata} ({self.reason})"
        if self.kind == "value":
            return f"value {who} x{self.factor:g} for giornata {self.giornata} ({self.reason})"
        return f"exclude {who} for giornata {self.giornata} ({self.reason})"


def note_from_entry(raw: Any, where: str) -> LineupNote:
    """One entry of the file (or of `lineup note`'s flags) validated into a LineupNote; the message names `where`."""
    if not isinstance(raw, dict):
        raise LineupNotesError(f"{where}: must be a mapping, got {raw!r}")
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise LineupNotesError(f"{where}: unknown key(s) {unknown}; known: {sorted(KEYS)}")
    kind = raw.get("type")
    if kind not in KINDS:
        raise LineupNotesError(f"{where}: type must be one of {KINDS}, got {kind!r}")
    giornata = raw.get("giornata")
    if isinstance(giornata, bool) or not isinstance(giornata, int) or giornata < 1:
        raise LineupNotesError(f"{where}: giornata must be the round the note is about (a whole number from 1), got {giornata!r}")
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise LineupNotesError(f"{where}: reason must say why -- the week's record explains itself afterwards")
    player, player_id = raw.get("player"), raw.get("player_id")
    if (player is None) == (player_id is None):
        raise LineupNotesError(f"{where}: name the player once -- `player` (the listone's spelling) or `player_id`")
    if player is not None and (not isinstance(player, str) or not player.strip()):
        raise LineupNotesError(f"{where}: player must be the listone's spelling, got {player!r}")
    if player_id is not None and (isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0):
        raise LineupNotesError(f"{where}: player_id must be the listone id, got {player_id!r}")
    p_start, factor = raw.get("p_start"), raw.get("factor")
    if kind == "p_start":
        if not is_number(p_start) or not 0.0 <= float(p_start) <= 1.0:
            raise LineupNotesError(f"{where}: p_start must be a number in [0, 1] -- the probability of a voto, got {p_start!r}")
        p_start = float(p_start)
    elif p_start is not None:
        raise LineupNotesError(f"{where}: p_start belongs to a p_start note")
    if kind == "value":
        if not is_number(factor) or not FACTOR_RANGE[0] < float(factor) <= FACTOR_RANGE[1]:
            raise LineupNotesError(f"{where}: factor must be a number in (0, {FACTOR_RANGE[1]:g}], got {factor!r}")
        factor = float(factor)
    elif factor is not None:
        raise LineupNotesError(f"{where}: factor belongs to a value note")
    return LineupNote(kind, int(giornata), reason.strip(), player=player.strip() if player else None,
                      player_id=player_id, p_start=p_start, factor=factor)


def parse_lineup_notes(text: str, *, where: str = "lineup-notes.yml") -> list[LineupNote]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LineupNotesError(f"{where}: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, list):
        raise LineupNotesError(f"{where}: the top level must be a list of notes")
    return [note_from_entry(raw, f"{where}: entry {i + 1}") for i, raw in enumerate(data)]


def load_lineup_notes(path: Path) -> list[LineupNote]:
    """The file's entries; no file is no notes."""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LineupNotesError(f"{path}: {exc}") from None
    return parse_lineup_notes(text, where=str(path))


def render_note(note: LineupNote) -> str:
    return yaml.safe_dump([note.to_entry()], sort_keys=False, allow_unicode=True, default_flow_style=False)


def append_lineup_note(path: Path, note: LineupNote) -> list[LineupNote]:
    """Reread, append, replace atomically -- text-first, so a hand-written
    comment survives, and re-parsed before it is written, so a file that is
    already malformed is not appended to (the hand edit that broke it is a
    person's to fix). Single-writer today, like adjustments.yml."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    parse_lineup_notes(existing, where=str(path))
    text = HEADER if not existing.strip() else existing if existing.endswith("\n") else existing + "\n"
    text += render_note(note)
    result = parse_lineup_notes(text, where=str(path))
    write_atomic(path, text.encode("utf-8"))
    return result


@dataclass(frozen=True)
class ResolvedNote:
    note: LineupNote
    player_id: int | None
    detail: str | None = None          # why the entry is inert or a problem, when it is


@dataclass(frozen=True)
class NotesLayer:
    giornata: int | None
    entries: tuple[ResolvedNote, ...]
    p_start: dict[int, tuple[float, str]]        # player_id -> (p_start, reason)
    value_factor: dict[int, tuple[float, str]]   # player_id -> (factor, reason)
    excluded: dict[int, str]                     # player_id -> reason
    problems: tuple[str, ...]
    inert: int                                   # entries for another giornata

    def to_dict(self) -> dict[str, Any]:
        return {"giornata": self.giornata, "count": len(self.entries), "inert": self.inert,
                "p_start": {str(k): v[0] for k, v in sorted(self.p_start.items())},
                "value_factor": {str(k): v[0] for k, v in sorted(self.value_factor.items())},
                "excluded": sorted(self.excluded), "problems": list(self.problems)}


EMPTY_NOTES = NotesLayer(None, (), {}, {}, {}, (), 0)


def _why(name: str, match: Match, candidates: list[Candidate]) -> str:
    named = {c.player_id: c.name for c in candidates}
    close = ", ".join(repr(named[i]) for i in match.candidates if i in named)
    if match.status == AMBIGUOUS:
        return f"{name!r} is {len(match.candidates)} players of the listone ({close}); add the initial the listone uses"
    if match.candidates:
        return f"{name!r} is not how the listone spells {close}; use the listone's spelling"
    return f"{name!r} is not in the listone; write him the listone's way -- surname first, then the initial"


def resolve_notes(notes: list[LineupNote], candidates: list[Candidate], *, giornata: int | None) -> NotesLayer:
    """Bind every entry to the listone. An entry for another giornata is
    inert and counted (`giornata=None` binds them all -- the doctor's
    read); an entry that resolves to nobody is a problem, named, never
    dropped. A later entry for the same player, kind and giornata wins."""
    known = {c.player_id for c in candidates}
    entries: list[ResolvedNote] = []
    p_start: dict[int, tuple[float, str]] = {}
    factors: dict[int, tuple[float, str]] = {}
    excluded: dict[int, str] = {}
    problems: list[str] = []
    inert = 0
    for n in notes:
        if giornata is not None and n.giornata != giornata:
            inert += 1
            entries.append(ResolvedNote(n, None, f"for giornata {n.giornata}, not {giornata}"))
            continue
        if n.player_id is not None:
            pid = n.player_id if n.player_id in known else None
            detail = None if pid is not None else f"player_id {n.player_id} is not in the listone"
        else:
            match = match_listone(n.player, candidates)
            pid = match.player_id
            detail = None if pid is not None else _why(n.player, match, candidates)
        if pid is None:
            problems.append(f"{n.describe()}: {detail}; the note is inert")
        elif n.kind == "p_start":
            p_start[pid] = (float(n.p_start), n.reason)
        elif n.kind == "value":
            factors[pid] = (float(n.factor), n.reason)
        else:
            excluded[pid] = n.reason
        entries.append(ResolvedNote(n, pid, detail))
    return NotesLayer(giornata, tuple(entries), p_start, factors, excluded, tuple(problems), inert)
