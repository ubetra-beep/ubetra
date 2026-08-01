"""Capture UBETRA wiki screenshots via Playwright against local wiki_demo DB."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
API = f"{BASE}/api"
OUT = Path(__file__).resolve().parents[1] / "wiki" / "images"
OUT.mkdir(parents=True, exist_ok=True)

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


def api(method: str, path: str, token: str | None = None, **kwargs):
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if "json" in kwargs:
        headers.setdefault("Content-Type", "application/json")
    r = requests.request(method, f"{API}{path}", headers=headers, timeout=60, **kwargs)
    if not r.ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    if not r.text:
        return None
    return r.json()


def shot(page, name: str, full_page: bool = True):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    print("shot", path.name)
    return path


def fill_register(page, user: dict):
    page.goto(f"{BASE}/#/register")
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', user["email"])
    page.fill('input[name="username"]', user["username"])
    page.fill('input[name="password"]', user["password"])
    shot(page, f"01-register-{user['username'].lower()}")
    page.click('button.primary-btn[type="submit"]')
    page.wait_for_url(re.compile(r".*#/onboarding.*"), timeout=15000)


def login(page, user: dict):
    page.goto(f"{BASE}/#/login")
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', user["email"])
    page.fill('input[name="password"]', user["password"])
    page.click('button.primary-btn[type="submit"]')
    page.wait_for_timeout(800)


def main():
    # Health
    for _ in range(30):
        try:
            if requests.get(f"{API}/health", timeout=2).ok:
                break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("Server not healthy")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 420, "height": 900},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()

        # --- Dom register + onboarding ---
        page.goto(f"{BASE}/#/login")
        page.wait_for_selector("h1, .auth-card", timeout=15000)
        shot(page, "00-login")

        fill_register(page, DOM)
        page.wait_for_selector("text=Start or join a dynamic")
        shot(page, "02-onboarding-dynamic")

        page.select_option("#ob-create-role", "dominant")
        page.click('button.primary-btn:has-text("Create dynamic")')
        page.wait_for_selector("text=AI", timeout=15000)
        shot(page, "03-onboarding-api")

        # Skip API if button exists
        later = page.locator('button:has-text("Fill out later")')
        if later.count():
            later.first.click()
            page.wait_for_timeout(800)

        # SPTI step
        if page.locator("text=SPTI").count():
            shot(page, "04-onboarding-spti")
            skip_spti = page.locator('button:has-text("Skip for now")')
            if skip_spti.count():
                skip_spti.first.click()
                page.wait_for_timeout(800)

        # Survey / kinks
        page.wait_for_timeout(500)
        if page.locator("text=Kink survey").count() or page.locator('button:has-text("Skip")').count():
            shot(page, "05-onboarding-kinks")
            for label in ("Skip for now", "Skip survey", "Skip", "Continue"):
                btn = page.locator(f'button:has-text("{label}")')
                if btn.count():
                    btn.first.click()
                    page.wait_for_timeout(900)
                    break

        # Finish / invite
        page.wait_for_timeout(1000)
        shot(page, "06-onboarding-finish")
        for label in ("Finish setup", "Go to dynamic", "Continue", "Done"):
            fin = page.locator(f'button:has-text("{label}")')
            if fin.count():
                fin.first.click()
                page.wait_for_timeout(1200)
                break
        # click any remaining primary on finish
        if "onboarding" in page.url:
            prim = page.locator("button.primary-btn")
            if prim.count():
                prim.last.click()
                page.wait_for_timeout(1200)

        shot(page, "07-dom-home-dynamic")

        # Get invite via API using token from localStorage
        token = page.evaluate("() => localStorage.getItem('ubetra_token')")
        dynamics = api("GET", "/dynamics", token=token)
        dynamic = dynamics[0]
        dynamic_id = dynamic["id"]
        invite = dynamic.get("invite_code") or api("GET", f"/dynamics/{dynamic_id}", token=token).get("invite_code")
        print("dynamic", dynamic_id, "invite", invite)

        # Seed a bit of content as Dom
        try:
            api(
                "PUT",
                f"/dynamics/{dynamic_id}/chat/settings",
                token=token,
                json={"e2e_enabled": True, "push_enabled": True, "system_events": True},
            )
        except Exception as e:
            print("chat settings warn", e)

        # Chat message
        try:
            api(
                "POST",
                f"/dynamics/{dynamic_id}/chat/messages",
                token=token,
                json={"message_type": "text", "body": "Welcome to our wiki demo dynamic."},
            )
        except Exception as e:
            print("chat warn", e)

        # Navigate main hubs as Dom
        page.goto(f"{BASE}/#/dynamic/{dynamic_id}")
        page.wait_for_timeout(900)
        shot(page, "10-dynamic-overview")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/track")
        page.wait_for_timeout(900)
        shot(page, "11-tracking-hub")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/ground-rules")
        page.wait_for_timeout(900)
        shot(page, "12-ground-rules")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/chastity")
        page.wait_for_timeout(900)
        shot(page, "13-chastity")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/tracking")
        page.wait_for_timeout(900)
        shot(page, "14-orgasm-tracking")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/feelings")
        page.wait_for_timeout(900)
        shot(page, "15-feelings")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/punishment")
        page.wait_for_timeout(900)
        shot(page, "16-punishment")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/tasks")
        page.wait_for_timeout(900)
        shot(page, "17-tasks")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/assistant")
        page.wait_for_timeout(900)
        shot(page, "18-playtime")

        page.goto(f"{BASE}/#/chat/{dynamic_id}")
        page.wait_for_timeout(1200)
        shot(page, "19-chat")

        page.goto(f"{BASE}/#/settings?dynamic={dynamic_id}")
        page.wait_for_timeout(1500)
        shot(page, "20-settings")

        # Scroll privacy section if present
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(400)
        shot(page, "21-settings-lower")

        # Logout Dom
        logout = page.locator("#logout-btn, button:has-text('Log out'), button:has-text('Logout')")
        if logout.count():
            logout.first.click()
            page.wait_for_timeout(600)
        else:
            page.evaluate("() => { localStorage.removeItem('ubetra_token'); location.hash='#/login'; }")
            page.wait_for_timeout(600)

        # --- Sub join ---
        fill_register(page, SUB)
        page.wait_for_selector("#ob-invite-code", timeout=15000)
        shot(page, "30-sub-onboarding-join")
        page.fill("#ob-invite-code", invite)
        page.select_option("#ob-join-role", "submissive")
        page.click('button.primary-btn:has-text("Join dynamic")')
        page.wait_for_timeout(1000)
        shot(page, "31-sub-after-join")

        # Skip remaining onboarding
        for _ in range(6):
            skip = page.locator('button:has-text("Skip")')
            if skip.count():
                skip.first.click()
                page.wait_for_timeout(700)
                continue
            fin = page.locator('button:has-text("Finish"), button:has-text("Go to")')
            if fin.count():
                fin.first.click()
                page.wait_for_timeout(900)
                break
            primary = page.locator("button.primary-btn")
            if primary.count() and "onboarding" in page.url:
                # avoid infinite; break if stuck
                break
            break

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}")
        page.wait_for_timeout(900)
        shot(page, "32-sub-dynamic-overview")

        page.goto(f"{BASE}/#/chat/{dynamic_id}")
        page.wait_for_timeout(1200)
        shot(page, "33-sub-chat")

        page.goto(f"{BASE}/#/settings?dynamic={dynamic_id}")
        page.wait_for_timeout(1200)
        shot(page, "34-sub-settings")

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}/track")
        page.wait_for_timeout(900)
        shot(page, "35-sub-tracking")

        # Meta for wiki authors
        meta = {
            "dynamic_id": dynamic_id,
            "invite_code": invite,
            "dom": DOM["username"],
            "sub": SUB["username"],
            "base": BASE,
        }
        (OUT.parent / "capture-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print("done", meta)

        browser.close()


if __name__ == "__main__":
    main()
