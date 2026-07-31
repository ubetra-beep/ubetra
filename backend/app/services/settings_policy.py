from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, PartnerRole
from .features import OPTIONAL_FEATURES, parse_enabled_features, serialize_enabled_features

# Keys a submissive cannot change directly — they may request a change via chat.
DOM_CONTROLLED_SETTING_KEYS = frozenset(
    {
        "chastity.sub_can_delete_breaks",
        "features",
        "feelings.prompt_mode",
        "feelings.require_end_of_day",
        "chat.system_events",
        "chat.retain_history",
        "assistant.tone",
        "assistant.extra_instructions",
    }
)


def setting_label(key: str) -> str:
    labels = {
        "chastity.sub_can_delete_breaks": "Allow sub to delete temporary unlock logs",
        "features": "Menu features",
        "feelings.prompt_mode": "Feelings prompt mode",
        "feelings.require_end_of_day": "Require end-of-day feelings",
        "chat.system_events": "Post activity logs to chat",
        "chat.retain_history": "Keep chat forever on server (no auto-delete)",
        "assistant.tone": "Assistant domme tone",
        "assistant.extra_instructions": "Assistant domme extra instructions",
    }
    if key.startswith("features."):
        feature_id = key.split(".", 1)[1]
        meta = OPTIONAL_FEATURES.get(feature_id) or {}
        return f"Feature: {meta.get('title', feature_id)}"
    return labels.get(key, key)


def is_dominant(membership: Membership) -> bool:
    return membership.role == PartnerRole.dominant


def require_dom_for_setting(membership: Membership, setting_key: str) -> None:
    base = setting_key.split(".", 1)[0]
    controlled = (
        setting_key in DOM_CONTROLLED_SETTING_KEYS
        or f"{base}" in DOM_CONTROLLED_SETTING_KEYS
        or setting_key.startswith("features.")
    )
    if controlled and not is_dominant(membership):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the keyholder can change this setting. Send a request from Settings.",
        )


def apply_setting(
    db: Session,
    dynamic: Dynamic,
    *,
    setting_key: str,
    value,
) -> str:
    """Apply a dom-controlled setting. Returns a short human summary."""
    if setting_key == "chastity.sub_can_delete_breaks":
        dynamic.chastity_sub_can_delete_breaks = bool(value)
        return (
            "allowed temporary unlock log deletion by sub"
            if dynamic.chastity_sub_can_delete_breaks
            else "disallowed temporary unlock log deletion by sub"
        )

    if setting_key == "chat.system_events":
        dynamic.chat_system_events = bool(value)
        return "enabled activity logs in chat" if value else "disabled activity logs in chat"

    if setting_key == "chat.retain_history":
        dynamic.chat_retain_history = bool(value)
        return (
            "enabled forever chat history on server"
            if dynamic.chat_retain_history
            else "disabled forever chat history (using timed server cache)"
        )

    if setting_key == "feelings.prompt_mode":
        mode = str(value or "soft").strip().lower()
        if mode not in ("soft", "hard"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid prompt mode")
        dynamic.feelings_prompt_mode = mode
        return f"set feelings prompt mode to {mode}"

    if setting_key == "feelings.require_end_of_day":
        dynamic.feelings_require_end_of_day = bool(value)
        return (
            "required end-of-day feelings"
            if dynamic.feelings_require_end_of_day
            else "made end-of-day feelings optional"
        )

    if setting_key.startswith("features."):
        feature_id = setting_key.split(".", 1)[1]
        if feature_id not in OPTIONAL_FEATURES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown feature")
        enabled = parse_enabled_features(dynamic.enabled_features)
        turn_on = bool(value)
        pair = OPTIONAL_FEATURES[feature_id].get("paired_with")
        if turn_on:
            enabled.add(feature_id)
            if pair:
                enabled.add(pair)
        else:
            enabled.discard(feature_id)
            if pair:
                enabled.discard(pair)
        dynamic.enabled_features = serialize_enabled_features(enabled)
        title = OPTIONAL_FEATURES[feature_id].get("title", feature_id)
        return f"{'enabled' if turn_on else 'disabled'} feature {title}"

    if setting_key == "assistant.tone":
        from .llm import ASSISTANT_TONES

        if isinstance(value, dict):
            tone = str(value.get("tone") or "balanced").strip()
            extra = str(value.get("extra_instructions") or "").strip()
            if tone not in ASSISTANT_TONES:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown tone")
            dynamic.assistant_tone = tone
            dynamic.assistant_extra_instructions = extra
            return f"set assistant tone to {ASSISTANT_TONES[tone]['label']} and updated instructions"
        tone = str(value or "balanced").strip()
        if tone not in ASSISTANT_TONES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown tone")
        dynamic.assistant_tone = tone
        return f"set assistant tone to {ASSISTANT_TONES[tone]['label']}"

    if setting_key == "assistant.extra_instructions":
        if isinstance(value, dict):
            value = value.get("extra_instructions", "")
        dynamic.assistant_extra_instructions = str(value or "").strip()
        return "updated assistant extra instructions"

    if setting_key == "features" and isinstance(value, list):
        selected = {str(item) for item in value if item in OPTIONAL_FEATURES}
        for feature_id in list(selected):
            pair = OPTIONAL_FEATURES.get(feature_id, {}).get("paired_with")
            if pair:
                selected.add(pair)
        dynamic.enabled_features = serialize_enabled_features(selected)
        return "updated menu features"

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown setting key")


def policy_snapshot(dynamic: Dynamic) -> dict:
    return {
        "chastity_sub_can_delete_breaks": bool(
            getattr(dynamic, "chastity_sub_can_delete_breaks", True)
        ),
        "feelings_prompt_mode": getattr(dynamic, "feelings_prompt_mode", None) or "soft",
        "feelings_require_end_of_day": bool(
            getattr(dynamic, "feelings_require_end_of_day", True)
        ),
        "chat_system_events": bool(getattr(dynamic, "chat_system_events", True)),
        "chat_retain_history": bool(getattr(dynamic, "chat_retain_history", False)),
        "chat_expire_hours": int(getattr(dynamic, "chat_expire_hours", 720) or 720),
        "assistant_tone": getattr(dynamic, "assistant_tone", None) or "balanced",
        "assistant_extra_instructions": getattr(dynamic, "assistant_extra_instructions", None) or "",
        "enabled_features": sorted(parse_enabled_features(dynamic.enabled_features)),
    }
