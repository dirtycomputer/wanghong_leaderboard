from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import orjson


def write_outputs(
    output_dir: Path,
    *,
    final_proof_md: str,
    proof_graph: dict[str, Any],
    cited_sources: list[dict[str, Any]],
    self_critique_md: str,
    trace: list[dict[str, Any]],
    run_manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "final_proof.md").write_text(final_proof_md, encoding="utf-8")
    (output_dir / "proof_graph.json").write_bytes(
        orjson.dumps(proof_graph, option=orjson.OPT_INDENT_2)
    )
    (output_dir / "cited_sources.json").write_bytes(
        orjson.dumps(cited_sources, option=orjson.OPT_INDENT_2)
    )
    (output_dir / "self_critique.md").write_text(self_critique_md, encoding="utf-8")
    with (output_dir / "trace.jsonl").open("wb") as fh:
        for entry in trace:
            fh.write(orjson.dumps(entry))
            fh.write(b"\n")
    manifest = {
        "schema_version": "1.0",
        "model": "google/gemma-4-31b-it",
        "outputs": {
            "final_proof": "final_proof.md",
            "proof_graph": "proof_graph.json",
            "cited_sources": "cited_sources.json",
            "self_critique": "self_critique.md",
            "trace": "trace.jsonl",
        },
        "wall_time_seconds": 0,
        "num_model_calls": len([t for t in trace if t.get("event") == "model_call"]),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **run_manifest,
    }
    (output_dir / "run_manifest.json").write_bytes(
        orjson.dumps(manifest, option=orjson.OPT_INDENT_2)
    )
