"""Agentic search + self-critique baseline (budget-bounded loop).

Per iteration:
1. Retrieve fresh corpus excerpts informed by the running notes.
2. Propose the next *step* of the proof (one lemma or strategic move).
3. Self-critique the proposal; on ``stop`` verdict, exit.

After the loop, ask the agent to write up a final proof + structured
proof graph. The budget caps both the number of iterations and the
total tokens recorded in ``trace.jsonl``.
"""

from __future__ import annotations

import re
import time
from typing import Any

from baselines.common.chat import ChatFn, default_chat, extract_text
from baselines.common.context import BaselineContext, load_task
from baselines.common.corpus import (
    load_corpus_manifest,
    retrieve_relevant_papers,
)
from baselines.common.outputs import write_baseline_outputs
from baselines.common.parse import extract_object

_AGENT_SYSTEM = (
    "You are a mathematical research agent operating with knowledge "
    "available before 2025-01-01. You may rely only on the supplied "
    "corpus excerpts and your own reasoning. Be precise about "
    "quantifiers and the role of each lemma in proving the "
    "three-dimensional Kakeya set conjecture."
)

_CRITIC_SYSTEM = (
    "You are a hostile self-critic. Inspect the previous step and "
    "respond with STRICT JSON {verdict: 'continue' | 'stop', "
    "weakness: string}. Return 'stop' once additional iterations are "
    "unlikely to help."
)

_WRITER_SYSTEM = (
    "You are summarising an agentic proof attempt. Emit STRICT JSON "
    "with the proof graph shape: target_theorem, definitions, "
    "pre_cutoff_dependencies (list of {arxiv_id, claim}), new_lemmas "
    "(list of {name, statement, proof_status, depends_on, used_for}), "
    "known_gaps (list of {location, description, severity}), "
    "final_implication. proof_status must be one of "
    "'proved', 'sketched', 'conjectural'."
)

_FALLBACK_PROMPT = (
    "Make maximal progress on the three-dimensional Kakeya set "
    "conjecture using only the provided pre-cutoff corpus."
)

_VALID_STATUSES = {"proved", "sketched", "conjectural"}
_VALID_SEVERITY = {"minor", "moderate", "fatal"}


def run(
    ctx: BaselineContext,
    *,
    chat: ChatFn | None = None,
    max_iterations: int = 4,
    retrieve_k: int = 3,
) -> dict[str, Any]:
    task = load_task(ctx.task_path)
    base_prompt = str(task.get("prompt") or _FALLBACK_PROMPT)
    chat_fn = chat or default_chat
    corpus_entries = load_corpus_manifest(ctx.corpus_root)

    trace: list[dict[str, Any]] = []
    running_notes: list[str] = []
    citations_seen: dict[str, dict[str, Any]] = {}

    for i in range(max_iterations):
        query = base_prompt + "\n" + "\n".join(running_notes[-2:])
        retrieved = retrieve_relevant_papers(query, corpus_entries, top_k=retrieve_k)
        for r in retrieved:
            key = r["arxiv_id"]
            if key and key not in citations_seen:
                citations_seen[key] = {
                    "arxiv_id": (
                        f"{r['arxiv_id']}{r.get('version','')}"
                        if r.get("version") else r["arxiv_id"]
                    ),
                    "claim": "retrieved by agentic search loop",
                    "where_used": f"iteration {i}",
                }
        rag_block = _format_rag(retrieved)

        step_text, _ = _call(
            chat_fn,
            ctx,
            _AGENT_SYSTEM,
            (
                f"Goal: {base_prompt}\n\n"
                f"Previous steps:\n{chr(10).join(running_notes) or '(none yet)'}\n\n"
                f"Corpus excerpts:\n{rag_block}\n\n"
                "Propose the NEXT proof step. Be precise; describe "
                "exactly one lemma or strategic move."
            ),
            purpose=f"iteration_{i}_propose",
            trace=trace,
        )
        running_notes.append(f"Step {i+1}: {step_text}")

        critic_text, _ = _call(
            chat_fn,
            ctx,
            _CRITIC_SYSTEM,
            f"Most recent step:\n{step_text}",
            purpose=f"iteration_{i}_critique",
            trace=trace,
        )
        critic = extract_object(critic_text) or {}
        verdict = str(critic.get("verdict") or "continue").lower()
        running_notes.append(f"Critic ({verdict}): {critic.get('weakness') or ''}")
        if verdict == "stop":
            break

    summary_text, summary_meta = _call(
        chat_fn,
        ctx,
        _WRITER_SYSTEM,
        "Steps so far:\n" + "\n".join(running_notes),
        purpose="final_summary",
        trace=trace,
    )

    graph_raw = extract_object(summary_text) or {}
    proof_graph = _normalise_graph(graph_raw, citations_seen)

    final_proof_md = (
        "# Agentic self-critique baseline\n\n"
        "## Steps + critiques\n\n"
        + "\n\n".join(running_notes)
        + "\n\n## Final summary\n\n"
        + summary_text
    )
    write_baseline_outputs(
        ctx.output_dir,
        final_proof_md=final_proof_md,
        proof_graph=proof_graph,
        cited_sources=list(citations_seen.values()),
        self_critique_md=(
            "# Self critique\n\n"
            "Iterative loop with retrieval, propose, critique. The final "
            "summary call produces the proof_graph. Without expert review "
            "it is still expected to leave fatal gaps in the proof chain."
        ),
        trace=trace,
    )
    return {
        "baseline": "agentic_self_critique",
        "iterations": len([t for t in trace if "propose" in (t.get("purpose") or "")]),
        "new_lemmas_extracted": len(proof_graph["new_lemmas"]),
        "cited_sources": len(citations_seen),
        "model": summary_meta.get("model"),
    }


def _format_rag(retrieved: list[dict[str, Any]]) -> str:
    if not retrieved:
        return "(corpus retrieval returned nothing)"
    chunks = []
    for r in retrieved:
        chunks.append(
            f"### arXiv:{r['arxiv_id']}{r.get('version','')} — {r['title']}\n"
            f"{r['excerpt'][:800]}\n"
        )
    return "\n".join(chunks)


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


def _normalise_graph(
    raw: dict[str, Any], citations_seen: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    new_lemmas_raw = raw.get("new_lemmas") if isinstance(raw.get("new_lemmas"), list) else []
    new_lemmas: list[dict[str, Any]] = []
    for L in new_lemmas_raw:
        if not isinstance(L, dict):
            continue
        status = str(L.get("proof_status") or "conjectural").lower()
        if status not in _VALID_STATUSES:
            status = "conjectural"
        depends = L.get("depends_on")
        used = L.get("used_for")
        new_lemmas.append(
            {
                "name": str(L.get("name") or "unnamed"),
                "statement": str(L.get("statement") or ""),
                "proof_status": status,
                "depends_on": [str(d) for d in depends] if isinstance(depends, list) else [],
                "used_for": [str(u) for u in used] if isinstance(used, list) else [],
            }
        )

    pre_cutoff_raw = raw.get("pre_cutoff_dependencies") or []
    pre_cutoff: list[dict[str, Any]] = []
    arxiv_re = re.compile(r"^[0-9]{4}\.[0-9]{4,5}(v[0-9]+)?$")
    for d in pre_cutoff_raw if isinstance(pre_cutoff_raw, list) else []:
        if not isinstance(d, dict):
            continue
        aid = str(d.get("arxiv_id") or "").replace("arXiv:", "").strip()
        if not arxiv_re.match(aid):
            continue
        pre_cutoff.append(
            {
                "arxiv_id": aid,
                "claim": str(d.get("claim") or ""),
                **({"where_used": str(d["where_used"])} if d.get("where_used") else {}),
            }
        )
    if not pre_cutoff:
        # Fall back to whatever the retrieval surfaced.
        pre_cutoff = [
            {"arxiv_id": v["arxiv_id"].split("v", 1)[0], "claim": v["claim"]}
            for v in citations_seen.values()
        ]

    known_gaps_raw = raw.get("known_gaps") or []
    known_gaps: list[dict[str, Any]] = []
    for g in known_gaps_raw if isinstance(known_gaps_raw, list) else []:
        if not isinstance(g, dict):
            continue
        sev = str(g.get("severity") or "moderate").lower()
        if sev not in _VALID_SEVERITY:
            sev = "moderate"
        known_gaps.append(
            {
                "location": str(g.get("location") or "unspecified"),
                "description": str(g.get("description") or ""),
                "severity": sev,
            }
        )
    if not known_gaps:
        known_gaps = [
            {
                "location": "agentic_self_critique",
                "description": (
                    "Final summary did not enumerate gaps; default fatal entry "
                    "applied to keep the schema honest."
                ),
                "severity": "fatal",
            }
        ]

    return {
        "schema_version": "1.0",
        "target_theorem": str(
            raw.get("target_theorem")
            or "Every Kakeya set in R^3 has Minkowski and Hausdorff dimension 3."
        ),
        "definitions": _normalise_defs(raw.get("definitions")),
        "pre_cutoff_dependencies": pre_cutoff,
        "new_lemmas": new_lemmas,
        "known_gaps": known_gaps,
        "final_implication": str(
            raw.get("final_implication") or "Not derived; baseline only sketches."
        ),
    }


def _normalise_defs(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "").strip()
        statement = str(d.get("statement") or "").strip()
        if name and statement:
            out.append({"name": name, "statement": statement})
    return out
