# Wanghong Leaderboard

This repo is building a leaderboard for the Wang Hong 3D Kakeya discovery
test. The goal is to evaluate whether different harnesses can make real
pre-cutoff progress toward the 3D Kakeya conjecture.

The current implementation is intentionally simple and still in local-test
mode. The harness `run.sh` files are the practical way to test a harness now;
the full Docker runner path is not fully wired through yet.

## Current Shape

```text
tasks/
  kakeya3d_discovery.yaml

harnesses/
  codex/
    run.sh
    harness.yaml
    prompts/
    .codex/
    tools/
      openalex_search.py
      exa_search.py

  tools/
    restricted_search/
      openalex.py
      exa.py
      main.py
      test.sh

judge/
runner/
proxy/
schemas/
scripts/
```

## Search Logic

There are two restricted search providers:

```text
harnesses/tools/restricted_search/openalex.py
harnesses/tools/restricted_search/exa.py
```

`openalex.py` uses OpenAlex with:

```text
to_publication_date:2025-01-01
```

`exa.py` uses Exa with:

```text
endPublishedDate: 2025-01-01T00:00:00Z
```

and then locally drops results with no publication date or with a date after the
cutoff.

OpenAlex does not need an API key. Exa needs:

```bash
EXA_API_KEY=...
```

in `.env`.

Test the two search tools:

```bash
cd /inspire/qb-ilm/project/exploration-topic/public/lzjjin/wanghong_leaderboard
source .venv/bin/activate
bash harnesses/tools/restricted_search/test.sh
```

## Codex Harness

The Codex harness lives in:

```text
harnesses/codex/
```

Codex does not use native web search. It only gets two local commands on PATH:

```bash
openalex_search.py "query" 5
exa_search.py "query" 5
```

Those commands call the shared restricted-search functions above.

Run the Codex harness locally:

```bash
cd /inspire/qb-ilm/project/exploration-topic/public/lzjjin/wanghong_leaderboard
source .venv/bin/activate

bash harnesses/codex/run.sh \
  --task tasks/kakeya3d_discovery.yaml \
  --output runs/codex/output
```

Important: this `run.sh` path is currently for local testing/debugging. The
official Docker runner flow still needs to be finished and validated.

## Required Output Files

Each harness should write:

```text
final_proof.md
proof_graph.json
cited_sources.json
self_critique.md
trace.jsonl
run_manifest.json
```

## Judge Flow

The task file records the target arXiv id:

```yaml
target_paper:
  arxiv_id: "2502.17655"
```

The target paper is judge-private. It is not given to the harness. The judge
uses it to build or load the private gold graph under:

```text
judge/vault/<task-yaml-name>/
```

Judge command:

```bash
python3 -m scripts.judge_submission \
  --submission runs/codex/output \
  --task tasks/kakeya3d_discovery.yaml \
  --report-out runs/codex/evaluation_report.json
```

If the gold graph is missing, the judge will need `MINERU_KEY` and
`OPENROUTER_JUDGE_KEY`.

## Environment

`.env` is local and should not be committed. Current important variables:

```text
OPENROUTER_KEY          Codex / generation model access
OPENROUTER_JUDGE_KEY    judge model access
MINERU_KEY              target-paper parsing for judge
EXA_API_KEY             Exa restricted search
RESTRICTED_SEARCH_CUTOFF default 2025-01-01T00:00:00Z
```

## Status

Working now:

```text
OpenAlex restricted search
Exa restricted search
Codex local run.sh path
Judge-side target-paper vault flow
```

Not finished yet:

```text
Official Docker runner integration
MCP wrapper for restricted search
Claude Code harness wiring
Full production launch path
```
