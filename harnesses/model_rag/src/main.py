from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import yaml

from src.model_client import chat, extract_text
from src.search_client import restricted_search
from src.write_outputs import write_outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    task = yaml.safe_load(args.task.read_text(encoding="utf-8")) or {}
    prompt = task.get("prompt", "Make progress on the three-dimensional Kakeya set conjecture.")
    search_results = restricted_search(str(prompt), max_results=5)
    context = "\n\n".join(
        f"### {r.get('title')}\n{r.get('url')}\n" + "\n".join(r.get("highlights") or [])[:1200]
        for r in search_results
    )
    system = Path("prompts/system.md").read_text(encoding="utf-8")
    user = f"{prompt}\n\nRestricted pre-cutoff search context:\n\n{context or '(none)'}"

    started = time.monotonic()
    completion = chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=2048,
    )
    elapsed = time.monotonic() - started
    answer = extract_text(completion)
    usage = completion.get("usage") or {}

    cited_sources = [
        {
            "arxiv_id": r["arxiv_id"],
            "claim": "returned by restricted search",
            "where_used": "model_rag context",
        }
        for r in search_results
        if r.get("arxiv_id")
    ]
    write_outputs(
        args.output,
        final_proof_md=answer or "No response was produced.",
        proof_graph={
            "schema_version": "1.0",
            "target_theorem": "Every Kakeya set in R^3 has Minkowski and Hausdorff dimension 3.",
            "definitions": [],
            "pre_cutoff_dependencies": cited_sources,
            "new_lemmas": [],
            "known_gaps": [
                {
                    "location": "model_rag",
                    "description": (
                        "Restricted-search RAG context was used, "
                        "but no proof chain was verified."
                    ),
                    "severity": "fatal",
                }
            ],
            "final_implication": "Not derived by the model_rag harness.",
        },
        cited_sources=cited_sources,
        self_critique_md=(
            "# Self critique\n\nRAG context was retrieved, but the proof remains unverified."
        ),
        trace=[
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "restricted_search",
                "returned": len(search_results),
            },
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "model_call",
                "elapsed_seconds": round(elapsed, 3),
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            },
        ],
        run_manifest={
            "harness_name": "model_rag",
            "harness_version": "0.1.0",
            "harness_kind": "model_rag",
            "restricted_search": {
                "enabled": True,
                "provider": "exa",
                "cutoff": os.environ.get("SEARCH_CUTOFF", "2025-01-01T00:00:00Z"),
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
