"""Self-report confessions (sub) + keyholder punishment dashboard."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, PartnerRole, PunishmentReport, User
from .chastity_goals import (
    GOAL_KINDS,
    REQUIREMENT_TYPES,
    START_MODES,
    build_goals_progress,
    parse_goals,
    resolve_tracking_start,
    serialize_goals,
)
from .context import build_dynamic_context
from .llm import generate_text, is_llm_configured

OPEN_STATUSES = {"pending", "assigned", "ideas", "remind"}


def punishable_options(db: Session, dynamic: Dynamic, membership: Membership) -> dict:
    """Active goals + bumpable requirements (keyholder dashboard)."""
    progress = build_goals_progress(db, dynamic)
    is_dom = membership.role == PartnerRole.dominant
    goals_out = []
    for goal in progress.get("goals") or []:
        if not is_dom:
            continue
        reqs = []
        for req in goal.get("requirements") or []:
            rtype = req.get("type")
            meta = REQUIREMENT_TYPES.get(rtype) or {}
            reqs.append(
                {
                    "type": rtype,
                    "title": req.get("title") or meta.get("title") or rtype,
                    "kind": req.get("kind") or meta.get("kind") or "count",
                    "hint": req.get("hint") or meta.get("hint") or "",
                    "target": req.get("target"),
                    "current": req.get("current"),
                    "unit": req.get("unit") or ("days" if meta.get("kind") == "duration" else "count"),
                    "suggested_adds": [1, 2, 3] if meta.get("kind") == "count" else [1, 2, 3, 7],
                }
            )
        if not reqs:
            continue
        goals_out.append(
            {
                "id": goal["id"],
                "kind": goal.get("kind"),
                "tone": goal.get("tone"),
                "title": goal.get("title") or GOAL_KINDS.get(goal.get("kind"), {}).get("title", "Goal"),
                "for_membership_id": goal.get("for_membership_id"),
                "for_display_name": goal.get("for_display_name"),
                "requirements": reqs,
            }
        )
    return {
        "goals": goals_out,
        "requirement_catalog": [
            {
                "id": k,
                "title": v["title"],
                "kind": v["kind"],
                "hint": v["hint"],
                "suggested_adds": [1, 2, 3] if v["kind"] == "count" else [1, 2, 3, 7],
            }
            for k, v in REQUIREMENT_TYPES.items()
        ],
        "goal_kinds": [
            {"id": k, "title": v["title"], "tone": v["tone"]} for k, v in GOAL_KINDS.items()
        ],
        "start_modes": [
            {"id": k, "title": v["title"], "hint": v["hint"]} for k, v in START_MODES.items()
        ],
        "you_are_dominant": is_dom,
    }


def apply_requirement_bumps(dynamic: Dynamic, adjustments: list[dict]) -> list[dict]:
    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    goals = data.get("goals") or []
    by_id = {g["id"]: g for g in goals}
    applied: list[dict] = []
    for raw in adjustments or []:
        if not isinstance(raw, dict):
            continue
        goal_id = str(raw.get("goal_id") or "")
        rtype = str(raw.get("requirement_type") or "")
        try:
            add = float(raw.get("add") or 0)
        except (TypeError, ValueError):
            continue
        if add <= 0 or goal_id not in by_id or rtype not in REQUIREMENT_TYPES:
            continue
        goal = by_id[goal_id]
        reqs = goal.setdefault("requirements", [])
        matched = next((r for r in reqs if r.get("type") == rtype), None)
        meta = REQUIREMENT_TYPES[rtype]
        if matched is None:
            new_val = add if meta["kind"] == "duration" else int(add)
            reqs.append({"type": rtype, "value": new_val})
            applied.append(
                {
                    "goal_id": goal_id,
                    "goal_title": goal.get("title") or goal_id,
                    "requirement_type": rtype,
                    "requirement_title": meta["title"],
                    "previous_target": 0,
                    "added": new_val,
                    "new_target": new_val,
                    "created": True,
                }
            )
            continue
        prev = float(matched.get("value") or 0)
        if meta["kind"] == "duration":
            new_val = round(prev + add, 2)
        else:
            new_val = int(prev + add)
        matched["value"] = new_val
        applied.append(
            {
                "goal_id": goal_id,
                "goal_title": goal.get("title") or goal_id,
                "requirement_type": rtype,
                "requirement_title": meta["title"],
                "previous_target": int(prev) if meta["kind"] == "count" else prev,
                "added": int(add) if meta["kind"] == "count" else add,
                "new_target": new_val,
                "created": False,
            }
        )
    if applied:
        dynamic.chastity_goals = serialize_goals(data)
    return applied


def create_confession(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    action: str,
) -> dict:
    """Sub (or anyone) submits bad behavior only — no self-assigned punishment."""
    action_text = (action or "").strip()
    if len(action_text) < 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Describe what happened.")
    if len(action_text) > 2000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Keep the description under 2000 characters.")

    report = PunishmentReport(
        dynamic_id=dynamic.id,
        reported_by_membership_id=membership.id,
        action_text=action_text,
        status="pending",
        applied_changes="[]",
        ideas="[]",
    )
    db.add(report)
    db.flush()
    return {"report": report_out(db, report)}


def assign_punishment(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    report: PunishmentReport,
    adjustments: list[dict],
) -> dict:
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can assign punishment.")
    if report.status == "covered":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This report is already closed.")
    if not adjustments:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose at least one goal adjustment.")

    applied = apply_requirement_bumps(dynamic, adjustments)
    if not applied:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid goal adjustments.")

    # Merge with any prior applied changes
    try:
        prior = json.loads(report.applied_changes or "[]")
    except json.JSONDecodeError:
        prior = []
    if not isinstance(prior, list):
        prior = []
    report.applied_changes = json.dumps([*prior, *applied])
    report.status = "assigned"
    report.remind_at = None
    db.flush()
    return {
        "report": report_out(db, report),
        "applied": applied,
        "options": punishable_options(db, dynamic, membership),
        "follow_up": True,
    }


def _merge_applied(report: PunishmentReport, extra: list[dict]) -> None:
    try:
        prior = json.loads(report.applied_changes or "[]")
    except json.JSONDecodeError:
        prior = []
    if not isinstance(prior, list):
        prior = []
    report.applied_changes = json.dumps([*prior, *extra])


def set_goal_as_punishment(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    report: PunishmentReport,
    payload: dict,
) -> dict:
    """Create an active chastity goal as the punishment."""
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can set a goal.")
    if report.status == "covered":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This report is already closed.")

    raw = payload if isinstance(payload, dict) else {}
    kind = str(raw.get("kind") or "orgasm_grant")
    if kind not in GOAL_KINDS:
        kind = "orgasm_grant"
    title = str(raw.get("title") or GOAL_KINDS[kind]["title"]).strip()[:80]
    if len(title) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Give the goal a title.")
    start_mode = str(raw.get("start_mode") or "now")
    if start_mode not in START_MODES:
        start_mode = "now"

    for_id = str(raw.get("for_membership_id") or report.reported_by_membership_id or "")
    if for_id:
        target = db.get(Membership, for_id)
        if target is None or target.dynamic_id != dynamic.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid partner for this goal.")
    else:
        for_id = None

    reqs_in = raw.get("requirements") if isinstance(raw.get("requirements"), list) else []
    reqs = []
    for item in reqs_in:
        if not isinstance(item, dict):
            continue
        rtype = str(item.get("type") or "")
        if rtype not in REQUIREMENT_TYPES:
            continue
        try:
            value = float(item.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        meta = REQUIREMENT_TYPES[rtype]
        reqs.append({"type": rtype, "value": int(value) if meta["kind"] == "count" else round(value, 2)})
    if not reqs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one requirement.")

    now = datetime.utcnow().replace(microsecond=0)
    now_iso = now.isoformat() + "Z"
    reset_at, _label = resolve_tracking_start(
        db,
        dynamic_id=dynamic.id,
        sub_id=for_id,
        start_mode=start_mode,
    )
    goal = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "title": title,
        "for_membership_id": for_id,
        "requirements": reqs,
        "start_mode": start_mode,
        "reset_at": reset_at.isoformat() + "Z",
        "created_at": now_iso,
        "active": True,
        "archived_at": None,
        "archive_reason": None,
        "repeat_count": 0,
    }
    data = parse_goals(getattr(dynamic, "chastity_goals", None))
    data.setdefault("goals", []).append(goal)
    dynamic.chastity_goals = serialize_goals(data)

    req_bits = ", ".join(
        f"{REQUIREMENT_TYPES[r['type']]['title']} {r['value']}"
        for r in reqs
    )
    applied = [
        {
            "kind": "goal",
            "goal_id": goal["id"],
            "goal_title": title,
            "requirement_title": req_bits,
            "created": True,
        }
    ]
    _merge_applied(report, applied)
    report.status = "assigned"
    report.remind_at = None
    db.flush()
    return {
        "report": report_out(db, report),
        "applied": applied,
        "options": punishable_options(db, dynamic, membership),
        "follow_up": True,
        "goal": goal,
    }


def generate_punishment_ideas(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    user: User,
    report: PunishmentReport,
) -> dict:
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can ask for ideas.")
    if not is_llm_configured(user, dynamic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add an AI key in Settings (or configure the server key) to get punishment ideas.",
        )

    options = punishable_options(db, dynamic, membership)
    applied = []
    try:
        applied = json.loads(report.applied_changes or "[]")
    except json.JSONDecodeError:
        applied = []
    assigned_block = "(none yet)"
    if isinstance(applied, list) and applied:
        assigned_block = "\n".join(
            (
                f"- Goal set: {a.get('goal_title')}: {a.get('requirement_title')}"
                if a.get("kind") == "goal"
                else f"- Task: {a.get('content')}"
                if a.get("kind") == "task" or (a.get("content") and not a.get("goal_title"))
                else f"- {a.get('goal_title')}: {a.get('requirement_title')} +{a.get('added')} → {a.get('new_target')}"
            )
            for a in applied
            if isinstance(a, dict)
        )

    goals_block = []
    for g in options["goals"]:
        req_bits = [
            f"{r['title']} (type={r['type']}, target={r['target']}, unit={r['unit']})"
            for r in g["requirements"]
        ]
        goals_block.append(f"- {g['title']} [{g['kind']}]: " + "; ".join(req_bits))
    goals_text = "\n".join(goals_block) if goals_block else "(no active goals)"

    context = build_dynamic_context(db, dynamic, requesting_membership_id=membership.id)
    prompt = f"""The keyholder is deciding additional punishment after a confession.

Confession:
\"\"\"{report.action_text}\"\"\"

Punishment already assigned to goals:
{assigned_block}

Current active goals:
{goals_text}

Propose 4-6 ADDITIONAL task or punishment ideas that fit this couple and do not ignore what was already assigned.
Prefer freeform tasks the sub can complete, plus optional further goal bumps if still appropriate.

Return ONLY a JSON array of objects with keys:
- title (short)
- summary (1-2 sentences)
- goal_id (string or null)
- requirement_type (string or null)
- add (number; 0 if none)
- task_suggestion (string or null)

Do not wrap in markdown. JSON array only.
"""
    raw = generate_text(user=user, user_prompt=prompt, dynamic_context=context, dynamic=dynamic, tool_id="punishments", db=db)
    ideas = _parse_ideas_json(raw, options)
    report.ideas = json.dumps(ideas)
    report.status = "ideas"
    db.flush()
    return {
        "report": report_out(db, report),
        "ideas": ideas,
        "options": options,
    }


def remind_tomorrow(db: Session, *, membership: Membership, report: PunishmentReport) -> dict:
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can snooze this.")
    report.status = "remind"
    report.remind_at = datetime.utcnow() + timedelta(days=1)
    db.flush()
    return {"report": report_out(db, report)}


def mark_covered(db: Session, *, membership: Membership, report: PunishmentReport) -> dict:
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can close this.")
    report.status = "covered"
    report.resolved_at = datetime.utcnow()
    report.resolved_by_membership_id = membership.id
    report.remind_at = None
    db.flush()
    return {"report": report_out(db, report)}


def apply_idea_to_report(
    db: Session,
    *,
    dynamic: Dynamic,
    membership: Membership,
    report: PunishmentReport,
    idea_id: str,
) -> dict:
    if membership.role != PartnerRole.dominant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the keyholder can apply ideas.")
    try:
        ideas = json.loads(report.ideas or "[]")
    except json.JSONDecodeError:
        ideas = []
    idea = next((i for i in ideas if isinstance(i, dict) and str(i.get("id")) == idea_id), None)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")

    adjustments = []
    if idea.get("goal_id") and idea.get("requirement_type") and float(idea.get("add") or 0) > 0:
        adjustments.append(
            {
                "goal_id": idea["goal_id"],
                "requirement_type": idea["requirement_type"],
                "add": idea["add"],
            }
        )
    applied = apply_requirement_bumps(dynamic, adjustments) if adjustments else []
    if applied:
        try:
            prior = json.loads(report.applied_changes or "[]")
        except json.JSONDecodeError:
            prior = []
        if not isinstance(prior, list):
            prior = []
        report.applied_changes = json.dumps([*prior, *applied])
        report.status = "assigned"
    db.flush()
    return {
        "report": report_out(db, report),
        "applied": applied,
        "source_idea": idea,
        "task_suggestion": idea.get("task_suggestion"),
    }


def get_report(db: Session, dynamic_id: str, report_id: str) -> PunishmentReport | None:
    report = db.get(PunishmentReport, report_id)
    if report is None or report.dynamic_id != dynamic_id:
        return None
    return report


def list_reports(
    db: Session,
    dynamic_id: str,
    membership: Membership,
    *,
    limit: int = 40,
) -> dict:
    rows = (
        db.query(PunishmentReport)
        .filter(PunishmentReport.dynamic_id == dynamic_id)
        .order_by(PunishmentReport.created_at.desc())
        .limit(limit)
        .all()
    )
    reports = [report_out(db, r) for r in rows]
    pending = [r for r in reports if r["status"] == "pending"]
    open_for_dom = [r for r in reports if r["status"] in OPEN_STATUSES]
    return {
        "reports": reports,
        "pending": pending,
        "open": open_for_dom if membership.role == PartnerRole.dominant else pending,
        "you_are_dominant": membership.role == PartnerRole.dominant,
    }


def inbox_items_for_member(db: Session, dynamic_id: str, membership: Membership) -> list[dict]:
    """Pending confessions + due reminders for the keyholder."""
    if membership.role != PartnerRole.dominant:
        return []
    now = datetime.utcnow()
    items: list[dict] = []
    pending = (
        db.query(PunishmentReport)
        .filter(
            PunishmentReport.dynamic_id == dynamic_id,
            PunishmentReport.status == "pending",
        )
        .order_by(PunishmentReport.created_at.desc())
        .limit(20)
        .all()
    )
    for report in pending:
        items.append(
            {
                "id": f"punish-{report.id}",
                "kind": "punishment_pending",
                "title": "Punishment needed",
                "body": (report.action_text or "")[:200],
                "occurred_at": report.created_at,
                "path": f"/dynamic/{dynamic_id}/punishment/{report.id}",
            }
        )
    reminders = (
        db.query(PunishmentReport)
        .filter(
            PunishmentReport.dynamic_id == dynamic_id,
            PunishmentReport.status == "remind",
            PunishmentReport.remind_at.isnot(None),
            PunishmentReport.remind_at <= now,
        )
        .order_by(PunishmentReport.remind_at.asc())
        .limit(10)
        .all()
    )
    for report in reminders:
        items.append(
            {
                "id": f"punish-remind-{report.id}",
                "kind": "punishment_remind",
                "title": "Punishment reminder",
                "body": (report.action_text or "")[:200],
                "occurred_at": report.remind_at or report.created_at,
                "path": f"/dynamic/{dynamic_id}/punishment/{report.id}",
            }
        )
    return items


def report_out(db: Session, report: PunishmentReport) -> dict:
    members = {
        m.id: m.display_name
        for m in db.query(Membership).filter(Membership.dynamic_id == report.dynamic_id).all()
    }
    try:
        applied = json.loads(report.applied_changes or "[]")
    except json.JSONDecodeError:
        applied = []
    try:
        ideas = json.loads(report.ideas or "[]")
    except json.JSONDecodeError:
        ideas = []
    return {
        "id": report.id,
        "action_text": report.action_text,
        "status": report.status,
        "reporter_name": members.get(report.reported_by_membership_id, "Partner"),
        "reported_by_membership_id": report.reported_by_membership_id,
        "applied": applied if isinstance(applied, list) else [],
        "ideas": ideas if isinstance(ideas, list) else [],
        "remind_at": (report.remind_at.isoformat() + "Z") if report.remind_at else None,
        "resolved_at": (report.resolved_at.isoformat() + "Z") if report.resolved_at else None,
        "created_at": (report.created_at.isoformat() + "Z") if report.created_at else None,
        "needs_follow_up": report.status in {"assigned", "ideas"},
    }


def _parse_ideas_json(raw: str, options: dict) -> list[dict]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [
            {
                "id": str(uuid.uuid4()),
                "title": "Assistant idea",
                "summary": (raw or "").strip()[:400] or "Could not parse structured ideas.",
                "goal_id": None,
                "requirement_type": None,
                "add": 0,
                "task_suggestion": None,
            }
        ]
    if not isinstance(data, list):
        return []
    valid_goals = {g["id"] for g in options.get("goals") or []}
    valid_types = set(REQUIREMENT_TYPES.keys())
    cleaned = []
    for item in data[:8]:
        if not isinstance(item, dict):
            continue
        goal_id = item.get("goal_id") or None
        if goal_id and goal_id not in valid_goals:
            goal_id = None
        rtype = item.get("requirement_type") or None
        if rtype and rtype not in valid_types:
            rtype = None
        try:
            add = float(item.get("add") or 0)
        except (TypeError, ValueError):
            add = 0
        if add < 0:
            add = 0
        cleaned.append(
            {
                "id": str(uuid.uuid4()),
                "title": str(item.get("title") or "Punishment idea")[:80],
                "summary": str(item.get("summary") or "")[:500],
                "goal_id": goal_id,
                "requirement_type": rtype,
                "add": int(add) if rtype and REQUIREMENT_TYPES[rtype]["kind"] == "count" else add,
                "task_suggestion": (str(item.get("task_suggestion") or "").strip() or None),
            }
        )
    return cleaned


def format_goals_for_context(db: Session, dynamic: Dynamic) -> str:
    progress = build_goals_progress(db, dynamic)
    lines = []
    for goal in progress.get("goals") or []:
        reqs = ", ".join(
            f"{r['title']}: {r['current']}/{r['target']} {r.get('unit') or ''}".strip()
            for r in goal.get("requirements") or []
        )
        lines.append(f"- {goal.get('title')} ({goal.get('kind')}): {reqs or 'no requirements'}")
    if not lines:
        return ""
    return "Active keyholder goals:\n" + "\n".join(lines)
