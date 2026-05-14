"""OpenRouter client for the judge stack.

This is intentionally *separate* from ``proxy.client.OpenRouterClient``
because the constraints are inverted: the judge stack is allowed to
use the latest models, ``:online`` suffixes, and the OpenRouter web
plugin. The two clients also read different env vars so a participant
proxy compromise cannot escalate into the judge account.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# Reasoning judge models (Kimi K2.6, etc.) can spend 10k+ tokens on the
# thinking block before emitting any content, and large generations take
# a while — give the read timeout generous headroom.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)

#: Default completion budget for judge calls. Sized for *reasoning*
#: models: Kimi K2.6 burns ~14k tokens on the thinking block for the
#: gold-graph / adversarial prompts, then needs ~1-2k more for the JSON
#: answer. Non-reasoning models simply never use the headroom (you only
#: pay for tokens actually generated). OpenRouter's ``reasoning`` cap is
#: not honoured by every provider, so a generous ``max_tokens`` is the
#: portable lever.
DEFAULT_JUDGE_MAX_TOKENS = 24000


class JudgeError(RuntimeError):
    """Raised when the judge call fails or produces unparseable output."""


@dataclass(frozen=True)
class JudgeResponse:
    """One judge LLM call result.

    ``text`` is the raw assistant content. ``parsed_json`` is set when
    ``expect_json=True`` and the response contained a valid JSON block.
    """

    text: str
    model: str
    provider: str | None
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    parsed_json: Any | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class JudgeClient:
    """Thin OpenRouter client with optional web search.

    Parameters
    ----------
    model:
        OpenRouter slug for the judge model. Defaults to
        ``anthropic/claude-sonnet-4.6`` so the rubric reviewer is a
        widely available frontier model; can be overridden by the
        ``JUDGE_MODEL`` env var or per-call.
    web_enabled:
        When ``True``, attach the OpenRouter web plugin so the model
        may issue web search calls during reasoning. Only judges B and
        E should set this.
    transport:
        Optional ``httpx`` transport. Tests inject ``httpx.MockTransport``
        here so :meth:`chat` can be exercised without live traffic.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "anthropic/claude-sonnet-4.6",
        base_url: str = OPENROUTER_BASE,
        web_enabled: bool = False,
        referer: str = "https://github.com/dirtycomputer/wanghong_leaderboard",
        app_title: str = "wanghong-leaderboard-judge",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("judge api_key is required")
        self._api_key = api_key
        self._model = model
        self._base = base_url.rstrip("/")
        self._web_enabled = web_enabled
        self._transport = transport
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": referer,
            "X-Title": app_title,
        }

    @property
    def model(self) -> str:
        return self._model

    @property
    def web_enabled(self) -> bool:
        return self._web_enabled

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = "OPENROUTER_JUDGE_KEY",
        model: str | None = None,
        web_enabled: bool = False,
    ) -> JudgeClient:
        key = os.environ.get(env_var, "").strip()
        if not key:
            raise RuntimeError(
                f"{env_var} is not set; the judge stack uses a separate "
                "OpenRouter key from the participant proxy"
            )
        return cls(
            api_key=key,
            model=model or os.environ.get("JUDGE_MODEL") or "anthropic/claude-sonnet-4.6",
            web_enabled=web_enabled,
        )

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
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_JUDGE_MAX_TOKENS,
        expect_json: bool = False,
    ) -> JudgeResponse:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._web_enabled:
            body["plugins"] = [{"id": "web"}]
        client_kwargs: dict[str, Any] = {"timeout": _DEFAULT_TIMEOUT}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        with httpx.Client(**client_kwargs) as http:
            response = http.post(
                f"{self._base}/chat/completions",
                headers=self._headers,
                json=body,
            )
        try:
            payload = response.json()
        except ValueError:
            raise JudgeError(f"upstream non-JSON ({response.status_code})") from None
        if response.status_code >= 400:
            raise JudgeError(f"judge LLM error {response.status_code}: {payload!r}")

        choices = payload.get("choices") or []
        first = choices[0] if choices else {}
        message = first.get("message") or {}
        content = message.get("content")
        text = content if isinstance(content, str) else _flatten_parts(content)
        usage = payload.get("usage") or {}
        finish_reason = first.get("finish_reason")

        parsed = None
        if expect_json:
            if not text and finish_reason == "length":
                # Reasoning models (Kimi K2.6, etc.) can burn the entire
                # completion budget on the thinking block and emit zero
                # content. Surface this explicitly instead of a vague
                # "empty text" so the operator knows to raise max_tokens.
                reasoning_tokens = (
                    (usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"
                    )
                )
                raise JudgeError(
                    f"judge model {self._model!r} hit max_tokens before "
                    f"emitting any content (finish_reason=length, "
                    f"reasoning_tokens={reasoning_tokens}); raise max_tokens"
                )
            parsed = _extract_json(text)

        return JudgeResponse(
            text=text,
            model=payload.get("model", self._model),
            provider=payload.get("provider"),
            finish_reason=finish_reason,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            parsed_json=parsed,
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


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_FIRST_JSON_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)
# Matches a backslash followed by a character that is NOT a legal JSON
# escape. Mathematical LLM output frequently contains things like
# ``\mathbb{R}`` or ``\delta`` inside string values; json.loads rejects
# the lone backslash. We retry after doubling those backslashes so the
# resulting JSON still decodes the same string content.
_BAD_JSON_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')


def _extract_json(text: str) -> Any:
    """Best-effort extraction of a JSON object/array from LLM output."""
    if not text:
        raise JudgeError("judge returned empty text")
    fenced = _JSON_FENCE_RE.search(text)
    candidates: list[str] = []
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())
    open_match = _FIRST_JSON_RE.search(text)
    if open_match:
        candidates.append(open_match.group(1).strip())
    last_err: Exception | None = None
    for cand in candidates:
        for variant in (cand, _BAD_JSON_ESCAPE_RE.sub(r"\\\\", cand)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError as exc:
                last_err = exc
                continue
    raise JudgeError(f"could not parse JSON from judge output: {last_err}")
