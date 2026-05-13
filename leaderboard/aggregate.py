"""Load and group ``evaluation_report.json`` files.

Reports may live in any directory tree under the configured root; the
aggregator recursively globs ``**/evaluation_report.json``.
Submissions are grouped by ``(harness_name, harness_version)``;
within each group, evaluations are sorted by ``created_at`` descending
so ``HarnessHistory.latest`` is always the freshest score.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import orjson


@dataclasses.dataclass(frozen=True)
class EvaluationRecord:
    """One ``evaluation_report.json`` file."""

    path: Path
    report: dict[str, Any]

    @property
    def harness_name(self) -> str:
        name = (self.report.get("submission") or {}).get("harness_name")
        if name:
            return str(name)
        # Fall back to the submission directory name. ``judge_submission``
        # writes the report next to the harness outputs, so the parent
        # directory of the report file IS the submission dir. This lets
        # the leaderboard separate baselines whose run_manifest.json
        # was not populated.
        parent = self.path.parent.name
        return parent or "unknown"

    @property
    def harness_version(self) -> str:
        return str(
            (self.report.get("submission") or {}).get("harness_version") or ""
        )

    @property
    def evaluation_id(self) -> str:
        return str(self.report.get("evaluation_id") or "")

    @property
    def rubric_version(self) -> str:
        return str(self.report.get("rubric_version") or "")

    @property
    def final_score(self) -> float:
        try:
            return float(self.report.get("final_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def weighted_score(self) -> float:
        try:
            return float(self.report.get("weighted_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def verdict(self) -> str:
        return str(self.report.get("verdict") or "FAILED").upper()

    @property
    def created_at(self) -> str:
        # judge_models[].created_at is not a thing; the orchestrator
        # records created_at on the EvalVersion. We expose it via the
        # report-level ``judge_models`` block when available, otherwise
        # fall back to evaluation_id (which contains a UTC timestamp).
        return self.evaluation_id or ""

    @property
    def applied_caps(self) -> list[dict[str, Any]]:
        caps = self.report.get("applied_caps") or []
        return [c for c in caps if isinstance(c, dict)]

    @property
    def is_contaminated(self) -> bool:
        if self.verdict in {"CONTAMINATED", "DISQUALIFIED"}:
            return True
        for cap in self.applied_caps:
            reason = str(cap.get("reason") or "").lower()
            if "contamin" in reason or "leak" in reason or "disqual" in reason:
                return True
        return False

    @property
    def harness_key(self) -> tuple[str, str]:
        return (self.harness_name, self.harness_version)


@dataclasses.dataclass(frozen=True)
class HarnessHistory:
    """All evaluations of one (harness_name, harness_version) tuple."""

    name: str
    version: str
    evaluations: tuple[EvaluationRecord, ...]  # newest first

    @property
    def latest(self) -> EvaluationRecord:
        return self.evaluations[0]


def load_reports(reports_root: Path) -> list[EvaluationRecord]:
    """Recursively load every ``evaluation_report.json`` under ``reports_root``."""
    records: list[EvaluationRecord] = []
    seen_ids: set[tuple[str, str, str]] = set()
    for path in sorted(reports_root.rglob("evaluation_report.json")):
        try:
            payload = orjson.loads(path.read_bytes())
        except orjson.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        rec = EvaluationRecord(path=path, report=payload)
        # Dedup by (harness_name, harness_version, evaluation_id).
        key = (rec.harness_name, rec.harness_version, rec.evaluation_id)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        records.append(rec)
    return records


def aggregate(records: Iterable[EvaluationRecord]) -> list[HarnessHistory]:
    """Group records by harness and sort each history newest-first.

    The returned list is sorted by ``HarnessHistory.latest.final_score``
    descending so the index page can iterate in display order.
    """
    grouped: dict[tuple[str, str], list[EvaluationRecord]] = {}
    for rec in records:
        grouped.setdefault(rec.harness_key, []).append(rec)

    histories: list[HarnessHistory] = []
    for (name, version), evals in grouped.items():
        evals.sort(key=lambda r: r.evaluation_id, reverse=True)
        histories.append(
            HarnessHistory(name=name, version=version, evaluations=tuple(evals))
        )
    histories.sort(
        key=lambda h: (h.latest.final_score, h.name),
        reverse=True,
    )
    return histories


def contamination_events(
    histories: Iterable[HarnessHistory],
) -> list[dict[str, Any]]:
    """Every evaluation (current OR historical) that triggered a leak / DQ cap."""
    events: list[dict[str, Any]] = []
    for h in histories:
        for ev in h.evaluations:
            if not ev.is_contaminated:
                continue
            events.append(
                {
                    "harness_name": ev.harness_name,
                    "harness_version": ev.harness_version,
                    "evaluation_id": ev.evaluation_id,
                    "verdict": ev.verdict,
                    "final_score": ev.final_score,
                    "cap_reasons": [
                        str(c.get("reason") or "") for c in ev.applied_caps
                    ],
                }
            )
    events.sort(key=lambda e: e["evaluation_id"], reverse=True)
    return events
