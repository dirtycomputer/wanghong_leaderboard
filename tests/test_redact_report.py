"""Tests for the publication redactor.

The redactor is a security boundary: a slip means leaking gold-graph
content or the contamination phrase bank into the public
``submissions/`` tree. Every drop-list entry needs a test.
"""

from __future__ import annotations

import copy
from pathlib import Path

import orjson
import pytest

from scripts.redact_report import main as redact_main
from scripts.redact_report import redact_report

_FULL_REPORT = {
    "schema_version": "1.0",
    "evaluation_id": "eval-20260513T205411Z",
    "rubric_version": "kakeya3d-rubric-v0.1",
    "submission": {"path": "/tmp/x", "harness_name": "rag"},
    "subscores": {"protocol": 80, "gold_graph": 70, "correctness": 30},
    "weighted_score": 55.0,
    "applied_caps": [],
    "final_score": 55.0,
    "verdict": "FLAGGED",
    "judges": {
        "A": {
            "passed": True,
            "subscores": {"protocol": 100, "clarity": 100},
            "contamination_hits": [
                {"label": "phrase-x", "snippet": "secret match"},
            ],
        },
        "B": {
            "severity": "none",
            "post_cutoff_evidence_found": False,
            "recommended_action": "rank",
            "suspect_passages": [
                {"text_span": "contains a regex hint", "reason": "..."},
            ],
            "raw_text": "judge LLM full response with hints",
            "model": "frontier-judge",
        },
        "C": {
            "target_theorem_match": 85,
            "core_mechanism_match": 80,
            "lemma_chain_match": 75,
            "final_implication_match": 90,
            "overall_subscore": 82,
            "missing_gold_nodes": ["Prop 1.6", "Lemma 2.3"],
            "notes": "candidate is missing the convex-set volume bound...",
            "raw_text": "very long judge C reasoning that quotes the gold graph",
            "model": "frontier-judge",
        },
        "D": {
            "fatal_gap_found": True,
            "correctness_subscore": 30,
            "gap_resistance_subscore": 40,
            "first_fatal_gap": {"severity": "fatal", "location": "L1", "description": "..."},
            "raw_text": "verbose adversarial critique",
            "model": "frontier-judge",
        },
        "E": {
            "classification": "pre_cutoff_combination",
            "novelty_subscore": 20,
            "evidence": [{"description": "...", "url": "https://example.com"}],
            "raw_text": "lots of web search excerpts",
            "model": "frontier-judge",
        },
    },
    "judge_models": [
        {"role": "B_contamination", "model": "frontier-judge", "web_access": True},
    ],
}


def test_strips_judge_b_suspect_passages():
    out = redact_report(copy.deepcopy(_FULL_REPORT))
    assert "suspect_passages" not in out["judges"]["B"]


def test_strips_judge_c_missing_gold_nodes_and_notes():
    out = redact_report(copy.deepcopy(_FULL_REPORT))
    assert "missing_gold_nodes" not in out["judges"]["C"]
    assert "notes" not in out["judges"]["C"]


def test_strips_every_raw_text():
    out = redact_report(copy.deepcopy(_FULL_REPORT))
    for letter in "BCDE":
        assert "raw_text" not in out["judges"][letter], (
            f"judges.{letter}.raw_text survived redaction"
        )


def test_strips_judge_a_contamination_hits():
    out = redact_report(copy.deepcopy(_FULL_REPORT))
    assert "contamination_hits" not in out["judges"]["A"]


def test_keeps_scores_and_caps():
    out = redact_report(copy.deepcopy(_FULL_REPORT))
    assert out["final_score"] == 55.0
    assert out["verdict"] == "FLAGGED"
    assert out["subscores"]["protocol"] == 80
    # Judge sub-fields that the renderer actually uses must survive.
    assert out["judges"]["C"]["overall_subscore"] == 82
    assert out["judges"]["B"]["severity"] == "none"
    assert out["judges"]["D"]["fatal_gap_found"] is True
    assert out["judges"]["E"]["classification"] == "pre_cutoff_combination"
    assert out["judges"]["E"]["evidence"]  # public URLs are fine to keep
    assert out["judge_models"][0]["model"] == "frontier-judge"


def test_redact_is_idempotent():
    once = redact_report(copy.deepcopy(_FULL_REPORT))
    twice = redact_report(copy.deepcopy(once))
    assert once == twice


def test_redact_tolerates_missing_judges_block():
    skinny = {"evaluation_id": "x", "verdict": "RANKED"}
    out = redact_report(skinny)
    assert out == skinny


def test_redact_does_not_mutate_input():
    before = copy.deepcopy(_FULL_REPORT)
    redact_report(_FULL_REPORT)
    # Defensive: redactor must deepcopy so the operator's local
    # ``runs/`` tree stays unmodified.
    assert before == _FULL_REPORT


def test_cli_writes_redacted_report_to_out(tmp_path: Path):
    src = tmp_path / "evaluation_report.json"
    src.write_bytes(orjson.dumps(_FULL_REPORT))
    out = tmp_path / "published" / "deep" / "evaluation_report.json"
    rc = redact_main([str(src), "--out", str(out)])
    assert rc == 0
    written = orjson.loads(out.read_bytes())
    assert "raw_text" not in written["judges"]["B"]
    assert "missing_gold_nodes" not in written["judges"]["C"]


def test_cli_fails_on_missing_source(tmp_path: Path, capsys):
    rc = redact_main([str(tmp_path / "nope.json"), "--out", str(tmp_path / "x.json")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_cli_fails_on_non_json(tmp_path: Path, capsys):
    bad = tmp_path / "evaluation_report.json"
    bad.write_text("not JSON at all", encoding="utf-8")
    out = tmp_path / "out.json"
    rc = redact_main([str(bad), "--out", str(out)])
    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_fails_on_non_object_root(tmp_path: Path, capsys):
    arr = tmp_path / "evaluation_report.json"
    arr.write_bytes(orjson.dumps([1, 2, 3]))
    out = tmp_path / "out.json"
    rc = redact_main([str(arr), "--out", str(out)])
    assert rc == 1
    assert "JSON object" in capsys.readouterr().err


@pytest.mark.parametrize("letter", list("ABCDE"))
def test_judge_field_survives_when_only_some_keys_dropped(letter):
    """Each judge's public-facing subscores must survive redaction."""
    out = redact_report(copy.deepcopy(_FULL_REPORT))
    assert letter in out["judges"]
    assert out["judges"][letter], f"judges.{letter} ended up empty"
