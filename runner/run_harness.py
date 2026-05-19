"""Run one self-contained harness directory in the Docker sandbox."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from runner.sandbox import SandboxConfig, run_in_sandbox, validate_harness_safety, validate_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", default="local-run")
    parser.add_argument("--model-api-base", required=True)
    parser.add_argument("--model-api-key", required=True)
    parser.add_argument("--search-api-base", default=None)
    parser.add_argument("--search-api-key", default=None)
    parser.add_argument("--search-cutoff", default="2025-01-01T00:00:00Z")
    args = parser.parse_args(argv)

    manifest = _load_manifest(args.harness)
    validate_harness_safety(manifest, args.harness)
    resources = manifest["resources"]
    config = SandboxConfig(
        image_ref=manifest["image"],
        run_id=args.run_id,
        harness_dir=args.harness,
        entrypoint=manifest["entrypoint"],
        capabilities=manifest["capabilities"],
        task_path=args.task,
        output_dir=args.output,
        proxy_api_base=args.model_api_base,
        proxy_token=args.model_api_key,
        search_api_base=args.search_api_base,
        search_token=args.search_api_key,
        search_cutoff=args.search_cutoff,
        cpu=int(resources["cpu"]),
        memory_gb=int(resources["memory_gb"]),
        max_wall_time_seconds=int(float(resources["max_wall_time_hours"]) * 3600),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    result = run_in_sandbox(config)
    if result.exit_code != 0:
        print(result.stderr_tail or result.stdout_tail, file=sys.stderr)
        return result.exit_code
    missing = validate_outputs(args.output)
    if missing:
        print(f"missing required outputs: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(args.output)
    return 0


def _load_manifest(harness_dir: Path) -> dict[str, Any]:
    path = harness_dir / "harness.yaml"
    if not path.exists():
        raise SystemExit(f"{path} not found")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"{path} must be a YAML mapping")
    return raw


if __name__ == "__main__":
    sys.exit(main())
