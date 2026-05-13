# wanghong_leaderboard

Time-capsule leaderboard for the **Wang Hong test**: can a harness,
restricted to a pre-2025-01-01 knowledge frontier, independently reach a
proof-level solution to the **three-dimensional Kakeya set conjecture**?

Inspired by Demis Hassabis's "Einstein test" framing — truncate the
model's knowledge before a major result and check whether the harness
can re-derive it from first principles + open literature.

## What's in this repository (P1 + P2 + P3 slices)

**P1 — proxy + canary** (merged):

| Path | Purpose |
| --- | --- |
| `proxy/policy.py` | Hard request validation: pinned model, no `:online`, no tools, no plugins (web disabled), no server tools, provider pinning. |
| `proxy/client.py` | Thin OpenRouter client that internally enforces the same policy. |
| `proxy/main.py` | FastAPI front-end exposing `/v1/chat/completions` for participant harnesses. |
| `proxy/audit_log.py` | Append-only JSONL audit log of every request/response/violation. |
| `scripts/canary_gemma.py` | Run the contamination canary against `google/gemma-4-31b-it`. |
| `scripts/canary_prompts.yaml` | Probes + contamination phrase bank for the canary. |

**P2 — time-capsule corpus** (PR #2):

| Path | Purpose |
| --- | --- |
| `corpus/seed_keywords.yaml` | Public arXiv search seeds + cutoff + blocklist (target paper id). |
| `corpus/harvest_arxiv.py` | Atom-feed paginator with strict `submittedDate < 2025-01-01 GMT` filter and per-PDF SHA-256. |
| `corpus/mineru_parse.py` | MinerU v4 batch URL client (model_version=`vlm`); curates `full.md` / `images/` / `content_list.json`. |
| `corpus/manifest.py` | Deterministic `manifest.jsonl` + `corpus_hash` (SHA-256 of canonical sorted entries). |
| `scripts/build_corpus.py` | Orchestrator: seeds → harvest → MinerU → manifest. |
| `scripts/parse_target_paper.py` | Vault pipeline for `arXiv:2502.17655` → `judge/vault/target_paper/` (never enters public corpus). |
| `tests/` | Mocked-HTTP tests for arXiv parsing, cutoff enforcement, MinerU zip curation, manifest determinism, vault cross-leak guard. |

**P3 — runner + schemas + starter** (merged):

| Path | Purpose |
| --- | --- |
| `schemas/proof_graph.schema.json` | Required structured proof artefact emitted by every harness; judge stack aligns against the hidden gold graph. |
| `schemas/run_manifest.schema.json` | Per-run metadata: pinned model, immutable docker digest, corpus hash, the five output paths. |
| `schemas/harness_manifest.schema.json` | What participants put in `harness.yaml`; runner validates before spending a token. |
| `runner/sandbox.py` | Builds the `docker run` command: `--network kakeya-internal` (no general egress), `--cap-drop ALL`, `--read-only`, pinned resource limits, refuses floating tags (only `name@sha256:…`). |
| `starter/` | Fork-and-go template: Dockerfile, run.sh, harness.yaml, src/main.py (single-shot baseline), src/model_client.py, src/write_outputs.py, README. |
| `cli/kakeya_lb/` | Local helper CLI: `kakeya-lb init <dir>`, `kakeya-lb validate`, `kakeya-lb schema-check`. |

**P4 — 5-layer judge stack** (PR #4):

| Path | Purpose |
| --- | --- |
| `judge/client.py` | OpenRouter client for the judge stack: reads `OPENROUTER_JUDGE_KEY`, defaults to a frontier model, optional web plugin (only B / E need it). |
| `judge/a_protocol.py` | Pure-program checks: schema validation, citation containment vs `corpus/manifest.jsonl`, phrase-bank scan replaying the Gemma canary patterns. DQ caps for missing files, leaked phrases, or citations outside the corpus. |
| `judge/b_contamination.py` | Hostile contamination auditor with web search. Severity (`none → major`) maps to caps (medium → 80; major / `disqualify` action → 0). |
| `judge/c_gold_graph.py` | Per-axis structural alignment against the hidden gold proof graph (target theorem / core mechanism / lemma chain / final implication). |
| `judge/d_adversarial.py` | Hostile referee that locates the first fatal gap. Severity caps: `fatal` → 70, `major` → 65. |
| `judge/e_novelty.py` | Open-world novelty audit with web. Classification → novelty score; `leak` short-circuits to DQ. |
| `judge/orchestrator.py` | Runs A→E (short-circuits B-E if A returns a DQ cap), applies caps, writes `evaluation_report.json` matching `schemas/evaluation_report.schema.json`. Records the judge model + rubric + gold-graph hash so historical scores stay reproducible. |
| `judge/rubric.py` | Weighted score (protocol .20 / gold-graph .25 / correctness .25 / gap-resistance .15 / novelty .10 / clarity .05) and cap arithmetic. |
| `scripts/build_gold_graph.py` | LLM-only MVP extractor: `judge/vault/target_paper/full.md` → `judge/vault/gold_graph.json` (validated against `proof_graph.schema.json`). Hand-review before public beta. |
| `scripts/judge_submission.py` | End-to-end CLI: `python -m scripts.judge_submission --submission <dir> --gold-graph judge/vault/gold_graph.json`. |

**P5 — reference baselines + alpha rules** (this branch):

| Path | Purpose |
| --- | --- |
| `baselines/zero_shot.py` | Single Gemma call, no retrieval. Survey-only by design — expected to hit the rubric's 45-cap. |
| `baselines/rag_synthesis.py` | Keyword retrieval over `corpus/manifest.jsonl` + single synthesis call with top-k stuffed context. Cites the retrieved arXiv ids. |
| `baselines/planner_verifier.py` | 3-call loop: planner emits a JSON plan → hostile verifier critiques → planner revises. Extracts `new_lemmas` from the revised plan. |
| `baselines/agentic_self_critique.py` | Budget-bounded iterate-retrieve-propose-critique loop, then one final summary call that emits the full proof graph. |
| `baselines/common/` | Shared helpers (`chat`, corpus retrieval, output writer, `BaselineContext`) — every baseline is `chat`-injectable for tests. |
| `scripts/run_baseline.py` | Top-level CLI: `python -m scripts.run_baseline --baseline rag_synthesis --task ... --corpus ... --output ...`. |
| `docs/PUBLIC_RULES.md` | Alpha-ready rules: corpus / runtime / generation / evaluation policies, hard caps, scoring axes, eval versioning, reference baselines. |
| `docs/EVAL_VERSIONING.md` | Lifecycle for the four version axes (corpus / gold-graph / rubric / judge models) and how the leaderboard preserves historical scores. |

Subsequent slices (P6 public leaderboard web UI) build on top of this.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 1. Configure secrets
cp .env.example .env
# fill in OPENROUTER_KEY, leave the others until later phases

# 2. Sanity tests
.venv/bin/python -m pytest -q

# 3. Run the Gemma contamination canary
export $(grep -v '^#' .env | xargs)
.venv/bin/python -m scripts.canary_gemma --out reports/canary

# 4. (Optional) bring up the proxy locally
.venv/bin/uvicorn proxy.main:app --host 0.0.0.0 --port 8080

# 5. Build the time-capsule corpus (P2). Requires MINERU_KEY in the env.
#    The orchestrator obeys the seed-file cutoff and blocklist, and
#    refuses to relax them.
.venv/bin/python -m scripts.build_corpus \
    --seeds corpus/seed_keywords.yaml \
    --out corpus/papers \
    --manifest-dir corpus

# 6. Parse the *target* paper into the private judge vault.
#    NEVER point this script at corpus/papers — its only output is
#    judge/vault/target_paper/.
.venv/bin/python -m scripts.parse_target_paper

# 7. Scaffold + validate a new harness locally (P3).
.venv/bin/kakeya-lb init my-harness
.venv/bin/kakeya-lb validate my-harness
.venv/bin/kakeya-lb schema-check my-harness/output  # after a run

# 8. Build the hidden gold proof graph (P4). Requires OPENROUTER_JUDGE_KEY.
.venv/bin/python -m scripts.build_gold_graph

# 9. Score a finished submission with the 5-layer judge stack.
.venv/bin/python -m scripts.judge_submission \
    --submission runs/example/output \
    --corpus-manifest corpus/manifest.jsonl \
    --gold-graph judge/vault/gold_graph.json
```

The canary writes a JSON + Markdown report to `reports/canary/`. The
exit status encodes the verdict:

- `0` — **CLEAN**: total contamination score below the per-prompt
  threshold. Safe to invest in the rest of the leaderboard.
- `1` — **SUSPICIOUS**: at least one prompt leaks; manual review of the
  Markdown report required before moving on.
- `2` — **CONTAMINATED**: the leaderboard premise is at risk. Consider
  swapping the generation model or moving the time-capsule cutoff
  before sinking effort into corpus / sandbox / judges.

## Security boundary

Two OpenRouter accounts are intentionally separated:

| Variable | Used by | Allowed |
| --- | --- | --- |
| `OPENROUTER_KEY` | Participant proxy (this repo) | `google/gemma-4-31b-it` only, no plugins, no tools, no `:online`, no server tools, provider pin, fallback disabled. |
| `OPENROUTER_JUDGE_KEY` | Judge stack (later phase) | Latest LLMs, web plugin, server tools, multi-provider — never exposed to participant containers. |
| `MINERU_KEY` | Corpus build / target-paper parse | Used outside the sandbox runner; participants never see it. |

Never commit any of these. The judge vault (`judge/vault/`) is
`.gitignore`d and will hold the parsed target paper plus the hidden
proof graph in later phases.

## Threat model summary

The participant proxy refuses any request that could exfiltrate
post-cutoff knowledge from OpenRouter:

- `model != "google/gemma-4-31b-it"`
- `model` containing `:online`
- `tools` / `tool_choice` / `tool_results` / `functions` / `function_call`
- `web_search_options`
- `plugins` other than `{"id":"web","enabled":false}`
- message bodies referencing `openrouter:web_search` / `web_fetch` / `file_search`

It also injects a hardened provider envelope: `allow_fallbacks: false`,
`require_parameters: true`, `data_collection: "deny"`, and, when
`GEMMA_PROVIDER_SLUG` is set, restricts routing to that single provider
for reproducibility.

## Roadmap

| Phase | Status | Deliverable |
| --- | --- | --- |
| P1 Bootstrap + Safety | merged | proxy + canary + tests |
| P2 Corpus pipeline | merged | arXiv harvester (`submittedDate < 2025-01-01 GMT`) + MinerU v4 parse + `manifest.jsonl` + `corpus_hash` + vault pipeline for target paper |
| P3 Runner + schemas + starter | merged | Docker sandbox runner (`--network kakeya-internal`, immutable digest only), JSON schemas, fork-and-go starter, `kakeya-lb` CLI |
| P4 Judge stack | PR #4 | 5-layer judges (protocol / contamination / gold-graph / adversarial / novelty); LLM-only gold graph for MVP; rubric + caps; evaluation_report schema |
| P5 Baselines + alpha | this PR | 4 reference baselines + `run_baseline` CLI + alpha public rules + evaluator versioning doc |
| P6 Public leaderboard | next | Web UI, anti-cheat dashboard, historical scores |

See `docs/PUBLIC_RULES.md` and `docs/EVAL_VERSIONING.md` for the full
plan.
