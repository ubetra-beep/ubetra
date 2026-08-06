"""Recapture Dom wiki screenshots with inbox overlay dismissed."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parents[1] / "wiki" / "images"
META = Path(__file__).resolve().parents[1] / "wiki" / "capture-meta.json"
DOM = {"email": "wiki-dom@example.com", "password": "WikiDemoPass123!"}


def dismiss(page):
    page.evaluate(
        """() => {
          const o = document.getElementById('inbox-overlay');
          if (o) o.remove();
          document.querySelectorAll('.inbox-overlay').forEach((el) => el.remove());
        }"""
    )
    for sel in (
        'button:has-text("Got it")',
        'button:has-text("Continue")',
        '#inbox-overlay button.primary-btn',
    ):
        btn = page.locator(sel)
        if btn.count():
            try:
                btn.first.click(timeout=1200, force=True)
                page.wait_for_timeout(300)
            except Exception:
                pass
    page.evaluate(
        """() => {
          const o = document.getElementById('inbox-overlay');
          if (o) o.remove();
        }"""
    )


def shot(page, name):
    dismiss(page)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("shot", name)


def goto(page, path, ready=None):
    page.goto(f"{BASE}/#{path}")
    page.wait_for_timeout(700)
    dismiss(page)
    if ready:
        try:
            page.wait_for_selector(f"text={ready}", timeout=10000)
        except Exception:
            page.wait_for_timeout(900)
    else:
        page.wait_for_timeout(900)
    dismiss(page)


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
        shot(page, "00-login")
        page.fill('input[name="email"]', DOM["email"])
        page.fill('input[name="password"]', DOM["password"])
        page.locator('button.primary-btn[type="submit"]').first.click(force=True)
        page.wait_for_timeout(1600)
        dismiss(page)
        # Ack inbox via API if possible
        try:
            import requests

            token = page.evaluate("() => localStorage.getItem('ubetra_token')")
            requests.post(
                f"{BASE}/api/dynamics/{dynamic_id}/inbox/ack",
                headers={"Authorization": f"Bearer {token}"},
                json={},
                timeout=30,
            )
        except Exception as e:
            print("inbox ack warn", e)
        dismiss(page)
        page.reload()
        page.wait_for_timeout(1000)
        dismiss(page)

        shots = [
            (f"/dynamic/{dynamic_id}", "10-dynamic-overview", None),
            (f"/dynamic/{dynamic_id}", "07-dom-home-dynamic", None),
            (f"/dynamic/{dynamic_id}/track", "11-tracking-hub", "History"),
            (f"/dynamic/{dynamic_id}/ground-rules", "12-ground-rules", "Ground"),
            (f"/dynamic/{dynamic_id}/interview", "26-interview", None),
            (f"/dynamic/{dynamic_id}/knowledge", "27-core-knowledge", None),
            (f"/dynamic/{dynamic_id}/chastity", "13-chastity", "Chastity"),
            (f"/dynamic/{dynamic_id}/tracking", "14-orgasm-tracking", None),
            (f"/dynamic/{dynamic_id}/feelings", "15-feelings", "Feelings"),
            (f"/dynamic/{dynamic_id}/punishment", "16-punishment", "Punishment"),
            (f"/dynamic/{dynamic_id}/tasks", "17-tasks", "Task"),
            (f"/dynamic/{dynamic_id}/assistant", "18-playtime", None),
            (f"/chat/{dynamic_id}", "19-chat", "Chat"),
            (f"/settings?dynamic={dynamic_id}", "20-settings", "Settings"),
            (f"/dynamic/{dynamic_id}/survey", "22-kink-list", "Kink"),
            (f"/dynamic/{dynamic_id}/history", "23-history", None),
            (f"/dynamic/{dynamic_id}/vault", "24-vault", None),
            (f"/dynamic/{dynamic_id}/assistant/games/spin", "25-spin-game", None),
            (f"/dynamic/{dynamic_id}/journal", "28-journal", None),
            (f"/dynamic/{dynamic_id}/sleep", "29-sleep", None),
        ]
        for path, name, ready in shots:
            goto(page, path, ready)
            if name == "20-settings":
                shot(page, "20-settings")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(400)
                shot(page, "21-settings-lower")
            else:
                shot(page, name)
        browser.close()
    print("dom shots done")


if __name__ == "__main__":
    main()
