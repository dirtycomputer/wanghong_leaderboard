"""Tests for the public JSON schemas."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from runner.schema_utils import (
    HARNESS_MANIFEST_SCHEMA_PATH,
    PROOF_GRAPH_SCHEMA_PATH,
    RUN_MANIFEST_SCHEMA_PATH,
    load_schema,
    validate_against,
)


@pytest.fixture
def harness_manifest() -> dict:
    return {
        "name": "model",
        "version": "0.1.0",
        "kind": "model",
        "image": "ghcr.io/x/y@sha256:" + "a" * 64,
        "license": "MIT",
        "authors": [{"name": "Alice", "affiliation": "Mu"}],
        "entrypoint": "./run.sh",
        "resources": {
            "max_wall_time_hours": 6,
            "max_model_calls": 1000,
            "max_total_tokens": 4_000_000,
            "cpu": 8,
            "memory_gb": 32,
            "gpu": False,
        },
        "capabilities": {
            "model": True,
            "restricted_search": False,
            "native_tools": False,
        },
        "outputs": {
            "final_proof": "final_proof.md",
            "proof_graph": "proof_graph.json",
            "citations": "cited_sources.json",
            "self_critique": "self_critique.md",
            "trace": "trace.jsonl",
        },
    }


@pytest.fixture
def proof_graph() -> dict:
    return {
        "schema_version": "1.0",
        "target_theorem": "Every Kakeya set in R^3 has Hausdorff dimension 3.",
        "definitions": [
            {"name": "delta-tube", "statement": "A tube of length 1 and radius delta."}
        ],
        "pre_cutoff_dependencies": [
            {"arxiv_id": "1909.10973v2", "claim": "Polynomial method"},
        ],
        "new_lemmas": [
            {
                "name": "L1",
                "statement": "Volume bound on tube unions",
                "proof_status": "sketched",
                "depends_on": ["delta-tube"],
                "used_for": ["final"],
            }
        ],
        "known_gaps": [
            {
                "location": "L1",
                "description": "Constant suboptimal",
                "severity": "minor",
            }
        ],
        "final_implication": "Therefore dim_H = 3.",
    }


@pytest.fixture
def run_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "harness_name": "model",
        "harness_version": "0.1.0",
        "harness_kind": "model",
        "model": "google/gemma-4-31b-it",
        "restricted_search": {"enabled": False},
        "outputs": {
            "final_proof": "final_proof.md",
            "proof_graph": "proof_graph.json",
            "cited_sources": "cited_sources.json",
            "self_critique": "self_critique.md",
            "trace": "trace.jsonl",
        },
    }


def test_harness_manifest_accepts_model_yaml():
    raw = yaml.safe_load(Path("harnesses/model/harness.yaml").read_text(encoding="utf-8"))
    errors = validate_against(raw, HARNESS_MANIFEST_SCHEMA_PATH)
    assert errors == []


def test_harness_manifest_rejects_native_tools(harness_manifest):
    harness_manifest["capabilities"]["native_tools"] = True
    errors = validate_against(harness_manifest, HARNESS_MANIFEST_SCHEMA_PATH)
    assert any("native_tools" in e for e in errors)


def test_harness_manifest_rejects_excessive_resources(harness_manifest):
    harness_manifest["resources"]["max_wall_time_hours"] = 100
    errors = validate_against(harness_manifest, HARNESS_MANIFEST_SCHEMA_PATH)
    assert errors


def test_proof_graph_accepts_minimal_valid(proof_graph):
    errors = validate_against(proof_graph, PROOF_GRAPH_SCHEMA_PATH)
    assert errors == []


def test_proof_graph_rejects_invalid_proof_status(proof_graph):
    bad = copy.deepcopy(proof_graph)
    bad["new_lemmas"][0]["proof_status"] = "definitely-proved"
    errors = validate_against(bad, PROOF_GRAPH_SCHEMA_PATH)
    assert any("proof_status" in e for e in errors)


def test_proof_graph_accepts_pre_2007_arxiv_id(proof_graph):
    """Old-format IDs like 0010069 (Katz 2000) must validate.

    The harvester strips the subject prefix from pre-2007 papers so the
    canonical short form is 7 digits, optionally with a version.
    """
    bad = copy.deepcopy(proof_graph)
    for cand in ("0010069", "0010069v2", "9807163", "9807163v1"):
        bad["pre_cutoff_dependencies"][0]["arxiv_id"] = cand
        errors = validate_against(bad, PROOF_GRAPH_SCHEMA_PATH)
        assert errors == [], f"{cand} unexpectedly rejected: {errors}"


def test_proof_graph_accepts_pre_2007_with_subject_prefix(proof_graph):
    """``math.CA/0010069`` (subject-prefixed) must also validate."""
    bad = copy.deepcopy(proof_graph)
    for cand in ("math.CA/0010069", "math/0010069", "astro-ph/0010069v1"):
        bad["pre_cutoff_dependencies"][0]["arxiv_id"] = cand
        errors = validate_against(bad, PROOF_GRAPH_SCHEMA_PATH)
        assert errors == [], f"{cand} unexpectedly rejected: {errors}"


def test_proof_graph_rejects_bad_arxiv_id(proof_graph):
    bad = copy.deepcopy(proof_graph)
    bad["pre_cutoff_dependencies"][0]["arxiv_id"] = "not-an-id"
    errors = validate_against(bad, PROOF_GRAPH_SCHEMA_PATH)
    assert errors


def test_proof_graph_rejects_wrong_schema_version(proof_graph):
    bad = copy.deepcopy(proof_graph)
    bad["schema_version"] = "0.9"
    errors = validate_against(bad, PROOF_GRAPH_SCHEMA_PATH)
    assert errors


def test_run_manifest_accepts_minimal_valid(run_manifest):
    errors = validate_against(run_manifest, RUN_MANIFEST_SCHEMA_PATH)
    assert errors == []


def test_run_manifest_rejects_wrong_model(run_manifest):
    bad = copy.deepcopy(run_manifest)
    bad["model"] = "openai/gpt-4o"
    errors = validate_against(bad, RUN_MANIFEST_SCHEMA_PATH)
    assert any("model" in e for e in errors)


def test_run_manifest_rejects_floating_image_digest(run_manifest):
    bad = copy.deepcopy(run_manifest)
    bad["docker_digest"] = "latest"
    errors = validate_against(bad, RUN_MANIFEST_SCHEMA_PATH)
    assert errors


def test_load_schema_roundtrip():
    schema = load_schema(HARNESS_MANIFEST_SCHEMA_PATH)
    assert schema["title"] == "harness.yaml"
