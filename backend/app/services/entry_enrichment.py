from __future__ import annotations

from ..models import ChastityLockup, Membership, OrgTrackingEntry
from ..routers.org_tracking import _entry_out
from .lockup_at_time import lockup_context_for_entry
from .session_groups import group_tracking_sessions
from .tracking_events import is_orgasm_event, orgasm_count


def enrich_tracking_entries(
    entries: list[OrgTrackingEntry],
    memberships: dict[str, Membership],
    lockups: list[ChastityLockup],
) -> tuple[list[dict], dict[str, str], dict[str, dict]]:
    entry_to_session, sessions_meta = group_tracking_sessions(entries)
    session_sizes = {s["session_id"]: s["entry_count"] for s in sessions_meta}
    contexts: dict[str, dict] = {}
    for entry in entries:
        contexts[entry.id] = lockup_context_for_entry(entry, lockups, memberships)

    outs = []
    for entry in entries:
        ctx = contexts[entry.id]
        outs.append(
            _entry_out(
                entry,
                memberships,
                session_id=entry_to_session.get(entry.id),
                during_lockup=ctx["during_lockup"],
                during_own_lockup=ctx["during_own_lockup"],
                locked_partner_names=ctx["locked_partner_names"],
                session_entry_count=session_sizes.get(entry_to_session.get(entry.id), 1),
            )
        )
    return outs, entry_to_session, contexts


def build_sessions_payload(
    entries: list[OrgTrackingEntry],
    memberships: dict[str, Membership],
    lockups: list[ChastityLockup],
) -> tuple[list[dict], dict[str, str]]:
    entry_to_session, sessions_meta = group_tracking_sessions(entries)
    entry_by_id = {e.id: e for e in entries}
    contexts = {
        e.id: lockup_context_for_entry(e, lockups, memberships) for e in entries
    }

    sessions = []
    for meta in sessions_meta:
        session_entries = [entry_by_id[eid] for eid in meta["entry_ids"] if eid in entry_by_id]
        locked_names: set[str] = set()
        during_lockup = False
        orgasm_total = 0
        for entry in session_entries:
            ctx = contexts[entry.id]
            if ctx["during_lockup"]:
                during_lockup = True
                locked_names.update(ctx["locked_partner_names"])
            if is_orgasm_event(entry.event_type):
                orgasm_total += orgasm_count(entry)
        sessions.append(
            {
                **meta,
                "during_lockup": during_lockup,
                "locked_partner_names": sorted(locked_names),
                "orgasm_count": orgasm_total,
            }
        )
    return sessions, entry_to_session
