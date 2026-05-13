"""Planner / Verifier two-agent loop.

Three Gemma calls:

1. **Planner** — emits a structured proof plan including candidate
   lemmas and their dependencies.
2. **Verifier** — hostile reviewer that lists weaknesses + missing
   quantifiers.
3. **Reviser** — re-runs the planner with the verifier critique in
   context to patch the plan.

The reviser's output is parsed as best-effort JSON to populate the
``proof_graph.new_lemmas`` array. If JSON parsing fails, the final
proof still ships but ``new_lemmas`` is empty (triggering the
survey-only cap, matching the zero-shot baseline's behaviour).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from baselines.common.chat import ChatFn, default_chat, extract_text
from baselines.common.context import BaselineContext, load_task
from baselines.common.outputs import write_baseline_outputs

_PLANNER_SYSTEM = (
    "You are a planner agent. Output a structured proof plan for the "
    "three-dimensional Kakeya set conjecture as STRICT JSON with the "
    "shape {target_theorem: string, new_lemmas: [{name, statement, "
    "proof_status, depends_on, used_for}], final_implication: string}. "
    "proof_status must be one of 'proved', 'sketched', 'conjectural'. "
    "Use only pre-2025-01-01 mathematical literature."
)

_VERIFIER_SYSTEM = (
    "You are a hostile mathematical verifier. Read the candidate plan "
    "and produce a bulleted markdown critique listing missing "
    "quantifiers, hand-waves, and unproved steps. Do not propose fixes."
)

_REVISER_SYSTEM = (
    "You are the planner agent revising your plan in light of the "
    "verifier's critique. Output the same STRICT JSON schema as before. "
    "Do not invent post-cutoff sources."
)

_FALLBACK_PROMPT = (
    "Make maximal progress on the three-dimensional Kakeya set conjecture. "
    "First produce a structured JSON plan."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def run(ctx: BaselineContext, *, chat: ChatFn | None = None) -> dict[str, Any]:
    task = load_task(ctx.task_path)
    base_prompt = str(task.get("prompt") or _FALLBACK_PROMPT)
    chat_fn = chat or default_chat

    trace: list[dict[str, Any]] = []

    # 1. Plan
    plan_text, plan_meta = _call(
        chat_fn,
        ctx,
        _PLANNER_SYSTEM,
        base_prompt,
        purpose="planner",
        trace=trace,
    )

    # 2. Verify
    critique, _ = _call(
        chat_fn,
        ctx,
        _VERIFIER_SYSTEM,
        f"Candidate plan:\n\n{plan_text}",
        purpose="verifier",
        trace=trace,
    )

    # 3. Revise
    revised_text, revised_meta = _call(
        chat_fn,
        ctx,
        _REVISER_SYSTEM,
        (
            f"Original plan:\n\n{plan_text}\n\n"
            f"Verifier critique:\n\n{critique}\n\n"
            "Now emit the revised JSON plan."
        ),
        purpose="reviser",
        trace=trace,
    )

    plan = _safe_parse_json(revised_text) or _safe_parse_json(plan_text) or {}
    new_lemmas = plan.get("new_lemmas") if isinstance(plan.get("new_lemmas"), list) else []
    new_lemmas = [_normalise_lemma(L) for L in new_lemmas if isinstance(L, dict)]

    final_proof_md = (
        "# Planner / Verifier baseline\n\n"
        "## Final plan (revised)\n\n"
        f"{revised_text}\n\n"
        "## Verifier critique\n\n"
        f"{critique}\n"
    )

    proof_graph = {
        "schema_version": "1.0",
        "target_theorem": str(
            plan.get("target_theorem")
            or "Every Kakeya set in R^3 has Minkowski and Hausdorff dimension 3."
        ),
        "definitions": [],
        "pre_cutoff_dependencies": [],
        "new_lemmas": new_lemmas,
        "known_gaps": [
            {
                "location": "planner_verifier",
                "description": (
                    "Two-agent loop emits a structured plan but does not "
                    "verify proof obligations against the corpus."
                ),
                "severity": "moderate",
            }
        ],
        "final_implication": str(
            plan.get("final_implication") or "Not derived from the corpus."
        ),
    }

    write_baseline_outputs(
        ctx.output_dir,
        final_proof_md=final_proof_md,
        proof_graph=proof_graph,
        cited_sources=[],
        self_critique_md=(
            "# Self critique\n\n"
            "Planner / verifier loop with three model calls. The revised "
            "plan may parse as JSON or not; the rubric's adversarial gap "
            "judge is the strict referee."
        ),
        trace=trace,
    )

    return {
        "baseline": "planner_verifier",
        "calls": 3,
        "new_lemmas_extracted": len(new_lemmas),
        "model": plan_meta.get("model") or revised_meta.get("model"),
    }


def _call(
    chat_fn: ChatFn,
    ctx: BaselineContext,
    system: str,
    user: str,
    *,
    purpose: str,
    trace: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    started = time.monotonic()
    completion = chat_fn(
        ctx,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    elapsed = time.monotonic() - started
    text = extract_text(completion)
    usage = completion.get("usage") or {}
    trace.append(
        {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "model_call",
            "purpose": purpose,
            "elapsed_seconds": round(elapsed, 3),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
    )
    return text, completion


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    candidates: list[str] = []
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(text.strip())
    obj_match = _FIRST_OBJ_RE.search(text)
    if obj_match:
        candidates.append(obj_match.group(1).strip())
    for cand in candidates:
        try:
            value = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


_VALID_STATUSES = {"proved", "sketched", "conjectural"}


def _normalise_lemma(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("proof_status") or "conjectural").lower()
    if status not in _VALID_STATUSES:
        status = "conjectural"
    depends = raw.get("depends_on")
    used = raw.get("used_for")
    return {
        "name": str(raw.get("name") or "unnamed"),
        "statement": str(raw.get("statement") or ""),
        "proof_status": status,
        "depends_on": [str(d) for d in depends] if isinstance(depends, list) else [],
        "used_for": [str(u) for u in used] if isinstance(used, list) else [],
    }
