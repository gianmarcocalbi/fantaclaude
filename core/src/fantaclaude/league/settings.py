"""league_settings: an append-only snapshot of the rules in force.

Every valuation depends on the rules -- money supply, roster bounds, scoring
-- so a rule change is history, not a lost fact. One row per observed change,
keyed by rules_hash; the full payloads travel in a JSON column, decoded by the
MCP's own models so nothing is renamed twice.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb
from fantacalcio_mcp.models import League, LeagueSettings, LeagueStatus

from fantaclaude.timeutil import to_db, utc_now

# Server-side bookkeeping that changes without any rule changing.
VOLATILE_KEYS = frozenset({"count", "version"})


@dataclass(frozen=True)
class LeagueSnapshot:
    league_id: int
    season_id: int | None
    matchday: int | None
    team_count: int | None
    budget: int | None
    roster_min: int | None
    roster_max: int | None
    modules: tuple[str, ...]
    bench_size: int | None
    substitutions: int | None
    rules_hash: str
    payload: dict[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(view: Any) -> str:
    """Sixteen hex characters of the sha256 of the canonical JSON of `view`:
    the one formula behind rules_hash, model_hash and inputs_hash."""
    return hashlib.sha256(canonical_json(view).encode("utf-8")).hexdigest()[:16]


def _rules_view(rosters: dict, lineup: dict, calculate: dict, team_count: int | None) -> dict:
    strip = lambda d: {k: v for k, v in d.items() if k not in VOLATILE_KEYS}
    return {"rosters": strip(rosters), "lineup": strip(lineup),
            "calculate": strip(calculate), "team_count": team_count}


def rules_hash(rosters: dict, lineup: dict, calculate: dict, team_count: int | None) -> str:
    """Sixteen hex characters over everything a valuation depends on: the
    three settings payloads (minus volatile bookkeeping) and the team count,
    which sets the money supply."""
    return digest(_rules_view(rosters, lineup, calculate, team_count))


def _is_email_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalised = "".join(ch for ch in key.lower() if ch.isalnum())
    return "email" in normalised or normalised in {"mail", "mails"}


# An email *shape*: local part, "@", domain, dot-TLD. Deliberately narrower
# than a bare "@" so a league nickname like "@bomber" is never redacted --
# over-matching there would be real data loss in the safe-looking direction.
# Unanchored: searched for anywhere in the value, so an address embedded in a
# longer note ("reach me at x@y.it") is still caught, not just an exact match.
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
EMAIL_REDACTED = "[email redacted]"


def _is_email_value(value: Any) -> bool:
    return isinstance(value, str) and bool(EMAIL_PATTERN.search(value))


def without_emails(value: Any) -> Any:
    """Scrub email addresses at any depth, two ways: drop every email-bearing
    *key* (defence in depth for the common case), and redact every *value*
    that has the shape of an email address regardless of the key it sits
    under -- a stray address under an innocuous key must not survive either.
    Redacting (not dropping) a matched value keeps the payload's shape intact
    for anything reading it later.

    Applied to profile/status/teams -- the payloads that carry people. Never
    applied to rosters/lineup/calculate: rules_hash() hashes those payloads'
    raw arguments while diff_rules() reads them back out of the stored
    payload, so scrubbing one and not the other would make the hashed view
    and the diffed view silently disagree. Those three carry rule numbers,
    not people, so there is nothing to gain from scrubbing them and a real
    invariant to lose.

    Public because kb/participants.py asks it the same question in the other
    direction -- "would this have changed anything?" -- rather than keeping a
    second walker that only saw the top level (finding 11).
    """
    if isinstance(value, dict):
        return {k: without_emails(v) for k, v in value.items() if not _is_email_key(k)}
    if isinstance(value, list):
        return [without_emails(item) for item in value]
    if _is_email_value(value):
        return EMAIL_REDACTED
    return value


def snapshot_from_payloads(*, profile: dict, status: dict, rosters: dict, lineup: dict,
                           calculate: dict, teams: Any) -> LeagueSnapshot:
    league = League.from_api(profile)            # pops the join password
    league_status = LeagueStatus.from_api(status)
    settings = LeagueSettings.from_api(rosters=rosters, lineup=lineup, calculate=calculate)
    team_rows = teams.get("data") if isinstance(teams, dict) else teams
    team_count = league.team_count
    if team_count is None and team_rows is not None:
        team_count = len(team_rows)
    return LeagueSnapshot(
        league_id=league.league_id,
        season_id=league_status.season_id,
        matchday=league_status.matchday,
        team_count=team_count,
        budget=settings.budget,
        roster_min=settings.roster_min,
        roster_max=settings.roster_max,
        modules=tuple(settings.modules),
        bench_size=settings.bench_size,
        substitutions=settings.substitutions,
        rules_hash=rules_hash(rosters, lineup, calculate, team_count),
        payload={"profile": without_emails(league.raw), "status": without_emails(league_status.raw),
                 "rosters": rosters, "lineup": lineup, "calculate": calculate,
                 "teams": without_emails(teams)},
    )


@dataclass(frozen=True)
class Change:
    path: str
    before: Any
    after: Any


def diff_payloads(old: Any, new: Any, prefix: str = "") -> list[Change]:
    """Recursive over mappings; lists and scalars compare as a whole. Paths
    are dotted, keys in sorted order, so a report is stable run to run."""
    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[Change] = []
        for key in sorted(set(old) | set(new), key=str):
            path = f"{prefix}.{key}" if prefix else str(key)
            changes.extend(diff_payloads(old.get(key), new.get(key), path))
        return changes
    return [] if old == new else [Change(prefix, old, new)]


def diff_rules(old_payload: dict, old_team_count: int | None, new: LeagueSnapshot) -> list[Change]:
    before = _rules_view(old_payload["rosters"], old_payload["lineup"], old_payload["calculate"], old_team_count)
    after = _rules_view(new.payload["rosters"], new.payload["lineup"], new.payload["calculate"], new.team_count)
    return diff_payloads(before, after)


@dataclass(frozen=True)
class StoredSnapshot:
    snapshot_id: int
    fetched_at: datetime
    rules_hash: str
    team_count: int | None
    payload: dict[str, Any]


def latest_snapshot(con: duckdb.DuckDBPyConnection) -> StoredSnapshot | None:
    row = con.execute(
        "SELECT snapshot_id, fetched_at, rules_hash, team_count, payload "
        "FROM league_settings ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    payload = row[4] if isinstance(row[4], dict) else json.loads(row[4])
    return StoredSnapshot(row[0], row[1], row[2], row[3], payload)


@dataclass(frozen=True)
class SyncResult:
    changed: bool
    snapshot_id: int | None
    rules_hash: str
    previous_hash: str | None
    diff: list[Change] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"changed": self.changed, "snapshot_id": self.snapshot_id,
                "rules_hash": self.rules_hash, "previous_hash": self.previous_hash,
                "diff": [{"path": c.path, "before": c.before, "after": c.after} for c in self.diff]}


def record_snapshot(con: duckdb.DuckDBPyConnection, snap: LeagueSnapshot, *,
                    fetched_at: datetime | None = None) -> SyncResult:
    """Append a row only when the rules hash moved. The first row is always
    a change; an identical hash is reported, not stored."""
    previous = latest_snapshot(con)
    if previous is not None and previous.rules_hash == snap.rules_hash:
        return SyncResult(False, previous.snapshot_id, snap.rules_hash, previous.rules_hash)
    diff = diff_rules(previous.payload, previous.team_count, snap) if previous is not None else []
    row = con.execute(
        "INSERT INTO league_settings (fetched_at, league_id, season_id, matchday, rules_hash, "
        "team_count, budget, roster_min, roster_max, modules, bench_size, substitutions, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON) RETURNING snapshot_id",
        [to_db(fetched_at or utc_now()), snap.league_id, snap.season_id, snap.matchday,
         snap.rules_hash, snap.team_count, snap.budget, snap.roster_min, snap.roster_max,
         list(snap.modules), snap.bench_size, snap.substitutions, canonical_json(snap.payload)],
    ).fetchone()
    return SyncResult(True, row[0], snap.rules_hash,
                      previous.rules_hash if previous is not None else None, diff)
