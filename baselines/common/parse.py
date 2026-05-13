"""Tolerant JSON extraction for baseline + judge LLM outputs.

The participant baselines and the judge stack both ask the model to
emit strict JSON, but math-domain outputs routinely contain things
like ``$\\mathbb{R}^3$`` or ``$\\delta$-tube`` inside JSON string
values, which ``json.loads`` rejects because ``\\m`` / ``\\d`` are not
valid JSON escapes. This module first tries the model's text verbatim
(including fenced code blocks and the first top-level object inside a
larger reply); if every candidate fails, it re-tries after doubling
stray backslashes.
"""

from __future__ import annotations

import json
import re
from typing import Any


class JSONExtractionError(ValueError):
    """Raised when no JSON object/array can be recovered from the text."""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_FIRST_JSON_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)
# A backslash NOT followed by a legal JSON escape character. Doubling
# these lets json.loads decode the original string content unchanged.
_BAD_JSON_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction. Returns the parsed object or raises."""
    if not text:
        raise JSONExtractionError("empty text")

    candidates: list[str] = []
    fenced = _JSON_FENCE_RE.search(text)
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
    raise JSONExtractionError(f"could not parse JSON: {last_err}")


def extract_object(text: str) -> dict[str, Any] | None:
    """Return the parsed JSON if it is a dict, otherwise None.

    Convenience wrapper used by the baselines, which only consume
    object-shaped responses and prefer ``None`` over an exception when
    the model produces something unparseable.
    """
    try:
        value = extract_json(text)
    except JSONExtractionError:
        return None
    return value if isinstance(value, dict) else None
