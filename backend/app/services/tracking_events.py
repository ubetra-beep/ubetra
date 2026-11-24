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


def counts_as_full_orgasm(tags: list[str]) -> bool:
    """An orgasm row is full unless it was marked ruined, denied, or milking.

    Older reports stored the method (PiV, vibrator, handjob, …) on the orgasm
    and kept ruined as its own tag. Those rows are full orgasms.
    """
    if has_ruined_orgasm_tag(tags) and not has_full_orgasm_tag(tags):
        return False
    if has_full_orgasm_tag(tags):
        return True
    if has_denial_tag(tags) or has_milking_tag(tags):
        return False
    return True


def entry_orgasm_tag_lists(entry) -> list[list[str]]:
    rows = list(getattr(entry, "orgasms", None) or [])
    if rows:
        return [
            [part.strip() for part in str(getattr(row, "tags", "") or "").split(",") if part.strip()]
            for row in rows
        ]
    raw = str(getattr(entry, "tags", "") or "")
    return [[part.strip() for part in raw.split(",") if part.strip()]]


def entry_counts_as_full_orgasm(entry) -> bool:
    if not is_orgasm_event(entry.event_type):
        return False
    return any(counts_as_full_orgasm(tags) for tags in entry_orgasm_tag_lists(entry))


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


def has_cheated_tag(tags: list[str]) -> bool:
    for raw in tags or []:
        t = " ".join(str(raw).lower().replace("-", " ").replace("_", " ").split())
        if not t:
            continue
        if "cheat" in t:
            return True
    return False


def has_milking_tag(tags: list[str]) -> bool:
    for raw in tags or []:
        t = " ".join(str(raw).lower().replace("-", " ").replace("_", " ").split())
        if not t:
            continue
        if "milk" in t:
            return True
    return False