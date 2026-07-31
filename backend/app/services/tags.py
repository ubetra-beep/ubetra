from __future__ import annotations

TAG_SEP = ","


def tags_to_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(TAG_SEP) if part.strip()]


def tags_to_string(tags: list[str] | None) -> str:
    if not tags:
        return ""
    cleaned = [t.strip().lower() for t in tags if t and t.strip()]
    return TAG_SEP.join(dict.fromkeys(cleaned))


def entry_matches_tags(entry_tags: list[str], selected: list[str]) -> bool:
    if not selected:
        return True
    if not entry_tags:
        return False
    selected_set = {t.lower() for t in selected}
    return any(tag in selected_set for tag in entry_tags)


def entry_all_tags(entry) -> list[str]:
    """Entry-level tags plus all per-orgasm row tags."""
    tags: list[str] = list(tags_to_list(getattr(entry, "tags", "") or ""))
    for row in getattr(entry, "orgasms", None) or []:
        tags.extend(tags_to_list(getattr(row, "tags", "") or ""))
    return list(dict.fromkeys(tags))


def entry_matches_selected_tags(entry, selected: list[str]) -> bool:
    """Match against entry tags and per-orgasm row tags."""
    if not selected:
        return True
    return entry_matches_tags(entry_all_tags(entry), selected)
