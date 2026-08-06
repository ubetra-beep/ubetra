"""Seed rich WikiDom / WikiSub demo data for wiki screenshots.

Assumes the API is running (default http://127.0.0.1:8000). Creates accounts
and dynamic if missing, then fills chat, interview, tracking, chastity,
feelings, tasks, punishment, journals, and agreements.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\seed_wiki_demo.py
  .\\.venv\\Scripts\\python.exe scripts\\seed_wiki_demo.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOM = {
    "email": "wiki-dom@example.com",
    "username": "WikiDom",
    "password": "WikiDemoPass123!",
}
SUB = {
    "email": "wiki-sub@example.com",
    "username": "WikiSub",
    "password": "WikiDemoPass123!",
}

META_PATH = ROOT / "wiki" / "capture-meta.json"


def api(base: str, method: str, path: str, token: str | None = None, ok=(200, 201, 204), **kwargs):
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if "json" in kwargs:
        headers.setdefault("Content-Type", "application/json")
    url = f"{base.rstrip('/')}/api{path}"
    r = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
    if not r.content or r.status_code == 204:
        return None
    try:
        return r.json()
    except Exception:
        return r.text


def wait_health(base: str, seconds: int = 60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if requests.get(f"{base.rstrip('/')}/api/health", timeout=2).ok:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit(f"API not healthy at {base}")


def register_or_login(base: str, user: dict) -> str:
    try:
        data = api(base, "POST", "/auth/register", json=user, ok=(200, 201))
        return data["access_token"]
    except RuntimeError as exc:
        if "already" not in str(exc).lower() and "409" not in str(exc) and "400" not in str(exc):
            # try login anyway
            pass
    data = api(base, "POST", "/auth/login", json={"email": user["email"], "password": user["password"]})
    return data["access_token"]


def finish_onboarding(base: str, token: str):
    steps = [
        ("POST", "/onboarding/skip-api", {}),
        ("PUT", "/onboarding/spti", {"skipped": True}),
        ("POST", "/onboarding/skip-survey", {}),
        ("POST", "/onboarding/complete", {}),
    ]
    for method, path, body in steps:
        try:
            api(base, method, path, token=token, json=body)
        except Exception as e:
            print("onboarding step warn", path, e)


def ensure_dynamic(base: str, dom_token: str, sub_token: str) -> tuple[str, str, dict, dict]:
    dynamics = api(base, "GET", "/dynamics", token=dom_token) or []
    if not dynamics:
        created = api(
            base,
            "POST",
            "/dynamics",
            token=dom_token,
            json={"name": "Wiki Demo Dynamic", "role": "dominant"},
        )
        dynamic_id = created["id"]
        invite = created.get("invite_code") or api(base, "GET", f"/dynamics/{dynamic_id}", token=dom_token).get(
            "invite_code"
        )
        api(
            base,
            "POST",
            "/dynamics/join",
            token=sub_token,
            json={"invite_code": invite, "role": "submissive"},
        )
    else:
        dynamic_id = dynamics[0]["id"]

    detail = api(base, "GET", f"/dynamics/{dynamic_id}", token=dom_token)
    invite = detail.get("invite_code") or dynamics[0].get("invite_code")
    partners = detail.get("partners") or []
    if len(partners) < 2:
        # Sub not joined yet
        invite = invite or detail.get("invite_code")
        api(
            base,
            "POST",
            "/dynamics/join",
            token=sub_token,
            json={"invite_code": invite, "role": "submissive"},
        )
        detail = api(base, "GET", f"/dynamics/{dynamic_id}", token=dom_token)
        partners = detail.get("partners") or []
        invite = detail.get("invite_code") or invite

    by_name = {p.get("display_name"): p for p in partners}
    by_role = {p.get("role"): p for p in partners}
    dom_m = by_name.get("WikiDom") or by_role.get("dominant") or partners[0]
    sub_m = by_name.get("WikiSub") or by_role.get("submissive") or next(p for p in partners if p["id"] != dom_m["id"])
    return dynamic_id, invite, dom_m, sub_m


def seed_interview_orm(dynamic_id: str, membership_id: str, summary: str, turns: list[tuple[str, str]]):
    """Insert interview transcript without needing an LLM."""
    from backend.app.database import SessionLocal
    from backend.app.models import InterviewMessage, InterviewRole, Membership

    db = SessionLocal()
    try:
        m = db.get(Membership, membership_id)
        if m is None:
            return
        # Clear prior demo interview messages
        for row in list(m.interview_messages or []):
            db.delete(row)
        db.flush()
        for role, content in turns:
            db.add(
                InterviewMessage(
                    membership_id=membership_id,
                    role=InterviewRole.assistant if role == "assistant" else InterviewRole.user,
                    content=content,
                )
            )
        m.interview_completed = True
        m.interview_summary = summary
        db.commit()
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    wait_health(base)

    print("auth…")
    dom_token = register_or_login(base, DOM)
    sub_token = register_or_login(base, SUB)

    print("dynamic…")
    dynamic_id, invite, dom_m, sub_m = ensure_dynamic(base, dom_token, sub_token)
    if not sub_m:
        raise SystemExit("Sub membership missing — join failed")
    finish_onboarding(base, dom_token)
    finish_onboarding(base, sub_token)
    dom_mid = dom_m["id"]
    sub_mid = sub_m["id"]
    print("dynamic", dynamic_id, "invite", invite)

    # Features
    enabled = [
        "spti",
        "context_library",
        "gear",
        "org_tracking",
        "chastity",
        "feelings",
        "punishment",
        "tasks",
        "acts",
        "image_vault",
        "scene_workshop",
        "journal",
        "sleep_tracking",
    ]
    try:
        api(base, "PUT", f"/dynamics/{dynamic_id}/features", token=dom_token, json={"enabled_optional": enabled})
    except Exception as e:
        print("features warn", e)

    # Chat settings — plaintext for screenshots
    api(
        base,
        "PUT",
        f"/dynamics/{dynamic_id}/chat/settings",
        token=dom_token,
        json={
            "e2e_enabled": False,
            "system_events": True,
            "push_enabled": True,
            "retain_history": True,
        },
    )

    # Clear prior chat by import? Skip — append conversation
    chat_lines = [
        (dom_token, "Good evening. Soft lock tonight — check in when you're ready."),
        (sub_token, "Yes, WikiDom. Cage is on. Feeling settled."),
        (dom_token, "Log feelings before we play, then open tracking when you're done."),
        (sub_token, "Logged. May I ask for a hygiene break around 10?"),
        (dom_token, "Approved for 15 minutes. Remember your evening journal."),
        (sub_token, "Thank you. Journal drafted — Use for AI is on, partner-visible off for the private bit."),
        (dom_token, "Perfect. Tasks for tomorrow are up on Playtime."),
    ]
    for token, body in chat_lines:
        try:
            api(
                base,
                "POST",
                f"/dynamics/{dynamic_id}/chat/messages",
                token=token,
                json={"message_type": "text", "body": body},
            )
        except Exception as e:
            print("chat warn", e)

    # Core knowledge both
    ck_dom = {
        "relationship_context": "Long-distance keyholder dynamic with weekly video check-ins and shared tracking.",
        "distance": "Two time zones apart; weekends together when travel allows.",
        "space": "Private home office for Dom; shared apartment for Sub.",
        "budget": "Modest toy budget; prioritize quality locks and wellness.",
        "about_you": "Patient Domme who likes structure, teasing denial, and clear aftercare.",
        "desires": "Consistent chastity arcs, orgasm logging honesty, playful punishments that stay fair.",
    }
    ck_sub = {
        "relationship_context": "Devoted Submissive learning to ask for what I need without dropping protocol.",
        "distance": "Same as Dom — we sync calendars for lock windows.",
        "space": "Bedroom desk for journaling; bathroom mirror for cage checks.",
        "budget": "Happy to save for upgrades Dom chooses.",
        "about_you": "Anxious-affectionate; responds well to checklists and praise.",
        "desires": "Locked weekends, ruined orgasms as earned treats, soft Domme voice in chat.",
    }
    for token, body in ((dom_token, ck_dom), (sub_token, ck_sub)):
        api(base, "PUT", f"/dynamics/{dynamic_id}/core-knowledge/me", token=token, json=body)
        try:
            api(base, "POST", f"/dynamics/{dynamic_id}/core-knowledge/me/submit", token=token, json={})
        except Exception as e:
            print("ck submit warn", e)

    # SPTI paste
    for token in (dom_token, sub_token):
        try:
            api(
                base,
                "PUT",
                f"/dynamics/{dynamic_id}/spti/me",
                token=token,
                json={"skipped": False, "results": "SPTI demo: Caregiver / Brat-tamer lean; high structure, medium intensity."},
            )
        except Exception as e:
            print("spti warn", e)

    # Interview transcripts (ORM)
    print("interview…")
    seed_interview_orm(
        dynamic_id,
        dom_mid,
        "WikiDom wants structured chastity arcs, honest orgasm logs, and fair playful punishments with clear aftercare.",
        [
            ("assistant", "What kind of dynamic are you building with WikiSub?"),
            ("user", "Keyholding with weekly goals, chastity as default, orgasm tracking for honesty."),
            ("assistant", "What should scenes emphasize?"),
            ("user", "Denial, teasing, and soft protocol — not extreme pain."),
            ("assistant", "Anything the AI should avoid?"),
            ("user", "No CNC or public exposure themes."),
        ],
    )
    seed_interview_orm(
        dynamic_id,
        sub_mid,
        "WikiSub thrives on checklists, praise, locked weekends, and earned ruined orgasms with soft Domme voice.",
        [
            ("assistant", "What helps you feel owned and safe?"),
            ("user", "Daily tasks, cage reminders, and knowing Dom sees my logs."),
            ("assistant", "Hard limits?"),
            ("user", "No permanent marks, no sharing photos outside the vault."),
            ("assistant", "What do you want more of?"),
            ("user", "Ruined orgasms as rewards and post-orgasm spins when Dom allows."),
        ],
    )

    # Agreements
    api(
        base,
        "POST",
        f"/dynamics/{dynamic_id}/agreements",
        token=dom_token,
        json={
            "title": "Check-ins",
            "content": "Sub posts a feelings check-in before play and an evening journal at least 4 nights a week.",
            "approve_now": True,
        },
    )
    api(
        base,
        "POST",
        f"/dynamics/{dynamic_id}/agreements",
        token=dom_token,
        json={
            "title": "Honesty in tracking",
            "content": "All orgasms and no-orgasm play sessions are logged the same day with tags.",
            "approve_now": True,
        },
    )

    # Longer history first (charts + active lockup), then conversational demo rows
    print("history seed…")
    try:
        from scripts.seed_history_demo import main as history_main

        old = sys.argv
        sys.argv = ["seed_history_demo.py", "--dom", "WikiDom", "--sub", "WikiSub"]
        try:
            history_main()
        finally:
            sys.argv = old
    except SystemExit as e:
        print("history seed exit", e)
    except Exception as e:
        print("history seed warn", e)

    # Chastity settings + hygiene break on active lock if present
    print("chastity…")
    try:
        api(
            base,
            "PUT",
            f"/dynamics/{dynamic_id}/chastity/settings",
            token=dom_token,
            json={"membership_id": sub_mid, "chastity_enabled": True, "chastity_max_lock_hours": 168},
        )
    except Exception as e:
        print("chastity settings warn", e)

    now = datetime.utcnow()
    try:
        status = api(base, "GET", f"/dynamics/{dynamic_id}/chastity", token=dom_token)
        active = None
        if isinstance(status, list):
            active = next((x for x in status if not x.get("ended_at")), None)
        elif isinstance(status, dict):
            active = status.get("active") or status.get("active_lockup")
            if not active and isinstance(status.get("lockups"), list):
                active = next((x for x in status["lockups"] if not x.get("ended_at")), None)
        lock_id = (active or {}).get("id") if isinstance(active, dict) else None
        if lock_id:
            api(
                base,
                "POST",
                f"/dynamics/{dynamic_id}/chastity/{lock_id}/break",
                token=dom_token,
                json={
                    "break_type": "authorized_hygiene",
                    "break_reason": "Hygiene",
                    "started_at": (now - timedelta(hours=6)).isoformat(timespec="seconds"),
                    "ended_at": (now - timedelta(hours=5, minutes=45)).isoformat(timespec="seconds"),
                    "note": "15 min hygiene",
                    "tags": ["Hygiene"],
                },
            )
        else:
            api(
                base,
                "POST",
                f"/dynamics/{dynamic_id}/chastity/historical",
                token=dom_token,
                json={
                    "for_membership_id": sub_mid,
                    "started_at": (now - timedelta(days=10)).isoformat(timespec="seconds"),
                    "ended_at": (now - timedelta(days=3)).isoformat(timespec="seconds"),
                    "note": "Wiki demo prior lockup",
                    "tags": ["weekend", "travel"],
                },
            )
            api(
                base,
                "POST",
                f"/dynamics/{dynamic_id}/chastity/start",
                token=dom_token,
                json={
                    "for_membership_id": sub_mid,
                    "device_notes": "Wiki demo active cage",
                    "started_at": (now - timedelta(days=2, hours=4)).isoformat(timespec="seconds"),
                    "planned_end_at": (now + timedelta(days=5)).isoformat(timespec="seconds"),
                    "show_planned_end": True,
                    "tags": ["active"],
                },
            )
    except Exception as e:
        print("chastity activity warn", e)

    # Tracking
    print("tracking…")
    tracking_samples = [
        (sub_token, sub_mid, "orgasm", ["Vibrator", "Full Orgasm"], "Solo evening — Dom approved"),
        (dom_token, sub_mid, "orgasm", ["Handjob", "Ruined Orgasm"], "Video session ruined"),
        (sub_token, sub_mid, "no_orgasm", ["Edging"], "Denied after tease"),
        (dom_token, dom_mid, "orgasm", ["PiV", "Full Orgasm"], "Together weekend"),
    ]
    for i, (token, mid, et, tags, notes) in enumerate(tracking_samples):
        body = {
            "for_membership_id": mid,
            "event_type": et,
            "notes": notes,
            "occurred_at": (now - timedelta(days=6 - i, hours=2)).isoformat(timespec="seconds"),
            "satisfaction": 4,
        }
        if et == "orgasm":
            body["orgasms"] = [{"tags": tags}]
        else:
            body["tags"] = tags
        try:
            api(base, "POST", f"/dynamics/{dynamic_id}/tracking", token=token, json=body)
        except Exception as e:
            print("tracking warn", e)

    # Feelings
    print("feelings…")
    for token, ctx, emos, horny in (
        (sub_token, "before_play", ["happy_trusting_intimate"], 6),
        (sub_token, "after_play", ["happy_optimistic_hopeful"], 3),
        (dom_token, "ad_hoc", ["happy"], 2),
    ):
        try:
            api(
                base,
                "POST",
                f"/dynamics/{dynamic_id}/feelings",
                token=token,
                json={"context": ctx, "emotion_ids": emos, "horny_level": horny},
            )
        except Exception as e:
            print("feelings warn", e)

    # Tasks
    print("tasks…")
    try:
        api(
            base,
            "POST",
            f"/dynamics/{dynamic_id}/tasks",
            token=dom_token,
            json={
                "title": "Evening protocol",
                "assigned_to_membership_id": sub_mid,
                "tasks": [
                    {
                        "content": "Lock check selfie to vault before bed",
                        "tags": ["Health / Hygiene"],
                        "due_in_amount": 1,
                        "due_in_unit": "days",
                    },
                    {
                        "content": "Write 5 lines in journal about today's denial",
                        "tags": ["Sensual"],
                        "due_in_amount": 1,
                        "due_in_unit": "days",
                    },
                    {
                        "content": "Wipe kitchen counters after dinner",
                        "tags": ["Domestic"],
                        "recurrence": "daily",
                        "due_in_amount": 1,
                        "due_in_unit": "days",
                    },
                ],
            },
        )
    except Exception as e:
        print("tasks warn", e)

    # Punishment
    try:
        api(
            base,
            "POST",
            f"/dynamics/{dynamic_id}/punishments/self-report",
            token=sub_token,
            json={"action": "Forgot to log last night's edged session until morning."},
        )
    except Exception as e:
        print("punishment warn", e)

    # Journals
    for token, title, body, visible in (
        (
            sub_token,
            "Locked weekend reflections",
            "Cage felt heavy at first, then grounding. Grateful Dom approved a short hygiene break.",
            True,
        ),
        (
            sub_token,
            "Private worry",
            "Worried I asked for release too soon — keeping this partner-hidden while I process.",
            False,
        ),
        (
            dom_token,
            "Keyholder notes",
            "Sub's logs look honest. Next week: add a post-orgasm spin if they earn a ruined orgasm.",
            True,
        ),
    ):
        try:
            api(
                base,
                "POST",
                f"/dynamics/{dynamic_id}/journal",
                token=token,
                json={"title": title, "body": body, "use_for_ai": True, "partner_visible": visible},
            )
        except Exception as e:
            print("journal warn", e)

    meta = {
        "dynamic_id": dynamic_id,
        "invite_code": invite,
        "dom": DOM["username"],
        "sub": SUB["username"],
        "base": base,
        "dom_membership_id": dom_mid,
        "sub_membership_id": sub_mid,
        "seeded_at": datetime.utcnow().isoformat() + "Z",
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("wrote", META_PATH)
    print("done", meta)


if __name__ == "__main__":
    main()
