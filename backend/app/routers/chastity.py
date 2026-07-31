import csv
import io
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import (
    ChastityBreak,
    ChastityBreakType,
    ChastityEndedKind,
    ChastityLimitProposal,
    ChastityLockup,
    ChastityRecordType,
    Dynamic,
    LockupStatus,
    Membership,
    PartnerRole,
    ProposalStatus,
    User,
)
from ..schemas import (
    ChastityBreakCreate,
    ChastityBreakFinish,
    ChastityBreakOut,
    ChastityBreakUpdate,
    ChastityHistoricalCreate,
    ChastityLimitProposalCreate,
    ChastityLimitProposalOut,
    ChastityLockupEnd,
    ChastityLockupNoteUpdate,
    ChastityLockupOut,
    ChastityLockupStart,
    ChastityLockupUpdate,
    ChastityOverviewOut,
    ChastityPartnerOverview,
    ChastityPartnerStats,
    ChastityPolicyUpdate,
    ChastitySettingsOut,
    ChastityStatsOut,
    ChastitySubSetting,
    ChastitySubSettingUpdate,
    ChastityTimerExtend,
)
from ..services.tags import tags_to_list, tags_to_string
from ..services.chastity import (
    BREAK_TYPE_LABELS,
    EMERGENCY_BREAK_TYPES,
    MAX_LOCK_PRESETS,
    active_break,
    active_lockup,
    chastity_subs,
    effective_locked_seconds,
    is_dominant,
    partner_chastity_stats,
    partner_state,
    require_chastity_sub,
)
from ..services.tracking import format_duration, lockup_duration_seconds
from ..services.chat_events import post_system_event
from ..services.chastity_goals import (
    build_goals_progress,
    parse_goals,
    resolve_tracking_start,
    serialize_goals,
    _sub_memberships,
)

router = APIRouter(prefix="/dynamics", tags=["chastity"])


def _membership_map(db: Session, dynamic_id: str) -> dict[str, Membership]:
    return {
        m.id: m
        for m in db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    }


def _break_out(brk: ChastityBreak, memberships: dict[str, Membership]) -> ChastityBreakOut:
    creator = memberships.get(brk.created_by_membership_id)
    return ChastityBreakOut(
        id=brk.id,
        break_type=brk.break_type.value,
        break_reason=brk.break_reason,
        started_at=brk.started_at,
        ended_at=brk.ended_at,
        note=brk.note,
        tags=tags_to_list(getattr(brk, "tags", "") or ""),
        created_by_display_name=creator.display_name if creator else "Partner",
    )


def _timer_overdue(lockup: ChastityLockup, *, now: datetime | None = None) -> bool:
    when = now or datetime.utcnow()
    return bool(
        lockup.status == LockupStatus.active
        and lockup.planned_end_at
        and lockup.planned_end_at <= when
    )


def _lockup_out(lockup: ChastityLockup, memberships: dict[str, Membership]) -> ChastityLockupOut:
    for_member = memberships.get(lockup.for_membership_id)
    started_by = memberships.get(lockup.started_by_membership_id)
    ended_by = (
        memberships.get(lockup.ended_by_membership_id)
        if lockup.ended_by_membership_id
        else None
    )
    end = lockup.ended_at or datetime.utcnow()
    duration = format_duration(lockup_duration_seconds(lockup.started_at, end))
    locked_duration = format_duration(effective_locked_seconds(lockup, until=end))
    return ChastityLockupOut(
        id=lockup.id,
        for_membership_id=lockup.for_membership_id,
        for_display_name=for_member.display_name if for_member else "Partner",
        started_by_display_name=started_by.display_name if started_by else "Partner",
        ended_by_display_name=ended_by.display_name if ended_by else None,
        started_at=lockup.started_at,
        ended_at=lockup.ended_at,
        planned_end_at=lockup.planned_end_at,
        device_notes=lockup.device_notes,
        release_notes=lockup.release_notes,
        tags=tags_to_list(getattr(lockup, "tags", "") or ""),
        ended_kind=getattr(lockup, "ended_kind", "") or "",
        timer_overdue=_timer_overdue(lockup),
        record_type=lockup.record_type.value,
        status=lockup.status.value,
        duration_label=duration,
        locked_duration_label=locked_duration,
        breaks=[_break_out(brk, memberships) for brk in lockup.breaks],
    )


def _notify_timer_overdue_if_needed(db: Session, dynamic_id: str, lockup: ChastityLockup) -> None:
    """One-shot push to keyholders when planned_end_at has passed."""
    if not _timer_overdue(lockup):
        return
    if getattr(lockup, "timer_notified_at", None):
        return
    sub = db.get(Membership, lockup.for_membership_id)
    sub_name = sub.display_name if sub else "partner"
    from ..services.push import notify_keyholders_push

    notify_keyholders_push(
        db,
        dynamic_id=dynamic_id,
        title="Lock timer finished",
        body=f"{sub_name}'s planned lock time is up. Extend or confirm Released!",
        url=f"/#/dynamic/{dynamic_id}/chastity",
        tag=f"ubetra-chastity-timer-{lockup.id}",
    )
    lockup.timer_notified_at = datetime.utcnow()
    db.add(lockup)
    db.commit()


def _load_lockup(db: Session, dynamic_id: str, lockup_id: str) -> ChastityLockup:
    lockup = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.id == lockup_id,
            ChastityLockup.dynamic_id == dynamic_id,
        )
        .first()
    )
    if lockup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lockup not found")
    return lockup


def _parse_break_type(value: str) -> ChastityBreakType:
    try:
        return ChastityBreakType(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid break type") from exc


def _settings_out(db: Session, dynamic_id: str, membership: Membership) -> ChastitySettingsOut:
    memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    subs = [m for m in memberships if m.role == PartnerRole.submissive]
    dynamic = db.get(Dynamic, dynamic_id)
    return ChastitySettingsOut(
        max_lock_presets=MAX_LOCK_PRESETS,
        break_types=[{"id": key, "label": label} for key, label in BREAK_TYPE_LABELS.items()],
        emergency_break_types=[t.value for t in EMERGENCY_BREAK_TYPES],
        submissives=[
            ChastitySubSetting(
                membership_id=sub.id,
                display_name=sub.display_name,
                role=sub.role,
                chastity_enabled=sub.chastity_enabled,
                chastity_max_lock_hours=sub.chastity_max_lock_hours,
                enrollment_requested=bool(getattr(sub, "chastity_enrollment_requested", False)),
            )
            for sub in subs
        ],
        you_are_dominant=is_dominant(membership),
        you_membership_id=membership.id,
        can_disable_chastity=is_dominant(membership),
        can_enable_self=False,
        any_enabled=bool(chastity_subs(memberships)),
        sub_can_delete_breaks=bool(
            getattr(dynamic, "chastity_sub_can_delete_breaks", True) if dynamic else True
        ),
    )


def _summary_label(partners: list[ChastityPartnerOverview]) -> str:
    tracked = [p for p in partners if p.chastity_enabled]
    if not tracked:
        return "Chastity not enabled for any submissive"
    locked = next((p for p in tracked if p.state == "locked"), None)
    if locked:
        return f"{locked.name} locked for {locked.current_duration_label}"
    on_break = next((p for p in tracked if p.state == "on_break"), None)
    if on_break:
        return f"{on_break.name} on break for {on_break.break_duration_label}"
    free = next((p for p in tracked if p.free_duration_label), None)
    if free:
        return f"{free.name} free for {free.free_duration_label}"
    return "No lockup history yet"


@router.get("/{dynamic_id}/chastity/settings", response_model=ChastitySettingsOut)
def get_chastity_settings(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastitySettingsOut:
    membership = get_membership(dynamic_id, user, db)
    return _settings_out(db, dynamic_id, membership)


@router.put("/{dynamic_id}/chastity/settings", response_model=ChastitySettingsOut)
def update_chastity_settings(
    dynamic_id: str,
    payload: ChastitySubSettingUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastitySettingsOut:
    membership = get_membership(dynamic_id, user, db)
    target = (
        db.query(Membership)
        .filter(
            Membership.id == payload.membership_id,
            Membership.dynamic_id == dynamic_id,
        )
        .first()
    )
    if target is None or target.role != PartnerRole.submissive:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid submissive")

    dom = is_dominant(membership)
    self_update = membership.id == target.id

    if not dom and not self_update:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only change chastity settings for yourself.",
        )
    if not dom:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can enroll or change chastity settings. Submit an enrollment request from Ground rules.",
        )

    allowed_hours = {preset["hours"] for preset in MAX_LOCK_PRESETS}
    if payload.chastity_max_lock_hours not in allowed_hours:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid max lock time")

    if not payload.chastity_enabled and active_lockup(db, dynamic_id, target.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="End the active lockup before disabling chastity for this submissive.",
        )

    target.chastity_enabled = payload.chastity_enabled
    target.chastity_max_lock_hours = payload.chastity_max_lock_hours
    if payload.chastity_enabled:
        target.chastity_enrollment_requested = False
    db.commit()
    return _settings_out(db, dynamic_id, membership)


@router.post("/{dynamic_id}/chastity/enrollment-request", response_model=ChastitySettingsOut)
def request_chastity_enrollment(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastitySettingsOut:
    """Submissive requests chastity enrollment; keyholder must approve (or demand-enable)."""
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.submissive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a submissive can request chastity enrollment.",
        )
    if membership.chastity_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already enrolled")
    membership.chastity_enrollment_requested = True
    if membership.chastity_max_lock_hours is None:
        membership.chastity_max_lock_hours = 72
    post_system_event(
        db,
        dynamic_id,
        membership,
        "requested chastity enrollment",
    )
    db.commit()
    return _settings_out(db, dynamic_id, membership)


@router.post("/{dynamic_id}/chastity/enrollment-request/cancel", response_model=ChastitySettingsOut)
def cancel_chastity_enrollment_request(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastitySettingsOut:
    membership = get_membership(dynamic_id, user, db)
    if membership.role != PartnerRole.submissive:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a submissive can cancel their request.")
    membership.chastity_enrollment_requested = False
    db.commit()
    return _settings_out(db, dynamic_id, membership)


@router.post("/{dynamic_id}/chastity/enrollment-request/{membership_id}/decline", response_model=ChastitySettingsOut)
def decline_chastity_enrollment_request(
    dynamic_id: str,
    membership_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastitySettingsOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can decline enrollment.")
    target = (
        db.query(Membership)
        .filter(Membership.id == membership_id, Membership.dynamic_id == dynamic_id)
        .first()
    )
    if target is None or target.role != PartnerRole.submissive:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid submissive")
    target.chastity_enrollment_requested = False
    post_system_event(db, dynamic_id, membership, f"declined chastity enrollment for {target.display_name}")
    db.commit()
    return _settings_out(db, dynamic_id, membership)


@router.patch("/{dynamic_id}/chastity/policy", response_model=ChastitySettingsOut)
def update_chastity_policy(
    dynamic_id: str,
    payload: ChastityPolicyUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastitySettingsOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can change chastity policy.",
        )
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if payload.sub_can_delete_breaks is not None:
        dynamic.chastity_sub_can_delete_breaks = payload.sub_can_delete_breaks
        post_system_event(
            db,
            dynamic_id,
            membership,
            (
                "allowed temporary unlock log deletion by sub"
                if payload.sub_can_delete_breaks
                else "disallowed temporary unlock log deletion by sub"
            ),
        )
    db.commit()
    return _settings_out(db, dynamic_id, membership)


@router.get("/{dynamic_id}/chastity/overview", response_model=ChastityOverviewOut)
def chastity_overview(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityOverviewOut:
    get_membership(dynamic_id, user, db)
    memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    # Fire one-shot keyholder pushes for any overdue planned ends
    overdue = (
        db.query(ChastityLockup)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.status == LockupStatus.active,
            ChastityLockup.planned_end_at.isnot(None),
            ChastityLockup.planned_end_at <= datetime.utcnow(),
            ChastityLockup.timer_notified_at.is_(None),
        )
        .all()
    )
    for lockup in overdue:
        _notify_timer_overdue_if_needed(db, dynamic_id, lockup)
    partners = [ChastityPartnerOverview(**partner_state(db, dynamic_id, m)) for m in memberships]
    any_enabled = any(p.chastity_enabled for p in partners)
    return ChastityOverviewOut(
        partners=partners,
        any_enabled=any_enabled,
        summary_label=_summary_label(partners),
    )


@router.get("/{dynamic_id}/chastity-goals")
def get_chastity_goals(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    progress = build_goals_progress(db, dynamic)
    # Only keyholder sees live progress / countdown
    if not is_dominant(membership):
        return {
            "goals": [],
            "archived_goals": [],
            "active_count": 0,
            "archived_count": 0,
            "header_hidden": True,
            "requirement_catalog": progress["requirement_catalog"],
            "goal_kinds": progress["goal_kinds"],
            "start_modes": progress.get("start_modes", []),
            "archive_reasons": progress.get("archive_reasons", []),
            "soft_max_requirements": progress["soft_max_requirements"],
            "baselines": None,
            "you_are_dominant": False,
            "config": {"goals": [], "header_hidden": True},
        }
    progress["you_are_dominant"] = True
    return progress


@router.put("/{dynamic_id}/chastity-goals")
def put_chastity_goals(
    dynamic_id: str,
    payload: dict,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can edit goals")
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")

    raw = payload if isinstance(payload, dict) else {}
    data = parse_goals(json.dumps(raw))
    raw_goals = raw.get("goals") if isinstance(raw.get("goals"), list) else []
    resolve_flags = {
        str(g.get("id")): bool(g.get("resolve_reset"))
        for g in raw_goals
        if isinstance(g, dict) and g.get("id") is not None
    }
    now = datetime.utcnow().replace(microsecond=0)
    now_iso = now.isoformat() + "Z"
    subs = _sub_memberships(db, dynamic_id)
    default_sub = subs[0].id if len(subs) == 1 else None

    for goal in data["goals"]:
        if not goal.get("created_at"):
            goal["created_at"] = now_iso
        if not goal.get("active", True):
            if not goal.get("archived_at"):
                goal["archived_at"] = now_iso
        else:
            goal["archived_at"] = None
            goal["archive_reason"] = None
        needs_resolve = resolve_flags.get(str(goal["id"]), False) or not goal.get("reset_at")
        if needs_resolve:
            sub_id = goal.get("for_membership_id") or default_sub
            reset_at, _label = resolve_tracking_start(
                db,
                dynamic_id=dynamic_id,
                sub_id=sub_id,
                start_mode=goal.get("start_mode") or "rolling",
            )
            goal["reset_at"] = reset_at.isoformat() + "Z"

    dynamic.chastity_goals = serialize_goals(data)
    db.commit()
    progress = build_goals_progress(db, dynamic)
    progress["you_are_dominant"] = True
    return progress


@router.get("/{dynamic_id}/chastity/stats", response_model=ChastityStatsOut)
def chastity_stats(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityStatsOut:
    get_membership(dynamic_id, user, db)
    memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    partners = [
        ChastityPartnerStats(**partner_chastity_stats(db, dynamic_id, membership))
        for membership in memberships
        if membership.role == PartnerRole.submissive
    ]
    any_enabled = any(p.chastity_enabled for p in partners)
    overview_partners = [ChastityPartnerOverview(**partner_state(db, dynamic_id, m)) for m in memberships]
    return ChastityStatsOut(
        partners=partners,
        any_enabled=any_enabled,
        summary_label=_summary_label(overview_partners),
    )


@router.get("/{dynamic_id}/chastity", response_model=list[ChastityLockupOut])
def list_lockups(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChastityLockupOut]:
    get_membership(dynamic_id, user, db)
    from ..services.chastity_orgasm_repair import repair_missed_orgasm_releases

    repair_missed_orgasm_releases(db, dynamic_id)
    memberships = _membership_map(db, dynamic_id)
    enabled_sub_ids = {
        m.id for m in memberships.values() if m.role == PartnerRole.submissive and m.chastity_enabled
    }
    lockups = (
        db.query(ChastityLockup)
        .options(joinedload(ChastityLockup.breaks))
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.for_membership_id.in_(enabled_sub_ids or [""]),
        )
        .order_by(ChastityLockup.started_at.desc())
        .limit(100)
        .all()
    )
    if not enabled_sub_ids:
        return []
    return [_lockup_out(lockup, memberships) for lockup in lockups]


@router.post(
    "/{dynamic_id}/chastity/start",
    response_model=ChastityLockupOut,
    status_code=status.HTTP_201_CREATED,
)
def start_lockup(
    dynamic_id: str,
    payload: ChastityLockupStart,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
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
    require_chastity_sub(target)

    if not is_dominant(membership) and membership.id != target.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant or the locked submissive can start a lockup.",
        )

    if active_lockup(db, dynamic_id, target.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This submissive already has an active lockup. End it before starting another.",
        )

    from ..services.chastity import as_naive_utc, assert_no_lockup_overlap, validate_planned_end

    started_at = as_naive_utc(payload.started_at) or datetime.utcnow()
    planned_end_at = as_naive_utc(payload.planned_end_at)

    validate_planned_end(target, started_at, planned_end_at)
    assert_no_lockup_overlap(
        db,
        dynamic_id=dynamic_id,
        for_membership_id=target.id,
        started_at=started_at,
        ended_at=None,
    )

    lockup = ChastityLockup(
        dynamic_id=dynamic_id,
        for_membership_id=target.id,
        started_by_membership_id=membership.id,
        device_notes=payload.device_notes.strip(),
        started_at=started_at,
        planned_end_at=planned_end_at,
        status=LockupStatus.active,
        record_type=ChastityRecordType.normal,
        tags=tags_to_string(payload.tags),
    )
    db.add(lockup)
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"started chastity lockup for {target.display_name}",
    )
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.post(
    "/{dynamic_id}/chastity/historical",
    response_model=ChastityLockupOut,
    status_code=status.HTTP_201_CREATED,
)
def create_historical_lockup(
    dynamic_id: str,
    payload: ChastityHistoricalCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
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
    require_chastity_sub(target)

    from ..services.chastity import as_naive_utc, assert_no_lockup_overlap

    started_at = as_naive_utc(payload.started_at)
    ended_at = as_naive_utc(payload.ended_at)
    if started_at is None or ended_at is None or ended_at <= started_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="End must be after start")

    assert_no_lockup_overlap(
        db,
        dynamic_id=dynamic_id,
        for_membership_id=target.id,
        started_at=started_at,
        ended_at=ended_at,
    )

    lockup = ChastityLockup(
        dynamic_id=dynamic_id,
        for_membership_id=target.id,
        started_by_membership_id=membership.id,
        started_at=started_at,
        ended_at=ended_at,
        device_notes=payload.note.strip(),
        status=LockupStatus.ended,
        record_type=ChastityRecordType.historical,
        ended_kind=ChastityEndedKind.historical.value,
        tags=tags_to_string(payload.tags),
    )
    db.add(lockup)
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"logged past chastity lockup for {target.display_name}",
    )
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


HISTORICAL_CSV_HEADERS = ["submissive", "started_at", "ended_at", "note", "tags"]


def _historical_csv_template_body(example_name: str = "justjim") -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HISTORICAL_CSV_HEADERS)
    writer.writerow(
        [
            example_name,
            "2025-06-01T08:00:00",
            "2025-06-04T20:30:00",
            "Imported from previous app",
            "cage, overnight",
        ]
    )
    writer.writerow(
        [
            example_name,
            "2025-07-10 09:00",
            "2025-07-12 18:00",
            "Weekend lock",
            "",
        ]
    )
    writer.writerow(
        [
            example_name,
            "2025-08-01T22:00:00Z",
            "2025-08-08T22:00:00Z",
            "Week-long historical lock",
            "chaster",
        ]
    )
    return buf.getvalue()


def _parse_csv_datetime(raw: str) -> datetime:
    text = (raw or "").strip()
    if not text:
        raise ValueError("missing datetime")
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    raise ValueError(f"Unrecognized datetime: {raw}")


def _resolve_sub_for_csv(
    db: Session,
    dynamic_id: str,
    label: str,
    enrolled: list[Membership],
) -> Membership | None:
    key = (label or "").strip().lower()
    if not key:
        return enrolled[0] if len(enrolled) == 1 else None
    for m in enrolled:
        if m.display_name.lower() == key:
            return m
        user = db.get(User, m.user_id)
        if user and (user.username or "").lower() == key:
            return m
    return None


@router.get("/{dynamic_id}/chastity/historical/csv-template")
def download_historical_csv_template(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    get_membership(dynamic_id, user, db)
    subs = (
        db.query(Membership)
        .options(joinedload(Membership.user))
        .filter(
            Membership.dynamic_id == dynamic_id,
            Membership.role == PartnerRole.submissive,
            Membership.chastity_enabled.is_(True),
        )
        .all()
    )
    example = "justjim"
    if subs:
        example = (subs[0].user.username if subs[0].user else None) or subs[0].display_name
    body = _historical_csv_template_body(example)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ubetra-chastity-history-template.csv"'
        },
    )


@router.post("/{dynamic_id}/chastity/historical/import-csv")
async def import_historical_csv(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV must be UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty CSV")
    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    required = ["submissive", "started_at", "ended_at"]
    for key in required:
        if key not in headers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CSV must include columns: {', '.join(HISTORICAL_CSV_HEADERS)}",
            )

    enrolled = (
        db.query(Membership)
        .options(joinedload(Membership.user))
        .filter(
            Membership.dynamic_id == dynamic_id,
            Membership.role == PartnerRole.submissive,
            Membership.chastity_enabled.is_(True),
        )
        .all()
    )
    if not enrolled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enable chastity for a submissive before importing history.",
        )

    from ..services.chastity import as_naive_utc, assert_no_lockup_overlap

    created = 0
    errors: list[str] = []
    for idx, row in enumerate(reader, start=2):
        try:
            label = (row.get(headers["submissive"]) or "").strip()
            target = _resolve_sub_for_csv(db, dynamic_id, label, enrolled)
            if target is None:
                raise ValueError(f"Unknown submissive “{label}”")
            require_chastity_sub(target)
            started_at = as_naive_utc(_parse_csv_datetime(row.get(headers["started_at"]) or ""))
            ended_at = as_naive_utc(_parse_csv_datetime(row.get(headers["ended_at"]) or ""))
            if started_at is None or ended_at is None or ended_at <= started_at:
                raise ValueError("ended_at must be after started_at")
            note = (row.get(headers.get("note", "note")) or "").strip()[:500]
            tags_raw = (row.get(headers.get("tags", "tags")) or "").strip()
            tags = [t.strip() for t in tags_raw.replace(";", ",").split(",") if t.strip()]
            assert_no_lockup_overlap(
                db,
                dynamic_id=dynamic_id,
                for_membership_id=target.id,
                started_at=started_at,
                ended_at=ended_at,
            )
            db.add(
                ChastityLockup(
                    dynamic_id=dynamic_id,
                    for_membership_id=target.id,
                    started_by_membership_id=membership.id,
                    started_at=started_at,
                    ended_at=ended_at,
                    device_notes=note,
                    status=LockupStatus.ended,
                    record_type=ChastityRecordType.historical,
                    ended_kind=ChastityEndedKind.historical.value,
                    tags=tags_to_string(tags),
                )
            )
            created += 1
        except HTTPException as exc:
            errors.append(f"Row {idx}: {exc.detail}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Row {idx}: {exc}")

    if created:
        post_system_event(
            db,
            dynamic_id,
            membership,
            f"imported {created} past chastity lockup(s) from CSV",
        )
        db.commit()
    elif errors:
        db.rollback()

    return {
        "created": created,
        "error_count": len(errors),
        "errors": errors[:25],
    }


@router.patch("/{dynamic_id}/chastity/{lockup_id}/end", response_model=ChastityLockupOut)
def end_lockup(
    dynamic_id: str,
    lockup_id: str,
    payload: ChastityLockupEnd,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    membership = get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    if lockup.status != LockupStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lockup is already ended")

    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is not None:
        from ..services.feelings import feelings_status, has_recent_context_checkin

        status_info = feelings_status(db, dynamic_id, membership, dynamic)
        if status_info.get("hard_gate_active") and not has_recent_context_checkin(
            db, dynamic_id, membership.id, "after_play", within_hours=12
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Log feelings (after play) on the Feelings wheel before ending lockup",
            )

    brk = active_break(lockup)
    ended_at = payload.ended_at or datetime.utcnow()
    if brk and brk.ended_at is None:
        brk.ended_at = ended_at

    lockup.status = LockupStatus.ended
    lockup.ended_at = ended_at
    lockup.ended_by_membership_id = membership.id
    lockup.release_notes = payload.release_notes.strip()
    lockup.ended_kind = payload.ended_kind
    lockup.timer_notified_at = None
    if payload.tags is not None:
        existing = tags_to_list(getattr(lockup, "tags", "") or "")
        merged = list(dict.fromkeys([*existing, *payload.tags]))
        lockup.tags = tags_to_string(merged)
    sub = db.get(Membership, lockup.for_membership_id)
    sub_name = sub.display_name if sub else "partner"
    from ..services.chat_events import post_activity_event

    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="lockup_ended",
        text=f"ended chastity lockup for {sub_name}",
        path=f"/dynamic/{dynamic_id}/chastity",
        link_label="Open chastity",
        subject_membership_id=lockup.for_membership_id,
    )
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.delete("/{dynamic_id}/chastity/{lockup_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_lockup(
    dynamic_id: str,
    lockup_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    membership = get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    is_subject = membership.id == lockup.for_membership_id
    if not is_dominant(membership) and not is_subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to remove this lockup.",
        )

    from ..models import FeelingCheckIn
    from ..services.chat_events import post_activity_event

    subject_id = lockup.for_membership_id
    sub = db.get(Membership, subject_id)
    sub_name = sub.display_name if sub else "partner"
    started = lockup.started_at
    when = started.strftime("%Y-%m-%d %H:%M") if started else ""

    # Clear FKs that would block delete
    db.query(FeelingCheckIn).filter(FeelingCheckIn.chastity_lockup_id == lockup.id).update(
        {FeelingCheckIn.chastity_lockup_id: None},
        synchronize_session=False,
    )
    db.query(ChastityBreak).filter(ChastityBreak.lockup_id == lockup.id).delete(
        synchronize_session=False
    )
    db.delete(lockup)

    if not is_dominant(membership):
        post_activity_event(
            db,
            dynamic_id=dynamic_id,
            actor=membership,
            action="lockup_deleted",
            text=f"{sub_name} deleted a lockup period{f' · {when}' if when else ''}",
            path=f"/dynamic/{dynamic_id}/chastity",
            link_label="Open chastity",
            subject_membership_id=subject_id,
        )
    db.commit()


@router.patch("/{dynamic_id}/chastity/{lockup_id}/note", response_model=ChastityLockupOut)
def update_lockup_note(
    dynamic_id: str,
    lockup_id: str,
    payload: ChastityLockupNoteUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    lockup.device_notes = payload.note.strip()
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.post(
    "/{dynamic_id}/chastity/{lockup_id}/break",
    response_model=ChastityLockupOut,
    status_code=status.HTTP_201_CREATED,
)
def create_break(
    dynamic_id: str,
    lockup_id: str,
    payload: ChastityBreakCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    membership = get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    if lockup.status != LockupStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lockup is not active")
    if active_break(lockup):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A break is already active")

    break_type = _parse_break_type(payload.break_type)
    target = db.get(Membership, lockup.for_membership_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid partner")

    if break_type in EMERGENCY_BREAK_TYPES:
        if not is_dominant(membership) and membership.id != target.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to start this break")
    elif not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant can authorize a temporary unlock.",
        )

    reason = payload.break_reason.strip() or BREAK_TYPE_LABELS.get(break_type.value, break_type.value)
    started_at = payload.started_at or datetime.utcnow()
    from ..services.chastity import validate_break_times

    validate_break_times(lockup, started_at=started_at, ended_at=payload.ended_at)
    brk = ChastityBreak(
        lockup_id=lockup.id,
        break_type=break_type,
        break_reason=reason,
        started_at=started_at,
        ended_at=payload.ended_at,
        note=payload.note.strip(),
        tags=tags_to_string(payload.tags),
        created_by_membership_id=membership.id,
    )
    db.add(brk)
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"started chastity break ({reason}) for {target.display_name}",
    )
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.patch(
    "/{dynamic_id}/chastity/{lockup_id}/break/{break_id}/finish",
    response_model=ChastityLockupOut,
)
def finish_break(
    dynamic_id: str,
    lockup_id: str,
    break_id: str,
    payload: ChastityBreakFinish,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    membership = get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    brk = next((b for b in lockup.breaks if b.id == break_id), None)
    if brk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Break not found")
    if brk.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Break is already finished")

    target = db.get(Membership, lockup.for_membership_id)
    if not is_dominant(membership) and (target is None or membership.id != target.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to finish this break")

    brk.ended_at = payload.ended_at or datetime.utcnow()
    from ..services.chastity import validate_break_times

    validate_break_times(lockup, started_at=brk.started_at, ended_at=brk.ended_at)
    if payload.break_type == "full_release":
        lockup.status = LockupStatus.ended
        lockup.ended_at = brk.ended_at
        lockup.ended_by_membership_id = membership.id
        lockup.release_notes = payload.break_reason.strip() or "Full release"
        lockup.ended_kind = ChastityEndedKind.released_orgasm.value
        lockup.timer_notified_at = None
    elif payload.break_type:
        brk.break_type = _parse_break_type(payload.break_type)
        if payload.break_reason.strip():
            brk.break_reason = payload.break_reason.strip()
    sub_name = target.display_name if target else "partner"
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"finished chastity break for {sub_name}",
    )
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.patch("/{dynamic_id}/chastity/{lockup_id}", response_model=ChastityLockupOut)
def update_lockup(
    dynamic_id: str,
    lockup_id: str,
    payload: ChastityLockupUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    if lockup.status == LockupStatus.active and active_break(lockup):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finish the active break before editing this lockup.",
        )

    if payload.started_at is not None:
        lockup.started_at = payload.started_at
    if payload.clear_ended_at:
        lockup.ended_at = None
        lockup.status = LockupStatus.active
        lockup.ended_by_membership_id = None
        lockup.ended_kind = ""
    elif payload.ended_at is not None:
        lockup.ended_at = payload.ended_at
        if lockup.ended_at:
            lockup.status = LockupStatus.ended
            if not (getattr(lockup, "ended_kind", "") or ""):
                lockup.ended_kind = ChastityEndedKind.unlocked.value
    if payload.planned_end_at is not None:
        lockup.planned_end_at = payload.planned_end_at
        if lockup.planned_end_at and lockup.planned_end_at > datetime.utcnow():
            lockup.timer_notified_at = None
    if payload.device_notes is not None:
        lockup.device_notes = payload.device_notes.strip()
    if payload.release_notes is not None:
        lockup.release_notes = payload.release_notes.strip()
    if payload.tags is not None:
        lockup.tags = tags_to_string(payload.tags)
    if payload.ended_kind is not None:
        lockup.ended_kind = payload.ended_kind

    if lockup.ended_at and lockup.ended_at <= lockup.started_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="End must be after start")

    from ..services.chastity import assert_no_lockup_overlap

    assert_no_lockup_overlap(
        db,
        dynamic_id=dynamic_id,
        for_membership_id=lockup.for_membership_id,
        started_at=lockup.started_at,
        ended_at=lockup.ended_at,
        exclude_id=lockup.id,
    )

    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.patch(
    "/{dynamic_id}/chastity/{lockup_id}/timer/extend",
    response_model=ChastityLockupOut,
)
def extend_lock_timer(
    dynamic_id: str,
    lockup_id: str,
    payload: ChastityTimerExtend,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can extend the lock timer.",
        )
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    if lockup.status != LockupStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lockup is not active")
    now = datetime.utcnow()
    base = lockup.planned_end_at or now
    if base < now:
        base = now
    from datetime import timedelta

    lockup.planned_end_at = base + timedelta(hours=payload.hours)
    lockup.timer_notified_at = None
    sub = db.get(Membership, lockup.for_membership_id)
    sub_name = sub.display_name if sub else "partner"
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"extended chastity lock timer for {sub_name} by {payload.hours}h",
    )
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.patch(
    "/{dynamic_id}/chastity/{lockup_id}/timer/release",
    response_model=ChastityLockupOut,
)
def confirm_timer_release(
    dynamic_id: str,
    lockup_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can confirm a timer release.",
        )
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    if lockup.status != LockupStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lockup is not active")
    if not lockup.planned_end_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No planned end timer set")
    ended_at = datetime.utcnow()
    lockup.status = LockupStatus.ended
    lockup.ended_at = ended_at
    lockup.ended_by_membership_id = membership.id
    lockup.ended_kind = ChastityEndedKind.released_timer.value
    lockup.timer_notified_at = None
    brk = active_break(lockup)
    if brk and brk.ended_at is None:
        brk.ended_at = ended_at
    if not (lockup.release_notes or "").strip():
        lockup.release_notes = "Released when lock timer completed"
    sub = db.get(Membership, lockup.for_membership_id)
    sub_name = sub.display_name if sub else "partner"
    from ..services.chat_events import post_activity_event

    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="lockup_ended",
        text=f"confirmed timer release for {sub_name}",
        path=f"/dynamic/{dynamic_id}/chastity",
        link_label="Open chastity",
        subject_membership_id=lockup.for_membership_id,
    )
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


@router.delete(
    "/{dynamic_id}/chastity/{lockup_id}/break/{break_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_break(
    dynamic_id: str,
    lockup_id: str,
    break_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    membership = get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    brk = next((b for b in lockup.breaks if b.id == break_id), None)
    if brk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Break not found")
    dynamic = db.get(Dynamic, dynamic_id)
    allow_sub = bool(getattr(dynamic, "chastity_sub_can_delete_breaks", True)) if dynamic else True
    is_subject = membership.id == lockup.for_membership_id
    if not is_dominant(membership):
        if not is_subject:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to delete this unlock entry.",
            )
        if not allow_sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Keyholder has disallowed deleting temporary unlock logs.",
            )

    reason = (brk.break_reason or "temporary unlock").strip()
    started = brk.started_at
    db.delete(brk)
    if not is_dominant(membership):
        from ..services.chat_events import post_activity_event

        sub = db.get(Membership, lockup.for_membership_id)
        sub_name = sub.display_name if sub else "partner"
        when = started.strftime("%Y-%m-%d %H:%M") if started else ""
        post_activity_event(
            db,
            dynamic_id=dynamic_id,
            actor=membership,
            action="temp_unlock_deleted",
            text=f"{sub_name} deleted a temporary unlock log ({reason}{f' · {when}' if when else ''})",
            path=f"/dynamic/{dynamic_id}/chastity",
            link_label="Open chastity",
            subject_membership_id=lockup.for_membership_id,
        )
    db.commit()


@router.patch(
    "/{dynamic_id}/chastity/{lockup_id}/break/{break_id}",
    response_model=ChastityLockupOut,
)
def update_break(
    dynamic_id: str,
    lockup_id: str,
    break_id: str,
    payload: ChastityBreakUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLockupOut:
    membership = get_membership(dynamic_id, user, db)
    lockup = _load_lockup(db, dynamic_id, lockup_id)
    brk = next((b for b in lockup.breaks if b.id == break_id), None)
    if brk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Break not found")

    target = db.get(Membership, lockup.for_membership_id)
    if not is_dominant(membership) and (target is None or membership.id != target.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to edit this unlock")

    if payload.started_at is not None:
        brk.started_at = payload.started_at
    if payload.clear_ended_at:
        brk.ended_at = None
    elif payload.ended_at is not None:
        brk.ended_at = payload.ended_at
    if payload.note is not None:
        brk.note = payload.note.strip()
    if payload.break_reason is not None:
        brk.break_reason = payload.break_reason.strip()
    if payload.break_type is not None:
        brk.break_type = _parse_break_type(payload.break_type)
    if payload.tags is not None:
        brk.tags = tags_to_string(payload.tags)

    from ..services.chastity import validate_break_times

    validate_break_times(lockup, started_at=brk.started_at, ended_at=brk.ended_at)
    db.commit()
    lockup = _load_lockup(db, dynamic_id, lockup.id)
    return _lockup_out(lockup, _membership_map(db, dynamic_id))


def _proposal_out(proposal: ChastityLimitProposal, memberships: dict[str, Membership]) -> ChastityLimitProposalOut:
    for_member = memberships.get(proposal.for_membership_id)
    proposer = memberships.get(proposal.proposed_by_membership_id)
    return ChastityLimitProposalOut(
        id=proposal.id,
        for_display_name=for_member.display_name if for_member else "Partner",
        proposed_max_hours=proposal.proposed_max_hours,
        rationale=proposal.rationale,
        status=proposal.status.value,
        proposed_by_display_name=proposer.display_name if proposer else "Partner",
        created_at=proposal.created_at,
        reviewed_at=proposal.reviewed_at,
    )


@router.get("/{dynamic_id}/chastity/limit-proposals", response_model=list[ChastityLimitProposalOut])
def list_limit_proposals(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChastityLimitProposalOut]:
    get_membership(dynamic_id, user, db)
    memberships = _membership_map(db, dynamic_id)
    proposals = (
        db.query(ChastityLimitProposal)
        .filter(ChastityLimitProposal.dynamic_id == dynamic_id)
        .order_by(ChastityLimitProposal.created_at.desc())
        .limit(50)
        .all()
    )
    return [_proposal_out(p, memberships) for p in proposals]


@router.post(
    "/{dynamic_id}/chastity/limit-proposals",
    response_model=ChastityLimitProposalOut,
    status_code=status.HTTP_201_CREATED,
)
def create_limit_proposal(
    dynamic_id: str,
    payload: ChastityLimitProposalCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLimitProposalOut:
    membership = get_membership(dynamic_id, user, db)
    target = (
        db.query(Membership)
        .filter(
            Membership.id == payload.for_membership_id,
            Membership.dynamic_id == dynamic_id,
        )
        .first()
    )
    if target is None or target.role != PartnerRole.submissive:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid submissive")

    if not is_dominant(membership) and membership.id != target.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only propose limits for yourself.",
        )

    allowed_hours = {preset["hours"] for preset in MAX_LOCK_PRESETS if preset["hours"] is not None}
    if payload.proposed_max_hours not in allowed_hours:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid max lock time")

    pending = (
        db.query(ChastityLimitProposal)
        .filter(
            ChastityLimitProposal.dynamic_id == dynamic_id,
            ChastityLimitProposal.for_membership_id == target.id,
            ChastityLimitProposal.status == ProposalStatus.pending,
        )
        .first()
    )
    if pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A limit proposal is already pending for this submissive.",
        )

    proposal = ChastityLimitProposal(
        dynamic_id=dynamic_id,
        for_membership_id=target.id,
        proposed_max_hours=payload.proposed_max_hours,
        rationale=payload.rationale.strip(),
        proposed_by_membership_id=membership.id,
    )
    db.add(proposal)
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"proposed chastity max lock time ({payload.proposed_max_hours}h) for {target.display_name}",
    )
    db.commit()
    db.refresh(proposal)
    return _proposal_out(proposal, _membership_map(db, dynamic_id))


@router.post(
    "/{dynamic_id}/chastity/limit-proposals/{proposal_id}/approve",
    response_model=ChastityLimitProposalOut,
)
def approve_limit_proposal(
    dynamic_id: str,
    proposal_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLimitProposalOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant can approve limit proposals.",
        )
    proposal = (
        db.query(ChastityLimitProposal)
        .filter(
            ChastityLimitProposal.id == proposal_id,
            ChastityLimitProposal.dynamic_id == dynamic_id,
        )
        .first()
    )
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if proposal.status != ProposalStatus.pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposal is not pending")

    target = db.get(Membership, proposal.for_membership_id)
    if target:
        target.chastity_max_lock_hours = proposal.proposed_max_hours
    proposal.status = ProposalStatus.approved
    proposal.reviewed_by_membership_id = membership.id
    proposal.reviewed_at = datetime.utcnow()
    sub_name = target.display_name if target else "partner"
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"approved chastity max lock time ({proposal.proposed_max_hours}h) for {sub_name}",
    )
    db.commit()
    db.refresh(proposal)
    return _proposal_out(proposal, _membership_map(db, dynamic_id))


@router.post(
    "/{dynamic_id}/chastity/limit-proposals/{proposal_id}/reject",
    response_model=ChastityLimitProposalOut,
)
def reject_limit_proposal(
    dynamic_id: str,
    proposal_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChastityLimitProposalOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the dominant can reject limit proposals.",
        )
    proposal = (
        db.query(ChastityLimitProposal)
        .filter(
            ChastityLimitProposal.id == proposal_id,
            ChastityLimitProposal.dynamic_id == dynamic_id,
        )
        .first()
    )
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if proposal.status != ProposalStatus.pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposal is not pending")

    proposal.status = ProposalStatus.rejected
    proposal.reviewed_by_membership_id = membership.id
    proposal.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(proposal)
    return _proposal_out(proposal, _membership_map(db, dynamic_id))
