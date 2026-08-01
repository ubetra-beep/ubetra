"""Bootstrap GitHub wiki (first page) then the git remote becomes available."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import requests

OWNER = "ubetra-beep"
REPO = "ubetra"
ROOT = Path(__file__).resolve().parents[1]
HOME_MD = (ROOT / "wiki" / "Home.md").read_text(encoding="utf-8")


def gh_token() -> str:
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def main():
    token = gh_token()
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "ubetra-wiki-bootstrap",
            "Authorization": f"token {token}",
            # Prefer HTML session via cookie from API is hard; use Accept for API? Web needs cookies.
        }
    )

    # Exchange token for a web session cookie via the OAuth-ish cookie endpoint used by gh
    # Fall back: use the pages API alternative — create wiki via git after seeding Home through
    # GitHub's "Create the first page" HTML form with authenticity_token.
    new_url = f"https://github.com/{OWNER}/{REPO}/wiki/_new"
    # Token alone often insufficient for HTML; try SSO cookie via api.github.com login
    r = session.get(
        new_url,
        headers={
            "Accept": "text/html",
            "Authorization": f"Bearer {token}",
        },
        allow_redirects=True,
        timeout=60,
    )
    print("GET _new", r.status_code, r.url[:120])
    if "authenticity_token" not in r.text:
        # Try without bearer, with token as cookie style used by some tools
        session.cookies.set("user_session", token, domain="github.com")
        r = session.get(new_url, timeout=60)
        print("GET retry", r.status_code, "token" in r.text.lower())

    m = re.search(r'name="authenticity_token" value="([^"]+)"', r.text)
    if not m:
        # Last resort: print hint
        Path(ROOT / "wiki" / "BOOTSTRAP_NEEDED.txt").write_text(
            "Open https://github.com/ubetra-beep/ubetra/wiki and click "
            "'Create the first page', title Home, save once. Then re-run wiki push.\n",
            encoding="utf-8",
        )
        raise SystemExit(
            "Could not obtain wiki form token automatically. "
            "Open https://github.com/ubetra-beep/ubetra/wiki and create the first page named Home, then re-run publish."
        )

    authenticity = m.group(1)
    post = session.post(
        f"https://github.com/{OWNER}/{REPO}/wiki",
        data={
            "authenticity_token": authenticity,
            "wiki[name]": "Home",
            "wiki[body]": HOME_MD[:5000],
            "wiki[commit]": "Bootstrap wiki Home",
            "wiki[format]": "markdown",
        },
        timeout=60,
        allow_redirects=True,
    )
    print("POST wiki", post.status_code, post.url[:120])


if __name__ == "__main__":
    main()
