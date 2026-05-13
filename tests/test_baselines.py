"""Tests for the maintained reference baselines.

Every baseline is exercised against an in-memory ``FakeChat`` so no
real Gemma tokens are spent during CI. A tiny synthetic corpus is
written under ``tmp_path`` so retrieval-based baselines have something
to retrieve.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import orjson

from baselines import (
    agentic_self_critique,
    planner_verifier,
    rag_synthesis,
    zero_shot,
)
from baselines.common.context import BaselineContext
from baselines.common.corpus import load_corpus_manifest, retrieve_relevant_papers
from cli.kakeya_lb.schemas import PROOF_GRAPH_SCHEMA_PATH, validate_against
from runner.sandbox import validate_outputs


@dataclasses.dataclass
class FakeChat:
    """Replaces the OpenAI-compatible chat client with a scripted dialogue."""

    responses: list[str | dict]
    calls: int = 0

    def __call__(self, ctx, messages):
        idx = min(self.calls, len(self.responses) - 1) if self.responses else 0
        item = self.responses[idx] if self.responses else ""
        self.calls += 1
        text = item if isinstance(item, str) else item.get("text", "")
        prompt_tokens = item.get("prompt_tokens", 100) if isinstance(item, dict) else 100
        completion_tokens = (
            item.get("completion_tokens", 80) if isinstance(item, dict) else 80
        )
        return {
            "model": "google/gemma-4-31b-it",
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        }


def _ctx(tmp_path: Path, *, with_corpus: bool = False) -> BaselineContext:
    task = tmp_path / "task.yaml"
    task.write_text(
        "prompt: Make progress on the three-dimensional Kakeya conjecture.\n",
        encoding="utf-8",
    )
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    if with_corpus:
        papers = corpus / "papers"
        papers.mkdir()
        for arxiv_id, title, body in (
            ("1909.10973", "Polynomial method and Kakeya", "polynomial method Kakeya tube"),
            ("2003.12345", "Multilinear Kakeya estimates", "multilinear Kakeya tube broad norm"),
        ):
            paper_dir = papers / f"arxiv_{arxiv_id}"
            paper_dir.mkdir()
            (paper_dir / "full.md").write_text(body, encoding="utf-8")
            (corpus / "manifest.jsonl").open("ab").write(
                orjson.dumps(
                    {
                        "arxiv_id": arxiv_id,
                        "version": "v1",
                        "title": title,
                        "authors": ["A. Author"],
                        "markdown_path": str(paper_dir / "full.md"),
                    }
                )
                + b"\n"
            )
    output = tmp_path / "output"
    return BaselineContext(
        task_path=task,
        corpus_root=corpus,
        output_dir=output,
        model_api_base="http://fake/v1",
        model_api_key="fake-key",
    )


def _assert_outputs_valid(ctx: BaselineContext) -> dict[str, Any]:
    missing = validate_outputs(ctx.output_dir)
    assert missing == [], f"missing outputs: {missing}"
    graph = orjson.loads((ctx.output_dir / "proof_graph.json").read_bytes())
    errors = validate_against(graph, PROOF_GRAPH_SCHEMA_PATH)
    assert errors == [], errors
    return graph


# ----- zero_shot ------------------------------------------------------------


def test_zero_shot_emits_schema_valid_outputs(tmp_path: Path):
    ctx = _ctx(tmp_path)
    chat = FakeChat(["Single-shot answer with no leak."])
    summary = zero_shot.run(ctx, chat=chat)
    assert summary["baseline"] == "zero_shot"
    assert chat.calls == 1
    graph = _assert_outputs_valid(ctx)
    assert graph["new_lemmas"] == []  # survey-only baseline
    assert (ctx.output_dir / "final_proof.md").read_text(encoding="utf-8") == (
        "Single-shot answer with no leak."
    )


# ----- rag_synthesis --------------------------------------------------------


def test_rag_synthesis_retrieves_and_cites(tmp_path: Path):
    ctx = _ctx(tmp_path, with_corpus=True)
    chat = FakeChat(["Synthesis answer referencing multilinear Kakeya."])
    summary = rag_synthesis.run(ctx, chat=chat, top_k=2)
    assert summary["baseline"] == "rag_synthesis"
    assert chat.calls == 1
    graph = _assert_outputs_valid(ctx)
    cited = orjson.loads((ctx.output_dir / "cited_sources.json").read_bytes())
    # At least one of the two seeded papers should be retrieved.
    assert any(c["arxiv_id"].startswith(("1909", "2003")) for c in cited)
    assert graph["pre_cutoff_dependencies"], "RAG baseline should populate dependencies"


def test_rag_synthesis_handles_empty_corpus(tmp_path: Path):
    ctx = _ctx(tmp_path)  # no manifest
    chat = FakeChat(["Synthesis when retrieval is empty."])
    rag_synthesis.run(ctx, chat=chat)
    _assert_outputs_valid(ctx)


# ----- planner_verifier -----------------------------------------------------


def test_planner_verifier_calls_three_times_and_extracts_lemmas(tmp_path: Path):
    ctx = _ctx(tmp_path)
    plan_json = orjson.dumps(
        {
            "target_theorem": "dim_H(K) = 3",
            "new_lemmas": [
                {
                    "name": "L1",
                    "statement": "Tube volume bound",
                    "proof_status": "sketched",
                    "depends_on": [],
                    "used_for": ["final"],
                }
            ],
            "final_implication": "Therefore dim_H = 3.",
        }
    ).decode()
    critique = (
        "- you wave at the polynomial method without defining degree.\n"
        "- epsilon bookkeeping missing"
    )
    chat = FakeChat([plan_json, critique, plan_json])
    summary = planner_verifier.run(ctx, chat=chat)
    assert chat.calls == 3
    assert summary["new_lemmas_extracted"] == 1
    graph = _assert_outputs_valid(ctx)
    assert graph["new_lemmas"][0]["name"] == "L1"
    assert graph["new_lemmas"][0]["proof_status"] == "sketched"


def test_planner_verifier_normalises_unknown_status(tmp_path: Path):
    ctx = _ctx(tmp_path)
    bogus = orjson.dumps(
        {"new_lemmas": [{"name": "L1", "statement": "x", "proof_status": "DEFINITELY"}]}
    ).decode()
    chat = FakeChat([bogus, "critique", bogus])
    planner_verifier.run(ctx, chat=chat)
    graph = _assert_outputs_valid(ctx)
    # Unknown status is normalised to 'conjectural' (still schema-valid).
    assert graph["new_lemmas"][0]["proof_status"] == "conjectural"


def test_planner_verifier_survives_invalid_json(tmp_path: Path):
    ctx = _ctx(tmp_path)
    chat = FakeChat(["no JSON here at all", "no JSON either", "still nope"])
    planner_verifier.run(ctx, chat=chat)
    graph = _assert_outputs_valid(ctx)
    assert graph["new_lemmas"] == []


# ----- agentic_self_critique ------------------------------------------------


def test_agentic_self_critique_stops_when_critic_says_so(tmp_path: Path):
    ctx = _ctx(tmp_path, with_corpus=True)
    summary_json = orjson.dumps(
        {
            "target_theorem": "dim_H(K) = 3",
            "definitions": [{"name": "tube", "statement": "δ-thick line segment"}],
            "pre_cutoff_dependencies": [
                {"arxiv_id": "1909.10973v1", "claim": "polynomial method"}
            ],
            "new_lemmas": [
                {
                    "name": "L1",
                    "statement": "Tube volume bound",
                    "proof_status": "sketched",
                    "depends_on": [],
                    "used_for": ["final"],
                }
            ],
            "known_gaps": [
                {
                    "location": "L1",
                    "description": "constant suboptimal",
                    "severity": "moderate",
                }
            ],
            "final_implication": "dim_H = 3.",
        }
    ).decode()
    chat = FakeChat(
        [
            "Step 1 propose: bound the tube union volume.",
            orjson.dumps({"verdict": "stop", "weakness": "good enough"}).decode(),
            summary_json,
        ]
    )
    summary = agentic_self_critique.run(ctx, chat=chat, max_iterations=4, retrieve_k=2)
    # 1 propose + 1 critique + 1 summary = 3 calls; the stop verdict ends the loop.
    assert chat.calls == 3
    assert summary["iterations"] == 1
    graph = _assert_outputs_valid(ctx)
    assert graph["new_lemmas"][0]["name"] == "L1"
    assert any(d["arxiv_id"].startswith("1909") for d in graph["pre_cutoff_dependencies"])


def test_agentic_self_critique_falls_back_when_summary_garbled(tmp_path: Path):
    ctx = _ctx(tmp_path, with_corpus=True)
    # Critic continues forever (will hit max_iterations).
    cont = orjson.dumps({"verdict": "continue", "weakness": "more please"}).decode()
    chat = FakeChat(
        [
            "step A",
            cont,
            "step B",
            cont,
            "this is not JSON at all",  # bogus final summary
        ]
    )
    agentic_self_critique.run(ctx, chat=chat, max_iterations=2, retrieve_k=1)
    graph = _assert_outputs_valid(ctx)
    # No new_lemmas extracted; default fatal known_gap present.
    assert graph["new_lemmas"] == []
    assert any(g["severity"] == "fatal" for g in graph["known_gaps"])


# ----- corpus helper -------------------------------------------------------


def test_retrieve_relevant_papers_scores_by_overlap(tmp_path: Path):
    ctx = _ctx(tmp_path, with_corpus=True)
    entries = load_corpus_manifest(ctx.corpus_root)
    hits = retrieve_relevant_papers("multilinear Kakeya", entries, top_k=2)
    assert hits
    assert hits[0]["title"].startswith("Multilinear")


def test_retrieve_returns_empty_on_no_overlap(tmp_path: Path):
    ctx = _ctx(tmp_path, with_corpus=True)
    entries = load_corpus_manifest(ctx.corpus_root)
    assert retrieve_relevant_papers("unrelated topology nonsense", entries) == []
