"""Recapture wiki screenshots against a seeded WikiDom/WikiSub demo."""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
API = f"{BASE}/api"
OUT = Path(__file__).resolve().parents[1] / "wiki" / "images"
META = Path(__file__).resolve().parents[1] / "wiki" / "capture-meta.json"
OUT.mkdir(parents=True, exist_ok=True)

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


def dismiss_overlays(page):
    for sel in ("#inbox-overlay button", ".inbox-overlay button", 'button:has-text("Continue")', 'button:has-text("Got it")', 'button:has-text("Close")'):
        btn = page.locator(sel)
        if btn.count():
            try:
                btn.first.click(timeout=1500)
                page.wait_for_timeout(400)
            except Exception:
                pass
    page.evaluate(
        """() => {
          const o = document.getElementById('inbox-overlay');
          if (o) o.remove();
        }"""
    )


def login(page, user):
    page.goto(f"{BASE}/#/login")
    page.wait_for_timeout(500)
    dismiss_overlays(page)
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', user["email"])
    page.fill('input[name="password"]', user["password"])
    page.locator('button.primary-btn[type="submit"]').first.click(force=True)
    page.wait_for_timeout(1400)
    dismiss_overlays(page)


def goto_wait(page, hash_path, ready_text=None, timeout=15000):
    page.goto(f"{BASE}/#{hash_path}")
    page.wait_for_timeout(400)
    page.evaluate(f"() => {{ location.hash = '{hash_path}'; }}")
    if ready_text:
        try:
            page.wait_for_selector(f"text={ready_text}", timeout=timeout)
        except Exception:
            page.wait_for_timeout(1200)
    else:
        page.wait_for_timeout(1200)


def main():
    for _ in range(40):
        try:
            if requests.get(f"{API}/health", timeout=2).ok:
                break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("Server not healthy")

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

        # Login screen
        page.goto(f"{BASE}/#/login")
        page.wait_for_selector("h1, .auth-card", timeout=15000)
        shot(page, "00-login")

        login(page, DOM)
        token = page.evaluate("() => localStorage.getItem('ubetra_token')")

        goto_wait(page, f"/dynamic/{dynamic_id}", ready_text=None)
        page.wait_for_timeout(1000)
        shot(page, "10-dynamic-overview")
        shot(page, "07-dom-home-dynamic")

        goto_wait(page, f"/dynamic/{dynamic_id}/track", "History")
        shot(page, "11-tracking-hub")

        goto_wait(page, f"/dynamic/{dynamic_id}/ground-rules", "Ground")
        shot(page, "12-ground-rules")

        goto_wait(page, f"/dynamic/{dynamic_id}/interview", ready_text=None)
        page.wait_for_timeout(1200)
        shot(page, "26-interview")

        goto_wait(page, f"/dynamic/{dynamic_id}/knowledge", ready_text=None)
        page.wait_for_timeout(1200)
        shot(page, "27-core-knowledge")

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
        page.wait_for_timeout(900)
        shot(page, "19-chat")

        goto_wait(page, f"/settings?dynamic={dynamic_id}", "Settings")
        page.wait_for_timeout(1000)
        shot(page, "20-settings")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(400)
        shot(page, "21-settings-lower")

        goto_wait(page, f"/dynamic/{dynamic_id}/survey", "Kink")
        shot(page, "22-kink-list")

        goto_wait(page, f"/dynamic/{dynamic_id}/history", ready_text=None)
        page.wait_for_timeout(1200)
        shot(page, "23-history")

        goto_wait(page, f"/dynamic/{dynamic_id}/vault", ready_text=None)
        page.wait_for_timeout(800)
        shot(page, "24-vault")

        goto_wait(page, f"/dynamic/{dynamic_id}/assistant/games/spin", ready_text=None)
        page.wait_for_timeout(1200)
        shot(page, "25-spin-game")

        goto_wait(page, f"/dynamic/{dynamic_id}/journal", ready_text=None)
        page.wait_for_timeout(1000)
        shot(page, "28-journal")

        goto_wait(page, f"/dynamic/{dynamic_id}/sleep", ready_text=None)
        page.wait_for_timeout(1000)
        shot(page, "29-sleep")

        # Sub views
        page.evaluate(
            """() => {
              localStorage.removeItem('ubetra_token');
              localStorage.removeItem('ubetra_user');
              location.hash = '#/login';
              location.reload();
            }"""
        )
        page.wait_for_timeout(1200)
        login(page, SUB)
        dismiss_overlays(page)

        goto_wait(page, f"/dynamic/{dynamic_id}", ready_text=None)
        page.wait_for_timeout(1000)
        dismiss_overlays(page)
        shot(page, "32-sub-dynamic-overview")

        goto_wait(page, f"/chat/{dynamic_id}", "Chat")
        dismiss_overlays(page)
        shot(page, "33-sub-chat")

        goto_wait(page, f"/settings?dynamic={dynamic_id}", "Settings")
        dismiss_overlays(page)
        shot(page, "34-sub-settings")

        goto_wait(page, f"/dynamic/{dynamic_id}/track", "History")
        dismiss_overlays(page)
        shot(page, "35-sub-tracking")

        goto_wait(page, f"/dynamic/{dynamic_id}/punishment", "Punishment")
        dismiss_overlays(page)
        shot(page, "36-sub-punishment")

        goto_wait(page, f"/dynamic/{dynamic_id}/interview", ready_text=None)
        page.wait_for_timeout(1000)
        dismiss_overlays(page)
        shot(page, "37-sub-interview")

        print("recapture done", dynamic_id)
        browser.close()


if __name__ == "__main__":
    main()
