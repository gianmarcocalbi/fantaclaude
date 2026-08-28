"""league.yml: what the API cannot express, with provenance on every leaf.

A leaf is a mapping {value, source, verified_on[, note]}; keys flatten with
dots ("auction.mode"). Where a key duplicates something the API reports, the
two must agree -- sync-league fails loud rather than picking a winner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .settings import LeagueSnapshot

LEAF_KEYS = frozenset({"value", "source", "verified_on"})
OPTIONAL_KEYS = frozenset({"note"})


class LeagueYmlError(ValueError):
    """league.yml is malformed or a leaf lacks provenance."""


@dataclass(frozen=True)
class Provenanced:
    key: str
    value: Any
    source: str
    verified_on: date
    note: str | None = None


def load_league_yml(path: Path) -> dict[str, Provenanced]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise LeagueYmlError(f"{path}: the top level must be a mapping")
    entries: dict[str, Provenanced] = {}

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict) and LEAF_KEYS <= set(node):
            extra = set(node) - LEAF_KEYS - OPTIONAL_KEYS
            if extra:
                raise LeagueYmlError(f"{path}: {prefix}: unexpected keys {sorted(extra)}")
            if not isinstance(node["verified_on"], date):
                raise LeagueYmlError(f"{path}: {prefix}: verified_on must be an ISO date")
            if not node["source"]:
                raise LeagueYmlError(f"{path}: {prefix}: source must not be empty")
            entries[prefix] = Provenanced(prefix, node["value"], str(node["source"]),
                                          node["verified_on"], node.get("note"))
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{prefix}.{key}" if prefix else str(key))
        else:
            raise LeagueYmlError(f"{path}: {prefix}: every leaf needs value/source/verified_on")

    walk(data, "")
    return entries


# league.yml key -> the value the API reports for it. `minrl`/`maxrl` are read
# as [goalkeepers, outfield]: the design spec's reading of `sroles: 2`
# (2+21 = msltc, 6+34 = xsltc). This cross-check is what would catch that
# reading being wrong.
COMPARABLE: dict[str, Callable[[LeagueSnapshot], Any]] = {
    "budget": lambda s: s.budget,
    "team_count": lambda s: s.team_count,
    "roster.min_size": lambda s: s.roster_min,
    "roster.max_size": lambda s: s.roster_max,
    "roster.min_goalkeepers": lambda s: (s.payload["rosters"].get("minrl") or [None])[0],
    "roster.max_goalkeepers": lambda s: (s.payload["rosters"].get("maxrl") or [None])[0],
}


@dataclass(frozen=True)
class Conflict:
    key: str
    league_yml: Any
    api: Any


def cross_check(entries: dict[str, Provenanced], snapshot: LeagueSnapshot) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for key in sorted(entries):
        reader = COMPARABLE.get(key)
        if reader is None:
            continue
        api_value = reader(snapshot)
        if api_value is not None and entries[key].value != api_value:
            conflicts.append(Conflict(key, entries[key].value, api_value))
    return conflicts
