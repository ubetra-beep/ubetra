"""Evaluate Assistant Domme triggers on keyholder page load."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import (
    AssistantThread,
    Dynamic,
    JournalEntry,
    Membership,
    PartnerRole,
    PunishmentReport,
)
from .assistant_chat import SUBJECT_BY_ID
from .chastity_goals import build_goals_progress
from .standing_targets import (
    build_standing_progress,
    measure_metric,
)
from .tasks_service import build_inbox


def _sub_and_dom(db: Session, dynamic_id: str) -> tuple[Membership | None, Membership | None]:
    memberships = db.query(Membership).filter(Membership.dynamic_id == dynamic_id).all()
    dominant = next((m for m in memberships if m.role == PartnerRole.dominant), None)
    sub = next((m for m in memberships if m.role == PartnerRole.submissive), None)
    return dominant, sub


def _thread_for(
    db: Session,
    *,
    dynamic_id: str,
    membership_id: str,
    subject_id: str,
    related_entity_id: str = "",
) -> AssistantThread | None:
    return (
        db.query(AssistantThread)
        .filter(
            AssistantThread.dynamic_id == dynamic_id,
            AssistantThread.membership_id == membership_id,
            AssistantThread.subject_id == subject_id,
            AssistantThread.related_entity_id == (related_entity_id or ""),
        )
        .first()
    )


def _thread_opened_by_user(db: Session, thread: AssistantThread | None) -> bool:
    if thread is None:
        return False
    from ..models import AssistantMessage

    return (
        db.query(AssistantMessage)
        .filter(AssistantMessage.thread_id == thread.id, AssistantMessage.role == "user")
        .first()
        is not None
    )


def evaluate_triggers(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
) -> list[dict]:
    """Return active trigger dicts: subject_id, nag, title, detail, related_entity_id."""
    if membership.role != PartnerRole.dominant:
        return []
    dominant, sub = _sub_and_dom(db, dynamic.id)
    dominant_id = dominant.id if dominant else None
    sub_id = sub.id if sub else None
    now = datetime.utcnow()
    out: list[dict] = []

    pending = (
        db.query(PunishmentReport)
        .filter(
            PunishmentReport.dynamic_id == dynamic.id,
            PunishmentReport.status.in_(["pending", "ideas", "remind"]),
        )
        .order_by(PunishmentReport.created_at.desc())
        .all()
    )
    for report in pending:
        thread = _thread_for(
            db,
            dynamic_id=dynamic.id,
            membership_id=membership.id,
            subject_id="confession",
            related_entity_id=report.id,
        )
        if _thread_opened_by_user(db, thread):
            continue
        snippet = (report.action_text or "").strip().replace("\n", " ")[:120]
        out.append(
            {
                "subject_id": "confession",
                "title": "Confession waiting",
                "detail": snippet or "The submissive filed a confession.",
                "related_entity_id": report.id,
                "nag": True,
                "path": f"/dynamic/{dynamic.id}/punishment/{report.id}",
            }
        )

    progress = build_standing_progress(db, dynamic)
    open_count = int(progress.get("open_task_count") or 0)
    drought_n = 3
    drought_target = next((t for t in progress["targets"] if t["metric"] == "open_tasks"), None)
    if drought_target:
        drought_n = int(drought_target.get("target") or 3)
        below = open_count < drought_n if drought_target["direction"] == "at_least" else open_count == 0
        nag = bool(drought_target.get("nag"))
    else:
        last_done = progress.get("last_completed_task_at")
        stale = True
        if last_done:
            try:
                when = datetime.fromisoformat(last_done.replace("Z", ""))
                stale = (now - when) > timedelta(days=3)
            except ValueError:
                stale = True
        below = open_count == 0 and stale
        nag = below
    if below:
        out.append(
            {
                "subject_id": "task_drought",
                "title": "Task drought",
                "detail": f"{open_count} open assigned task(s). Default floor is {drought_n}.",
                "related_entity_id": "",
                "nag": nag if drought_target else True,
                "path": f"/dynamic/{dynamic.id}/tasks",
            }
        )

    # Sub orgasms up, or ratio of keyholder/sub down.
    ratio_row = next((t for t in progress["targets"] if t["metric"] == "orgasm_ratio_dom_over_sub"), None)
    sub_row = next((t for t in progress["targets"] if t["metric"] == "sub_orgasms"), None)
    if ratio_row or sub_row:
        for row, subject in ((sub_row, "orgasm_balance"), (ratio_row, "orgasm_balance")):
            if not row or row.get("met"):
                continue
            if any(x["subject_id"] == "orgasm_balance" for x in out):
                break
            out.append(
                {
                    "subject_id": "orgasm_balance",
                    "title": "Orgasm balance",
                    "detail": (
                        f"{row.get('title')}: current {row.get('current')} vs target {row.get('target')} "
                        f"(trend {row.get('trend')}). Is this intentional?"
                    ),
                    "related_entity_id": row.get("id") or "",
                    "nag": bool(row.get("nag")),
                    "path": f"/dynamic/{dynamic.id}/tracking",
                }
            )
    else:
        sub_m = measure_metric(
            db,
            dynamic_id=dynamic.id,
            metric="sub_orgasms",
            window_days=14,
            sub_id=sub_id,
            dominant_id=dominant_id,
            now=now,
        )
        dom_m = measure_metric(
            db,
            dynamic_id=dynamic.id,
            metric="orgasms_to_dominant",
            window_days=14,
            sub_id=sub_id,
            dominant_id=dominant_id,
            now=now,
        )
        if sub_m["trend"] == "up" and float(sub_m["current"]) > float(dom_m["current"]):
            out.append(
                {
                    "subject_id": "orgasm_balance",
                    "title": "Orgasm balance",
                    "detail": (
                        f"Sub orgasms {sub_m['current']} this window (up) vs keyholder {dom_m['current']}. "
                        "Is this intentional?"
                    ),
                    "related_entity_id": "",
                    "nag": True,
                    "path": f"/dynamic/{dynamic.id}/tracking",
                }
            )

    lock_row = next(
        (t for t in progress["targets"] if t["metric"] in {"lockup_hours", "percent_locked"} and not t.get("met")),
        None,
    )
    if lock_row:
        out.append(
            {
                "subject_id": "lockup_trend",
                "title": "Lockup trend",
                "detail": (
                    f"{lock_row.get('title')}: current {lock_row.get('current')} vs target {lock_row.get('target')} "
                    f"(trend {lock_row.get('trend')}). Is this intentional?"
                ),
                "related_entity_id": lock_row.get("id") or "",
                "nag": bool(lock_row.get("nag")),
                "path": f"/dynamic/{dynamic.id}/chastity",
            }
        )
    else:
        hours = measure_metric(
            db,
            dynamic_id=dynamic.id,
            metric="lockup_hours",
            window_days=14,
            sub_id=sub_id,
            dominant_id=dominant_id,
            now=now,
        )
        if hours["trend"] == "down" and float(hours["previous"]) > 0:
            out.append(
                {
                    "subject_id": "lockup_trend",
                    "title": "Lockup trend",
                    "detail": (
                        f"Lockup hours {hours['current']} this window vs {hours['previous']} last window. "
                        "Is this intentional?"
                    ),
                    "related_entity_id": "",
                    "nag": True,
                    "path": f"/dynamic/{dynamic.id}/chastity",
                }
            )

    inbox = build_inbox(db, dynamic.id, membership)
    inbox_items = [i for i in (inbox.get("items") or []) if i.get("kind") != "feelings_logged"]
    if inbox_items:
        out.append(
            {
                "subject_id": "inbox",
                "title": "Inbox",
                "detail": f"{len(inbox_items)} item(s) while you were away.",
                "related_entity_id": "",
                "nag": False,
                "path": f"/dynamic/{dynamic.id}/tasks",
            }
        )

    journals = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.dynamic_id == dynamic.id,
            JournalEntry.partner_visible.is_(True),
            JournalEntry.created_at >= now - timedelta(days=7),
        )
        .order_by(JournalEntry.updated_at.desc())
        .limit(5)
        .all()
    )
    new_journals = [
        j
        for j in journals
        if j.membership_id != membership.id
        and not _thread_opened_by_user(
            db,
            _thread_for(
                db,
                dynamic_id=dynamic.id,
                membership_id=membership.id,
                subject_id="journal_review",
                related_entity_id=j.id,
            ),
        )
    ]
    if new_journals:
        latest = new_journals[0]
        out.append(
            {
                "subject_id": "journal_review",
                "title": "Journal review",
                "detail": latest.title or "New partner-visible journal entry.",
                "related_entity_id": latest.id,
                "nag": False,
                "path": f"/dynamic/{dynamic.id}/journal",
            }
        )

    try:
        goals = build_goals_progress(db, dynamic)
        active = [g for g in (goals.get("goals") or []) if g.get("active", True)]
        ready = [g for g in active if g.get("ready")]
        if ready:
            out.append(
                {
                    "subject_id": "goal_progress",
                    "title": "Goal progress",
                    "detail": f"{len(ready)} gift goal(s) look ready to grant.",
                    "related_entity_id": ready[0].get("id") or "",
                    "nag": False,
                    "path": f"/dynamic/{dynamic.id}/tasks?tab=goals",
                }
            )
    except Exception:
        pass

    try:
        from .feature_utilization import build_utilization

        util = build_utilization(db, dynamic)
        unused = util.get("unused") or []
        if unused:
            titles = ", ".join(unused[:4])
            out.append(
                {
                    "subject_id": "feature_audit",
                    "title": "Unused features",
                    "detail": f"Enabled but unused: {titles}.",
                    "related_entity_id": "",
                    "nag": False,
                    "path": f"/dynamic/{dynamic.id}/features",
                }
            )
    except Exception:
        pass

    return out


def index_payload(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    triggers: list[dict] | None = None,
) -> list[dict]:
    triggers = triggers if triggers is not None else evaluate_triggers(db, dynamic=dynamic, membership=membership)
    by_subject: dict[str, dict] = {}
    for trig in triggers:
        sid = trig["subject_id"]
        prev = by_subject.get(sid)
        if prev is None or (trig.get("nag") and not prev.get("nag")):
            by_subject[sid] = trig
    items = []
    for spec in SUBJECT_BY_ID.values():
        trig = by_subject.get(spec["id"])
        items.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "blurb": spec["blurb"],
                "always": bool(spec.get("always")),
                "triggered": bool(trig),
                "nag": bool(trig and trig.get("nag")),
                "detail": (trig or {}).get("detail") or spec["blurb"],
                "related_entity_id": (trig or {}).get("related_entity_id") or "",
                "path": (trig or {}).get("path") or "",
            }
        )
    return items
