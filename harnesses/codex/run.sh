#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export CODEX_HOME="${CODEX_HOME:-$SCRIPT_DIR/.codex}"
export PATH="$SCRIPT_DIR/tools:$PATH"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_PATH="$2"; shift 2 ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${TASK_PATH:-}" || -z "${OUTPUT_DIR:-}" ]]; then
  echo "usage: ./run.sh --task TASK.yaml --output OUTPUT_DIR" >&2
  exit 2
fi
if [[ ! -f "$TASK_PATH" ]]; then
  echo "task file not found: $TASK_PATH" >&2
  exit 1
fi
if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found on PATH" >&2
  exit 1
fi
if [[ -z "${OPENROUTER_KEY:-}" ]]; then
  echo "OPENROUTER_KEY is required for the Codex OpenRouter provider" >&2
  exit 1
fi
unset EXA_API_KEY OPENROUTER_JUDGE_KEY MINERU_KEY

mkdir -p "$OUTPUT_DIR"
TASK_PATH="$(cd "$(dirname "$TASK_PATH")" && pwd)/$(basename "$TASK_PATH")"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

{
  cat "$SCRIPT_DIR/prompts/system.md"
  printf '\n\nOutput directory: `%s`\n\n' "$OUTPUT_DIR"
  printf 'Search commands: `openalex_search.py "query" 5`, `exa_search.py "query" 5`\n\n'
  printf 'Task:\n```yaml\n'
  cat "$TASK_PATH"
  printf '\n```\n'
  cat <<'EOF'

Write exactly these output files: final_proof.md, proof_graph.json,
cited_sources.json, self_critique.md. The launcher writes run_manifest.json.
EOF
} > "$OUTPUT_DIR/codex_prompt.md"

codex exec \
  --cd "$OUTPUT_DIR" \
  --skip-git-repo-check \
  --sandbox workspace-write \
  --ignore-rules \
  --json \
  --output-last-message "$OUTPUT_DIR/codex_last_message.md" \
  -c 'mcp_servers={}' \
  -c 'tools.web_search=false' \
  - < "$OUTPUT_DIR/codex_prompt.md" > "$OUTPUT_DIR/trace.jsonl" 2> "$OUTPUT_DIR/codex_stderr.log"

cat > "$OUTPUT_DIR/run_manifest.json" <<EOF
{
  "schema_version": "1.0",
  "harness_name": "codex",
  "harness_version": "0.1.0",
  "harness_kind": "codex",
  "model": "google/gemma-4-31b-it",
  "restricted_search": {"enabled": true, "providers": ["openalex", "exa"], "cutoff": "${RESTRICTED_SEARCH_CUTOFF:-2025-01-01T00:00:00Z}"},
  "outputs": {
    "final_proof": "final_proof.md",
    "proof_graph": "proof_graph.json",
    "cited_sources": "cited_sources.json",
    "self_critique": "self_critique.md",
    "trace": "trace.jsonl"
  },
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
