"""Small schema helpers shared by the runner and judge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_DIR = _ROOT / "schemas"

HARNESS_MANIFEST_SCHEMA_PATH = _SCHEMA_DIR / "harness_manifest.schema.json"
PROOF_GRAPH_SCHEMA_PATH = _SCHEMA_DIR / "proof_graph.schema.json"
RUN_MANIFEST_SCHEMA_PATH = _SCHEMA_DIR / "run_manifest.schema.json"


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_against(document: Any, schema_path: Path) -> list[str]:
    schema = load_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(document), key=lambda e: e.path):
        location = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{location}: {err.message}")
    return errors
