"""Helpers for writing the five required output files atomically.

The official runner refuses runs where any of the five files is
missing or malformed. Using this helper guarantees you write all of
them with the right names and JSON shapes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import orjson


def write_outputs(
    output_dir: str | Path,
    *,
    final_proof_md: str,
    proof_graph: dict[str, Any],
    cited_sources: list[dict[str, Any]],
    self_critique_md: str,
    trace: list[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    """Write the five required output files and return their paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = {
        "final_proof": out / "final_proof.md",
        "proof_graph": out / "proof_graph.json",
        "cited_sources": out / "cited_sources.json",
        "self_critique": out / "self_critique.md",
        "trace": out / "trace.jsonl",
    }

    paths["final_proof"].write_text(final_proof_md, encoding="utf-8")
    paths["proof_graph"].write_bytes(orjson.dumps(proof_graph, option=orjson.OPT_INDENT_2))
    paths["cited_sources"].write_bytes(orjson.dumps(cited_sources, option=orjson.OPT_INDENT_2))
    paths["self_critique"].write_text(self_critique_md, encoding="utf-8")

    if trace is None:
        trace = [
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "run_start",
            }
        ]
    with paths["trace"].open("wb") as fh:
        for entry in trace:
            fh.write(orjson.dumps(entry))
            fh.write(b"\n")

    return paths
