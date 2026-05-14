"""Tests for the leaderboard report aggregator."""

from __future__ import annotations

from pathlib import Path

import orjson

from leaderboard import aggregate, contamination_events, load_reports


def _write_report(
    root: Path,
    subdir: str,
    *,
    evaluation_id: str,
    final_score: float,
    verdict: str = "FLAGGED",
    weighted_score: float | None = None,
    harness_name: str | None = None,
    harness_version: str | None = None,
    applied_caps: list[dict] | None = None,
) -> Path:
    submission_dir = root / subdir
    submission_dir.mkdir(parents=True, exist_ok=True)
    submission_payload = {"path": str(submission_dir)}
    if harness_name is not None:
        submission_payload["harness_name"] = harness_name
    if harness_version is not None:
        submission_payload["harness_version"] = harness_version
    report = {
        "schema_version": "1.0",
        "evaluation_id": evaluation_id,
        "rubric_version": "kakeya3d-rubric-v0.1",
        "submission": submission_payload,
        "judges": {"A": {}, "B": {}, "C": {}, "D": {}, "E": {}},
        "weighted_score": (
            final_score if weighted_score is None else weighted_score
        ),
        "applied_caps": applied_caps or [],
        "final_score": final_score,
        "verdict": verdict,
    }
    path = submission_dir / "evaluation_report.json"
    path.write_bytes(orjson.dumps(report))
    return path


def test_load_reports_finds_nested_files(tmp_path: Path):
    _write_report(tmp_path, "a", evaluation_id="eval-1", final_score=70)
    _write_report(tmp_path, "deeper/b", evaluation_id="eval-2", final_score=42)
    records = load_reports(tmp_path)
    assert {r.evaluation_id for r in records} == {"eval-1", "eval-2"}


def test_load_reports_deduplicates_identical_eval_ids(tmp_path: Path):
    _write_report(tmp_path, "a", evaluation_id="eval-1", final_score=70)
    # A second report with the same harness + eval id is a dup.
    _write_report(
        tmp_path,
        "a-copy",
        evaluation_id="eval-1",
        final_score=70,
        harness_name="a",  # same as path-derived name from first
    )
    records = load_reports(tmp_path)
    # One of them survives; both report payloads are identical for our purposes.
    keys = {(r.harness_name, r.evaluation_id) for r in records}
    assert keys == {("a", "eval-1")}


def test_aggregate_falls_back_to_parent_dir_name(tmp_path: Path):
    _write_report(tmp_path, "rag_synthesis", evaluation_id="eval-1", final_score=40)
    _write_report(
        tmp_path,
        "planner_verifier",
        evaluation_id="eval-2",
        final_score=55,
    )
    histories = aggregate(load_reports(tmp_path))
    names = [h.name for h in histories]
    # Sorted by latest.final_score descending: planner_verifier > rag_synthesis.
    assert names == ["planner_verifier", "rag_synthesis"]
    assert histories[0].latest.final_score == 55


def test_aggregate_walks_above_evaluation_id_dir(tmp_path: Path):
    """``submissions/<harness>/<eval-id>/evaluation_report.json`` layout
    must pick the harness directory, not the eval-id directory.
    """
    _write_report(
        tmp_path,
        "submissions/baselines/planner_verifier/eval-20260513T205434Z",
        evaluation_id="eval-20260513T205434Z",
        final_score=52.2,
    )
    histories = aggregate(load_reports(tmp_path))
    assert len(histories) == 1
    assert histories[0].name == "planner_verifier"


def test_aggregate_uses_report_harness_name_over_path(tmp_path: Path):
    _write_report(
        tmp_path,
        "ignored-path",
        evaluation_id="eval-1",
        final_score=42,
        harness_name="my-harness",
        harness_version="1.2.3",
    )
    histories = aggregate(load_reports(tmp_path))
    assert histories[0].name == "my-harness"
    assert histories[0].version == "1.2.3"


def test_aggregate_groups_historical_evaluations(tmp_path: Path):
    _write_report(
        tmp_path,
        "harness-a/old",
        evaluation_id="eval-20260101T000000Z",
        final_score=30,
        harness_name="harness-a",
        harness_version="0.1",
    )
    _write_report(
        tmp_path,
        "harness-a/new",
        evaluation_id="eval-20260601T000000Z",
        final_score=60,
        harness_name="harness-a",
        harness_version="0.1",
    )
    histories = aggregate(load_reports(tmp_path))
    assert len(histories) == 1
    h = histories[0]
    assert len(h.evaluations) == 2
    # Newest first.
    assert h.evaluations[0].evaluation_id == "eval-20260601T000000Z"
    assert h.latest.final_score == 60


def test_contamination_events_pick_up_dq_caps(tmp_path: Path):
    _write_report(
        tmp_path,
        "good",
        evaluation_id="eval-good",
        final_score=70,
        verdict="RANKED",
    )
    _write_report(
        tmp_path,
        "bad",
        evaluation_id="eval-bad",
        final_score=0,
        verdict="CONTAMINATED",
        applied_caps=[
            {
                "reason": "contaminated: judge B reports major leak",
                "cap": 0,
                "source": "judge_b_contamination",
            }
        ],
    )
    histories = aggregate(load_reports(tmp_path))
    events = contamination_events(histories)
    assert len(events) == 1
    assert events[0]["evaluation_id"] == "eval-bad"
    assert events[0]["verdict"] == "CONTAMINATED"


def test_contamination_events_include_disqualified_verdict(tmp_path: Path):
    """A DISQUALIFIED verdict is treated as a contamination event even
    when no cap reason mentions the word.
    """
    _write_report(
        tmp_path,
        "bad",
        evaluation_id="eval-1",
        final_score=0,
        verdict="DISQUALIFIED",
        applied_caps=[],
    )
    events = contamination_events(aggregate(load_reports(tmp_path)))
    assert len(events) == 1
    assert events[0]["verdict"] == "DISQUALIFIED"
