"""Finish onboarding and recapture hub screenshots for the wiki."""
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
META = Path(__file__).resolve().parents[1] / "wiki" / "capture-meta.json"

DOM = {"email": "wiki-dom@example.com", "password": "WikiDemoPass123!"}
SUB = {"email": "wiki-sub@example.com", "password": "WikiDemoPass123!"}


def api(method, path, token=None, **kwargs):
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, f"{API}{path}", headers=headers, timeout=60, **kwargs)
    if not r.ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else None


def shot(page, name):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print("shot", path.name)


def login(page, user):
    page.goto(f"{BASE}/#/login")
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', user["email"])
    page.fill('input[name="password"]', user["password"])
    page.click('button.primary-btn[type="submit"]')
    page.wait_for_timeout(1200)


def finish_onboarding(page):
    for _ in range(10):
        url = page.url
        # Skip / fill later buttons
        for label in ("Fill out later", "Skip for now", "Finish setup", "Go to your dynamic", "Continue"):
            btn = page.locator(f'button:has-text("{label}")')
            if btn.count():
                btn.first.click()
                page.wait_for_timeout(900)
                break
        else:
            # Done button on finish card
            done = page.locator('button.primary-btn')
            if "You're all set" in page.content() and done.count():
                done.first.click()
                page.wait_for_timeout(1000)
            break
        if "#/onboarding" not in page.url and "#/dynamic" in page.url:
            break
        if "#/onboarding" not in page.url and "Welcome to UBETRA" not in page.content():
            break


def goto_wait(page, hash_path, ready_text=None, timeout=15000):
    page.goto(f"{BASE}/#{hash_path}")
    page.wait_for_timeout(500)
    # Force hashchange if already on same path
    page.evaluate(f"() => {{ location.hash = '{hash_path}'; }}")
    if ready_text:
        page.wait_for_selector(f"text={ready_text}", timeout=timeout)
    else:
        page.wait_for_timeout(1200)


def main():
    meta = json.loads(META.read_text(encoding="utf-8"))
    dynamic_id = meta["dynamic_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 420, "height": 900},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()

        # Dom: complete onboarding via API skips + UI
        login(page, DOM)
        token = page.evaluate("() => localStorage.getItem('ubetra_token')")
        # API-complete remaining onboarding steps
        try:
            api("POST", "/onboarding/skip-api", token=token)
        except Exception:
            pass
        try:
            api("PUT", "/onboarding/spti", token=token, json={"skipped": True})
        except Exception:
            pass
        try:
            api("POST", "/onboarding/skip-survey", token=token)
        except Exception:
            pass
        try:
            api("POST", "/onboarding/complete", token=token)
        except Exception as e:
            print("complete warn", e)

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}")
        page.wait_for_timeout(1500)
        finish_onboarding(page)
        page.goto(f"{BASE}/#/dynamic/{dynamic_id}")
        page.wait_for_timeout(1500)
        shot(page, "10-dynamic-overview")

        # Turn off e2e for demo plaintext chat seed, then capture
        try:
            api(
                "PUT",
                f"/dynamics/{dynamic_id}/chat/settings",
                token=token,
                json={"e2e_enabled": False},
            )
            api(
                "POST",
                f"/dynamics/{dynamic_id}/chat/messages",
                token=token,
                json={"message_type": "text", "body": "Welcome to our wiki demo dynamic."},
            )
            api(
                "POST",
                f"/dynamics/{dynamic_id}/chat/messages",
                token=token,
                json={"message_type": "text", "body": "Encrypted chat and push work on every signed-in device."},
            )
        except Exception as e:
            print("seed chat", e)

        goto_wait(page, f"/dynamic/{dynamic_id}/track", "History")
        shot(page, "11-tracking-hub")

        goto_wait(page, f"/dynamic/{dynamic_id}/ground-rules", "Ground")
        shot(page, "12-ground-rules")

        goto_wait(page, f"/dynamic/{dynamic_id}/chastity", "Chastity")
        shot(page, "13-chastity")

        goto_wait(page, f"/dynamic/{dynamic_id}/tracking", ready_text=None)
        page.wait_for_timeout(1000)
        shot(page, "14-orgasm-tracking")

        goto_wait(page, f"/dynamic/{dynamic_id}/feelings", "Feelings")
        shot(page, "15-feelings")

        goto_wait(page, f"/dynamic/{dynamic_id}/punishment", "Punishment")
        shot(page, "16-punishment")

        goto_wait(page, f"/dynamic/{dynamic_id}/tasks", "Task")
        shot(page, "17-tasks")

        goto_wait(page, f"/dynamic/{dynamic_id}/assistant", ready_text=None)
        page.wait_for_timeout(1200)
        shot(page, "18-playtime")

        goto_wait(page, f"/chat/{dynamic_id}", "Chat")
        page.wait_for_timeout(800)
        shot(page, "19-chat")

        goto_wait(page, f"/settings?dynamic={dynamic_id}", "Settings")
        page.wait_for_timeout(1000)
        shot(page, "20-settings")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(400)
        shot(page, "21-settings-lower")

        # Survey (good reference from earlier finish attempt)
        goto_wait(page, f"/dynamic/{dynamic_id}/survey", "Kink")
        shot(page, "22-kink-list")

        goto_wait(page, f"/dynamic/{dynamic_id}/history", ready_text=None)
        page.wait_for_timeout(1000)
        shot(page, "23-history")

        goto_wait(page, f"/dynamic/{dynamic_id}/vault", ready_text=None)
        page.wait_for_timeout(800)
        shot(page, "24-vault")

        goto_wait(page, f"/dynamic/{dynamic_id}/assistant/games/spin", ready_text=None)
        page.wait_for_timeout(1200)
        shot(page, "25-spin-game")

        # Logout and Sub
        page.evaluate("() => { localStorage.removeItem('ubetra_token'); location.hash='#/login'; }")
        page.wait_for_timeout(600)
        login(page, SUB)
        sub_token = page.evaluate("() => localStorage.getItem('ubetra_token')")
        try:
            api("POST", "/onboarding/skip-api", token=sub_token)
        except Exception:
            pass
        try:
            api("PUT", "/onboarding/spti", token=sub_token, json={"skipped": True})
        except Exception:
            pass
        try:
            api("POST", "/onboarding/skip-survey", token=sub_token)
        except Exception:
            pass
        try:
            api("POST", "/onboarding/complete", token=sub_token)
        except Exception:
            pass

        page.goto(f"{BASE}/#/dynamic/{dynamic_id}")
        page.wait_for_timeout(1500)
        finish_onboarding(page)
        page.goto(f"{BASE}/#/dynamic/{dynamic_id}")
        page.wait_for_timeout(1200)
        shot(page, "32-sub-dynamic-overview")

        goto_wait(page, f"/chat/{dynamic_id}", "Chat")
        shot(page, "33-sub-chat")

        goto_wait(page, f"/settings?dynamic={dynamic_id}", "Settings")
        shot(page, "34-sub-settings")

        goto_wait(page, f"/dynamic/{dynamic_id}/track", "History")
        shot(page, "35-sub-tracking")

        goto_wait(page, f"/dynamic/{dynamic_id}/punishment", "Punishment")
        shot(page, "36-sub-punishment")

        print("recapture done")
        browser.close()


if __name__ == "__main__":
    main()
