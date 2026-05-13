"""Tests for the corpus manifest builder."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import orjson
import pytest

from corpus.harvest_arxiv import CutoffViolation
from corpus.manifest import (
    CORPUS_HASH_FILENAME,
    MANIFEST_FILENAME,
    ManifestEntry,
    build_manifest,
    compute_corpus_hash,
    write_manifest,
)


def _entry(arxiv_id: str, submitted: datetime, **kwargs) -> ManifestEntry:
    defaults = dict(
        version="v1",
        title="Title",
        authors=("Author One",),
        categories=("math.CA",),
        submitted_at=submitted,
        pdf_path=f"corpus/papers/{arxiv_id}/source.pdf",
        pdf_sha256="0" * 64,
        pdf_bytes=1024,
        markdown_path=f"corpus/papers/{arxiv_id}/full.md",
        markdown_sha256="1" * 64,
        mineru_model_version="vlm",
    )
    defaults.update(kwargs)
    return ManifestEntry(arxiv_id=arxiv_id, **defaults)


def test_build_manifest_sorts_by_id():
    entries = [
        _entry("2024.00099", datetime(2024, 5, 1, tzinfo=UTC)),
        _entry("2024.00001", datetime(2024, 4, 1, tzinfo=UTC)),
    ]
    built = build_manifest(entries)
    assert [e.arxiv_id for e in built] == ["2024.00001", "2024.00099"]


def test_build_manifest_rejects_post_cutoff_entry():
    entries = [_entry("2025.99999", datetime(2025, 6, 1, tzinfo=UTC))]
    with pytest.raises(CutoffViolation):
        build_manifest(entries)


def test_build_manifest_rejects_blocklisted_id():
    entries = [_entry("2502.17655", datetime(2024, 12, 30, tzinfo=UTC))]
    with pytest.raises(ValueError):
        build_manifest(entries, blocklist=frozenset({"2502.17655"}))


def test_build_manifest_rejects_duplicates():
    a = _entry("2024.00001", datetime(2024, 6, 1, tzinfo=UTC))
    b = _entry("2024.00001", datetime(2024, 6, 2, tzinfo=UTC))
    with pytest.raises(ValueError):
        build_manifest([a, b])


def test_corpus_hash_is_stable_across_order():
    a = _entry("2024.00009", datetime(2024, 6, 1, tzinfo=UTC))
    b = _entry("2024.00001", datetime(2024, 6, 2, tzinfo=UTC))
    h1 = compute_corpus_hash(build_manifest([a, b]))
    h2 = compute_corpus_hash(build_manifest([b, a]))
    assert h1 == h2


def test_corpus_hash_changes_when_entry_changes():
    a = _entry("2024.00001", datetime(2024, 6, 1, tzinfo=UTC))
    h1 = compute_corpus_hash(build_manifest([a]))
    b = _entry(
        "2024.00001",
        datetime(2024, 6, 1, tzinfo=UTC),
        markdown_sha256="2" * 64,
    )
    h2 = compute_corpus_hash(build_manifest([b]))
    assert h1 != h2


def test_write_manifest_writes_jsonl_and_hash(tmp_path: Path):
    entry = _entry("2024.00001", datetime(2024, 6, 1, tzinfo=UTC))
    manifest_path, corpus_hash = write_manifest(
        build_manifest([entry]), tmp_path
    )
    assert manifest_path == tmp_path / MANIFEST_FILENAME
    contents = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(contents) == 1
    obj = orjson.loads(contents[0])
    assert obj["arxiv_id"] == "2024.00001"
    assert obj["submitted_at"] == "2024-06-01T00:00:00Z"
    hash_path = tmp_path / CORPUS_HASH_FILENAME
    assert hash_path.read_text(encoding="utf-8").strip() == corpus_hash
