from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import ContextLink, ContextLinkCategory, User
from ..schemas import ContextLinkCategoryOut, ContextLinkCreate, ContextLinkOut
from ..services.context import CONTEXT_CATEGORY_LABELS
from ..services.drive import fetch_public_google_doc_text, is_google_drive_url

router = APIRouter(prefix="/dynamics", tags=["context"])


def _link_out(link: ContextLink) -> ContextLinkOut:
    return ContextLinkOut(
        id=link.id,
        category=link.category,
        title=link.title,
        url=link.url,
        notes=link.notes,
        has_fetched_text=bool(link.fetched_text.strip()),
        added_by_display_name=link.added_by.display_name if link.added_by else "Partner",
        created_at=link.created_at,
    )


@router.get("/{dynamic_id}/context/categories", response_model=list[ContextLinkCategoryOut])
def list_context_categories(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ContextLinkCategoryOut]:
    get_membership(dynamic_id, user, db)
    return [
        ContextLinkCategoryOut(id=category.value, label=label)
        for category, label in CONTEXT_CATEGORY_LABELS.items()
    ]


@router.get("/{dynamic_id}/context", response_model=list[ContextLinkOut])
def list_context_links(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ContextLinkOut]:
    get_membership(dynamic_id, user, db)
    links = (
        db.query(ContextLink)
        .options(joinedload(ContextLink.added_by))
        .filter(ContextLink.dynamic_id == dynamic_id)
        .order_by(ContextLink.created_at.desc())
        .all()
    )
    return [_link_out(link) for link in links]


@router.post(
    "/{dynamic_id}/context",
    response_model=ContextLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_context_link(
    dynamic_id: str,
    payload: ContextLinkCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ContextLinkOut:
    membership = get_membership(dynamic_id, user, db)
    url = payload.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL must start with http")

    fetched = ""
    if is_google_drive_url(url):
        fetched = fetch_public_google_doc_text(url)

    link = ContextLink(
        dynamic_id=dynamic_id,
        added_by_membership_id=membership.id,
        category=payload.category,
        title=payload.title.strip(),
        url=url,
        notes=payload.notes.strip(),
        fetched_text=fetched,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    link = (
        db.query(ContextLink)
        .options(joinedload(ContextLink.added_by))
        .filter(ContextLink.id == link.id)
        .one()
    )
    return _link_out(link)


@router.delete("/{dynamic_id}/context/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_context_link(
    dynamic_id: str,
    link_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    get_membership(dynamic_id, user, db)
    link = (
        db.query(ContextLink)
        .filter(ContextLink.id == link_id, ContextLink.dynamic_id == dynamic_id)
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    db.delete(link)
    db.commit()
