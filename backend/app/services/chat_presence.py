from __future__ import annotations

import time
from threading import Lock

# dynamic_id -> membership_id -> expiry monotonic time
_typing: dict[str, dict[str, float]] = {}
_lock = Lock()

_TYPING_TTL = 3.5


def mark_typing(dynamic_id: str, membership_id: str, ttl: float = _TYPING_TTL) -> None:
    now = time.monotonic()
    with _lock:
        bucket = _typing.setdefault(dynamic_id, {})
        bucket[membership_id] = now + ttl
        # prune expired
        expired = [mid for mid, exp in bucket.items() if exp <= now]
        for mid in expired:
            bucket.pop(mid, None)


def active_typers(dynamic_id: str, *, exclude_membership_id: str | None = None) -> list[str]:
    now = time.monotonic()
    with _lock:
        bucket = _typing.get(dynamic_id) or {}
        alive = []
        stale = []
        for mid, exp in bucket.items():
            if exp <= now:
                stale.append(mid)
            elif exclude_membership_id and mid == exclude_membership_id:
                continue
            else:
                alive.append(mid)
        for mid in stale:
            bucket.pop(mid, None)
        if not bucket and dynamic_id in _typing:
            _typing.pop(dynamic_id, None)
        return alive
