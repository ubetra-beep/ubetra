"""Picture requests from chat. The model list is the Gemini image family that has drawn adult stills on this account."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Dynamic, User
from .ai_services import get_tool_routes, resolve_config_for_tool, set_tool_routes
from .openai_client import generate_image_openai_compatible

ADULT_IMAGE_MODELS = [
    {
        "id": "google/gemini-2.5-flash-image",
        "label": "Nano Banana",
        "note": "Gemini 2.5 Flash Image. Drew adult pictures on this account.",
    },
    {
        "id": "google/gemini-3.1-flash-lite-image",
        "label": "Nano Banana 2 Lite",
        "note": "Faster model in the same Gemini image family.",
    },
    {
        "id": "google/gemini-3.1-flash-image",
        "label": "Nano Banana 2",
        "note": "Newer Gemini image model.",
    },
    {
        "id": "google/gemini-3-pro-image",
        "label": "Nano Banana Pro",
        "note": "Higher-detail Gemini image model.",
    },
    {
        "id": "x-ai/grok-imagine-image-2.0",
        "label": "Grok Imagine 2.0",
        "note": "OpenRouter image API. Refuses sexual images of real people.",
    },
    {
        "id": "bytedance-seed/seedream-5-0-flash",
        "label": "Seedream 5.0 Flash",
        "note": "OpenRouter image API.",
    },
    {
        "id": "black-forest-labs/flux.2-pro",
        "label": "FLUX.2 Pro",
        "note": "OpenRouter image API. Official Flux refuses adult prompts.",
    },
]

IMAGE_STYLES = [
    {"id": "art", "label": "Art"},
    {"id": "photo", "label": "Photo"},
]

IMAGE_TEMPLATES = [
    {"id": "custom", "label": "Custom", "prompt": ""},
    {
        "id": "portrait",
        "label": "Portrait",
        "prompt": "Close portrait of one adult, facing the camera.",
    },
    {
        "id": "couple",
        "label": "Couple",
        "prompt": "Two consenting adults close together, intimate.",
    },
    {
        "id": "scene",
        "label": "Scene",
        "prompt": "A consensual scene between a keyholder and a submissive. No names and no written text.",
    },
    {
        "id": "object",
        "label": "Object",
        "prompt": "A single object centered in the frame, no person, no written text.",
    },
]

_MODEL_IDS = {row["id"] for row in ADULT_IMAGE_MODELS}


def options() -> dict:
    return {
        "models": ADULT_IMAGE_MODELS,
        "styles": IMAGE_STYLES,
        "templates": IMAGE_TEMPLATES,
        "default_model": ADULT_IMAGE_MODELS[0]["id"],
        "default_style": "art",
    }


def _ensure_route(db: Session, dynamic: Dynamic) -> None:
    routes = get_tool_routes(dynamic)
    if routes.get("image_gen"):
        return
    previous = routes.get("manga_image")
    if previous:
        set_tool_routes(dynamic, {"image_gen": previous})
        db.commit()


def generate_picture(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    model: str,
    style: str,
    prompt: str,
) -> str:
    chosen = (model or "").strip()
    if chosen not in _MODEL_IDS:
        chosen = ADULT_IMAGE_MODELS[0]["id"]
    text = " ".join((prompt or "").split())
    if len(text) < 3:
        raise ValueError("Describe the picture you want.")
    if len(text) > 1200:
        text = text[:1200]
    _ensure_route(db, dynamic)
    cfg, _image_svc = resolve_config_for_tool(db, user, dynamic, "image_gen")
    if style == "photo":
        lead = (
            "Photorealistic photograph, natural light, sharp detail. "
            "No text, no letters, no watermark, no usernames."
        )
    else:
        lead = (
            "Illustrated artwork, drawn style, clear shapes. "
            "No text, no letters, no watermark, no usernames."
        )
    return generate_image_openai_compatible(
        api_key=cfg.api_key if cfg.api_key != "local" else "",
        prompt=f"{lead} {text}"[:1400],
        model=chosen,
        base_url=cfg.base_url or None,
    )
