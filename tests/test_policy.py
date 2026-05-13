"""Unit tests for the participant proxy policy.

These tests are the contract that protects the time-capsule property.
If any of them break we have lost the security boundary.
"""

from __future__ import annotations

import pytest

from proxy.policy import (
    GEMMA_MODEL_ID,
    PolicyViolation,
    enforce_request,
    safe_provider_envelope,
)


def _base_request(**overrides):
    body = {
        "model": GEMMA_MODEL_ID,
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.2,
        "max_tokens": 64,
    }
    body.update(overrides)
    return body


def test_accepts_baseline_request():
    decision = enforce_request(_base_request())
    assert decision.request["model"] == GEMMA_MODEL_ID
    assert decision.request["plugins"] == [{"id": "web", "enabled": False}]
    provider = decision.request["provider"]
    assert provider["allow_fallbacks"] is False
    assert provider["require_parameters"] is True
    assert provider["data_collection"] == "deny"


def test_rejects_wrong_model():
    with pytest.raises(PolicyViolation):
        enforce_request(_base_request(model="openai/gpt-4o"))


def test_rejects_online_suffix():
    with pytest.raises(PolicyViolation):
        enforce_request(_base_request(model=f"{GEMMA_MODEL_ID}:online"))


def test_rejects_tools_field():
    with pytest.raises(PolicyViolation):
        enforce_request(
            _base_request(tools=[{"type": "function", "function": {"name": "search"}}])
        )


def test_rejects_tool_choice():
    with pytest.raises(PolicyViolation):
        enforce_request(_base_request(tool_choice="auto"))


def test_rejects_functions_field():
    with pytest.raises(PolicyViolation):
        enforce_request(
            _base_request(functions=[{"name": "search", "parameters": {}}])
        )


def test_rejects_function_call():
    with pytest.raises(PolicyViolation):
        enforce_request(_base_request(function_call={"name": "search"}))


def test_rejects_web_search_options():
    with pytest.raises(PolicyViolation):
        enforce_request(_base_request(web_search_options={"max_results": 5}))


def test_rejects_enabled_web_plugin():
    with pytest.raises(PolicyViolation):
        enforce_request(_base_request(plugins=[{"id": "web", "enabled": True}]))


def test_rejects_non_web_plugin():
    with pytest.raises(PolicyViolation):
        enforce_request(_base_request(plugins=[{"id": "browser"}]))


def test_accepts_disabled_web_plugin_and_normalises():
    decision = enforce_request(
        _base_request(plugins=[{"id": "web", "enabled": False}])
    )
    assert decision.request["plugins"] == [{"id": "web", "enabled": False}]


def test_rejects_server_tool_in_message_content():
    with pytest.raises(PolicyViolation):
        enforce_request(
            _base_request(
                messages=[
                    {
                        "role": "user",
                        "content": "please openrouter:web_search for kakeya",
                    }
                ]
            )
        )


def test_rejects_server_tool_in_structured_content():
    with pytest.raises(PolicyViolation):
        enforce_request(
            _base_request(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "use openrouter:web_fetch"},
                        ],
                    }
                ]
            )
        )


def test_drops_participant_supplied_provider(monkeypatch):
    monkeypatch.delenv("GEMMA_PROVIDER_SLUG", raising=False)
    decision = enforce_request(
        _base_request(
            provider={"order": ["evil"], "allow_fallbacks": True, "data_collection": "allow"}
        )
    )
    assert decision.request["provider"] == {
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
    }


def test_provider_pinning_when_env_set(monkeypatch):
    monkeypatch.setenv("GEMMA_PROVIDER_SLUG", "fictitious")
    envelope = safe_provider_envelope(None)
    assert envelope["only"] == ["fictitious"]


def test_missing_model_is_rejected():
    body = _base_request()
    body.pop("model")
    with pytest.raises(PolicyViolation):
        enforce_request(body)


def test_non_dict_body_rejected():
    with pytest.raises(PolicyViolation):
        enforce_request([])  # type: ignore[arg-type]
