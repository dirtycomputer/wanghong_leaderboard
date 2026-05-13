"""Per-run context passed to every baseline.

Holds everything the baseline needs to talk to the proxy and write
outputs: the standard ``MODEL_API_BASE`` / ``MODEL_API_KEY`` /
``MODEL_NAME`` envelope plus the task / corpus / output paths supplied
by the official runner.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

import yaml


@dataclasses.dataclass(frozen=True)
class BaselineContext:
    task_path: Path
    corpus_root: Path
    output_dir: Path
    model_api_base: str
    model_api_key: str
    model_name: str = "google/gemma-4-31b-it"

    @classmethod
    def from_env(
        cls,
        *,
        task_path: Path,
        corpus_root: Path,
        output_dir: Path,
        model_api_base: str | None = None,
        model_api_key: str | None = None,
        model_name: str | None = None,
    ) -> BaselineContext:
        return cls(
            task_path=task_path,
            corpus_root=corpus_root,
            output_dir=output_dir,
            model_api_base=(model_api_base or os.environ.get("MODEL_API_BASE", "")).rstrip("/"),
            model_api_key=model_api_key or os.environ.get("MODEL_API_KEY", ""),
            model_name=model_name or os.environ.get("MODEL_NAME", "google/gemma-4-31b-it"),
        )


def load_task(task_path: Path) -> dict[str, Any]:
    """Load the task YAML, returning an empty dict if the file is empty."""
    raw = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"task file {task_path} must be a YAML mapping")
    return raw
