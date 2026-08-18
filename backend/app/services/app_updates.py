"""Compare this install to GitHub main (VERSION file)."""
from __future__ import annotations

import re
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from ..config import ROOT_DIR

GITHUB_REPO = "ubetra-beep/ubetra"
GITHUB_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/VERSION"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"
GITHUB_CHANGELOG_URL = f"{GITHUB_REPO_URL}/blob/main/CHANGELOG.md"

_LOCK = threading.Lock()
_CACHE: dict = {"at": 0.0, "version": ""}
_CACHE_TTL_SEC = 60 * 60


def read_local_version() -> str:
    path = ROOT_DIR / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return ""


def parse_version(raw: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", (raw or "").strip())
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts[:4])


def fetch_github_version() -> str:
    now = time.time()
    with _LOCK:
        if _CACHE["version"] and now - _CACHE["at"] < _CACHE_TTL_SEC:
            return str(_CACHE["version"])
    try:
        req = Request(GITHUB_VERSION_URL, headers={"User-Agent": "UBETRA-update-check"})
        with urlopen(req, timeout=4) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip().splitlines()[0].strip()
    except (URLError, TimeoutError, OSError, ValueError):
        with _LOCK:
            return str(_CACHE["version"] or "")
    with _LOCK:
        _CACHE["at"] = now
        _CACHE["version"] = text
    return text


def updates_payload() -> dict:
    local = read_local_version()
    remote = fetch_github_version()
    newer = bool(remote and local and parse_version(remote) > parse_version(local))
    return {
        "local_version": local,
        "github_version": remote,
        "github_newer": newer,
        "github_repo": GITHUB_REPO,
        "github_url": GITHUB_REPO_URL,
        "changelog_url": GITHUB_CHANGELOG_URL,
    }
