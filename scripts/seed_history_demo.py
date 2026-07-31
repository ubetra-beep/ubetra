"""Seed ~3 months of demo history for a domme/sub dynamic.

Default pair: xseptional (dominant) + justjim (submissive).
Re-runnable: deletes prior demo-seed tagged rows for that dynamic first.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\seed_history_demo.py
  .\\.venv\\Scripts\\python.exe scripts\\seed_history_demo.py --dom xseptional --sub justjim
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import SessionLocal
from backend.app.models import (
    ChastityBreak,
    ChastityBreakType,
    ChastityEndedKind,
    ChastityLockup,
    ChastityRecordType,
    Dynamic,
    LockupStatus,
    Membership,
    OrgEventType,
    OrgTrackingEntry,
    OrgTrackingOrgasm,
    PartnerRole,
    Task,
    TaskApprovalStatus,
    TaskList,
    TaskRecurrence,
    TaskSource,
    TaskVisibility,
    User,
)
from backend.app.services.org_tracking_prefs import FIELD_DEFS, METRIC_DEFS, serialize_org_tracking_prefs

SEED_TAG = "demo-seed"
DEMO_NOTE = "[demo-seed] synthetic history for charts"


def _pick_dynamic(db, dom_name: str, sub_name: str) -> tuple[Dynamic, Membership, Membership]:
    dom_user = db.query(User).filter(User.username == dom_name).first()
    sub_user = db.query(User).filter(User.username == sub_name).first()
    if not dom_user or not sub_user:
        raise SystemExit(f"Users not found: dom={dom_name!r} sub={sub_name!r}")

    dom_memberships = db.query(Membership).filter(Membership.user_id == dom_user.id).all()
    for dm in dom_memberships:
        sm = (
            db.query(Membership)
            .filter(
                Membership.dynamic_id == dm.dynamic_id,
                Membership.user_id == sub_user.id,
            )
            .first()
        )
        if not sm:
            continue
        dynamic = db.get(Dynamic, dm.dynamic_id)
        # Prefer roles as labeled; swap if accounts flipped roles.
        if dm.role == PartnerRole.dominant and sm.role == PartnerRole.submissive:
            return dynamic, dm, sm
        if dm.role == PartnerRole.submissive and sm.role == PartnerRole.dominant:
            return dynamic, sm, dm
        return dynamic, dm, sm

    raise SystemExit(f"No shared dynamic between {dom_name} and {sub_name}")


def _clear_demo(db, dynamic_id: str) -> None:
    entries = (
        db.query(OrgTrackingEntry)
        .filter(
            OrgTrackingEntry.dynamic_id == dynamic_id,
            OrgTrackingEntry.notes.contains(SEED_TAG),
        )
        .all()
    )
    for entry in entries:
        db.delete(entry)

    lockups = (
        db.query(ChastityLockup)
        .filter(
            ChastityLockup.dynamic_id == dynamic_id,
            ChastityLockup.device_notes.contains(SEED_TAG),
        )
        .all()
    )
    for lockup in lockups:
        db.delete(lockup)

    lists = db.query(TaskList).filter(TaskList.dynamic_id == dynamic_id).all()
    for task_list in lists:
        for task in list(task_list.tasks or []):
            if SEED_TAG in (task.content or "") or SEED_TAG in (task.tags or ""):
                db.delete(task)
    db.flush()


def _enable_all_prefs(dynamic: Dynamic) -> None:
    prefs = {
        "fields": {k: True for k in FIELD_DEFS},
        "metrics": {k: True for k in METRIC_DEFS},
    }
    dynamic.org_tracking_prefs = serialize_org_tracking_prefs(prefs)


def _at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _add_orgasm(
    db,
    *,
    dynamic_id: str,
    logger: Membership,
    for_member: Membership,
    when: datetime,
    tags: list[str],
    duration: int,
    satisfaction: int,
    edging: int,
    location: str,
    play: bool = False,
) -> None:
    entry = OrgTrackingEntry(
        dynamic_id=dynamic_id,
        logged_by_membership_id=logger.id,
        for_membership_id=for_member.id,
        event_type=OrgEventType.no_orgasm if play else OrgEventType.orgasm,
        notes=DEMO_NOTE,
        tags=",".join([SEED_TAG, *tags]),
        duration_minutes=duration,
        location=location,
        initiated_by_membership_id=logger.id,
        protection=random.choice(["protected", "unprotected", "n_a"]),
        satisfaction=satisfaction,
        edging_count=edging,
        occurred_at=when,
        ended_at=when + timedelta(minutes=duration),
    )
    db.add(entry)
    db.flush()
    if not play:
        for idx, tag in enumerate(tags):
            db.add(
                OrgTrackingOrgasm(
                    entry_id=entry.id,
                    tags=tag,
                    position=idx,
                )
            )


def seed(dom_name: str, sub_name: str, days: int = 90) -> None:
    random.seed(42)
    db = SessionLocal()
    try:
        dynamic, dom, sub = _pick_dynamic(db, dom_name, sub_name)
        print(f"Seeding dynamic {dynamic.name!r} ({dynamic.id[:8]}…) for {dom.display_name}/{sub.display_name}")
        _clear_demo(db, dynamic.id)
        sub.chastity_enabled = True
        _enable_all_prefs(dynamic)

        now = datetime.utcnow().replace(microsecond=0)
        start = (now - timedelta(days=days)).replace(hour=8, minute=0, second=0, microsecond=0)

        # Long overlapping lockup periods with hygiene / ruin / denial breaks.
        cursor = start
        lockup_count = 0
        while cursor < now - timedelta(days=2):
            length_days = random.randint(4, 12)
            ended = min(cursor + timedelta(days=length_days), now - timedelta(hours=6))
            lockup = ChastityLockup(
                dynamic_id=dynamic.id,
                for_membership_id=sub.id,
                started_by_membership_id=dom.id,
                ended_by_membership_id=dom.id,
                started_at=cursor,
                ended_at=ended,
                device_notes=f"{SEED_TAG} cage session {lockup_count + 1}",
                release_notes=DEMO_NOTE,
                tags=SEED_TAG,
                ended_kind=random.choice(
                    [
                        ChastityEndedKind.unlocked.value,
                        ChastityEndedKind.released_orgasm.value,
                        ChastityEndedKind.released_timer.value,
                    ]
                ),
                record_type=ChastityRecordType.normal,
                status=LockupStatus.ended,
            )
            db.add(lockup)
            db.flush()
            lockup_count += 1

            # A couple of short hygiene breaks
            for _ in range(random.randint(1, 3)):
                b_start = cursor + timedelta(days=random.uniform(0.5, max(1.0, length_days - 1)))
                if b_start >= ended:
                    continue
                b_end = b_start + timedelta(minutes=random.randint(8, 18))
                db.add(
                    ChastityBreak(
                        lockup_id=lockup.id,
                        break_type=ChastityBreakType.authorized_hygiene,
                        break_reason="hygiene",
                        started_at=b_start,
                        ended_at=min(b_end, ended),
                        note=DEMO_NOTE,
                        tags=SEED_TAG,
                        created_by_membership_id=dom.id,
                    )
                )

            # Occasional ruin / denial break
            if random.random() < 0.55:
                b_start = cursor + timedelta(days=random.uniform(1.0, max(1.5, length_days - 0.5)))
                if b_start < ended:
                    kind = random.choice(
                        [ChastityBreakType.authorized_ruin, ChastityBreakType.authorized_denial]
                    )
                    b_end = b_start + timedelta(minutes=random.randint(5, 25))
                    db.add(
                        ChastityBreak(
                            lockup_id=lockup.id,
                            break_type=kind,
                            break_reason="ruin" if "ruin" in kind.value else "denial",
                            started_at=b_start,
                            ended_at=min(b_end, ended),
                            note=DEMO_NOTE,
                            tags=SEED_TAG,
                            created_by_membership_id=dom.id,
                        )
                    )

            free_gap = timedelta(days=random.randint(1, 4))
            cursor = ended + free_gap

        # Active lockup for the last stretch
        active_start = now - timedelta(days=random.randint(3, 8))
        db.add(
            ChastityLockup(
                dynamic_id=dynamic.id,
                for_membership_id=sub.id,
                started_by_membership_id=dom.id,
                started_at=active_start,
                ended_at=None,
                device_notes=f"{SEED_TAG} active cage",
                tags=SEED_TAG,
                record_type=ChastityRecordType.normal,
                status=LockupStatus.active,
            )
        )

        locations = ["bedroom", "living room", "hotel", "shower", "couch"]
        orgasm_count = 0
        play_count = 0

        day = start
        while day.date() <= now.date():
            weekday = day.weekday()
            # Domme orgasms: more frequent weekends
            dom_chance = 0.55 if weekday >= 5 else 0.28
            if random.random() < dom_chance:
                when = _at(day, random.randint(9, 22), random.randint(0, 59))
                if when <= now:
                    full = random.random() < 0.85
                    _add_orgasm(
                        db,
                        dynamic_id=dynamic.id,
                        logger=dom,
                        for_member=dom,
                        when=when,
                        tags=["full orgasm" if full else "ruined orgasm"],
                        duration=random.randint(12, 55),
                        satisfaction=random.randint(3, 5),
                        edging=random.randint(0, 4),
                        location=random.choice(locations),
                    )
                    orgasm_count += 1

            # Sub: fewer full O, more ruins / play while locked
            sub_roll = random.random()
            if sub_roll < 0.12:
                when = _at(day, random.randint(10, 23), random.randint(0, 59))
                if when <= now:
                    _add_orgasm(
                        db,
                        dynamic_id=dynamic.id,
                        logger=dom,
                        for_member=sub,
                        when=when,
                        tags=["full orgasm"],
                        duration=random.randint(15, 70),
                        satisfaction=random.randint(4, 5),
                        edging=random.randint(2, 8),
                        location=random.choice(locations),
                    )
                    orgasm_count += 1
            elif sub_roll < 0.32:
                when = _at(day, random.randint(10, 23), random.randint(0, 59))
                if when <= now:
                    _add_orgasm(
                        db,
                        dynamic_id=dynamic.id,
                        logger=dom,
                        for_member=sub,
                        when=when,
                        tags=["ruined orgasm"],
                        duration=random.randint(8, 35),
                        satisfaction=random.randint(2, 4),
                        edging=random.randint(3, 10),
                        location=random.choice(locations),
                    )
                    orgasm_count += 1
            elif sub_roll < 0.48:
                when = _at(day, random.randint(18, 22), random.randint(0, 59))
                if when <= now:
                    _add_orgasm(
                        db,
                        dynamic_id=dynamic.id,
                        logger=sub,
                        for_member=sub,
                        when=when,
                        tags=["tease"],
                        duration=random.randint(10, 40),
                        satisfaction=random.randint(2, 4),
                        edging=random.randint(1, 6),
                        location=random.choice(locations),
                        play=True,
                    )
                    play_count += 1

            # Occasional shared evening (both climax)
            if weekday >= 5 and random.random() < 0.35:
                when = _at(day, 21, random.randint(0, 40))
                if when <= now:
                    for member, tag in ((dom, "full orgasm"), (sub, random.choice(["full orgasm", "ruined orgasm"]))):
                        _add_orgasm(
                            db,
                            dynamic_id=dynamic.id,
                            logger=dom,
                            for_member=member,
                            when=when + timedelta(minutes=random.randint(0, 20)),
                            tags=[tag],
                            duration=random.randint(20, 60),
                            satisfaction=random.randint(3, 5),
                            edging=random.randint(0, 5),
                            location="bedroom",
                        )
                        orgasm_count += 1

            day += timedelta(days=1)

        # Tasks that count toward goals
        task_list = (
            db.query(TaskList)
            .filter(TaskList.dynamic_id == dynamic.id)
            .order_by(TaskList.created_at.asc())
            .first()
        )
        if task_list is None:
            task_list = TaskList(
                dynamic_id=dynamic.id,
                title="Demo tasks",
                created_by_membership_id=dom.id,
            )
            db.add(task_list)
            db.flush()

        task_titles = [
            "Kneel greeting",
            "Evening check-in",
            "Edge x10 no finish",
            "Write thank-you note",
            "Wear plug during chores",
            "Photo proof of cage",
            "Journal about denial",
            "Prepare Domme tea",
        ]
        for i in range(24):
            due = start + timedelta(days=random.randint(0, days - 1), hours=random.randint(8, 20))
            completed = due + timedelta(hours=random.randint(1, 12)) if random.random() < 0.7 else None
            if completed and completed > now:
                completed = now - timedelta(hours=1)
            db.add(
                Task(
                    task_list_id=task_list.id,
                    position=i,
                    content=f"{random.choice(task_titles)} ({SEED_TAG})",
                    visibility=TaskVisibility.visible,
                    completed_at=completed,
                    created_by_membership_id=dom.id,
                    tags=SEED_TAG,
                    approval_status=TaskApprovalStatus.approved,
                    source=TaskSource.dom,
                    recurrence=TaskRecurrence.none,
                    due_at=due,
                    assigned_to_membership_id=sub.id,
                )
            )

        db.commit()
        print(
            f"Done: {lockup_count} ended lockups + 1 active, "
            f"~{orgasm_count} orgasm entries, ~{play_count} play sessions, 24 tasks. "
            f"All prefs/metrics enabled."
        )
        print("Hard-refresh History -> Weekly / Orgasm report / Chastity stats to see charts.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed 3 months of history demo data")
    parser.add_argument("--dom", default="xseptional", help="Dominant username")
    parser.add_argument("--sub", default="justjim", help="Submissive username")
    parser.add_argument("--days", type=int, default=90, help="How many days back to seed")
    args = parser.parse_args()
    seed(args.dom, args.sub, days=args.days)


if __name__ == "__main__":
    main()
