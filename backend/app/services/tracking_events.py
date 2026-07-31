from __future__ import annotations

from ..models import OrgEventType, OrgTrackingEntry, OrgTrackingOrgasm

ORGASM_EVENT_TYPES = frozenset({OrgEventType.orgasm, OrgEventType.both})
PLAY_EVENT_TYPES = frozenset({OrgEventType.no_orgasm, OrgEventType.sex})


def is_orgasm_event(event_type: OrgEventType) -> bool:
    return event_type in ORGASM_EVENT_TYPES


def is_play_event(event_type: OrgEventType) -> bool:
    return event_type in PLAY_EVENT_TYPES


def orgasm_count(entry: OrgTrackingEntry, orgasms: list[OrgTrackingOrgasm] | None = None) -> int:
    rows = orgasms if orgasms is not None else list(entry.orgasms or [])
    if rows:
        return len(rows)
    return 1 if is_orgasm_event(entry.event_type) else 0


def has_full_orgasm_tag(tags: list[str]) -> bool:
    for raw in tags or []:
        t = " ".join(str(raw).lower().replace("-", " ").replace("_", " ").split())
        if not t:
            continue
        if t == "full orgasm" or t.startswith("full orgasm"):
            return True
        if "full" in t and "orgasm" in t:
            return True
    return False


def has_ruined_orgasm_tag(tags: list[str]) -> bool:
    for raw in tags or []:
        t = " ".join(str(raw).lower().replace("-", " ").replace("_", " ").split())
        if not t:
            continue
        if "ruin" in t:
            return True
    return False


def has_denial_tag(tags: list[str]) -> bool:
    """Match denial / denied / teased & denied — not ruins."""
    for raw in tags or []:
        t = " ".join(str(raw).lower().replace("-", " ").replace("_", " ").split())
        if not t:
            continue
        if "ruin" in t:
            continue
        if t in {"denial", "denied", "deny", "teased denied", "tease denial", "tease denied"}:
            return True
        if "denied" in t or "denial" in t:
            return True
    return False