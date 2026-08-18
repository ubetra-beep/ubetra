"""In-app wiki and visit log. Remote Chromium web play is gone."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import KioskVisit, Membership, User
from ..schemas import KioskVisitCreate, KioskVisitEnd, KioskVisitOut
from ..services.settings_policy import is_dominant
from ..services.wiki_pages import (
    list_wiki_pages,
    load_wiki_page,
    wiki_image_path,
)

router = APIRouter()


def _valid_http_url(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("wiki:"):
        slug = text.split(":", 1)[1].strip() or "Home"
        return f"wiki:{slug}"
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL must be http(s)")
    return text[:500]


def _member_name(db: Session, membership_id: str) -> str:
    m = db.get(Membership, membership_id)
    return m.display_name if m else ""


def _visit_out(db: Session, visit: KioskVisit) -> KioskVisitOut:
    return KioskVisitOut(
        id=visit.id,
        membership_id=visit.membership_id,
        member_name=_member_name(db, visit.membership_id),
        url=visit.url,
        title=visit.title or "",
        source=visit.source or "manual",
        started_at=visit.started_at,
        ended_at=visit.ended_at,
        duration_sec=int(visit.duration_sec or 0),
    )


@router.get("/app/wiki")
def wiki_index(user: Annotated[User, Depends(get_current_user)]) -> dict:
    _ = user
    return {"pages": list_wiki_pages()}


@router.get("/app/wiki/pages/{slug}")
def wiki_page(slug: str, user: Annotated[User, Depends(get_current_user)]) -> dict:
    _ = user
    page = load_wiki_page(slug)
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wiki page not found")
    return page


@router.get("/app/wiki/images/{name}")
def wiki_image(name: str):
    path = wiki_image_path(name)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wiki image not found")
    return FileResponse(path)


@router.get("/dynamics/{dynamic_id}/kiosk/visits", response_model=list[KioskVisitOut])
def list_kiosk_visits(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 80,
) -> list[KioskVisitOut]:
    membership = get_membership(dynamic_id, user, db)
    q = db.query(KioskVisit).filter(KioskVisit.dynamic_id == dynamic_id)
    if not is_dominant(membership):
        q = q.filter(KioskVisit.membership_id == membership.id)
    rows = q.order_by(KioskVisit.started_at.desc()).limit(max(1, min(limit, 200))).all()
    return [_visit_out(db, v) for v in rows]


@router.post(
    "/dynamics/{dynamic_id}/kiosk/visits",
    response_model=KioskVisitOut,
    status_code=status.HTTP_201_CREATED,
)
def start_kiosk_visit(
    dynamic_id: str,
    payload: KioskVisitCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> KioskVisitOut:
    membership = get_membership(dynamic_id, user, db)
    url = _valid_http_url(payload.url)
    source = (payload.source or "manual").strip()[:32] or "manual"
    visit = KioskVisit(
        dynamic_id=dynamic_id,
        membership_id=membership.id,
        url=url,
        title=(payload.title or "")[:200],
        source=source,
        started_at=datetime.utcnow(),
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return _visit_out(db, visit)


@router.patch("/dynamics/{dynamic_id}/kiosk/visits/{visit_id}", response_model=KioskVisitOut)
def end_kiosk_visit(
    dynamic_id: str,
    visit_id: str,
    payload: KioskVisitEnd,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> KioskVisitOut:
    membership = get_membership(dynamic_id, user, db)
    visit = db.get(KioskVisit, visit_id)
    if visit is None or visit.dynamic_id != dynamic_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found")
    if visit.membership_id != membership.id and not is_dominant(membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    visit.ended_at = datetime.utcnow()
    if payload.title is not None:
        visit.title = payload.title[:200]
    if payload.duration_sec is not None:
        visit.duration_sec = payload.duration_sec
    else:
        start = visit.started_at or visit.ended_at
        visit.duration_sec = max(0, int((visit.ended_at - start).total_seconds()))
    db.commit()
    db.refresh(visit)
    return _visit_out(db, visit)
