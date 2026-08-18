from __future__ import annotations

import re
from datetime import datetime, timezone

_NAIVE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$")


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


def stamp_datetimes(obj):
    """Walk JSON-ready values and mark naive UTC datetimes/ISO strings with Z."""
    if isinstance(obj, datetime):
        return utc_iso(obj)
    if isinstance(obj, str) and _NAIVE_ISO.match(obj):
        return obj.replace(" ", "T") + "Z"
    if isinstance(obj, dict):
        return {key: stamp_datetimes(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [stamp_datetimes(value) for value in obj]
    return obj
