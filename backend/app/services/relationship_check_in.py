"""LLM relationship check-in: interviews + ground rules + tracking → shared report."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Agreement,
    ChastityLockup,
    Dynamic,
    Membership,
    OrgTrackingEntry,
    RelationshipCheckIn,
    User,
)
from .chat_events import post_activity_event
from .context import build_dynamic_context, get_memberships
from .history_dashboard import build_history_dashboard
from .llm import generate_text, is_llm_configured
from .push import _notify_users_payload

logger = logging.getLogger(__name__)

CHECK_IN_INTERVAL = timedelta(days=90)
INVITE_COOLDOWN = timedelta(days=14)
WINDOW_DAYS = 90

_stop = threading.Event()
_thread: threading.Thread | None = None


def earliest_tracking_log_at(db: Session, dynamic_id: str) -> datetime | None:
    """Oldest orgasm or chastity log (not dynamic created_at alone)."""
    stamps: list[datetime] = []
    for value in (
        db.query(func.min(OrgTrackingEntry.occurred_at))
        .filter(OrgTrackingEntry.dynamic_id == dynamic_id)
        .scalar(),
        db.query(func.min(ChastityLockup.started_at))
        .filter(ChastityLockup.dynamic_id == dynamic_id)
        .scalar(),
    ):
        if value is None:
            continue
        if getattr(value, "tzinfo", None) is not None:
            value = value.replace(tzinfo=None)
        stamps.append(value)
    return min(stamps) if stamps else None


def last_check_in(db: Session, dynamic_id: str) -> RelationshipCheckIn | None:
    return (
        db.query(RelationshipCheckIn)
        .filter(RelationshipCheckIn.dynamic_id == dynamic_id)
        .order_by(RelationshipCheckIn.created_at.desc())
        .first()
    )


def check_in_due(db: Session, dynamic: Dynamic, *, now: datetime | None = None) -> bool:
    """True when tracking history is 3+ months old and no check-in in the last 3 months."""
    now = now or datetime.utcnow()
    earliest = earliest_tracking_log_at(db, dynamic.id)
    if earliest is None or earliest > now - CHECK_IN_INTERVAL:
        return False
    latest = last_check_in(db, dynamic.id)
    if latest and latest.created_at > now - CHECK_IN_INTERVAL:
        return False
    return True


def should_post_invite(db: Session, dynamic: Dynamic, *, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if not check_in_due(db, dynamic, now=now):
        return False
    invited = getattr(dynamic, "check_in_invite_posted_at", None)
    if invited is None:
        return True
    if getattr(invited, "tzinfo", None) is not None:
        invited = invited.replace(tzinfo=None)
    latest = last_check_in(db, dynamic.id)
    # After a completed check-in, allow a new invite once due again.
    if latest and invited < latest.created_at:
        return True
    # Otherwise don't spam — wait cooldown (and full interval for the next cycle).
    return invited <= now - max(INVITE_COOLDOWN, CHECK_IN_INTERVAL)


def _partner_ready(membership: Membership) -> bool:
    return bool(membership.spti_completed_at) or membership.interview_completed


def readiness(db: Session, dynamic: Dynamic, user: User) -> tuple[bool, str]:
    memberships = get_memberships(db, dynamic.id)
    if len(memberships) < 2:
        return False, "Both partners must join the dynamic first."
    if not all(_partner_ready(m) for m in memberships):
        return False, "Both partners need SPTI results or a completed dynamic interview first."
    if not is_llm_configured(user, dynamic):
        return False, "Configure an AI API key for this dynamic first."
    return True, ""


def _format_interviews(memberships: list[Membership]) -> str:
    blocks: list[str] = []
    for m in memberships:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        name = m.display_name or "Partner"
        summary = (m.interview_summary or "").strip()
        if summary:
            blocks.append(f"### {name} ({role}) — interview summary\n{summary}")
        else:
            blocks.append(f"### {name} ({role}) — interview summary\n(not completed)")
    return "\n\n".join(blocks) if blocks else "(no interviews)"


def _format_agreements(db: Session, dynamic_id: str) -> str:
    rows = (
        db.query(Agreement)
        .filter(Agreement.dynamic_id == dynamic_id)
        .order_by(Agreement.position.asc())
        .all()
    )
    lines: list[str] = []
    for a in rows:
        body = (a.approved_content or "").strip()
        if not body:
            continue
        title = (a.title or "Agreement").strip()
        lines.append(f"- {title}: {body}")
    return "\n".join(lines) if lines else "(no approved ground rules yet)"


def _format_tracking(db: Session, dynamic: Dynamic, memberships: list[Membership]) -> str:
    dash = build_history_dashboard(db, dynamic.id, memberships, days=WINDOW_DAYS)
    lines = [
        f"Period: last {dash['days']} days.",
        f"Comparison: {dash.get('comparison_label') or 'n/a'}",
        "",
        "Partner totals:",
    ]
    for p in dash.get("partners") or []:
        lock_bit = (
            f", chastity locked {p.percent_locked}% (all-time)"
            if p.chastity_enabled and p.percent_locked is not None
            else ""
        )
        lines.append(
            f"- {p.name} ({p.role}): {p.orgasm_count} orgasms, {p.play_count} play logs{lock_bit}"
        )

    lines.append("")
    lines.append("Weekly buckets (newest last):")
    names = {m.id: m.display_name for m in memberships}
    for bucket in (dash.get("weekly_buckets") or [])[-8:]:
        org_bits = ", ".join(
            f"{names.get(mid, mid[:6])}={n}" for mid, n in (bucket.orgasms_by_partner or {}).items()
        )
        lock_bits = ", ".join(
            f"{names.get(mid, mid[:6])}={pct}%"
            for mid, pct in (bucket.chastity_locked_pct_by_partner or {}).items()
        )
        lines.append(
            f"- {bucket.label}: orgasms [{org_bits or 'none'}]; locked% [{lock_bits or 'n/a'}]"
        )
    return "\n".join(lines)


def build_check_in_packet(db: Session, dynamic: Dynamic) -> str:
    memberships = get_memberships(db, dynamic.id)
    return "\n\n".join(
        [
            "## Interviews (both partners — shared for this check-in)",
            _format_interviews(memberships),
            "## Approved ground rules",
            _format_agreements(db, dynamic.id),
            f"## Orgasm & chastity logs (last {WINDOW_DAYS} days)",
            _format_tracking(db, dynamic, memberships),
        ]
    )


def generate_check_in(
    db: Session,
    *,
    dynamic: Dynamic,
    actor: Membership,
    user: User,
) -> RelationshipCheckIn:
    ready, reason = readiness(db, dynamic, user)
    if not ready:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    memberships = get_memberships(db, dynamic.id)
    packet = build_check_in_packet(db, dynamic)
    base_ctx = build_dynamic_context(
        db,
        dynamic,
        requesting_membership_id=actor.id,
        include_tracking=True,
    )
    prompt = f"""You are writing a quarterly relationship check-in for a consensual adult D/s dynamic.
Both partners will read this. Be warm, practical, and specific — not generic BDSM advice.

Use ONLY the material below (interviews, ground rules, tracking). Do not invent events.

Write markdown with these sections:
1. **Snapshot** — 2–4 sentences on how the last ~{WINDOW_DAYS} days look in the logs vs what they said they want.
2. **Alignment** — where interviews / ground rules and the logs match well.
3. **Gaps & questions** — 3–6 concrete discussion prompts (boundaries, pacing, chastity/orgasm balance, rituals). Phrase as questions for both of them.
4. **Suggestions** — up to 5 optional, reversible experiments (tasks, check-ins, rule tweaks). Label each as optional.

Keep the whole report under ~700 words. No preamble.

CHECK-IN MATERIAL:
{packet}
"""
    report = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=base_ctx,
        dynamic=dynamic,
        tool_id="check_in",
        db=db,
    ).strip()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned an empty check-in. Try again.",
        )

    now = datetime.utcnow()
    period_start = now - timedelta(days=WINDOW_DAYS)
    row = RelationshipCheckIn(
        dynamic_id=dynamic.id,
        created_by_membership_id=actor.id,
        report_text=report,
        period_start=period_start,
        period_end=now,
        window_days=WINDOW_DAYS,
    )
    db.add(row)
    db.flush()

    path = f"/dynamic/{dynamic.id}/check-in/{row.id}"
    post_activity_event(
        db,
        dynamic_id=dynamic.id,
        actor=actor,
        action="relationship_check_in",
        text="Relationship check-in is ready for both of you.",
        path=path,
        link_label="Open check-in",
        from_label="Check-in",
        extra={"check_in_id": row.id},
        force=True,
    )
    user_ids = {m.user_id for m in memberships if m.user_id}
    _notify_users_payload(
        db,
        user_ids=user_ids,
        title="Relationship check-in",
        body="Your shared check-in report is ready.",
        url=f"/#{path}",
        tag=f"ubetra-checkin-{dynamic.id}"[:32],
        dynamic_id=dynamic.id,
        kind="chat",
    )
    return row


def post_check_in_invite(
    db: Session,
    dynamic: Dynamic,
    *,
    actor: Membership | None = None,
    force: bool = False,
) -> bool:
    """Post a Chat link inviting both partners. Returns True if a message was posted."""
    now = datetime.utcnow()
    if not force and not should_post_invite(db, dynamic, now=now):
        return False
    memberships = get_memberships(db, dynamic.id)
    if not memberships:
        return False
    actor = actor or next(
        (m for m in memberships if (m.role.value if hasattr(m.role, "value") else m.role) == "dominant"),
        memberships[0],
    )
    path = f"/dynamic/{dynamic.id}/check-in"
    post_activity_event(
        db,
        dynamic_id=dynamic.id,
        actor=actor,
        action="relationship_check_in_invite",
        text=(
            "Time for a relationship check-in — review interviews, ground rules, "
            "and orgasm & chastity logs together."
        ),
        path=path,
        link_label="Open check-in",
        from_label="Check-in",
        force=True,
    )
    dynamic.check_in_invite_posted_at = now
    user_ids = {m.user_id for m in memberships if m.user_id}
    _notify_users_payload(
        db,
        user_ids=user_ids,
        title="Relationship check-in",
        body="A check-in link was posted in Chat.",
        url=f"/#{path}",
        tag=f"ubetra-checkin-invite-{dynamic.id}"[:32],
        dynamic_id=dynamic.id,
        kind="chat",
    )
    return True


def maybe_post_invite_for_dynamic(db: Session, dynamic_id: str) -> bool:
    dynamic = db.get(Dynamic, dynamic_id)
    if dynamic is None:
        return False
    posted = post_check_in_invite(db, dynamic)
    if posted:
        db.commit()
    return posted


def scan_check_in_invites(db: Session) -> int:
    posted = 0
    for dynamic in db.query(Dynamic).all():
        try:
            if post_check_in_invite(db, dynamic):
                posted += 1
        except Exception:
            logger.exception("check-in invite failed for %s", dynamic.id)
    if posted:
        db.commit()
    return posted


def start_check_in_loop() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def _loop() -> None:
        # First pass after a short delay so migrations finish.
        if _stop.wait(45):
            return
        while True:
            from ..database import SessionLocal

            db = SessionLocal()
            try:
                scan_check_in_invites(db)
            except Exception:
                logger.exception("check-in invite scan failed")
            finally:
                db.close()
            if _stop.wait(6 * 60 * 60):  # every 6 hours
                return

    _thread = threading.Thread(target=_loop, name="ubetra-check-in", daemon=True)
    _thread.start()


def stop_check_in_loop() -> None:
    _stop.set()
