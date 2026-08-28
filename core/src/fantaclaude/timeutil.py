"""Timestamps: aware UTC in Python, naive UTC in DuckDB.

DuckDB's TIMESTAMP has no zone, and binding an aware datetime converts it to
the machine's local time first -- an auction-night laptop in Rome would store
10:00Z as 12:00. Everything that lands in a TIMESTAMP column passes through
to_db() so the stored value is always UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_db(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)
