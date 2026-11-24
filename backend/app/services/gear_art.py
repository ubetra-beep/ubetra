"""Pictures of gear, drawn once and reused in the menu, scenes, and chat."""

from __future__ import annotations

import base64
import io
import logging
import re
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import DATA_DIR
from ..database import SessionLocal
from ..models import AiService, Dynamic, GearArt, GearInventoryItem, User
from .gear_catalog import catalog_items
from .openai_client import generate_image_openai_compatible

_lock = threading.Lock()
_running: set[str] = set()
log = logging.getLogger(__name__)

ART_ROOT = DATA_DIR / "gear_art"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:60] or "item"


def _safe_key(item_key: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_-]", "", item_key or "")
    if not key or key != item_key:
        raise ValueError("bad gear key")
    return key


def art_path(dynamic_id: str, item_key: str) -> Path:
    return ART_ROOT / _safe_key(dynamic_id) / f"{_safe_key(item_key)}.png"


def list_gear_entries(db: Session, dynamic_id: str) -> list[dict]:
    """Catalog items plus custom inventory, with stable chat slugs."""
    custom = (
        db.query(GearInventoryItem)
        .filter(
            GearInventoryItem.dynamic_id == dynamic_id,
            GearInventoryItem.is_custom.is_(True),
        )
        .order_by(GearInventoryItem.name)
        .all()
    )
    owned = {
        item.catalog_item_id: item
        for item in db.query(GearInventoryItem)
        .filter(GearInventoryItem.dynamic_id == dynamic_id, GearInventoryItem.catalog_item_id.isnot(None))
        .all()
    }
    rows: list[dict] = []
    for entry in catalog_items():
        inv = owned.get(entry["id"])
        rows.append(
            {
                "key": entry["id"],
                "name": entry["name"],
                "notes": entry.get("notes") or "",
                "owned": bool(inv and inv.owned),
                "want": bool(inv and inv.want),
            }
        )
    for item in custom:
        rows.append(
            {
                "key": f"custom_{item.id}",
                "name": item.name,
                "notes": item.notes or "",
                "owned": bool(item.owned),
                "want": bool(item.want),
            }
        )
    used: set[str] = set()
    for row in rows:
        base = slugify(row["name"])
        slug = base
        n = 2
        while slug in used:
            slug = f"{base}-{n}"
            n += 1
        used.add(slug)
        row["slug"] = slug
        row["has_image"] = art_path(dynamic_id, row["key"]).is_file()
    return rows


def suggest(entries: list[dict], query: str, limit: int = 5) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return entries[:limit]
    starts = [
        row for row in entries
        if row["name"].lower().startswith(q) or row["slug"].startswith(q)
    ]
    contains = [
        row for row in entries
        if row not in starts and (q in row["name"].lower() or q in row["slug"])
    ]
    return (starts + contains)[:limit]


def knockout_background(image):
    """Drop a plain light backdrop so chat emojis are not white squares."""
    image = image.convert("RGBA")
    width, height = image.size
    if width < 2 or height < 2:
        return image
    pixels = image.load()
    corners = (
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    )
    br = sum(p[0] for p in corners) // 4
    bg = sum(p[1] for p in corners) // 4
    bb = sum(p[2] for p in corners) // 4
    if (br + bg + bb) / 3 < 210:
        return image
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            dist = abs(red - br) + abs(green - bg) + abs(blue - bb)
            if dist < 42:
                pixels[x, y] = (red, green, blue, 0)
            elif dist < 90:
                fade = int(255 * (dist - 42) / 48)
                pixels[x, y] = (red, green, blue, min(alpha, fade))
    return image


def _shrink(data_url: str) -> bytes:
    raw = data_url.split(",", 1)[-1]
    blob = base64.b64decode(raw)
    try:
        from PIL import Image
    except ImportError:
        return blob
    image = Image.open(io.BytesIO(blob)).convert("RGBA")
    image.thumbnail((256, 256))
    image = knockout_background(image)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def knockout_saved_files() -> int:
    from PIL import Image

    changed = 0
    if not ART_ROOT.is_dir():
        return 0
    for path in ART_ROOT.glob("*/*.png"):
        image = Image.open(path).convert("RGBA")
        image = knockout_background(image)
        image.save(path, format="PNG", optimize=True)
        changed += 1
    return changed


def _image_target(db: Session, dynamic: Dynamic) -> tuple[str, str, str] | None:
    svc = (
        db.query(AiService)
        .filter(AiService.provider == "openrouter", AiService.dynamic_id == dynamic.id)
        .first()
    )
    if svc is None or not (svc.api_key or "").strip():
        return None
    user = db.get(User, svc.owner_user_id)
    if user is None:
        return None
    from .ai_services import resolve_config_for_tool

    cfg, image_svc = resolve_config_for_tool(db, user, dynamic, "image_gen")
    model = ""
    if image_svc and (image_svc.image_model or "").strip():
        model = image_svc.image_model.strip()
    if not model:
        model = "google/gemini-2.5-flash-image"
    key = cfg.api_key if cfg.api_key != "local" else ""
    if not key:
        key = svc.api_key
    base = cfg.base_url or "https://openrouter.ai/api/v1"
    return key, model, base


def draw_one(db: Session, dynamic: Dynamic, entry: dict) -> bool:
    target = _image_target(db, dynamic)
    if target is None:
        return False
    api_key, model, base = target
    notes = f" {entry['notes']}" if entry.get("notes") else ""
    data_url = generate_image_openai_compatible(
        api_key=api_key,
        prompt=(
            "A single object centered on a plain off-white background, simple clear product icon, "
            "no person, no hands, no face, no text, no letters, no watermark, no username. "
            f"The object is: {entry['name']}.{notes}"
        )[:900],
        model=model,
        base_url=base,
    )
    path = art_path(dynamic.id, entry["key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_shrink(data_url))
    row = (
        db.query(GearArt)
        .filter(GearArt.dynamic_id == dynamic.id, GearArt.item_key == entry["key"])
        .first()
    )
    if row is None:
        row = GearArt(dynamic_id=dynamic.id, item_key=entry["key"])
        db.add(row)
    row.name = entry["name"][:200]
    row.slug = entry["slug"][:80]
    db.flush()
    return True


def status(db: Session, dynamic_id: str) -> dict:
    entries = list_gear_entries(db, dynamic_id)
    ready = sum(1 for row in entries if row["has_image"])
    return {
        "total": len(entries),
        "ready": ready,
        "running": dynamic_id in _running,
    }


def ensure_generating(dynamic_id: str) -> dict:
    with _lock:
        already = dynamic_id in _running
        if not already:
            _running.add(dynamic_id)
    if already:
        db = SessionLocal()
        try:
            return status(db, dynamic_id)
        finally:
            db.close()

    def work() -> None:
        db = SessionLocal()
        try:
            dynamic = db.get(Dynamic, dynamic_id)
            if dynamic is None:
                return
            for entry in list_gear_entries(db, dynamic_id):
                if entry["has_image"]:
                    continue
                try:
                    if not draw_one(db, dynamic, entry):
                        log.warning("gear art stopped; no image service for %s", entry["name"])
                        break
                    db.commit()
                    log.info("gear art saved %s", entry["name"])
                except Exception:
                    log.exception("gear art failed for %s", entry["name"])
                    db.rollback()
        finally:
            db.close()
            with _lock:
                _running.discard(dynamic_id)

    threading.Thread(target=work, name=f"gear-art-{dynamic_id[:8]}", daemon=True).start()
    db = SessionLocal()
    try:
        return status(db, dynamic_id)
    finally:
        db.close()


def scene_gear_prompt(db: Session, dynamic: Dynamic) -> tuple[str, list[str]]:
    entries = [row for row in list_gear_entries(db, dynamic.id) if row["owned"] or row["want"]]
    if not entries:
        return "", []
    lines = ["Gear this couple actually has (use these objects; do not invent other toys):"]
    images: list[str] = []
    for row in entries:
        mark = "owned" if row["owned"] else "wanted"
        lines.append(f"- {row['name']} ({mark})")
        path = art_path(dynamic.id, row["key"])
        if row["owned"] and path.is_file() and len(images) < 6:
            blob = base64.b64encode(path.read_bytes()).decode("ascii")
            images.append(f"data:image/png;base64,{blob}")
    if images:
        lines.append(
            "The attached images are the owned items, in the same order as the owned lines above. "
            "Describe those real objects."
        )
    return "\n".join(lines) + "\n", images


def file_data_url(dynamic_id: str, item_key: str) -> str:
    path = art_path(dynamic_id, item_key)
    if not path.is_file():
        return ""
    blob = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{blob}"
