"""Pronouns from biological sex. Unset, intersex, and prefer-not-to-say use they/them."""

from __future__ import annotations


def pronouns_for_sex(sex: str | None) -> dict[str, str]:
    value = (sex or "").strip().lower()
    if value == "male":
        return {"subj": "he", "obj": "him", "poss": "his", "Subj": "He", "Obj": "Him"}
    if value == "female":
        return {"subj": "she", "obj": "her", "poss": "her", "Subj": "She", "Obj": "Her"}
    return {"subj": "they", "obj": "them", "poss": "their", "Subj": "They", "Obj": "Them"}


def role_tokens(
    *,
    sub_name: str,
    dom_name: str,
    sub_sex: str | None = "",
    dom_sex: str | None = "",
) -> dict[str, str]:
    sub = pronouns_for_sex(sub_sex)
    dom = pronouns_for_sex(dom_sex)
    return {
        "sub": (sub_name or "your partner").strip() or "your partner",
        "dom": (dom_name or "the keyholder").strip() or "the keyholder",
        "ss": sub["subj"],
        "so": sub["obj"],
        "sp": sub["poss"],
        "SS": sub["Subj"],
        "ds": dom["subj"],
        "do": dom["obj"],
        "dp": dom["poss"],
        "DS": dom["Subj"],
    }


def fill_role_text(text: str, tokens: dict[str, str]) -> str:
    out = text or ""
    for key, value in tokens.items():
        out = out.replace("{" + key + "}", value)
    return out


def personalize_items(items: list[dict], tokens: dict[str, str]) -> list[dict]:
    personalized = []
    for item in items:
        copy = dict(item)
        if copy.get("title"):
            copy["title"] = fill_role_text(str(copy["title"]), tokens)
        if copy.get("description"):
            copy["description"] = fill_role_text(str(copy["description"]), tokens)
        if copy.get("value_label"):
            copy["value_label"] = fill_role_text(str(copy["value_label"]), tokens)
        personalized.append(copy)
    return personalized
