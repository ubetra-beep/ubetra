from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import User
from ..schemas import (
    EdgeGuardAddOut,
    EdgeGuardDecisionIn,
    EdgeGuardDomainsIn,
    EdgeGuardHeartbeatIn,
    EdgeGuardOut,
    EdgeGuardPolicyIn,
)
from ..services import edge_guard as edge_guard_service

router = APIRouter(prefix="/dynamics/{dynamic_id}/edge-guard", tags=["edge-guard"])


@router.get("", response_model=EdgeGuardOut)
def get_edge_guard(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return edge_guard_service.snapshot(db, membership)


@router.post("/domains", response_model=EdgeGuardAddOut)
def add_edge_guard_domains(
    dynamic_id: str,
    payload: EdgeGuardDomainsIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return edge_guard_service.add_domains(
        db,
        membership,
        payload.domains,
        payload.membership_id,
    )


@router.delete("/domains/{domain_id}", response_model=EdgeGuardOut)
def remove_edge_guard_domain(
    dynamic_id: str,
    domain_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return edge_guard_service.remove_domain(db, membership, domain_id)


@router.post("/domains/{domain_id}/removal-request", response_model=EdgeGuardOut)
def request_edge_guard_removal(
    dynamic_id: str,
    domain_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return edge_guard_service.request_removal(db, membership, domain_id)


@router.post("/domains/{domain_id}/decision", response_model=EdgeGuardOut)
def decide_edge_guard_removal(
    dynamic_id: str,
    domain_id: str,
    payload: EdgeGuardDecisionIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return edge_guard_service.decide_removal(db, membership, domain_id, payload.decision)


@router.patch("/policy", response_model=EdgeGuardOut)
def update_edge_guard_policy(
    dynamic_id: str,
    payload: EdgeGuardPolicyIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return edge_guard_service.update_policy(
        db,
        membership,
        locked=payload.locked,
        require_enabled=payload.require_enabled,
        membership_id=payload.membership_id,
    )


@router.post("/heartbeat", response_model=EdgeGuardOut)
def edge_guard_heartbeat(
    dynamic_id: str,
    payload: EdgeGuardHeartbeatIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    return edge_guard_service.record_heartbeat(
        db,
        membership,
        enabled=payload.enabled,
        running=payload.running,
        vpn_permission=payload.vpn_permission,
        domain_count=payload.domain_count,
    )
