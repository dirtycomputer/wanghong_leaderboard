"""Build the time-capsule corpus end to end.

Reads ``corpus/seed_keywords.yaml``, runs the arXiv harvester for each
query, dedupes results, downloads the PDFs, parses each PDF through
MinerU v4, then writes ``manifest.jsonl`` + ``corpus_hash.txt``.

The target paper (``arXiv:2502.17655``) is always excluded — both by
the seed file's ``arxiv_id_blocklist`` and by the manifest builder's
defence-in-depth check. Use ``scripts/parse_target_paper.py`` to bring
it into the private judge vault.

Usage::

    python -m scripts.build_corpus \
        --seeds corpus/seed_keywords.yaml \
        --out corpus/papers \
        --manifest-dir corpus

Requires ``OPENROUTER_KEY`` to be **unset** (the corpus builder must
never call the participant model) and ``MINERU_KEY`` to be set.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from corpus.harvest_arxiv import (
    DEFAULT_CUTOFF,
    ArxivResult,
    CutoffViolation,
    download_pdf,
    search_arxiv,
)
from corpus.manifest import ManifestEntry, build_manifest, write_manifest
from corpus.mineru_parse import MineruClient, parse_pdf_url

logger = logging.getLogger("build_corpus")


@dataclasses.dataclass(frozen=True)
class SeedConfig:
    queries: list[str]
    categories: list[str]
    submitted_before: datetime
    blocklist: frozenset[str]
    max_results_per_query: int
    max_total_papers: int


def load_seeds(path: Path) -> SeedConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    filters = raw.get("filters", {}) or {}
    limits = raw.get("limits", {}) or {}
    cutoff_str = filters.get("submitted_before", "2025-01-01T00:00:00Z")
    cutoff = datetime.fromisoformat(cutoff_str.replace("Z", "+00:00"))
    blocklist = frozenset(filters.get("arxiv_id_blocklist", []) or [])
    return SeedConfig(
        queries=list(raw.get("queries", []) or []),
        categories=list(raw.get("categories", []) or []),
        submitted_before=cutoff,
        blocklist=blocklist,
        max_results_per_query=int(limits.get("max_results_per_query", 100)),
        max_total_papers=int(limits.get("max_total_papers", 1000)),
    )


def compose_query(query: str, categories: list[str]) -> str:
    """AND the query expression with a category OR-group."""
    if not categories:
        return query
    cat_clause = " OR ".join(f"cat:{c}" for c in categories)
    return f"({query}) AND ({cat_clause})"


def harvest_unique(seeds: SeedConfig) -> list[ArxivResult]:
    seen: dict[str, ArxivResult] = {}
    for query in seeds.queries:
        expr = compose_query(query, seeds.categories)
        logger.info("query: %s", expr)
        for result in search_arxiv(
            expr,
            cutoff=seeds.submitted_before,
            max_results=seeds.max_results_per_query,
            blocklist=seeds.blocklist,
        ):
            seen.setdefault(result.arxiv_id, result)
            if len(seen) >= seeds.max_total_papers:
                logger.info("hit max_total_papers=%d, stopping", seeds.max_total_papers)
                return list(seen.values())
    return list(seen.values())


def build_one(
    result: ArxivResult,
    *,
    papers_root: Path,
    mineru: MineruClient,
    cutoff: datetime,
) -> ManifestEntry:
    paper_dir = papers_root / f"arxiv_{result.arxiv_id}{result.version}"
    pdf_meta = download_pdf(result, out_dir=paper_dir, cutoff=cutoff)
    parse_result = parse_pdf_url(mineru, result.pdf_url, paper_dir=paper_dir)
    return ManifestEntry(
        arxiv_id=result.arxiv_id,
        version=result.version,
        title=result.title,
        authors=result.authors,
        categories=result.categories,
        submitted_at=result.submitted_at,
        pdf_path=pdf_meta["pdf_path"],
        pdf_sha256=pdf_meta["pdf_sha256"],
        pdf_bytes=pdf_meta["pdf_bytes"],
        markdown_path=str(parse_result.full_md),
        markdown_sha256=parse_result.markdown_sha256,
        mineru_model_version=mineru._model_version,  # noqa: SLF001
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=Path, default=Path("corpus/seed_keywords.yaml"))
    parser.add_argument("--out", type=Path, default=Path("corpus/papers"))
    parser.add_argument("--manifest-dir", type=Path, default=Path("corpus"))
    parser.add_argument(
        "--max-papers",
        type=int,
        default=None,
        help="Optional override for limits.max_total_papers (smoke testing).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    seeds = load_seeds(args.seeds)
    if args.max_papers is not None:
        seeds = dataclasses.replace(seeds, max_total_papers=args.max_papers)
    if seeds.submitted_before > DEFAULT_CUTOFF:
        # Defence-in-depth: the seed file cannot relax the module's
        # built-in cutoff.
        raise CutoffViolation(
            f"seeds cutoff {seeds.submitted_before} is past the module cutoff {DEFAULT_CUTOFF}"
        )

    logger.info("harvesting (cutoff=%s)", seeds.submitted_before.isoformat())
    results = harvest_unique(seeds)
    logger.info("found %d unique pre-cutoff papers", len(results))

    if not results:
        logger.warning("no results — aborting before MinerU charges")
        return 0

    mineru = MineruClient.from_env()
    entries: list[ManifestEntry] = []
    for result in results:
        try:
            entries.append(
                build_one(
                    result,
                    papers_root=args.out,
                    mineru=mineru,
                    cutoff=seeds.submitted_before,
                )
            )
        except Exception:
            logger.exception("failed to process %s; skipping", result.arxiv_id)

    manifest_entries = build_manifest(
        entries, cutoff=seeds.submitted_before, blocklist=seeds.blocklist
    )
    manifest_path, corpus_hash = write_manifest(manifest_entries, args.manifest_dir)
    logger.info("wrote %s (%d entries)", manifest_path, len(manifest_entries))
    logger.info("corpus_hash=%s", corpus_hash)
    print(corpus_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
