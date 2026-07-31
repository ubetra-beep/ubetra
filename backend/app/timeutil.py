from __future__ import annotations

from datetime import datetime, timezone


def as_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetimes for SQLite storage (naive UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def utc_iso(dt: datetime | None) -> str | None:
    """Serialize naive/aware datetimes as UTC ISO-8601 with Z."""
    if dt is None:
        return None
    naive = as_naive_utc(dt)
    assert naive is not None
    return naive.isoformat(timespec="seconds") + "Z"
