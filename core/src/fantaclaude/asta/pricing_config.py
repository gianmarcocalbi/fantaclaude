"""pricing.yml -> PricingConfig, so whoever tunes the numbers never opens
the algorithm and whoever changes the algorithm never hunts for numbers."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.asta.pricing import PricingConfig

# fantaclaude.values is top level and imports nothing from the package, so
# asta/ still reaches into no other layer -- the model layer least of all.
from fantaclaude.values import is_number


class PricingConfigError(ValueError):
    """pricing.yml is malformed, names an unknown knob, or types one wrongly."""


def load_pricing_config(path: Path) -> PricingConfig:
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PricingConfigError(f"{path}: {exc}") from None
    if not isinstance(data, dict):
        raise PricingConfigError(f"{path}: the top level must be a mapping of knobs")
    known = {f.name: f.type for f in fields(PricingConfig)}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise PricingConfigError(f"{path}: unknown knob(s) {unknown}; known: {sorted(known)}")
    values: dict[str, Any] = {}
    for name, value in data.items():
        expected = known[name]
        # is_number also rules out `.nan` / `.inf`, which nothing downstream
        # range-checks: a NaN bench_weight makes every rank weight NaN and
        # every max price with it, and neither survives the canonical_json
        # that model_hash and the stored config both go through.
        if not is_number(value) or (expected == "int" and not isinstance(value, int)):
            raise PricingConfigError(f"{path}: {name} must be {expected}, got {value!r}")
        values[name] = int(value) if expected == "int" else float(value)
    return PricingConfig(**values)
