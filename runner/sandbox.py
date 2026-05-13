"""Docker-backed sandbox for participant harness runs.

The module is split so each side effect (subprocess, filesystem) is
isolated and tested in mocks:

* :func:`is_immutable_image_reference` — pure string check; the only
  acceptable image reference is ``<name>@sha256:<64 hex>``.
* :func:`validate_harness_manifest_safety` — refuses harnesses that
  claim external APIs or network access.
* :func:`build_docker_command` — pure constructor of the
  ``docker run …`` argv. No subprocess invocation; tested directly.
* :func:`validate_outputs` — checks the five required files exist
  after a run.
* :func:`run_in_sandbox` — composes the above and invokes ``docker``
  via subprocess. Production path; mocked in tests.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path
from typing import Any

INTERNAL_NETWORK = "kakeya-internal"

REQUIRED_OUTPUTS: tuple[str, ...] = (
    "final_proof.md",
    "proof_graph.json",
    "cited_sources.json",
    "self_critique.md",
    "trace.jsonl",
)

_IMMUTABLE_REFERENCE = re.compile(r"^[^@]+@sha256:[0-9a-f]{64}$")

_DEFAULT_PIDS_LIMIT = 4096


class SandboxError(RuntimeError):
    """Raised when the sandbox refuses to start a run or detects abuse."""


@dataclasses.dataclass(frozen=True)
class SandboxConfig:
    """Inputs required to run one harness submission.

    Paths are expressed on the host filesystem; the runner mounts them
    into the container at fixed locations.
    """

    image_ref: str  # MUST be ``name@sha256:…``
    run_id: str
    corpus_root: Path
    task_path: Path
    output_dir: Path
    proxy_api_base: str
    proxy_token: str
    cpu: int
    memory_gb: int
    max_wall_time_seconds: int
    network: str = INTERNAL_NETWORK
    extra_env: tuple[tuple[str, str], ...] = ()


@dataclasses.dataclass(frozen=True)
class SandboxRunResult:
    exit_code: int
    duration_seconds: float
    docker_command: tuple[str, ...]
    stdout_tail: str
    stderr_tail: str


def is_immutable_image_reference(reference: str) -> bool:
    """Return True iff ``reference`` is an immutable ``name@sha256:…``."""
    return bool(_IMMUTABLE_REFERENCE.match(reference or ""))


def validate_harness_manifest_safety(manifest: dict[str, Any]) -> None:
    """Raise :class:`SandboxError` if the manifest disagrees with the runtime invariants."""
    claims = manifest.get("claims") or {}
    if claims.get("uses_external_apis"):
        raise SandboxError(
            "harness.yaml claims uses_external_apis=true; the runner "
            "isolates the container and only the leaderboard proxy is reachable"
        )
    if claims.get("requires_network"):
        raise SandboxError(
            "harness.yaml claims requires_network=true; only the leaderboard "
            "proxy is reachable from the participant container"
        )


def build_docker_command(config: SandboxConfig) -> list[str]:
    """Build the ``docker run`` argv. Pure — does not invoke subprocess."""
    if not is_immutable_image_reference(config.image_ref):
        raise SandboxError(
            f"image reference {config.image_ref!r} is not immutable; "
            "submissions must pin name@sha256:<digest>"
        )

    cmd: list[str] = [
        "docker", "run",
        "--rm",
        "--name", f"kakeya-{config.run_id}",
        "--network", config.network,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:size=512m",
        "--cpus", str(config.cpu),
        "--memory", f"{config.memory_gb}g",
        "--pids-limit", str(_DEFAULT_PIDS_LIMIT),
        "--ulimit", "nofile=4096:4096",
        "--stop-timeout", "30",
        "-v", f"{config.corpus_root.resolve()}:/corpus:ro",
        "-v", f"{config.task_path.resolve()}:/task/task.yaml:ro",
        "-v", f"{config.output_dir.resolve()}:/output:rw",
        "-e", f"MODEL_API_BASE={config.proxy_api_base}",
        "-e", f"MODEL_API_KEY={config.proxy_token}",
        "-e", "MODEL_NAME=google/gemma-4-31b-it",
        "-e", f"RUN_ID={config.run_id}",
    ]
    for key, value in config.extra_env:
        cmd.extend(["-e", f"{key}={value}"])

    cmd.append(config.image_ref)
    cmd.extend(
        [
            "--task", "/task/task.yaml",
            "--corpus", "/corpus",
            "--output", "/output",
            "--model-api-base", config.proxy_api_base,
            "--model-api-key", config.proxy_token,
        ]
    )
    return cmd


def validate_outputs(output_dir: Path) -> list[str]:
    """Return the list of *missing* required output filenames."""
    missing: list[str] = []
    for name in REQUIRED_OUTPUTS:
        if not (output_dir / name).exists():
            missing.append(name)
    return missing


def run_in_sandbox(
    config: SandboxConfig,
    *,
    runner: Any = subprocess,
) -> SandboxRunResult:
    """Invoke ``docker run`` with the configured constraints.

    ``runner`` defaults to the stdlib ``subprocess`` module but accepts
    any object exposing a compatible ``run`` callable; tests inject a
    fake.
    """
    cmd = build_docker_command(config)
    started = _monotonic()
    completed = runner.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=config.max_wall_time_seconds,
        check=False,
    )
    elapsed = _monotonic() - started
    return SandboxRunResult(
        exit_code=completed.returncode,
        duration_seconds=elapsed,
        docker_command=tuple(cmd),
        stdout_tail=(completed.stdout or "")[-4096:],
        stderr_tail=(completed.stderr or "")[-4096:],
    )


def _monotonic() -> float:
    import time

    return time.monotonic()
