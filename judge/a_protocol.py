"""Judge A — pure-program protocol & contamination check.

Runs entirely offline. Its decisions are deterministic and form the
hard floor of the rubric: if Judge A returns ``disqualifying_issues``,
the submission cannot be ranked regardless of how well the other
judges score it.

Checks
------
1. All five required output files are present.
2. ``proof_graph.json`` validates against
   ``schemas/proof_graph.schema.json``.
3. ``cited_sources.json`` validates against
   ``schemas/cited_sources.schema.json``.
4. ``run_manifest.json`` (if present) validates against its schema.
5. The phrase bank used by the Gemma canary is replayed against the
   final proof / proof graph / self critique; matches surface as
   contamination evidence.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

import orjson

from judge.rubric import CAPS, Cap
from runner.sandbox import REQUIRED_OUTPUTS
from runner.schema_utils import (
    PROOF_GRAPH_SCHEMA_PATH,
    RUN_MANIFEST_SCHEMA_PATH,
    validate_against,
)

CITED_SOURCES_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "cited_sources.schema.json"
)

# Phrase bank mirrors scripts/canary_prompts.yaml; if these phrases
# appear anywhere in the submission's free text we treat them as a
# direct leak of the target paper.
_LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("target_arxiv_id", re.compile(r"\b2502\.17655\b")),
    (
        "target_title",
        re.compile(
            r"(?i)volume\s+estimates?\s+for\s+unions?\s+of\s+convex\s+sets",
        ),
    ),
    (
        "wang_zahl_hyphen",
        re.compile(r"(?i)\bWang[\-–]Zahl\b"),
    ),
]

# Files we scan for the phrase bank (free-text fields the harness can
# write into).
_SCAN_BASENAMES: tuple[str, ...] = (
    "final_proof.md",
    "self_critique.md",
    "proof_graph.json",
)


@dataclasses.dataclass
class JudgeAResult:
    passed: bool
    disqualifying_issues: list[str]
    warnings: list[str]
    contamination_hits: list[dict[str, Any]]
    leak_evidence_count: int
    files_present: list[str]
    files_missing: list[str]
    subscores: dict[str, float]
    caps: list[Cap]

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["caps"] = [c.as_dict() for c in self.caps]
        return d


def run(submission_dir: Path) -> JudgeAResult:
    """Execute Judge A against a submission directory."""
    submission_dir = Path(submission_dir)
    issues: list[str] = []
    warnings: list[str] = []
    hits: list[dict[str, Any]] = []
    files_present: list[str] = []
    files_missing: list[str] = []
    caps: list[Cap] = []

    # 1. File presence
    for name in REQUIRED_OUTPUTS:
        if (submission_dir / name).exists():
            files_present.append(name)
        else:
            files_missing.append(name)
            issues.append(f"missing required output {name!r}")

    proof_graph_path = submission_dir / "proof_graph.json"
    proof_graph_obj: dict[str, Any] | None = None
    if proof_graph_path.exists():
        proof_graph_obj, errs = _validate_json(
            proof_graph_path, PROOF_GRAPH_SCHEMA_PATH
        )
        for e in errs:
            issues.append(f"proof_graph.json schema: {e}")

    cited_path = submission_dir / "cited_sources.json"
    if cited_path.exists():
        cited_loaded, errs = _validate_json(cited_path, CITED_SOURCES_SCHEMA_PATH)
        for e in errs:
            issues.append(f"cited_sources.json schema: {e}")

    run_manifest_path = submission_dir / "run_manifest.json"
    if run_manifest_path.exists():
        _, errs = _validate_json(run_manifest_path, RUN_MANIFEST_SCHEMA_PATH)
        for e in errs:
            issues.append(f"run_manifest.json schema: {e}")

    # 2. Phrase-bank scan across free-text outputs
    for name in _SCAN_BASENAMES:
        path = submission_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in _LEAK_PATTERNS:
            for m in pattern.finditer(text):
                hits.append(
                    {
                        "file": name,
                        "label": label,
                        "pattern": pattern.pattern,
                        "snippet": text[max(0, m.start() - 30): m.end() + 30],
                    }
                )

    # 3. Survey-only detection (cap, not DQ)
    if proof_graph_obj is not None and isinstance(
        proof_graph_obj.get("new_lemmas"), list
    ) and not proof_graph_obj["new_lemmas"]:
        caps.append(
            Cap(
                reason="survey only — no new_lemmas in proof_graph.json",
                cap=CAPS.SURVEY_ONLY,
                source="judge_a_protocol",
            )
        )

    # 4. DQ caps
    if hits:
        caps.append(
            Cap(
                reason=(
                    "contaminated: target paper id / title / Wang-Zahl phrase "
                    "appears in submission text"
                ),
                cap=CAPS.DQ_VALUE,
                source="judge_a_protocol",
            )
        )
        issues.append(
            f"phrase-bank contamination matches: {len(hits)}"
        )
    if files_missing:
        caps.append(
            Cap(
                reason=f"missing required outputs: {', '.join(files_missing)}",
                cap=CAPS.DQ_VALUE,
                source="judge_a_protocol",
            )
        )

    # Soft hint: schema errors should not silently fail the run, but
    # they suppress the clarity sub-score.
    clarity = 100.0 if not files_missing and not issues else 0.0
    protocol = 100.0 if not issues else 0.0

    return JudgeAResult(
        passed=not issues,
        disqualifying_issues=issues,
        warnings=warnings,
        contamination_hits=hits,
        leak_evidence_count=len(hits),
        files_present=files_present,
        files_missing=files_missing,
        subscores={"protocol": protocol, "clarity": clarity},
        caps=caps,
    )


def _validate_json(path: Path, schema_path: Path) -> tuple[Any | None, list[str]]:
    try:
        loaded = orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError as exc:
        return None, [f"invalid JSON ({exc})"]
    errs = validate_against(loaded, schema_path)
    return loaded, errs
