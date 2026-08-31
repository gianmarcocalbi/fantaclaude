"""One predicate, for every loader that reads a number out of a YAML file or
out of the league API's JSON.

Two things slip past a bare isinstance check. A bool is an int, so
`availability: true` would be 1.0. And a float can be NaN or an infinity:
YAML writes them `.nan` and `.inf`, and json.loads reads a bare `NaN`
literal happily. Neither survives the canonical_json that every hash and
every stored payload goes through, and nothing this model computes has a
meaning at infinity -- while a NaN is worse than an error, because it
propagates silently through every sum until an entire ranking is NaN.

This was three private `_number` copies (model/scoring.py, model/d_factor.py,
kb/notes.py) and six inlined spellings of the same test. Some of them stood
behind a range check that already excluded a NaN and some did not, which is
exactly the divergence nine copies of one predicate produce: bnMls, the
D-Factor bands and the pricing knobs all accepted a NaN, the other six
refused it.

Deliberately at the top level and importing nothing from the package:
asta/ must be able to use it without reaching into the model layer.
"""

from __future__ import annotations

import math
from typing import Any


def is_number(value: Any) -> bool:
    """A real, finite number: not a bool, not NaN, not an infinity."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isinstance(value, int) or math.isfinite(value)     # an int is always finite; math.isfinite(10**400) is not


def json_safe(value: Any) -> Any:
    """The same value with every non-finite float -- -inf, inf, nan -- replaced
    by None, at any depth; tuples come back as lists, as JSON would have them.

    A -inf is a real answer inside the pricing (no completion exists without
    this player; his class has no slot left) and not a number JSON has, and
    DuckDB's JSON column refuses it. One scrubber for the one rule, used by
    every to_dict and explain that a board or a run is written from -- it used
    to be two private copies, and explain() applied neither."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value
