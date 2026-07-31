from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import User
from ..schemas import AccountImportResult
from ..services.account_export import build_user_export, import_user_export

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/export")
def export_account(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    payload = build_user_export(db, user)
    filename = f"ubetra-export-{user.username}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=AccountImportResult)
def import_account(
    payload: dict[str, Any],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AccountImportResult:
    if not isinstance(payload, dict) or "ubetra_export_version" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid export file.",
        )
    result = import_user_export(db, user, payload)
    return AccountImportResult(**result)
