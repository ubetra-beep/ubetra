from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, get_membership
from ..database import get_db
from ..models import Dynamic, LlmProvider, Membership, PartnerRole, User
from ..schemas import (
    DynamicCreate,
    DynamicFeaturesOut,
    DynamicFeaturesUpdate,
    DynamicJoin,
    DynamicOut,
    DynamicPolicyOut,
    MenuSummariesOut,
    PartnerOut,
    PartnerUsernameUpdate,
    SharedLlmOut,
    SharedLlmUpdate,
)
from ..services.menu_summaries import menu_summaries
from ..services.chat_events import post_system_event
from ..services.features import (
    OPTIONAL_FEATURES,
    features_for_dynamic,
    parse_enabled_features,
    serialize_enabled_features,
)
from ..services.settings_policy import DOM_CONTROLLED_SETTING_KEYS, is_dominant, policy_snapshot
from ..services.llm import PROVIDER_CATALOG, is_llm_configured, mask_api_key, resolve_llm_config_for_dynamic
from .auth import apply_username

router = APIRouter(prefix="/dynamics", tags=["dynamics"])

_MEMBERSHIPS_WITH_USERS = joinedload(Dynamic.memberships).joinedload(Membership.user)


def _partner_out(m: Membership, current_user_id: str) -> PartnerOut:
    username = ""
    if getattr(m, "user", None) is not None:
        username = m.user.username or ""
    elif m.display_name:
        username = m.display_name
    return PartnerOut(
        id=m.id,
        display_name=m.display_name,
        username=username,
        role=m.role,
        survey_submitted=m.survey_submitted,
        survey_submitted_at=m.survey_submitted_at,
        share_kinks=bool(m.share_kinks),
        interview_completed=m.interview_completed,
        spti_completed=bool(m.spti_completed_at),
        chastity_enabled=m.chastity_enabled,
        chastity_max_lock_hours=m.chastity_max_lock_hours,
        is_you=m.user_id == current_user_id,
    )


def _dynamic_to_out(dynamic: Dynamic, current_user_id: str) -> DynamicOut:
    partners = [_partner_out(m, current_user_id) for m in dynamic.memberships]
    return DynamicOut(
        id=dynamic.id,
        name=dynamic.name,
        invite_code=dynamic.invite_code,
        created_at=dynamic.created_at,
        partners=partners,
        shared_llm_configured=bool((dynamic.shared_llm_api_key or "").strip()),
        enabled_features=sorted(parse_enabled_features(dynamic.enabled_features)),
    )


@router.get("", response_model=list[DynamicOut])
def list_dynamics(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DynamicOut]:
    memberships = (
        db.query(Membership)
        .options(joinedload(Membership.dynamic).options(_MEMBERSHIPS_WITH_USERS))
        .filter(Membership.user_id == user.id)
        .all()
    )
    dynamics = [m.dynamic for m in memberships]
    return [_dynamic_to_out(d, user.id) for d in dynamics]


@router.post("", response_model=DynamicOut, status_code=status.HTTP_201_CREATED)
def create_dynamic(
    payload: DynamicCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DynamicOut:
    dynamic = Dynamic(name=payload.name)
    db.add(dynamic)
    db.flush()

    membership = Membership(
        dynamic_id=dynamic.id,
        user_id=user.id,
        role=payload.role,
        display_name=user.username,
    )
    db.add(membership)
    db.commit()
    db.refresh(dynamic)
    dynamic = (
        db.query(Dynamic)
        .options(_MEMBERSHIPS_WITH_USERS)
        .filter(Dynamic.id == dynamic.id)
        .one()
    )
    return _dynamic_to_out(dynamic, user.id)


@router.post("/join", response_model=DynamicOut)
def join_dynamic(
    payload: DynamicJoin,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DynamicOut:
    dynamic = (
        db.query(Dynamic)
        .options(_MEMBERSHIPS_WITH_USERS)
        .filter(Dynamic.invite_code == payload.invite_code.upper())
        .first()
    )
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite code")

    existing = (
        db.query(Membership)
        .filter(Membership.dynamic_id == dynamic.id, Membership.user_id == user.id)
        .first()
    )
    if existing:
        return _dynamic_to_out(dynamic, user.id)

    if len(dynamic.memberships) >= 2:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dynamic is full")

    opposite_roles = {PartnerRole.dominant, PartnerRole.submissive}
    taken_roles = {m.role for m in dynamic.memberships}
    if payload.role in taken_roles and len(taken_roles) == 1:
        # Allow two subs or two doms only if user explicitly wants; for MVP enforce complement
        other = next(iter(taken_roles))
        if other == payload.role:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A {payload.role.value} is already in this dynamic",
            )

    membership = Membership(
        dynamic_id=dynamic.id,
        user_id=user.id,
        role=payload.role,
        display_name=payload.display_name or user.username,
    )
    db.add(membership)
    db.flush()
    # Prefer Dom & Sub names over the placeholder "Our dynamic"
    members = (
        db.query(Membership).filter(Membership.dynamic_id == dynamic.id).all()
    )
    dom = next((m for m in members if m.role == PartnerRole.dominant), None)
    sub = next((m for m in members if m.role == PartnerRole.submissive), None)
    placeholder = (dynamic.name or "").strip().lower() in {"", "our dynamic", "dynamic"}
    if dom and sub and placeholder:
        dynamic.name = f"{dom.display_name} & {sub.display_name}"
    if (dynamic.shared_llm_api_key or "").strip():
        post_system_event(
            db,
            dynamic.id,
            membership,
            "joined the dynamic — shared AI API key is active for this relationship",
        )
    db.commit()
    db.refresh(dynamic)
    return _dynamic_to_out(dynamic, user.id)


@router.get("/{dynamic_id}/shared-llm", response_model=SharedLlmOut)
def get_shared_llm(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SharedLlmOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, membership.dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    setter_name = None
    if dynamic.shared_llm_set_by_membership_id:
        setter = db.get(Membership, dynamic.shared_llm_set_by_membership_id)
        setter_name = setter.display_name if setter else None
    configured = bool((dynamic.shared_llm_api_key or "").strip())
    return SharedLlmOut(
        configured=configured,
        provider=dynamic.shared_llm_provider or LlmProvider.gemini.value,
        model=dynamic.shared_llm_model or "",
        api_key_hint=mask_api_key(dynamic.shared_llm_api_key) if configured else None,
        set_by_display_name=setter_name,
    )


@router.put("/{dynamic_id}/shared-llm", response_model=SharedLlmOut)
def update_shared_llm(
    dynamic_id: str,
    payload: SharedLlmUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SharedLlmOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, membership.dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    if payload.provider not in PROVIDER_CATALOG:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")

    had_key = bool((dynamic.shared_llm_api_key or "").strip())
    catalog = PROVIDER_CATALOG[payload.provider]
    if payload.provider == LlmProvider.server.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use a personal provider key for the dynamic, not server default",
        )
    if not payload.api_key.strip() and not had_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key required")

    dynamic.shared_llm_provider = payload.provider
    dynamic.shared_llm_model = (payload.model or catalog["default_model"]).strip()
    if payload.api_key.strip():
        dynamic.shared_llm_api_key = payload.api_key.strip()
    dynamic.shared_llm_set_by_membership_id = membership.id

    user.llm_provider = payload.provider
    user.llm_model = dynamic.shared_llm_model
    if payload.api_key.strip():
        user.llm_api_key = payload.api_key.strip()

    if had_key:
        post_system_event(
            db,
            dynamic_id,
            membership,
            "updated the shared AI API key for this dynamic",
        )
    else:
        post_system_event(
            db,
            dynamic_id,
            membership,
            "configured the shared AI API key for this dynamic",
        )
    db.commit()
    return get_shared_llm(dynamic_id, user, db)


@router.get("/{dynamic_id}/features", response_model=DynamicFeaturesOut)
def get_dynamic_features(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DynamicFeaturesOut:
    get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    data = features_for_dynamic(dynamic)
    return DynamicFeaturesOut(**data)


@router.put("/{dynamic_id}/features", response_model=DynamicFeaturesOut)
def update_dynamic_features(
    dynamic_id: str,
    payload: DynamicFeaturesUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DynamicFeaturesOut:
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can change menu features. Send a request from Settings.",
        )
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    selected = {item for item in payload.enabled_optional if item in OPTIONAL_FEATURES}
    # Keep paired optional features (tasks/acts) in sync
    for feature_id in list(selected):
        pair = OPTIONAL_FEATURES.get(feature_id, {}).get("paired_with")
        if pair:
            selected.add(pair)
    dynamic.enabled_features = serialize_enabled_features(selected)
    db.commit()
    db.refresh(dynamic)
    return DynamicFeaturesOut(**features_for_dynamic(dynamic))


@router.get("/{dynamic_id}/policy", response_model=DynamicPolicyOut)
def get_dynamic_policy(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DynamicPolicyOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dynamic not found")
    snap = policy_snapshot(dynamic)
    locked = [] if is_dominant(membership) else sorted(
        {
            *DOM_CONTROLLED_SETTING_KEYS,
            *[f"features.{fid}" for fid in OPTIONAL_FEATURES if not OPTIONAL_FEATURES[fid].get("hidden")],
        }
    )
    return DynamicPolicyOut(
        you_are_dominant=is_dominant(membership),
        chastity_sub_can_delete_breaks=snap["chastity_sub_can_delete_breaks"],
        feelings_prompt_mode=snap["feelings_prompt_mode"],
        feelings_require_end_of_day=snap["feelings_require_end_of_day"],
        chat_system_events=snap["chat_system_events"],
        chat_retain_history=snap["chat_retain_history"],
        enabled_features=snap["enabled_features"],
        locked_setting_keys=locked,
    )


@router.get("/{dynamic_id}/menu-summaries", response_model=MenuSummariesOut)
def get_menu_summaries(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MenuSummariesOut:
    get_membership(dynamic_id, user, db)
    data = menu_summaries(db, dynamic_id)
    return MenuSummariesOut(**data)


@router.put("/{dynamic_id}/partners/{membership_id}/username", response_model=PartnerOut)
def update_partner_username(
    dynamic_id: str,
    membership_id: str,
    payload: PartnerUsernameUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PartnerOut:
    """Keyholder can rename a submissive's username (partner-facing display name)."""
    membership = get_membership(dynamic_id, user, db)
    if not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can change a partner's username",
        )
    target = (
        db.query(Membership)
        .options(joinedload(Membership.user))
        .filter(Membership.id == membership_id, Membership.dynamic_id == dynamic_id)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partner not found")
    if target.role != PartnerRole.submissive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only a submissive's username can be changed this way",
        )
    if target.user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partner account not found")

    old_name = target.display_name
    new_name = apply_username(db, target.user, payload.username)
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is not None:
        members = (
            db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
        )
        dom = next((m for m in members if m.role == PartnerRole.dominant), None)
        sub = next((m for m in members if m.role == PartnerRole.submissive), None)
        if dom and sub:
            current = (dynamic.name or "").strip().lower()
            old_pair = f"{(old_name or '').strip().lower()} & {(dom.display_name or '').strip().lower()}"
            old_pair_rev = f"{(dom.display_name or '').strip().lower()} & {(old_name or '').strip().lower()}"
            if current in {"", "our dynamic", "dynamic", old_pair, old_pair_rev}:
                dynamic.name = f"{dom.display_name} & {sub.display_name}"
    post_system_event(
        db,
        dynamic_id,
        membership,
        f"set {old_name}'s username to {new_name}",
    )
    db.commit()
    db.refresh(target)
    if target.user is None:
        target.user = db.get(User, target.user_id)
    return _partner_out(target, user.id)


@router.get("/{dynamic_id}", response_model=DynamicOut)
def get_dynamic(
    dynamic_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DynamicOut:
    membership = get_membership(dynamic_id, user, db)
    dynamic = (
        db.query(Dynamic)
        .options(_MEMBERSHIPS_WITH_USERS)
        .filter(Dynamic.id == membership.dynamic_id)
        .one()
    )
    return _dynamic_to_out(dynamic, user.id)
