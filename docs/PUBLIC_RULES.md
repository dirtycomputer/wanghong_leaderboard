# Public rules (draft)

> **Status:** stub. Final wording will be locked once the canary
> verdict is `CLEAN` and the corpus + judge stack are stable.

## One-sentence rule

A submission is a Dockerized harness that may use **only**
`google/gemma-4-31b-it` through the official leaderboard OpenRouter
proxy and a fixed arXiv time-capsule corpus of papers submitted before
**2025-01-01 GMT**. The goal is to independently produce a proof-level
solution to — or maximal progress on — the **three-dimensional Kakeya
set conjecture**. Any use or apparent recall of post-cutoff sources,
including `arXiv:2502.17655`, is marked contaminated or disqualified.

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

| Condition | Cap |
| --- | --- |
| Direct mention of `arXiv:2502.17655`, the verbatim paper title, or "Wang-Zahl 2025" | Disqualified / Contaminated |
| Citation of any source submitted after 2025-01-01 | Disqualified |
| Only literature survey, no new proof mechanism | ≤ 45 |
| Plausible strategy but key lemma unproved | ≤ 65 |
| Fatal mathematical gap in the proof chain | ≤ 70 |
| High gold-graph overlap with medium contamination risk | ≤ 80, flagged |
| Expert-accepted proof-level route | ≥ 90 |
