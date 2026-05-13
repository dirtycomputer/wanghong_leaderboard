"""Tests for the shared baseline JSON-extraction helper."""

from __future__ import annotations

import pytest

from baselines.common.parse import (
    JSONExtractionError,
    extract_json,
    extract_object,
)


def test_extract_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_array():
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_from_fenced_block():
    assert extract_json('text\n```json\n{"x": 2}\n```\ntail') == {"x": 2}


def test_extract_object_returns_none_on_garbage():
    assert extract_object("definitely not JSON") is None


def test_extract_object_returns_none_on_non_dict():
    # extract_json would succeed on "[1,2]" but the convenience helper
    # only returns dicts; everything else is None.
    assert extract_object("[1, 2, 3]") is None


def test_extract_handles_latex_backslashes_in_strings():
    """The headline regression: Gemma writes ``\\mathbb{R}^3`` inside a
    JSON string and json.loads rejects ``\\m``. The helper retries
    after doubling stray backslashes so the original content survives.
    """
    text = (
        '```json\n{"target_theorem": "Kakeya in $\\mathbb{R}^3$ with '
        '$\\delta$-tubes"}\n```'
    )
    obj = extract_json(text)
    assert "mathbb" in obj["target_theorem"]
    assert "delta" in obj["target_theorem"]


def test_extract_raises_on_empty():
    with pytest.raises(JSONExtractionError):
        extract_json("")


def test_extract_raises_on_unparseable():
    with pytest.raises(JSONExtractionError):
        extract_json("the answer is forty two")
