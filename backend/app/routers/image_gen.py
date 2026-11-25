from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, User
from ..services import image_gen

router = APIRouter(prefix="/dynamics", tags=["images"])


class ImageGenerateIn(BaseModel):
    model: str = ""
    style: str = "art"
    prompt: str = Field(default="", max_length=1200)


@router.get("/{dynamic_id}/images/options")
def image_options(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    get_membership(dynamic_id, user, db)
    return image_gen.options()


@router.post("/{dynamic_id}/images/generate")
def image_generate(
    dynamic_id: str,
    payload: ImageGenerateIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    try:
        data_url = image_gen.generate_picture(
            db,
            user=user,
            dynamic=dynamic,
            model=payload.model,
            style=payload.style,
            prompt=payload.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"image_data": data_url}
