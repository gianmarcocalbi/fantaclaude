"""The weekly layer's own version and constants, hashed beside the run's
model_hash (spec, "Two hashes here too"). Every threshold the blend, the
checks, the bench, the matchup term and the spread read lives here, so a
change to any of them is a new weekly model that calibration can split on,
and the run's hash does not pretend it changed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

WEEKLY_VERSION = 1


@dataclass(frozen=True)
class WeeklyConfig:
    # the blend's checks (Task 7)
    injured_page_threshold: int = 10       # an infortunato the page still prices at or above this % is a disagreement
    kb_depth_out_threshold: int = 10       # a KB `depth: out` under a page at or above this % is a disagreement
    kb_availability_gap: float = 0.3       # published/100 minus the KB availability at or above this is a disagreement
    european_window_days: int = 3          # a tie within this many days of the fixture makes it a European week
    european_gap: float = 0.2              # published/100 minus rate x rotation_factor at or above this is a disagreement
    european_min_published: int = 60       # below this % the site is already fading him; nothing to argue
    # the XI's outputs (Task 8)
    contingency_threshold: float = 0.75    # a starter below this p_start gets a re-solve without him
    close_call_margin: float = 0.5         # a slot whose best excluded fit is within this many points is a close call
    close_calls_max: int = 3
    # the forecast terms (Task 9)
    matchup_shrink_k: float = 60.0         # rows at which a matchup delta counts half
    matchup_cap: float = 0.5               # the most the matchup term may move fv_if_plays, either way
    spread_prior_k: float = 10.0           # rated matches at which a player's own dispersion counts half against the role prior
    spread_back_seasons: int = 3

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


DEFAULT_CONFIG = WeeklyConfig()          # a module-level singleton -- frozen, so one default serves every caller (B008)


def weekly_hash(cfg: WeeklyConfig = DEFAULT_CONFIG) -> str:
    """Sixteen hex characters over the version and every constant, sorted."""
    payload = json.dumps({"version": WEEKLY_VERSION, **cfg.to_dict()}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
