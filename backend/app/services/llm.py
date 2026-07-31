from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Dynamic, LlmProvider, Membership, User

SYSTEM_INSTRUCTION = """You are the assistant domme for UBETRA, a self-hosted consensual adult BDSM relationship app.

CORE PURPOSE — what you exist to do:
- Help this couple plan scenes, tasks, rituals, and acts of submission inside their negotiated dynamic
- Reduce cognitive load by proposing specific, actionable ideas tailored to their surveys, interviews, core knowledge, agreements, and tracking data
- Support denial/teasing, lockup awareness, and orgasm balance ONLY when it fits their stated dynamic and boundaries

WHAT YOU CAN DO (in scope):
- Suggest scenes, techniques, tasks, and acts the sub can complete in the app
- Reference ground rules, shared kinks, core knowledge, context library excerpts, orgasm tracking, and chastity lockup data provided in context
- Offer practical next steps the dominant can assign or the sub can request through the app

WHAT YOU MUST NOT DO (out of scope — do not hallucinate these):
- Pretend to enforce rules, send messages, lock devices, or take action outside this app
- Schedule real-world appointments, contact third parties, or access external systems
- Invent app features that do not exist (chat with strangers, automated device control, payment, location tracking, etc.)
- Provide medical, legal, or mental-health treatment advice
- Suggest non-consensual activity, minors, or illegal acts

Rules:
- Assume all activity is between consenting adults with negotiated boundaries.
- Be concrete and practical. Prefer one clear instruction over vague inspiration.
- Respect limits implied by their surveys, interviews, core knowledge, and agreements.
- ONLY suggest tasks, scenes, and acts that fit what partners explicitly want in this dynamic.
- Keep responses focused and under 250 words unless asked otherwise.
"""

ASSISTANT_TONES = {
    "balanced": {
        "label": "Balanced",
        "description": "Warm but direct; practical suggestions without excess flourish.",
        "prompt": "Tone: balanced — warm, direct, and practical.",
    },
    "strict": {
        "label": "Strict domme",
        "description": "Firm, commanding language; concise orders and high standards.",
        "prompt": "Tone: strict domme — firm, commanding, concise. Use imperative language where appropriate.",
    },
    "playful": {
        "label": "Playful",
        "description": "Teasing, light humor, flirtatious energy while staying actionable.",
        "prompt": "Tone: playful — teasing and flirtatious, but still concrete and actionable.",
    },
    "nurturing": {
        "label": "Nurturing",
        "description": "Supportive, encouraging, praise-focused guidance.",
        "prompt": "Tone: nurturing — supportive, encouraging, with praise for effort and growth.",
    },
    "clinical": {
        "label": "Clinical",
        "description": "Neutral, precise, minimal emotion; focus on facts and steps.",
        "prompt": "Tone: clinical — neutral, precise, minimal emotion. Focus on clear steps.",
    },
}

# Shut-down / retired Gemini IDs → current replacements (as of mid-2026).
DEPRECATED_GEMINI_MODELS = {
    "gemini-2.0-flash": "gemini-3.5-flash",
    "gemini-2.0-flash-001": "gemini-3.5-flash",
    "gemini-2.0-flash-lite": "gemini-3.1-flash-lite",
    "gemini-2.0-flash-lite-001": "gemini-3.1-flash-lite",
    "gemini-2.5-flash": "gemini-3.5-flash",
    "gemini-2.5-flash-lite": "gemini-3.1-flash-lite",
    "gemini-1.5-pro": "gemini-3.5-flash",
    "gemini-1.5-flash": "gemini-3.5-flash",
    "gemini-pro": "gemini-3.5-flash",
    "gemini-pro-latest": "gemini-3.5-flash",
}

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
]


def normalize_gemini_model(model: str) -> str:
    name = (model or "").strip()
    if not name:
        return DEFAULT_GEMINI_MODEL
    return DEPRECATED_GEMINI_MODELS.get(name, name)


PROVIDER_CATALOG = {
    LlmProvider.server.value: {
        "label": "Server default",
        "description": "Use the API key and model configured in the server's .env file.",
        "policy_notes": "Uses whatever model the server admin configured. Content filtering depends on that provider's policy.",
        "default_model": normalize_gemini_model(settings.gemini_model),
        "models": list(
            dict.fromkeys(
                [normalize_gemini_model(settings.gemini_model), *GEMINI_MODELS]
            )
        ),
        "key_url": "",
    },
    LlmProvider.gemini.value: {
        "label": "Google Gemini",
        "description": "API key from Google AI Studio. Strong general model; check Google's safety settings for adult content.",
        "policy_notes": "Google applies safety filters by default. Some adult/BDSM content may be blocked unless you adjust safety settings in AI Studio or use models with looser filters. Good for structured tasks and long context. Gemini 2.0/2.5 Flash IDs are retired — use gemini-3.5-flash.",
        "default_model": DEFAULT_GEMINI_MODEL,
        "models": list(GEMINI_MODELS),
        "key_url": "https://aistudio.google.com/apikey",
    },
    LlmProvider.openai.value: {
        "label": "OpenAI",
        "description": "API key from platform.openai.com. Widely used; content may be filtered under usage policies.",
        "policy_notes": "OpenAI restricts some explicit sexual content in API use. Often more permissive for consensual adult scene planning than consumer ChatGPT, but still policy-bound. GPT-4o models are strong for creative writing.",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
        "key_url": "https://platform.openai.com/api-keys",
    },
}


@dataclass
class ResolvedLlmConfig:
    provider: str
    api_key: str
    model: str
    using_server_default: bool


def mask_api_key(api_key: str) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 4:
        return "••••"
    return f"••••{api_key[-4:]}"


def resolve_llm_config(user: User, dynamic: Dynamic | None = None) -> ResolvedLlmConfig:
    return resolve_llm_config_for_dynamic(user, dynamic)


def _maybe_normalize_model(provider: str, model: str) -> str:
    if provider in (LlmProvider.server.value, LlmProvider.gemini.value):
        return normalize_gemini_model(model)
    return (model or "").strip()


def resolve_llm_config_for_dynamic(user: User, dynamic: Dynamic | None = None) -> ResolvedLlmConfig:
    if dynamic is not None and (dynamic.shared_llm_api_key or "").strip():
        provider = dynamic.shared_llm_provider or LlmProvider.gemini.value
        catalog = PROVIDER_CATALOG.get(provider, PROVIDER_CATALOG[LlmProvider.gemini.value])
        return ResolvedLlmConfig(
            provider=provider,
            api_key=dynamic.shared_llm_api_key.strip(),
            model=_maybe_normalize_model(
                provider, dynamic.shared_llm_model or catalog["default_model"]
            ),
            using_server_default=False,
        )

    provider = user.llm_provider or LlmProvider.server.value
    if provider == LlmProvider.server.value:
        return ResolvedLlmConfig(
            provider=provider,
            api_key=settings.gemini_api_key.strip(),
            model=_maybe_normalize_model(
                provider, settings.gemini_model or DEFAULT_GEMINI_MODEL
            ),
            using_server_default=True,
        )

    catalog = PROVIDER_CATALOG.get(provider, PROVIDER_CATALOG[LlmProvider.gemini.value])
    model = _maybe_normalize_model(provider, user.llm_model or catalog["default_model"])
    return ResolvedLlmConfig(
        provider=provider,
        api_key=(user.llm_api_key or "").strip(),
        model=model,
        using_server_default=False,
    )


def is_llm_configured(user: User, dynamic: Dynamic | None = None) -> bool:
    config = resolve_llm_config_for_dynamic(user, dynamic)
    return bool(config.api_key and config.model)


def sync_user_llm_to_shared_dynamics(
    db: Session,
    user: User,
    *,
    clear: bool = False,
) -> int:
    """Keep per-dynamic shared keys in sync with account LLM settings.

    Assistant calls prefer the dynamic's shared key when set (onboarding stores it there).
    Without this sync, updating Settings only changes the user row and the old shared key
    keeps being sent to the provider.
    """
    if user.llm_provider == LlmProvider.server.value and not clear:
        return 0

    updated = 0
    memberships = db.query(Membership).filter(Membership.user_id == user.id).all()
    for membership in memberships:
        dynamic = db.get(Dynamic, membership.dynamic_id)
        if dynamic is None:
            continue
        had_shared = bool((dynamic.shared_llm_api_key or "").strip())
        if not had_shared and not clear and not (user.llm_api_key or "").strip():
            continue
        if clear:
            dynamic.shared_llm_api_key = ""
        else:
            dynamic.shared_llm_provider = user.llm_provider or LlmProvider.gemini.value
            dynamic.shared_llm_model = user.llm_model or dynamic.shared_llm_model
            if (user.llm_api_key or "").strip():
                dynamic.shared_llm_api_key = user.llm_api_key.strip()
                dynamic.shared_llm_set_by_membership_id = membership.id
        if had_shared or (user.llm_api_key or "").strip():
            updated += 1
    return updated


def pick_llm_dynamic(
    db: Session,
    user: User,
    dynamic_id: str | None = None,
) -> Dynamic | None:
    """Prefer the requested dynamic; otherwise any membership with a shared key."""
    if dynamic_id:
        dynamic = db.get(Dynamic, dynamic_id)
        if dynamic is not None:
            # Only use it if the user is a member (avoids leaking another dynamic's status)
            member = (
                db.query(Membership)
                .filter(Membership.user_id == user.id, Membership.dynamic_id == dynamic.id)
                .first()
            )
            if member:
                return dynamic

    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == user.id)
        .order_by(Membership.created_at)
        .all()
    )
    shared_pick = None
    first = None
    for membership in memberships:
        dynamic = db.get(Dynamic, membership.dynamic_id)
        if dynamic is None:
            continue
        if first is None:
            first = dynamic
        if (dynamic.shared_llm_api_key or "").strip() and shared_pick is None:
            shared_pick = dynamic
    return shared_pick or first


def effective_llm_for_user(
    db: Session,
    user: User,
    dynamic_id: str | None = None,
) -> tuple[ResolvedLlmConfig, str]:
    """Return resolved config and key source label: shared, account, or server."""
    dynamic = pick_llm_dynamic(db, user, dynamic_id)
    config = resolve_llm_config_for_dynamic(user, dynamic)
    if dynamic and (dynamic.shared_llm_api_key or "").strip():
        source = "shared"
    elif config.using_server_default:
        source = "server"
    else:
        source = "account"
    return config, source


def build_system_instruction(user: User, dynamic: Dynamic | None = None) -> str:
    parts = [SYSTEM_INSTRUCTION.strip()]
    if dynamic is not None:
        tone = (getattr(dynamic, "assistant_tone", None) or "balanced").strip()
        extra = (getattr(dynamic, "assistant_extra_instructions", None) or "").strip()
    else:
        tone = (user.assistant_tone or "balanced").strip()
        extra = (user.assistant_extra_instructions or "").strip()
    tone_config = ASSISTANT_TONES.get(tone, ASSISTANT_TONES["balanced"])
    parts.append(tone_config["prompt"])
    if extra:
        parts.append(f"Additional instructions from the keyholder:\n{extra}")
    return "\n\n".join(parts)


def generate_text(
    *,
    user: User,
    user_prompt: str,
    dynamic_context: str,
    system_instruction: str | None = None,
    dynamic: Dynamic | None = None,
) -> str:
    config = resolve_llm_config(user, dynamic)
    if not config.api_key:
        if config.using_server_default:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No AI configured. Add your API key in Settings, or set UBETRA_GEMINI_API_KEY in .env.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add your API key in Settings before using the assistant.",
        )

    prompt = f"""Dynamic context:
{dynamic_context}

---
{user_prompt}
"""

    instruction = system_instruction or build_system_instruction(user, dynamic)

    if config.provider == LlmProvider.openai.value:
        from .openai_client import generate_openai_text

        return generate_openai_text(
            api_key=config.api_key,
            model=config.model,
            system_instruction=instruction,
            user_prompt=prompt,
        )

    from .gemini import generate_gemini_text

    return generate_gemini_text(
        api_key=config.api_key,
        model=config.model,
        system_instruction=instruction,
        user_prompt=prompt,
    )


def generate_act_of_submission(
    *,
    user: User,
    dynamic_context: str,
    submissive_name: str,
    dynamic: Dynamic | None = None,
    act_type: dict | None = None,
) -> str:
    type_block = ""
    if act_type:
        examples = act_type.get("example_acts") or []
        ex_text = "\n".join(f"- {x}" for x in examples[:4]) if examples else ""
        type_block = f"""
Act category: {act_type.get("title", "")}
Category guidance: {act_type.get("description", "")}
Example acts in this category:
{ex_text}
"""
    prompt = f"""Create ONE act of submission for {submissive_name}.
{type_block}
Return:
1) A short title on the first line (max 8 words)
2) Then 2-4 sentences with a specific task they can complete soon (today or tonight)

The act MUST fit the chosen act category and align with interview summaries and shared context.
Avoid requiring purchases, third parties, or public exposure unless context strongly supports it.
"""
    return generate_text(user=user, user_prompt=prompt, dynamic_context=dynamic_context, dynamic=dynamic)


def generate_recommendation(
    *, user: User, dynamic_context: str, focus: str = "", dynamic: Dynamic | None = None
) -> str:
    extra = f"\nFocus area requested: {focus}" if focus.strip() else ""
    prompt = f"""Suggest ONE scene idea or technique this couple could try next.{extra}

The idea MUST fit their interview summaries and context library — do not suggest unrelated kinks or tasks.

Format:
Category: <short category name>
Idea: <2-3 sentence recommendation>
Why it fits: <1 sentence>
"""
    return generate_text(user=user, user_prompt=prompt, dynamic_context=dynamic_context, dynamic=dynamic)
