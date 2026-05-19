"""Tiny CLI for validating harnesses and outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from runner.sandbox import REQUIRED_OUTPUTS, validate_outputs
from runner.schema_utils import (
    HARNESS_MANIFEST_SCHEMA_PATH,
    PROOF_GRAPH_SCHEMA_PATH,
    RUN_MANIFEST_SCHEMA_PATH,
    validate_against,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kakeya-lb",
        description="Validate harness directories and harness outputs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate",
        help="Validate harness.yaml and run.sh in a harness directory.",
    )
    validate.add_argument("directory", type=Path, nargs="?", default=Path("."))
    validate.set_defaults(handler=_validate_harness)

    schema_check = subparsers.add_parser(
        "schema-check",
        help="Verify required output files and JSON schemas.",
    )
    schema_check.add_argument("output_dir", type=Path, nargs="?", default=Path("output"))
    schema_check.set_defaults(handler=_schema_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def _validate_harness(args: argparse.Namespace) -> int:
    directory: Path = args.directory
    yaml_path = directory / "harness.yaml"
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

    entrypoint = raw.get("entrypoint")
    entry_path = directory / str(entrypoint).removeprefix("./")
    if not entry_path.exists():
        print(f"error: entrypoint {entrypoint!r} not found under {directory}", file=sys.stderr)
        return 1
    if not entry_path.is_file():
        print(f"error: entrypoint {entrypoint!r} is not a file", file=sys.stderr)
        return 1

    if (raw.get("capabilities") or {}).get("native_tools") is not False:
        print("error: capabilities.native_tools must be false", file=sys.stderr)
        return 1

    print(f"{yaml_path}: OK")
    return 0


def _schema_check(args: argparse.Namespace) -> int:
    out: Path = args.output_dir
    if not out.exists():
        print(f"error: {out} does not exist", file=sys.stderr)
        return 1

    missing = validate_outputs(out)
    if missing:
        print(f"{out}: missing required outputs: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"{out}: all {len(REQUIRED_OUTPUTS)} required files present")

    failed = _check_json(out / "proof_graph.json", PROOF_GRAPH_SCHEMA_PATH)
    run_manifest = out / "run_manifest.json"
    if run_manifest.exists():
        failed |= _check_json(run_manifest, RUN_MANIFEST_SCHEMA_PATH)
    return 1 if failed else 0


def _check_json(path: Path, schema_path: Path) -> bool:
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


if __name__ == "__main__":
    sys.exit(main())
