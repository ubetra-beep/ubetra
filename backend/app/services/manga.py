from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..models import Dynamic, MangaComic, MangaPanel, Membership, User
from .ai_services import resolve_config_for_tool, tool_status
from .context import build_dynamic_context
from .features import is_feature_enabled
from .llm import generate_text, is_llm_configured
from .openai_client import generate_image_openai_compatible

MODE_WARNINGS = {
    "script": (
        "Script / storyboard mode uses text only. Hosted models (Gemini/OpenAI) may still "
        "refuse explicit content — prefer LM Studio or an uncensored OpenRouter model."
    ),
    "hybrid": (
        "Hybrid mode asks for AI images when possible and falls back to captioned frames. "
        "Most hosted image APIs refuse NSFW manga — expect partial panels or refusals."
    ),
    "full": (
        "Full panel mode tries to generate an image for every panel. Adult/BDSM art is often "
        "blocked by DALL·E / Gemini Imagen / many OpenRouter image models. Use a local image "
        "pipeline or accept script fallbacks when providers refuse."
    ),
}


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        return json.loads(match.group(0))
    raise ValueError("Model did not return JSON")


def year_month_now() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def list_comics(db: Session, dynamic_id: str) -> list[MangaComic]:
    return (
        db.query(MangaComic)
        .options(joinedload(MangaComic.panels))
        .filter(MangaComic.dynamic_id == dynamic_id)
        .order_by(MangaComic.year_month.desc(), MangaComic.created_at.desc())
        .all()
    )


def get_month_comic(db: Session, dynamic_id: str, year_month: str | None = None) -> MangaComic | None:
    ym = year_month or year_month_now()
    return (
        db.query(MangaComic)
        .options(joinedload(MangaComic.panels))
        .filter(MangaComic.dynamic_id == dynamic_id, MangaComic.year_month == ym)
        .order_by(MangaComic.updated_at.desc())
        .first()
    )


def generate_manga(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
    mode: str,
    replace_draft: bool = True,
) -> MangaComic:
    if not is_feature_enabled(dynamic, "manga_comics"):
        raise HTTPException(status_code=403, detail="Monthly manga is not enabled for this dynamic.")
    if mode not in MODE_WARNINGS:
        raise HTTPException(status_code=400, detail="Unknown manga mode")
    script_st = tool_status(db, user, dynamic, "manga_script")
    if not script_st.configured and not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=400,
            detail=script_st.issue or "Configure an AI provider for manga scripts first.",
        )

    ym = year_month_now()
    existing = get_month_comic(db, dynamic.id, ym)
    if existing and existing.status == "saved" and not replace_draft:
        raise HTTPException(
            status_code=409,
            detail="This month already has a saved comic. Only one saved comic per month.",
        )
    if existing and existing.status == "saved":
        raise HTTPException(
            status_code=409,
            detail="This month’s comic is already saved. Wait until next month or delete it as Dom.",
        )

    context = build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=membership.id,
        include_tracking=True,
    )
    prompt = f"""Create a short consensual adult manga comic about this couple's dynamic for this month.

Return ONLY JSON with this shape:
{{
  "title": "short title",
  "panels": [
    {{
      "caption": "narration / scene setting",
      "dialogue": "spoken lines",
      "visual_prompt": "detailed visual description for an illustrator, manga style, SFW-leaning wording if needed"
    }}
  ]
}}

Rules:
- 4 to 8 panels
- Stay inside negotiated boundaries from the context
- Be concrete and story-shaped (beginning, tension, close)
- Mode requested: {mode}
"""
    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=context,
        dynamic=dynamic,
        tool_id="manga_script",
        db=db,
    )
    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manga JSON parse failed: {exc}",
        ) from exc

    title = str(data.get("title") or f"Comic {ym}").strip()[:200]
    panels_in = data.get("panels") or []
    if not isinstance(panels_in, list) or not panels_in:
        raise HTTPException(status_code=502, detail="Manga had no panels")

    warnings = [MODE_WARNINGS[mode]]
    image_cfg, image_svc = resolve_config_for_tool(db, user, dynamic, "manga_image")
    want_images = mode in ("hybrid", "full")
    image_st = tool_status(db, user, dynamic, "manga_image")
    if want_images and not image_st.configured:
        warnings.append(image_st.issue or "No image AI service assigned — using captioned frames.")
        want_images = False

    if existing:
        for panel in list(existing.panels):
            db.delete(panel)
        comic = existing
        comic.title = title
        comic.mode = mode
        comic.status = "draft"
        comic.warnings_json = json.dumps(warnings)
        comic.created_by_membership_id = membership.id
    else:
        comic = MangaComic(
            dynamic_id=dynamic.id,
            created_by_membership_id=membership.id,
            year_month=ym,
            title=title,
            mode=mode,
            status="draft",
            warnings_json=json.dumps(warnings),
        )
        db.add(comic)
        db.flush()

    img_model = "dall-e-3"
    if image_svc and (image_svc.image_model or "").strip():
        img_model = image_svc.image_model.strip()
    elif image_cfg.model:
        img_model = image_cfg.model

    for idx, panel in enumerate(panels_in[:8]):
        if not isinstance(panel, dict):
            continue
        caption = str(panel.get("caption") or "").strip()
        dialogue = str(panel.get("dialogue") or "").strip()
        visual = str(panel.get("visual_prompt") or caption or dialogue).strip()
        image_data = ""
        image_error = ""
        if want_images:
            try:
                image_data = generate_image_openai_compatible(
                    api_key=image_cfg.api_key if image_cfg.api_key != "local" else "",
                    prompt=(
                        "Manga panel, black and white ink, adult consensual couple, "
                        f"{visual}"
                    )[:1000],
                    model=img_model,
                    base_url=image_cfg.base_url or "https://api.openai.com/v1",
                )
            except HTTPException as exc:
                image_error = str(exc.detail)
                warnings.append(f"Panel {idx + 1} image refused/failed: {image_error}")
                if mode == "full":
                    pass
        row = MangaPanel(
            comic_id=comic.id,
            position=idx,
            caption=caption,
            dialogue=dialogue,
            visual_prompt=visual,
            image_data=image_data,
            image_error=image_error,
        )
        db.add(row)

    comic.warnings_json = json.dumps(list(dict.fromkeys(warnings)))
    db.flush()
    db.refresh(comic)
    return (
        db.query(MangaComic)
        .options(joinedload(MangaComic.panels))
        .filter(MangaComic.id == comic.id)
        .one()
    )


def save_comic(db: Session, comic: MangaComic) -> MangaComic:
    comic.status = "saved"
    db.flush()
    return comic
