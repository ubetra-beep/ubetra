from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..models import (
    ActOfSubmission,
    ActStatus,
    Agreement,
    ChastityLockup,
    ContextLink,
    ContextLinkCategory,
    CoreKnowledge,
    Dynamic,
    InterestResponse,
    InterestValue,
    InterviewMessage,
    InterviewRole,
    LockupStatus,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    PartnerRole,
    Task,
    TaskList,
    TaskVisibility,
    User,
)

EXPORT_VERSION = 1


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


def _partner_membership(membership: Membership, dynamic: Dynamic) -> Membership | None:
    return next((m for m in dynamic.memberships if m.id != membership.id), None)


def _role_label(membership: Membership | None) -> str | None:
    if membership is None:
        return None
    return membership.role.value


def build_user_export(db: Session, user: User) -> dict[str, Any]:
    memberships = (
        db.query(Membership)
        .options(
            joinedload(Membership.dynamic).joinedload(Dynamic.memberships),
            joinedload(Membership.interest_responses),
            joinedload(Membership.core_knowledge),
            joinedload(Membership.interview_messages),
        )
        .filter(Membership.user_id == user.id)
        .all()
    )

    dynamics_payload: list[dict[str, Any]] = []
    for membership in memberships:
        dynamic = membership.dynamic
        partner = _partner_membership(membership, dynamic)

        interest_responses = [
            {
                "interest_id": row.interest_id,
                "value": row.value.value,
                "updated_at": _iso(row.updated_at),
            }
            for row in membership.interest_responses
        ]

        core_knowledge = None
        if membership.core_knowledge:
            ck = membership.core_knowledge
            core_knowledge = {
                "relationship_context": ck.relationship_context,
                "distance": ck.distance,
                "space": ck.space,
                "budget": ck.budget,
                "about_you": ck.about_you,
                "desires": ck.desires,
                "submitted": ck.submitted,
                "updated_at": _iso(ck.updated_at),
            }

        interview_messages = [
            {
                "role": msg.role.value,
                "content": msg.content,
                "created_at": _iso(msg.created_at),
            }
            for msg in sorted(membership.interview_messages, key=lambda m: m.created_at)
        ]

        acts_requested = (
            db.query(ActOfSubmission)
            .filter(ActOfSubmission.requested_by_membership_id == membership.id)
            .order_by(ActOfSubmission.created_at)
            .all()
        )
        acts_payload = [
            {
                "status": act.status.value,
                "hint_text": act.hint_text,
                "knowledge_focus": act.knowledge_focus,
                "sub_response_text": act.sub_response_text,
                "sub_rating": act.sub_rating,
                "dom_verified": act.dom_verified,
                "dom_notes": act.dom_notes,
                "created_at": _iso(act.created_at),
                "completed_at": _iso(act.completed_at),
                "verified_at": _iso(act.verified_at),
            }
            for act in acts_requested
        ]

        context_links = (
            db.query(ContextLink)
            .filter(ContextLink.added_by_membership_id == membership.id)
            .order_by(ContextLink.created_at)
            .all()
        )
        context_links_payload = [
            {
                "category": link.category.value,
                "title": link.title,
                "url": link.url,
                "notes": link.notes,
                "fetched_text": link.fetched_text,
                "created_at": _iso(link.created_at),
            }
            for link in context_links
        ]

        org_entries = (
            db.query(OrgTrackingEntry)
            .filter(OrgTrackingEntry.logged_by_membership_id == membership.id)
            .order_by(OrgTrackingEntry.occurred_at)
            .all()
        )
        org_payload = []
        for entry in org_entries:
            target = db.get(Membership, entry.for_membership_id)
            for_role = "self"
            if target and target.id != membership.id:
                for_role = target.role.value
            org_payload.append(
                {
                    "event_type": entry.event_type.value,
                    "notes": entry.notes,
                    "tags": entry.tags,
                    "for_role": for_role,
                    "occurred_at": _iso(entry.occurred_at),
                    "created_at": _iso(entry.created_at),
                }
            )

        chastity_lockups = (
            db.query(ChastityLockup)
            .filter(
                ChastityLockup.dynamic_id == dynamic.id,
                ChastityLockup.started_by_membership_id == membership.id,
            )
            .order_by(ChastityLockup.started_at)
            .all()
        )
        chastity_payload = []
        for lockup in chastity_lockups:
            target = db.get(Membership, lockup.for_membership_id)
            for_role = "self"
            if target and target.id != membership.id:
                for_role = target.role.value
            chastity_payload.append(
                {
                    "for_role": for_role,
                    "device_notes": lockup.device_notes,
                    "release_notes": lockup.release_notes,
                    "status": lockup.status.value,
                    "started_at": _iso(lockup.started_at),
                    "ended_at": _iso(lockup.ended_at),
                }
            )

        task_lists = (
            db.query(TaskList)
            .options(joinedload(TaskList.tasks))
            .filter(TaskList.created_by_membership_id == membership.id)
            .order_by(TaskList.created_at)
            .all()
        )
        task_lists_payload = []
        for task_list in task_lists:
            tasks = sorted(task_list.tasks, key=lambda t: t.position)
            task_lists_payload.append(
                {
                    "title": task_list.title,
                    "created_at": _iso(task_list.created_at),
                    "tasks": [
                        {
                            "position": task.position,
                            "content": task.content,
                            "visibility": task.visibility.value,
                            "completed_at": _iso(task.completed_at),
                        }
                        for task in tasks
                    ],
                }
            )

        agreements = (
            db.query(Agreement)
            .filter(
                Agreement.dynamic_id == dynamic.id,
                or_(
                    Agreement.created_by_membership_id == membership.id,
                    Agreement.pending_by_membership_id == membership.id,
                    Agreement.approved_by_membership_id == membership.id,
                ),
            )
            .order_by(Agreement.position, Agreement.created_at)
            .all()
        )
        agreements_payload = [
            {
                "title": agreement.title,
                "approved_content": agreement.approved_content,
                "pending_content": agreement.pending_content,
                "pending_at": _iso(agreement.pending_at),
                "approved_at": _iso(agreement.approved_at),
                "position": agreement.position,
                "created_at": _iso(agreement.created_at),
                "updated_at": _iso(agreement.updated_at),
                "you_created": agreement.created_by_membership_id == membership.id,
                "you_pending": agreement.pending_by_membership_id == membership.id,
                "you_approved": agreement.approved_by_membership_id == membership.id,
            }
            for agreement in agreements
        ]

        dynamics_payload.append(
            {
                "invite_code": dynamic.invite_code,
                "dynamic_name": dynamic.name,
                "dynamic_created_at": _iso(dynamic.created_at),
                "membership": {
                    "role": membership.role.value,
                    "display_name": membership.display_name,
                    "survey_submitted": membership.survey_submitted,
                    "survey_submitted_at": _iso(membership.survey_submitted_at),
                    "interview_completed": membership.interview_completed,
                    "interview_summary": membership.interview_summary,
                    "chastity_enabled": membership.chastity_enabled,
                    "chastity_max_lock_hours": membership.chastity_max_lock_hours,
                    "created_at": _iso(membership.created_at),
                },
                "partner_role": _role_label(partner),
                "interest_responses": interest_responses,
                "core_knowledge": core_knowledge,
                "interview_messages": interview_messages,
                "acts_requested": acts_payload,
                "context_links": context_links_payload,
                "org_entries": org_payload,
                "chastity_lockups": chastity_payload,
                "task_lists_created": task_lists_payload,
                "agreements": agreements_payload,
            }
        )

    return {
        "ubetra_export_version": EXPORT_VERSION,
        "exported_at": _iso(datetime.utcnow()),
        "source_username": user.username,
        "llm": {
            "provider": user.llm_provider,
            "api_key": user.llm_api_key,
            "model": user.llm_model,
        },
        "assistant": {
            "tone": user.assistant_tone,
            "extra_instructions": user.assistant_extra_instructions,
            "include_tracking": user.assistant_include_tracking,
        },
        "dynamics": dynamics_payload,
    }


def _membership_for_invite(db: Session, user: User, invite_code: str) -> Membership | None:
    return (
        db.query(Membership)
        .join(Dynamic)
        .filter(
            Membership.user_id == user.id,
            Dynamic.invite_code == invite_code.upper(),
        )
        .first()
    )


def _membership_by_role(dynamic: Dynamic, role: str) -> Membership | None:
    try:
        partner_role = PartnerRole(role)
    except ValueError:
        return None
    return next((m for m in dynamic.memberships if m.role == partner_role), None)


def _agreement_key(title: str, position: int, created_at: str | None) -> tuple[str, int, str]:
    return (title.strip(), position, created_at or "")


def import_user_export(db: Session, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    version = payload.get("ubetra_export_version")
    if version != EXPORT_VERSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export version: {version}",
        )

    warnings: list[str] = []
    restored: list[str] = []
    skipped: list[dict[str, str]] = []

    llm = payload.get("llm") or {}
    if isinstance(llm, dict):
        user.llm_provider = str(llm.get("provider") or user.llm_provider)
        user.llm_model = str(llm.get("model") or user.llm_model)
        if llm.get("api_key"):
            user.llm_api_key = str(llm["api_key"])

    assistant = payload.get("assistant") or {}
    if isinstance(assistant, dict):
        if assistant.get("tone"):
            user.assistant_tone = str(assistant["tone"])
        if "extra_instructions" in assistant:
            user.assistant_extra_instructions = str(assistant.get("extra_instructions") or "")
        if "include_tracking" in assistant:
            user.assistant_include_tracking = bool(assistant.get("include_tracking"))

    for dynamic_data in payload.get("dynamics") or []:
        invite_code = str(dynamic_data.get("invite_code") or "").upper()
        if not invite_code:
            skipped.append({"invite_code": "", "reason": "Missing invite code in export"})
            continue

        membership = _membership_for_invite(db, user, invite_code)
        if membership is None:
            skipped.append(
                {
                    "invite_code": invite_code,
                    "reason": "Join this dynamic with the same invite code before importing.",
                }
            )
            continue

        dynamic = db.get(Dynamic, membership.dynamic_id)
        if dynamic is None:
            skipped.append({"invite_code": invite_code, "reason": "Dynamic not found"})
            continue

        membership_data = dynamic_data.get("membership") or {}
        membership.role = PartnerRole(membership_data.get("role") or membership.role.value)
        membership.display_name = str(
            membership_data.get("display_name") or membership.display_name
        )
        membership.survey_submitted = bool(membership_data.get("survey_submitted"))
        membership.survey_submitted_at = _parse_iso(membership_data.get("survey_submitted_at"))
        membership.interview_completed = bool(membership_data.get("interview_completed"))
        membership.interview_summary = str(membership_data.get("interview_summary") or "")
        if "chastity_enabled" in membership_data:
            membership.chastity_enabled = bool(membership_data.get("chastity_enabled"))
        if "chastity_max_lock_hours" in membership_data:
            value = membership_data.get("chastity_max_lock_hours")
            membership.chastity_max_lock_hours = int(value) if value is not None else None
        if membership_data.get("created_at"):
            membership.created_at = _parse_iso(membership_data.get("created_at")) or membership.created_at

        for row in dynamic_data.get("interest_responses") or []:
            interest_id = row.get("interest_id")
            if not interest_id:
                continue
            existing = (
                db.query(InterestResponse)
                .filter(
                    InterestResponse.membership_id == membership.id,
                    InterestResponse.interest_id == interest_id,
                )
                .first()
            )
            value = row.get("value")
            updated_at = _parse_iso(row.get("updated_at"))
            if existing:
                existing.value = InterestValue(value)
                if updated_at:
                    existing.updated_at = updated_at
            else:
                db.add(
                    InterestResponse(
                        membership_id=membership.id,
                        interest_id=interest_id,
                        value=InterestValue(value),
                        updated_at=updated_at or datetime.utcnow(),
                    )
                )

        ck_data = dynamic_data.get("core_knowledge")
        if isinstance(ck_data, dict):
            ck = membership.core_knowledge
            if ck is None:
                ck = CoreKnowledge(membership_id=membership.id)
                db.add(ck)
                db.flush()
            ck.relationship_context = str(ck_data.get("relationship_context") or "")
            ck.distance = str(ck_data.get("distance") or "")
            ck.space = str(ck_data.get("space") or "")
            ck.budget = str(ck_data.get("budget") or "")
            ck.about_you = str(ck_data.get("about_you") or "")
            ck.desires = str(ck_data.get("desires") or "")
            ck.submitted = bool(ck_data.get("submitted"))
            if ck_data.get("updated_at"):
                ck.updated_at = _parse_iso(ck_data.get("updated_at")) or ck.updated_at

        db.query(InterviewMessage).filter(
            InterviewMessage.membership_id == membership.id
        ).delete(synchronize_session=False)
        for msg in dynamic_data.get("interview_messages") or []:
            db.add(
                InterviewMessage(
                    membership_id=membership.id,
                    role=InterviewRole(msg.get("role")),
                    content=str(msg.get("content") or ""),
                    created_at=_parse_iso(msg.get("created_at")) or datetime.utcnow(),
                )
            )

        db.query(ActOfSubmission).filter(
            ActOfSubmission.requested_by_membership_id == membership.id
        ).delete(synchronize_session=False)
        for act in dynamic_data.get("acts_requested") or []:
            db.add(
                ActOfSubmission(
                    dynamic_id=dynamic.id,
                    requested_by_membership_id=membership.id,
                    status=ActStatus(act.get("status")),
                    hint_text=str(act.get("hint_text") or ""),
                    knowledge_focus=str(act.get("knowledge_focus") or ""),
                    sub_response_text=act.get("sub_response_text"),
                    sub_rating=act.get("sub_rating"),
                    dom_verified=act.get("dom_verified"),
                    dom_notes=act.get("dom_notes"),
                    created_at=_parse_iso(act.get("created_at")) or datetime.utcnow(),
                    completed_at=_parse_iso(act.get("completed_at")),
                    verified_at=_parse_iso(act.get("verified_at")),
                )
            )

        db.query(ContextLink).filter(
            ContextLink.added_by_membership_id == membership.id
        ).delete(synchronize_session=False)
        for link in dynamic_data.get("context_links") or []:
            db.add(
                ContextLink(
                    dynamic_id=dynamic.id,
                    added_by_membership_id=membership.id,
                    category=ContextLinkCategory(link.get("category")),
                    title=str(link.get("title") or ""),
                    url=str(link.get("url") or ""),
                    notes=str(link.get("notes") or ""),
                    fetched_text=str(link.get("fetched_text") or ""),
                    created_at=_parse_iso(link.get("created_at")) or datetime.utcnow(),
                )
            )

        db.query(OrgTrackingEntry).filter(
            OrgTrackingEntry.logged_by_membership_id == membership.id
        ).delete(synchronize_session=False)
        for entry in dynamic_data.get("org_entries") or []:
            for_role = entry.get("for_role") or "self"
            if for_role == "self":
                target_membership = membership
            else:
                target_membership = _membership_by_role(dynamic, for_role)
            if target_membership is None:
                warnings.append(
                    f"{invite_code}: skipped org entry — partner role '{for_role}' not in dynamic yet"
                )
                continue
            db.add(
                OrgTrackingEntry(
                    dynamic_id=dynamic.id,
                    logged_by_membership_id=membership.id,
                    for_membership_id=target_membership.id,
                    event_type=OrgEventType(entry.get("event_type")),
                    notes=str(entry.get("notes") or ""),
                    tags=str(entry.get("tags") or ""),
                    occurred_at=_parse_iso(entry.get("occurred_at")) or datetime.utcnow(),
                    created_at=_parse_iso(entry.get("created_at")) or datetime.utcnow(),
                )
            )

        for lockup_data in dynamic_data.get("chastity_lockups") or []:
            for_role = lockup_data.get("for_role") or "self"
            if for_role == "self":
                target_membership = membership
            else:
                target_membership = _membership_by_role(dynamic, for_role)
            if target_membership is None:
                warnings.append(
                    f"{invite_code}: skipped chastity lockup — partner role '{for_role}' not in dynamic yet"
                )
                continue
            status_value = lockup_data.get("status") or "ended"
            db.add(
                ChastityLockup(
                    dynamic_id=dynamic.id,
                    for_membership_id=target_membership.id,
                    started_by_membership_id=membership.id,
                    device_notes=str(lockup_data.get("device_notes") or ""),
                    release_notes=str(lockup_data.get("release_notes") or ""),
                    status=LockupStatus(status_value),
                    started_at=_parse_iso(lockup_data.get("started_at")) or datetime.utcnow(),
                    ended_at=_parse_iso(lockup_data.get("ended_at")),
                )
            )

        existing_lists = (
            db.query(TaskList)
            .filter(TaskList.created_by_membership_id == membership.id)
            .all()
        )
        for task_list in existing_lists:
            db.query(Task).filter(Task.task_list_id == task_list.id).delete(
                synchronize_session=False
            )
        db.query(TaskList).filter(TaskList.created_by_membership_id == membership.id).delete(
            synchronize_session=False
        )
        for task_list_data in dynamic_data.get("task_lists_created") or []:
            task_list = TaskList(
                dynamic_id=dynamic.id,
                title=str(task_list_data.get("title") or "Tasks"),
                created_by_membership_id=membership.id,
                created_at=_parse_iso(task_list_data.get("created_at")) or datetime.utcnow(),
            )
            db.add(task_list)
            db.flush()
            for task_data in task_list_data.get("tasks") or []:
                db.add(
                    Task(
                        task_list_id=task_list.id,
                        position=int(task_data.get("position") or 0),
                        content=str(task_data.get("content") or ""),
                        visibility=TaskVisibility(task_data.get("visibility") or "visible"),
                        completed_at=_parse_iso(task_data.get("completed_at")),
                    )
                )

        existing_agreements = {
            _agreement_key(a.title, a.position, _iso(a.created_at)): a
            for a in db.query(Agreement).filter(Agreement.dynamic_id == dynamic.id).all()
        }
        for agreement_data in dynamic_data.get("agreements") or []:
            key = _agreement_key(
                str(agreement_data.get("title") or ""),
                int(agreement_data.get("position") or 0),
                agreement_data.get("created_at"),
            )
            agreement = existing_agreements.get(key)
            pending_by = membership.id if agreement_data.get("you_pending") else None
            approved_by = membership.id if agreement_data.get("you_approved") else None
            created_by = membership.id if agreement_data.get("you_created") else None

            if agreement is None and agreement_data.get("you_created"):
                agreement = Agreement(
                    id=str(uuid.uuid4()),
                    dynamic_id=dynamic.id,
                    title=str(agreement_data.get("title") or ""),
                    approved_content=str(agreement_data.get("approved_content") or ""),
                    pending_content=str(agreement_data.get("pending_content") or ""),
                    pending_by_membership_id=pending_by,
                    pending_at=_parse_iso(agreement_data.get("pending_at")),
                    approved_at=_parse_iso(agreement_data.get("approved_at")),
                    approved_by_membership_id=approved_by,
                    created_by_membership_id=created_by or membership.id,
                    position=int(agreement_data.get("position") or 0),
                    created_at=_parse_iso(agreement_data.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_iso(agreement_data.get("updated_at")) or datetime.utcnow(),
                )
                db.add(agreement)
                existing_agreements[key] = agreement
                continue

            if agreement is None:
                warnings.append(f"{invite_code}: skipped agreement '{key[0]}' — not found in dynamic")
                continue

            if agreement_data.get("you_created"):
                agreement.title = str(agreement_data.get("title") or agreement.title)
                agreement.approved_content = str(
                    agreement_data.get("approved_content") or agreement.approved_content
                )
                agreement.pending_content = str(
                    agreement_data.get("pending_content") or agreement.pending_content
                )
                agreement.position = int(agreement_data.get("position") or agreement.position)
                if agreement_data.get("created_at"):
                    agreement.created_at = (
                        _parse_iso(agreement_data.get("created_at")) or agreement.created_at
                    )
                if agreement_data.get("updated_at"):
                    agreement.updated_at = (
                        _parse_iso(agreement_data.get("updated_at")) or agreement.updated_at
                    )
            if agreement_data.get("you_pending"):
                agreement.pending_content = str(agreement_data.get("pending_content") or "")
                agreement.pending_by_membership_id = membership.id
                agreement.pending_at = _parse_iso(agreement_data.get("pending_at"))
            if agreement_data.get("you_approved"):
                agreement.approved_content = str(
                    agreement_data.get("approved_content") or agreement.approved_content
                )
                agreement.approved_at = _parse_iso(agreement_data.get("approved_at"))
                agreement.approved_by_membership_id = membership.id
                if not agreement.pending_content.strip():
                    agreement.pending_by_membership_id = None
                    agreement.pending_at = None

        restored.append(invite_code)

    db.commit()
    return {
        "llm_restored": bool(llm),
        "dynamics_restored": restored,
        "dynamics_skipped": skipped,
        "warnings": warnings,
    }
