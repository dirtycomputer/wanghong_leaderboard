"""Manifest builder for the time-capsule corpus.

A manifest is a JSONL file with one entry per paper that survived
harvesting and parsing. The corpus hash is the SHA-256 of the
canonical, sorted manifest contents — so re-running the pipeline with
the same inputs deterministically produces the same hash, and any
difference (new paper, new MinerU version, new cutoff policy) is
visible in the leaderboard metadata.

The manifest also acts as a defence-in-depth guard: the builder
refuses to add any entry submitted on or after the cutoff or whose
arXiv id is on the blocklist (target paper, etc.).
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson

from corpus.harvest_arxiv import DEFAULT_CUTOFF, CutoffViolation

MANIFEST_FILENAME = "manifest.jsonl"
CORPUS_HASH_FILENAME = "corpus_hash.txt"


@dataclasses.dataclass(frozen=True)
class ManifestEntry:
    """One paper in the time-capsule corpus."""

    arxiv_id: str
    version: str
    title: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    submitted_at: datetime
    pdf_path: str
    pdf_sha256: str
    pdf_bytes: int
    markdown_path: str
    markdown_sha256: str
    mineru_model_version: str
    cutoff_policy: str = "submitted_before_2025-01-01T00:00:00Z"

    def to_canonical_dict(self) -> dict[str, Any]:
        """Deterministic ordered dict used for hashing.

        Keys are sorted alphabetically and ``submitted_at`` is
        rendered as an explicit UTC ISO-8601 string so that local
        timezone configuration cannot shift the hash.
        """
        return {
            "arxiv_id": self.arxiv_id,
            "authors": list(self.authors),
            "categories": list(self.categories),
            "cutoff_policy": self.cutoff_policy,
            "markdown_path": self.markdown_path,
            "markdown_sha256": self.markdown_sha256,
            "mineru_model_version": self.mineru_model_version,
            "pdf_bytes": self.pdf_bytes,
            "pdf_path": self.pdf_path,
            "pdf_sha256": self.pdf_sha256,
            "submitted_at": _as_utc_isoformat(self.submitted_at),
            "title": self.title,
            "version": self.version,
        }


def build_manifest(
    entries: Iterable[ManifestEntry],
    *,
    cutoff: datetime = DEFAULT_CUTOFF,
    blocklist: frozenset[str] = frozenset(),
) -> list[ManifestEntry]:
    """Validate, sort and return the manifest entry list.

    Refuses any entry whose submission timestamp is at or after
    ``cutoff`` (raises :class:`CutoffViolation`) or whose arXiv id is
    in ``blocklist`` (raises :class:`ValueError`). The output list is
    sorted by ``(arxiv_id, version)`` so the corpus hash is
    deterministic.
    """
    validated: list[ManifestEntry] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if entry.submitted_at >= cutoff:
            raise CutoffViolation(
                f"manifest refuses {entry.arxiv_id}{entry.version}: "
                f"submitted_at {_as_utc_isoformat(entry.submitted_at)} "
                f">= cutoff {_as_utc_isoformat(cutoff)}"
            )
        if entry.arxiv_id in blocklist:
            raise ValueError(
                f"manifest refuses blocklisted arXiv id {entry.arxiv_id}"
            )
        key = (entry.arxiv_id, entry.version)
        if key in seen:
            raise ValueError(
                f"duplicate manifest entry for {entry.arxiv_id}{entry.version}"
            )
        seen.add(key)
        validated.append(entry)

    validated.sort(key=lambda e: (e.arxiv_id, e.version))
    return validated


def write_manifest(entries: list[ManifestEntry], corpus_root: Path) -> tuple[Path, str]:
    """Write ``manifest.jsonl`` + ``corpus_hash.txt`` and return paths.

    The corpus hash is also returned for the caller to record in the
    leaderboard run metadata.
    """
    corpus_root.mkdir(parents=True, exist_ok=True)
    manifest_path = corpus_root / MANIFEST_FILENAME

    canonical_lines: list[bytes] = []
    with manifest_path.open("wb") as fh:
        for entry in entries:
            canonical = orjson.dumps(entry.to_canonical_dict(), option=orjson.OPT_SORT_KEYS)
            fh.write(canonical)
            fh.write(b"\n")
            canonical_lines.append(canonical)

    digest = hashlib.sha256()
    for line in canonical_lines:
        digest.update(line)
        digest.update(b"\n")
    corpus_hash = digest.hexdigest()

    hash_path = corpus_root / CORPUS_HASH_FILENAME
    hash_path.write_text(corpus_hash + "\n", encoding="utf-8")
    return manifest_path, corpus_hash


def compute_corpus_hash(entries: list[ManifestEntry]) -> str:
    """Pure-function variant for callers that don't want to write files."""
    digest = hashlib.sha256()
    for entry in entries:
        line = orjson.dumps(entry.to_canonical_dict(), option=orjson.OPT_SORT_KEYS)
        digest.update(line)
        digest.update(b"\n")
    return digest.hexdigest()


def _as_utc_isoformat(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
