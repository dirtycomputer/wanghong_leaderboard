"""Thin OpenAI-compatible chat client and a callable protocol baselines use."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from baselines.common.context import BaselineContext


class RealChatError(RuntimeError):
    """Raised when the proxy returns a non-2xx response."""


#: Signature used by every baseline. Tests inject a fake that returns
#: deterministic text without hitting the proxy.
ChatFn = Callable[[BaselineContext, list[dict[str, Any]]], dict[str, Any]]


def default_chat(
    ctx: BaselineContext,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 1024,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Send a single chat completion through the leaderboard proxy.

    Returns the raw OpenAI-compatible response dict so callers can
    inspect usage / finish_reason in addition to message content.
    """
    body: dict[str, Any] = {
        "model": ctx.model_name,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {ctx.model_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as http:
        response = http.post(
            f"{ctx.model_api_base}/chat/completions",
            json=body,
            headers=headers,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RealChatError(f"proxy returned non-JSON: {response.text!r}") from exc
    if response.status_code >= 400:
        raise RealChatError(f"proxy error {response.status_code}: {payload!r}")
    return payload


def extract_text(completion: dict[str, Any]) -> str:
    """Read the assistant content out of an OpenAI-compatible response."""
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
