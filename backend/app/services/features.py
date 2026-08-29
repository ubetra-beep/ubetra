from __future__ import annotations

import json

from ..models import Dynamic

SECTION_ORDER = ("tracking", "playtime", "knowledge", "chat")
SECTION_LABELS = {
    "tracking": "Tracking",
    "playtime": "Playtime",
    "knowledge": "Setup & knowledge",
    "chat": "Chat",
}

# Always shown — app is not useful without these.
CORE_FEATURES = {
    "ground_rules",
    "interview",
    "kink_list",
    "core_knowledge",
    "history",
}

CORE_FEATURE_META = {
    "history": {
        "title": "History",
        "section": "tracking",
        "blurb": "Reports, calendars, and linked session logs.",
    },
    "ground_rules": {
        "title": "Ground rules",
        "section": "knowledge",
        "blurb": "Agreements you both approve.",
    },
    "interview": {
        "title": "Dynamic interview",
        "section": "knowledge",
        "blurb": "What each of you wants from the dynamic.",
    },
    "kink_list": {
        "title": "Kink list",
        "section": "knowledge",
        "blurb": "Rate interests and compare overlap.",
    },
    "core_knowledge": {
        "title": "Core knowledge",
        "section": "knowledge",
        "blurb": "Logistics, space, budget, and desires for AI context.",
    },
}

# Optional menu items partners can hide when unused.
OPTIONAL_FEATURES = {
    "spti": {
        "title": "SPTI profile",
        "section": "knowledge",
        "blurb": "Paste personality-test results for AI tone and scene ideas.",
    },
    "context_library": {
        "title": "Context library",
        "section": "knowledge",
        "blurb": "Stories, contracts, and notes tagged for the assistant.",
    },
    "gear": {
        "title": "Gear",
        "section": "knowledge",
        "blurb": "Inventory of toys, outfits, and kinky stuff.",
    },
    "org_tracking": {
        "title": "Sex & orgasm tracking",
        "section": "tracking",
        "blurb": "Log orgasms, denial, and play for either partner.",
    },
    "chastity": {
        "title": "Chastity tracking",
        "section": "tracking",
        "blurb": "Lockups, breaks, Eventual Release, and gift goals.",
    },
    "feelings": {
        "title": "Feelings tracking",
        "section": "tracking",
        "blurb": "Wheel check-ins before/after play or at end of day.",
    },
    "punishment": {
        "title": "Punishment self-report",
        "section": "tracking",
        "blurb": "Confessions the keyholder assigns or covers.",
    },
    "sleep_tracking": {
        "title": "Sleep tracking",
        "section": "tracking",
        "blurb": "Night log; Health Connect on Android.",
        "default_enabled": False,
        "partner_enableable": True,
    },
    "cycle_tracking": {
        "title": "Cycle tracking",
        "section": "tracking",
        "blurb": "Period flow and symptoms either partner can view.",
        "default_enabled": False,
        "partner_enableable": True,
    },
    # tasks + acts are one Playtime menu item (merged UI); keep both keys for API gates
    "tasks": {
        "title": "Tasks & acts",
        "section": "playtime",
        "blurb": "Assign, request, and verify tasks and acts of submission.",
        "paired_with": "acts",
    },
    "acts": {
        "title": "Tasks & acts",
        "section": "playtime",
        "blurb": "Assign, request, and verify tasks and acts of submission.",
        "hidden": True,
        "paired_with": "tasks",
    },
    "image_vault": {
        "title": "Image vault",
        "section": "chat",
        "blurb": "Private copies of photos from Chat.",
    },
    "scene_workshop": {
        "title": "Playtime",
        "section": "playtime",
        "blurb": "Scene builder, spin the wheel, and Instructor.",
    },
    "manga_comics": {
        "title": "Monthly manga",
        "section": "playtime",
        "blurb": "One generated comic a month. Either partner can enable.",
        "default_enabled": False,
        "partner_enableable": True,
    },
    "journal": {
        "title": "Journal",
        "section": "tracking",
        "blurb": "Private writing; per-entry share with partner and AI.",
    },
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
                "blurb": meta.get("blurb") or "",
                "enabled": is_on,
                "paired_with": pair,
                "default_enabled": meta.get("default_enabled", True),
                "partner_enableable": bool(meta.get("partner_enableable")),
            }
        )
    core_items = [
        {
            "id": fid,
            "title": CORE_FEATURE_META[fid]["title"],
            "section": CORE_FEATURE_META[fid]["section"],
            "blurb": CORE_FEATURE_META[fid]["blurb"],
        }
        for fid in ("history", "ground_rules", "interview", "kink_list", "core_knowledge")
        if fid in CORE_FEATURE_META
    ]
    return {
        "enabled": sorted(enabled),
        "core": sorted(CORE_FEATURES),
        "core_items": core_items,
        "sections": [{"id": sid, "title": SECTION_LABELS[sid]} for sid in SECTION_ORDER],
        "optional": optional_rows,
        "features_picked": bool(getattr(dynamic, "features_onboarded", False)),
    }


def is_feature_enabled(dynamic: Dynamic, feature_id: str) -> bool:
    return feature_id in parse_enabled_features(dynamic.enabled_features)


def is_partner_enableable(feature_id: str) -> bool:
    return bool(OPTIONAL_FEATURES.get(feature_id, {}).get("partner_enableable"))
