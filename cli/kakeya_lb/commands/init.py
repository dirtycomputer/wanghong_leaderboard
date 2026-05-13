"""``kakeya-lb init <dir>`` — scaffold a harness from the starter template."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_STARTER_DIR = Path(__file__).resolve().parents[3] / "starter"


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "init",
        help="Scaffold a new harness directory from the starter template.",
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="Path to create. Must not exist (or must be empty if --force).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing non-empty destination (file-by-file).",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    dest: Path = args.destination
    if dest.exists() and not args.force and any(dest.iterdir()):
        print(
            f"error: {dest} already exists and is not empty (use --force)",
            file=sys.stderr,
        )
        return 1
    if not _STARTER_DIR.exists():
        print(
            f"error: starter template not found at {_STARTER_DIR}",
            file=sys.stderr,
        )
        return 1
    shutil.copytree(_STARTER_DIR, dest, dirs_exist_ok=args.force)
    print(f"Initialized harness at {dest}")
    print(
        "Next steps:\n"
        "  1. Edit src/main.py to implement your approach.\n"
        "  2. Update authors and resources in harness.yaml.\n"
        f"  3. Run: kakeya-lb validate {dest}"
    )
    return 0
