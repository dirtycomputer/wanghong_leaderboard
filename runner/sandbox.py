"""Docker-backed sandbox for self-contained harness directories.

The module is split so each side effect (subprocess, filesystem) is
isolated and tested in mocks:

* :func:`is_immutable_image_reference` — pure string check; the only
  acceptable image reference is ``<name>@sha256:<64 hex>``.
* :func:`validate_harness_safety` — refuses native tools and unsafe
  entrypoints.
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
    harness_dir: Path
    entrypoint: str
    capabilities: dict[str, bool]
    task_path: Path
    output_dir: Path
    proxy_api_base: str
    proxy_token: str
    cpu: int
    memory_gb: int
    max_wall_time_seconds: int
    search_api_base: str | None = None
    search_token: str | None = None
    search_cutoff: str = "2025-01-01T00:00:00Z"
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


def validate_harness_safety(manifest: dict[str, Any], harness_dir: Path) -> None:
    """Raise :class:`SandboxError` if the harness is not runnable safely."""
    capabilities = manifest.get("capabilities") or {}
    if capabilities.get("native_tools") is not False:
        raise SandboxError("capabilities.native_tools must be false")

    entrypoint = str(manifest.get("entrypoint") or "")
    if entrypoint != "./run.sh":
        raise SandboxError("entrypoint must be ./run.sh")
    run_sh = Path(harness_dir) / "run.sh"
    if not run_sh.exists():
        raise SandboxError(f"entrypoint {run_sh} not found")
    if not run_sh.is_file():
        raise SandboxError(f"entrypoint {run_sh} is not a file")


def build_docker_command(config: SandboxConfig) -> list[str]:
    """Build the ``docker run`` argv. Pure — does not invoke subprocess."""
    if not is_immutable_image_reference(config.image_ref):
        raise SandboxError(
            f"image reference {config.image_ref!r} is not immutable; "
            "submissions must pin name@sha256:<digest>"
        )
    if config.entrypoint != "./run.sh":
        raise SandboxError("entrypoint must be ./run.sh")
    if config.capabilities.get("native_tools") is not False:
        raise SandboxError("capabilities.native_tools must be false")
    if config.capabilities.get("restricted_search") and not config.search_api_base:
        raise SandboxError("restricted_search=true requires search_api_base")

    env: list[tuple[str, str]] = [
        ("RUN_ID", config.run_id),
        ("DISABLE_NATIVE_TOOLS", "1"),
        ("DISABLE_NATIVE_WEB_SEARCH", "1"),
    ]
    if config.capabilities.get("model"):
        env.extend(
            [
                ("MODEL_API_BASE", config.proxy_api_base),
                ("MODEL_API_KEY", config.proxy_token),
                ("MODEL_NAME", "google/gemma-4-31b-it"),
            ]
        )
    if config.capabilities.get("restricted_search"):
        assert config.search_api_base is not None
        env.extend(
            [
                ("SEARCH_API_BASE", config.search_api_base),
                ("SEARCH_CUTOFF", config.search_cutoff),
            ]
        )
        if config.search_token:
            env.append(("SEARCH_API_KEY", config.search_token))

    cmd: list[str] = [
        "docker", "run",
        "--rm",
        "--name", f"kakeya-{config.run_id}",
        "--network", config.network,
        "--workdir", "/harness",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:size=512m",
        "--cpus", str(config.cpu),
        "--memory", f"{config.memory_gb}g",
        "--pids-limit", str(_DEFAULT_PIDS_LIMIT),
        "--ulimit", "nofile=4096:4096",
        "--stop-timeout", "30",
        "-v", f"{config.harness_dir.resolve()}:/harness:ro",
        "-v", f"{config.task_path.resolve()}:/task/task.yaml:ro",
        "-v", f"{config.output_dir.resolve()}:/output:rw",
    ]
    for key, value in env:
        cmd.extend(["-e", f"{key}={value}"])
    for key, value in config.extra_env:
        cmd.extend(["-e", f"{key}={value}"])

    cmd.append(config.image_ref)
    cmd.extend(
        [
            config.entrypoint,
            "--task", "/task/task.yaml",
            "--output", "/output",
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
