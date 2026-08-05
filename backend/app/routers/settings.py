from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_membership
from ..config import settings
from ..database import get_db
from ..models import AiService, Dynamic, LlmProvider, Membership, User
from ..schemas import (
    AssistantSettingsOut,
    AssistantSettingsUpdate,
    AssistantToneOption,
    AiRoutingOut,
    AiServiceCreate,
    AiServiceOut,
    AiServiceUpdate,
    AiToolRouteUpdate,
    AiToolStatusOut,
    LlmProviderOption,
    LlmSettingsOut,
    LlmSettingsUpdate,
    LlmTestOut,
)
from ..services.ai_services import (
    AI_TOOLS,
    ensure_legacy_services,
    get_service_for_user,
    get_tool_routes,
    list_visible_services,
    run_capability_probe,
    service_out,
    set_tool_routes,
    tool_status,
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
    shared_configured = bool(
        dynamic
        and (
            (dynamic.shared_llm_api_key or "").strip()
            or (getattr(dynamic, "shared_llm_base_url", None) or "").strip()
        )
    )
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
        base_url=(user.llm_base_url or "").strip(),
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
        shared_base_url=(
            (getattr(dynamic, "shared_llm_base_url", None) or "").strip() or None
            if shared_configured
            else None
        ),
        active_dynamic_id=dynamic.id if dynamic else None,
    )


@router.get("/llm/providers", response_model=list[LlmProviderOption])
def list_llm_providers() -> list[LlmProviderOption]:
    return [
        LlmProviderOption(
            id=provider_id,
            label=details["label"],
            description=details["description"],
            policy_notes=details.get("policy_notes", ""),
            default_model=details["default_model"],
            models=list(details["models"]),
            key_url=details.get("key_url", ""),
            needs_base_url=bool(details.get("needs_base_url")),
            default_base_url=details.get("default_base_url") or "",
            allow_empty_key=bool(details.get("allow_empty_key")),
        )
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
    if payload.base_url is not None:
        user.llm_base_url = payload.base_url.strip()
    elif catalog.get("needs_base_url") and not (user.llm_base_url or "").strip():
        user.llm_base_url = (catalog.get("default_base_url") or "").strip()

    if payload.clear_api_key:
        user.llm_api_key = ""
        sync_user_llm_to_shared_dynamics(db, user, clear=True)
    elif payload.api_key is not None and payload.api_key.strip():
        user.llm_api_key = payload.api_key.strip()
        sync_user_llm_to_shared_dynamics(db, user)
    elif payload.provider != LlmProvider.server.value:
        sync_user_llm_to_shared_dynamics(db, user)

    if (
        payload.provider != LlmProvider.server.value
        and not user.llm_api_key.strip()
        and not catalog.get("allow_empty_key")
    ):
        if payload.api_key is None and not payload.clear_api_key:
            pass
        elif not payload.clear_api_key and not (payload.api_key or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key is required for this provider.",
            )
    if catalog.get("needs_base_url") and not (user.llm_base_url or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Base URL is required for this provider (e.g. http://host:1234/v1).",
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


def _ai_service_model(data: dict) -> AiServiceOut:
    return AiServiceOut(**data)


def _routing_out(db: Session, user: User, dynamic: Dynamic | None) -> AiRoutingOut:
    ensure_legacy_services(db, user, dynamic)
    services = list_visible_services(db, user, dynamic)
    routes = get_tool_routes(dynamic)
    tools: list[AiToolStatusOut] = []
    for tool in AI_TOOLS.values():
        st = tool_status(db, user, dynamic, tool.id)
        assigned_unknown = False
        if st.service_id:
            svc = get_service_for_user(db, user, st.service_id, dynamic)
            if svc is not None:
                cap_map = {
                    "text": svc.cap_text,
                    "text_nsfw": svc.cap_text_nsfw,
                    "image": svc.cap_image,
                    "image_nsfw": svc.cap_image_nsfw,
                }
                assigned_unknown = any(cap_map.get(cap) is None for cap in tool.needs)
        tools.append(
            AiToolStatusOut(
                tool_id=tool.id,
                label=tool.label,
                description=tool.description,
                needs=list(tool.needs),
                configured=st.configured,
                service_id=st.service_id,
                service_name=st.service_name,
                issue=st.issue,
                needs_assignment=st.needs_assignment,
                missing_caps=st.missing_caps,
                recommendations=st.recommendations,
                assigned_unknown=assigned_unknown or st.needs_assignment,
            )
        )
    return AiRoutingOut(
        dynamic_id=dynamic.id if dynamic else None,
        default_ai_service_id=getattr(user, "default_ai_service_id", None),
        adult_ai_service_id=getattr(user, "adult_ai_service_id", None),
        routes=routes,
        tools=tools,
        services=[_ai_service_model(service_out(s)) for s in services],
    )


@router.get("/ai-services", response_model=list[AiServiceOut])
def list_ai_services(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> list[AiServiceOut]:
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    ensure_legacy_services(db, user, dynamic)
    return [_ai_service_model(service_out(s)) for s in list_visible_services(db, user, dynamic)]


@router.post("/ai-services", response_model=AiServiceOut)
def create_ai_service(
    payload: AiServiceCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AiServiceOut:
    if payload.provider not in PROVIDER_CATALOG:
        raise HTTPException(status_code=400, detail="Unknown provider")
    catalog = PROVIDER_CATALOG[payload.provider]
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    dyn_id = None
    if payload.share_with_dynamic and dynamic is not None:
        dyn_id = dynamic.id
    svc = AiService(
        owner_user_id=user.id,
        dynamic_id=dyn_id,
        name=(payload.name or "AI connection").strip()[:120],
        provider=payload.provider,
        api_key=(payload.api_key or "").strip(),
        model=(payload.model or catalog["default_model"]).strip(),
        image_model=(payload.image_model or "").strip(),
        base_url=(payload.base_url or catalog.get("default_base_url") or "").strip(),
        purpose=(payload.purpose or "general").strip()[:32],
    )
    if not svc.api_key and not catalog.get("allow_empty_key"):
        raise HTTPException(status_code=400, detail="API key is required for this provider.")
    if catalog.get("needs_base_url") and not svc.base_url:
        raise HTTPException(status_code=400, detail="Base URL is required for this provider.")
    db.add(svc)
    db.flush()
    if payload.purpose == "adult" and not user.adult_ai_service_id:
        user.adult_ai_service_id = svc.id
    if payload.purpose == "general" and not user.default_ai_service_id:
        user.default_ai_service_id = svc.id
    if payload.purpose == "images" and not user.adult_ai_service_id:
        user.adult_ai_service_id = svc.id
    db.commit()
    db.refresh(svc)
    return _ai_service_model(service_out(svc))


@router.patch("/ai-services/{service_id}", response_model=AiServiceOut)
def update_ai_service(
    service_id: str,
    payload: AiServiceUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AiServiceOut:
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    svc = get_service_for_user(db, user, service_id, dynamic)
    if svc is None or svc.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="AI service not found")
    if payload.name is not None:
        svc.name = payload.name.strip()[:120] or svc.name
    if payload.provider is not None:
        if payload.provider not in PROVIDER_CATALOG:
            raise HTTPException(status_code=400, detail="Unknown provider")
        svc.provider = payload.provider
    if payload.model is not None:
        svc.model = payload.model.strip()
    if payload.image_model is not None:
        svc.image_model = payload.image_model.strip()
    if payload.base_url is not None:
        svc.base_url = payload.base_url.strip()
    if payload.purpose is not None:
        svc.purpose = payload.purpose.strip()[:32]
    if payload.clear_api_key:
        svc.api_key = ""
    elif payload.api_key is not None and payload.api_key.strip():
        svc.api_key = payload.api_key.strip()
    if payload.share_with_dynamic is not None and dynamic is not None:
        svc.dynamic_id = dynamic.id if payload.share_with_dynamic else None
    if payload.set_as_default:
        user.default_ai_service_id = svc.id
    if payload.set_as_adult:
        user.adult_ai_service_id = svc.id
    db.commit()
    db.refresh(svc)
    return _ai_service_model(service_out(svc))


@router.delete("/ai-services/{service_id}")
def delete_ai_service(
    service_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    svc = db.get(AiService, service_id)
    if svc is None or svc.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="AI service not found")
    if user.default_ai_service_id == svc.id:
        user.default_ai_service_id = None
    if user.adult_ai_service_id == svc.id:
        user.adult_ai_service_id = None
    db.delete(svc)
    db.commit()
    return {"ok": True}


@router.post("/ai-services/{service_id}/probe", response_model=AiServiceOut)
def probe_ai_service(
    service_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AiServiceOut:
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    svc = get_service_for_user(db, user, service_id, dynamic)
    if svc is None or svc.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="AI service not found")
    svc = run_capability_probe(db, user=user, svc=svc, dynamic=dynamic)
    return _ai_service_model(service_out(svc))


@router.get("/ai-routing", response_model=AiRoutingOut)
def get_ai_routing(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AiRoutingOut:
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    return _routing_out(db, user, dynamic)


@router.put("/ai-routing", response_model=AiRoutingOut)
def update_ai_routing(
    payload: AiToolRouteUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AiRoutingOut:
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=400, detail="Join a dynamic before assigning AI tools.")
    membership = get_membership(dynamic.id, user, db)
    if not is_dominant(membership):
        raise HTTPException(status_code=403, detail="Only the keyholder can assign AI tool routing.")
    for sid in payload.routes.values():
        if not sid:
            continue
        if get_service_for_user(db, user, sid, dynamic) is None:
            raise HTTPException(status_code=400, detail=f"Unknown AI service: {sid}")
    set_tool_routes(dynamic, payload.routes)
    db.commit()
    return _routing_out(db, user, dynamic)


@router.get("/ai-tools/{tool_id}/status", response_model=AiToolStatusOut)
def get_ai_tool_status(
    tool_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    dynamic_id: str | None = None,
) -> AiToolStatusOut:
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    ensure_legacy_services(db, user, dynamic)
    tool = AI_TOOLS.get(tool_id)
    st = tool_status(db, user, dynamic, tool_id)
    return AiToolStatusOut(
        tool_id=st.tool_id,
        label=st.label,
        description=tool.description if tool else "",
        needs=list(tool.needs) if tool else [],
        configured=st.configured,
        service_id=st.service_id,
        service_name=st.service_name,
        issue=st.issue,
        needs_assignment=st.needs_assignment,
        missing_caps=st.missing_caps,
        recommendations=st.recommendations,
        assigned_unknown=st.needs_assignment or (not st.configured),
    )
