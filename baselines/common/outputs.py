"""Helpers for writing the five required output files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson


def write_baseline_outputs(
    output_dir: Path,
    *,
    final_proof_md: str,
    proof_graph: dict[str, Any],
    cited_sources: list[dict[str, Any]],
    self_critique_md: str,
    trace: list[dict[str, Any]],
) -> dict[str, Path]:
    """Write all five required files atomically and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "final_proof": output_dir / "final_proof.md",
        "proof_graph": output_dir / "proof_graph.json",
        "cited_sources": output_dir / "cited_sources.json",
        "self_critique": output_dir / "self_critique.md",
        "trace": output_dir / "trace.jsonl",
    }
    paths["final_proof"].write_text(final_proof_md, encoding="utf-8")
    paths["proof_graph"].write_bytes(orjson.dumps(proof_graph, option=orjson.OPT_INDENT_2))
    paths["cited_sources"].write_bytes(orjson.dumps(cited_sources, option=orjson.OPT_INDENT_2))
    paths["self_critique"].write_text(self_critique_md, encoding="utf-8")
    with paths["trace"].open("wb") as fh:
        for entry in trace:
            fh.write(orjson.dumps(entry))
            fh.write(b"\n")
    return paths
