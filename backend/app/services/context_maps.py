"""Per-screen context flow maps and indexed packs for Assistant Domme chat.

The catalog is always small. Live packs are loaded for the current route key.
Follow-up turns refresh only packs that go stale — they do not re-send interview,
agreements, journals, or the full tracking dump.
Partner Chat is never included.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Dynamic, Membership, PartnerRole, PunishmentReport

# Catalog of named packs. One-liners teach the model when each pack exists.
PACK_INDEX: dict[str, str] = {
    "identity": "Partner names and roles",
    "agreements": "Approved ground rules (first turn on Setup / agreements screens)",
    "interview": "Requester interview summary and kink highlights",
    "core_knowledge": "Requester submitted Core knowledge fields",
    "tracking_orgasm": "Orgasm counts and recent sex events",
    "tracking_chastity": "Lockup state, hours, breaks",
    "standing_targets": "Weighted standing balance targets vs this window",
    "tasks_inbox": "Open tasks and inbox titles (not partner Chat)",
    "journals": "Recent Use-for-AI journal snippets",
    "feelings": "Recent feelings-wheel check-ins",
    "punishment": "Open confessions / punishment queue",
    "playtime": "Recent Instructor sessions",
    "goals": "Gift / unlock goals",
    "features": "Optional modules on vs off",
    "utilization": "Unused or stale enabled modules",
    "context_library": "Library items tagged for AI",
    "gear": "Gear inventory titles",
    "permissions": "Assistant Apply grants",
    "changelog": "Recent changes applied from Assistant chat",
}

# route key → hub, live packs, sibling branches
AREA_MAPS: dict[str, dict] = {
    "": {
        "hub": "tracking",
        "title": "Tracking hub",
        "packs": ["identity", "features", "standing_targets", "tasks_inbox", "tracking_orgasm", "tracking_chastity"],
        "branches": ["history", "tracking", "chastity", "feelings", "sleep", "cycle", "punishment", "journal"],
    },
    "track": {
        "hub": "tracking",
        "title": "Tracking hub",
        "packs": ["identity", "features", "standing_targets", "tasks_inbox", "tracking_orgasm", "tracking_chastity"],
        "branches": ["history", "tracking", "chastity", "feelings", "sleep", "cycle", "punishment", "journal"],
    },
    "history": {
        "hub": "tracking",
        "title": "History",
        "packs": ["identity", "tracking_orgasm", "tracking_chastity", "standing_targets", "playtime"],
        "branches": ["track", "tracking", "chastity"],
    },
    "tracking": {
        "hub": "tracking",
        "title": "Sex & orgasm tracking",
        "packs": ["identity", "tracking_orgasm", "standing_targets", "goals", "feelings"],
        "branches": ["history", "chastity", "track"],
    },
    "chastity": {
        "hub": "tracking",
        "title": "Chastity tracking",
        "packs": ["identity", "tracking_chastity", "standing_targets", "goals", "punishment"],
        "branches": ["history", "tracking", "tasks"],
    },
    "feelings": {
        "hub": "tracking",
        "title": "Feelings",
        "packs": ["identity", "feelings", "journals"],
        "branches": ["track", "journal"],
    },
    "sleep": {
        "hub": "tracking",
        "title": "Sleep tracking",
        "packs": ["identity", "feelings"],
        "branches": ["track", "cycle"],
    },
    "cycle": {
        "hub": "tracking",
        "title": "Cycle tracking",
        "packs": ["identity"],
        "branches": ["track", "sleep"],
    },
    "punishment": {
        "hub": "tracking",
        "title": "Punishment / confessions",
        "packs": ["identity", "punishment", "goals", "tasks_inbox", "agreements"],
        "branches": ["track", "tasks", "journal"],
    },
    "journal": {
        "hub": "tracking",
        "title": "Journal",
        "packs": ["identity", "journals", "feelings"],
        "branches": ["track", "feelings"],
    },
    "vault": {
        "hub": "chat",
        "title": "Image vault",
        "packs": ["identity", "features"],
        "branches": [],
    },
    "tasks": {
        "hub": "playtime",
        "title": "Tasks & acts",
        "packs": ["identity", "tasks_inbox", "goals", "standing_targets", "punishment"],
        "branches": ["acts", "assistant", "punishment"],
    },
    "acts": {
        "hub": "playtime",
        "title": "Acts of submission",
        "packs": ["identity", "tasks_inbox", "interview"],
        "branches": ["tasks"],
    },
    "assistant": {
        "hub": "playtime",
        "title": "Playtime",
        "packs": ["identity", "features", "playtime", "tasks_inbox", "utilization"],
        "branches": ["assistant/scene", "assistant/games", "instructor", "manga", "tasks"],
    },
    "assistant/scene": {
        "hub": "playtime",
        "title": "Scene builder",
        "packs": ["identity", "interview", "agreements", "context_library", "gear"],
        "branches": ["assistant", "survey"],
    },
    "assistant/games": {
        "hub": "playtime",
        "title": "Playtime games",
        "packs": ["identity", "playtime"],
        "branches": ["assistant/games/spin", "assistant"],
    },
    "assistant/games/spin": {
        "hub": "playtime",
        "title": "Spin the wheel",
        "packs": ["identity", "tracking_orgasm", "tracking_chastity", "playtime"],
        "branches": ["assistant/games", "tracking", "chastity"],
    },
    "instructor": {
        "hub": "playtime",
        "title": "Instructor",
        "packs": ["identity", "playtime", "tracking_orgasm"],
        "branches": ["assistant"],
    },
    "manga": {
        "hub": "playtime",
        "title": "Monthly manga",
        "packs": ["identity", "interview", "context_library"],
        "branches": ["assistant"],
    },
    "ground-rules": {
        "hub": "setup",
        "title": "Ground rules",
        "packs": ["identity", "agreements"],
        "branches": ["interview", "knowledge"],
    },
    "interview": {
        "hub": "setup",
        "title": "Dynamic interview",
        "packs": ["identity", "interview", "core_knowledge"],
        "branches": ["knowledge", "survey", "ground-rules"],
    },
    "survey": {
        "hub": "setup",
        "title": "Kink list",
        "packs": ["identity", "interview"],
        "branches": ["overlap", "interview"],
    },
    "overlap": {
        "hub": "setup",
        "title": "Kink overlap",
        "packs": ["identity", "interview"],
        "branches": ["survey"],
    },
    "knowledge": {
        "hub": "setup",
        "title": "Core knowledge",
        "packs": ["identity", "core_knowledge", "interview"],
        "branches": ["knowledge/spti", "interview", "context"],
    },
    "knowledge/spti": {
        "hub": "setup",
        "title": "SPTI profile",
        "packs": ["identity", "interview", "core_knowledge"],
        "branches": ["knowledge"],
    },
    "context": {
        "hub": "setup",
        "title": "Context library",
        "packs": ["identity", "context_library"],
        "branches": ["knowledge", "gear"],
    },
    "gear": {
        "hub": "setup",
        "title": "Gear",
        "packs": ["identity", "gear"],
        "branches": ["context", "assistant/scene"],
    },
    "features": {
        "hub": "setup",
        "title": "Application features",
        "packs": ["identity", "features", "utilization", "permissions"],
        "branches": ["track", "assistant"],
    },
}

HUB_LABELS = {
    "tracking": "Tracking tab",
    "playtime": "Playtime tab",
    "chat": "Chat tab — partner messages never go to the assistant",
    "setup": "Setup / Dynamic (ground rules, interview, knowledge)",
}

# Packs that stay fresh and should be re-injected on follow-up turns.
LIVE_REFRESH_PACKS = {
    "identity",
    "tracking_orgasm",
    "tracking_chastity",
    "standing_targets",
    "tasks_inbox",
    "punishment",
    "goals",
    "feelings",
    "features",
    "permissions",
    "changelog",
}


def lookup_area(route_key: str) -> dict:
    key = route_key or "track"
    if key in AREA_MAPS:
        return dict(AREA_MAPS[key])
    base = key.split("/")[0] if key else "track"
    if base in AREA_MAPS:
        return dict(AREA_MAPS[base])
    return dict(AREA_MAPS["track"])


def format_catalog() -> str:
    lines = [
        "Context catalog (index only — do not assume live numbers for packs not listed under Current area):",
        "Hubs: Tracking | Playtime | Setup. Partner Chat is private and is never in context.",
    ]
    by_hub: dict[str, list[tuple[str, dict]]] = {}
    for key, meta in AREA_MAPS.items():
        if key == "":
            continue
        by_hub.setdefault(meta["hub"], []).append((key, meta))
    for hub, items in by_hub.items():
        lines.append(f"{HUB_LABELS.get(hub, hub)}:")
        for key, meta in items:
            packs = ", ".join(meta.get("packs") or [])
            lines.append(f"  - `{key}` {meta.get('title')}: packs {packs}")
    lines.append("Pack meanings:")
    for pid, blurb in PACK_INDEX.items():
        lines.append(f"  - {pid}: {blurb}")
    return "\n".join(lines)


def format_current_flow(route_key: str) -> str:
    area = lookup_area(route_key)
    key = route_key or "track"
    branches = area.get("branches") or []
    lines = [
        f"Current area key: `{key}` — {area.get('title')} (hub: {HUB_LABELS.get(area.get('hub'), area.get('hub'))}).",
        f"Live packs for this screen: {', '.join(area.get('packs') or [])}.",
    ]
    if branches:
        lines.append("Branches from here: " + ", ".join(f"`{b}`" for b in branches) + ".")
    lines.append(
        "Use only these live packs plus the catalog. If they ask about another area, "
        "use the catalog one-liner and offer open_path so they can open that screen."
    )
    return "\n".join(lines)


def _identity_pack(memberships: list[Membership], requesting_membership_id: str | None) -> list[str]:
    lines = ["Identity:"]
    for membership in memberships:
        role = "dominant" if membership.role == PartnerRole.dominant else "submissive"
        you = " (requester)" if membership.id == requesting_membership_id else ""
        lines.append(f"  - {membership.display_name} ({role}{you})")
    return lines


def _agreements_pack(db: Session, dynamic: Dynamic) -> list[str]:
    from ..models import Agreement

    rows = (
        db.query(Agreement)
        .filter(Agreement.dynamic_id == dynamic.id)
        .order_by(Agreement.position, Agreement.created_at)
        .all()
    )
    approved = [a for a in rows if (a.approved_content or "").strip()]
    if not approved:
        return ["Agreements: none approved."]
    lines = ["Approved ground rules:"]
    for agreement in approved[:12]:
        title = (agreement.title or "Agreement").strip()
        lines.append(f"  - {title}: {agreement.approved_content.strip()[:400]}")
    return lines


def _interview_pack(db: Session, memberships: list[Membership], requesting_membership_id: str | None) -> list[str]:
    from .context import _interest_labels, _overlap_labels

    lines = ["Interview / kinks:"]
    for membership in memberships:
        role = "dominant" if membership.role == PartnerRole.dominant else "submissive"
        is_you = membership.id == requesting_membership_id
        if is_you and membership.interview_completed and (membership.interview_summary or "").strip():
            lines.append(f"  {membership.display_name} ({role}) interview: {membership.interview_summary.strip()[:800]}")
        elif membership.interview_completed:
            lines.append(f"  {membership.display_name} ({role}): interview completed")
        if membership.survey_submitted:
            wants = _interest_labels(db, membership)
            if wants:
                lines.append(f"  {membership.display_name} kinks: {', '.join(wants[:18])}")
    if len(memberships) == 2:
        overlap = _overlap_labels(db, memberships[0], memberships[1])
        if overlap:
            lines.append("  Shared interests: " + ", ".join(overlap[:20]))
    return lines if len(lines) > 1 else ["Interview / kinks: none on file."]


def _core_knowledge_pack(memberships: list[Membership], requesting_membership_id: str | None) -> list[str]:
    from .context import _format_core_knowledge

    lines = ["Core knowledge:"]
    for membership in memberships:
        knowledge = membership.core_knowledge
        is_you = membership.id == requesting_membership_id
        if is_you and knowledge and knowledge.submitted:
            ck = _format_core_knowledge(knowledge)
            if ck:
                lines.append(f"  {membership.display_name}:")
                lines.extend(ck)
        elif knowledge and knowledge.submitted:
            lines.append(f"  {membership.display_name}: submitted (private)")
    return lines if len(lines) > 1 else ["Core knowledge: none submitted."]


def _orgasm_pack(db: Session, dynamic_id: str, memberships: list[Membership]) -> list[str]:
    from ..models import OrgTrackingEntry
    from .tracking import partner_orgasm_counts

    counts = partner_orgasm_counts(db, dynamic_id, memberships)
    lines = ["Sex & orgasm tracking (90 days):"]
    for membership in memberships:
        role = "dominant" if membership.role == PartnerRole.dominant else "submissive"
        lines.append(f"  {membership.display_name} ({role}): {counts.get(membership.id, 0)} orgasms")
    recent = (
        db.query(OrgTrackingEntry)
        .filter(OrgTrackingEntry.dynamic_id == dynamic_id)
        .order_by(OrgTrackingEntry.occurred_at.desc())
        .limit(5)
        .all()
    )
    if recent:
        mmap = {m.id: m for m in memberships}
        lines.append("  Recent events:")
        for entry in recent:
            partner = mmap.get(entry.for_membership_id)
            name = partner.display_name if partner else "Partner"
            when = entry.occurred_at.strftime("%Y-%m-%d") if entry.occurred_at else "?"
            lines.append(f"    {when}: {name} — {entry.event_type.value}")
    return lines


def _chastity_pack(db: Session, dynamic_id: str, memberships: list[Membership]) -> list[str]:
    from .chastity import chastity_subs, partner_state

    tracked = chastity_subs(memberships)
    if not tracked:
        return ["Chastity: no one enrolled."]
    lines = ["Chastity / lockup:"]
    for membership in tracked:
        stats = partner_state(db, dynamic_id, membership)
        state = stats.get("state") or "unlocked"
        extra = ""
        if state == "locked":
            extra = f" for {stats.get('current_duration_label')}"
        elif state == "on_break":
            extra = f" for {stats.get('break_duration_label')}"
        lines.append(
            f"  {membership.display_name}: {state}{extra}; "
            f"{stats.get('lockup_count', 0)} lockups, "
            f"{stats.get('percent_locked_all_time')}% locked, "
            f"longest {stats.get('longest_lockup_label') or 'n/a'}"
        )
    return lines


def _standing_pack(db: Session, dynamic: Dynamic) -> list[str]:
    from .standing_targets import format_standing_targets_for_context

    block = format_standing_targets_for_context(db, dynamic)
    return [block] if block else ["Standing targets: none set."]


def _inbox_pack(db: Session, dynamic: Dynamic, requesting_membership_id: str | None, memberships: list[Membership]) -> list[str]:
    from .standing_targets import build_standing_progress
    from .tasks_service import build_inbox

    requester = next((m for m in memberships if m.id == requesting_membership_id), None)
    progress = build_standing_progress(db, dynamic)
    lines = [
        f"Open assigned tasks: {progress.get('open_task_count', 0)}. "
        f"Last completed: {progress.get('last_completed_task_at') or 'none'}."
    ]
    if requester:
        inbox = build_inbox(db, dynamic.id, requester)
        items = inbox.get("items") or []
        if items:
            lines.append("Inbox titles:")
            for item in items[:10]:
                lines.append(f"  - {item.get('title')}: {(item.get('body') or '')[:120]}")
    return lines


def _journals_pack(db: Session, dynamic: Dynamic, requesting_membership_id: str | None, memberships: list[Membership]) -> list[str]:
    from ..models import JournalEntry

    journals = (
        db.query(JournalEntry)
        .filter(JournalEntry.dynamic_id == dynamic.id, JournalEntry.use_for_ai.is_(True))
        .order_by(JournalEntry.updated_at.desc())
        .limit(6)
        .all()
    )
    journals = [
        entry
        for entry in journals
        if entry.partner_visible or entry.membership_id == requesting_membership_id
    ]
    if not journals:
        return ["Journals: none tagged for AI."]
    mmap = {m.id: m for m in memberships}
    lines = ["Journals (Use for AI):"]
    for entry in journals:
        author = mmap.get(entry.membership_id)
        name = author.display_name if author else "Partner"
        lines.append(f"  [{name}] {entry.title or 'Untitled'}: {(entry.body or '')[:280]}")
    return lines


def _feelings_pack(db: Session, dynamic_id: str, memberships: list[Membership]) -> list[str]:
    from .feelings import recent_checkins

    rows = recent_checkins(db, dynamic_id, limit=6, since_hours=24 * 14)
    if not rows:
        return ["Feelings: no recent check-ins."]
    mmap = {m.id: m for m in memberships}
    lines = ["Recent feelings:"]
    for row in rows:
        partner = mmap.get(row.for_membership_id)
        name = partner.display_name if partner else "Partner"
        when = row.occurred_at.strftime("%Y-%m-%d") if row.occurred_at else "?"
        lines.append(f"  {when}: {name} ({row.context})")
    return lines


def _punishment_pack(db: Session, dynamic_id: str) -> list[str]:
    rows = (
        db.query(PunishmentReport)
        .filter(
            PunishmentReport.dynamic_id == dynamic_id,
            PunishmentReport.status.in_(("pending", "ideas", "assigned", "remind")),
        )
        .order_by(PunishmentReport.created_at.desc())
        .limit(8)
        .all()
    )
    if not rows:
        return ["Punishment queue: none open."]
    lines = ["Punishment / confessions:"]
    for row in rows:
        snippet = (row.action_text or "").strip().replace("\n", " ")[:160]
        lines.append(f"  - {row.status} id={row.id}: {snippet}")
    return lines


def _playtime_pack(db: Session, dynamic_id: str, memberships: list[Membership]) -> list[str]:
    from ..models import InstructorSession

    plays = (
        db.query(InstructorSession)
        .filter(InstructorSession.dynamic_id == dynamic_id)
        .order_by(InstructorSession.started_at.desc())
        .limit(6)
        .all()
    )
    if not plays:
        return ["Playtime: no recent Instructor sessions."]
    mmap = {m.id: m for m in memberships}
    lines = ["Recent Instructor sessions:"]
    for visit in plays:
        who = mmap.get(visit.membership_id)
        name = who.display_name if who else "Partner"
        lines.append(f"  {name}: {(visit.title or 'Instructor')[:80]}")
    return lines


def _goals_pack(db: Session, dynamic: Dynamic) -> list[str]:
    from .chastity_goals import build_goals_progress

    data = build_goals_progress(db, dynamic)
    goals = data.get("goals") or []
    if not goals:
        return ["Gift / unlock goals: none active."]
    lines = ["Gift / unlock goals:"]
    for goal in goals[:8]:
        title = goal.get("title") or goal.get("kind") or "goal"
        status = "ready to grant" if goal.get("ready") else "in progress"
        lines.append(f"  - {title}: {status}")
    return lines


def _features_pack(dynamic: Dynamic) -> list[str]:
    from .page_capabilities import feature_menu_lines

    return feature_menu_lines(dynamic)


def _utilization_pack(db: Session, dynamic: Dynamic) -> list[str]:
    from .feature_utilization import utilization_lines

    return utilization_lines(db, dynamic) or ["Utilization: no timestamps yet."]


def _library_pack(db: Session, dynamic: Dynamic) -> list[str]:
    from ..models import ContextLink

    links = (
        db.query(ContextLink)
        .filter(ContextLink.dynamic_id == dynamic.id, ContextLink.use_for_ai.is_(True))
        .order_by(ContextLink.created_at.desc())
        .limit(8)
        .all()
    )
    if not links:
        return ["Context library: none tagged for AI."]
    lines = ["Context library:"]
    for link in links:
        lines.append(f"  - {link.title}")
    return lines


def _gear_pack(db: Session, dynamic_id: str) -> list[str]:
    from ..models import GearInventoryItem

    items = (
        db.query(GearInventoryItem)
        .filter(GearInventoryItem.dynamic_id == dynamic_id)
        .order_by(GearInventoryItem.created_at.desc())
        .limit(12)
        .all()
    )
    if not items:
        return ["Gear: empty inventory."]
    lines = ["Gear inventory:"]
    for item in items:
        label = getattr(item, "name", None) or getattr(item, "title", None) or "item"
        lines.append(f"  - {label}")
    return lines


def _permissions_pack(dynamic: Dynamic) -> list[str]:
    from .assistant_permissions import public_permissions

    perms = public_permissions(dynamic)
    caps = perms.get("capabilities") or []
    if not caps:
        return ["Assistant permissions: defaults (ask)."]
    return [
        "Assistant permission grants: "
        + ", ".join(f"{c['id']}={c['level']}" for c in caps)
    ]


def _changelog_pack(db: Session, dynamic_id: str) -> list[str]:
    from ..models import AssistantChangeLog

    logs = (
        db.query(AssistantChangeLog)
        .filter(AssistantChangeLog.dynamic_id == dynamic_id)
        .order_by(AssistantChangeLog.created_at.desc())
        .limit(8)
        .all()
    )
    if not logs:
        return ["Assistant change log: empty."]
    lines = ["Recent Assistant-applied changes:"]
    for row in logs:
        lines.append(f"  - {row.action}: {row.summary}")
    return lines


_PACK_BUILDERS = {
    "identity": lambda db, dynamic, memberships, mid: _identity_pack(memberships, mid),
    "agreements": lambda db, dynamic, memberships, mid: _agreements_pack(db, dynamic),
    "interview": lambda db, dynamic, memberships, mid: _interview_pack(db, memberships, mid),
    "core_knowledge": lambda db, dynamic, memberships, mid: _core_knowledge_pack(memberships, mid),
    "tracking_orgasm": lambda db, dynamic, memberships, mid: _orgasm_pack(db, dynamic.id, memberships),
    "tracking_chastity": lambda db, dynamic, memberships, mid: _chastity_pack(db, dynamic.id, memberships),
    "standing_targets": lambda db, dynamic, memberships, mid: _standing_pack(db, dynamic),
    "tasks_inbox": lambda db, dynamic, memberships, mid: _inbox_pack(db, dynamic, mid, memberships),
    "journals": lambda db, dynamic, memberships, mid: _journals_pack(db, dynamic, mid, memberships),
    "feelings": lambda db, dynamic, memberships, mid: _feelings_pack(db, dynamic.id, memberships),
    "punishment": lambda db, dynamic, memberships, mid: _punishment_pack(db, dynamic.id),
    "playtime": lambda db, dynamic, memberships, mid: _playtime_pack(db, dynamic.id, memberships),
    "goals": lambda db, dynamic, memberships, mid: _goals_pack(db, dynamic),
    "features": lambda db, dynamic, memberships, mid: _features_pack(dynamic),
    "utilization": lambda db, dynamic, memberships, mid: _utilization_pack(db, dynamic),
    "context_library": lambda db, dynamic, memberships, mid: _library_pack(db, dynamic),
    "gear": lambda db, dynamic, memberships, mid: _gear_pack(db, dynamic.id),
    "permissions": lambda db, dynamic, memberships, mid: _permissions_pack(dynamic),
    "changelog": lambda db, dynamic, memberships, mid: _changelog_pack(db, dynamic.id),
}


def _render_pack(pack_id: str, db: Session, dynamic: Dynamic, memberships: list[Membership], mid: str | None) -> list[str]:
    builder = _PACK_BUILDERS.get(pack_id)
    if not builder:
        return []
    try:
        return list(builder(db, dynamic, memberships, mid) or [])
    except Exception:
        return [f"{pack_id}: unavailable."]


def build_assistant_context(
    db: Session,
    dynamic: Dynamic,
    *,
    requesting_membership_id: str | None,
    route_key: str = "",
    first_turn: bool = True,
    include_tracking: bool = True,
    subject_id: str = "",
) -> str:
    from .context import get_memberships
    from .features import is_feature_enabled
    from .page_capabilities import format_page_capabilities, lookup_page

    memberships = get_memberships(db, dynamic.id)
    area = lookup_area(route_key)
    wanted = list(area.get("packs") or [])
    if "identity" not in wanted:
        wanted.insert(0, "identity")
    if first_turn and "permissions" not in wanted:
        wanted.append("permissions")
    if first_turn and "changelog" not in wanted:
        wanted.append("changelog")
    if not first_turn:
        wanted = [p for p in wanted if p in LIVE_REFRESH_PACKS]
        if "identity" not in wanted:
            wanted.insert(0, "identity")

    skip_tracking = not include_tracking
    tracking_packs = {"tracking_orgasm", "tracking_chastity", "feelings", "playtime"}

    lines = [
        f"Dynamic name: {dynamic.name}",
        "Consensual adult BDSM dynamic. Partner Chat transcripts are never included.",
        "",
        format_catalog(),
        "",
        format_current_flow(route_key),
        "",
    ]
    page = lookup_page(route_key)
    feat_id = page.get("feature_id")
    feat_on = True
    if feat_id and feat_id not in {
        "history",
        "ground_rules",
        "interview",
        "kink_list",
        "core_knowledge",
    }:
        try:
            feat_on = is_feature_enabled(dynamic, feat_id)
        except Exception:
            feat_on = True
    lines.append(
        format_page_capabilities(
            route_key=route_key or "track",
            feature_enabled=feat_on,
            role="dominant",
        )
    )
    if subject_id:
        lines.append(f"Assistant subject: {subject_id}.")
    lines.append("")
    if not first_turn:
        lines.append(
            "Follow-up turn: identity and live metrics for this screen are refreshed. "
            "Interview, agreements, journals, and other heavy packs from earlier in this thread still apply. "
            "Do not request a full dump."
        )
        lines.append("")

    included: list[str] = []
    for pack_id in wanted:
        if skip_tracking and pack_id in tracking_packs:
            continue
        block = _render_pack(pack_id, db, dynamic, memberships, requesting_membership_id)
        if block:
            lines.extend(block)
            lines.append("")
            included.append(pack_id)
    lines.append("Packs included this turn: " + (", ".join(included) if included else "none") + ".")
    return "\n".join(lines).strip()
