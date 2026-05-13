#!/usr/bin/env bash
# Entry point invoked by the official runner. Forwards the standard
# arguments to the Python harness and returns its exit code.
#
# The official runner always passes:
#   --task           path inside the container to task.yaml
#   --corpus         path inside the container to /corpus (read-only)
#   --output         path inside the container to /output (read-write)
#   --model-api-base proxy URL (the only reachable host)
#   --model-api-key  ephemeral run token issued by the runner
set -euo pipefail

exec python -m src.main "$@"
