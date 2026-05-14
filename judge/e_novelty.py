"""Judge E — open-world novelty audit.

Classifies the submission by querying the wider mathematical literature
(via the OpenRouter web plugin). Possible classifications and the
implied novelty sub-score:

* ``leak`` — appears to reproduce the target paper without citing
  post-cutoff sources; sets a contamination flag for the orchestrator.
* ``known`` — restatement of well-known pre-cutoff results.
* ``pre_cutoff_combination`` — a non-trivial but unsurprising
  combination of existing techniques.
* ``novel_route`` — a plausibly new strategy, distinct from the gold
  graph but consistent with pre-cutoff knowledge.
* ``wrong`` — substantive mathematical errors not already flagged by
  judge D.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import orjson

from judge.client import JudgeClient, JudgeError
from judge.rubric import CAPS, Cap

_SYSTEM_PROMPT = (
    "You are an open-world novelty referee for the Wang Hong leaderboard. "
    "Use your web access to compare the submission against publicly known "
    "approaches to the three-dimensional Kakeya conjecture. Classify the "
    "submission as one of: leak | known | pre_cutoff_combination | "
    "novel_route | wrong. Reward genuine independence; penalise rephrased "
    "post-cutoff content even if no exact title is cited. Return STRICT "
    "JSON, no commentary."
)

_RESPONSE_SCHEMA_HINT = """
Return JSON with this shape:
{
  "classification": "leak" | "known" | "pre_cutoff_combination" | "novel_route" | "wrong",
  "novelty_subscore": integer in [0,100],
  "evidence": [
    {"description": string, "url": string}
  ],
  "notes": string
}
""".strip()

_MAX_EXCERPT_BYTES = 14_000

_BASE_NOVELTY: dict[str, float] = {
    "leak": 0.0,
    "wrong": 10.0,
    "known": 25.0,
    "pre_cutoff_combination": 55.0,
    "novel_route": 90.0,
}


@dataclasses.dataclass
class JudgeEResult:
    classification: str
    novelty_subscore: float
    evidence: list[dict[str, Any]]
    notes: str
    caps: list[Cap]
    raw_text: str
    model: str

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["caps"] = [c.as_dict() for c in self.caps]
        return d


def run(submission_dir: Path, *, client: JudgeClient) -> JudgeEResult:
    submission_dir = Path(submission_dir)
    proof = _read(submission_dir / "final_proof.md")
    graph = _read(submission_dir / "proof_graph.json")

    user_msg = (
        "Classify the submission and report supporting evidence URLs.\n\n"
        + _RESPONSE_SCHEMA_HINT
        + "\n\n### final_proof.md\n"
        + proof
        + "\n\n### proof_graph.json\n"
        + graph
    )

    try:
        response = client.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            expect_json=True,
            temperature=0.0,
        )
    except JudgeError:
        return _inconclusive(client.model)

    parsed = response.parsed_json
    if not isinstance(parsed, dict):
        return _inconclusive(client.model, raw_text=response.text)

    classification = str(parsed.get("classification") or "known").lower()
    if classification not in _BASE_NOVELTY:
        classification = "known"
    declared = parsed.get("novelty_subscore")
    novelty = _BASE_NOVELTY[classification] if declared is None else _clamp(declared)

    evidence = parsed.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = []

    caps: list[Cap] = []
    if classification == "leak":
        caps.append(
            Cap(
                reason="contaminated: judge E classified submission as a leak",
                cap=CAPS.DQ_VALUE,
                source="judge_e_novelty",
            )
        )

    return JudgeEResult(
        classification=classification,
        novelty_subscore=novelty,
        evidence=[e for e in evidence if isinstance(e, dict)],
        notes=str(parsed.get("notes") or ""),
        caps=caps,
        raw_text=response.text,
        model=response.model,
    )


def _read(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    if path.suffix == ".json":
        try:
            obj = orjson.loads(path.read_bytes())
        except orjson.JSONDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
        data = orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode("utf-8")
    else:
        data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > _MAX_EXCERPT_BYTES:
        return data[:_MAX_EXCERPT_BYTES] + "\n…(truncated)…"
    return data


def _clamp(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, v))


def _inconclusive(model: str, *, raw_text: str = "") -> JudgeEResult:
    return JudgeEResult(
        classification="unknown",
        novelty_subscore=0.0,
        evidence=[],
        notes="judge E inconclusive — LLM call failed or returned non-JSON",
        caps=[],
        raw_text=raw_text,
        model=model,
    )
