from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import CycleLog, Dynamic, Membership, User
from ..services.features import is_feature_enabled
from ..services.sleep_sync import (
    build_google_sleep_auth_url,
    google_fitness_configured,
    import_cycle_days,
    sync_google_cycle,
)
from .sleep import sleep_history_window

router = APIRouter(prefix="/dynamics", tags=["cycle"])

BLEEDING = {"spotting", "light", "medium", "heavy"}
FLOW_VALUES = {"none", "spotting", "light", "medium", "heavy"}


class CycleDayIn(BaseModel):
    day: str = Field(min_length=10, max_length=10)
    flow: str = "none"
    symptoms: list[str] = Field(default_factory=list)
    notes: str = ""


class CycleLogOut(BaseModel):
    id: str
    day: str
    flow: str
    symptoms: list[str] = []
    notes: str = ""
    source: str
    is_yours: bool

    class Config:
        from_attributes = True


class CycleSummaryOut(BaseModel):
    last_period_start: str = ""
    cycle_day: int | None = None
    typical_length: int = 28
    predicted_next: str = ""
    on_period: bool = False
    logged_days: int = 0


class CyclePersonOut(BaseModel):
    membership_id: str
    display_name: str
    is_you: bool
    logs: list[CycleLogOut]
    summary: CycleSummaryOut


class CycleStatusOut(BaseModel):
    feature_enabled: bool
    google_configured: bool
    google_connected: bool
    google_cycle_scope: bool = False
    history_since: str = ""
    history_days: int = 30
    people: list[CyclePersonOut]


class CycleSyncOut(BaseModel):
    imported: int
    source: str = "google"


class CycleImportIn(BaseModel):
    days: list[dict] = Field(default_factory=list)


def _require_cycle(dynamic: Dynamic) -> None:
    if not is_feature_enabled(dynamic, "cycle_tracking"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cycle tracking is not enabled for this dynamic.",
        )


def _parse_day(value: str) -> str:
    try:
        return date.fromisoformat((value or "").strip()[:10]).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD") from exc


def _log_out(row: CycleLog, viewer_id: str) -> CycleLogOut:
    try:
        symptoms = json.loads(row.symptoms_json or "[]")
        if not isinstance(symptoms, list):
            symptoms = []
    except json.JSONDecodeError:
        symptoms = []
    return CycleLogOut(
        id=row.id,
        day=row.day,
        flow=row.flow or "none",
        symptoms=[str(item) for item in symptoms],
        notes=row.notes or "",
        source=row.source or "manual",
        is_yours=row.subject_membership_id == viewer_id,
    )


def summarize_cycle(logs: list[CycleLog]) -> CycleSummaryOut:
    days = sorted(logs, key=lambda row: row.day)
    starts: list[str] = []
    prev_bleed = False
    for row in days:
        is_bleed = (row.flow or "none") in BLEEDING
        if is_bleed and not prev_bleed:
            starts.append(row.day)
        prev_bleed = is_bleed
    lengths: list[int] = []
    for idx in range(1, len(starts)):
        a = date.fromisoformat(starts[idx - 1])
        b = date.fromisoformat(starts[idx])
        gap = (b - a).days
        if 15 <= gap <= 60:
            lengths.append(gap)
    typical = round(sum(lengths[-6:]) / len(lengths[-6:])) if lengths else 28
    last = starts[-1] if starts else ""
    cycle_day = None
    predicted = ""
    on_period = False
    today = date.today()
    if last:
        last_d = date.fromisoformat(last)
        cycle_day = (today - last_d).days + 1
        predicted = (last_d + timedelta(days=typical)).isoformat()
        last_bleed = max((row.day for row in days if (row.flow or "") in BLEEDING), default="")
        if last_bleed:
            gap = (today - date.fromisoformat(last_bleed)).days
            on_period = gap <= 1 and cycle_day <= 10
    return CycleSummaryOut(
        last_period_start=last,
        cycle_day=cycle_day if cycle_day and cycle_day > 0 else None,
        typical_length=typical,
        predicted_next=predicted,
        on_period=on_period,
        logged_days=len(days),
    )


def _person_out(membership: Membership, logs: list[CycleLog], viewer_id: str) -> CyclePersonOut:
    mine = [row for row in logs if row.subject_membership_id == membership.id]
    return CyclePersonOut(
        membership_id=membership.id,
        display_name=membership.display_name,
        is_you=membership.id == viewer_id,
        logs=[_log_out(row, viewer_id) for row in sorted(mine, key=lambda r: r.day, reverse=True)[:90]],
        summary=summarize_cycle(mine),
    )


@router.get("/{dynamic_id}/cycle", response_model=CycleStatusOut)
def get_cycle(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CycleStatusOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    enabled = is_feature_enabled(dynamic, "cycle_tracking")
    scopes = user.google_fitness_scopes or ""
    google_connected = bool((user.google_refresh_token or "").strip()) and bool(scopes.strip())
    google_cycle_scope = "reproductive_health" in scopes
    history_since, history_days = sleep_history_window(db, dynamic_id)
    if not enabled:
        return CycleStatusOut(
            feature_enabled=False,
            google_configured=google_fitness_configured(),
            google_connected=google_connected,
            google_cycle_scope=google_cycle_scope,
            history_since=history_since,
            history_days=history_days,
            people=[],
        )
    members = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    logs = (
        db.query(CycleLog)
        .filter(CycleLog.dynamic_id == dynamic_id)
        .order_by(CycleLog.day.desc())
        .all()
    )
    people = [_person_out(member, logs, membership.id) for member in members]
    people.sort(key=lambda person: (not person.is_you, person.display_name.lower()))
    return CycleStatusOut(
        feature_enabled=True,
        google_configured=google_fitness_configured(),
        google_connected=google_connected,
        google_cycle_scope=google_cycle_scope,
        history_since=history_since,
        history_days=history_days,
        people=people,
    )


@router.put("/{dynamic_id}/cycle/day", response_model=CycleLogOut)
def upsert_cycle_day(
    dynamic_id: str,
    payload: CycleDayIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CycleLogOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_cycle(dynamic)
    day = _parse_day(payload.day)
    flow = (payload.flow or "none").strip().lower()
    if flow not in FLOW_VALUES:
        raise HTTPException(status_code=400, detail="Invalid flow value")
    symptoms = [str(item).strip()[:40] for item in (payload.symptoms or []) if str(item).strip()][:12]
    notes = (payload.notes or "").strip()[:1000]
    row = (
        db.query(CycleLog)
        .filter(
            CycleLog.dynamic_id == dynamic_id,
            CycleLog.subject_membership_id == membership.id,
            CycleLog.day == day,
        )
        .first()
    )
    if row is None:
        row = CycleLog(
            dynamic_id=dynamic_id,
            subject_membership_id=membership.id,
            day=day,
            flow=flow,
            symptoms_json=json.dumps(symptoms),
            notes=notes,
            source="manual",
        )
        db.add(row)
    else:
        row.flow = flow
        row.symptoms_json = json.dumps(symptoms)
        row.notes = notes
        row.source = "manual"
        row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _log_out(row, membership.id)


@router.delete("/{dynamic_id}/cycle/day/{day}")
def delete_cycle_day(
    dynamic_id: str,
    day: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_cycle(dynamic)
    parsed = _parse_day(day)
    row = (
        db.query(CycleLog)
        .filter(
            CycleLog.dynamic_id == dynamic_id,
            CycleLog.subject_membership_id == membership.id,
            CycleLog.day == parsed,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/{dynamic_id}/cycle/google/connect")
def google_cycle_connect(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    get_membership(dynamic_id, user, db)
    return {"auth_url": build_google_sleep_auth_url(user_id=user.id, dynamic_id=dynamic_id, next_page="cycle")}


@router.post("/{dynamic_id}/cycle/google/sync", response_model=CycleSyncOut)
def google_cycle_sync(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CycleSyncOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_cycle(dynamic)
    imported = sync_google_cycle(db, user=user, membership=membership, dynamic_id=dynamic_id)
    db.commit()
    return CycleSyncOut(imported=imported)


@router.post("/{dynamic_id}/cycle/healthconnect/import", response_model=CycleSyncOut)
def healthconnect_cycle_import(
    dynamic_id: str,
    payload: CycleImportIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CycleSyncOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    _require_cycle(dynamic)
    imported = import_cycle_days(
        db,
        membership=membership,
        dynamic_id=dynamic_id,
        days=payload.days,
        source="healthconnect",
    )
    db.commit()
    return CycleSyncOut(imported=imported, source="healthconnect")
