from datetime import UTC, datetime, timedelta, timezone

from fantaclaude.timeutil import to_db, utc_now


def _naive(*args: int) -> datetime:
    # A tzinfo-free `datetime(...)` call trips ruff's DTZ001; build the
    # deliberately naive values these assertions need through an aware
    # constructor instead, then strip the zone back off.
    return datetime(*args, tzinfo=UTC).replace(tzinfo=None)


def test_to_db_normalises_to_naive_utc():
    rome = timezone(timedelta(hours=2))
    assert to_db(datetime(2026, 8, 24, 12, 0, tzinfo=rome)) == _naive(2026, 8, 24, 10, 0)
    assert to_db(datetime(2026, 8, 24, 10, 0, tzinfo=UTC)) == _naive(2026, 8, 24, 10, 0)
    assert to_db(_naive(2026, 8, 24, 10, 0)) == _naive(2026, 8, 24, 10, 0)   # naive is taken as UTC


def test_utc_now_is_aware():
    assert utc_now().tzinfo is UTC
