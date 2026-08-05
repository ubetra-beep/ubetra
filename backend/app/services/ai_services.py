"""Multi-connection AI services, tool routing, capability probes, and fix hints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import AiService, Dynamic, LlmProvider, Membership, User
from .llm import (
    PROVIDER_CATALOG,
    ResolvedLlmConfig,
    is_llm_configured,
    mask_api_key,
    resolve_llm_config_for_dynamic,
)

# Capability keys used by tools and probe results
CAP_TEXT = "text"
CAP_TEXT_NSFW = "text_nsfw"
CAP_IMAGE = "image"
CAP_IMAGE_NSFW = "image_nsfw"


@dataclass(frozen=True)
class AiToolSpec:
    id: str
    label: str
    description: str
    needs: tuple[str, ...]
    recommend_providers: tuple[str, ...]
    recommend_note: str = ""


AI_TOOLS: dict[str, AiToolSpec] = {
    "assistant": AiToolSpec(
        id="assistant",
        label="Assistant Domme",
        description="Scene ideas, tasks, and playtime coaching.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
        recommend_note="Prefer LM Studio (local uncensored) or an uncensored OpenRouter model.",
    ),
    "interview": AiToolSpec(
        id="interview",
        label="Interview summaries",
        description="Summarize intake interviews into Core Knowledge.",
        needs=(CAP_TEXT,),
        recommend_providers=(
            LlmProvider.gemini.value,
            LlmProvider.openrouter.value,
            LlmProvider.openai.value,
        ),
    ),
    "core_knowledge": AiToolSpec(
        id="core_knowledge",
        label="Core Knowledge assist",
        description="Draft / refine shared core knowledge.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "acts": AiToolSpec(
        id="acts",
        label="Acts of submission",
        description="Suggest and expand act catalog items.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "punishments": AiToolSpec(
        id="punishments",
        label="Punishment suggestions",
        description="Propose negotiated consequences.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "journals": AiToolSpec(
        id="journals",
        label="Journal assist",
        description="Help draft journal prompts and reflections.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "agreements": AiToolSpec(
        id="agreements",
        label="Agreements assist",
        description="Draft protocol / agreement language.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "interests": AiToolSpec(
        id="interests",
        label="Kink survey assist",
        description="Explain or expand interest catalog items.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.openrouter.value, LlmProvider.lmstudio.value),
    ),
    "spin_wheel": AiToolSpec(
        id="spin_wheel",
        label="Spin wheel",
        description="Generate spin outcomes and scene twists.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "playtime": AiToolSpec(
        id="playtime",
        label="Playtime ideas",
        description="Short play session suggestions.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "tasks": AiToolSpec(
        id="tasks",
        label="Task / make-up assist",
        description="Domme notes and task help text.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
    ),
    "manga_script": AiToolSpec(
        id="manga_script",
        label="Monthly manga (script)",
        description="Storyboard / captions for monthly manga.",
        needs=(CAP_TEXT, CAP_TEXT_NSFW),
        recommend_providers=(LlmProvider.lmstudio.value, LlmProvider.openrouter.value),
        recommend_note="Use an uncensored text model — Gemini/OpenAI often refuse explicit scripts.",
    ),
    "manga_image": AiToolSpec(
        id="manga_image",
        label="Monthly manga (images)",
        description="Panel image generation for hybrid/full modes.",
        needs=(CAP_IMAGE, CAP_IMAGE_NSFW),
        recommend_providers=(
            LlmProvider.lmstudio.value,
            LlmProvider.openai_compatible.value,
            LlmProvider.openrouter.value,
        ),
        recommend_note=(
            "Hosted DALL·E / many OpenRouter image models refuse NSFW. "
            "Best: local Automatic1111 / ComfyUI / Forge behind an OpenAI-compatible /v1, "
            "or a known NSFW image host."
        ),
    ),
}


@dataclass
class ToolStatus:
    tool_id: str
    label: str
    configured: bool
    service_id: str | None
    service_name: str | None
    issue: str | None
    needs_assignment: bool
    missing_caps: list[str]
    recommendations: list[dict[str, str]]


def _parse_routes(raw: str | None) -> dict[str, str]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k and v}


def get_tool_routes(dynamic: Dynamic | None) -> dict[str, str]:
    if dynamic is None:
        return {}
    return _parse_routes(getattr(dynamic, "ai_tool_routes", None))


def set_tool_routes(dynamic: Dynamic, routes: dict[str, str | None]) -> None:
    current = get_tool_routes(dynamic)
    for tool_id, service_id in routes.items():
        if tool_id not in AI_TOOLS:
            continue
        if not service_id:
            current.pop(tool_id, None)
        else:
            current[tool_id] = service_id
    dynamic.ai_tool_routes = json.dumps(current)


def service_to_config(svc: AiService) -> ResolvedLlmConfig:
    catalog = PROVIDER_CATALOG.get(svc.provider) or {}
    key = (svc.api_key or "").strip()
    if not key and catalog.get("allow_empty_key"):
        key = "local"
    base = (svc.base_url or "").strip() or (catalog.get("default_base_url") or "")
    return ResolvedLlmConfig(
        provider=svc.provider,
        api_key=key,
        model=(svc.model or catalog.get("default_model") or "").strip(),
        using_server_default=False,
        base_url=base.rstrip("/"),
    )


def service_is_ready(svc: AiService) -> bool:
    catalog = PROVIDER_CATALOG.get(svc.provider) or {}
    cfg = service_to_config(svc)
    if catalog.get("needs_base_url") and not cfg.base_url:
        return False
    if catalog.get("allow_empty_key"):
        return bool(cfg.model and cfg.base_url)
    return bool(cfg.api_key and cfg.model)


def _cap_value(svc: AiService, cap: str) -> bool | None:
    return {
        CAP_TEXT: svc.cap_text,
        CAP_TEXT_NSFW: svc.cap_text_nsfw,
        CAP_IMAGE: svc.cap_image,
        CAP_IMAGE_NSFW: svc.cap_image_nsfw,
    }.get(cap)


def service_satisfies(svc: AiService, needs: tuple[str, ...]) -> tuple[bool, list[str]]:
    """True when no capability is known-failed. Untested caps are allowed (UI shows amber/red for unknown separately)."""
    missing: list[str] = []
    for need in needs:
        val = _cap_value(svc, need)
        if val is False:
            missing.append(need)
    if not service_is_ready(svc):
        return False, list(needs)
    return (len(missing) == 0, missing)


def list_visible_services(
    db: Session,
    user: User,
    dynamic: Dynamic | None = None,
) -> list[AiService]:
    owned = (
        db.query(AiService)
        .filter(AiService.owner_user_id == user.id)
        .order_by(AiService.created_at.asc())
        .all()
    )
    if dynamic is None:
        return owned
    dyn_rows = (
        db.query(AiService)
        .filter(AiService.dynamic_id == dynamic.id)
        .order_by(AiService.created_at.asc())
        .all()
    )
    by_id = {s.id: s for s in [*owned, *dyn_rows]}
    return list(by_id.values())


def get_service_for_user(
    db: Session,
    user: User,
    service_id: str,
    dynamic: Dynamic | None = None,
) -> AiService | None:
    svc = db.get(AiService, service_id)
    if svc is None:
        return None
    if svc.owner_user_id == user.id:
        return svc
    if dynamic is not None and svc.dynamic_id == dynamic.id:
        member = (
            db.query(Membership)
            .filter(Membership.user_id == user.id, Membership.dynamic_id == dynamic.id)
            .first()
        )
        if member:
            return svc
    return None


def recommend_for_tool(tool: AiToolSpec) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for pid in tool.recommend_providers:
        cat = PROVIDER_CATALOG.get(pid) or {}
        out.append(
            {
                "provider": pid,
                "label": cat.get("label") or pid,
                "note": tool.recommend_note or (cat.get("policy_notes") or "")[:220],
                "key_url": cat.get("key_url") or "",
            }
        )
    return out


def tool_status(
    db: Session,
    user: User,
    dynamic: Dynamic | None,
    tool_id: str,
) -> ToolStatus:
    tool = AI_TOOLS.get(tool_id)
    if tool is None:
        return ToolStatus(
            tool_id=tool_id,
            label=tool_id,
            configured=False,
            service_id=None,
            service_name=None,
            issue="Unknown AI tool.",
            needs_assignment=True,
            missing_caps=[],
            recommendations=[],
        )

    routes = get_tool_routes(dynamic)
    service_id = routes.get(tool_id)
    svc: AiService | None = None
    if service_id:
        svc = get_service_for_user(db, user, service_id, dynamic)

    if svc is None and any(n in (CAP_TEXT_NSFW, CAP_IMAGE_NSFW, CAP_IMAGE) for n in tool.needs):
        adult_id = getattr(user, "adult_ai_service_id", None)
        if adult_id:
            svc = get_service_for_user(db, user, adult_id, dynamic)

    if svc is None:
        default_id = getattr(user, "default_ai_service_id", None)
        if default_id:
            svc = get_service_for_user(db, user, default_id, dynamic)

    if svc is not None:
        if not service_is_ready(svc):
            return ToolStatus(
                tool_id=tool.id,
                label=tool.label,
                configured=False,
                service_id=svc.id,
                service_name=svc.name,
                issue=(
                    f"“{svc.name}” is incomplete — add API key / base URL / model "
                    "in Settings → AI connections."
                ),
                needs_assignment=False,
                missing_caps=list(tool.needs),
                recommendations=recommend_for_tool(tool),
            )
        ok, missing = service_satisfies(svc, tool.needs)
        if not ok:
            miss_labels = ", ".join(missing)
            return ToolStatus(
                tool_id=tool.id,
                label=tool.label,
                configured=False,
                service_id=svc.id,
                service_name=svc.name,
                issue=(
                    f"“{svc.name}” failed or has not passed probes for: {miss_labels}. "
                    "Run Batch test on that connection, or assign a different service "
                    "in Advanced AI routing."
                ),
                needs_assignment=False,
                missing_caps=missing,
                recommendations=recommend_for_tool(tool),
            )
        return ToolStatus(
            tool_id=tool.id,
            label=tool.label,
            configured=True,
            service_id=svc.id,
            service_name=svc.name,
            issue=None,
            needs_assignment=False,
            missing_caps=[],
            recommendations=[],
        )

    # No routed service — legacy single-key fallback for text tools only
    if CAP_IMAGE not in tool.needs and CAP_IMAGE_NSFW not in tool.needs:
        if is_llm_configured(user, dynamic):
            return ToolStatus(
                tool_id=tool.id,
                label=tool.label,
                configured=True,
                service_id=None,
                service_name="Legacy shared / account key",
                issue=None,
                needs_assignment=False,
                missing_caps=[],
                recommendations=[],
            )

    return ToolStatus(
        tool_id=tool.id,
        label=tool.label,
        configured=False,
        service_id=None,
        service_name=None,
        issue=(
            f"No AI service assigned for {tool.label}. "
            "Add a connection in Settings → AI, then assign it under Advanced AI routing."
            + (f" {tool.recommend_note}" if tool.recommend_note else "")
        ),
        needs_assignment=True,
        missing_caps=list(tool.needs),
        recommendations=recommend_for_tool(tool),
    )


def resolve_config_for_tool(
    db: Session,
    user: User,
    dynamic: Dynamic | None,
    tool_id: str,
) -> tuple[ResolvedLlmConfig, AiService | None]:
    st = tool_status(db, user, dynamic, tool_id)
    if st.service_id:
        svc = get_service_for_user(db, user, st.service_id, dynamic)
        if svc and service_is_ready(svc):
            return service_to_config(svc), svc
    return resolve_llm_config_for_dynamic(user, dynamic), None


def ensure_legacy_services(
    db: Session, user: User, dynamic: Dynamic | None = None
) -> list[AiService]:
    """Seed AiService rows from legacy user/shared LLM fields when empty."""
    existing = list_visible_services(db, user, dynamic)
    if existing:
        return existing

    created: list[AiService] = []
    if (user.llm_api_key or "").strip() or (user.llm_base_url or "").strip():
        catalog = PROVIDER_CATALOG.get(user.llm_provider) or {}
        svc = AiService(
            owner_user_id=user.id,
            dynamic_id=None,
            name="Account default",
            provider=user.llm_provider or LlmProvider.gemini.value,
            api_key=user.llm_api_key or "",
            model=user.llm_model or catalog.get("default_model") or "",
            base_url=user.llm_base_url or "",
            purpose="general",
        )
        db.add(svc)
        db.flush()
        user.default_ai_service_id = svc.id
        created.append(svc)

    if dynamic is not None and (
        (dynamic.shared_llm_api_key or "").strip()
        or (getattr(dynamic, "shared_llm_base_url", None) or "").strip()
    ):
        catalog = PROVIDER_CATALOG.get(dynamic.shared_llm_provider) or {}
        svc = AiService(
            owner_user_id=user.id,
            dynamic_id=dynamic.id,
            name="Shared dynamic AI",
            provider=dynamic.shared_llm_provider or LlmProvider.gemini.value,
            api_key=dynamic.shared_llm_api_key or "",
            model=dynamic.shared_llm_model or catalog.get("default_model") or "",
            base_url=getattr(dynamic, "shared_llm_base_url", None) or "",
            purpose="general",
        )
        db.add(svc)
        db.flush()
        if not user.default_ai_service_id:
            user.default_ai_service_id = svc.id
        routes = {
            tid: svc.id for tid, spec in AI_TOOLS.items() if CAP_IMAGE not in spec.needs
        }
        set_tool_routes(dynamic, routes)
        created.append(svc)

    if created:
        db.commit()
    return list_visible_services(db, user, dynamic)


def service_out(svc: AiService) -> dict[str, Any]:
    return {
        "id": svc.id,
        "name": svc.name,
        "provider": svc.provider,
        "model": svc.model,
        "image_model": svc.image_model or "",
        "base_url": svc.base_url or "",
        "purpose": svc.purpose or "general",
        "dynamic_id": svc.dynamic_id,
        "api_key_set": bool((svc.api_key or "").strip()),
        "api_key_hint": mask_api_key(svc.api_key),
        "cap_text": svc.cap_text,
        "cap_text_nsfw": svc.cap_text_nsfw,
        "cap_image": svc.cap_image,
        "cap_image_nsfw": svc.cap_image_nsfw,
        "last_tested_at": svc.last_tested_at.isoformat() + "Z" if svc.last_tested_at else None,
        "test_log": _safe_json_list(svc.test_log),
        "ready": service_is_ready(svc),
    }


def _safe_json_list(raw: str | None) -> list:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def run_capability_probe(
    db: Session,
    *,
    user: User,
    svc: AiService,
    dynamic: Dynamic | None = None,
) -> AiService:
    """Batch-test text / NSFW text / image / NSFW image and store results."""
    from .llm import generate_text_with_config
    from .openai_client import generate_image_openai_compatible

    cfg = service_to_config(svc)
    log: list[dict[str, Any]] = []

    def _try_text(label: str, prompt: str, system: str) -> bool:
        try:
            reply = generate_text_with_config(
                config=cfg,
                user=user,
                user_prompt=prompt,
                dynamic_context="Capability probe — ignore relationship context.",
                system_instruction=system,
                dynamic=dynamic,
            )
            ok = bool(reply and len(reply.strip()) > 0)
            log.append({"probe": label, "ok": ok, "detail": (reply or "")[:160]})
            return ok
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            log.append({"probe": label, "ok": False, "detail": detail[:300]})
            return False
        except Exception as exc:  # noqa: BLE001
            log.append({"probe": label, "ok": False, "detail": str(exc)[:300]})
            return False

    svc.cap_text = _try_text(
        CAP_TEXT,
        "Reply with exactly this token and nothing else: UBETRA_OK",
        "You are a connectivity probe. Reply with exactly: UBETRA_OK",
    )
    svc.cap_text_nsfw = _try_text(
        CAP_TEXT_NSFW,
        (
            "This is a consensual adult BDSM capability probe between adults. "
            "Reply with exactly UBETRA_NSFW_OK if you can discuss chastity, denial, "
            "and erotic service without refusing. One short sentence of compliance is enough."
        ),
        (
            "You assist a private consensual adult D/s app. "
            "Do not refuse adult sexual content between consenting adults. "
            "If allowed, reply starting with UBETRA_NSFW_OK."
        ),
    )

    image_capable_providers = {
        LlmProvider.openai.value,
        LlmProvider.openrouter.value,
        LlmProvider.openai_compatible.value,
        LlmProvider.lmstudio.value,
    }
    if svc.provider in image_capable_providers:
        img_model = (svc.image_model or "").strip() or (
            "dall-e-3" if svc.provider == LlmProvider.openai.value else (svc.model or "dall-e-3")
        )
        key = cfg.api_key if cfg.api_key != "local" else ""

        def _try_image(label: str, prompt: str) -> bool:
            try:
                url = generate_image_openai_compatible(
                    api_key=key,
                    prompt=prompt,
                    model=img_model,
                    base_url=cfg.base_url or None,
                    size="512x512",
                )
                ok = bool(url)
                log.append({"probe": label, "ok": ok, "detail": "image ok" if ok else "empty"})
                return ok
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                log.append({"probe": label, "ok": False, "detail": detail[:300]})
                return False
            except Exception as exc:  # noqa: BLE001
                log.append({"probe": label, "ok": False, "detail": str(exc)[:300]})
                return False

        svc.cap_image = _try_image(
            CAP_IMAGE,
            "Simple line-art sketch of two coffee mugs on a table, clean manga style, SFW",
        )
        svc.cap_image_nsfw = _try_image(
            CAP_IMAGE_NSFW,
            (
                "Consensual adult manga panel: clothed dominant and kneeling adult submissive, "
                "tasteful erotic tension, no minors, private artistic study"
            ),
        )
    else:
        svc.cap_image = False
        svc.cap_image_nsfw = False
        log.append(
            {
                "probe": CAP_IMAGE,
                "ok": False,
                "detail": f"Provider {svc.provider} has no image generation path in UBETRA yet.",
            }
        )
        log.append(
            {
                "probe": CAP_IMAGE_NSFW,
                "ok": False,
                "detail": "Skipped — no image endpoint for this provider.",
            }
        )

    svc.last_tested_at = datetime.utcnow()
    svc.test_log = json.dumps(log)
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return svc
