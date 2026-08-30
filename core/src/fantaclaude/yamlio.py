"""One reader for every YAML file that must be a mapping.

preferences.yml, pricing.yml, league.yml and d_factor.yml were each read by
their own copy of `safe_load(...) or {}` with their own subset of the
errors caught -- rank's copy caught only yaml.YAMLError, so a file that
was not UTF-8 was a traceback there and a clean not-ready everywhere else.
Every caller wraps YamlFileError in its own error class, so the exit codes
and the messages the skills key on do not change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class YamlFileError(ValueError):
    """The file is missing, unreadable, not YAML, or not a mapping; the message names the path."""


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise YamlFileError(f"{path} is missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise YamlFileError(f"{path}: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise YamlFileError(f"{path}: the top level must be a mapping")
    return data
