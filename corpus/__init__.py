"""Time-capsule corpus pipeline.

Three stages: ``harvest_arxiv`` (download metadata + PDFs from arXiv
respecting the ``submittedDate < 2025-01-01 GMT`` cutoff),
``mineru_parse`` (precise PDF parsing via the MinerU v4 VLM API), and
``manifest`` (hashable record of every paper that made it into the
corpus). The target paper ``arXiv:2502.17655`` never travels through
this module — it has its own ``scripts/parse_target_paper.py`` that
writes to the private judge vault.
"""

from corpus.manifest import (
    CORPUS_HASH_FILENAME,
    MANIFEST_FILENAME,
    ManifestEntry,
    build_manifest,
    compute_corpus_hash,
    write_manifest,
)

__all__ = [
    "CORPUS_HASH_FILENAME",
    "MANIFEST_FILENAME",
    "ManifestEntry",
    "build_manifest",
    "compute_corpus_hash",
    "write_manifest",
]
