from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, PartnerRole
from .features import (
    OPTIONAL_FEATURES,
    is_partner_enableable,
    parse_enabled_features,
    serialize_enabled_features,
)
from .tasks_service import (
    default_reminder_offsets,
    normalize_reminder_offsets,
    serialize_reminder_offsets,
)

# Keys a submissive cannot change directly — they may request a change via chat.
DOM_CONTROLLED_SETTING_KEYS = frozenset(
    {
        "chastity.sub_can_delete_breaks",
        "chastity.auto_relock_after_orgasm",
        "chastity.unlock_presets",
        "features",
        "feelings.prompt_mode",
        "feelings.require_end_of_day",
        "feelings.prompt_after_events",
        "feelings.notify_inbox",
        "chat.system_events",
        "chat.retain_history",
        "chat.clear_dom_only",
        "assistant.tone",
        "assistant.extra_instructions",
        "assistant.permissions",
        "tasks.push_enabled",
        "tasks.reminder_offsets",
        "tasks.complete_notify",
        "video.ml_censor_mode",
    }
)


def setting_label(key: str) -> str:
    labels = {
        "chastity.sub_can_delete_breaks": "Allow sub to delete temporary unlock logs",
        "chastity.auto_relock_after_orgasm": "Lock again after an orgasm release",
        "chastity.unlock_presets": "Chastity unlock presets",
        "features": "Application features",
        "feelings.prompt_mode": "Feelings prompt mode",
        "feelings.require_end_of_day": "End-of-day feelings reminder",
        "feelings.prompt_after_events": "Prompt feelings after play",
        "feelings.notify_inbox": "Feelings return overlay",
        "chat.system_events": "Post activity logs to chat",
        "chat.retain_history": "Keep chat forever on server (no auto-delete)",
        "chat.clear_dom_only": "Only keyholder can clear chat",
        "assistant.tone": "Assistant domme tone",
        "assistant.extra_instructions": "Assistant domme extra instructions",
        "assistant.permissions": "Assistant Domme agent permissions",
        "tasks.push_enabled": "Task push notifications",
        "tasks.due_lead_minutes": "Minutes before due to notify",
        "tasks.reminder_offsets": "Task due reminders",
        "tasks.complete_notify": "Notify keyholder when tasks are completed",
        "video.ml_censor_mode": "Smart censor on sub display",
    }
    if key.startswith("features."):
        feature_id = key.split(".", 1)[1]
        meta = OPTIONAL_FEATURES.get(feature_id) or {}
        return f"Feature: {meta.get('title', feature_id)}"
    return labels.get(key, key)


def is_dominant(membership: Membership) -> bool:
    return membership.role == PartnerRole.dominant


def require_dom_for_setting(membership: Membership, setting_key: str) -> None:
    if setting_key.startswith("features."):
        feature_id = setting_key.split(".", 1)[1]
        if is_partner_enableable(feature_id):
            return
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

    if setting_key == "chastity.auto_relock_after_orgasm":
        dynamic.chastity_auto_relock_after_orgasm = bool(value)
        return (
            "enabled auto re-lock after orgasm"
            if dynamic.chastity_auto_relock_after_orgasm
            else "disabled auto re-lock after orgasm"
        )

    if setting_key == "chastity.unlock_presets":
        from .chastity_release import serialize_unlock_presets

        dynamic.chastity_unlock_presets = serialize_unlock_presets(value if isinstance(value, list) else [])
        return "updated chastity unlock presets"

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

    if setting_key == "chat.clear_dom_only":
        dynamic.chat_clear_dom_only = bool(value)
        return (
            "restricted chat clear to keyholder only"
            if dynamic.chat_clear_dom_only
            else "allowed anyone to clear chat"
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

    if setting_key == "feelings.prompt_after_events":
        dynamic.feelings_prompt_after_events = bool(value)
        return (
            "turned on feelings prompts after play"
            if dynamic.feelings_prompt_after_events
            else "turned off feelings prompts after play"
        )

    if setting_key == "feelings.notify_inbox":
        dynamic.feelings_notify_inbox = bool(value)
        return (
            "included feelings in the return overlay"
            if dynamic.feelings_notify_inbox
            else "stopped feelings return overlay popups"
        )

    if setting_key == "tasks.push_enabled":
        dynamic.task_push_enabled = bool(value)
        return "enabled task push notifications" if value else "disabled task push notifications"

    if setting_key == "tasks.due_lead_minutes":
        try:
            minutes = max(0, min(24 * 60, int(value)))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid lead time") from exc
        dynamic.task_reminder_offsets = serialize_reminder_offsets([minutes])
        return f"set task due reminders to {minutes} minutes before"

    if setting_key == "tasks.reminder_offsets":
        if not isinstance(value, list):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reminder list")
        offsets = normalize_reminder_offsets(value)
        dynamic.task_reminder_offsets = serialize_reminder_offsets(offsets)
        if not offsets:
            return "turned off task due reminders"
        return "set task due reminders to " + ", ".join(f"{m} min" for m in offsets) + " before"

    if setting_key == "tasks.complete_notify":
        dynamic.task_complete_notify = bool(value)
        return (
            "turned on task completion notifications"
            if dynamic.task_complete_notify
            else "turned off task completion notifications"
        )

    if setting_key == "tasks.completed_history_days":
        try:
            days = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid history length") from exc
        dynamic.task_completed_history_days = max(1, min(90, days))
        return f"show the last {dynamic.task_completed_history_days} days of completed tasks"

    if setting_key == "video.ml_censor_mode":
        mode = str(value or "off").strip().lower()
        if mode not in ("off", "auto", "client", "cuda"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid censor mode")
        dynamic.ml_censor_mode = mode
        return f"set smart censor to {mode}"

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
        return "updated application features"

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown setting key")


def policy_snapshot(dynamic: Dynamic) -> dict:
    from .chastity_release import effective_unlock_presets

    return {
        "chastity_sub_can_delete_breaks": bool(
            getattr(dynamic, "chastity_sub_can_delete_breaks", True)
        ),
        "chastity_auto_relock_after_orgasm": bool(
            getattr(dynamic, "chastity_auto_relock_after_orgasm", True)
        ),
        "chastity_unlock_presets": effective_unlock_presets(dynamic),
        "feelings_prompt_mode": getattr(dynamic, "feelings_prompt_mode", None) or "soft",
        "feelings_require_end_of_day": bool(
            getattr(dynamic, "feelings_require_end_of_day", True)
        ),
        "feelings_prompt_after_events": bool(
            getattr(dynamic, "feelings_prompt_after_events", True)
        ),
        "feelings_notify_inbox": bool(getattr(dynamic, "feelings_notify_inbox", False)),
        "chat_system_events": bool(getattr(dynamic, "chat_system_events", True)),
        "chat_retain_history": bool(getattr(dynamic, "chat_retain_history", False)),
        "chat_expire_hours": int(getattr(dynamic, "chat_expire_hours", 720) or 720),
        "chat_clear_dom_only": bool(getattr(dynamic, "chat_clear_dom_only", False)),
        "assistant_tone": getattr(dynamic, "assistant_tone", None) or "balanced",
        "assistant_extra_instructions": getattr(dynamic, "assistant_extra_instructions", None) or "",
        "enabled_features": sorted(parse_enabled_features(dynamic.enabled_features)),
        "task_push_enabled": bool(getattr(dynamic, "task_push_enabled", True)),
        "task_reminder_offsets": default_reminder_offsets(dynamic),
        "task_complete_notify": bool(getattr(dynamic, "task_complete_notify", True)),
        "task_completed_history_days": int(getattr(dynamic, "task_completed_history_days", 9) or 9),
        "ml_censor_mode": (getattr(dynamic, "ml_censor_mode", None) or "off"),
    }
