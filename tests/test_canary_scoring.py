"""Unit tests for canary contamination scoring.

These guard the pattern-bank weights so that a model that obviously
recalls the target paper cannot slip through with a "clean" verdict
after an accidental pattern edit.
"""

from __future__ import annotations

from pathlib import Path

from scripts.canary_gemma import (
    MODEL_CONTAMINATED_THRESHOLD,
    PROMPT_LEAK_THRESHOLD,
    load_config,
    score_text,
    verdict_from,
)

PROMPTS_PATH = Path(__file__).resolve().parent.parent / "scripts" / "canary_prompts.yaml"


def _patterns():
    _, patterns = load_config(PROMPTS_PATH)
    return patterns


def test_loads_default_prompts_and_patterns():
    prompts, patterns = load_config(PROMPTS_PATH)
    assert len(prompts) >= 5
    assert len(patterns) >= 5


def test_clean_response_is_clean():
    _, score = score_text(
        "I do not know what arXiv 2502 refers to, but the 2D Kakeya problem "
        "was settled by Davies in 1971.",
        _patterns(),
    )
    assert score < PROMPT_LEAK_THRESHOLD
    assert verdict_from(score) == "CLEAN"


def test_direct_arxiv_id_is_severe():
    _, score = score_text(
        "The paper arXiv:2502.17655 by Hong Wang and Joshua Zahl proves the Kakeya conjecture.",
        _patterns(),
    )
    assert score >= MODEL_CONTAMINATED_THRESHOLD
    assert verdict_from(score).startswith("CONTAMINATED")


def test_paper_title_is_severe():
    _, score = score_text(
        'The paper "Volume estimates for unions of convex sets" resolves the 3D Kakeya problem.',
        _patterns(),
    )
    assert score >= PROMPT_LEAK_THRESHOLD


def test_completion_attribution_is_severe():
    _, score = score_text(
        "The Kakeya conjecture was resolved in February 2025 by Wang and Zahl.",
        _patterns(),
    )
    assert score >= MODEL_CONTAMINATED_THRESHOLD


def test_author_only_without_year_is_not_flagged():
    # Hong Wang and Joshua Zahl are real pre-cutoff researchers; their
    # names alone must not flag a response as contaminated.
    _, score = score_text(
        "Hong Wang and Joshua Zahl have written extensively on incidence "
        "geometry and the restriction conjecture.",
        _patterns(),
    )
    assert verdict_from(score) == "CLEAN"


def test_verdict_thresholds():
    assert verdict_from(0) == "CLEAN"
    assert verdict_from(PROMPT_LEAK_THRESHOLD).startswith("SUSPICIOUS")
    assert verdict_from(MODEL_CONTAMINATED_THRESHOLD).startswith("CONTAMINATED")
