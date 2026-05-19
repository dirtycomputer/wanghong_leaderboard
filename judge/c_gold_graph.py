"""Judge C — gold proof graph alignment.

The hidden gold graph lives in ``judge/vault/<task>/gold_graph.json`` (an
LLM-extracted artefact for the MVP, hand-vetted before P5). Judge C
compares the submission's ``proof_graph.json`` against it across four
structural axes and returns per-axis match scores plus an aggregate.

This judge is *not* given web access — it must reason from the
submitted graph + free text + the gold graph alone.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import orjson

from judge.client import JudgeClient, JudgeError
from judge.rubric import Cap

_SYSTEM_PROMPT = (
    "You are a mathematical reviewer comparing a candidate proof graph "
    "against a hidden gold proof graph for the three-dimensional Kakeya "
    "conjecture. Score per-axis alignment in [0,100]. A high lemma_chain "
    "score requires that the candidate's lemmas cover the gold graph's "
    "central mechanisms; mere vocabulary overlap is not sufficient. If "
    "the candidate takes a *different but plausible* route, say so under "
    "possible_equivalent_new_route and avoid penalising it on lemma "
    "matching alone. Return STRICT JSON, no commentary."
)

_RESPONSE_SCHEMA_HINT = """
Return JSON with this shape:
{
  "target_theorem_match": integer in [0,100],
  "core_mechanism_match": integer in [0,100],
  "lemma_chain_match": integer in [0,100],
  "final_implication_match": integer in [0,100],
  "missing_gold_nodes": [string],
  "possible_equivalent_new_route": boolean,
  "notes": string,
  "overall_subscore": integer in [0,100]
}
""".strip()

_MAX_EXCERPT_BYTES = 18_000


@dataclasses.dataclass
class JudgeCResult:
    target_theorem_match: float
    core_mechanism_match: float
    lemma_chain_match: float
    final_implication_match: float
    missing_gold_nodes: list[str]
    possible_equivalent_new_route: bool
    notes: str
    overall_subscore: float
    caps: list[Cap]
    raw_text: str
    model: str

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["caps"] = [c.as_dict() for c in self.caps]
        return d


def run(
    submission_dir: Path,
    *,
    client: JudgeClient,
    gold_graph_path: Path,
) -> JudgeCResult:
    submission_dir = Path(submission_dir)
    gold = _read(gold_graph_path)
    submitted = _read(submission_dir / "proof_graph.json")
    proof = _read(submission_dir / "final_proof.md")

    user_msg = (
        "Compare the candidate's proof graph against the gold graph "
        "across four axes and return a JSON object.\n\n"
        + _RESPONSE_SCHEMA_HINT
        + "\n\n### gold_graph.json\n"
        + gold
        + "\n\n### candidate proof_graph.json\n"
        + submitted
        + "\n\n### candidate final_proof.md (excerpt)\n"
        + proof
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

    target = _clamp(parsed.get("target_theorem_match"))
    core = _clamp(parsed.get("core_mechanism_match"))
    chain = _clamp(parsed.get("lemma_chain_match"))
    final = _clamp(parsed.get("final_implication_match"))
    overall = _clamp(parsed.get("overall_subscore"))
    if overall == 0.0 and any(v > 0 for v in (target, core, chain, final)):
        overall = (target + core + chain + final) / 4.0

    missing = parsed.get("missing_gold_nodes") or []
    if not isinstance(missing, list):
        missing = []

    return JudgeCResult(
        target_theorem_match=target,
        core_mechanism_match=core,
        lemma_chain_match=chain,
        final_implication_match=final,
        missing_gold_nodes=[str(m) for m in missing],
        possible_equivalent_new_route=bool(parsed.get("possible_equivalent_new_route")),
        notes=str(parsed.get("notes") or ""),
        overall_subscore=overall,
        caps=[],
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


def _inconclusive(model: str, *, raw_text: str = "") -> JudgeCResult:
    return JudgeCResult(
        target_theorem_match=0.0,
        core_mechanism_match=0.0,
        lemma_chain_match=0.0,
        final_implication_match=0.0,
        missing_gold_nodes=[],
        possible_equivalent_new_route=False,
        notes="judge C inconclusive — LLM call failed or returned non-JSON",
        overall_subscore=0.0,
        caps=[],
        raw_text=raw_text,
        model=model,
    )
