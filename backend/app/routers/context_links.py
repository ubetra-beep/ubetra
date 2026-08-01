"""Server-side context file library (replaces Drive URL injection)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import ContextLink, ContextLinkCategory, User
from ..schemas import ContextLinkCategoryOut, ContextLinkCreate, ContextLinkOut, ContextLinkUpdate
from ..services.context_files import (
    CONTEXT_SUBJECTS,
    extract_text_from_bytes,
    normalize_subject,
)

router = APIRouter(prefix="/dynamics", tags=["context"])

DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "context_files"


def _subject_to_category(subject: str) -> ContextLinkCategory:
    if subject == "stories":
        return ContextLinkCategory.fictional_story
    if subject == "scenes":
        return ContextLinkCategory.scene_inspiration
    return ContextLinkCategory.other


def _link_out(link: ContextLink) -> ContextLinkOut:
    subject = normalize_subject(getattr(link, "subject", None) or link.category.value)
    text = (link.fetched_text or "").strip()
    return ContextLinkOut(
        id=link.id,
        category=link.category,
        subject=subject,
        title=link.title,
        url=link.url or "",
        notes=link.notes or "",
        filename=getattr(link, "filename", "") or "",
        mime_type=getattr(link, "mime_type", "") or "",
        file_size=int(getattr(link, "file_size", 0) or 0),
        use_for_ai=bool(getattr(link, "use_for_ai", True)),
        has_fetched_text=bool(text),
        text_preview=text[:240],
        added_by_display_name=link.added_by.display_name if link.added_by else "Partner",
        created_at=link.created_at,
    )


def _store_raw_file(dynamic_id: str, link_id: str, filename: str, data: bytes) -> None:
    folder = DATA_ROOT / dynamic_id
    folder.mkdir(parents=True, exist_ok=True)
    safe = Path(filename or "upload").name.replace("..", "_")
    path = folder / f"{link_id}_{safe}"
    path.write_bytes(data)


@router.get("/{dynamic_id}/context/categories", response_model=list[ContextLinkCategoryOut])
def list_context_categories(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ContextLinkCategoryOut]:
    get_membership(dynamic_id, user, db)
    return [
        ContextLinkCategoryOut(id=key, label=label)
        for key, label in CONTEXT_SUBJECTS.items()
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
    "/{dynamic_id}/context/upload",
    response_model=ContextLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_context_file(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    subject: str = Form("other"),
    title: str = Form(""),
    notes: str = Form(""),
    use_for_ai: bool = Form(True),
) -> ContextLinkOut:
    membership = get_membership(dynamic_id, user, db)
    data = await file.read()
    filename = file.filename or "upload.txt"
    try:
        text = extract_text_from_bytes(filename, data, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    subj = normalize_subject(subject)
    link = ContextLink(
        dynamic_id=dynamic_id,
        added_by_membership_id=membership.id,
        category=_subject_to_category(subj),
        subject=subj,
        title=(title or Path(filename).stem or "Upload").strip()[:200],
        url="",
        notes=(notes or "").strip(),
        fetched_text=text,
        filename=filename[:255],
        mime_type=(file.content_type or "")[:120],
        file_size=len(data),
        use_for_ai=bool(use_for_ai),
    )
    db.add(link)
    db.flush()
    try:
        _store_raw_file(dynamic_id, link.id, filename, data)
    except OSError:
        pass
    db.commit()
    link = (
        db.query(ContextLink)
        .options(joinedload(ContextLink.added_by))
        .filter(ContextLink.id == link.id)
        .one()
    )
    return _link_out(link)


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
    """Create from pasted text (or empty notes) — no Drive fetch."""
    membership = get_membership(dynamic_id, user, db)
    text = (payload.text_content or payload.notes or "").strip()
    if not text and not payload.notes.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paste text content or upload a file. Google Drive links are no longer fetched.",
        )
    subj = normalize_subject(payload.subject or (payload.category.value if payload.category else "other"))
    link = ContextLink(
        dynamic_id=dynamic_id,
        added_by_membership_id=membership.id,
        category=payload.category or _subject_to_category(subj),
        subject=subj,
        title=payload.title.strip()[:200],
        url=(payload.url or "").strip()[:2000],
        notes=payload.notes.strip(),
        fetched_text=text or payload.notes.strip(),
        filename="",
        mime_type="text/plain",
        file_size=len((text or payload.notes).encode("utf-8")),
        use_for_ai=bool(payload.use_for_ai),
    )
    db.add(link)
    db.commit()
    link = (
        db.query(ContextLink)
        .options(joinedload(ContextLink.added_by))
        .filter(ContextLink.id == link.id)
        .one()
    )
    return _link_out(link)


@router.patch("/{dynamic_id}/context/{link_id}", response_model=ContextLinkOut)
def update_context_link(
    dynamic_id: str,
    link_id: str,
    payload: ContextLinkUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ContextLinkOut:
    get_membership(dynamic_id, user, db)
    link = (
        db.query(ContextLink)
        .options(joinedload(ContextLink.added_by))
        .filter(ContextLink.id == link_id, ContextLink.dynamic_id == dynamic_id)
        .first()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if payload.title is not None:
        link.title = payload.title.strip()[:200]
    if payload.subject is not None:
        subj = normalize_subject(payload.subject)
        link.subject = subj
        link.category = _subject_to_category(subj)
    if payload.notes is not None:
        link.notes = payload.notes.strip()
    if payload.use_for_ai is not None:
        link.use_for_ai = bool(payload.use_for_ai)
    db.commit()
    db.refresh(link)
    return _link_out(link)


@router.delete(
    "/{dynamic_id}/context/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_context_link(
    dynamic_id: str,
    link_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)
