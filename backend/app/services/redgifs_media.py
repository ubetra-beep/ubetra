"""Read-only playlists from a shared RedGIFs drop folder (Gluetun writes elsewhere)."""
from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings

MEDIA_SUFFIXES = {
    ".mp4": "video",
    ".webm": "video",
    ".mov": "video",
    ".mkv": "video",
    ".m4v": "video",
    ".gif": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
}
SKIP_SUFFIXES = {".part", ".tmp", ".ytdl", ".download"}
STALE_WRITE_SEC = 3.0


def redgifs_root() -> Path:
    raw = (settings.redgifs_dir or "").strip() or str(Path("/app/backend/data/redgifs"))
    return Path(raw).expanduser()


def root_ok() -> bool:
    path = redgifs_root()
    return path.is_dir()


def _is_growing(path: Path) -> bool:
    try:
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except OSError:
        return True
    return age < STALE_WRITE_SEC


def _kind_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in SKIP_SUFFIXES:
        return None
    if path.name.endswith(".info.json") or path.name.lower() == "archive.txt":
        return None
    return MEDIA_SUFFIXES.get(suffix)


def _safe_folder(name: str) -> str:
    text = (name or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError("invalid playlist")
    return text


def _safe_file(name: str) -> str:
    text = (name or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError("invalid file")
    return text


def resolve_playlist_dir(folder: str) -> Path:
    root = redgifs_root().resolve()
    dest = (root / _safe_folder(folder)).resolve()
    if dest != root and root not in dest.parents:
        raise ValueError("invalid playlist")
    if not dest.is_dir():
        raise FileNotFoundError("playlist not found")
    return dest


def resolve_media_file(folder: str, filename: str) -> Path:
    dest = (resolve_playlist_dir(folder) / _safe_file(filename)).resolve()
    root = redgifs_root().resolve()
    if root not in dest.parents:
        raise ValueError("invalid file")
    if not dest.is_file():
        raise FileNotFoundError("file not found")
    if _kind_for(dest) is None:
        raise FileNotFoundError("file not found")
    return dest


@dataclass
class MediaFile:
    name: str
    kind: str
    size: int
    url_path: str


def list_playlist_files(folder: str) -> list[MediaFile]:
    dest = resolve_playlist_dir(folder)
    rows: list[MediaFile] = []
    for path in sorted(dest.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        kind = _kind_for(path)
        if kind is None or _is_growing(path):
            continue
        rows.append(
            MediaFile(
                name=path.name,
                kind=kind,
                size=int(path.stat().st_size),
                url_path=f"{folder}/{path.name}",
            )
        )
    return rows


def list_playlists() -> list[dict]:
    root = redgifs_root()
    if not root.is_dir():
        return []
    playlists = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            files = list_playlist_files(path.name)
        except (ValueError, FileNotFoundError, OSError):
            files = []
        playlists.append(
            {
                "id": path.name,
                "title": path.name.replace("|", " · ").replace("｜", " · "),
                "count": len(files),
                "files": [
                    {
                        "name": item.name,
                        "kind": item.kind,
                        "size": item.size,
                    }
                    for item in files
                ],
            }
        )
    return playlists


def mime_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() in {".mp4", ".m4v"}:
        return "video/mp4"
    if path.suffix.lower() == ".webm":
        return "video/webm"
    return "application/octet-stream"
