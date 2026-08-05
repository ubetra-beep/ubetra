from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Dynamic, InterviewMessage, InterviewRole, Membership, PartnerRole, User
from .context import build_dynamic_context
from .act_catalog import maybe_generate_act_catalog
from .core_knowledge_from_interview import maybe_auto_fill_core_knowledge_from_interview
from .llm import generate_text

INTERVIEW_COMPLETE = "INTERVIEW_COMPLETE"
SUMMARY_PREFIX = "SUMMARY:"
MAX_QUESTIONS = 8
MIN_TURNS_FOR_MANUAL_COMPLETE = 2

# LLM often writes "INTERVIEW COMPLETE" or "Interview Complete Summary" instead of the token.
_COMPLETE_MARKER_RE = re.compile(
    r"\bINTERVIEW[_\s-]*COMPLETE\b",
    re.IGNORECASE,
)
_SUMMARY_LINE_RE = re.compile(
    r"^\s*(?:#{1,3}\s*)?(?:\*{0,2})?SUMMARY(?:\s+COMPLETE)?(?:\*{0,2})?\s*[:\-–—]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_SUMMARY_BLOCK_RE = re.compile(
    r"(?:INTERVIEW[_\s-]*COMPLETE\s*)?(?:SUMMARY(?:\s+COMPLETE)?)\s*[:\-–—]?\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
_USER_DONE_RE = re.compile(
    r"\b("
    r"mark(?:\s+(?:the\s+|this\s+|my\s+)?)?interview\s+as\s+complete"
    r"|interview\s+is\s+(?:done|complete|finished)"
    r"|i(?:'m|\s+am)\s+done"
    r"|that(?:'s|\s+is)\s+all\b"
    r"|nothing\s+more\s+to\s+add"
    r"|we(?:'re|\s+are)\s+done"
    r"|finish(?:\s+the)?\s+interview"
    r"|end\s+(?:the\s+)?interview"
    r")\b",
    re.IGNORECASE,
)

INTERVIEW_SYSTEM = """You are conducting a private interview to learn what ONE partner wants from their consensual BDSM dynamic.

Goals:
- Understand their goals, boundaries, rituals, frequency, and emotional needs for THIS dynamic
- Learn what kinds of tasks, scenes, and acts would feel meaningful vs unwanted
- Ask what tasks and acts each partner is willing to perform — include practical domestic-service examples where helpful (e.g. tidying, laundry, meal prep, errands, morning/evening routines, rituals of service) and ask what feels good vs off-limits
- Stay within consensual adult activity; do not push beyond stated comfort

Rules:
- Ask ONE clear question at a time (2-4 sentences max)
- Reference what you already know from context when helpful
- Do not assign specific tasks yet — only gather willingness, limits, and preferences for acts of submission and service
- When you have enough detail (usually after 4–8 exchanges covering goals, boundaries, tone, and what they want day-to-day), you MUST end your message with exactly these two lines (no other formatting):
  INTERVIEW_COMPLETE
  SUMMARY: <2-4 paragraph summary of what they want, limits, and tone for this dynamic>

If the user says they are done, or asks you to mark the interview complete, immediately end with INTERVIEW_COMPLETE and SUMMARY — do not ask another question.
If they add more detail after a prior summary, acknowledge briefly and end again with INTERVIEW_COMPLETE and an updated SUMMARY that incorporates the new information."""


def _message_to_role(role: InterviewRole) -> str:
    return role.value


def get_interview_messages(db: Session, membership_id: str) -> list[InterviewMessage]:
    return (
        db.query(InterviewMessage)
        .filter(InterviewMessage.membership_id == membership_id)
        .order_by(InterviewMessage.created_at)
        .all()
    )


def _conversation_lines(messages: list[InterviewMessage]) -> str:
    lines = []
    for msg in messages:
        speaker = "Assistant" if msg.role == InterviewRole.assistant else "User"
        lines.append(f"{speaker}: {msg.content}")
    return "\n".join(lines)


def _user_wants_to_finish(message: str) -> bool:
    return bool(_USER_DONE_RE.search(message or ""))


def _parse_completion(raw: str) -> tuple[str, str | None]:
    """Return (visible_reply, summary_or_none). Tolerant of LLM formatting drift."""
    text = (raw or "").strip()
    if not text:
        return "", None

    # Exact token, spaced form, or "INTERVIEW COMPLETE SUMMARY" heading
    marker = re.search(
        r"\bINTERVIEW[_\s-]*COMPLETE(?:\s+SUMMARY)?\b\s*[:\-–—]?\s*",
        text,
        re.IGNORECASE,
    )
    summary_line = _SUMMARY_LINE_RE.search(text)

    if not marker and not summary_line:
        return text, None

    if marker:
        visible = text[: marker.start()].strip()
        after = text[marker.end() :].strip()
    else:
        visible = text[: summary_line.start()].strip()
        after = text[summary_line.start() :].strip()

    summary = None
    line_in_after = _SUMMARY_LINE_RE.search(after)
    if line_in_after:
        summary = after[line_in_after.start(1) :].strip()
    elif summary_line and not marker:
        summary = text[summary_line.start(1) :].strip()
    else:
        block = _SUMMARY_BLOCK_RE.search(after)
        if block:
            summary = block.group(1).strip()
        elif after:
            cleaned = re.sub(
                r"^(?:SUMMARY(?:\s+COMPLETE)?)\s*[:\-–—]?\s*",
                "",
                after,
                flags=re.IGNORECASE,
            )
            summary = cleaned.strip() or None

    if summary:
        summary = re.sub(r"^#+\s*", "", summary).strip()
        summary = re.sub(r"^\*{1,2}\s*|\s*\*{1,2}$", "", summary).strip()

    if not visible and summary:
        visible = "Thanks — I have enough to tailor suggestions to your dynamic."
    return visible, summary


def _assistant_turns(messages: list[InterviewMessage]) -> int:
    return sum(1 for m in messages if m.role == InterviewRole.assistant)


def _user_turns(messages: list[InterviewMessage]) -> int:
    return sum(1 for m in messages if m.role == InterviewRole.user)


def can_manually_complete(messages: list[InterviewMessage]) -> bool:
    return _user_turns(messages) >= MIN_TURNS_FOR_MANUAL_COMPLETE


def _generate_summary(
    *,
    user: User,
    dynamic: Dynamic,
    context: str,
    history: str,
    extra_note: str = "",
    db: Session | None = None,
) -> str:
    prompt = f"""Based on this interview, write only:
SUMMARY: <2-4 paragraphs capturing what this partner wants, boundaries, and tone>

Interview:
{history}
{extra_note}"""
    summary_raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=context,
        system_instruction=INTERVIEW_SYSTEM,
        dynamic=dynamic,
        tool_id="interview",
        db=db,
    )
    _, summary = _parse_completion(f"{INTERVIEW_COMPLETE}\n{summary_raw}")
    if summary:
        return summary
    # Last resort: use the model output as the summary body
    cleaned = summary_raw.strip()
    if cleaned.upper().startswith(SUMMARY_PREFIX):
        cleaned = cleaned.split(":", 1)[1].strip()
    return cleaned or "Interview notes captured; partner can add more detail anytime."


def _mark_completed(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
    summary: str,
) -> None:
    membership.interview_summary = summary.strip()
    membership.interview_completed = True
    maybe_auto_fill_core_knowledge_from_interview(
        db, user=user, dynamic=dynamic, membership=membership
    )
    maybe_generate_act_catalog(db, user=user, dynamic=dynamic)


def start_interview(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
) -> InterviewMessage:
    existing = get_interview_messages(db, membership.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Interview already started. Reply to continue.",
        )

    role_label = "dominant" if membership.role == PartnerRole.dominant else "submissive"
    context = build_dynamic_context(db, dynamic, requesting_membership_id=membership.id)
    prompt = f"""Begin the interview with {membership.display_name} ({role_label}).
Ask your first question about what they want from this dynamic.
Do not include INTERVIEW_COMPLETE yet."""

    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=context,
        system_instruction=INTERVIEW_SYSTEM,
        dynamic=dynamic,
        tool_id="interview",
        db=db,
    )
    visible, summary = _parse_completion(raw)
    message = InterviewMessage(
        membership_id=membership.id,
        role=InterviewRole.assistant,
        content=visible or raw.strip(),
    )
    db.add(message)
    if summary:
        _mark_completed(db, user=user, dynamic=dynamic, membership=membership, summary=summary)
    db.commit()
    db.refresh(message)
    return message


def reply_to_interview(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
    user_message: str,
) -> tuple[InterviewMessage, InterviewMessage | None, bool]:
    """Accept replies whether or not the interview is already marked complete.

    Completed interviews stay open for additions; new material updates the summary.
    """
    user_msg = InterviewMessage(
        membership_id=membership.id,
        role=InterviewRole.user,
        content=user_message.strip(),
    )
    db.add(user_msg)
    db.flush()

    messages = get_interview_messages(db, membership.id)
    context = build_dynamic_context(db, dynamic, requesting_membership_id=membership.id)
    history = _conversation_lines(messages)
    already_done = bool(membership.interview_completed)
    user_done = _user_wants_to_finish(user_message)

    if already_done:
        prompt = f"""Conversation so far:
{history}

The interview was already marked complete. The user is adding or adjusting context.
Acknowledge briefly (1-2 sentences), then end with:
INTERVIEW_COMPLETE
SUMMARY: <updated 2-4 paragraph summary incorporating the new information>"""
    elif user_done:
        prompt = f"""Conversation so far:
{history}

The user wants to finish now. Do not ask another question. End with:
INTERVIEW_COMPLETE
SUMMARY: <2-4 paragraph summary of what they want, limits, and tone>"""
    else:
        prompt = f"""Conversation so far:
{history}

Respond to the user's latest message. Ask the next interview question OR, if you already have enough detail on goals, boundaries, tone, and day-to-day preferences, finish with:
INTERVIEW_COMPLETE
SUMMARY: <2-4 paragraph summary>"""

    raw = generate_text(
        user=user,
        user_prompt=prompt,
        dynamic_context=context,
        system_instruction=INTERVIEW_SYSTEM,
        dynamic=dynamic,
        tool_id="interview",
        db=db,
    )
    visible, summary = _parse_completion(raw)
    force_complete = (
        already_done
        or user_done
        or summary is not None
        or _assistant_turns(messages) >= MAX_QUESTIONS
    )

    if force_complete and not summary:
        summary = _generate_summary(
            user=user,
            dynamic=dynamic,
            context=context,
            history=history,
            extra_note=f"Assistant draft reply:\n{visible or raw}",
            db=db,
        )

    assistant_msg = InterviewMessage(
        membership_id=membership.id,
        role=InterviewRole.assistant,
        content=visible or raw.strip(),
    )
    db.add(assistant_msg)

    if force_complete and summary:
        _mark_completed(db, user=user, dynamic=dynamic, membership=membership, summary=summary)

    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    return user_msg, assistant_msg, bool(membership.interview_completed)


def complete_interview(
    db: Session,
    *,
    user: User,
    dynamic: Dynamic,
    membership: Membership,
) -> Membership:
    """Manually mark the interview complete and generate/refresh the summary."""
    messages = get_interview_messages(db, membership.id)
    if not messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start the interview before marking it complete.",
        )
    if not can_manually_complete(messages) and not membership.interview_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Answer a couple of questions first, then you can mark it complete.",
        )

    context = build_dynamic_context(db, dynamic, requesting_membership_id=membership.id)
    history = _conversation_lines(messages)
    summary = _generate_summary(
        user=user,
        dynamic=dynamic,
        context=context,
        history=history,
        db=db,
    )
    note = InterviewMessage(
        membership_id=membership.id,
        role=InterviewRole.assistant,
        content="Interview marked complete. You can keep adding details anytime — the summary will update.",
    )
    db.add(note)
    _mark_completed(db, user=user, dynamic=dynamic, membership=membership, summary=summary)
    db.commit()
    db.refresh(membership)
    return membership
