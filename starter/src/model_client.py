"""Tiny OpenAI-compatible client pointed at the leaderboard proxy.

Inside the participant container, the only reachable host is the
leaderboard proxy. The proxy enforces:
- model == google/gemma-4-31b-it
- no :online suffix, no tools, no plugins, no server tools
- pinned provider, no fallback

Reading ``MODEL_API_BASE``, ``MODEL_API_KEY`` and ``MODEL_NAME`` from
the environment lets the same harness run unchanged against:
* the official runner (real proxy)
* ``kakeya-lb smoke-run`` (fake model server, ships in a follow-up PR)
"""

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
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Send a single chat completion through the leaderboard proxy."""
    base = os.environ["MODEL_API_BASE"].rstrip("/")
    key = os.environ["MODEL_API_KEY"]
    model = os.environ.get("MODEL_NAME", "google/gemma-4-31b-it")

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as http:
        response = http.post(f"{base}/chat/completions", json=body, headers=headers)
    response.raise_for_status()
    return response.json()


def extract_text(completion: dict[str, Any]) -> str:
    choices = completion.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""
