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


def aliases_path() -> Path:
    return kb_dir() / "rules" / "aliases.yml"


def exports_dir() -> Path:
    return data_dir() / "exports"


def pricing_yml_path() -> Path:
    return workspace_root() / "pricing.yml"


def adjustments_path() -> Path:
    """data/adjustments.yml: my beliefs and preferences for the auction -- mine, hand-editable, outlives the auction."""
    return data_dir() / "adjustments.yml"


def lineup_notes_path() -> Path:
    """data/lineup-notes.yml: my facts for the week -- mine, hand-editable, appended by `lineup note`, every entry with a giornata and a reason."""
    return data_dir() / "lineup-notes.yml"


def asta_state_path() -> Path:
    """data/asta-state.json: the mirrored auction as last seen, written atomically; removed only by `asta verify-transfer --prune` on a clean diff (3a). The copy under records/asta/ is permanent."""
    return data_dir() / "asta-state.json"


def asta_captures_dir() -> Path:
    """data/raw/asta_live/: one JSONL of feed nodes per served session — the
    capture `asta replay` rehearses on."""
    return raw_dir() / "asta_live"


def web_dist_dir() -> Path:
    """web/dist: the built dashboard bundle FastAPI mounts (poe web-build)."""
    return workspace_root() / "web" / "dist"
