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
    image_data_urls: list[str] | None = None,
) -> str:
    root = (base_url or DEFAULT_OPENAI_BASE).rstrip("/")
    if root.endswith("/chat/completions"):
        url = root
    else:
        url = f"{root}/chat/completions"

    user_content: str | list = user_prompt
    if image_data_urls:
        user_content = [{"type": "text", "text": user_prompt}]
        for url in image_data_urls[:6]:
            if url:
                user_content.append({"type": "image_url", "image_url": {"url": url}})
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
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


def _generate_image_openrouter(*, api_key: str, prompt: str, model: str, root: str) -> str:
    """OpenRouter draws through chat completions, not /images/generations."""
    url = f"{root}/chat/completions"
    payload = json.dumps(
        {
            "model": model or "google/gemini-2.5-flash-image",
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
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
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Image API returned an unexpected response",
        ) from exc
    images = message.get("images") or []
    if images and isinstance(images[0], dict):
        image_url = images[0].get("image_url") or {}
        found = image_url.get("url") or images[0].get("url") or ""
        if found:
            return found
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            image_url = part.get("image_url") or {}
            found = image_url.get("url") or ""
            if found:
                return found
    notes: list[str] = []
    refusal = message.get("refusal")
    if refusal:
        notes.append(str(refusal).strip())
    if isinstance(content, str) and content.strip():
        notes.append(content.strip())
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, str) and part.strip():
                notes.append(part.strip())
            elif isinstance(part, dict) and str(part.get("text") or "").strip():
                notes.append(str(part["text"]).strip())
    reason = " ".join(notes).strip()
    detail = "The image model returned no picture"
    if reason:
        detail = f"{detail}. {reason[:400]}"
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=detail,
    )


def _generate_image_openrouter_images(*, api_key: str, prompt: str, model: str, root: str) -> str:
    """OpenRouter's dedicated image API: POST /images, not chat completions."""
    url = f"{root}/images"
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": "1:1",
            "output_format": "png",
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
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
            media = item.get("media_type") or "image/png"
            return f"data:{media};base64,{item['b64_json']}"
        if item.get("url"):
            return item["url"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Image API returned an unexpected response",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="The image model returned no picture",
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
    if "openrouter.ai" in root:
        name = (model or "").lower()
        # Gemini image models on this key answer through chat completions.
        if name.startswith("google/gemini") or "nano-banana" in name:
            return _generate_image_openrouter(
                api_key=api_key,
                prompt=prompt,
                model=model,
                root=root,
            )
        return _generate_image_openrouter_images(
            api_key=api_key,
            prompt=prompt,
            model=model,
            root=root,
        )
    url = f"{root}/images/generations"
    name = (model or "").lower()
    gpt_image = name.startswith("gpt-image") or name.startswith("chatgpt-image")
    # GPT image models only accept 1024+ sizes and reject response_format.
    if gpt_image and size in {"256x256", "512x512"}:
        size = "1024x1024"
    body = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }
    if not gpt_image:
        body["response_format"] = "b64_json"
    payload = json.dumps(body).encode("utf-8")
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
