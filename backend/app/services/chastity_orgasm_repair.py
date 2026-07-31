"""Apply missed full-orgasm releases onto overlapping chastity lockups."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from ..models import (
    ChastityBreak,
    ChastityEndedKind,
    ChastityLockup,
    ChastityRecordType,
    LockupStatus,
    OrgEventType,
    OrgTrackingEntry,
)
from .tags import tags_to_list
from .tracking_events import has_full_orgasm_tag


def repair_missed_orgasm_releases(db: Session, dynamic_id: str) -> int:
    """End lockups that overlap a logged full orgasm but were never marked Released!.

    If the lockup continued after the orgasm (later temp unlocks), those breaks are
    moved onto a new lockup starting at the first lock-back after the orgasm so
    history is preserved.

    Returns number of lockups updated.
    """
    entries = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.event_type.in_([OrgEventType.orgasm, OrgEventType.both]),
        )
        .order_by(OrgTrackingEntry.occurred_at.asc())
        .all()
    )
    updated = 0
    for entry in entries:
        tags: list[str] = []
        for row in entry.orgasms or []:
            tags.extend(tags_to_list(getattr(row, "tags", "") or ""))
        tags.extend(tags_to_list(entry.tags or ""))
        if not has_full_orgasm_tag(tags):
            continue
        at = entry.occurred_at or datetime.utcnow()
        lockup = (
            db.query(ChastityLockup)
            .options(joinedload(ChastityLockup.breaks))
            .filter(
                ChastityLockup.dynamic_id == dynamic_id,
                ChastityLockup.for_membership_id == entry.for_membership_id,
                ChastityLockup.started_at <= at,
            )
            .order_by(ChastityLockup.started_at.desc())
            .first()
        )
        if lockup is None:
            continue
        kind = getattr(lockup, "ended_kind", "") or ""
        if kind in (
            ChastityEndedKind.released_orgasm.value,
            ChastityEndedKind.released_timer.value,
        ):
            continue
        if lockup.ended_at is not None and lockup.ended_at < at:
            continue

        was_open = lockup.ended_at is None
        original_ended_at = lockup.ended_at
        post_breaks: list[ChastityBreak] = []
        resume_at: datetime | None = None

        for brk in list(lockup.breaks or []):
            if brk.started_at >= at:
                post_breaks.append(brk)
                continue
            if brk.ended_at is None or brk.ended_at > at:
                if brk.ended_at is not None and brk.ended_at > at:
                    if resume_at is None or brk.ended_at < resume_at:
                        resume_at = brk.ended_at
                brk.ended_at = at

        if post_breaks and resume_at is None:
            resume_at = min(b.started_at for b in post_breaks)

        lockup.status = LockupStatus.ended
        lockup.ended_at = at
        lockup.ended_kind = ChastityEndedKind.released_orgasm.value
        lockup.timer_notified_at = None
        if not (lockup.release_notes or "").strip():
            lockup.release_notes = "Released with full orgasm"
        updated += 1

        needs_continuation = bool(post_breaks) or (
            resume_at is not None and resume_at > at and was_open
        )
        if not needs_continuation:
            continue

        new_start = resume_at if resume_at and resume_at > at else at
        any_open_break = any(b.ended_at is None for b in post_breaks)
        new_active = was_open or any_open_break
        new_lockup = ChastityLockup(
            dynamic_id=lockup.dynamic_id,
            for_membership_id=lockup.for_membership_id,
            started_by_membership_id=lockup.started_by_membership_id,
            started_at=new_start,
            ended_at=None if new_active else original_ended_at,
            ended_by_membership_id=None
            if new_active
            else lockup.ended_by_membership_id,
            device_notes="",
            release_notes="",
            tags=lockup.tags or "",
            record_type=lockup.record_type or ChastityRecordType.normal,
            status=LockupStatus.active if new_active else LockupStatus.ended,
            ended_kind="" if new_active else ChastityEndedKind.unlocked.value,
        )
        db.add(new_lockup)
        db.flush()
        for brk in post_breaks:
            brk.lockup_id = new_lockup.id

    if updated:
        db.commit()
    return updated
