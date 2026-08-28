"""Immutable, dated raw files: what every adapter's fetch() writes.

data/raw/<kind>/<UTC stamp>-<kind>[-<label>].<ext>, created O_EXCL so nothing is ever
overwritten, fsynced, and hashed -- the spine is rebuildable from these.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fantaclaude.timeutil import utc_now


@dataclass(frozen=True)
class RawFile:
    path: Path
    sha256: str
    fetched_at: datetime
    kind: str


class RawStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, kind: str, payload: Any, *, label: str | None = None,
              fetched_at: datetime | None = None) -> RawFile:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        return self.write_bytes(kind, data, ext="json", label=label, fetched_at=fetched_at)

    def write_bytes(self, kind: str, data: bytes, *, ext: str, label: str | None = None,
                    fetched_at: datetime | None = None) -> RawFile:
        """data/raw/<kind>/<UTC stamp>-<kind>[-<label>].<ext>, O_EXCL and fsynced.

        `label` names what the file is *of* -- a season, a giornata, a page --
        so a directory listing reads without opening anything; the stamp keeps
        two fetches of the same thing apart.
        """
        fetched_at = fetched_at or utc_now()
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        stamp = fetched_at.strftime("%Y%m%dT%H%M%S%fZ")    # microseconds keep two writes apart
        suffix = f"-{label}" if label else ""
        path = folder / f"{stamp}-{kind}{suffix}.{ext}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        return RawFile(path, hashlib.sha256(data).hexdigest(), fetched_at, kind)

    def list(self, kind: str, *, ext: str = "json", label: str | None = None) -> list[Path]:
        """Every file of `kind` and `ext`, or only those of one `label`."""
        folder = self.root / kind
        pattern = f"*-{kind}-{label}.{ext}" if label else f"*-{kind}*.{ext}"
        return sorted(folder.glob(pattern)) if folder.is_dir() else []

    @staticmethod
    def sha256_of(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
