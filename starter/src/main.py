"""Starter baseline harness — replace with your approach.

This baseline:
1. Reads the task description from ``--task``.
2. Sends a single chat completion through the leaderboard proxy.
3. Writes the five required output files.

It is intentionally simple so you can verify the plumbing locally with
``kakeya-lb smoke-run .`` before iterating on retrieval, planning,
proof search and self-critique.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml

from src.model_client import chat, extract_text
from src.write_outputs import write_outputs

SYSTEM_PROMPT = (
    "You are a mathematical research agent operating with knowledge "
    "available before 2025-01-01. Make maximal progress on the "
    "three-dimensional Kakeya set conjecture using only the provided "
    "corpus and your own reasoning. Do not invent post-cutoff sources."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-api-base", type=str)
    parser.add_argument("--model-api-key", type=str)
    args = parser.parse_args()

    task = yaml.safe_load(args.task.read_text(encoding="utf-8")) or {}
    user_prompt = task.get(
        "prompt",
        "State and outline a proof strategy for the three-dimensional Kakeya set conjecture, "
        "citing only the provided corpus.",
    )

    started = time.monotonic()
    completion = chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
    elapsed = time.monotonic() - started
    answer = extract_text(completion)

    write_outputs(
        args.output,
        final_proof_md=answer or "No response was produced.",
        proof_graph={
            "schema_version": "1.0",
            "target_theorem": (
                "Every Kakeya set in R^3 has Minkowski and Hausdorff dimension 3."
            ),
            "definitions": [],
            "pre_cutoff_dependencies": [],
            "new_lemmas": [],
            "known_gaps": [
                {
                    "location": "starter",
                    "description": (
                        "Baseline emits a free-text response without a structured "
                        "lemma chain; replace this harness to populate the proof graph."
                    ),
                    "severity": "fatal",
                }
            ],
            "final_implication": "Not derived by the starter harness.",
        },
        cited_sources=[],
        self_critique_md=(
            "# Self critique\n\n"
            "Starter harness emits a single free-text response and reports a fatal gap. "
            "Replace `src/main.py` with your own pipeline."
        ),
        trace=[
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "model_call",
                "elapsed_seconds": round(elapsed, 3),
                "purpose": "starter baseline single-shot",
            }
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
