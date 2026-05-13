"""``kakeya-lb validate <dir>`` — schema-check the harness manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from cli.kakeya_lb.schemas import HARNESS_MANIFEST_SCHEMA_PATH, validate_against


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "validate",
        help="Validate harness.yaml against the official schema.",
    )
    parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Harness directory (defaults to current dir).",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    yaml_path = args.directory / "harness.yaml"
    if not yaml_path.exists():
        print(f"error: {yaml_path} not found", file=sys.stderr)
        return 1

    raw: Any = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if raw is None:
        print(f"error: {yaml_path} is empty", file=sys.stderr)
        return 1

    errors = validate_against(raw, HARNESS_MANIFEST_SCHEMA_PATH)
    if errors:
        print(f"{yaml_path}: {len(errors)} schema violation(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Spot-check the dangerous boolean fields.
    claims = raw.get("claims", {})
    if claims.get("uses_external_apis"):
        print(
            "error: claims.uses_external_apis must be false; the runner "
            "isolates the participant container",
            file=sys.stderr,
        )
        return 1
    if claims.get("requires_network"):
        print(
            "error: claims.requires_network must be false; only the leaderboard "
            "proxy is reachable",
            file=sys.stderr,
        )
        return 1

    print(f"{yaml_path}: OK")
    return 0
