from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..config import settings
from ..database import get_db
from ..models import Dynamic, LlmProvider, Membership, User
from ..schemas import (
    AssistantSettingsOut,
    AssistantSettingsUpdate,
    AssistantToneOption,
    LlmProviderOption,
    LlmSettingsOut,
    LlmSettingsUpdate,
    LlmTestOut,
)
from ..services.llm import (
    ASSISTANT_TONES,
    PROVIDER_CATALOG,
    effective_llm_for_user,
    generate_text,
    is_llm_configured,
    mask_api_key,
    pick_llm_dynamic,
    sync_user_llm_to_shared_dynamics,
)
from ..services.settings_policy import is_dominant, require_dom_for_setting


router = APIRouter(prefix="/settings", tags=["settings"])


def _settings_out(
    user: User,
    db: Session,
    *,
    dynamic_id: str | None = None,
) -> LlmSettingsOut:
    config, source = effective_llm_for_user(db, user, dynamic_id)
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    shared_count = (
        db.query(Dynamic)
        .join(Membership, Membership.dynamic_id == Dynamic.id)
        .filter(Membership.user_id == user.id)
        .filter(Dynamic.shared_llm_api_key.isnot(None))
        .filter(Dynamic.shared_llm_api_key != "")
        .count()
    )

    active_hint = mask_api_key(config.api_key) if config.api_key else None
    shared_configured = bool(dynamic and (dynamic.shared_llm_api_key or "").strip())
    account_provider = user.llm_provider or LlmProvider.server.value
    # Account form fields stay personal; shared_* reflects what both partners actually use.
    account_model = (user.llm_model or "").strip() or (
        config.model if source != "shared" else ""
    )

    return LlmSettingsOut(
        provider=account_provider,
        model=account_model or config.model,
        api_key_set=bool((user.llm_api_key or "").strip())
        or (account_provider == LlmProvider.server.value and bool(settings.gemini_api_key.strip())),
        api_key_hint=mask_api_key(user.llm_api_key)
        if account_provider != LlmProvider.server.value
        else (
            mask_api_key(settings.gemini_api_key)
            if settings.gemini_api_key.strip()
            else None
        ),
        configured=is_llm_configured(user, dynamic),
        using_server_default=config.using_server_default and source == "server",
        server_env_configured=bool(settings.gemini_api_key.strip()),
        active_key_source=source,
        active_api_key_hint=active_hint,
        shared_dynamics_count=shared_count,
        shared_configured=shared_configured,
        shared_provider=(dynamic.shared_llm_provider if shared_configured else None),
        shared_model=(dynamic.shared_llm_model if shared_configured else None),
        shared_api_key_hint=(
            mask_api_key(dynamic.shared_llm_api_key) if shared_configured else None
        ),
        active_dynamic_id=dynamic.id if dynamic else None,
    )


@router.get("/llm/providers", response_model=list[LlmProviderOption])
def list_llm_providers() -> list[LlmProviderOption]:
    return [
        LlmProviderOption(id=provider_id, **details)
        for provider_id, details in PROVIDER_CATALOG.items()
    ]


@router.get("/llm", response_model=LlmSettingsOut)
def get_llm_settings(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> LlmSettingsOut:
    return _settings_out(user, db, dynamic_id=dynamic_id)


@router.put("/llm", response_model=LlmSettingsOut)
def update_llm_settings(
    payload: LlmSettingsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> LlmSettingsOut:
    if payload.provider not in PROVIDER_CATALOG:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")

    user.llm_provider = payload.provider
    catalog = PROVIDER_CATALOG[payload.provider]
    user.llm_model = (payload.model or catalog["default_model"]).strip()

    if payload.clear_api_key:
        user.llm_api_key = ""
        sync_user_llm_to_shared_dynamics(db, user, clear=True)
    elif payload.api_key is not None and payload.api_key.strip():
        user.llm_api_key = payload.api_key.strip()
        sync_user_llm_to_shared_dynamics(db, user)
    elif payload.provider != LlmProvider.server.value:
        sync_user_llm_to_shared_dynamics(db, user)

    if payload.provider != LlmProvider.server.value and not user.llm_api_key.strip():
        if payload.api_key is None and not payload.clear_api_key:
            pass
        elif not payload.clear_api_key and not (payload.api_key or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key is required for this provider.",
            )

    db.commit()
    db.refresh(user)
    return _settings_out(user, db, dynamic_id=dynamic_id)


@router.post("/llm/test", response_model=LlmTestOut)
def test_llm_connection(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> LlmTestOut:
    config, source = effective_llm_for_user(db, user, dynamic_id)
    dynamic = pick_llm_dynamic(db, user, dynamic_id)

    if not config.api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add an API key in Settings (or set UBETRA_GEMINI_API_KEY) before testing.",
        )

    try:
        reply = generate_text(
            user=user,
            user_prompt="Reply with exactly this token and nothing else: UBETRA_OK",
            dynamic_context="Connectivity probe. Ignore any relationship context.",
            system_instruction=(
                "You are a connectivity probe for UBETRA. "
                "Reply with exactly: UBETRA_OK"
            ),
            dynamic=dynamic,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return LlmTestOut(
            ok=False,
            provider=config.provider,
            model=config.model,
            active_key_source=source,
            detail=detail,
        )

    return LlmTestOut(
        ok=True,
        provider=config.provider,
        model=config.model,
        active_key_source=source,
        reply=(reply or "")[:240],
    )


def _assistant_settings_out(
    user: User,
    *,
    dynamic: Dynamic | None = None,
    membership: Membership | None = None,
) -> AssistantSettingsOut:
    if dynamic is not None:
        tone = getattr(dynamic, "assistant_tone", None) or "balanced"
        extra = getattr(dynamic, "assistant_extra_instructions", None) or ""
    else:
        tone = user.assistant_tone or "balanced"
        extra = user.assistant_extra_instructions or ""
    if tone not in ASSISTANT_TONES:
        tone = "balanced"
    return AssistantSettingsOut(
        tone=tone,
        extra_instructions=extra,
        include_tracking=bool(user.assistant_include_tracking),
        you_are_dominant=is_dominant(membership) if membership else True,
        dynamic_id=dynamic.id if dynamic else None,
    )


@router.get("/assistant/tones", response_model=list[AssistantToneOption])
def list_assistant_tones() -> list[AssistantToneOption]:
    return [
        AssistantToneOption(id=tone_id, label=details["label"], description=details["description"])
        for tone_id, details in ASSISTANT_TONES.items()
    ]


@router.get("/assistant", response_model=AssistantSettingsOut)
def get_assistant_settings(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AssistantSettingsOut:
    membership = None
    dynamic = None
    if dynamic_id:
        membership = get_membership(dynamic_id, user, db)
        dynamic = db.get(Dynamic, dynamic_id)
    else:
        membership = (
            db.query(Membership)
            .filter(Membership.user_id == user.id)
            .order_by(Membership.created_at)
            .first()
        )
        if membership:
            dynamic = db.get(Dynamic, membership.dynamic_id)
    return _assistant_settings_out(user, dynamic=dynamic, membership=membership)


@router.put("/assistant", response_model=AssistantSettingsOut)
def update_assistant_settings(
    payload: AssistantSettingsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AssistantSettingsOut:
    if payload.tone not in ASSISTANT_TONES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown tone")

    membership = None
    dynamic = None
    if dynamic_id:
        membership = get_membership(dynamic_id, user, db)
        dynamic = db.get(Dynamic, dynamic_id)
    else:
        membership = (
            db.query(Membership)
            .filter(Membership.user_id == user.id)
            .order_by(Membership.created_at)
            .first()
        )
        if membership:
            dynamic = db.get(Dynamic, membership.dynamic_id)

    # Tone / extra instructions are keyholder-controlled for the dynamic.
    if dynamic is not None and membership is not None:
        if not is_dominant(membership):
            # Sub may only change personal tracking visibility
            user.assistant_include_tracking = payload.include_tracking
            db.commit()
            db.refresh(user)
            return _assistant_settings_out(user, dynamic=dynamic, membership=membership)
        require_dom_for_setting(membership, "assistant.tone")
        dynamic.assistant_tone = payload.tone
        dynamic.assistant_extra_instructions = payload.extra_instructions.strip()
    else:
        user.assistant_tone = payload.tone
        user.assistant_extra_instructions = payload.extra_instructions.strip()

    # Tracking visibility stays per-user (privacy preference).
    user.assistant_include_tracking = payload.include_tracking
    db.commit()
    db.refresh(user)
    if dynamic is not None:
        db.refresh(dynamic)
    return _assistant_settings_out(user, dynamic=dynamic, membership=membership)
