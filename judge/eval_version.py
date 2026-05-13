"""Versioning record attached to every evaluation report.

Updating the judge model, the gold proof graph, or the rubric must
not silently mutate historical scores. The :class:`EvalVersion`
captured at orchestration time records exactly which combination
produced a given final score, so the public leaderboard can show
``score@eval-2026-05-13-v1`` and keep older snapshots reachable.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from collections.abc import Iterable
from typing import Any


@dataclasses.dataclass(frozen=True)
class JudgeModelRecord:
    role: str
    model: str
    web_access: bool = False
    provider: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "model": self.model,
            "web_access": self.web_access,
            "provider": self.provider,
        }


@dataclasses.dataclass(frozen=True)
class EvalVersion:
    evaluation_id: str
    rubric_version: str
    gold_graph_hash: str | None
    target_paper_parse_hash: str | None
    judge_models: tuple[JudgeModelRecord, ...]
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "rubric_version": self.rubric_version,
            "gold_graph_hash": self.gold_graph_hash,
            "target_paper_parse_hash": self.target_paper_parse_hash,
            "created_at": self.created_at,
            "judge_models": [j.as_dict() for j in self.judge_models],
        }


def make_evaluation_id(prefix: str = "eval", now_utc: str | None = None) -> str:
    if now_utc is None:
        now_utc = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{prefix}-{now_utc}"


def hash_bytes(values: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for v in values:
        digest.update(v)
    return digest.hexdigest()
