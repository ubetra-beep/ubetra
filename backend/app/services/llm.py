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
        "policy_notes": "Uses whatever model the server admin configured. Content filtering depends on that provider's policy. For fewer adult blocks, point the server at a local LM Studio / OpenRouter uncensored model instead of Gemini/OpenAI.",
        "default_model": normalize_gemini_model(settings.gemini_model),
        "models": list(
            dict.fromkeys(
                [normalize_gemini_model(settings.gemini_model), *GEMINI_MODELS]
            )
        ),
        "key_url": "",
        "needs_base_url": False,
        "default_base_url": "",
        "allow_empty_key": False,
    },
    LlmProvider.gemini.value: {
        "label": "Google Gemini",
        "description": "API key from Google AI Studio. Strong general model; check Google's safety settings for adult content.",
        "policy_notes": "Google applies safety filters by default. Consensual adult/BDSM text may still be blocked. Best for structured tasks when content is mild. For explicit scene writing or manga, prefer LM Studio (local uncensored) or OpenRouter models marketed as uncensored. Gemini 2.0/2.5 Flash IDs are retired — use gemini-3.5-flash.",
        "default_model": DEFAULT_GEMINI_MODEL,
        "models": list(GEMINI_MODELS),
        "key_url": "https://aistudio.google.com/apikey",
        "needs_base_url": False,
        "default_base_url": "",
        "allow_empty_key": False,
    },
    LlmProvider.openai.value: {
        "label": "OpenAI",
        "description": "API key from platform.openai.com. Widely used; content may be filtered under usage policies.",
        "policy_notes": "OpenAI restricts some explicit sexual content in API use. Often more permissive for consensual adult scene planning than consumer ChatGPT, but still policy-bound. Image models (DALL·E) frequently refuse NSFW manga panels — use script/hybrid modes or a local image pipeline.",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
        "key_url": "https://platform.openai.com/api-keys",
        "needs_base_url": False,
        "default_base_url": "https://api.openai.com/v1",
        "allow_empty_key": False,
    },
    LlmProvider.openrouter.value: {
        "label": "OpenRouter",
        "description": "One key routes to many hosted models (including community / uncensored options).",
        "policy_notes": "Filtering depends on the underlying model you pick. For adult D/s text, prefer models labeled uncensored / abliterated / NSFW-friendly rather than frontier OpenAI/Anthropic/Google models (those often still refuse). Images follow each model's rules — many refuse explicit art. Good middle ground when you cannot run local LM Studio.",
        "default_model": "openrouter/auto",
        "models": [
            "openrouter/auto",
            "nousresearch/hermes-3-llama-3.1-70b",
            "cognitivecomputations/dolphin-mixtral-8x22b",
            "microsoft/wizardlm-2-8x22b",
            "meta-llama/llama-3.1-70b-instruct",
        ],
        "key_url": "https://openrouter.ai/keys",
        "needs_base_url": False,
        "default_base_url": "https://openrouter.ai/api/v1",
        "allow_empty_key": False,
    },
    LlmProvider.lmstudio.value: {
        "label": "LM Studio (local)",
        "description": "OpenAI-compatible local server (LM Studio). Best option for uncensored adult content you control.",
        "policy_notes": "Best for not getting blocked: load an uncensored / abliterated GGUF in LM Studio, enable the local server, and point UBETRA at its base URL (e.g. http://192.168.1.10:1234/v1). The Docker/server host must reach that URL (LAN or VPN). No vendor safety layer — you own the hardware and privacy. API key is often optional (use any placeholder if required).",
        "default_model": "local-model",
        "models": ["local-model"],
        "key_url": "https://lmstudio.ai/",
        "needs_base_url": True,
        "default_base_url": "http://127.0.0.1:1234/v1",
        "allow_empty_key": True,
    },
    LlmProvider.openai_compatible.value: {
        "label": "OpenAI-compatible",
        "description": "Any chat-completions endpoint: Ollama, text-generation-webui, Together, Fireworks, etc.",
        "policy_notes": "Same as LM Studio when you self-host: pick an uncensored model to avoid adult blocks. Hosted proxies may still enforce their own policies — read the provider docs. Enter the full API root ending in /v1 when applicable.",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "llama3.1", "mixtral"],
        "key_url": "",
        "needs_base_url": True,
        "default_base_url": "http://127.0.0.1:11434/v1",
        "allow_empty_key": True,
    },
}


@dataclass
class ResolvedLlmConfig:
    provider: str
    api_key: str
    model: str
    using_server_default: bool
    base_url: str = ""


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


def _provider_base_url(provider: str, stored: str | None = None) -> str:
    catalog = PROVIDER_CATALOG.get(provider) or {}
    custom = (stored or "").strip()
    if custom:
        return custom.rstrip("/")
    return (catalog.get("default_base_url") or "").rstrip("/")


def resolve_llm_config_for_dynamic(user: User, dynamic: Dynamic | None = None) -> ResolvedLlmConfig:
    shared_key = (dynamic.shared_llm_api_key or "").strip() if dynamic is not None else ""
    shared_provider = (dynamic.shared_llm_provider or "").strip() if dynamic is not None else ""
    shared_base = (getattr(dynamic, "shared_llm_base_url", None) or "").strip() if dynamic else ""
    if dynamic is not None and (shared_key or (shared_provider and shared_base)):
        provider = shared_provider or LlmProvider.gemini.value
        catalog = PROVIDER_CATALOG.get(provider, PROVIDER_CATALOG[LlmProvider.gemini.value])
        key = shared_key
        if not key and catalog.get("allow_empty_key"):
            key = "local"
        return ResolvedLlmConfig(
            provider=provider,
            api_key=key,
            model=_maybe_normalize_model(
                provider, dynamic.shared_llm_model or catalog["default_model"]
            ),
            using_server_default=False,
            base_url=_provider_base_url(provider, shared_base),
        )

    # LM Studio / compatible may use base_url without a real key
    provider = user.llm_provider or LlmProvider.server.value
    if provider == LlmProvider.server.value:
        return ResolvedLlmConfig(
            provider=provider,
            api_key=settings.gemini_api_key.strip(),
            model=_maybe_normalize_model(
                provider, settings.gemini_model or DEFAULT_GEMINI_MODEL
            ),
            using_server_default=True,
            base_url="",
        )

    catalog = PROVIDER_CATALOG.get(provider, PROVIDER_CATALOG[LlmProvider.gemini.value])
    model = _maybe_normalize_model(provider, user.llm_model or catalog["default_model"])
    key = (user.llm_api_key or "").strip()
    if not key and catalog.get("allow_empty_key"):
        key = "local"
    return ResolvedLlmConfig(
        provider=provider,
        api_key=key,
        model=model,
        using_server_default=False,
        base_url=_provider_base_url(provider, getattr(user, "llm_base_url", None)),
    )


def is_llm_configured(user: User, dynamic: Dynamic | None = None) -> bool:
    config = resolve_llm_config_for_dynamic(user, dynamic)
    catalog = PROVIDER_CATALOG.get(config.provider) or {}
    if catalog.get("needs_base_url") and not config.base_url:
        return False
    if catalog.get("allow_empty_key"):
        return bool(config.model and config.base_url)
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
        had_shared = bool(
            (dynamic.shared_llm_api_key or "").strip()
            or (getattr(dynamic, "shared_llm_base_url", None) or "").strip()
        )
        if not had_shared and not clear and not (user.llm_api_key or "").strip() and not (
            getattr(user, "llm_base_url", None) or ""
        ).strip():
            continue
        if clear:
            dynamic.shared_llm_api_key = ""
            dynamic.shared_llm_base_url = ""
        else:
            dynamic.shared_llm_provider = user.llm_provider or LlmProvider.gemini.value
            dynamic.shared_llm_model = user.llm_model or dynamic.shared_llm_model
            if (getattr(user, "llm_base_url", None) or "").strip():
                dynamic.shared_llm_base_url = user.llm_base_url.strip()
            if (user.llm_api_key or "").strip():
                dynamic.shared_llm_api_key = user.llm_api_key.strip()
                dynamic.shared_llm_set_by_membership_id = membership.id
            elif PROVIDER_CATALOG.get(dynamic.shared_llm_provider, {}).get("allow_empty_key"):
                dynamic.shared_llm_set_by_membership_id = membership.id
                if not (dynamic.shared_llm_api_key or "").strip():
                    dynamic.shared_llm_api_key = "local"
        if had_shared or (user.llm_api_key or "").strip() or (
            getattr(user, "llm_base_url", None) or ""
        ).strip():
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

    openai_like = {
        LlmProvider.openai.value,
        LlmProvider.openrouter.value,
        LlmProvider.lmstudio.value,
        LlmProvider.openai_compatible.value,
    }
    if config.provider in openai_like:
        from .openai_client import generate_openai_compatible_text

        extra = {}
        if config.provider == LlmProvider.openrouter.value:
            extra = {
                "HTTP-Referer": (settings.public_app_url or "https://ubetra.local").rstrip("/"),
                "X-Title": "UBETRA",
            }
        return generate_openai_compatible_text(
            api_key=config.api_key if config.api_key != "local" else "",
            model=config.model,
            system_instruction=instruction,
            user_prompt=prompt,
            base_url=config.base_url or None,
            extra_headers=extra or None,
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
