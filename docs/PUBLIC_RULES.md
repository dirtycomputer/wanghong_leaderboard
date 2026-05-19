# Public Rules

Harnesses must be self-contained directories under `harnesses/<name>/`.

Each harness provides:

```text
harness.yaml
run.sh
```

`run.sh` is the only runtime entrypoint. The official runner mounts the harness
at `/harness`, mounts the task at `/task/task.yaml`, mounts output at `/output`,
and executes:

```bash
./run.sh --task /task/task.yaml --output /output
```

## Allowed Access

Harnesses may use:

- `MODEL_API_BASE` and `MODEL_API_KEY` for model calls through the proxy.
- `SEARCH_API_BASE` and optional `SEARCH_API_KEY` when `restricted_search: true`.
- Files inside their own harness directory.

Harnesses may not use:

- Native web search from Codex, Claude Code, browser tools, plugins, MCP tools, or external APIs.
- Floating Docker image tags. Images must be pinned as `name@sha256:<digest>`.
- Direct upstream model credentials.

## Search

Search is provided by `harnesses/tools/restricted_search`.

The service uses Exa and enforces a publication-date cutoff. The default cutoff
is:

```text
2025-01-01T00:00:00Z
```

Harnesses that need retrieval should call `SEARCH_API_BASE/search`.

## Outputs

Every harness must write:

```text
final_proof.md
proof_graph.json
cited_sources.json
self_critique.md
trace.jsonl
```

The optional `run_manifest.json` records harness name, version, kind, model,
restricted-search metadata, and output filenames.

## Evaluation

Judge A performs deterministic protocol checks and contamination phrase checks.
The remaining judges score contamination, gold-graph alignment, adversarial
gaps, and novelty.
