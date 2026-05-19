"""Tests for Judge A (protocol)."""

from __future__ import annotations

from pathlib import Path

import orjson

from judge import a_protocol


def _write_valid_submission(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "final_proof.md").write_text("# proof", encoding="utf-8")
    (out / "self_critique.md").write_text("notes", encoding="utf-8")
    (out / "trace.jsonl").write_text("", encoding="utf-8")
    (out / "cited_sources.json").write_bytes(
        orjson.dumps([{"arxiv_id": "1909.10973v2", "claim": "polynomial method"}])
    )
    (out / "proof_graph.json").write_bytes(
        orjson.dumps(
            {
                "schema_version": "1.0",
                "target_theorem": "Every Kakeya set in R^3 has Hausdorff dimension 3.",
                "definitions": [],
                "pre_cutoff_dependencies": [
                    {"arxiv_id": "1909.10973v2", "claim": "polynomial method"}
                ],
                "new_lemmas": [
                    {
                        "name": "L1",
                        "statement": "Volume bound",
                        "proof_status": "sketched",
                        "depends_on": [],
                        "used_for": [],
                    }
                ],
                "known_gaps": [],
                "final_implication": "Therefore dim_H = 3.",
            }
        )
    )


def test_passes_for_well_formed_submission(tmp_path: Path):
    sub = tmp_path / "sub"
    _write_valid_submission(sub)
    result = a_protocol.run(sub)
    assert result.passed
    assert result.disqualifying_issues == []
    assert result.contamination_hits == []
    assert result.subscores["protocol"] == 100.0
    assert result.subscores["clarity"] == 100.0


def test_flags_missing_required_file(tmp_path: Path):
    sub = tmp_path / "sub"
    _write_valid_submission(sub)
    (sub / "final_proof.md").unlink()
    result = a_protocol.run(sub)
    assert not result.passed
    assert any("final_proof.md" in i for i in result.disqualifying_issues)
    assert any(c.cap == 0.0 for c in result.caps)


def test_detects_phrase_bank_contamination(tmp_path: Path):
    sub = tmp_path / "sub"
    _write_valid_submission(sub)
    (sub / "final_proof.md").write_text(
        "Following the result in arXiv:2502.17655 ...", encoding="utf-8"
    )
    result = a_protocol.run(sub)
    assert result.leak_evidence_count >= 1
    assert any("contaminated" in c.reason for c in result.caps)
    assert any(c.cap == 0.0 for c in result.caps)


def test_caps_survey_only_when_no_new_lemmas(tmp_path: Path):
    sub = tmp_path / "sub"
    _write_valid_submission(sub)
    graph = orjson.loads((sub / "proof_graph.json").read_bytes())
    graph["new_lemmas"] = []
    (sub / "proof_graph.json").write_bytes(orjson.dumps(graph))
    result = a_protocol.run(sub)
    assert any(c.reason.startswith("survey only") for c in result.caps)
