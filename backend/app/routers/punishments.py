from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, PartnerRole, User
from ..services.chat_events import post_activity_event
from ..services.punishments import (
    apply_idea_to_report,
    assign_punishment,
    create_confession,
    generate_punishment_ideas,
    get_report,
    list_reports,
    mark_covered,
    punishable_options,
    remind_tomorrow,
    report_out,
)

router = APIRouter(prefix="/dynamics", tags=["punishments"])


@router.get("/{dynamic_id}/punishments/options")
def get_punishment_options(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    return punishable_options(db, dynamic, membership)


@router.get("/{dynamic_id}/punishments")
def get_punishment_reports(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return list_reports(db, dynamic_id, membership)


@router.get("/{dynamic_id}/punishments/{report_id}")
def get_punishment_report(
    dynamic_id: str,
    report_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    report = get_report(db, dynamic_id, report_id)
    if dynamic is None or report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    payload = {
        "report": report_out(db, report),
        "you_are_dominant": membership.role == PartnerRole.dominant,
    }
    if membership.role == PartnerRole.dominant:
        payload["options"] = punishable_options(db, dynamic, membership)
    return payload


@router.post("/{dynamic_id}/punishments/self-report")
def post_punishment_self_report(
    dynamic_id: str,
    payload: dict[str, Any],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    result = create_confession(
        db,
        dynamic=dynamic,
        membership=membership,
        action=str(payload.get("action") or ""),
    )
    report = result["report"]
    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="punishment_pending",
        text=f"{membership.display_name} confessed something that needs punishment: {(report.get('action_text') or '')[:160]}",
        path=f"/dynamic/{dynamic_id}/punishment/{report['id']}",
        link_label="Open punishment dashboard",
        from_label="Punishment",
    )
    db.commit()
    return result


@router.post("/{dynamic_id}/punishments/{report_id}/assign")
def post_assign_punishment(
    dynamic_id: str,
    report_id: str,
    payload: dict[str, Any],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    report = get_report(db, dynamic_id, report_id)
    if dynamic is None or report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    result = assign_punishment(
        db,
        dynamic=dynamic,
        membership=membership,
        report=report,
        adjustments=payload.get("adjustments") if isinstance(payload.get("adjustments"), list) else [],
    )
    applied = result.get("applied") or []
    bits = [
        f"{a['requirement_title']} +{a['added']} → {a['new_target']} on “{a['goal_title']}”"
        for a in applied
    ]
    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="punishment_assigned",
        text=f"{membership.display_name} assigned punishment: {'; '.join(bits)}",
        path=f"/dynamic/{dynamic_id}/punishment/{report_id}",
        link_label="Open punishment",
        from_label="Punishment",
    )
    db.commit()
    return result


@router.post("/{dynamic_id}/punishments/{report_id}/ideas")
def post_punishment_ideas(
    dynamic_id: str,
    report_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    report = get_report(db, dynamic_id, report_id)
    if dynamic is None or report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    result = generate_punishment_ideas(
        db,
        dynamic=dynamic,
        membership=membership,
        user=user,
        report=report,
    )
    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="punishment_ideas",
        text=f"{membership.display_name} asked the assistant for more punishment ideas",
        path=f"/dynamic/{dynamic_id}/punishment/{report_id}",
        link_label="Open punishment",
        from_label="Punishment",
    )
    db.commit()
    return result


@router.post("/{dynamic_id}/punishments/{report_id}/remind")
def post_punishment_remind(
    dynamic_id: str,
    report_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    report = get_report(db, dynamic_id, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    result = remind_tomorrow(db, membership=membership, report=report)
    db.commit()
    return result


@router.post("/{dynamic_id}/punishments/{report_id}/covered")
def post_punishment_covered(
    dynamic_id: str,
    report_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    report = get_report(db, dynamic_id, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    result = mark_covered(db, membership=membership, report=report)
    post_activity_event(
        db,
        dynamic_id=dynamic_id,
        actor=membership,
        action="punishment_covered",
        text=f"{membership.display_name} marked a punishment as covered",
        path=f"/dynamic/{dynamic_id}/punishment",
        link_label="Punishment log",
        from_label="Punishment",
    )
    db.commit()
    return result


@router.post("/{dynamic_id}/punishments/{report_id}/apply-idea")
def post_apply_punishment_idea(
    dynamic_id: str,
    report_id: str,
    payload: dict[str, Any],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    report = get_report(db, dynamic_id, report_id)
    if dynamic is None or report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    result = apply_idea_to_report(
        db,
        dynamic=dynamic,
        membership=membership,
        report=report,
        idea_id=str(payload.get("idea_id") or ""),
    )
    db.commit()
    return result
