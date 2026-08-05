from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from ..models import (
    Agreement,
    ChastityLockup,
    ContextLink,
    ContextLinkCategory,
    CoreKnowledge,
    Dynamic,
    Interest,
    InterestResponse,
    InterestValue,
    JournalEntry,
    LockupStatus,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    PartnerRole,
)
from ..schemas import CoreKnowledgeOut
from ..services.chastity import chastity_subs, partner_state
from ..services.tracking import partner_orgasm_counts

POSITIVE = {InterestValue.want, InterestValue.if_partner}

CORE_KNOWLEDGE_FIELDS = {
    "relationship_context": "Relationship",
    "distance": "Distance & logistics",
    "space": "Play space",
    "budget": "Budget & resources",
    "about_you": "About you",
    "desires": "Desires & fantasies",
}


def get_memberships(db: Session, dynamic_id: str) -> list[Membership]:
    return (
        db.query(Membership)
        .options(joinedload(Membership.core_knowledge), joinedload(Membership.user))
        .filter(Membership.dynamic_id == dynamic_id)
        .all()
    )


def get_or_create_core_knowledge(db: Session, membership: Membership) -> CoreKnowledge:
    if membership.core_knowledge:
        return membership.core_knowledge
    record = CoreKnowledge(membership_id=membership.id)
    db.add(record)
    db.flush()
    return record


def core_knowledge_to_out(
    record: CoreKnowledge,
    *,
    is_yours: bool,
    partner_display_name: str | None = None,
) -> CoreKnowledgeOut:
    return CoreKnowledgeOut(
        relationship_context=(record.relationship_context or ""),
        distance=(record.distance or ""),
        space=(record.space or ""),
        budget=(record.budget or ""),
        about_you=(record.about_you or ""),
        desires=(record.desires or ""),
        submitted=bool(record.submitted),
        updated_at=record.updated_at or datetime.utcnow(),
        is_yours=is_yours,
        partner_display_name=partner_display_name,
    )


def _interest_labels(db: Session, membership: Membership) -> list[str]:
    responses = (
        db.query(InterestResponse, Interest)
        .join(Interest, Interest.id == InterestResponse.interest_id)
        .filter(
            InterestResponse.membership_id == membership.id,
            InterestResponse.value.in_(POSITIVE),
        )
        .all()
    )
    labels = []
    for _response, interest in responses:
        if membership.role == PartnerRole.submissive and interest.submissive_display_override:
            labels.append(interest.submissive_display_override)
        else:
            labels.append(interest.display_copy)
    return labels


def _overlap_labels(db: Session, first: Membership, second: Membership) -> list[str]:
    first_map = {
        row.interest_id: row.value
        for row in db.query(InterestResponse)
        .filter(InterestResponse.membership_id == first.id)
        .all()
    }
    second_map = {
        row.interest_id: row.value
        for row in db.query(InterestResponse)
        .filter(InterestResponse.membership_id == second.id)
        .all()
    }
    overlap_ids = [
        interest_id
        for interest_id, value in first_map.items()
        if value in POSITIVE and second_map.get(interest_id) in POSITIVE
    ]
    if not overlap_ids:
        return []
    interests = db.query(Interest).filter(Interest.id.in_(overlap_ids)).all()
    return [interest.display_copy for interest in interests]


def response_map(db: Session, membership_id: str) -> dict[str, InterestValue]:
    rows = (
        db.query(InterestResponse)
        .filter(InterestResponse.membership_id == membership_id)
        .all()
    )
    return {row.interest_id: row.value for row in rows}


def compute_overlap(
    your_responses: dict[str, InterestValue],
    partner_responses: dict[str, InterestValue],
) -> list[str]:
    overlap: list[str] = []
    for interest_id, value in your_responses.items():
        if value not in POSITIVE:
            continue
        partner_value = partner_responses.get(interest_id)
        if partner_value in POSITIVE:
            overlap.append(interest_id)
    return overlap


CONTEXT_CATEGORY_LABELS = {
    ContextLinkCategory.fictional_story: "Fictional stories",
    ContextLinkCategory.contract: "Contracts & agreements",
    ContextLinkCategory.reference_guide: "Reference guides",
    ContextLinkCategory.scene_inspiration: "Scene inspiration",
    ContextLinkCategory.other: "Other",
}


def _format_core_knowledge(
    knowledge: CoreKnowledge,
    *,
    focus_fields: list[str] | None = None,
) -> list[str]:
    lines = []
    fields = focus_fields if focus_fields else list(CORE_KNOWLEDGE_FIELDS.keys())
    for key in fields:
        if key not in CORE_KNOWLEDGE_FIELDS:
            continue
        value = (getattr(knowledge, key, None) or "").strip()
        if value:
            lines.append(f"    {CORE_KNOWLEDGE_FIELDS[key]}: {value}")
    return lines


def _format_tracking_context(db: Session, dynamic_id: str, memberships: list[Membership]) -> list[str]:
    lines: list[str] = []
    org_counts = partner_orgasm_counts(db, dynamic_id, memberships)
    lines.append("Sex & orgasm tracking (last 90 days):")
    for membership in memberships:
        role = "dominant" if membership.role == PartnerRole.dominant else "submissive"
        lines.append(f"  {membership.display_name} ({role}): {org_counts.get(membership.id, 0)} orgasms logged")

    chastity_lines: list[str] = []
    tracked_subs = chastity_subs(memberships)
    for membership in tracked_subs:
        stats = partner_state(db, dynamic_id, membership)
        if stats["state"] == "locked":
            chastity_lines.append(
                f"  {membership.display_name} (submissive): LOCKED for {stats['current_duration_label']}"
            )
        elif stats["state"] == "on_break":
            chastity_lines.append(
                f"  {membership.display_name} (submissive): on break for {stats['break_duration_label']}"
            )
        chastity_lines.append(
            f"  {membership.display_name} (submissive): {stats['lockup_count']} lockups, "
            f"{stats['percent_locked_all_time']}% locked all time, "
            f"longest {stats['longest_lockup_label'] or 'n/a'}"
        )

    if chastity_lines:
        lines.append("")
        lines.append("Chastity / lockup tracking:")
        lines.extend(chastity_lines)

    recent_orgs = (
        db.query(OrgTrackingEntry)
        .filter(OrgTrackingEntry.dynamic_id == dynamic_id)
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .limit(5)
        .all()
    )
    if recent_orgs:
        membership_map = {m.id: m for m in memberships}
        lines.append("")
        lines.append("Recent orgasm/sex events:")
        for entry in recent_orgs:
            partner = membership_map.get(entry.for_membership_id)
            name = partner.display_name if partner else "Partner"
            when = entry.occurred_at.strftime("%Y-%m-%d")
            lines.append(f"  {when}: {name} — {entry.event_type.value}")

    active_lockups = (
        db.query(ChastityLockup)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.status == LockupStatus.active,
            ChastityLockup.for_membership_id.in_([m.id for m in tracked_subs] or [""]),
        )
        .all()
    )
    for lockup in active_lockups:
        partner = next((m for m in memberships if m.id == lockup.for_membership_id), None)
        if partner and lockup.device_notes.strip():
            lines.append(
                f"  Active lockup notes for {partner.display_name}: {lockup.device_notes.strip()[:200]}"
            )

    from .feelings import recent_checkins

    feeling_rows = recent_checkins(db, dynamic_id, limit=8, since_hours=24 * 14)
    if feeling_rows:
        membership_map = {m.id: m for m in memberships}
        lines.append("")
        lines.append("Recent feelings check-ins:")
        for row in feeling_rows:
            partner = membership_map.get(row.for_membership_id)
            name = partner.display_name if partner else "Partner"
            when = row.occurred_at.strftime("%Y-%m-%d") if row.occurred_at else "?"
            try:
                import json

                sels = json.loads(row.selections_json or "[]")
                labels = [
                    s.get("label") for s in sels if isinstance(s, dict) and s.get("label")
                ]
            except Exception:
                labels = []
            label_bit = ", ".join(labels[:3]) if labels else "feelings"
            lines.append(f"  {when}: {name} ({row.context}) — {label_bit}")

    lines.append("")
    lines.append(
        "Use this tracking data when relevant — e.g. denial, teasing, release timing, "
        "feelings before/after play, or balancing orgasm frequency — but only within negotiated boundaries."
    )
    return lines


def _context_flag(context_flags, name: str, default: bool) -> bool:
    """Read a boolean flag from a JournalAssistContextFlags-like object or dict."""
    if context_flags is None:
        return default
    if isinstance(context_flags, dict):
        return bool(context_flags.get(name, default))
    return bool(getattr(context_flags, name, default))


def build_dynamic_context(
    db: Session,
    dynamic: Dynamic,
    *,
    requesting_membership_id: str | None = None,
    knowledge_focus_fields: list[str] | None = None,
    include_tracking: bool = True,
    context_flags=None,
) -> str:
    memberships = get_memberships(db, dynamic.id)
    if not memberships:
        return f"Dynamic name: {dynamic.name}"

    lines = [
        f"Dynamic name: {dynamic.name}",
        "This is a consensual adult BDSM relationship dynamic. All suggestions must assume informed consent.",
        "",
    ]

    agreements = (
        db.query(Agreement)
        .filter(Agreement.dynamic_id == dynamic.id)
        .order_by(Agreement.position, Agreement.created_at)
        .all()
    )
    approved_agreements = [a for a in agreements if a.approved_content.strip()]
    if approved_agreements and not _context_flag(context_flags, "agreements", True):
        approved_agreements = []
    if approved_agreements:
        lines.append("Approved ground rules and agreements:")
        for agreement in approved_agreements:
            title = agreement.title.strip() or "Agreement"
            lines.append(f"- {title}: {agreement.approved_content.strip()}")
        lines.append("")

    for membership in memberships:
        role = "dominant" if membership.role == PartnerRole.dominant else "submissive"
        is_requester = membership.id == requesting_membership_id
        sex = ""
        if membership.user is not None:
            sex = (getattr(membership.user, "biological_sex", None) or "").strip()
        sex_bit = f", {sex}" if sex and sex != "prefer_not_to_say" else ""
        lines.append(f"Partner: {membership.display_name} ({role}{sex_bit})")

        if is_requester and membership.interview_completed and membership.interview_summary.strip():
            lines.append("  Personal dynamic interview (what they want):")
            lines.append(f"    {membership.interview_summary.strip()}")

        if is_requester and membership.spti_completed_at and membership.spti_data.strip():
            lines.append("  SPTI personality profile (for tailoring tone and scene ideas):")
            lines.append(f"    {membership.spti_data.strip()[:2000]}")
        elif not is_requester and membership.spti_completed_at:
            lines.append("  SPTI profile: completed (details private)")

        knowledge = membership.core_knowledge
        if is_requester and knowledge and knowledge.submitted:
            focus = knowledge_focus_fields or None
            ck_lines = _format_core_knowledge(knowledge, focus_fields=focus)
            if ck_lines:
                label = "Core knowledge"
                if focus:
                    labels = [CORE_KNOWLEDGE_FIELDS.get(k, k) for k in focus if k in CORE_KNOWLEDGE_FIELDS]
                    if labels:
                        label += f" (emphasis: {', '.join(labels)})"
                lines.append(f"  {label}:")
                lines.extend(ck_lines)
        elif not is_requester and knowledge and knowledge.submitted:
            lines.append("  Core knowledge: submitted (private — not shown)")
        # Kink lists always feed the LLM for scene context, even when not shared with partner.
        if membership.survey_submitted:
            wants = _interest_labels(db, membership)
            if wants:
                privacy = "shared with partner" if membership.share_kinks else "private to AI"
                lines.append(
                    f"  Kink survey highlights ({privacy}): {', '.join(wants[:25])}"
                )
        lines.append("")

    if len(memberships) == 2:
        dominant = next((m for m in memberships if m.role == PartnerRole.dominant), None)
        if dominant and dominant.share_kinks:
            overlap = _overlap_labels(db, memberships[0], memberships[1])
            if overlap:
                lines.append("Shared interests (both want or are open; dominant enabled sharing):")
                lines.append(", ".join(overlap[:40]))
                lines.append("")

    links = (
        db.query(ContextLink)
        .filter(
            ContextLink.dynamic_id == dynamic.id,
            ContextLink.use_for_ai.is_(True),
        )
        .order_by(ContextLink.created_at.desc())
        .limit(20)
        .all()
    )
    if links:
        from .context_files import CONTEXT_SUBJECTS, normalize_subject

        allow_stories = _context_flag(context_flags, "stories", True)
        allow_scenes = _context_flag(context_flags, "scenes", True)
        filtered_links = []
        for link in links:
            subject = normalize_subject(getattr(link, "subject", None) or link.category.value)
            if subject == "stories" and not allow_stories:
                continue
            if subject == "scenes" and not allow_scenes:
                continue
            filtered_links.append((link, subject))
        if filtered_links:
            lines.append("Context library (files & notes tagged for AI):")
            for link, subject in filtered_links:
                label = CONTEXT_SUBJECTS.get(subject, subject)
                lines.append(f"  [{label}] {link.title}")
                if link.notes.strip():
                    lines.append(f"    Notes: {link.notes.strip()[:500]}")
                if link.fetched_text.strip():
                    snippet = link.fetched_text.strip()[:800]
                    lines.append(f"    Excerpt: {snippet}")
            lines.append("")

    if _context_flag(context_flags, "journals", True):
        journals = (
            db.query(JournalEntry)
            .filter(
                JournalEntry.dynamic_id == dynamic.id,
                JournalEntry.use_for_ai.is_(True),
            )
            .order_by(JournalEntry.updated_at.desc())
            .limit(12)
            .all()
        )
        # Only feed journals to the AI that are either shared with the partner
        # or written by the person requesting this context (their own private journal).
        journals = [
            entry
            for entry in journals
            if entry.partner_visible or entry.membership_id == requesting_membership_id
        ]
        if journals:
            membership_map = {m.id: m for m in memberships}
            lines.append("Journal entries (shared with AI):")
            for entry in journals:
                author = membership_map.get(entry.membership_id)
                name = author.display_name if author else "Partner"
                lines.append(f"  [{name}] {entry.title or 'Untitled'}")
                body = (entry.body or "").strip()
                if body:
                    lines.append(f"    {body[:600]}")
            lines.append("")

    if include_tracking and _context_flag(context_flags, "tracking", True):
        lines.append("Activity tracking:")
        lines.extend(_format_tracking_context(db, dynamic.id, memberships))
        lines.append("")
        try:
            from .punishments import format_goals_for_context

            goals_block = format_goals_for_context(db, dynamic)
            if goals_block:
                lines.append(goals_block)
                lines.append("")
        except Exception:
            pass

    if requesting_membership_id:
        requester = next((m for m in memberships if m.id == requesting_membership_id), None)
        if requester and not requester.interview_completed:
            lines.append(
                "NOTE: The requesting partner has not completed their dynamic interview yet. "
                "Suggestions should be conservative and ask clarifying questions if needed."
            )

    return "\n".join(lines).strip()
