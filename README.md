# Wanghong Leaderboard

This repo runs self-contained harnesses for the Wang Hong 3D Kakeya task.

The current design is intentionally simple:

```text
harnesses/<name>/
  harness.yaml
  run.sh
  prompts/
  config/
  src/
```

The runner mounts one harness directory at `/harness` and executes only
`./run.sh`. Harnesses do not receive a local corpus. If a harness needs search,
it must use the shared restricted Exa service under `harnesses/tools`.

## Main Pieces

| Path | Purpose |
| --- | --- |
| `harnesses/` | All runnable harnesses and shared harness tools. |
| `harnesses/tools/restricted_search/` | Exa-backed search service with a pre-cutoff publication-date filter. |
| `runner/` | Docker sandbox runner for one `harnesses/<name>` directory. |
| `proxy/` | OpenAI/OpenRouter-compatible model proxy that blocks native tools and web search. |
| `runner/cli.py` | Small validation commands for harness schemas. |
| `schemas/` | JSON schemas for harness metadata, run metadata, citations, proof graphs, and evaluations. |
| `judge/` | Evaluation stack for completed harness outputs. |
| `leaderboard/` | Aggregation and static leaderboard rendering. |
| `scripts/` | Operational scripts for canary checks, judging, gold graph extraction, and leaderboard builds. |
| `tests/` | Unit tests for the current pipeline. |

## Run A Harness

Validate a harness directory:

```bash
uv run python -m runner.cli validate harnesses/model_rag
```

Start restricted search:

```bash
EXA_API_KEY=xxx \
RESTRICTED_SEARCH_CUTOFF=2025-01-01T00:00:00Z \
uv run python -m uvicorn harnesses.tools.restricted_search.main:app --host 0.0.0.0 --port 8088
```

Run a harness:

```bash
uv run python -m runner.run_harness \
  --harness harnesses/model_rag \
  --task tasks/kakeya3d_discovery.yaml \
  --output path/to/output \
  --model-api-base http://proxy:8080/v1 \
  --model-api-key "$MODEL_API_KEY" \
  --search-api-base http://restricted-search:8088
```

The harness must write:

```text
final_proof.md
proof_graph.json
cited_sources.json
self_critique.md
trace.jsonl
```

It may also write `run_manifest.json`.

## Environment

Copy `.env.example` and fill the keys you need:

| Variable | Used by |
| --- | --- |
| `OPENROUTER_KEY` | Participant model proxy. |
| `OPENROUTER_JUDGE_KEY` | Judge models. Never exposed to harness containers. |
| `EXA_API_KEY` | Restricted search service. |
| `RESTRICTED_SEARCH_TOKEN` | Optional auth token for restricted search. |
| `GEMMA_PROVIDER_SLUG` | Optional provider pin for reproducibility. |
| `PROXY_AUDIT_DIR` | Proxy JSONL audit logs. |

## Current Flow

1. Put or create a harness under `harnesses/<name>/`.
2. Validate `harness.yaml` with `kakeya-lb validate`.
3. Start the model proxy and restricted search service.
4. Run the harness through `runner.run_harness`.
5. Judge the output with `scripts.judge_submission`.
6. Aggregate reports with `scripts.build_leaderboard`.
