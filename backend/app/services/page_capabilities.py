"""Static catalog of what each screen can do, keyed by hash-route suffix."""

from __future__ import annotations

from .features import CORE_FEATURES, OPTIONAL_FEATURES, parse_enabled_features

# route suffix after /dynamic/{id}/  → capability block
PAGE_CAPABILITIES: dict[str, dict] = {
    "": {
        "title": "Tracking hub",
        "feature_id": "history",
        "actions": [
            "Open History, chastity, orgasm log, feelings, punishment, journal, and other tracking modules that are enabled",
            "Toggle application features from the hub menu",
        ],
    },
    "track": {
        "title": "Tracking hub",
        "feature_id": "history",
        "actions": [
            "Browse enabled tracking modules",
            "Open Setup / Dynamic (ground rules, interview, kink list)",
        ],
    },
    "history": {
        "title": "History",
        "feature_id": "history",
        "actions": [
            "Review weekly buckets, orgasm reports, chastity-day calendars, and session logs",
        ],
    },
    "tracking": {
        "title": "Sex & orgasm tracking",
        "feature_id": "org_tracking",
        "actions": [
            "Log orgasm or no-orgasm play for either partner",
            "Edit standing balance targets for orgasm split",
            "Import prior history",
        ],
    },
    "chastity": {
        "title": "Chastity tracking",
        "feature_id": "chastity",
        "actions": [
            "Lock, unlock, log breaks, and review lockup history",
            "Edit standing lockup-balance targets",
            "Open gift/unlock goals under Tasks → Goals",
        ],
    },
    "feelings": {
        "title": "Feelings",
        "feature_id": "feelings",
        "actions": [
            "Log a feelings-wheel check-in",
            "Review recent check-ins",
        ],
    },
    "sleep": {
        "title": "Sleep tracking",
        "feature_id": "sleep_tracking",
        "actions": ["Log sleep and view recent nights"],
    },
    "cycle": {
        "title": "Cycle tracking",
        "feature_id": "cycle_tracking",
        "actions": ["Log period data for either partner"],
    },
    "punishment": {
        "title": "Punishment / confessions",
        "feature_id": "punishment",
        "actions": [
            "Review a pending confession",
            "Assign a punishment task or bump a gift goal",
            "Mark covered, remind later, or request ideas (AI)",
        ],
    },
    "journal": {
        "title": "Journal",
        "feature_id": "journal",
        "actions": [
            "Read partner-visible entries",
            "Ask for a Domme review of an entry (AI)",
            "Write a new entry",
        ],
    },
    "vault": {
        "title": "Image vault",
        "feature_id": "image_vault",
        "actions": ["Browse private images copied from chat"],
    },
    "tasks": {
        "title": "Tasks & acts",
        "feature_id": "tasks",
        "actions": [
            "Create, assign, pause, or approve tasks",
            "Handle overdue, late-complete, and make-up work",
            "Edit gift goals and standing balance targets",
            "Build a training regimen (AI)",
        ],
    },
    "acts": {
        "title": "Acts of submission",
        "feature_id": "acts",
        "actions": [
            "Request or verify an act",
            "Generate or manually edit act-type catalog",
        ],
    },
    "assistant": {
        "title": "Playtime",
        "feature_id": "scene_workshop",
        "actions": [
            "Open scene builder, spin the wheel, Instructor, manga, or tasks",
        ],
    },
    "assistant/scene": {
        "title": "Scene builder",
        "feature_id": "scene_workshop",
        "actions": ["Pick effort and lean, generate subjects, draft a scene (AI)"],
    },
    "assistant/games": {
        "title": "Playtime games",
        "feature_id": "scene_workshop",
        "actions": ["Open spin the wheel"],
    },
    "assistant/games/spin": {
        "title": "Spin the wheel",
        "feature_id": "scene_workshop",
        "actions": ["Configure outcomes, spin, fulfill orgasm/chastity logs"],
    },
    "instructor": {
        "title": "Instructor",
        "feature_id": "scene_workshop",
        "actions": ["Start or control a stroke-to-the-beat session"],
    },
    "manga": {
        "title": "Monthly manga",
        "feature_id": "manga_comics",
        "actions": ["Generate this month's comic (AI)"],
    },
    "ground-rules": {
        "title": "Ground rules",
        "feature_id": "ground_rules",
        "actions": ["Propose or approve agreements", "Draft wording with assist (AI)"],
    },
    "interview": {
        "title": "Dynamic interview",
        "feature_id": "interview",
        "actions": ["Answer intake questions (chat when AI is on, form when AI is off)"],
    },
    "survey": {
        "title": "Kink list",
        "feature_id": "kink_list",
        "actions": ["Rate interests", "Review overlap with partner"],
    },
    "overlap": {
        "title": "Kink overlap",
        "feature_id": "kink_list",
        "actions": ["See shared wants"],
    },
    "knowledge": {
        "title": "Core knowledge",
        "feature_id": "core_knowledge",
        "actions": ["Edit private relationship context fields", "Fill from interview"],
    },
    "knowledge/spti": {
        "title": "SPTI profile",
        "feature_id": "spti",
        "actions": ["Paste or skip SPTI results"],
    },
    "context": {
        "title": "Context library",
        "feature_id": "context_library",
        "actions": ["Add stories, scenes, or notes tagged for AI"],
    },
    "gear": {
        "title": "Gear",
        "feature_id": "gear",
        "actions": ["Inventory toys, kinky stuff, and outfits"],
    },
    "features": {
        "title": "Application features",
        "feature_id": None,
        "actions": ["Enable or disable optional modules"],
    },
}

HUB_LABELS = {
    "tracking": "Tracking tab — history, lockups, play, feelings, punishment, journal",
    "playtime": "Playtime tab — tasks, scenes, games, Instructor, manga",
    "chat": "Chat tab — partner messages (never sent to the assistant)",
}


def route_key_from_parts(parts: list[str]) -> str:
    """parts are hash segments after 'dynamic' and the id."""
    if not parts:
        return ""
    if parts[0] == "assistant" and len(parts) >= 3:
        return "/".join(parts[:3]) if parts[1] == "games" else "/".join(parts[:2])
    if parts[0] == "knowledge" and len(parts) >= 2:
        return "/".join(parts[:2])
    if parts[0] in {"punishment", "history", "tracking", "chastity"} and len(parts) >= 2:
        return parts[0]
    return parts[0]


def lookup_page(route_key: str) -> dict:
    if route_key in PAGE_CAPABILITIES:
        return dict(PAGE_CAPABILITIES[route_key])
    base = route_key.split("/")[0] if route_key else ""
    if base in PAGE_CAPABILITIES:
        return dict(PAGE_CAPABILITIES[base])
    return dict(PAGE_CAPABILITIES[""])


def feature_menu_lines(dynamic) -> list[str]:
    enabled = parse_enabled_features(getattr(dynamic, "enabled_features", None))
    lines = ["Enabled application features (do not suggest modules that are off):"]
    for fid in sorted(CORE_FEATURES):
        lines.append(f"  - {fid} (core, always on)")
    for fid, meta in OPTIONAL_FEATURES.items():
        if meta.get("hidden"):
            continue
        on = fid in enabled or (meta.get("paired_with") in enabled if meta.get("paired_with") else False)
        lines.append(f"  - {meta['title']} ({fid}): {'ON' if on else 'OFF'}")
    lines.append("Hubs: Tracking, Playtime, Chat.")
    return lines


def format_page_capabilities(
    *,
    route_key: str,
    feature_enabled: bool,
    role: str = "dominant",
) -> str:
    page = lookup_page(route_key)
    lines = [
        f"The keyholder is currently on: {page.get('title') or 'the app'} (route `{route_key or 'track'}`).",
        f"Requester role: {role}.",
    ]
    if page.get("feature_id") and not feature_enabled:
        lines.append("This module is disabled — do not suggest using it until they turn it on in Application features.")
    else:
        lines.append("What they can do on this screen:")
        for action in page.get("actions") or []:
            lines.append(f"  - {action}")
    return "\n".join(lines)
