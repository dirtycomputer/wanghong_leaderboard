"""Tests for the four LLM-backed judges (B / C / D / E).

The real ``JudgeClient`` is replaced by a fake so no HTTP is issued.
The fake records the messages it was given and returns a pre-canned
``JudgeResponse``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import orjson

from judge import b_contamination, c_gold_graph, d_adversarial, e_novelty
from judge.client import JudgeResponse


@dataclasses.dataclass
class FakeJudgeClient:
    payload: dict[str, Any] | list[Any]
    model: str = "fake-model"
    web_enabled: bool = False
    captured_messages: list[list[dict[str, Any]]] = dataclasses.field(default_factory=list)

    def chat(self, messages, *, expect_json=False, temperature=0.0, max_tokens=2048):
        self.captured_messages.append(messages)
        text = orjson.dumps(self.payload).decode("utf-8")
        return JudgeResponse(
            text=text,
            model=self.model,
            provider=None,
            finish_reason="stop",
            input_tokens=10,
            output_tokens=10,
            parsed_json=self.payload if expect_json else None,
            raw={},
        )


def _write_sub(tmp_path: Path) -> Path:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "final_proof.md").write_text("# proof", encoding="utf-8")
    (sub / "self_critique.md").write_text("ok", encoding="utf-8")
    (sub / "proof_graph.json").write_bytes(
        orjson.dumps({"schema_version": "1.0", "new_lemmas": []})
    )
    (sub / "cited_sources.json").write_bytes(orjson.dumps([]))
    (sub / "trace.jsonl").write_text("", encoding="utf-8")
    return sub


# ---------- Judge B ----------------------------------------------------------

def test_judge_b_marks_major_contamination_as_dq(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(
        payload={
            "post_cutoff_evidence_found": True,
            "severity": "major",
            "suspect_passages": [
                {"text_span": "...", "reason": "leak", "supporting_urls": ["https://x"]}
            ],
            "recommended_action": "disqualify",
            "protocol_subscore": 0,
        }
    )
    result = b_contamination.run(sub, client=client)
    assert result.post_cutoff_evidence_found is True
    assert any(c.cap == 0.0 for c in result.caps)
    assert any("contaminated" in c.reason for c in result.caps)


def test_judge_b_moderate_caps_at_medium(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(
        payload={
            "post_cutoff_evidence_found": True,
            "severity": "moderate",
            "suspect_passages": [],
            "recommended_action": "flag",
            "protocol_subscore": 60,
        }
    )
    result = b_contamination.run(sub, client=client)
    assert any(c.cap == 80.0 for c in result.caps)


def test_judge_b_inconclusive_on_non_dict(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(payload=[1, 2, 3])
    result = b_contamination.run(sub, client=client)
    assert result.severity == "unknown"


# ---------- Judge C ----------------------------------------------------------

def test_judge_c_averages_when_overall_zero(tmp_path: Path):
    sub = _write_sub(tmp_path)
    gold = tmp_path / "gold.json"
    gold.write_bytes(orjson.dumps({"schema_version": "1.0"}))
    client = FakeJudgeClient(
        payload={
            "target_theorem_match": 80,
            "core_mechanism_match": 60,
            "lemma_chain_match": 40,
            "final_implication_match": 80,
            "missing_gold_nodes": ["m1"],
            "possible_equivalent_new_route": False,
            "notes": "ok",
            "overall_subscore": 0,
        }
    )
    result = c_gold_graph.run(sub, client=client, gold_graph_path=gold)
    assert abs(result.overall_subscore - 65.0) < 1e-6
    assert result.missing_gold_nodes == ["m1"]


def test_judge_c_clamps_out_of_range(tmp_path: Path):
    sub = _write_sub(tmp_path)
    gold = tmp_path / "gold.json"
    gold.write_bytes(orjson.dumps({}))
    client = FakeJudgeClient(
        payload={
            "target_theorem_match": 200,
            "core_mechanism_match": -50,
            "lemma_chain_match": 10,
            "final_implication_match": 0,
            "overall_subscore": 999,
        }
    )
    result = c_gold_graph.run(sub, client=client, gold_graph_path=gold)
    assert result.target_theorem_match == 100.0
    assert result.core_mechanism_match == 0.0
    assert result.overall_subscore == 100.0


# ---------- Judge D ----------------------------------------------------------

def test_judge_d_caps_fatal_gap_at_70(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(
        payload={
            "fatal_gap_found": True,
            "first_fatal_gap": {
                "location": "L1",
                "description": "missing quantifier",
                "severity": "fatal",
            },
            "correctness_subscore": 30,
            "gap_resistance_subscore": 20,
            "notes": "",
        }
    )
    result = d_adversarial.run(sub, client=client)
    assert any(c.cap == 70.0 for c in result.caps)
    assert result.fatal_gap_found is True


def test_judge_d_major_severity_caps_at_65(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(
        payload={
            "fatal_gap_found": False,
            "first_fatal_gap": {
                "location": "L1",
                "description": "key lemma only sketched",
                "severity": "major",
            },
            "correctness_subscore": 55,
            "gap_resistance_subscore": 55,
        }
    )
    result = d_adversarial.run(sub, client=client)
    assert any(c.cap == 65.0 for c in result.caps)


def test_judge_d_clean_proof_has_no_caps(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(
        payload={
            "fatal_gap_found": False,
            "first_fatal_gap": None,
            "correctness_subscore": 92,
            "gap_resistance_subscore": 88,
        }
    )
    result = d_adversarial.run(sub, client=client)
    assert result.caps == []


# ---------- Judge E ----------------------------------------------------------

def test_judge_e_leak_is_dq(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(
        payload={
            "classification": "leak",
            "novelty_subscore": 5,
            "evidence": [{"description": "matches X", "url": "https://x"}],
        }
    )
    result = e_novelty.run(sub, client=client)
    assert result.classification == "leak"
    assert any(c.cap == 0.0 for c in result.caps)


def test_judge_e_defaults_novelty_when_missing(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(payload={"classification": "novel_route"})
    result = e_novelty.run(sub, client=client)
    assert result.novelty_subscore == 90.0
    assert result.classification == "novel_route"


def test_judge_e_unknown_class_maps_to_known(tmp_path: Path):
    sub = _write_sub(tmp_path)
    client = FakeJudgeClient(payload={"classification": "spectacular"})
    result = e_novelty.run(sub, client=client)
    assert result.classification == "known"
