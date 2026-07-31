"""Per-dynamic sex/orgasm tracking field + metric preferences."""

from __future__ import annotations

import json
from typing import Any

from ..models import Dynamic

# Log form fields (optional ones default off so couples opt in).
FIELD_DEFS: dict[str, dict[str, Any]] = {
    "notes": {"title": "Notes", "default": True},
    "session_end": {"title": "Session end time", "default": True},
    "location": {"title": "Location", "default": False},
    "initiated_by": {"title": "Who initiated", "default": False},
    "protection": {"title": "Protection (safer sex)", "default": False},
    "notes_private": {"title": "Allow private notes (logger + keyholder only)", "default": False},
}

# History / report metrics.
METRIC_DEFS: dict[str, dict[str, Any]] = {
    "partner_chart_90d": {"title": "30-day cumulative orgasm chart", "default": True},
    "days_with_without": {"title": "Days with / without orgasms", "default": True},
    "total_orgasms": {"title": "Total orgasm count", "default": True},
    "full_orgasm_days": {"title": "Full orgasm days", "default": True},
    "play_days": {"title": "Play days (no orgasm)", "default": True},
    "lockup_context": {"title": "Orgasms during lockup context", "default": True},
    "ruined_count": {"title": "Ruined / denial count", "default": True},
    "avg_duration": {"title": "Average session duration", "default": True},
    "avg_rates": {"title": "Averages per week / month", "default": True},
    "avg_satisfaction": {"title": "Average satisfaction", "default": True},
    "avg_edging": {"title": "Average edging count", "default": True},
    "monthly_charts": {"title": "Monthly trend charts", "default": True},
    "intervals_full": {"title": "Intervals between full orgasms", "default": True},
    "intervals_any": {"title": "Intervals between any orgasm", "default": True},
}


def _defaults() -> dict[str, dict[str, bool]]:
    return {
        "fields": {k: bool(v["default"]) for k, v in FIELD_DEFS.items()},
        "metrics": {k: bool(v["default"]) for k, v in METRIC_DEFS.items()},
    }


def parse_org_tracking_prefs(raw: str | None) -> dict[str, dict[str, bool]]:
    base = _defaults()
    text = (raw or "").strip()
    if not text:
        return base
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return base
    if not isinstance(data, dict):
        return base
    fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    for key in FIELD_DEFS:
        if key in fields:
            base["fields"][key] = bool(fields[key])
    for key in METRIC_DEFS:
        if key in metrics:
            base["metrics"][key] = bool(metrics[key])
    return base


def serialize_org_tracking_prefs(prefs: dict) -> str:
    parsed = parse_org_tracking_prefs(json.dumps(prefs) if not isinstance(prefs, str) else prefs)
    # Prefer structured input
    if isinstance(prefs, dict):
        merged = _defaults()
        fields = prefs.get("fields") if isinstance(prefs.get("fields"), dict) else {}
        metrics = prefs.get("metrics") if isinstance(prefs.get("metrics"), dict) else {}
        for key in FIELD_DEFS:
            if key in fields:
                merged["fields"][key] = bool(fields[key])
        for key in METRIC_DEFS:
            if key in metrics:
                merged["metrics"][key] = bool(metrics[key])
        parsed = merged
    return json.dumps(parsed)


def prefs_for_dynamic(dynamic: Dynamic) -> dict:
    prefs = parse_org_tracking_prefs(getattr(dynamic, "org_tracking_prefs", None))
    return {
        "fields": [
            {
                "id": fid,
                "title": meta["title"],
                "enabled": prefs["fields"][fid],
            }
            for fid, meta in FIELD_DEFS.items()
        ],
        "metrics": [
            {
                "id": mid,
                "title": meta["title"],
                "enabled": prefs["metrics"][mid],
            }
            for mid, meta in METRIC_DEFS.items()
        ],
        "raw": prefs,
    }


def field_enabled(dynamic: Dynamic | None, field_id: str) -> bool:
    if dynamic is None:
        return bool(FIELD_DEFS.get(field_id, {}).get("default", False))
    prefs = parse_org_tracking_prefs(getattr(dynamic, "org_tracking_prefs", None))
    return bool(prefs["fields"].get(field_id, FIELD_DEFS.get(field_id, {}).get("default", False)))


def metric_enabled(dynamic: Dynamic | None, metric_id: str) -> bool:
    if dynamic is None:
        return bool(METRIC_DEFS.get(metric_id, {}).get("default", False))
    prefs = parse_org_tracking_prefs(getattr(dynamic, "org_tracking_prefs", None))
    return bool(prefs["metrics"].get(metric_id, METRIC_DEFS.get(metric_id, {}).get("default", False)))
