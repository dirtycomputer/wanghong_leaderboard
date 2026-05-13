"""Literature-RAG + single synthesis baseline.

1. Load ``corpus/manifest.jsonl`` from the read-only corpus mount.
2. Score every paper by keyword overlap against the task prompt.
3. Stuff the top-``k`` (title + first ~1500 chars of the MinerU
   markdown) into a single Gemma prompt as RAG context.
4. Emit a free-text proof and a ``cited_sources.json`` that references
   exactly the retrieved arXiv IDs.
"""

from __future__ import annotations

import time
from typing import Any

from baselines.common.chat import ChatFn, default_chat, extract_text
from baselines.common.context import BaselineContext, load_task
from baselines.common.corpus import (
    load_corpus_manifest,
    retrieve_relevant_papers,
)
from baselines.common.outputs import write_baseline_outputs

_SYSTEM_PROMPT = (
    "You are a mathematical research agent. Use ONLY the attached "
    "corpus excerpts and your own reasoning to make progress on the "
    "three-dimensional Kakeya set conjecture. Cite each claim by its "
    "arXiv id. Do not reference any post-2025-01-01 source."
)

_FALLBACK_USER_PROMPT = (
    "Using only the corpus excerpts below, outline a proof strategy for the "
    "three-dimensional Kakeya set conjecture and identify the strongest "
    "available pre-cutoff techniques."
)


def run(
    ctx: BaselineContext,
    *,
    chat: ChatFn | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    task = load_task(ctx.task_path)
    base_prompt = str(task.get("prompt") or _FALLBACK_USER_PROMPT)

    entries = load_corpus_manifest(ctx.corpus_root)
    retrieved = retrieve_relevant_papers(base_prompt, entries, top_k=top_k)

    rag_block = _build_rag_block(retrieved)
    user_prompt = f"{base_prompt}\n\n## Retrieved corpus excerpts\n\n{rag_block}"

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

    cited_sources = [
        {
            "arxiv_id": (
                f"{r['arxiv_id']}{r.get('version') or ''}"
                if r.get("version")
                else r["arxiv_id"]
            ),
            "claim": "retrieved as RAG context for the synthesis prompt",
            "where_used": "rag_synthesis context block",
        }
        for r in retrieved
    ]
    proof_graph = {
        "schema_version": "1.0",
        "target_theorem": (
            "Every Kakeya set in R^3 has Minkowski and Hausdorff dimension 3."
        ),
        "definitions": [],
        "pre_cutoff_dependencies": cited_sources,
        "new_lemmas": [],
        "known_gaps": [
            {
                "location": "rag_synthesis",
                "description": (
                    "Synthesis baseline reuses retrieved excerpts without "
                    "introducing new lemmas or proof structure."
                ),
                "severity": "fatal",
            }
        ],
        "final_implication": (
            "Not derived: baseline only restates the retrieved literature."
        ),
    }
    trace = [
        {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "retrieval",
            "top_k": top_k,
            "returned": len(retrieved),
        },
        {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "model_call",
            "purpose": "rag synthesis",
            "elapsed_seconds": round(elapsed, 3),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        },
    ]
    write_baseline_outputs(
        ctx.output_dir,
        final_proof_md=answer or "No response was produced.",
        proof_graph=proof_graph,
        cited_sources=cited_sources,
        self_critique_md=(
            "# Self critique\n\n"
            "RAG-synthesis baseline performs a single keyword retrieval and "
            "one Gemma synthesis call. It does not introduce new lemmas, so "
            "the rubric's survey-only cap (≤45) is expected to bind."
        ),
        trace=trace,
    )
    return {
        "baseline": "rag_synthesis",
        "elapsed_seconds": elapsed,
        "retrieved": len(retrieved),
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "model": completion.get("model"),
    }


def _build_rag_block(retrieved: list[dict[str, Any]]) -> str:
    if not retrieved:
        return "(no corpus papers matched the query)"
    chunks = []
    for r in retrieved:
        authors = ", ".join(r.get("authors") or [])
        chunks.append(
            f"### arXiv:{r['arxiv_id']}{r.get('version','')} — {r['title']}\n"
            f"_Authors: {authors}_\n\n"
            f"{r['excerpt']}\n"
        )
    return "\n".join(chunks)
