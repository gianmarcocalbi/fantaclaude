"""The Mantra D-Factor: the defence modifier, as data plus a pure function.

Mechanism (fantacalcio.it, "Regolamento sistema Mantra", read 2026-08-29):
the five defensive men of a lineup are the five best voti among the
players with a role in Dc, B, Dd, Ds, E, M, provided at least three of the
five are true defenders (Dc, B, Dd, Ds); a "5+1" variant adds the
goalkeeper; the average of those voti maps to points for the whole team.
The thresholds are NOT published -- the regolamento says the platform
"proposes the most common version" and lets a league customise the output
-- so they are league data, read off the league's own settings page, kept
in d_factor.yml with a source and a date. The file ships empty; while the
D-Factor is active and the table is empty, `rank` refuses.

The best five under the "at least three true defenders" rule are the best
three true defenders plus the best two of the remaining eligible players:
for a sum with one cardinality constraint the greedy choice is the optimum.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .roles import Role

D_FACTOR_YML = Path(__file__).with_name("d_factor.yml")
# Coincides today with roles.DEFENSIVE, but the two encode different regolamento
# rules -- D-Factor eligibility here, the module's defensive half there -- kept
# separate on purpose, and expected to be changed independently.
D_FACTOR_ROLES: frozenset[Role] = frozenset({Role.Dc, Role.B, Role.Dd, Role.Ds, Role.E, Role.M})
TRUE_DEFENDERS: frozenset[Role] = frozenset({Role.Dc, Role.B, Role.Dd, Role.Ds})
COUNTED = 5
MIN_TRUE_DEFENDERS = 3


class DFactorTableError(ValueError):
    """d_factor.yml does not describe a table this module can apply."""


@dataclass(frozen=True)
class Band:
    floor: float           # applies when the average is >= floor
    points: float


@dataclass(frozen=True)
class DFactorTable:
    bands: tuple[Band, ...]          # descending by floor
    with_goalkeeper: bool
    source: str | None
    verified_on: date | None

    @property
    def is_empty(self) -> bool:
        return not self.bands

    def points(self, average: float) -> float:
        for band in self.bands:
            if average >= band.floor:
                return band.points
        return 0.0

    def slope(self, average: float) -> float:
        """Points per unit of average voto around `average`: the rise to the
        next band up, over the distance to it -- the gradient the projection
        uses for a per-player uplift, since a step read at one point would
        say most defenders are worth nothing to the modifier."""
        above = [b for b in self.bands if b.floor > average]
        if not above:
            return 0.0
        nxt = min(above, key=lambda b: b.floor)
        floor_here = max((b.floor for b in self.bands if b.floor <= average), default=average)
        span = nxt.floor - floor_here
        return (nxt.points - self.points(average)) / span if span > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"bands": [{"min": b.floor, "points": b.points} for b in self.bands],
                "with_goalkeeper": self.with_goalkeeper, "source": self.source,
                "verified_on": self.verified_on.isoformat() if self.verified_on else None}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_d_factor(path: Path = D_FACTOR_YML) -> DFactorTable:
    # This is the one file in the system a human transcribes by hand off a web
    # page, so a YAML *syntax* error here is the expected mistake, not an
    # exotic one -- and yaml.parser.ParserError is neither DFactorTableError
    # nor even a ValueError. Unwrapped it escaped both callers: `rank` died
    # with a traceback where the contract says exit 3, and `doctor`, the
    # command meant to name what is wrong, crashed instead of failing its
    # scoring check. Caught here, the way load_pricing_config catches its own.
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DFactorTableError(f"{path}: {exc}") from None
    if not isinstance(data, dict):
        raise DFactorTableError(f"{path}: the top level must be a mapping")
    raw_bands = data.get("bands")
    if raw_bands is None:
        raw_bands = []
    if not isinstance(raw_bands, list):
        raise DFactorTableError(f"{path}: bands must be a list")
    bands: list[Band] = []
    for entry in raw_bands:
        if not isinstance(entry, dict) or not _number(entry.get("min")) or not _number(entry.get("points")):
            raise DFactorTableError(f"{path}: every band is {{min: <average>, points: <points>}}, got {entry!r}")
        bands.append(Band(float(entry["min"]), float(entry["points"])))
    bands.sort(key=lambda b: -b.floor)
    floors = [b.floor for b in bands]
    if len(set(floors)) != len(floors):
        raise DFactorTableError(f"{path}: two bands share the same min")
    verified_on = data.get("verified_on")
    if isinstance(verified_on, datetime):
        verified_on = verified_on.date()
    if verified_on is not None and not isinstance(verified_on, date):
        raise DFactorTableError(f"{path}: verified_on must be an ISO date or null")
    source = data.get("source")
    if source is not None and not isinstance(source, str):
        raise DFactorTableError(f"{path}: source must be text or null")
    if bands and (verified_on is None or not source):
        raise DFactorTableError(f"{path}: a filled table needs source and verified_on")
    with_goalkeeper = data.get("with_goalkeeper", False)
    if not isinstance(with_goalkeeper, bool):
        raise DFactorTableError(f"{path}: with_goalkeeper must be true or false")
    return DFactorTable(tuple(bands), with_goalkeeper, source, verified_on)


def defensive_average(players: Sequence[tuple[frozenset[Role], float]], *, goalkeeper: float | None = None,
                      with_goalkeeper: bool = False) -> float | None:
    """The average the D-Factor is computed on, or None when the lineup does
    not qualify (fewer than five eligible players, fewer than three true
    defenders among them, or a 5+1 table without a goalkeeper vote)."""
    eligible = sorted(((i, roles, voto) for i, (roles, voto) in enumerate(players) if roles & D_FACTOR_ROLES),
                      key=lambda item: -item[2])
    if len(eligible) < COUNTED:
        return None
    defenders = [item for item in eligible if item[1] & TRUE_DEFENDERS]
    if len(defenders) < MIN_TRUE_DEFENDERS:
        return None
    chosen = defenders[:MIN_TRUE_DEFENDERS]
    taken = {item[0] for item in chosen}
    chosen += [item for item in eligible if item[0] not in taken][:COUNTED - MIN_TRUE_DEFENDERS]
    votes = [item[2] for item in chosen]
    if with_goalkeeper:
        if goalkeeper is None:
            return None
        votes.append(goalkeeper)
    return sum(votes) / len(votes)


def d_factor_points(players: Sequence[tuple[frozenset[Role], float]], table: DFactorTable, *,
                    goalkeeper: float | None = None) -> float:
    if table.is_empty:
        return 0.0
    average = defensive_average(players, goalkeeper=goalkeeper, with_goalkeeper=table.with_goalkeeper)
    return 0.0 if average is None else table.points(average)
