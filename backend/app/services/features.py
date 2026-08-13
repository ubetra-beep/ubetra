from __future__ import annotations

import json

from ..models import Dynamic

# Always shown — app is not useful without these.
CORE_FEATURES = {
    "ground_rules",
    "interview",
    "kink_list",
    "core_knowledge",
    "history",
}

# Optional menu items partners can hide when unused.
OPTIONAL_FEATURES = {
    "spti": {"title": "SPTI profile", "section": "knowledge"},
    "context_library": {"title": "Context library", "section": "knowledge"},
    "gear": {"title": "Gear", "section": "knowledge"},
    "org_tracking": {"title": "Sex & orgasm tracking", "section": "tracking"},
    "chastity": {"title": "Chastity tracking", "section": "tracking"},
    "feelings": {"title": "Feelings tracking", "section": "tracking"},
    "punishment": {"title": "Punishment self-report", "section": "tracking"},
    "sleep_tracking": {
        "title": "Sleep tracking",
        "section": "tracking",
        "default_enabled": False,
        "partner_enableable": True,
    },
    "cycle_tracking": {
        "title": "Cycle tracking",
        "section": "tracking",
        "default_enabled": False,
        "partner_enableable": True,
    },
    # tasks + acts are one Playtime menu item (merged UI); keep both keys for API gates
    "tasks": {"title": "Tasks & acts", "section": "playtime", "paired_with": "acts"},
    "acts": {"title": "Tasks & acts", "section": "playtime", "hidden": True, "paired_with": "tasks"},
    "image_vault": {"title": "Image vault", "section": "tracking"},
    "scene_workshop": {"title": "Playtime", "section": "playtime"},
    "manga_comics": {
        "title": "Monthly manga",
        "section": "playtime",
        "default_enabled": False,
        "partner_enableable": True,
    },
    "journal": {"title": "Journal", "section": "tracking"},
}

DEFAULT_OPTIONAL_ENABLED = {
    feature_id
    for feature_id, meta in OPTIONAL_FEATURES.items()
    if meta.get("default_enabled", True)
}


def parse_enabled_features(raw: str | None) -> set[str]:
    text = (raw or "").strip()
    if not text:
        return set(CORE_FEATURES) | set(DEFAULT_OPTIONAL_ENABLED)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set(CORE_FEATURES) | set(DEFAULT_OPTIONAL_ENABLED)
    if not isinstance(data, list):
        return set(CORE_FEATURES) | set(DEFAULT_OPTIONAL_ENABLED)
    enabled = {str(item) for item in data if isinstance(item, str)}
    # Keep tasks/acts in sync when only one is listed
    if "tasks" in enabled or "acts" in enabled:
        enabled.add("tasks")
        enabled.add("acts")
    return set(CORE_FEATURES) | (enabled & set(OPTIONAL_FEATURES.keys()))


def serialize_enabled_features(enabled: set[str]) -> str:
    optional = sorted(enabled & set(OPTIONAL_FEATURES.keys()))
    return json.dumps(optional)


def features_for_dynamic(dynamic: Dynamic) -> dict:
    enabled = parse_enabled_features(dynamic.enabled_features)
    optional_rows = []
    seen_pairs: set[str] = set()
    for feature_id, meta in OPTIONAL_FEATURES.items():
        if meta.get("hidden"):
            continue
        pair = meta.get("paired_with")
        pair_key = tuple(sorted([feature_id, pair])) if pair else (feature_id,)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        is_on = feature_id in enabled or (pair in enabled if pair else False)
        optional_rows.append(
            {
                "id": feature_id,
                "title": meta["title"],
                "section": meta["section"],
                "enabled": is_on,
                "paired_with": pair,
                "default_enabled": meta.get("default_enabled", True),
                "partner_enableable": bool(meta.get("partner_enableable")),
            }
        )
    return {
        "enabled": sorted(enabled),
        "core": sorted(CORE_FEATURES),
        "optional": optional_rows,
    }


def is_feature_enabled(dynamic: Dynamic, feature_id: str) -> bool:
    return feature_id in parse_enabled_features(dynamic.enabled_features)


def is_partner_enableable(feature_id: str) -> bool:
    return bool(OPTIONAL_FEATURES.get(feature_id, {}).get("partner_enableable"))
