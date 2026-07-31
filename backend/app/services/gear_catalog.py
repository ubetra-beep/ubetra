from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..config import ROOT_DIR

CATALOG_PATH = ROOT_DIR / "backend" / "data" / "gear_catalog.json"


@lru_cache(maxsize=1)
def load_gear_catalog() -> dict:
    if not CATALOG_PATH.exists():
        return {"categories": [], "items": []}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def catalog_categories() -> list[dict]:
    return list(load_gear_catalog().get("categories") or [])


def catalog_items(category: str | None = None) -> list[dict]:
    items = list(load_gear_catalog().get("items") or [])
    if category:
        items = [item for item in items if item.get("category") == category]
    return items


def catalog_item_by_id(item_id: str) -> dict | None:
    for item in catalog_items():
        if item.get("id") == item_id:
            return item
    return None
