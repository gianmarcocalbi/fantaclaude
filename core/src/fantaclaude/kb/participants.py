"""Opponent dossiers: the fixed front-matter the auction's pressure model
loads at startup (spec, "Dossiers are loaded, not read live").

kb/league/participants/<nick>.md is written by `fanta-kb interview`. Beside
the audit's four keys the front-matter carries: nick (as the league shows
it -- the join to the FantaAstaLive team mapping), team (the league team
name, optional until the auction assigns one), budget_style (early |
steady | hoarder), favourite_clubs (listone club names), overpays and
avoids (role classes), max_single_share (the largest share of a budget
ever seen on one player, optional). The prose is what the model reads to
explain a call. No field may carry an email address -- the repository
rule that an address never reaches a tool result applies to the files a
tool would read back.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.kb.audit import FrontMatter, FrontMatterError, parse_front_matter
from fantaclaude.league.settings import EMAIL_PATTERN
from fantaclaude.model.demand import ROLE_CLASSES

BUDGET_STYLES = ("early", "steady", "hoarder")


class ParticipantError(ValueError):
    """A dossier's front-matter is missing or malformed; the message names the file."""


@dataclass(frozen=True)
class Participant:
    path: Path
    nick: str
    team: str | None
    budget_style: str
    favourite_clubs: tuple[str, ...]
    overpays: tuple[str, ...]
    avoids: tuple[str, ...]
    max_single_share: float | None
    front_matter: FrontMatter

    def to_dict(self) -> dict[str, Any]:
        return {"nick": self.nick, "team": self.team, "budget_style": self.budget_style,
                "favourite_clubs": list(self.favourite_clubs), "overpays": list(self.overpays),
                "avoids": list(self.avoids), "max_single_share": self.max_single_share,
                "updated": self.front_matter.updated.isoformat() if self.front_matter.updated else None}


def _names(data: dict[str, Any], key: str, path: Path, *, allowed: tuple[str, ...] | None = None) -> tuple[str, ...]:
    value = data.get(key, [])
    if value is None:
        value = []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ParticipantError(f"{path}: {key} must be a list of names, got {value!r}")
    if allowed is not None:
        bad = [v for v in value if v not in allowed]
        if bad:
            raise ParticipantError(f"{path}: {key} names classes that do not exist: {bad}; choose from {allowed}")
    return tuple(v.strip() for v in value)


def _no_emails(data: dict[str, Any], path: Path) -> None:
    for key, value in data.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            if isinstance(v, str) and EMAIL_PATTERN.search(v):
                raise ParticipantError(f"{path}: {key} carries an email address; dossiers never do")


def load_participant(path: Path) -> Participant:
    try:
        front_matter = parse_front_matter(path.read_text(encoding="utf-8"))
    except (FrontMatterError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ParticipantError(f"{path}: {exc}") from None
    if front_matter is None:
        raise ParticipantError(f"{path}: no front-matter block")
    data: dict[str, Any] = front_matter.raw
    _no_emails(data, path)
    nick = data.get("nick")
    if not isinstance(nick, str) or not nick.strip():
        raise ParticipantError(f"{path}: nick must be the name the league shows")
    team = data.get("team")
    if team is not None and (not isinstance(team, str) or not team.strip()):
        raise ParticipantError(f"{path}: team must be the league team name or absent")
    style = data.get("budget_style")
    if style not in BUDGET_STYLES:
        raise ParticipantError(f"{path}: budget_style must be one of {BUDGET_STYLES}, got {style!r}")
    share = data.get("max_single_share")
    if share is not None and (isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < float(share) <= 1):
        raise ParticipantError(f"{path}: max_single_share is a share of the budget in (0, 1], got {share!r}")
    return Participant(path=path, nick=nick.strip(), team=team.strip() if team else None, budget_style=style,
                       favourite_clubs=_names(data, "favourite_clubs", path),
                       overpays=_names(data, "overpays", path, allowed=ROLE_CLASSES),
                       avoids=_names(data, "avoids", path, allowed=ROLE_CLASSES),
                       max_single_share=None if share is None else float(share), front_matter=front_matter)


def load_participants(kb_dir: Path) -> list[Participant]:
    """Every kb/league/participants/*.md, by nick; two dossiers for one nick raise."""
    by_nick: dict[str, Participant] = {}
    for path in sorted(kb_dir.glob("league/participants/*.md")):
        p = load_participant(path)
        if p.nick in by_nick:
            raise ParticipantError(f"{path}: nick {p.nick!r} already has a dossier at {by_nick[p.nick].path}")
        by_nick[p.nick] = p
    return [by_nick[nick] for nick in sorted(by_nick)]
