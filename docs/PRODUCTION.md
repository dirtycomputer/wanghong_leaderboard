# Production

Production has four moving pieces:

```text
proxy                         model API gate
harnesses/tools/restricted_search  Exa search gate
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

## 2. Start Restricted Search

```bash
EXA_API_KEY=xxx \
RESTRICTED_SEARCH_CUTOFF=2025-01-01T00:00:00Z \
uvicorn harnesses.tools.restricted_search.main:app --host 0.0.0.0 --port 8088
```

If `RESTRICTED_SEARCH_TOKEN` is set, pass the same value to the runner as
`--search-api-key`.

## 3. Validate A Harness

```bash
python3 -m runner.cli validate harnesses/model_rag
```

## 4. Run A Harness

```bash
python3 -m runner.run_harness \
  --harness harnesses/model_rag \
  --task path/to/task.yaml \
  --output runs/model_rag/output \
  --model-api-base http://proxy:8080/v1 \
  --model-api-key "$MODEL_API_KEY" \
  --search-api-base http://restricted-search:8088
```

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
