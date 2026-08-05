from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, MangaComic, User
from ..services.features import is_feature_enabled
from ..services.manga import MODE_WARNINGS, generate_manga, list_comics, save_comic, year_month_now
from ..services.settings_policy import is_dominant

router = APIRouter(prefix="/dynamics", tags=["manga"])


class MangaPanelOut(BaseModel):
    id: str
    position: int
    caption: str
    dialogue: str
    visual_prompt: str
    image_data: str = ""
    image_error: str = ""

    class Config:
        from_attributes = True


class MangaComicOut(BaseModel):
    id: str
    year_month: str
    title: str
    mode: str
    status: str
    warnings: list[str] = []
    created_at: datetime
    updated_at: datetime
    panels: list[MangaPanelOut] = []

    class Config:
        from_attributes = True


class MangaGenerateRequest(BaseModel):
    mode: str = "script"


class MangaModesOut(BaseModel):
    modes: list[dict]
    year_month: str
    feature_enabled: bool


def _comic_out(comic: MangaComic) -> MangaComicOut:
    import json

    try:
        warnings = json.loads(comic.warnings_json or "[]")
    except json.JSONDecodeError:
        warnings = []
    panels = sorted(comic.panels or [], key=lambda p: p.position)
    return MangaComicOut(
        id=comic.id,
        year_month=comic.year_month,
        title=comic.title,
        mode=comic.mode,
        status=comic.status,
        warnings=warnings if isinstance(warnings, list) else [],
        created_at=comic.created_at,
        updated_at=comic.updated_at,
        panels=[MangaPanelOut.model_validate(p) for p in panels],
    )


@router.get("/{dynamic_id}/manga/modes", response_model=MangaModesOut)
def manga_modes(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MangaModesOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    modes = [
        {"id": "script", "label": "Script / storyboard", "warning": MODE_WARNINGS["script"]},
        {"id": "hybrid", "label": "Hybrid (images when allowed)", "warning": MODE_WARNINGS["hybrid"]},
        {"id": "full", "label": "Full AI panels", "warning": MODE_WARNINGS["full"]},
    ]
    return MangaModesOut(
        modes=modes,
        year_month=year_month_now(),
        feature_enabled=is_feature_enabled(dynamic, "manga_comics"),
    )


@router.get("/{dynamic_id}/manga", response_model=list[MangaComicOut])
def manga_list(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MangaComicOut]:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    if not is_feature_enabled(dynamic, "manga_comics"):
        raise HTTPException(status_code=403, detail="Monthly manga is not enabled.")
    return [_comic_out(c) for c in list_comics(db, dynamic_id)]


@router.post("/{dynamic_id}/manga/generate", response_model=MangaComicOut)
def manga_generate(
    dynamic_id: str,
    payload: MangaGenerateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MangaComicOut:
    if payload.mode not in MODE_WARNINGS:
        raise HTTPException(status_code=400, detail="Unknown manga mode")
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=404, detail="Dynamic not found")
    comic = generate_manga(
        db,
        user=user,
        dynamic=dynamic,
        membership=membership,
        mode=payload.mode,
    )
    db.commit()
    return _comic_out(comic)


@router.post("/{dynamic_id}/manga/{comic_id}/save", response_model=MangaComicOut)
def manga_save(
    dynamic_id: str,
    comic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MangaComicOut:
    get_membership(dynamic_id, user, db)
    comic = db.get(MangaComic, comic_id)
    if comic is None or comic.dynamic_id != dynamic_id:
        raise HTTPException(status_code=404, detail="Comic not found")
    save_comic(db, comic)
    db.commit()
    db.refresh(comic)
    return _comic_out(comic)


@router.delete("/{dynamic_id}/manga/{comic_id}")
def manga_delete(
    dynamic_id: str,
    comic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    membership = get_membership(dynamic_id, user, db)
    comic = db.get(MangaComic, comic_id)
    if comic is None or comic.dynamic_id != dynamic_id:
        raise HTTPException(status_code=404, detail="Comic not found")
    if comic.status == "saved" and not is_dominant(membership):
        raise HTTPException(status_code=403, detail="Only the keyholder can delete a saved comic")
    db.delete(comic)
    db.commit()
    return {"ok": True}
