"""Tests for the judge OpenRouter client and JSON extraction."""

from __future__ import annotations

import pytest

from judge.client import JudgeError, _extract_json


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
