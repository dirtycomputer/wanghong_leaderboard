"""Tests for the full judge orchestrator."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import orjson

from judge.client import JudgeResponse
from judge.orchestrator import OrchestratorClients, evaluate
from runner.schema_utils import validate_against

EVAL_REPORT_SCHEMA = (
    Path(__file__).resolve().parents[1] / "schemas" / "evaluation_report.schema.json"
)


@dataclasses.dataclass
class FakeClient:
    payloads: list[Any]
    model: str = "fake-judge"
    web_enabled: bool = False
    calls: int = 0

    def chat(self, messages, *, expect_json=False, temperature=0.0, max_tokens=2048):
        payload = self.payloads[self.calls % len(self.payloads)]
        self.calls += 1
        return JudgeResponse(
            text=orjson.dumps(payload).decode("utf-8"),
            model=self.model,
            provider=None,
            finish_reason="stop",
            input_tokens=10,
            output_tokens=10,
            parsed_json=payload if expect_json else None,
            raw={},
        )


def _write_sub(tmp_path: Path) -> Path:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "final_proof.md").write_text("# proof", encoding="utf-8")
    (sub / "self_critique.md").write_text("ok", encoding="utf-8")
    (sub / "trace.jsonl").write_text("", encoding="utf-8")
    (sub / "cited_sources.json").write_bytes(
        orjson.dumps([{"arxiv_id": "1909.10973v2", "claim": "polynomial method"}])
    )
    (sub / "proof_graph.json").write_bytes(
        orjson.dumps(
            {
                "schema_version": "1.0",
                "target_theorem": "dim_H(K) = 3",
                "definitions": [],
                "pre_cutoff_dependencies": [
                    {"arxiv_id": "1909.10973v2", "claim": "polynomial method"}
                ],
                "new_lemmas": [
                    {
                        "name": "L1",
                        "statement": "Volume bound",
                        "proof_status": "proved",
                        "depends_on": [],
                        "used_for": [],
                    }
                ],
                "known_gaps": [],
                "final_implication": "dim_H = 3.",
            }
        )
    )
    return sub


def _write_gold(tmp_path: Path) -> Path:
    gold = tmp_path / "gold_graph.json"
    gold.write_bytes(orjson.dumps({"schema_version": "1.0", "new_lemmas": []}))
    return gold


# B, C, D, E payloads used for a "clean" pass.
_GOOD_PAYLOADS = {
    "B": {
        "post_cutoff_evidence_found": False,
        "severity": "none",
        "suspect_passages": [],
        "recommended_action": "rank",
        "protocol_subscore": 100,
    },
    "C": {
        "target_theorem_match": 85,
        "core_mechanism_match": 80,
        "lemma_chain_match": 75,
        "final_implication_match": 90,
        "missing_gold_nodes": [],
        "possible_equivalent_new_route": False,
        "notes": "",
        "overall_subscore": 82,
    },
    "D": {
        "fatal_gap_found": False,
        "first_fatal_gap": None,
        "correctness_subscore": 80,
        "gap_resistance_subscore": 80,
    },
    "E": {
        "classification": "pre_cutoff_combination",
        "novelty_subscore": 55,
        "evidence": [],
    },
}


def test_orchestrator_clean_run_produces_ranked_verdict(tmp_path: Path):
    sub = _write_sub(tmp_path)
    gold = _write_gold(tmp_path)
    web = FakeClient(payloads=[_GOOD_PAYLOADS["B"], _GOOD_PAYLOADS["E"]])
    offline = FakeClient(payloads=[_GOOD_PAYLOADS["C"], _GOOD_PAYLOADS["D"]])
    report = evaluate(
        sub,
        clients=OrchestratorClients(web_client=web, offline_client=offline),
        gold_graph_path=gold,
    )
    assert report["verdict"] == "RANKED"
    assert report["applied_caps"] == []
    assert report["final_score"] == report["weighted_score"]
    assert report["judge_models"][0]["role"] == "A_protocol"


def test_orchestrator_short_circuits_when_judge_a_dq(tmp_path: Path):
    sub = _write_sub(tmp_path)
    (sub / "final_proof.md").write_text(
        "Following arXiv:2502.17655 ...", encoding="utf-8"
    )
    gold = _write_gold(tmp_path)
    web = FakeClient(payloads=[{"never": "called"}])
    offline = FakeClient(payloads=[{"never": "called"}])
    report = evaluate(
        sub,
        clients=OrchestratorClients(web_client=web, offline_client=offline),
        gold_graph_path=gold,
    )
    # Judge A's DQ cap should short-circuit B-E so the fake clients
    # are never invoked.
    assert web.calls == 0
    assert offline.calls == 0
    assert report["verdict"] in {"CONTAMINATED", "DISQUALIFIED"}
    assert report["final_score"] == 0.0


def test_orchestrator_applies_d_fatal_gap_cap(tmp_path: Path):
    sub = _write_sub(tmp_path)
    gold = _write_gold(tmp_path)
    bad_d = {
        "fatal_gap_found": True,
        "first_fatal_gap": {
            "location": "L1",
            "description": "broken induction",
            "severity": "fatal",
        },
        "correctness_subscore": 60,
        "gap_resistance_subscore": 30,
    }
    web = FakeClient(payloads=[_GOOD_PAYLOADS["B"], _GOOD_PAYLOADS["E"]])
    offline = FakeClient(payloads=[_GOOD_PAYLOADS["C"], bad_d])
    report = evaluate(
        sub,
        clients=OrchestratorClients(web_client=web, offline_client=offline),
        gold_graph_path=gold,
    )
    caps = [c["reason"] for c in report["applied_caps"]]
    assert any("fatal" in r for r in caps)
    assert report["final_score"] <= 70.0
    assert report["verdict"] == "FLAGGED"


def test_orchestrator_verdict_flagged_when_cap_is_non_binding(tmp_path: Path):
    """A submission that scores below a non-binding cap is still FLAGGED."""
    sub = _write_sub(tmp_path)
    gold = _write_gold(tmp_path)
    # Judge D reports a fatal gap (cap=70) but the underlying axes
    # are weak enough that the weighted score is below 70.
    bad_d = {
        "fatal_gap_found": True,
        "first_fatal_gap": {
            "location": "X",
            "description": "broken",
            "severity": "fatal",
        },
        "correctness_subscore": 5,
        "gap_resistance_subscore": 5,
    }
    web = FakeClient(payloads=[_GOOD_PAYLOADS["B"], _GOOD_PAYLOADS["E"]])
    offline = FakeClient(payloads=[_GOOD_PAYLOADS["C"], bad_d])
    report = evaluate(
        sub,
        clients=OrchestratorClients(web_client=web, offline_client=offline),
        gold_graph_path=gold,
    )
    assert report["weighted_score"] < 70.0
    # Cap was non-binding, so applied_caps is empty, but verdict still flags.
    assert report["applied_caps"] == []
    assert report["verdict"] == "FLAGGED"


def test_orchestrator_output_matches_schema(tmp_path: Path):
    sub = _write_sub(tmp_path)
    gold = _write_gold(tmp_path)
    web = FakeClient(payloads=[_GOOD_PAYLOADS["B"], _GOOD_PAYLOADS["E"]])
    offline = FakeClient(payloads=[_GOOD_PAYLOADS["C"], _GOOD_PAYLOADS["D"]])
    report = evaluate(
        sub,
        clients=OrchestratorClients(web_client=web, offline_client=offline),
        gold_graph_path=gold,
    )
    errors = validate_against(report, EVAL_REPORT_SCHEMA)
    assert errors == [], errors
