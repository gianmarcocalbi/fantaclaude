"""Team profiles: the structured front-matter Phase 1 reads.

kb/serie-a/teams/<slug>/profile.md carries, beside the audit's four keys,
what the projection needs as numbers and labels -- team, team_short,
coach, module, europe, rotation_factor -- and the set-piece takers as a
small mapping. The prose below the front-matter is for the model; the
front-matter is for the code, and this loader is its only reader, so a
malformed profile fails here with its path rather than as a wrong
projection in September.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.ingest.names import normalise
from fantaclaude.kb.audit import FrontMatter, FrontMatterError, parse_front_matter
from fantaclaude.values import is_number

PROFILE_KEYS = ("team", "team_short", "coach", "module", "europe", "rotation_factor")
EUROPE = ("none", "UCL", "UEL", "UECL")
ROTATION_RANGE = (0.5, 1.0)


class ProfileError(ValueError):
    """A profile's front-matter is missing or malformed; the message names the file."""


@dataclass(frozen=True)
class TeamProfile:
    path: Path
    team: str
    team_short: str
    coach: str
    module: str
    europe: str
    rotation_factor: float
    takers: dict[str, str]
    front_matter: FrontMatter


def team_slug(name: str) -> str:
    """"Hellas Verona" -> "hellas-verona": the folder a club's notes live in."""
    return "-".join(normalise(name))


def load_profile(path: Path) -> TeamProfile:
    try:
        front_matter = parse_front_matter(path.read_text(encoding="utf-8"))
    except (FrontMatterError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ProfileError(f"{path}: {exc}") from None
    if front_matter is None:
        raise ProfileError(f"{path}: no front-matter block")
    data: dict[str, Any] = front_matter.raw
    missing = [key for key in PROFILE_KEYS if data.get(key) in (None, "")]
    if missing:
        raise ProfileError(f"{path}: missing {missing}")
    for key in ("team", "coach", "module"):
        if not isinstance(data[key], str):
            raise ProfileError(f"{path}: {key} must be text")
    short = data["team_short"]
    if not isinstance(short, str) or len(short) != 3 or not short.isupper():
        raise ProfileError(f"{path}: team_short must be the listone's three-letter code, got {short!r}")
    if data["europe"] not in EUROPE:
        raise ProfileError(f"{path}: europe must be one of {EUROPE}, got {data['europe']!r}")
    rotation = data["rotation_factor"]
    if not is_number(rotation) or not ROTATION_RANGE[0] <= float(rotation) <= ROTATION_RANGE[1]:
        raise ProfileError(f"{path}: rotation_factor must be a number in {ROTATION_RANGE}, got {rotation!r}")
    takers = data.get("takers") or {}
    if not isinstance(takers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in takers.items()):
        raise ProfileError(f"{path}: takers must be a mapping of role -> player")
    expected = team_slug(data["team"])
    if path.parent.name != expected:
        raise ProfileError(f"{path}: folder {path.parent.name!r} is not the team's slug {expected!r}")
    return TeamProfile(path=path, team=data["team"], team_short=short, coach=data["coach"], module=str(data["module"]),
                       europe=data["europe"], rotation_factor=float(rotation), takers=dict(takers),
                       front_matter=front_matter)


def load_profiles(kb_dir: Path) -> list[TeamProfile]:
    """Every kb/serie-a/teams/*/profile.md, by team name; the first bad one raises."""
    profiles = [load_profile(path) for path in sorted(kb_dir.glob("serie-a/teams/*/profile.md"))]
    return sorted(profiles, key=lambda p: p.team)
