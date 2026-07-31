import json
import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .config import CATALOG_PATH, DATA_DIR, ROOT_DIR
from .models import Interest, InterestCategory

SEED_DIR = ROOT_DIR / "backend" / "seed"
SEED_FILES = (
    "interest_catalog.json",
    "feelings_wheel.json",
    "feelings_descriptions.json",
    "gear_catalog.json",
)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:48] or "item"


def load_catalog_from_har(har_path: Path) -> dict:
    raw = json.loads(har_path.read_text(encoding="utf-8"))
    categories = []
    for cat in raw.get("sex_interest_categories", []):
        cat_id = _slug(cat["name"])
        interests = []
        for item in cat.get("interests", []):
            label = item.get("display_copy") or item.get("token", "interest")
            interests.append(
                {
                    "id": f"{cat_id}_{_slug(label)}",
                    "display_copy": item.get("display_copy", ""),
                    "submissive_display_override": item.get("submissive_display_override") or None,
                    "description": item.get("description") or None,
                    "display_order": item.get("display_order", 0),
                }
            )
        categories.append(
            {
                "id": cat_id,
                "name": cat.get("name", ""),
                "description": cat.get("description"),
                "display_order": cat.get("display_order", 0),
                "interests": interests,
            }
        )
    return {"categories": categories}


def _interest_count(catalog: dict) -> int:
    return sum(len(c.get("interests") or []) for c in (catalog.get("categories") or []))


def _catalog_looks_minimal(path: Path) -> bool:
    """True when the on-disk catalog is the tiny fallback (or empty/corrupt)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _interest_count(data) <= 5
    except Exception:
        return True


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Docker mounts a volume over backend/data — restore baked-in seed JSON when
    # missing, or when a previous boot wrote the tiny fallback before seed existed.
    if SEED_DIR.is_dir():
        for name in SEED_FILES:
            src = SEED_DIR / name
            dest = DATA_DIR / name
            if not src.is_file():
                continue
            if not dest.exists() or (name == "interest_catalog.json" and _catalog_looks_minimal(dest)):
                if not dest.exists() or src.stat().st_size > dest.stat().st_size:
                    shutil.copy2(src, dest)


def ensure_catalog_file(har_fallback: Path | None = None) -> Path:
    ensure_data_dir()
    if CATALOG_PATH.exists() and not _catalog_looks_minimal(CATALOG_PATH):
        return CATALOG_PATH

    seed_path = SEED_DIR / "interest_catalog.json"
    if seed_path.is_file() and not _catalog_looks_minimal(seed_path):
        shutil.copy2(seed_path, CATALOG_PATH)
        return CATALOG_PATH

    if har_fallback and har_fallback.exists():
        catalog = load_catalog_from_har(har_fallback)
        CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        return CATALOG_PATH

    # Minimal fallback if HAR/seed is unavailable
    catalog = {
        "categories": [
            {
                "id": "domination_submission",
                "name": "Domination/Submission",
                "description": "Power dynamics between partners.",
                "display_order": 1,
                "interests": [
                    {
                        "id": "domination_submission_training",
                        "display_copy": "Training",
                        "submissive_display_override": None,
                        "description": "Structured practice with goals and feedback.",
                        "display_order": 1,
                    },
                    {
                        "id": "domination_submission_orgasm_control",
                        "display_copy": "Orgasm control",
                        "submissive_display_override": None,
                        "description": None,
                        "display_order": 2,
                    },
                ],
            }
        ]
    }
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return CATALOG_PATH


def seed_catalog(db: Session, har_fallback: Path | None = None) -> None:
    from .models import InterestResponse

    path = ensure_catalog_file(har_fallback)
    data = json.loads(path.read_text(encoding="utf-8"))
    seed_n = _interest_count(data)
    existing_n = db.query(Interest).count()

    # First boot with only the tiny fallback, or a volume that kept that stub DB.
    needs_reseed = existing_n == 0 or (seed_n > 20 and existing_n <= 5)
    if not needs_reseed:
        return

    if existing_n > 0:
        db.query(InterestResponse).delete()
        db.query(Interest).delete()
        db.query(InterestCategory).delete()
        db.commit()

    for cat in data.get("categories", []):
        category = InterestCategory(
            id=cat["id"],
            name=cat["name"],
            description=cat.get("description"),
            display_order=cat.get("display_order", 0),
        )
        db.add(category)
        for item in cat.get("interests", []):
            db.add(
                Interest(
                    id=item["id"],
                    category_id=cat["id"],
                    display_copy=item["display_copy"],
                    submissive_display_override=item.get("submissive_display_override"),
                    description=item.get("description"),
                    display_order=item.get("display_order", 0),
                )
            )
    db.commit()
