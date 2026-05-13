"""Judge D — adversarial gap finder.

A hostile mathematical referee whose only job is to find the *first*
fatal gap. The prompt demands precise quantifiers, scale dependencies
and epsilon bookkeeping; the judge is told *not* to reward
plausibility. Severity of the worst gap maps to a rubric cap (cap-70
for ``fatal``, cap-65 for ``major``).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import orjson

from judge.client import JudgeClient, JudgeError
from judge.rubric import CAPS, Cap

_SYSTEM_PROMPT = (
    "You are a hostile mathematical referee. Assume every claim is wrong "
    "until every implication is justified. Read the candidate's proof of "
    "the three-dimensional Kakeya conjecture and locate the *first* fatal "
    "gap. Demand precise quantifiers, scale dependencies, epsilon "
    "bookkeeping, and explicit handling of exceptional configurations. Do "
    "not reward plausibility. Return STRICT JSON, no commentary."
)

_RESPONSE_SCHEMA_HINT = """
Return JSON with this shape:
{
  "fatal_gap_found": boolean,
  "first_fatal_gap": {
    "location": string,
    "description": string,
    "severity": "minor" | "moderate" | "major" | "fatal"
  } | null,
  "correctness_subscore": integer in [0,100],
  "gap_resistance_subscore": integer in [0,100],
  "notes": string
}
""".strip()

_MAX_EXCERPT_BYTES = 24_000


@dataclasses.dataclass
class JudgeDResult:
    fatal_gap_found: bool
    first_fatal_gap: dict[str, Any] | None
    correctness_subscore: float
    gap_resistance_subscore: float
    notes: str
    caps: list[Cap]
    raw_text: str
    model: str

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["caps"] = [c.as_dict() for c in self.caps]
        return d


def run(submission_dir: Path, *, client: JudgeClient) -> JudgeDResult:
    submission_dir = Path(submission_dir)
    proof = _read(submission_dir / "final_proof.md")
    graph = _read(submission_dir / "proof_graph.json")

    user_msg = (
        "Find the first fatal gap in the candidate's proof. If no fatal "
        "gap exists, still demand precision and report sub-fatal weaknesses. "
        "Return JSON only.\n\n"
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
            max_tokens=2048,
        )
    except JudgeError:
        return _inconclusive(client.model)

    parsed = response.parsed_json
    if not isinstance(parsed, dict):
        return _inconclusive(client.model, raw_text=response.text)

    fatal = bool(parsed.get("fatal_gap_found"))
    gap = parsed.get("first_fatal_gap")
    if not isinstance(gap, dict):
        gap = None
    severity = str((gap or {}).get("severity") or "minor").lower()

    correctness = _clamp(parsed.get("correctness_subscore"))
    resistance = _clamp(parsed.get("gap_resistance_subscore"))

    caps: list[Cap] = []
    if fatal and severity == "fatal":
        caps.append(
            Cap(
                reason="fatal mathematical gap identified by judge D",
                cap=CAPS.FATAL_GAP,
                source="judge_d_adversarial",
            )
        )
    elif severity == "major":
        caps.append(
            Cap(
                reason="major (sub-fatal) gap identified by judge D",
                cap=CAPS.KEY_LEMMA_UNPROVED,
                source="judge_d_adversarial",
            )
        )

    return JudgeDResult(
        fatal_gap_found=fatal,
        first_fatal_gap=gap,
        correctness_subscore=correctness,
        gap_resistance_subscore=resistance,
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


def _inconclusive(model: str, *, raw_text: str = "") -> JudgeDResult:
    return JudgeDResult(
        fatal_gap_found=False,
        first_fatal_gap=None,
        correctness_subscore=0.0,
        gap_resistance_subscore=0.0,
        notes="judge D inconclusive — LLM call failed or returned non-JSON",
        caps=[],
        raw_text=raw_text,
        model=model,
    )
