"""Tests for the corpus orchestrator + target-paper vault pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import orjson
import pytest

from scripts.build_corpus import SeedConfig, compose_query, load_seeds
from scripts.parse_target_paper import _ensure_target_not_in_public_corpus


def test_compose_query_ands_categories():
    expr = compose_query("all:Kakeya", ["math.CA", "math.MG"])
    assert expr == "(all:Kakeya) AND (cat:math.CA OR cat:math.MG)"


def test_compose_query_passthrough_when_no_categories():
    assert compose_query("all:Kakeya", []) == "all:Kakeya"


def test_load_seeds_parses_default_file():
    seeds = load_seeds(Path("corpus/seed_keywords.yaml"))
    assert isinstance(seeds, SeedConfig)
    assert seeds.queries, "seed file must contain at least one query"
    assert "math.CA" in seeds.categories
    assert seeds.submitted_before == datetime(2025, 1, 1, tzinfo=UTC)
    assert "2502.17655" in seeds.blocklist
    assert seeds.max_results_per_query > 0
    assert seeds.max_total_papers > 0


def test_target_paper_guard_passes_when_absent(tmp_path: Path):
    (tmp_path / "manifest.jsonl").write_text(
        orjson.dumps({"arxiv_id": "2401.00001"}).decode() + "\n",
        encoding="utf-8",
    )
    _ensure_target_not_in_public_corpus(tmp_path)  # should not raise


def test_target_paper_guard_raises_when_present(tmp_path: Path):
    (tmp_path / "manifest.jsonl").write_text(
        orjson.dumps({"arxiv_id": "2502.17655"}).decode() + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        _ensure_target_not_in_public_corpus(tmp_path)


def test_target_paper_guard_passes_when_manifest_missing(tmp_path: Path):
    # No manifest at all: pipeline hasn't been built yet, vault parse is fine.
    _ensure_target_not_in_public_corpus(tmp_path)
