"""Every filesystem location the package uses, in one place.

The root comes from the MCP so both packages agree on FANTACALCIO_HOME and on
what "the workspace" is; nothing here re-derives it from __file__.
"""

from __future__ import annotations

from pathlib import Path

from fantacalcio_mcp.config import workspace_root as _mcp_workspace_root


def workspace_root() -> Path:
    return _mcp_workspace_root()


def data_dir() -> Path:
    return workspace_root() / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def db_path() -> Path:
    return data_dir() / "fanta.duckdb"


def kb_dir() -> Path:
    return workspace_root() / "kb"


def records_dir() -> Path:
    return workspace_root() / "records"


def league_yml_path() -> Path:
    return workspace_root() / "league.yml"


def preferences_yml_path() -> Path:
    return workspace_root() / "preferences.yml"
