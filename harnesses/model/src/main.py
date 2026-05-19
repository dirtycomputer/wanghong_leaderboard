from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import yaml

from src.model_client import chat, extract_text
from src.write_outputs import write_outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    task = yaml.safe_load(args.task.read_text(encoding="utf-8")) or {}
    prompt = task.get(
        "prompt",
        "State and outline a proof strategy for the three-dimensional Kakeya set "
        "conjecture using only allowed model access.",
    )
    system = Path("prompts/system.md").read_text(encoding="utf-8")

    started = time.monotonic()
    completion = chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
    )
    elapsed = time.monotonic() - started
    answer = extract_text(completion)
    usage = completion.get("usage") or {}

    write_outputs(
        args.output,
        final_proof_md=answer or "No response was produced.",
        proof_graph={
            "schema_version": "1.0",
            "target_theorem": "Every Kakeya set in R^3 has Minkowski and Hausdorff dimension 3.",
            "definitions": [],
            "pre_cutoff_dependencies": [],
            "new_lemmas": [],
            "known_gaps": [
                {
                    "location": "model",
                    "description": "Single model-call harness; no structured lemma chain was established.",
                    "severity": "fatal",
                }
            ],
            "final_implication": "Not derived by the model harness.",
        },
        cited_sources=[],
        self_critique_md="# Self critique\n\nSingle-call model harness; expected to leave fatal gaps.",
        trace=[
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "model_call",
                "elapsed_seconds": round(elapsed, 3),
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            }
        ],
        run_manifest={
            "harness_name": "model",
            "harness_version": "0.1.0",
            "harness_kind": "model",
            "restricted_search": {"enabled": False},
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
