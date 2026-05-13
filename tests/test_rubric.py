"""Tests for the rubric (weighted score + caps)."""

from __future__ import annotations

from judge.rubric import (
    CAPS,
    WEIGHTS,
    Cap,
    apply_rubric,
    verdict_from,
    weighted_score,
)


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_weighted_score_clamps_per_axis():
    score = weighted_score(
        {
            "protocol": 200,
            "gold_graph": -10,
            "correctness": 50,
            "gap_resistance": 50,
            "novelty": 50,
            "clarity": 50,
        }
    )
    # protocol clamps to 100, gold_graph to 0; remaining axes are 50.
    rest_weight = (
        WEIGHTS["correctness"]
        + WEIGHTS["gap_resistance"]
        + WEIGHTS["novelty"]
        + WEIGHTS["clarity"]
    )
    expected = (
        WEIGHTS["protocol"] * 100
        + WEIGHTS["gold_graph"] * 0
        + rest_weight * 50
    )
    assert abs(score - expected) < 1e-9


def test_apply_rubric_no_caps():
    subscores = {axis: 80 for axis in WEIGHTS}
    weighted, final, applied = apply_rubric(subscores, [])
    assert weighted == 80.0
    assert final == 80.0
    assert applied == []


def test_apply_rubric_binding_cap_dq():
    caps = [Cap(reason="disqualified: missing", cap=CAPS.DQ_VALUE, source="judge_a_protocol")]
    weighted, final, applied = apply_rubric({axis: 100 for axis in WEIGHTS}, caps)
    assert weighted == 100.0
    assert final == CAPS.DQ_VALUE
    assert applied[0].reason.startswith("disqualified")


def test_apply_rubric_keeps_only_binding_caps():
    caps = [
        Cap(reason="cap a", cap=90, source="x"),
        Cap(reason="cap b", cap=40, source="y"),
    ]
    subscores = {axis: 60 for axis in WEIGHTS}
    weighted, final, applied = apply_rubric(subscores, caps)
    assert weighted == 60.0
    assert final == 40.0
    # 90 > 60 -> not binding
    assert [c.reason for c in applied] == ["cap b"]


def test_verdict_ranked_when_no_caps():
    assert verdict_from(75.0, []) == "RANKED"


def test_verdict_disqualified_on_dq_cap():
    cap = Cap(reason="disqualified: leak", cap=0, source="judge_a")
    assert verdict_from(0.0, [cap]) == "DISQUALIFIED"


def test_verdict_contaminated_keyword():
    cap = Cap(reason="contaminated", cap=0, source="judge_b")
    assert verdict_from(0.0, [cap]) == "CONTAMINATED"


def test_verdict_flagged_when_non_dq_cap():
    cap = Cap(reason="fatal mathematical gap", cap=70, source="judge_d")
    assert verdict_from(70.0, [cap]) == "FLAGGED"
