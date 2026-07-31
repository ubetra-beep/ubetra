from __future__ import annotations

import re
import urllib.error
import urllib.request

GOOGLE_DRIVE_HOSTS = ("drive.google.com", "docs.google.com", "sheets.google.com")
DOC_ID_PATTERN = re.compile(r"/d/([a-zA-Z0-9_-]+)")


def is_google_drive_url(url: str) -> bool:
    lowered = url.lower().strip()
    return any(host in lowered for host in GOOGLE_DRIVE_HOSTS)


def extract_google_file_id(url: str) -> str | None:
    match = DOC_ID_PATTERN.search(url)
    return match.group(1) if match else None


def fetch_public_google_doc_text(url: str, *, max_chars: int = 12000) -> str:
    """Best-effort fetch for publicly shared Google Docs. Returns empty string on failure."""
    file_id = extract_google_file_id(url)
    if not file_id:
        return ""

    export_url = f"https://docs.google.com/document/d/{file_id}/export?format=txt"
    request = urllib.request.Request(
        export_url,
        headers={"User-Agent": "UBETRA/0.1 (self-hosted)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(max_chars + 1)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return ""

    text = raw.decode("utf-8", errors="ignore").strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…"
    return text
