"""Judge B — contamination audit with web search.

Reads the submission's free-text outputs, asks the judge LLM (with the
web plugin enabled) to detect phrases / lemmas / citations that appear
to come from sources submitted after the time-capsule cutoff. The
output severity is mapped to a rubric cap.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from judge.client import JudgeClient, JudgeError
from judge.rubric import CAPS, Cap

_SYSTEM_PROMPT = (
    "You are a hostile contamination auditor for the Wang Hong leaderboard. "
    "Submissions must rely *only* on sources submitted to arXiv before "
    "2025-01-01 00:00:00 GMT. Use your web search ability to verify whether "
    "the submission's phrases, lemmas, attributions, or citations leak "
    "post-cutoff information (especially arXiv:2502.17655 by Hong Wang and "
    "Joshua Zahl, 'Volume estimates for unions of convex sets, and the "
    "Kakeya set conjecture in three dimensions'). Do not be fooled by "
    "plausible-sounding pre-cutoff vocabulary alone; require concrete "
    "evidence (URLs) for each finding. Return STRICT JSON, no commentary."
)

_RESPONSE_SCHEMA_HINT = """
Return JSON with this shape:
{
  "post_cutoff_evidence_found": boolean,
  "severity": "none" | "minor" | "moderate" | "major",
  "suspect_passages": [
    {
      "text_span": string,
      "reason": string,
      "supporting_urls": [string]
    }
  ],
  "recommended_action": "rank" | "flag" | "contaminated_not_ranked" | "disqualify",
  "protocol_subscore": integer in [0,100]
}
""".strip()

_MAX_EXCERPT_BYTES = 12_000


@dataclasses.dataclass
class JudgeBResult:
    post_cutoff_evidence_found: bool
    severity: str
    suspect_passages: list[dict[str, Any]]
    recommended_action: str
    protocol_subscore: float
    caps: list[Cap]
    raw_text: str
    model: str

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["caps"] = [c.as_dict() for c in self.caps]
        return d


def run(submission_dir: Path, *, client: JudgeClient) -> JudgeBResult:
    submission_dir = Path(submission_dir)
    excerpts = {
        "final_proof.md": _read(submission_dir / "final_proof.md"),
        "self_critique.md": _read(submission_dir / "self_critique.md"),
        "proof_graph.json": _read(submission_dir / "proof_graph.json"),
        "cited_sources.json": _read(submission_dir / "cited_sources.json"),
    }
    user_msg = (
        "Audit the following submission for post-cutoff contamination. "
        "Look for: arXiv IDs newer than 2025-01-01, paper titles that match "
        "post-cutoff publications, attributions of the 3D Kakeya proof to "
        "specific 2025 authors, and lemma statements whose first appearance "
        "you can locate is post-cutoff.\n\n"
        + _RESPONSE_SCHEMA_HINT
        + "\n\n"
        + "\n\n".join(f"### {name}\n{content}" for name, content in excerpts.items())
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

    severity = str(parsed.get("severity") or "none").lower()
    found = bool(parsed.get("post_cutoff_evidence_found"))
    action = str(parsed.get("recommended_action") or "rank")
    suspect = parsed.get("suspect_passages") or []
    if not isinstance(suspect, list):
        suspect = []
    subscore = float(parsed.get("protocol_subscore", 100 if not found else 0))
    subscore = max(0.0, min(100.0, subscore))

    caps: list[Cap] = []
    if found and severity == "major":
        caps.append(
            Cap(
                reason="contaminated: judge B reports major post-cutoff evidence",
                cap=CAPS.DQ_VALUE,
                source="judge_b_contamination",
            )
        )
    elif found and severity == "moderate":
        caps.append(
            Cap(
                reason="flagged: judge B reports moderate post-cutoff risk",
                cap=CAPS.MEDIUM_CONTAMINATION_RISK,
                source="judge_b_contamination",
            )
        )
    if action in {"contaminated_not_ranked", "disqualify"}:
        caps.append(
            Cap(
                reason=f"judge B recommended action: {action}",
                cap=CAPS.DQ_VALUE,
                source="judge_b_contamination",
            )
        )

    return JudgeBResult(
        post_cutoff_evidence_found=found,
        severity=severity,
        suspect_passages=suspect,
        recommended_action=action,
        protocol_subscore=subscore,
        caps=caps,
        raw_text=response.text,
        model=response.model,
    )


def _read(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > _MAX_EXCERPT_BYTES:
        return data[:_MAX_EXCERPT_BYTES] + "\n…(truncated)…"
    return data


def _inconclusive(model: str, *, raw_text: str = "") -> JudgeBResult:
    """Safe default when the LLM call or parse fails."""
    return JudgeBResult(
        post_cutoff_evidence_found=False,
        severity="unknown",
        suspect_passages=[],
        recommended_action="rank",
        protocol_subscore=50.0,
        caps=[
            Cap(
                reason="judge B inconclusive — LLM call failed or returned non-JSON",
                cap=100.0,  # non-binding cap, just for audit trail
                source="judge_b_contamination",
            )
        ],
        raw_text=raw_text,
        model=model,
    )
