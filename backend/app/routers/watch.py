"""Wear OS HTTP routes.

The phone relay is the primary watch path: the watch talks only to the phone
over an encrypted Wear Data Layer channel and does not call these routes.
They remain for older watch builds that still claim a device token.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import User
from ..services.watch import (
    build_watch_summary,
    claim_pair_code,
    issue_pair_code,
    list_watch_devices,
    refresh_watch_token,
    revoke_watch_device,
)

router = APIRouter(prefix="/devices/watch", tags=["watch"])
summary_router = APIRouter(prefix="/dynamics", tags=["watch"])


class WatchPairCodeIn(BaseModel):
    api_base: str = ""


class WatchPairCodeOut(BaseModel):
    code: str
    expires_at: datetime
    expires_in: int
    api_base: str


class WatchClaimIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    label: str = Field(default="", max_length=64)


class WatchTokenOut(BaseModel):
    device_id: str
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    api_base: str


class WatchRefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class WatchRevokeIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=36)


class WatchDeviceOut(BaseModel):
    id: str
    label: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked: bool = False


class WatchActionOut(BaseModel):
    id: str
    label: str
    method: str
    path: str
    for_membership_id: str | None = None
    subject_name: str = ""
    finish_on_phone: bool = False
    body: dict | None = None


class WatchChastitySubjectOut(BaseModel):
    membership_id: str
    name: str
    chastity_enabled: bool
    state: str
    duration_label: str | None = None
    timer_overdue: bool = False
    planned_end_visible: bool = False
    planned_end_at: datetime | None = None
    active_lockup_id: str | None = None
    active_break_id: str | None = None
    break_label: str | None = None


class WatchChastityOut(BaseModel):
    enabled: bool
    summary_label: str
    subjects: list[WatchChastitySubjectOut]


class WatchSleepNightOut(BaseModel):
    membership_id: str
    name: str
    is_you: bool
    night_date: str | None = None
    duration_min: int | None = None
    duration_label: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class WatchSleepOut(BaseModel):
    enabled: bool
    nights: list[WatchSleepNightOut]


class WatchCyclePersonOut(BaseModel):
    membership_id: str
    name: str
    is_you: bool
    cycle_day: int | None = None
    on_period: bool = False
    last_period_start: str = ""
    predicted_next: str = ""
    typical_length: int = 28
    period_length: int = 5
    today_flow: str = ""


class WatchCycleOut(BaseModel):
    enabled: bool
    people: list[WatchCyclePersonOut]


class WatchOrgasmPartnerOut(BaseModel):
    membership_id: str
    name: str
    count_7d: int


class WatchOrgasmOut(BaseModel):
    enabled: bool
    recent_orgasm_label: str
    partners: list[WatchOrgasmPartnerOut]


class WatchSummaryOut(BaseModel):
    dynamic_id: str
    role: str
    you_membership_id: str
    display_name: str
    chastity: WatchChastityOut
    sleep: WatchSleepOut
    cycle: WatchCycleOut
    orgasm: WatchOrgasmOut
    allowed_actions: list[WatchActionOut]
    generated_at: datetime


@router.post("/pair-code", response_model=WatchPairCodeOut)
def create_watch_pair_code(
    payload: WatchPairCodeIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WatchPairCodeOut:
    """Signed-in phone requests a short code. api_base is a hint the client may fill."""
    return WatchPairCodeOut(**issue_pair_code(db, user, payload.api_base))


@router.post("/claim", response_model=WatchTokenOut)
def claim_watch(
    payload: WatchClaimIn,
    db: Annotated[Session, Depends(get_db)],
) -> WatchTokenOut:
    """Unauthenticated watch exchanges a pairing code for a device token pair."""
    return WatchTokenOut(**claim_pair_code(db, payload.code, payload.label))


@router.post("/refresh", response_model=WatchTokenOut)
def refresh_watch(
    payload: WatchRefreshIn,
    db: Annotated[Session, Depends(get_db)],
) -> WatchTokenOut:
    """Rotate the device refresh token and issue a new watch access JWT."""
    return WatchTokenOut(**refresh_watch_token(db, payload.refresh_token))


@router.post("/revoke", response_model=WatchDeviceOut)
def revoke_watch(
    payload: WatchRevokeIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WatchDeviceOut:
    return WatchDeviceOut(**revoke_watch_device(db, user, payload.device_id))


@router.get("", response_model=list[WatchDeviceOut])
def get_watch_devices(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WatchDeviceOut]:
    return [WatchDeviceOut(**row) for row in list_watch_devices(db, user)]


@summary_router.get("/{dynamic_id}/watch/summary", response_model=WatchSummaryOut)
def watch_summary(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WatchSummaryOut:
    """Role-aware glance for the signed-in member. Phone JWTs and watch JWTs both work."""
    membership = get_membership(dynamic_id, user, db)
    return WatchSummaryOut(**build_watch_summary(db, dynamic_id, membership))
