from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, Membership, User
from ..routers.chastity import _lockup_out
from ..schemas import (
    HistoryChastityDaysOut,
    HistoryChastityStatsOut,
    HistoryDashboardOut,
    HistoryOrgasmReportOut,
    HistorySessionsReportOut,
    HistorySessionOut,
    HistoryWeeklyOut,
)
from ..services.chastity import is_dominant
from ..services.entry_enrichment import build_sessions_payload, enrich_tracking_entries
from ..services.lockup_at_time import load_lockups_for_dynamic
from ..services.history_dashboard import build_history_dashboard
from ..services.history_reports import (
    build_chastity_days_report,
    build_chastity_stats_report,
    build_orgasm_report,
)

router = APIRouter(prefix="/dynamics", tags=["history"])


def _memberships(db: Session, dynamic_id: str) -> list[Membership]:
    return db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()


def _parse_tags(tags: str) -> list[str]:
    return [part.strip().lower() for part in tags.split(",") if part.strip()]


@router.get("/{dynamic_id}/history-dashboard", response_model=HistoryDashboardOut)
def history_dashboard(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(default=90, ge=7, le=3650),
    tags: str = Query(default=""),
) -> HistoryDashboardOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    memberships = _memberships(db, dynamic_id)
    selected_tags = _parse_tags(tags)
    payload = build_history_dashboard(
        db, dynamic_id, memberships, days=days, selected_tags=selected_tags
    )
    membership_map = payload["membership_map"]
    lockups = load_lockups_for_dynamic(db, dynamic_id)
    enriched, entry_session_map, _ = enrich_tracking_entries(
        payload["org_entries"], membership_map, lockups
    )
    return HistoryDashboardOut(
        dynamic_id=dynamic_id,
        dynamic_name=dynamic.name if dynamic else "Dynamic",
        days=payload["days"],
        selected_tags=payload["selected_tags"],
        available_tags=payload["available_tags"],
        partners=payload["partners"],
        comparison_label=payload["comparison_label"],
        weekly_buckets=payload["weekly_buckets"],
        org_entries=enriched,
        chastity_lockups=[_lockup_out(lockup, membership_map) for lockup in payload["chastity_lockups"]],
        chastity_any_enabled=payload["chastity_any_enabled"],
        you_are_dominant=is_dominant(membership),
    )


@router.get("/{dynamic_id}/history/reports/weekly", response_model=HistoryWeeklyOut)
def history_weekly_report(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(default=90, ge=7, le=3650),
    tags: str = Query(default=""),
) -> HistoryWeeklyOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    memberships = _memberships(db, dynamic_id)
    payload = build_history_dashboard(
        db, dynamic_id, memberships, days=days, selected_tags=_parse_tags(tags)
    )
    return HistoryWeeklyOut(
        dynamic_name=dynamic.name if dynamic else "Dynamic",
        days=payload["days"],
        comparison_label=payload["comparison_label"],
        partners=payload["partners"],
        weekly_buckets=payload["weekly_buckets"],
        chastity_any_enabled=payload["chastity_any_enabled"],
    )


@router.get("/{dynamic_id}/history/reports/chastity-days", response_model=HistoryChastityDaysOut)
def history_chastity_days_report(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    year: int | None = Query(default=None, ge=2020, le=2100),
) -> HistoryChastityDaysOut:
    get_membership(dynamic_id, user, db)
    y = year or datetime.utcnow().year
    payload = build_chastity_days_report(db, dynamic_id, _memberships(db, dynamic_id), year=y)
    return HistoryChastityDaysOut(**payload)


@router.get("/{dynamic_id}/history/reports/orgasms", response_model=HistoryOrgasmReportOut)
def history_orgasm_report(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    year: int | None = Query(default=None, ge=2020, le=2100),
    tags: str = Query(default=""),
) -> HistoryOrgasmReportOut:
    get_membership(dynamic_id, user, db)
    y = year or datetime.utcnow().year
    payload = build_orgasm_report(
        db,
        dynamic_id,
        _memberships(db, dynamic_id),
        year=y,
        selected_tags=_parse_tags(tags),
    )
    return HistoryOrgasmReportOut(**payload)


@router.get("/{dynamic_id}/history/reports/chastity-stats", response_model=HistoryChastityStatsOut)
def history_chastity_stats_report(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    year: int | None = Query(default=None, ge=2020, le=2100),
) -> HistoryChastityStatsOut:
    get_membership(dynamic_id, user, db)
    y = year or datetime.utcnow().year
    payload = build_chastity_stats_report(db, dynamic_id, _memberships(db, dynamic_id), year=y)
    return HistoryChastityStatsOut(**payload)


@router.get("/{dynamic_id}/history/reports/sessions", response_model=HistorySessionsReportOut)
def history_sessions_report(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(default=90, ge=7, le=3650),
    tags: str = Query(default=""),
) -> HistorySessionsReportOut:
    get_membership(dynamic_id, user, db)
    memberships = _memberships(db, dynamic_id)
    membership_map = {m.id: m for m in memberships}
    payload = build_history_dashboard(
        db, dynamic_id, memberships, days=days, selected_tags=_parse_tags(tags)
    )
    lockups = load_lockups_for_dynamic(db, dynamic_id)
    sessions_meta, entry_session_map = build_sessions_payload(
        payload["org_entries"], membership_map, lockups
    )
    enriched, _, _ = enrich_tracking_entries(
        payload["org_entries"], membership_map, lockups
    )
    enriched_by_id = {e.id: e for e in enriched}
    sessions = []
    for meta in sessions_meta:
        session_entries = [enriched_by_id[eid] for eid in meta["entry_ids"] if eid in enriched_by_id]
        sessions.append(
            HistorySessionOut(
                **{k: meta[k] for k in (
                    "session_id", "started_at", "ended_at", "entry_ids",
                    "entry_count", "during_lockup", "locked_partner_names", "orgasm_count",
                )},
                entries=session_entries,
            )
        )
    return HistorySessionsReportOut(
        days=payload["days"],
        sessions=sessions,
        entry_session_map=entry_session_map,
    )


@router.get("/{dynamic_id}/history/reports/org-log", response_model=HistoryDashboardOut)
def history_org_log(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(default=90, ge=7, le=3650),
    tags: str = Query(default=""),
) -> HistoryDashboardOut:
    return history_dashboard(dynamic_id, user, db, days=days, tags=tags)


@router.get("/{dynamic_id}/history/reports/chastity-log", response_model=HistoryDashboardOut)
def history_chastity_log(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(default=365, ge=7, le=3650),
) -> HistoryDashboardOut:
    return history_dashboard(dynamic_id, user, db, days=days, tags="")
