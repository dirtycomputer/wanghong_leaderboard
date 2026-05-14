"""Tests for the judge OpenRouter client and JSON extraction."""

from __future__ import annotations

import httpx
import orjson
import pytest

from judge.client import DEFAULT_JUDGE_MAX_TOKENS, JudgeClient, JudgeError, _extract_json


def test_extract_plain_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fence():
    text = 'Some preamble\n```json\n{"x": 2}\n```\ntrailing'
    assert _extract_json(text) == {"x": 2}


def test_extract_unfenced_object_amid_text():
    text = "let me think...\n{\n  \"k\": 3\n}\nthat's my answer"
    assert _extract_json(text) == {"k": 3}


def test_extract_array():
    assert _extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_raises_on_garbage():
    with pytest.raises(JudgeError):
        _extract_json("the answer is forty two")


def test_extract_raises_on_empty():
    with pytest.raises(JudgeError):
        _extract_json("")


def test_extract_handles_latex_backslashes_in_strings():
    # LLMs writing math output frequently emit ``\mathbb{R}`` etc. inside
    # JSON string values, which json.loads rejects because ``\m`` is not
    # a valid escape. The extractor must double-escape and retry.
    text = (
        '```json\n{"notes": "The Kakeya conjecture in $\\mathbb{R}^3$ '
        'uses $\\delta$-tubes."}\n```'
    )
    obj = _extract_json(text)
    assert obj["notes"].startswith("The Kakeya conjecture")
    assert "mathbb" in obj["notes"]


# --- chat() over a mocked transport -----------------------------------------


def _client(handler, *, model: str = "test-judge") -> JudgeClient:
    return JudgeClient(
        api_key="test-key",
        model=model,
        transport=httpx.MockTransport(handler),
    )


def _completion(content: str, *, finish_reason: str = "stop", usage: dict | None = None):
    return {
        "model": "test-judge",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
        ],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20},
    }


def test_chat_default_max_tokens_is_reasoning_sized():
    # Regression: Kimi K2.6 burns ~14k tokens on the thinking block; the
    # judge default must leave room for reasoning + the JSON answer.
    assert DEFAULT_JUDGE_MAX_TOKENS >= 16000

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = orjson.loads(request.content)
        return httpx.Response(200, json=_completion('{"ok": true}'))

    resp = _client(handler).chat([{"role": "user", "content": "hi"}], expect_json=True)
    assert resp.parsed_json == {"ok": True}
    assert captured["body"]["max_tokens"] == DEFAULT_JUDGE_MAX_TOKENS


def test_chat_raises_clear_error_when_reasoning_exhausts_budget():
    # Reasoning models can spend the whole completion budget on the
    # thinking block and emit zero content with finish_reason=length.
    # chat() must raise a JudgeError that names the failure mode rather
    # than a vague "empty text".
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completion(
                "",
                finish_reason="length",
                usage={
                    "prompt_tokens": 2051,
                    "completion_tokens": 8192,
                    "completion_tokens_details": {"reasoning_tokens": 8069},
                },
            ),
        )

    with pytest.raises(JudgeError) as exc:
        _client(handler, model="moonshotai/kimi-k2.6").chat(
            [{"role": "user", "content": "hi"}], expect_json=True
        )
    msg = str(exc.value)
    assert "finish_reason=length" in msg
    assert "reasoning_tokens=8069" in msg
    assert "moonshotai/kimi-k2.6" in msg


def test_chat_surfaces_upstream_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "provider declined"}})

    with pytest.raises(JudgeError) as exc:
        _client(handler).chat([{"role": "user", "content": "hi"}], expect_json=True)
    assert "403" in str(exc.value)


def test_chat_returns_finish_reason_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion('{"v": 1}', finish_reason="stop"))

    resp = _client(handler).chat([{"role": "user", "content": "hi"}], expect_json=True)
    assert resp.finish_reason == "stop"
    assert resp.parsed_json == {"v": 1}
