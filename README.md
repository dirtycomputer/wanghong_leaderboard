# wanghong_leaderboard

Time-capsule leaderboard for the **Wang Hong test**: can a harness,
restricted to a pre-2025-01-01 knowledge frontier, independently reach a
proof-level solution to the **three-dimensional Kakeya set conjecture**?

Inspired by Demis Hassabis's "Einstein test" framing — truncate the
model's knowledge before a major result and check whether the harness
can re-derive it from first principles + open literature.

## What's in this repository (P1 slice)

This branch lands the bootstrap + safety slice:

| Path | Purpose |
| --- | --- |
| `proxy/policy.py` | Hard request validation: pinned model, no `:online`, no tools, no plugins (web disabled), no server tools, provider pinning. |
| `proxy/client.py` | Thin OpenRouter client that internally enforces the same policy. |
| `proxy/main.py` | FastAPI front-end exposing `/v1/chat/completions` for participant harnesses. |
| `proxy/audit_log.py` | Append-only JSONL audit log of every request/response/violation. |
| `scripts/canary_gemma.py` | Run the contamination canary against `google/gemma-4-31b-it`. |
| `scripts/canary_prompts.yaml` | Probes + contamination phrase bank for the canary. |
| `tests/` | Unit tests for the policy and the canary scoring. |

Subsequent slices (P2 corpus, P3 sandbox runner, P4 judge stack,
P5 baselines + starter, P6 web UI) live behind this one and are
unblocked once the canary verdict is `CLEAN`.

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
| P1 Bootstrap + Safety | this PR | proxy + canary + tests |
| P2 Corpus pipeline | next | arXiv harvester (`submittedDate < 2025-01-01 GMT`) + MinerU v4 parse + `corpus_hash` |
| P3 Sandbox runner | | Docker network isolation, output schemas, starter repo |
| P4 Judge stack | | 5-layer judges (protocol / contamination / gold-graph / adversarial / novelty); LLM-only gold graph for MVP |
| P5 Baselines + alpha | | 4 baseline harnesses, public rules, evaluator versioning |
| P6 Public leaderboard | | Web UI, anti-cheat dashboard, historical scores |

See `docs/PUBLIC_RULES.md` (stub) and the design discussion in the
project notes for the full plan.
