"""Create the first GitHub wiki page using a logged-in Chrome profile if available."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HOME = Path(__file__).resolve().parents[1] / "wiki" / "Home.md"
WIKI_NEW = "https://github.com/ubetra-beep/ubetra/wiki/_new"
CHROME_USER = Path.home() / "AppData/Local/Google/Chrome/User Data"


def main():
    body = HOME.read_text(encoding="utf-8")
    # Copy only Default cookies profile subset into temp to avoid locking main Chrome
    tmp = Path(tempfile.mkdtemp(prefix="ubetra-chrome-"))
    src_default = CHROME_USER / "Default"
    dst_default = tmp / "Default"
    dst_default.mkdir(parents=True)
    for name in ("Cookies", "Login Data", "Preferences", "Secure Preferences", "Network"):
        src = src_default / name
        if src.exists():
            try:
                if src.is_dir():
                    shutil.copytree(src, dst_default / name, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst_default / name)
            except Exception as e:
                print("skip", name, e)
    # Local State
    local_state = CHROME_USER / "Local State"
    if local_state.exists():
        try:
            shutil.copy2(local_state, tmp / "Local State")
        except Exception as e:
            print("local state", e)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(tmp),
            channel="chrome",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(WIKI_NEW, wait_until="domcontentloaded", timeout=60000)
        print("url", page.url)
        print("title", page.title())
        # If login wall, fail clearly
        if "/login" in page.url or page.locator("text=Sign in").count():
            page.screenshot(path=str(Path(__file__).resolve().parents[1] / "wiki" / "images" / "wiki-login-wall.png"))
            context.close()
            raise SystemExit("Chrome profile is not logged into GitHub. Create first wiki page manually once.")

        # Fill wiki editor
        # Modern GitHub uses textarea#wiki-body or name=wiki[body]
        page.wait_for_timeout(1500)
        name_input = page.locator('input[name="wiki[name]"], #wiki-name, input[name="name"]')
        if name_input.count():
            name_input.first.fill("Home")
        body_area = page.locator('textarea[name="wiki[body]"], #wiki-body, textarea')
        if not body_area.count():
            page.screenshot(path=str(Path(__file__).resolve().parents[1] / "wiki" / "images" / "wiki-editor-missing.png"))
            print(page.content()[:2000])
            context.close()
            raise SystemExit("Wiki editor not found")
        body_area.first.fill(body[:8000])
        save = page.locator('button:has-text("Save Page"), button:has-text("Save page"), button[type="submit"]')
        save.first.click()
        page.wait_for_timeout(2500)
        print("after save", page.url)
        context.close()
    print("bootstrap ok")


if __name__ == "__main__":
    main()
