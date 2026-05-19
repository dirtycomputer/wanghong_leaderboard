from __future__ import annotations

import os
from typing import Any

import httpx


def chat(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    base = os.environ["MODEL_API_BASE"].rstrip("/")
    key = os.environ["MODEL_API_KEY"]
    model = os.environ.get("MODEL_NAME", "google/gemma-4-31b-it")
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=httpx.Timeout(120.0)) as http:
        response = http.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
    response.raise_for_status()
    return response.json()


def extract_text(completion: dict[str, Any]) -> str:
    choices = completion.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""
