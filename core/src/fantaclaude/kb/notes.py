"""Player notes: the sparse per-player judgment the projection reads.

kb/serie-a/teams/<slug>/players/<name>.md exists only where prose changes
a decision (spec, "Knowledge base"): a contested shirt, a fitness risk, a
newcomer with no Serie A history. Beside the audit's four keys the
front-matter carries what the projection needs as numbers -- player_id
(the listone id, the only join; the file's location is a mirror of the
club and never the key), depth (starter | contested | cover | out: an
absolute statement about now, which replaces the statistical presenze
rate), availability (0..1, multiplies presenze), prior_fantamedia (a
newcomer's expected fantamedia, used only when he has no history). The
prose below is for the model. This loader is the front-matter's only
reader, so a malformed note fails here with its path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.kb.audit import FrontMatter, FrontMatterError, parse_front_matter
from fantaclaude.kb.profiles import team_slug

DEPTHS = ("starter", "contested", "cover", "out")
PRIOR_RANGE = (3.0, 10.0)


class NoteError(ValueError):
    """A note's front-matter is missing or malformed; the message names the file."""


@dataclass(frozen=True)
class PlayerNote:
    path: Path
    player_id: int
    name: str
    team_short: str
    depth: str | None
    availability: float
    prior_fantamedia: float | None
    front_matter: FrontMatter

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "name": self.name, "team_short": self.team_short, "depth": self.depth,
                "availability": self.availability, "prior_fantamedia": self.prior_fantamedia,
                "updated": self.front_matter.updated.isoformat() if self.front_matter.updated else None}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_note(path: Path) -> PlayerNote:
    try:
        front_matter = parse_front_matter(path.read_text(encoding="utf-8"))
    except (FrontMatterError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise NoteError(f"{path}: {exc}") from None
    if front_matter is None:
        raise NoteError(f"{path}: no front-matter block")
    data: dict[str, Any] = front_matter.raw
    player_id = data.get("player_id")
    if isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0:
        raise NoteError(f"{path}: player_id must be the listone id, got {player_id!r}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise NoteError(f"{path}: name must be the listone's spelling")
    short = data.get("team_short")
    if not isinstance(short, str) or len(short) != 3 or not short.isupper():
        raise NoteError(f"{path}: team_short must be the listone's three-letter code, got {short!r}")
    depth = data.get("depth")
    if depth is not None and depth not in DEPTHS:
        raise NoteError(f"{path}: depth must be one of {DEPTHS}, got {depth!r}")
    availability = data.get("availability", 1.0)
    if not _number(availability) or not 0.0 <= float(availability) <= 1.0:
        raise NoteError(f"{path}: availability must be a number in [0, 1], got {availability!r}")
    prior = data.get("prior_fantamedia")
    if prior is not None and (not _number(prior) or not PRIOR_RANGE[0] <= float(prior) <= PRIOR_RANGE[1]):
        raise NoteError(f"{path}: prior_fantamedia must be a voto-sized number in {PRIOR_RANGE}, got {prior!r}")
    return PlayerNote(path=path, player_id=player_id, name=name.strip(), team_short=short, depth=depth,
                      availability=float(availability), prior_fantamedia=None if prior is None else float(prior),
                      front_matter=front_matter)


def load_player_notes(kb_dir: Path) -> dict[int, PlayerNote]:
    """Every kb/serie-a/teams/*/players/*.md, by player_id; two notes for one id raise."""
    notes: dict[int, PlayerNote] = {}
    for path in sorted(kb_dir.glob("serie-a/teams/*/players/*.md")):
        note = load_note(path)
        if note.player_id in notes:
            raise NoteError(f"{path}: player_id {note.player_id} already has a note at {notes[note.player_id].path}")
        notes[note.player_id] = note
    return notes


def misplaced_notes(notes: dict[int, PlayerNote], team_name_of: dict[int, str]) -> list[tuple[PlayerNote, str]]:
    """Notes whose folder is not the slug of the player's current club --
    with the slug they belong under. A player the listone no longer has is
    not misplaced: there is nowhere better to put him."""
    moved: list[tuple[PlayerNote, str]] = []
    for player_id, note in sorted(notes.items()):
        team = team_name_of.get(player_id)
        if team is None:
            continue
        expected = team_slug(team)
        if note.path.parent.parent.name != expected:
            moved.append((note, expected))
    return moved
