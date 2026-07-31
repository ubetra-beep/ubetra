from __future__ import annotations

import google.generativeai as genai
from fastapi import HTTPException, status


def _safety_settings() -> list[dict[str, str]]:
    categories = [
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    ]
    return [{"category": category, "threshold": "BLOCK_NONE"} for category in categories]


def generate_gemini_text(
    *,
    api_key: str,
    model: str,
    system_instruction: str,
    user_prompt: str,
) -> str:
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_instruction,
    )
    try:
        response = gemini_model.generate_content(
            user_prompt,
            safety_settings=_safety_settings(),
        )
    except Exception as exc:
        message = str(exc)
        if "404" in message or "no longer available" in message.lower() or "not found" in message.lower():
            message = (
                f"{exc}. This model ID is likely retired. "
                "Open Settings and switch to gemini-3.5-flash (or gemini-3.1-flash-lite)."
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini error: {message}",
        ) from exc

    text = getattr(response, "text", None)
    if not text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Gemini returned an empty response. The model may have blocked the output, "
                "or the model ID may be retired — try gemini-3.5-flash in Settings."
            ),
        )
    return text.strip()
