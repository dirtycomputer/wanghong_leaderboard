"""Append-only JSONL audit log for the participant proxy.

Each model call is recorded as a single line so that reviewers can
later detect contamination, budget overruns and unexpected traffic
patterns. Sensitive fields (API keys, full prompt content) are not
logged here by default — only metadata. Prompts can be optionally
hashed via the ``hash_prompt`` helper for spot-check matching against
the contamination phrase bank.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import orjson


@dataclass
class AuditRecord:
    """A single proxy request/response audit entry."""

    request_id: str
    run_id: str
    harness_digest: str | None
    occurred_at: float = field(default_factory=time.time)
    direction: str = "request"  # "request" | "response" | "violation"
    model: str | None = None
    provider: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None
    latency_ms: int | None = None
    prompt_sha256: str | None = None
    violation: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class AuditLog:
    """Thread-safe append-only JSONL writer."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._path = self._dir / f"proxy-{time.strftime('%Y%m%d')}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: AuditRecord) -> None:
        line = orjson.dumps(asdict(record), option=orjson.OPT_APPEND_NEWLINE)
        with self._lock, self._path.open("ab") as fh:
            fh.write(line)

    def write_many(self, records: Iterable[AuditRecord]) -> None:
        for record in records:
            self.write(record)


def hash_prompt(messages: list[dict[str, Any]]) -> str:
    """Stable SHA-256 of the message list for cross-run matching.

    Hashes the serialised role/content pairs only, so that audit
    correlation can be done without persisting raw prompt text.
    """
    canonical = orjson.dumps(
        [{"role": m.get("role"), "content": m.get("content")} for m in messages],
        option=orjson.OPT_SORT_KEYS,
    )
    return hashlib.sha256(canonical).hexdigest()
