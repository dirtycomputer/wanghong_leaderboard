"""Maintained reference harnesses for the Wang Hong leaderboard.

Each baseline is a small Python module that produces the five
required output files (``final_proof.md``, ``proof_graph.json``,
``cited_sources.json``, ``self_critique.md``, ``trace.jsonl``) using
the participant API surface (``MODEL_API_BASE`` + ``MODEL_API_KEY``
proxy, read-only ``/corpus``). They are designed so the same code
runs:

* as a maintained reference score (``python -m scripts.run_baseline
  --baseline rag_synthesis --task ... --corpus ...``)
* inside the official Docker sandbox (build with the starter
  ``Dockerfile`` and point ``run.sh`` at ``baselines.<name>``)
* under unit tests (each ``run`` accepts an injected ``chat`` and a
  fake-model fixture under ``tests/test_baselines.py``)
"""

from baselines import (
    agentic_self_critique,
    planner_verifier,
    rag_synthesis,
    zero_shot,
)
from baselines.common.context import BaselineContext

REGISTRY: dict[str, callable] = {
    "zero_shot": zero_shot.run,
    "rag_synthesis": rag_synthesis.run,
    "planner_verifier": planner_verifier.run,
    "agentic_self_critique": agentic_self_critique.run,
}

__all__ = [
    "BaselineContext",
    "REGISTRY",
    "agentic_self_critique",
    "planner_verifier",
    "rag_synthesis",
    "zero_shot",
]
