"""Thin OpenRouter client used by canary scripts and internal services.

This module is *not* the FastAPI proxy — it is a direct upstream
client that nevertheless reuses the same policy enforcement so that
internal callers (the contamination canary, baseline harnesses, eval
glue) cannot accidentally bypass it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from proxy.policy import GEMMA_MODEL_ID, enforce_request

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter returns a non-2xx response."""

    def __init__(self, status_code: int, payload: Any) -> None:
        super().__init__(f"OpenRouter error {status_code}: {payload!r}")
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True)
class ChatCompletion:
    """Subset of the OpenRouter response we care about for the canary."""

    text: str
    model: str
    provider: str | None
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    raw: dict[str, Any]


class OpenRouterClient:
    """Minimal chat completions client wired to ``policy.enforce_request``.

    Parameters
    ----------
    api_key:
        OpenRouter API key. The participant proxy reads this from
        ``OPENROUTER_KEY``; the judge stack uses ``OPENROUTER_JUDGE_KEY``
        (and may relax the policy in its own dedicated client — this
        class is for the participant side only).
    base_url:
        Override for tests / staging.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = OPENROUTER_BASE,
        referer: str = "https://github.com/dirtycomputer/wanghong_leaderboard",
        app_title: str = "wanghong-leaderboard",
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": referer,
            "X-Title": app_title,
        }

    @classmethod
    def from_env(cls, env_var: str = "OPENROUTER_KEY") -> OpenRouterClient:
        key = os.environ.get(env_var, "").strip()
        if not key:
            raise RuntimeError(
                f"{env_var} is not set; cannot reach OpenRouter. "
                "Copy .env.example to .env and fill it in."
            )
        return cls(api_key=key)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.ReadTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=16),
        reraise=True,
    )
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        top_p: float = 0.95,
        max_tokens: int = 1024,
        extra_request: dict[str, Any] | None = None,
    ) -> ChatCompletion:
        """Run a single chat completion against the pinned Gemma model.

        The body is normalized through ``enforce_request`` so that the
        same time-capsule guarantees apply to internal calls as to
        participant traffic.
        """
        request_body: dict[str, Any] = {
            "model": GEMMA_MODEL_ID,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if extra_request:
            request_body.update(extra_request)

        decision = enforce_request(request_body)
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as http:
            response = http.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=decision.request,
            )

        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text}

        if response.status_code >= 400:
            raise OpenRouterError(response.status_code, payload)

        return _parse_completion(payload)


def _parse_completion(payload: dict[str, Any]) -> ChatCompletion:
    choices = payload.get("choices") or []
    first = choices[0] if choices else {}
    message = first.get("message") or {}
    content = message.get("content")
    text = content if isinstance(content, str) else _flatten_parts(content)
    usage = payload.get("usage") or {}
    return ChatCompletion(
        text=text,
        model=payload.get("model", ""),
        provider=payload.get("provider"),
        finish_reason=first.get("finish_reason"),
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        raw=payload,
    )


def _flatten_parts(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            parts.append(part["text"])
    return "".join(parts)
