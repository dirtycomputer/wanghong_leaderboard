"""Official runner for participant harnesses.

The runner is the second security boundary (the first is the proxy).
It enforces:

* The image is referenced by an immutable ``sha256`` digest — floating
  tags (``latest``, ``main``, version aliases) are rejected.
* The container is attached to an ``--internal`` Docker network so it
  cannot reach the public internet; only approved internal services
  such as the model proxy and restricted search are reachable.
* All Linux capabilities are dropped, ``no-new-privileges`` is set,
  the process tree is pid-limited and resource-bounded.
* The participant container never sees ``OPENROUTER_KEY``; only an
  ephemeral run token issued by the runner.
"""

from runner.sandbox import (
    INTERNAL_NETWORK,
    SandboxConfig,
    SandboxError,
    SandboxRunResult,
    build_docker_command,
    is_immutable_image_reference,
    validate_harness_safety,
    validate_outputs,
)

__all__ = [
    "INTERNAL_NETWORK",
    "SandboxConfig",
    "SandboxError",
    "SandboxRunResult",
    "build_docker_command",
    "is_immutable_image_reference",
    "validate_harness_safety",
    "validate_outputs",
]
