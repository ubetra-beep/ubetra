from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import HTTPException, status

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def generate_openai_compatible_text(
    *,
    api_key: str,
    model: str,
    system_instruction: str,
    user_prompt: str,
    base_url: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 180,
) -> str:
    root = (base_url or DEFAULT_OPENAI_BASE).rstrip("/")
    if root.endswith("/chat/completions"):
        url = root
    else:
        url = f"{root}/chat/completions"

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.9,
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {})
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("metadata") or body
            else:
                detail = detail or body
        except json.JSONDecodeError:
            detail = body or str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM error: {detail}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM unreachable: {exc.reason}",
        ) from exc

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM returned an unexpected response shape",
        ) from exc


def generate_openai_text(
    *,
    api_key: str,
    model: str,
    system_instruction: str,
    user_prompt: str,
    base_url: str | None = None,
) -> str:
    return generate_openai_compatible_text(
        api_key=api_key,
        model=model,
        system_instruction=system_instruction,
        user_prompt=user_prompt,
        base_url=base_url or DEFAULT_OPENAI_BASE,
    )


def generate_image_openai_compatible(
    *,
    api_key: str,
    prompt: str,
    model: str = "dall-e-3",
    base_url: str | None = None,
    size: str = "1024x1024",
) -> str:
    """Returns a data URL or remote URL string. Raises HTTPException on failure."""
    root = (base_url or DEFAULT_OPENAI_BASE).rstrip("/")
    url = f"{root}/images/generations"
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {}).get("message", body)
        except json.JSONDecodeError:
            detail = body or str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Image generation error: {detail}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Image API unreachable: {exc.reason}",
        ) from exc

    try:
        item = data["data"][0]
        if item.get("b64_json"):
            return f"data:image/png;base64,{item['b64_json']}"
        if item.get("url"):
            return item["url"]
    except (KeyError, IndexError, TypeError):
        pass
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Image API returned an unexpected response",
    )
