"""Build the public Wang Hong leaderboard as a static HTML site.

Reads every ``evaluation_report.json`` under ``--reports`` and writes
``index.html`` + per-submission detail pages + ``static/style.css``
into ``--out``. The site is JS-free and reproducible byte-for-byte
given the same input directory.

Usage::

    python -m scripts.build_leaderboard \\
        --reports submissions/ \\
        --out site/

Then host ``site/`` on GitHub Pages, S3, or any static file server.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from leaderboard import aggregate, load_reports, render_site

logger = logging.getLogger("build_leaderboard")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports",
        type=Path,
        required=True,
        help="Directory tree containing one or more evaluation_report.json files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory; will be created if missing.",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="Wang Hong (3D Kakeya) Leaderboard",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.reports.exists():
        logger.error("reports directory %s does not exist", args.reports)
        return 1

    records = load_reports(args.reports)
    logger.info("loaded %d evaluation report(s)", len(records))
    histories = aggregate(records)
    logger.info(
        "grouped into %d harness(es); top score=%.1f",
        len(histories),
        histories[0].latest.final_score if histories else 0.0,
    )

    written = render_site(histories, args.out, title=args.title)
    logger.info("wrote %d file(s) under %s", len(written), args.out)
    print(args.out / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
