"""Zero-shot single-prompt baseline.

The simplest possible reference harness. One Gemma call. No retrieval.
No planning. Produces schema-valid output but with empty
``new_lemmas`` — Judge A applies the survey-only cap (≤45) and the
adversarial gap finder is expected to fault the proof.
"""

from __future__ import annotations

import time
from typing import Any

from baselines.common.chat import ChatFn, default_chat, extract_text
from baselines.common.context import BaselineContext, load_task
from baselines.common.outputs import write_baseline_outputs

_SYSTEM_PROMPT = (
    "You are a mathematical research agent operating with knowledge "
    "available before 2025-01-01. Make maximal progress on the "
    "three-dimensional Kakeya set conjecture using only the supplied "
    "corpus and your own reasoning. Do not invent post-cutoff sources."
)

_FALLBACK_USER_PROMPT = (
    "State and outline a proof strategy for the three-dimensional "
    "Kakeya set conjecture. Cite only the supplied corpus."
)


def run(ctx: BaselineContext, *, chat: ChatFn | None = None) -> dict[str, Any]:
    """Run the zero-shot baseline and write the five output files."""
    task = load_task(ctx.task_path)
    user_prompt = str(task.get("prompt") or _FALLBACK_USER_PROMPT)

    chat_fn = chat or default_chat

    started = time.monotonic()
    completion = chat_fn(
        ctx,
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    elapsed = time.monotonic() - started
    answer = extract_text(completion)
    usage = completion.get("usage") or {}

    proof_graph = {
        "schema_version": "1.0",
        "target_theorem": (
            "Every Kakeya set in R^3 has Minkowski and Hausdorff dimension 3."
        ),
        "definitions": [],
        "pre_cutoff_dependencies": [],
        "new_lemmas": [],
        "known_gaps": [
            {
                "location": "zero_shot",
                "description": (
                    "Single-shot baseline; emits free-text output without a "
                    "structured lemma chain."
                ),
                "severity": "fatal",
            }
        ],
        "final_implication": "Not derived by the zero-shot baseline.",
    }
    trace = [
        {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "model_call",
            "purpose": "zero_shot synthesis",
            "elapsed_seconds": round(elapsed, 3),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
    ]
    write_baseline_outputs(
        ctx.output_dir,
        final_proof_md=answer or "No response was produced.",
        proof_graph=proof_graph,
        cited_sources=[],
        self_critique_md=(
            "# Self critique\n\n"
            "Zero-shot baseline emits a single free-text response and reports "
            "a fatal gap. Expected to fail the rubric's survey-only cap (≤45)."
        ),
        trace=trace,
    )
    return {
        "baseline": "zero_shot",
        "elapsed_seconds": elapsed,
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "model": completion.get("model"),
    }
