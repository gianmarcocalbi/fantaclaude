"""The reliability curve on the published p_start (spec, "Calibration: what
3c ships").

The outcome is "got a voto", not "started": a substitute who plays half an
hour gets one, so the low bins read above their percentages by construction
-- and it is still the right outcome, because it is what `expected_points =
p_start x fv_if_plays` assumes p_start means. Bins of ten points on the
page's own values, each with a 95% Wilson interval; beside them the Brier
score of the published number, of the blend and of the base rate, over the
same rows, so "does the page beat knowing nothing, and does the blend beat
the page" is one line.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any

from fantaclaude.analysis.calibration.actuals import Scored

BIN_WIDTH = 10
TOP_BIN = 9                      # 90-100: a published 100 joins the nineties
Z95 = 1.959963984540054


@dataclass(frozen=True)
class Bin:
    low: int
    high: int
    n: int
    mean_predicted: float
    observed: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class PStartReport:
    n: int
    bins: list[Bin]
    base_rate: float | None
    brier_published: float | None
    brier_blend: float | None
    brier_base_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"n": self.n, "bins": [asdict(b) for b in self.bins], "base_rate": self.base_rate,
                "brier_published": self.brier_published, "brier_blend": self.brier_blend,
                "brier_base_rate": self.brier_base_rate}


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for k successes in n trials; (0, 1) for none."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def bin_index(published: int) -> int:
    return min(max(published, 0) // BIN_WIDTH, TOP_BIN)


def reliability(rows: Sequence[Scored]) -> PStartReport:
    usable = [r for r in rows if r.p_start_published is not None]
    if not usable:
        return PStartReport(0, [], None, None, None, None)
    outcomes = [1.0 if r.voted else 0.0 for r in usable]
    grouped: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for row, outcome in zip(usable, outcomes, strict=True):
        grouped[bin_index(row.p_start_published)].append((row.p_start_published / 100, outcome))
    bins = []
    for index in sorted(grouped):
        pairs = grouped[index]
        k, n = int(sum(y for _, y in pairs)), len(pairs)
        low, high = wilson(k, n)
        bins.append(Bin(index * BIN_WIDTH, 100 if index == TOP_BIN else index * BIN_WIDTH + BIN_WIDTH - 1, n,
                        fmean(p for p, _ in pairs), k / n, low, high))
    base = fmean(outcomes)
    return PStartReport(
        len(usable), bins, base,
        fmean((r.p_start_published / 100 - y) ** 2 for r, y in zip(usable, outcomes, strict=True)),
        fmean((r.p_start - y) ** 2 for r, y in zip(usable, outcomes, strict=True)),
        fmean((base - y) ** 2 for y in outcomes))
