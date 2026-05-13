"""Parse the target paper (arXiv:2502.17655) into the private judge vault.

This script is intentionally separate from ``scripts/build_corpus.py``
so the target never travels through the public corpus pipeline. It
writes to ``judge/vault/target_paper/`` (which is ``.gitignore``-d) and
prints the markdown SHA-256 so that the gold proof graph and judge
configurations can pin to a specific parse.

Usage::

    python -m scripts.parse_target_paper

Refuses to run if the target arXiv id is mistakenly listed in any
public corpus manifest under ``--corpus-root``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import orjson

from corpus.manifest import MANIFEST_FILENAME
from corpus.mineru_parse import MineruClient, parse_pdf_url

TARGET_ARXIV_ID = "2502.17655"
TARGET_PDF_URL = f"https://arxiv.org/pdf/{TARGET_ARXIV_ID}.pdf"
VAULT_SUBDIR = "target_paper"

logger = logging.getLogger("parse_target_paper")


def _ensure_target_not_in_public_corpus(corpus_root: Path) -> None:
    manifest_path = corpus_root / MANIFEST_FILENAME
    if not manifest_path.exists():
        return
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = orjson.loads(line)
        except orjson.JSONDecodeError:
            continue
        if entry.get("arxiv_id") == TARGET_ARXIV_ID:
            raise RuntimeError(
                f"target paper {TARGET_ARXIV_ID} is present in public corpus manifest "
                f"({manifest_path}); refusing to also write it to the vault. "
                "Rebuild the public corpus first."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path("judge/vault"))
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("corpus"),
        help="Public corpus root used for the cross-leak safety check.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    _ensure_target_not_in_public_corpus(args.corpus_root)

    paper_dir = args.vault_root / VAULT_SUBDIR
    paper_dir.mkdir(parents=True, exist_ok=True)

    mineru = MineruClient.from_env()
    result = parse_pdf_url(mineru, TARGET_PDF_URL, paper_dir=paper_dir)
    logger.info("wrote %s", result.full_md)
    logger.info("markdown_sha256=%s", result.markdown_sha256)
    print(result.markdown_sha256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
