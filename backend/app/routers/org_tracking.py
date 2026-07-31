from datetime import datetime, timedelta

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership

from ..database import get_db

from ..models import (
    ChastityEndedKind,
    Dynamic,
    LockupStatus,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    OrgTrackingOrgasm,
    PartnerRole,
    User,
)

from ..schemas import (
    OrgTrackingEntryCreate,
    OrgTrackingEntryOut,
    OrgTrackingEntryUpdate,
    OrgTrackingPrefsOut,
    OrgTrackingPrefsUpdate,
    OrgTrackingStatsOut,
)

from ..services.tags import tags_to_list, tags_to_string

from ..services.chat_events import post_activity_event, post_system_event

from ..services.tracking_events import has_full_orgasm_tag, is_orgasm_event, is_play_event, orgasm_count

from ..services.feelings import feelings_status, has_recent_context_checkin

from ..services.tracking_calendar import build_tracking_calendar

from ..services.org_tracking_prefs import prefs_for_dynamic, serialize_org_tracking_prefs

from ..services.settings_policy import is_dominant

from ..timeutil import as_naive_utc

router = APIRouter(prefix="/dynamics", tags=["org-tracking"])

def _maybe_release_lockup_for_full_orgasm(
    db: Session,
    *,
    dynamic_id: str,
    membership: Membership,
    target: Membership,
    entry: OrgTrackingEntry,
) -> None:
    """If a full orgasm was logged during a lockup (incl. on break), end as Released!."""
    if entry.event_type not in (OrgEventType.orgasm, OrgEventType.both):
        return
    orgasm_tags: list[str] = []
    for row in entry.orgasms or []:
        orgasm_tags.extend(tags_to_list(getattr(row, "tags", "") or ""))
    orgasm_tags.extend(tags_to_list(entry.tags or ""))
    if not has_full_orgasm_tag(orgasm_tags):
        return

    from ..services.chastity import active_break, active_lockup

    ended_at = entry.occurred_at or datetime.utcnow()
    lockup = active_lockup(db, dynamic_id, target.id)
    if lockup is None:
        # Cover lockup that overlaps the orgasm time (already ended wrongly, or race)
        from ..models import ChastityLockup

        lockup = (
            db.query(ChastityLockup)
            .filter(
                ChastityLockup.dynamic_id == dynamic_id,
                ChastityLockup.for_membership_id == target.id,
                ChastityLockup.started_at <= ended_at,
            )
            .order_by(ChastityLockup.started_at.desc())
            .first()
        )
        if lockup is None:
            return
        if lockup.ended_at is not None and lockup.ended_at < ended_at:
            return
        if (getattr(lockup, "ended_kind", "") or "") in (
            ChastityEndedKind.released_orgasm.value,
            ChastityEndedKind.released_timer.value,
        ):
            return

    brk = active_break(lockup)
    if brk and brk.ended_at is None:
        brk.ended_at = ended_at
    # Also close any break that was still open past the orgasm
    for open_brk in lockup.breaks or []:
        if open_brk.ended_at is None:
            open_brk.ended_at = ended_at
        elif open_brk.started_at <= ended_at < open_brk.ended_at:
            open_brk.ended_at = ended_at

    lockup.status = LockupStatus.ended
    lockup.ended_at = ended_at
    lockup.ended_by_membership_id = membership.id
    lockup.ended_kind = ChastityEndedKind.released_orgasm.value
    lockup.timer_notified_at = None
    if not (lockup.release_notes or "").strip():
        lockup.release_notes = "Released with full orgasm"
    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="lockup_ended",
        text=f"ended chastity lockup for {target.display_name} (full orgasm)",
        path=f"/dynamic/{dynamic_id}/chastity",
        link_label="Open chastity",
        subject_membership_id=target.id,
    )



def _entry_out(
    entry: OrgTrackingEntry,
    memberships: dict[str, Membership],
    *,
    viewer: Membership | None = None,
    session_id: str | None = None,
    during_lockup: bool = False,
    during_own_lockup: bool = False,
    locked_partner_names: list[str] | None = None,
    session_entry_count: int = 1,
) -> OrgTrackingEntryOut:

    for_member = memberships.get(entry.for_membership_id)
    logged_by = memberships.get(entry.logged_by_membership_id)
    initiated = memberships.get(getattr(entry, "initiated_by_membership_id", None) or "")

    notes = entry.notes or ""
    notes_hidden = False
    if getattr(entry, "notes_private", False) and notes:
        can_see = False
        if viewer is not None:
            can_see = viewer.id in (
                entry.logged_by_membership_id,
                entry.for_membership_id,
            ) or is_dominant(viewer)
        if not can_see:
            notes = ""
            notes_hidden = True

    return OrgTrackingEntryOut(
        id=entry.id,
        for_membership_id=entry.for_membership_id,
        for_display_name=for_member.display_name if for_member else "Partner",
        event_type=entry.event_type,
        notes=notes,
        tags=tags_to_list(entry.tags),
        orgasms=[
            {
                "id": row.id,
                "tags": tags_to_list(row.tags),
                "position": row.position,
            }
            for row in sorted(entry.orgasms or [], key=lambda r: r.position)
        ],
        occurred_at=entry.occurred_at,
        ended_at=entry.ended_at,
        duration_minutes=entry.duration_minutes,
        dominant_time_at=entry.dominant_time_at,
        submissive_time_at=entry.submissive_time_at,
        location=getattr(entry, "location", "") or "",
        initiated_by_membership_id=getattr(entry, "initiated_by_membership_id", None),
        initiated_by_display_name=initiated.display_name if initiated else None,
        protection=getattr(entry, "protection", "") or "",
        satisfaction=getattr(entry, "satisfaction", None),
        edging_count=getattr(entry, "edging_count", None),
        notes_private=bool(getattr(entry, "notes_private", False)),
        notes_hidden=notes_hidden,
        logged_by_display_name=logged_by.display_name if logged_by else "Partner",
        session_id=session_id,
        during_lockup=during_lockup,
        during_own_lockup=during_own_lockup,
        locked_partner_names=locked_partner_names or [],
        session_entry_count=session_entry_count,
    )

def _membership_map(db: Session, dynamic_id: str) -> dict[str, Membership]:

    return {m.id: m for m in db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()}

def _validate_payload(event_type: OrgEventType, orgasms: list) -> None:

    if event_type == OrgEventType.orgasm and not orgasms:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="Orgasm events need at least one orgasm with tags.",

        )

    if event_type == OrgEventType.no_orgasm and orgasms:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="No-orgasm play events cannot include orgasm rows.",

        )

def _apply_orgasms(entry: OrgTrackingEntry, orgasms: list) -> None:

    entry.orgasms.clear()

    for idx, detail in enumerate(orgasms):

        entry.orgasms.append(

            OrgTrackingOrgasm(

                tags=tags_to_string(detail.tags),

                position=idx,

            )

        )

@router.get("/{dynamic_id}/tracking/stats", response_model=OrgTrackingStatsOut)
def tracking_stats(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OrgTrackingStatsOut:
    get_membership(dynamic_id, user, db)
    memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    since_7 = today - timedelta(days=6)
    since_30 = today - timedelta(days=29)

    partners = []
    label_bits = []
    for membership in memberships:
        entries = (
            db.query(OrgTrackingEntry)
            .options(joinedload(OrgTrackingEntry.orgasms))
            .filter(
                OrgTrackingEntry.dynamic_id == dynamic_id,
                OrgTrackingEntry.for_membership_id == membership.id,
                OrgTrackingEntry.occurred_at >= since_7,
            )
            .all()
        )
        orgasm_count_total = sum(
            orgasm_count(entry) for entry in entries if is_orgasm_event(entry.event_type)
        )
        partners.append(
            {
                "membership_id": membership.id,
                "name": membership.display_name,
                "orgasm_count": orgasm_count_total,
            }
        )
        label_bits.append(f"{membership.display_name}: {orgasm_count_total}")

    if any(p["orgasm_count"] for p in partners):
        label = f"{' · '.join(label_bits)} (last 7 days)"
    else:
        label = "No orgasms in the last 7 days"

    # Preload 30-day entries once
    entries_30 = (
        db.query(OrgTrackingEntry)
        .options(joinedload(OrgTrackingEntry.orgasms))
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.occurred_at >= since_30,
            OrgTrackingEntry.occurred_at < today + timedelta(days=1),
        )
        .all()
    )
    running = {m.id: 0 for m in memberships}
    cumulative_30d = []
    for i in range(30):
        day = since_30 + timedelta(days=i)
        day_end = day + timedelta(days=1)
        for entry in entries_30:
            if not is_orgasm_event(entry.event_type):
                continue
            occurred = entry.occurred_at.replace(tzinfo=None) if getattr(entry.occurred_at, "tzinfo", None) else entry.occurred_at
            if day <= occurred < day_end and entry.for_membership_id in running:
                running[entry.for_membership_id] += orgasm_count(entry)
        cumulative_30d.append(
            {
                "date": day.date().isoformat(),
                "by_partner": {mid: running[mid] for mid in running},
            }
        )

    return OrgTrackingStatsOut(
        partners=partners,
        recent_orgasm_label=label,
        cumulative_30d=cumulative_30d,
    )


@router.get("/{dynamic_id}/tracking", response_model=list[OrgTrackingEntryOut])

def list_tracking_entries(

    dynamic_id: str,

    user: Annotated[User, Depends(get_current_user)],

    db: Annotated[Session, Depends(get_db)],

) -> list[OrgTrackingEntryOut]:

    membership = get_membership(dynamic_id, user, db)

    membership_map = _membership_map(db, dynamic_id)

    entries = (

        db.query(OrgTrackingEntry)

        .options(joinedload(OrgTrackingEntry.orgasms))

        .filter(OrgTrackingEntry.dynamic_id == dynamic_id)

        .order_by(OrgTrackingEntry.occurred_at.desc())

        .limit(200)

        .all()

    )

    return [_entry_out(entry, membership_map, viewer=membership) for entry in entries]


@router.get("/{dynamic_id}/tracking-prefs", response_model=OrgTrackingPrefsOut)
def get_tracking_prefs(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OrgTrackingPrefsOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    data = prefs_for_dynamic(dynamic)
    return OrgTrackingPrefsOut(fields=data["fields"], metrics=data["metrics"])


@router.put("/{dynamic_id}/tracking-prefs", response_model=OrgTrackingPrefsOut)
def update_tracking_prefs(
    dynamic_id: str,
    payload: OrgTrackingPrefsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OrgTrackingPrefsOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the dominant can change tracking preferences")
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    current = prefs_for_dynamic(dynamic)["raw"]
    for key, val in (payload.fields or {}).items():
        if key in current["fields"]:
            current["fields"][key] = bool(val)
    for key, val in (payload.metrics or {}).items():
        if key in current["metrics"]:
            current["metrics"][key] = bool(val)
    dynamic.org_tracking_prefs = serialize_org_tracking_prefs(current)
    db.commit()
    data = prefs_for_dynamic(dynamic)
    return OrgTrackingPrefsOut(fields=data["fields"], metrics=data["metrics"])


@router.get("/{dynamic_id}/tracking-calendar")
def tracking_events_calendar(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    range: Annotated[str, Query()] = "month",
    users: Annotated[str | None, Query(description="Comma-separated membership ids")] = None,
    types: Annotated[str | None, Query(description="chastity,orgasms,feelings")] = None,
) -> dict:
    """Unified Tracking hub calendar. Path avoids /tracking/{entry_id} collisions."""
    get_membership(dynamic_id, user, db)
    membership_ids = [x.strip() for x in (users or "").split(",") if x.strip()] or None
    event_types = [x.strip() for x in (types or "").split(",") if x.strip()] or None
    return build_tracking_calendar(
        db,
        dynamic_id,
        range_key=range,
        membership_ids=membership_ids,
        event_types=event_types,
    )


@router.post(

    "/{dynamic_id}/tracking",

    response_model=OrgTrackingEntryOut,

    status_code=status.HTTP_201_CREATED,

)

def log_tracking_entry(

    dynamic_id: str,

    payload: OrgTrackingEntryCreate,

    user: Annotated[User, Depends(get_current_user)],

    db: Annotated[Session, Depends(get_db)],

) -> OrgTrackingEntryOut:

    membership = get_membership(dynamic_id, user, db)

    target = (

        db.query(Membership)

        .filter(

            Membership.id == payload.for_membership_id,

            Membership.dynamic_id == dynamic_id,

        )

        .first()

    )

    if target is None:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid partner")

    if payload.event_type not in (OrgEventType.orgasm, OrgEventType.no_orgasm):

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="Use orgasm or no_orgasm event types.",

        )

    _validate_payload(payload.event_type, payload.orgasms)

    occurred_at = as_naive_utc(payload.occurred_at) or datetime.utcnow()
    ended_at = as_naive_utc(payload.ended_at)
    duration_minutes = payload.duration_minutes
    if duration_minutes is None and ended_at is not None:
        secs = (ended_at - occurred_at).total_seconds()
        if secs >= 0:
            duration_minutes = min(24 * 60, int(round(secs / 60)))

    entry = OrgTrackingEntry(

        dynamic_id=dynamic_id,

        logged_by_membership_id=membership.id,

        for_membership_id=target.id,

        event_type=payload.event_type,

        notes=payload.notes.strip(),

        tags=tags_to_string(payload.tags),

        occurred_at=occurred_at,

        ended_at=ended_at,

        duration_minutes=duration_minutes,

        dominant_time_at=None,

        submissive_time_at=None,

        location=(payload.location or "").strip()[:120],

        initiated_by_membership_id=payload.initiated_by_membership_id,

        protection=(payload.protection or "").strip()[:32],

        satisfaction=payload.satisfaction,

        edging_count=payload.edging_count,

        notes_private=bool(payload.notes_private),

    )

    if payload.orgasms:

        _apply_orgasms(entry, payload.orgasms)

    db.add(entry)

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is not None:
        status_info = feelings_status(db, dynamic_id, membership, dynamic)
        if status_info.get("hard_gate_active") and not has_recent_context_checkin(
            db, dynamic_id, membership.id, "before_play", within_hours=12
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Log feelings (before play) on the Feelings wheel first",
            )

    event_labels = {

        OrgEventType.orgasm: "orgasm",

        OrgEventType.no_orgasm: "play (no orgasm)",

    }

    label = event_labels.get(payload.event_type, str(payload.event_type))

    target_name = target.display_name

    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="orgasm_logged" if payload.event_type == OrgEventType.orgasm else "play_logged",
        text=f"logged {label} for {target_name}",
        path=f"/dynamic/{dynamic_id}/tracking",
        link_label="Open tracking",
        subject_membership_id=target.id,
    )

    _maybe_release_lockup_for_full_orgasm(
        db,
        dynamic_id=dynamic_id,
        membership=membership,
        target=target,
        entry=entry,
    )

    db.commit()

    db.refresh(entry)

    return _entry_out(entry, _membership_map(db, dynamic_id), viewer=membership)

@router.patch("/{dynamic_id}/tracking/{entry_id}", response_model=OrgTrackingEntryOut)

def update_tracking_entry(

    dynamic_id: str,

    entry_id: str,

    payload: OrgTrackingEntryUpdate,

    user: Annotated[User, Depends(get_current_user)],

    db: Annotated[Session, Depends(get_db)],

) -> OrgTrackingEntryOut:

    membership = get_membership(dynamic_id, user, db)

    entry = (

        db.query(OrgTrackingEntry)

        .options(joinedload(OrgTrackingEntry.orgasms))

        .filter(OrgTrackingEntry.id == entry_id, OrgTrackingEntry.dynamic_id == dynamic_id)

        .first()

    )

    if entry is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    if payload.event_type is not None:

        entry.event_type = payload.event_type

    if payload.notes is not None:

        entry.notes = payload.notes.strip()

    if payload.tags is not None:

        entry.tags = tags_to_string(payload.tags)

    if payload.occurred_at is not None:

        entry.occurred_at = as_naive_utc(payload.occurred_at)

    if "ended_at" in payload.model_fields_set:

        entry.ended_at = as_naive_utc(payload.ended_at)

    if payload.duration_minutes is not None:

        entry.duration_minutes = payload.duration_minutes

    if payload.dominant_time_at is not None:

        entry.dominant_time_at = as_naive_utc(payload.dominant_time_at)

    if payload.submissive_time_at is not None:

        entry.submissive_time_at = as_naive_utc(payload.submissive_time_at)

    if payload.location is not None:
        entry.location = payload.location.strip()[:120]
    if "initiated_by_membership_id" in payload.model_fields_set:
        entry.initiated_by_membership_id = payload.initiated_by_membership_id
    if payload.protection is not None:
        entry.protection = payload.protection.strip()[:32]
    if "satisfaction" in payload.model_fields_set:
        entry.satisfaction = payload.satisfaction
    if "edging_count" in payload.model_fields_set:
        entry.edging_count = payload.edging_count
    if payload.notes_private is not None:
        entry.notes_private = bool(payload.notes_private)

    if payload.orgasms is not None:

        _validate_payload(entry.event_type, payload.orgasms)

        _apply_orgasms(entry, payload.orgasms)

    db.commit()

    db.refresh(entry)

    return _entry_out(entry, _membership_map(db, dynamic_id), viewer=membership)

@router.delete("/{dynamic_id}/tracking/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)

def delete_tracking_entry(

    dynamic_id: str,

    entry_id: str,

    user: Annotated[User, Depends(get_current_user)],

    db: Annotated[Session, Depends(get_db)],

) -> None:

    get_membership(dynamic_id, user, db)

    entry = (

        db.query(OrgTrackingEntry)

        .filter(OrgTrackingEntry.id == entry_id, OrgTrackingEntry.dynamic_id == dynamic_id)

        .first()

    )

    if entry is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    db.delete(entry)

    db.commit()

