"""``kakeya-lb schema-check <output_dir>`` — validate the five output files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cli.kakeya_lb.schemas import (
    PROOF_GRAPH_SCHEMA_PATH,
    RUN_MANIFEST_SCHEMA_PATH,
    validate_against,
)
from runner.sandbox import REQUIRED_OUTPUTS, validate_outputs


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "schema-check",
        help=(
            "Verify that the output directory has all required files "
            "and that JSON files match schemas."
        ),
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=Path("output"),
        help="Path produced by the harness run (defaults to ./output).",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    out: Path = args.output_dir
    if not out.exists():
        print(f"error: {out} does not exist", file=sys.stderr)
        return 1

    missing = validate_outputs(out)
    if missing:
        print(f"{out}: missing required outputs: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"{out}: all {len(REQUIRED_OUTPUTS)} required files present")

    failed = False
    failed |= _check_json(out / "proof_graph.json", PROOF_GRAPH_SCHEMA_PATH)

    run_manifest = out / "run_manifest.json"
    if run_manifest.exists():
        failed |= _check_json(run_manifest, RUN_MANIFEST_SCHEMA_PATH)

    return 1 if failed else 0


def _check_json(path: Path, schema_path: Path) -> bool:
    """Return True on failure (matches the ``failed |=`` accumulator pattern)."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{path}: invalid JSON ({exc})", file=sys.stderr)
        return True

    errors = validate_against(document, schema_path)
    if errors:
        print(f"{path}: {len(errors)} schema violation(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return True
    print(f"{path}: OK against {schema_path.name}")
    return False
