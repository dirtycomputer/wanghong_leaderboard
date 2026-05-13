# Public rules — alpha

> **Status:** alpha. The wording, weights, and caps below are stable
> for the duration of `rubric_version = kakeya3d-rubric-v0.1`. Bumps
> to the rubric version will be announced and historical scores will
> remain visible under their original `evaluation_id`.

## One-sentence rule

A submission is a Dockerized harness that may use **only**
`google/gemma-4-31b-it` through the official leaderboard OpenRouter
proxy and a fixed arXiv time-capsule corpus of papers submitted before
**2025-01-01 GMT**. The goal is to independently produce a proof-level
solution to — or maximal progress on — the **three-dimensional Kakeya
set conjecture**. Any use or apparent recall of post-cutoff sources,
including `arXiv:2502.17655`, is marked contaminated or disqualified.

## Corpus policy

- Public corpus is built only from arXiv records with
  `submittedDate < 2025-01-01 00:00:00 GMT`.
- Each paper PDF is parsed by MinerU v4 (`model_version: "vlm"`); the
  resulting `full.md`, `images/`, and `content_list.json` are the only
  representation participants see.
- `corpus_hash` is the SHA-256 of the canonical, sorted manifest. The
  hash is part of every run's recorded metadata so submissions made
  against different corpus snapshots remain distinguishable on the
  leaderboard.
- The target paper `arXiv:2502.17655` is held only in the private judge
  vault. The corpus orchestrator's blocklist + the manifest builder's
  defence-in-depth check both refuse to add it; `scripts/parse_target_paper.py`
  in turn refuses to run if the target id ever appears in the public
  manifest.

## Submission format

- Submit one of:
  1. **GitHub repo URL + commit SHA** (recommended).
  2. **Immutable Docker image** referenced as `name@sha256:<digest>`.
     Floating tags (`latest`, `main`, version aliases) are rejected.
  3. **Local bundle** produced by `kakeya-lb bundle` (later phase).
- Every submission must include a `harness.yaml` validating against
  `schemas/harness_manifest.schema.json` and an executable `./run.sh`.
- The run output directory must contain exactly five files:
  `final_proof.md`, `proof_graph.json`, `cited_sources.json`,
  `self_critique.md`, `trace.jsonl`. The `proof_graph.json` must
  validate against `schemas/proof_graph.schema.json`.

## Runtime sandbox

- Containers run on a custom Docker network named `kakeya-internal`
  with `--internal` (no external egress; only the leaderboard proxy is
  reachable).
- `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only`
  root filesystem, `--tmpfs /tmp`, `--pids-limit 4096`,
  `--ulimit nofile=4096:4096`.
- CPU / memory / wall-time / model-call budgets are enforced from
  `harness.yaml` and capped by the runner's own ceilings.
- The container is given only an **ephemeral run token**; it never
  sees `OPENROUTER_KEY`, `OPENROUTER_JUDGE_KEY`, or `MINERU_KEY`.

## Generation policy (participant side)

- Model is pinned to `google/gemma-4-31b-it` via the official proxy.
- `:online` model suffixes are rejected.
- `tools`, `tool_choice`, `tool_results`, `functions`, `function_call`,
  `web_search_options` and OpenRouter server tools are rejected.
- The only allowed plugin entry is `{"id":"web","enabled":false}`.
- Provider routing is pinned by the proxy; fallbacks are disabled.
- The participant container has no general internet egress; the only
  reachable endpoint is the leaderboard proxy.
- The MinerU API key and the judge OpenRouter key are never mounted
  into participant containers.

## Evaluation policy (judge side)

- Latest LLMs are allowed for judging.
- Web access (including OpenRouter `:online` and server tools) is
  allowed for the contamination-audit judge.
- The target paper `arXiv:2502.17655` is held in a private judge vault.
- Scores are versioned by `evaluation_id`; updating the judge model or
  the gold graph creates a new versioned score, never an in-place
  overwrite.

## Hard caps

Applied by the rubric (`judge/rubric.py`) after weighted scoring.
The lowest binding cap wins.

| Condition | Cap | Source |
| --- | --- | --- |
| Direct mention of `arXiv:2502.17655`, the verbatim paper title, or `Wang-Zahl` | DQ | Judge A protocol |
| Cited arXiv id is not in the time-capsule corpus manifest | DQ | Judge A protocol |
| Missing any of the five required output files | DQ | Judge A protocol |
| Judge B confirms `severity: major` post-cutoff evidence | DQ | Judge B contamination |
| Judge B recommends `disqualify` or `contaminated_not_ranked` | DQ | Judge B contamination |
| Judge E classifies submission as `leak` | DQ | Judge E novelty |
| Only literature survey, no new lemmas | ≤ 45 | Judge A protocol |
| Major (sub-fatal) gap or key lemma only sketched | ≤ 65 | Judge D adversarial |
| Fatal mathematical gap in the proof chain | ≤ 70 | Judge D adversarial |
| Judge B reports `severity: moderate` post-cutoff risk | ≤ 80 | Judge B contamination |
| Expert-accepted proof-level route | ≥ 90 | weighted score |

## Scoring axes (sum to 100)

| Axis | Weight | Source |
| --- | --- | --- |
| Protocol / contamination / reproducibility | 20% | Judges A + B |
| Hidden gold-graph alignment | 25% | Judge C |
| Mathematical correctness | 25% | Judge D |
| Adversarial gap resistance | 15% | Judge D |
| Novelty / independence | 10% | Judge E |
| Clarity / auditability | 5% | Judge A |

## Evaluation versioning

Every `evaluation_report.json` records `evaluation_id`,
`rubric_version` (`kakeya3d-rubric-v0.1`), the judge model slugs (B, C,
D, E), the SHA-256 of the gold proof graph in use, and the SHA-256 of
the MinerU parse of the target paper. Updating the rubric or any
judge model produces a *new* versioned score and does not silently
overwrite older ones on the public leaderboard. See
[`docs/EVAL_VERSIONING.md`](EVAL_VERSIONING.md) for the full lifecycle
description.

## Reference baselines

The leaderboard team publishes four maintained reference scores
against every corpus / rubric / judge-model version. They run the
same participant API surface as third-party submissions:

| Baseline | Calls | What it does |
| --- | --- | --- |
| `zero_shot` | 1 | one Gemma call, no retrieval, no planning |
| `rag_synthesis` | 1 | keyword retrieval over `corpus/` + single synthesis |
| `planner_verifier` | 3 | planner → hostile verifier → reviser |
| `agentic_self_critique` | ≤ 9 | retrieve → propose → self-critique loop with a budget |

Code: `baselines/`. CLI: `python -m scripts.run_baseline --baseline <name> …`.
Every baseline is unit-tested with a mocked Gemma client so the
reference scores stay reproducible even when the proxy / judge keys
rotate.
