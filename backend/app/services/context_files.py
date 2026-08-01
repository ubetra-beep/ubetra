"""Extract text from AI-friendly uploads for the context library."""

from __future__ import annotations

import csv
import html
import io
import json
import re
from pathlib import Path

ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".pdf", ".docx"}
MAX_TEXT_CHARS = 100_000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

CONTEXT_SUBJECTS = {
    "stories": "Stories",
    "journals": "Journals",
    "scenes": "Scenes",
    "other": "Other",
}

# Map legacy ContextLinkCategory values → subject tags
LEGACY_CATEGORY_TO_SUBJECT = {
    "fictional_story": "stories",
    "contract": "other",
    "reference_guide": "other",
    "scene_inspiration": "scenes",
    "other": "other",
}


def normalize_subject(raw: str | None) -> str:
    key = (raw or "other").strip().lower()
    if key in CONTEXT_SUBJECTS:
        return key
    return LEGACY_CATEGORY_TO_SUBJECT.get(key, "other")


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_text_from_bytes(filename: str, data: bytes, mime: str = "") -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is too large (max 5 MB).")
    name = (filename or "upload").strip()
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "Unsupported format. Use .txt, .md, .csv, .json, .html, .pdf, or .docx."
        )

    if ext in {".txt", ".md"}:
        text = data.decode("utf-8", errors="replace")
    elif ext == ".csv":
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV must be UTF-8") from exc
        reader = csv.reader(io.StringIO(decoded))
        rows = [", ".join(cell.strip() for cell in row if cell is not None) for row in reader]
        text = "\n".join(r for r in rows if r.strip())
    elif ext == ".json":
        try:
            parsed = json.loads(data.decode("utf-8"))
            text = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid JSON: {exc}") from exc
    elif ext in {".html", ".htm"}:
        text = _strip_html(data.decode("utf-8", errors="replace"))
    elif ext == ".pdf":
        text = _extract_pdf(data)
    elif ext == ".docx":
        text = _extract_docx(data)
    else:
        raise ValueError("Unsupported format.")

    text = (text or "").strip()
    if not text:
        raise ValueError("Could not extract any text from that file.")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ValueError("PDF support is not installed on this server.") from exc
    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(parts).strip()


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise ValueError("DOCX support is not installed on this server.") from exc
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
