"""Capture Sub-only wiki screenshots (after Dom shots already exist)."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parents[1] / "wiki" / "images"
META = Path(__file__).resolve().parents[1] / "wiki" / "capture-meta.json"
SUB = {"email": "wiki-sub@example.com", "password": "WikiDemoPass123!"}


def dismiss(page):
    page.evaluate(
        "() => { const o = document.getElementById('inbox-overlay'); if (o) o.remove(); }"
    )
    for sel in ('button:has-text("Continue")', 'button:has-text("Got it")'):
        btn = page.locator(sel)
        if btn.count():
            try:
                btn.first.click(timeout=800)
            except Exception:
                pass


def shot(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("shot", name)


def main():
    dynamic_id = json.loads(META.read_text(encoding="utf-8"))["dynamic_id"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            viewport={"width": 420, "height": 900},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        ).new_page()
        page.goto(f"{BASE}/#/login")
        page.wait_for_selector('input[name="email"]')
        page.fill('input[name="email"]', SUB["email"])
        page.fill('input[name="password"]', SUB["password"])
        page.locator('button.primary-btn[type="submit"]').first.click(force=True)
        page.wait_for_timeout(1500)
        dismiss(page)

        shots = [
            (f"/dynamic/{dynamic_id}", "32-sub-dynamic-overview", None),
            (f"/chat/{dynamic_id}", "33-sub-chat", "Chat"),
            (f"/settings?dynamic={dynamic_id}", "34-sub-settings", "Settings"),
            (f"/dynamic/{dynamic_id}/track", "35-sub-tracking", "History"),
            (f"/dynamic/{dynamic_id}/punishment", "36-sub-punishment", "Punishment"),
            (f"/dynamic/{dynamic_id}/interview", "37-sub-interview", None),
        ]
        for path, name, ready in shots:
            page.goto(f"{BASE}/#{path}")
            page.wait_for_timeout(900)
            dismiss(page)
            if ready:
                try:
                    page.wait_for_selector(f"text={ready}", timeout=8000)
                except Exception:
                    page.wait_for_timeout(800)
            else:
                page.wait_for_timeout(900)
            dismiss(page)
            shot(page, name)
        browser.close()
    print("sub shots done")


if __name__ == "__main__":
    main()
