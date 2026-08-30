"""One ranking order for the whole run.

The per-class regroup-and-sort appears six times -- `replacement_levels`,
`assign_tiers` and `divergence` in the valuation, the three per-class tables
in the exports, and the rank report's top three -- and it carried two
different tie-breaks: `-value_p50` alone in the exports and the report,
`(-value_p50, player_id)` in the valuation.

That is not duplication, it is a correctness inconsistency. Every player with
`exp_presenze == 0` sits at `value_p50 == 0.0`, so a tier cut or a divergence
pairing could land on a *different* player than the one `rankings.md` prints
beside it -- decided by nothing but the order the rows happened to arrive in.
One helper, one deterministic tie-break, at every site.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _field(item: Any, name: str) -> Any:
    """A Projection, a PoolPlayer and the exports' dict rows all carry
    `player_id`, `role_class` and `value_p50` -- as attributes on the first
    two, as keys on the third. The alternative is an accessor argument at
    every call site, which is the duplication this module exists to remove."""
    return item[name] if isinstance(item, dict) else getattr(item, name)


def rank_key(item: Any) -> tuple[float, int]:
    """Value descending, then player_id ascending.

    The id breaks the tie because it is the only total order the run already
    has, and it is reproducible from the record -- unlike the order a query
    happened to return the rows in, which is what the exports were leaning on."""
    return (-float(_field(item, "value_p50")), int(_field(item, "player_id")))


def by_class(items: Iterable[Any]) -> dict[str, list[Any]]:
    """Group by role class; every list in `rank_key` order.

    Classes come back in the order they first appear, so a caller that wants
    them in a fixed order says so (`ROLE_CLASSES`) rather than relying on this."""
    groups: dict[str, list[Any]] = {}
    for item in items:
        groups.setdefault(str(_field(item, "role_class")), []).append(item)
    return {cls: sorted(members, key=rank_key) for cls, members in groups.items()}
