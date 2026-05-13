"""Shared schema loader / validator used by every CLI command."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIR = _PKG_ROOT / "schemas"

HARNESS_MANIFEST_SCHEMA_PATH = _SCHEMA_DIR / "harness_manifest.schema.json"
PROOF_GRAPH_SCHEMA_PATH = _SCHEMA_DIR / "proof_graph.schema.json"
RUN_MANIFEST_SCHEMA_PATH = _SCHEMA_DIR / "run_manifest.schema.json"


def load_schema(path: Path) -> dict[str, Any]:
    """Load a JSON schema file from disk."""
    if not path.exists():
        # Allow CLI to be invoked from a pip-installed wheel where the
        # schemas/ tree may be relocated. Fall back to importlib.resources
        # if the on-disk lookup fails.
        try:
            return json.loads(
                resources.files("schemas").joinpath(path.name).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, ModuleNotFoundError) as exc:  # pragma: no cover
            raise FileNotFoundError(f"could not locate schema {path.name!r}") from exc
    return json.loads(path.read_text(encoding="utf-8"))


def validate_against(document: Any, schema_path: Path) -> list[str]:
    """Validate ``document`` against the schema and return error messages.

    Returns an empty list when the document is valid.
    """
    schema = load_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(document), key=lambda e: e.path):
        location = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{location}: {err.message}")
    return errors
