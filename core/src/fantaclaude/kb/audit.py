"""fantaclaude kb audit: which documents have expired.

Every kb document carries front-matter: updated (ISO date), ttl ("7d", "30d"
or "never"), confidence, source. Expired means updated + ttl < today. The
audit is a notice, never a refusal -- refusing belongs to the skill that
would otherwise lean on stale prose.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

REQUIRED = ("updated", "ttl", "confidence", "source")
_TTL = re.compile(r"^(\d+)d$")


class FrontMatterError(ValueError):
    """The leading YAML block is malformed."""


@dataclass(frozen=True)
class FrontMatter:
    updated: date | None
    ttl: str | None
    confidence: str | None
    source: str | None
    raw: dict[str, Any]


def parse_front_matter(text: str) -> FrontMatter | None:
    """The leading '---' block as YAML; None when the document has none."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        raise FrontMatterError("unterminated front-matter")
    data = yaml.safe_load(text[4:end]) or {}
    if not isinstance(data, dict):
        raise FrontMatterError("front-matter is not a mapping")
    updated = data.get("updated")
    # PyYAML yields a datetime for `2026-08-20T10:00:00`, and datetime is a
    # date subclass -- so it passes the check below and then cannot be compared
    # to the plain date the audit works in. Normalise rather than reject: the
    # author meant a day, and a TTL is measured in days.
    if isinstance(updated, datetime):
        updated = updated.date()
    if updated is not None and not isinstance(updated, date):
        raise FrontMatterError("updated must be an ISO date")
    ttl = data.get("ttl")
    return FrontMatter(updated, None if ttl is None else str(ttl),
                       data.get("confidence"), data.get("source"), data)


def ttl_days(ttl: str) -> int | None:
    if ttl == "never":
        return None
    match = _TTL.match(ttl)
    if not match:
        raise FrontMatterError(f"ttl must look like '7d' or 'never', got {ttl!r}")
    return int(match.group(1))


@dataclass(frozen=True)
class AuditEntry:
    path: str
    status: str            # ok | expired | missing_front_matter | invalid
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _validator_for(path: Path):
    """The structured loader a document must satisfy beyond the four keys:
    profiles, player notes and participant dossiers each have one. Imported
    lazily -- those modules import this one."""
    if path.name == "profile.md" and path.parent.parent.name == "teams":
        from fantaclaude.kb.profiles import load_profile

        return load_profile
    if path.parent.name == "players" and path.parent.parent.parent.name == "teams":
        from fantaclaude.kb.notes import load_note

        return load_note
    if path.parent.name == "participants" and path.parent.parent.name == "league":
        from fantaclaude.kb.participants import load_participant

        return load_participant
    return None


def audit(kb_dir: Path, today: date) -> list[AuditEntry]:
    entries: list[AuditEntry] = []
    if not kb_dir.is_dir():
        return entries
    for path in sorted(kb_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        rel = str(path.relative_to(kb_dir))
        try:
            fm = parse_front_matter(path.read_text(encoding="utf-8"))
            if fm is None:
                entries.append(AuditEntry(rel, "missing_front_matter", "no leading --- block"))
                continue
            missing = [k for k in REQUIRED if fm.raw.get(k) in (None, "")]
            if missing:
                entries.append(AuditEntry(rel, "invalid", f"missing {missing}"))
                continue
            days = ttl_days(fm.ttl)
            validator = _validator_for(path)
            if validator is not None:
                try:
                    validator(path)
                except ValueError as exc:
                    entries.append(AuditEntry(rel, "invalid", str(exc).split(": ", 1)[-1]))
                    continue
        except (FrontMatterError, OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            entries.append(AuditEntry(rel, "invalid", str(exc)))
            continue
        detail = f"updated {fm.updated}, ttl {fm.ttl}"
        if days is not None and fm.updated + timedelta(days=days) < today:
            entries.append(AuditEntry(rel, "expired", detail))
        else:
            entries.append(AuditEntry(rel, "ok", detail))
    return entries
