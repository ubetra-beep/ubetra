"""Serve the wiki that shipped with this install (repo wiki/ folder)."""
from __future__ import annotations

import re
from pathlib import Path

from ..config import ROOT_DIR

WIKI_DIR = ROOT_DIR / "wiki"
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")

DEFAULT_PAGES = [
    ("Home", "Home"),
    ("Getting-Started", "Getting Started"),
    ("Onboarding", "Onboarding"),
    ("Features-and-Settings", "Features & Settings"),
    ("Workflows", "Workflows"),
    ("Feature-map", "Feature map"),
    ("AI-context", "AI context"),
    ("Context-maps", "Context maps"),
    ("Assistant-Domme", "Assistant Domme"),
    ("Dynamics", "Dynamics"),
    ("Tracking", "Tracking"),
    ("Chat", "Chat"),
    ("Playtime", "Playtime"),
    ("Settings", "Settings"),
    ("Roles-and-Permissions", "Roles & Permissions"),
    ("Self-Hosting", "Self-Hosting"),
]


def _safe_slug(slug: str) -> str | None:
    text = (slug or "").strip()
    if not text:
        return None
    if text.lower().endswith(".md"):
        text = text[:-3]
    if not SLUG_RE.match(text):
        return None
    return text


def list_wiki_pages() -> list[dict]:
    pages = []
    seen: set[str] = set()
    if WIKI_DIR.is_dir():
        for path in sorted(WIKI_DIR.glob("*.md")):
            slug = path.stem
            if slug.startswith("_"):
                continue
            title = slug.replace("-", " ")
            pages.append({"slug": slug, "title": title})
            seen.add(slug.lower())
    for slug, title in DEFAULT_PAGES:
        if slug.lower() not in seen:
            pages.append({"slug": slug, "title": title})
    return pages


def _read_local(slug: str) -> str | None:
    path = WIKI_DIR / f"{slug}.md"
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def load_wiki_page(slug: str) -> dict | None:
    safe = _safe_slug(slug)
    if not safe:
        return None
    body = _read_local(safe)
    if body is None:
        return None
    title = safe.replace("-", " ")
    first = next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.startswith("# ")), "")
    if first:
        title = first
    return {
        "slug": safe,
        "title": title,
        "markdown": body,
        "source": "local",
    }


def wiki_image_path(name: str) -> Path | None:
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    path = WIKI_DIR / "images" / name
    if path.is_file():
        return path
    return None
