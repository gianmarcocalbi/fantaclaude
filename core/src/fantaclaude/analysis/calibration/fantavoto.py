"""The fantavoto bias, the spread check and the surprises (spec, "Calibration:
what 3c ships").

Among predictions that got a voto, actual fantavoto minus `fv_if_plays`, per
classic role and overall, per `model_hash` and `weekly_hash` -- a bias is a
property of a model, never of the season. Where `fv_sd` is set (from 3b),
the share of errors inside one and two spreads, against 68% and 95%. Nothing
here corrects anything: a bias that holds up is written into the model by
hand, where it feeds `model_hash`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import fmean, stdev
from typing import Any

from fantaclaude.analysis.calibration.actuals import Scored

ROLE_ORDER = ("P", "D", "C", "A")
CONFIDENT, LONG_SHOT = 80, 20            # published p_start, the page's own scale
LIST_LIMIT, MY_MISSES = 10, 5


@dataclass(frozen=True)
class Bias:
    group: str
    n: int
    mean_error: float
    se: float | None                    # None with a single row
    mae: float


@dataclass(frozen=True)
class ModelBias:
    model_hash: str
    weekly_hash: str | None
    groups: list[Bias]
    spread_n: int
    within_1sd: float | None
    within_2sd: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"model_hash": self.model_hash, "weekly_hash": self.weekly_hash,
                "groups": [asdict(g) for g in self.groups], "spread_n": self.spread_n,
                "within_1sd": self.within_1sd, "within_2sd": self.within_2sd}


@dataclass(frozen=True)
class Surprise:
    giornata: int
    player_id: int
    name: str
    club: str | None
    p_start_published: int | None
    fv_if_plays: float
    fantavoto: float | None
    error: float | None


def _bias(group: str, errors: list[float]) -> Bias:
    n = len(errors)
    return Bias(group, n, fmean(errors), stdev(errors) / math.sqrt(n) if n > 1 else None, fmean(abs(e) for e in errors))


def fantavoto_bias(rows: Sequence[Scored]) -> list[ModelBias]:
    by_model: dict[tuple[str, str | None], list[Scored]] = defaultdict(list)
    for row in rows:
        if row.voted:
            by_model[(row.model_hash, row.weekly_hash)].append(row)
    out = []
    for (model, weekly), group in sorted(by_model.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        by_role: dict[str, list[float]] = defaultdict(list)
        for row in group:
            by_role[row.actual.classic_role].append(row.error)
        roles = [r for r in ROLE_ORDER if r in by_role] + sorted(set(by_role) - set(ROLE_ORDER))
        groups = [_bias(role, by_role[role]) for role in roles] + [_bias("all", [r.error for r in group])]
        spread = [r for r in group if r.fv_sd is not None and r.fv_sd > 0]
        within_1 = fmean(1.0 if abs(r.error) <= r.fv_sd else 0.0 for r in spread) if spread else None
        within_2 = fmean(1.0 if abs(r.error) <= 2 * r.fv_sd else 0.0 for r in spread) if spread else None
        out.append(ModelBias(model, weekly, groups, len(spread), within_1, within_2))
    return out


def _surprise(row: Scored) -> Surprise:
    return Surprise(row.giornata, row.player_id, row.name, row.club, row.p_start_published, row.fv_if_plays,
                    row.actual.fantavoto if row.voted else None, row.error)


def surprises(rows: Sequence[Scored], *, my_roster: frozenset[int] = frozenset()) -> dict[str, list[Surprise]]:
    """The page's confident no-shows, its long shots who played, and the
    largest fantavoto misses on my own roster -- what a journal entry names."""
    no_shows = sorted((r for r in rows if r.p_start_published is not None and r.p_start_published >= CONFIDENT
                       and not r.voted), key=lambda r: (-r.p_start_published, r.giornata, r.name))
    long_shots = sorted((r for r in rows if r.p_start_published is not None and r.p_start_published <= LONG_SHOT
                         and r.voted), key=lambda r: (-r.actual.fantavoto, r.giornata, r.name))
    misses = sorted((r for r in rows if r.player_id in my_roster and r.voted),
                    key=lambda r: (-abs(r.error), r.giornata, r.name))
    return {"no_shows": [_surprise(r) for r in no_shows[:LIST_LIMIT]],
            "long_shots": [_surprise(r) for r in long_shots[:LIST_LIMIT]],
            "my_misses": [_surprise(r) for r in misses[:MY_MISSES]]}
