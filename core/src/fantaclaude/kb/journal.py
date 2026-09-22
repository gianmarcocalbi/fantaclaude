"""The season journal's file names (spec, "The season journal"): one entry per
giornata beside entry zero, the auction's `giornata-00-asta.md`."""

from __future__ import annotations

from pathlib import Path

from fantaclaude.model.seasons import season_label


def season_dir(kb: Path, season_id: int) -> Path:
    return kb / "league" / f"season-{season_label(season_id)}"


def entry_path(kb: Path, season_id: int, giornata: int) -> Path:
    return season_dir(kb, season_id) / f"giornata-{giornata:02d}.md"
