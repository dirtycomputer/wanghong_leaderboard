"""Tests for the static-site renderer."""

from __future__ import annotations

from pathlib import Path

from leaderboard.aggregate import EvaluationRecord, HarnessHistory
from leaderboard.render import _slug, render_site


def _record(
    tmp_path: Path,
    *,
    harness_name: str,
    evaluation_id: str,
    final_score: float,
    verdict: str = "FLAGGED",
    subscores: dict | None = None,
    applied_caps: list | None = None,
) -> EvaluationRecord:
    path = tmp_path / harness_name / "evaluation_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "1.0",
        "evaluation_id": evaluation_id,
        "rubric_version": "kakeya3d-rubric-v0.1",
        "submission": {"path": str(path.parent), "harness_name": harness_name},
        "subscores": subscores or {
            "protocol": 80, "gold_graph": 70, "correctness": 30,
            "gap_resistance": 40, "novelty": 20, "clarity": 80,
        },
        "weighted_score": final_score,
        "final_score": final_score,
        "applied_caps": applied_caps or [],
        "verdict": verdict,
        "judges": {"A": {}, "B": {}, "C": {}, "D": {}, "E": {}},
        "judge_models": [
            {"role": "B_contamination", "model": "fake-judge", "web_access": True},
        ],
    }
    import orjson
    path.write_bytes(orjson.dumps(report))
    return EvaluationRecord(path=path, report=report)


def test_slug_makes_filesystem_safe_names():
    assert _slug("rag_synthesis", "eval-20260513T120000Z") == (
        "rag_synthesis_eval-20260513T120000Z"
    )
    assert _slug("UPPER/case spaces", "eval-1") == "upper-case-spaces_eval-1"
    assert _slug("", "") == "unnamed_no-eval-id"


def test_render_site_writes_index_and_detail(tmp_path: Path):
    a = _record(tmp_path, harness_name="alpha", evaluation_id="eval-A", final_score=72)
    b = _record(tmp_path, harness_name="beta", evaluation_id="eval-B", final_score=33)
    histories = [
        HarnessHistory(name="alpha", version="", evaluations=(a,)),
        HarnessHistory(name="beta", version="", evaluations=(b,)),
    ]
    out = tmp_path / "site"
    written = render_site(histories, out, generated_at="2026-05-13T12:00:00Z")
    assert (out / "index.html").exists()
    assert (out / "static" / "style.css").exists()
    assert (out / "submissions").is_dir()

    index = (out / "index.html").read_text(encoding="utf-8")
    # Index has both harnesses in score order.
    alpha_pos = index.find(">alpha<")
    beta_pos = index.find(">beta<")
    assert alpha_pos != -1 and beta_pos != -1
    assert alpha_pos < beta_pos
    # Verdict pill present.
    assert "verdict FLAGGED" in index
    # No contamination -> friendly empty-state copy.
    assert "No contamination" in index

    # Detail page for alpha exists and links back.
    detail = list(written.values())[0]
    text = detail.read_text(encoding="utf-8")
    assert "back to leaderboard" in text or "back to" in text


def test_render_site_surfaces_contamination_events(tmp_path: Path):
    a = _record(
        tmp_path,
        harness_name="leaker",
        evaluation_id="eval-leak",
        final_score=0,
        verdict="CONTAMINATED",
        applied_caps=[
            {
                "reason": "contaminated: judge B reports major post-cutoff evidence",
                "cap": 0,
                "source": "judge_b_contamination",
            }
        ],
    )
    histories = [HarnessHistory(name="leaker", version="", evaluations=(a,))]
    out = tmp_path / "site"
    render_site(histories, out, generated_at="2026-05-13T12:00:00Z")
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Anti-cheat events" in index
    assert "judge B reports major" in index
    assert "verdict CONTAMINATED" in index


def test_render_site_wipes_stale_submission_pages(tmp_path: Path):
    out = tmp_path / "site"
    submissions = out / "submissions"
    submissions.mkdir(parents=True)
    (submissions / "stale.html").write_text("legacy", encoding="utf-8")

    a = _record(tmp_path, harness_name="fresh", evaluation_id="eval-1", final_score=50)
    histories = [HarnessHistory(name="fresh", version="", evaluations=(a,))]
    render_site(histories, out, generated_at="2026-05-13T12:00:00Z")
    assert not (submissions / "stale.html").exists()
    assert any(submissions.iterdir())


def test_render_site_history_table_lists_older_evaluations(tmp_path: Path):
    old = _record(
        tmp_path,
        harness_name="h",
        evaluation_id="eval-20260101T000000Z",
        final_score=30,
    )
    new = _record(
        tmp_path,
        harness_name="h",
        evaluation_id="eval-20260601T000000Z",
        final_score=60,
    )
    histories = [HarnessHistory(name="h", version="", evaluations=(new, old))]
    out = tmp_path / "site"
    render_site(histories, out, generated_at="2026-05-13T12:00:00Z")
    # The detail page for the latest eval should reference the older one.
    detail = next((out / "submissions").iterdir())
    text = detail.read_text(encoding="utf-8")
    assert "eval-20260101T000000Z" in text
