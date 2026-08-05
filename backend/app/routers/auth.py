import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..config import settings
from ..database import get_db
from ..models import Membership, User
from ..schemas import (
    AuthPublicConfig,
    ClaimEmailRequest,
    LoginResponse,
    MfaResendRequest,
    MfaVerifyRequest,
    PasswordResetConfirm,
    PasswordResetOk,
    PasswordResetRequest,
    TokenResponse,
    UserCreate,
    UserEmailUpdate,
    UserPasswordUpdate,
    UserUsernameUpdate,
    UserSexUpdate,
    UserLogin,
    UserOut,
)
from ..services.mfa import (
    create_challenge,
    create_mfa_token,
    decode_mfa_token,
    smtp_configured,
    verify_challenge,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,63}$")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _validate_email(email: str) -> str:
    normalized = _normalize_email(email)
    if not _EMAIL_RE.match(normalized):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email")
    return normalized


def _normalize_username(username: str) -> str:
    return username.strip()


def _validate_username(username: str) -> str:
    normalized = _normalize_username(username)
    if not _USERNAME_RE.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 3–64 characters: letters, numbers, . _ - (start with a letter or number)",
        )
    return normalized


def apply_username(db: Session, user: User, username: str) -> str:
    """Set account username and sync membership display names. Raises HTTPException if taken/invalid."""
    username = _validate_username(username)
    taken = (
        db.query(User)
        .filter(func.lower(User.username) == username.lower(), User.id != user.id)
        .first()
    )
    if taken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")
    user.username = username
    db.query(Membership).filter(Membership.user_id == user.id).update(
        {Membership.display_name: username},
        synchronize_session=False,
    )
    return username


def _email_hint(email: str) -> str | None:
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[:1] + "*"
    else:
        masked = local[:1] + "***" + local[-1:]
    return f"{masked}@{domain}"


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email or "",
        email_set=bool((user.email or "").strip()),
        onboarding_completed=user.onboarding_completed,
        mfa_required=settings.mfa_required,
        biological_sex=getattr(user, "biological_sex", None) or "",
    )


@router.get("/config", response_model=AuthPublicConfig)
def auth_config() -> AuthPublicConfig:
    return AuthPublicConfig(
        mfa_required=settings.mfa_required,
        allow_public_register=settings.allow_public_register,
        smtp_configured=smtp_configured(),
    )


@router.post("/register", response_model=LoginResponse)
def register(payload: UserCreate, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    if not settings.allow_public_register:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled",
        )
    username = _validate_username(payload.username)
    existing = (
        db.query(User)
        .filter(func.lower(User.username) == username.lower())
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")

    email = _validate_email(payload.email)
    email_taken = (
        db.query(User)
        .filter(User.email == email, User.email != "")
        .first()
    )
    if email_taken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if settings.mfa_required:
        try:
            challenge, _ = create_challenge(db, user)
            db.commit()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return LoginResponse(
            mfa_required=True,
            mfa_token=create_mfa_token(user.id, challenge.id),
            email_hint=_email_hint(user.email),
        )

    return LoginResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=LoginResponse)
def login(payload: UserLogin, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    email = _normalize_email(payload.email)
    user = db.query(User).filter(User.email == email, User.email != "").first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if settings.mfa_required:
        try:
            challenge, _ = create_challenge(db, user)
            db.commit()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
        return LoginResponse(
            mfa_required=True,
            mfa_token=create_mfa_token(user.id, challenge.id),
            email_hint=_email_hint(user.email),
        )

    return LoginResponse(access_token=create_access_token(user.id))


@router.post("/mfa/verify", response_model=TokenResponse)
def verify_mfa(payload: MfaVerifyRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    try:
        claims = decode_mfa_token(payload.mfa_token)
        verify_challenge(db, claims["cid"], claims["sub"], payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = db.get(User, claims["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/mfa/resend", response_model=LoginResponse)
def resend_mfa(payload: MfaResendRequest, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    try:
        claims = decode_mfa_token(payload.mfa_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = db.get(User, claims["sub"])
    if user is None or not (user.email or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot resend code")

    try:
        challenge, _ = create_challenge(db, user)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    return LoginResponse(
        mfa_required=True,
        mfa_token=create_mfa_token(user.id, challenge.id),
        email_hint=_email_hint(user.email),
    )


@router.post("/claim-email", response_model=LoginResponse)
def claim_email(payload: ClaimEmailRequest, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    """Attach email to an existing account that has none, then start MFA."""
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if (user.email or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already set")

    email = _validate_email(payload.email)
    taken = (
        db.query(User)
        .filter(User.email == email, User.id != user.id, User.email != "")
        .first()
    )
    if taken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    user.email = email
    db.commit()
    db.refresh(user)

    if not settings.mfa_required:
        return LoginResponse(access_token=create_access_token(user.id))

    try:
        challenge, _ = create_challenge(db, user)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    return LoginResponse(
        mfa_required=True,
        mfa_token=create_mfa_token(user.id, challenge.id),
        email_hint=_email_hint(user.email),
    )


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return _user_out(user)


@router.put("/username", response_model=UserOut)
def update_username(
    payload: UserUsernameUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    apply_username(db, user, payload.username)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.put("/sex", response_model=UserOut)
def update_biological_sex(
    payload: UserSexUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    user.biological_sex = payload.biological_sex
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.put("/email", response_model=UserOut)
def update_email(
    payload: UserEmailUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    email = _validate_email(payload.email)
    taken = (
        db.query(User)
        .filter(User.email == email, User.id != user.id, User.email != "")
        .first()
    )
    if taken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
    user.email = email
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.put("/password", response_model=UserOut)
def update_password(
    payload: UserPasswordUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/password-reset/request", response_model=PasswordResetOk)
def password_reset_request(
    payload: PasswordResetRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetOk:
    from ..services.password_reset import request_password_reset

    result = request_password_reset(db, payload.email)
    db.commit()
    return PasswordResetOk(**result)


@router.post("/password-reset/confirm", response_model=PasswordResetOk)
def password_reset_confirm(
    payload: PasswordResetConfirm,
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetOk:
    from ..services.password_reset import confirm_password_reset

    try:
        confirm_password_reset(
            db,
            email=payload.email,
            new_password=payload.new_password,
            code=payload.code,
            token=payload.token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return PasswordResetOk(ok=True, detail="Password updated. You can sign in now.")
