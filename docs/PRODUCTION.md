# Production

Production is not fully wired through yet. This document records the intended
pieces and the current local-test path.

```text
proxy                         model API gate
harnesses/tools/restricted_search  OpenAlex/Exa search tools
runner                        Docker sandbox
judge                         evaluation stack
```

## 1. Start The Model Proxy

```bash
OPENROUTER_KEY=xxx \
uvicorn proxy.main:app --host 0.0.0.0 --port 8080
```

The proxy rejects native tools, web-search payloads, OpenRouter web plugins, and
provider fallback.

## 2. Restricted Search

Current local testing uses direct command tools:

```text
openalex_search.py
exa_search.py
```

The FastAPI wrapper exists in `harnesses/tools/restricted_search/main.py`, but
the official runner integration is still not the blessed path.

## 3. Validate A Harness

```bash
python3 -m runner.cli validate harnesses/model_rag
```

## 4. Run A Harness

```bash
bash harnesses/codex/run.sh \
  --task tasks/kakeya3d_discovery.yaml \
  --output runs/codex/output
```

This `run.sh` command is currently a local test/debug path. The Docker runner
flow still needs to be completed and validated.

## 5. Judge A Run

```bash
python3 -m scripts.judge_submission \
  --submission runs/model_rag/output \
  --task tasks/kakeya3d_discovery.yaml \
  --report-out runs/model_rag/evaluation_report.json
```

The judge reads `target_paper.arxiv_id` from the task and keeps private judge
files under `judge/vault/<task-yaml-name>/`.

## 6. Build Leaderboard

```bash
python3 -m scripts.build_leaderboard \
  --submissions submissions \
  --out leaderboard/static
```
