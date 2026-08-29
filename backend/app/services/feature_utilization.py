"""Last-used timestamps for enabled optional features (Assistant feature audit)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    ChastityLockup,
    CycleLog,
    Dynamic,
    FeelingCheckIn,
    GearInventoryItem,
    InstructorSession,
    JournalEntry,
    MangaComic,
    OrgTrackingEntry,
    PunishmentReport,
    SleepSession,
    SpinGameSession,
    Task,
    TaskList,
    VaultImage,
)
from .features import OPTIONAL_FEATURES, parse_enabled_features

STALE_DAYS = 30

FEATURE_PATHS = {
    "org_tracking": "/tracking",
    "chastity": "/chastity",
    "journal": "/journal",
    "feelings": "/feelings",
    "tasks": "/tasks",
    "acts": "/acts",
    "scene_workshop": "/assistant",
    "manga_comics": "/manga",
    "sleep_tracking": "/sleep",
    "cycle_tracking": "/cycle",
    "image_vault": "/vault",
    "gear": "/gear",
    "punishment": "/punishment",
    "context_library": "/context",
    "spti": "/knowledge/spti",
}


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat() + "Z"


def _latest(db: Session, query) -> datetime | None:
    try:
        return query.scalar()
    except Exception:
        return None


def last_activity_map(db: Session, dynamic_id: str) -> dict[str, datetime | None]:
    """feature_id → last activity datetime (None = never)."""
    out: dict[str, datetime | None] = {}

    out["org_tracking"] = _latest(
        db,
        db.query(func.max(OrgTrackingEntry.occurred_at)).filter(
            OrgTrackingEntry.dynamic_id == dynamic_id
        ),
    )
    out["chastity"] = _latest(
        db,
        db.query(func.max(ChastityLockup.started_at)).filter(ChastityLockup.dynamic_id == dynamic_id),
    )
    out["journal"] = _latest(
        db,
        db.query(func.max(JournalEntry.updated_at)).filter(JournalEntry.dynamic_id == dynamic_id),
    )
    out["feelings"] = _latest(
        db,
        db.query(func.max(FeelingCheckIn.occurred_at)).filter(
            FeelingCheckIn.dynamic_id == dynamic_id
        ),
    )
    last_list = _latest(
        db,
        db.query(func.max(TaskList.created_at)).filter(TaskList.dynamic_id == dynamic_id),
    )
    last_done = _latest(
        db,
        db.query(func.max(Task.completed_at))
        .join(TaskList, Task.task_list_id == TaskList.id)
        .filter(TaskList.dynamic_id == dynamic_id),
    )
    out["tasks"] = last_done if (last_done and (last_list is None or last_done >= last_list)) else last_list
    out["acts"] = out.get("tasks")
    out["scene_workshop"] = _latest(
        db,
        db.query(func.max(SpinGameSession.updated_at)).filter(
            SpinGameSession.dynamic_id == dynamic_id
        ),
    )
    instructor = _latest(
        db,
        db.query(func.max(InstructorSession.started_at)).filter(
            InstructorSession.dynamic_id == dynamic_id
        ),
    )
    if instructor and (out["scene_workshop"] is None or instructor > out["scene_workshop"]):
        out["scene_workshop"] = instructor
    out["manga_comics"] = _latest(
        db,
        db.query(func.max(MangaComic.updated_at)).filter(MangaComic.dynamic_id == dynamic_id),
    )
    out["sleep_tracking"] = _latest(
        db,
        db.query(func.max(SleepSession.end_at)).filter(SleepSession.dynamic_id == dynamic_id),
    )
    out["cycle_tracking"] = _latest(
        db,
        db.query(func.max(CycleLog.updated_at)).filter(CycleLog.dynamic_id == dynamic_id),
    )
    out["image_vault"] = _latest(
        db,
        db.query(func.max(VaultImage.created_at)).filter(VaultImage.dynamic_id == dynamic_id),
    )
    out["gear"] = _latest(
        db,
        db.query(func.max(GearInventoryItem.updated_at)).filter(
            GearInventoryItem.dynamic_id == dynamic_id
        ),
    )
    out["punishment"] = _latest(
        db,
        db.query(func.max(PunishmentReport.created_at)).filter(
            PunishmentReport.dynamic_id == dynamic_id
        ),
    )
    return out


def build_utilization(db: Session, dynamic: Dynamic, *, stale_days: int = STALE_DAYS) -> dict:
    enabled = parse_enabled_features(getattr(dynamic, "enabled_features", None))
    last_map = last_activity_map(db, dynamic.id)
    now = datetime.utcnow()
    cutoff = now - timedelta(days=stale_days)
    rows = []
    unused = []
    underused = []
    for feature_id, meta in OPTIONAL_FEATURES.items():
        if meta.get("hidden"):
            continue
        pair = meta.get("paired_with")
        if pair and feature_id > pair:
            continue
        is_on = feature_id in enabled or (pair in enabled if pair else False)
        last = last_map.get(feature_id)
        if last is None and pair:
            last = last_map.get(pair)
        status = "off"
        if is_on:
            if last is None:
                status = "unused"
                unused.append(feature_id)
            elif last < cutoff:
                status = "underused"
                underused.append(feature_id)
            else:
                status = "active"
        path = FEATURE_PATHS.get(feature_id) or ""
        if path:
            path = f"/dynamic/{dynamic.id}{path}"
        rows.append(
            {
                "id": feature_id,
                "title": meta.get("title", feature_id),
                "section": meta.get("section", ""),
                "enabled": is_on,
                "last_used": _iso(last),
                "status": status,
                "path": path,
            }
        )
    return {
        "stale_days": stale_days,
        "features": rows,
        "unused": unused,
        "underused": underused,
    }


def utilization_lines(db: Session, dynamic: Dynamic) -> list[str]:
    data = build_utilization(db, dynamic)
    lines = ["Feature utilization (enabled optional modules):"]
    for row in data["features"]:
        if not row["enabled"]:
            continue
        last = row["last_used"] or "never"
        lines.append(f"  - {row['title']} ({row['id']}): {row['status']}, last {last}")
    unused = data.get("unused") or []
    under = data.get("underused") or []
    if unused or under:
        lines.append(
            "Offer toggle_feature to disable unused modules if the keyholder is not using them."
        )
    return lines
