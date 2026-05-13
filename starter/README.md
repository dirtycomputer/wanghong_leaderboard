# Starter harness for the Wang Hong leaderboard

Fork this directory, replace `src/main.py` with your approach, and
submit. The official runner gives you:

| Env var | Meaning |
| --- | --- |
| `MODEL_API_BASE` | URL of the leaderboard proxy (only reachable host) |
| `MODEL_API_KEY` | Ephemeral run token, valid only for this run |
| `MODEL_NAME` | `google/gemma-4-31b-it` (do not change) |

And mounts:

| Path | Mode | Contents |
| --- | --- | --- |
| `/corpus` | read-only | The time-capsule arXiv corpus (`manifest.jsonl`, `papers/`, `corpus_hash.txt`) |
| `/task` | read-only | The task YAML |
| `/output` | read-write | Where your harness writes the five required files |

## Required outputs

You must write all five files into `/output`:

- `final_proof.md` — your written-up proof / strategy / partial result
- `proof_graph.json` — structured graph matching `schemas/proof_graph.schema.json`
- `cited_sources.json` — every corpus paper you used
- `self_critique.md` — your own list of weaknesses / gaps
- `trace.jsonl` — one JSON line per model call / tool step

## Local validation

```bash
pip install wanghong-leaderboard  # provides the kakeya-lb CLI
kakeya-lb validate .              # schema check on harness.yaml
docker build -t my-harness:dev .
```

A `kakeya-lb smoke-run .` command ships in a follow-up PR; it stands
up a fake model server so you can iterate without spending tokens.

## Hard rules

- The participant container has **no general internet egress**. Only the
  leaderboard proxy is reachable.
- The proxy rejects `:online`, `tools`, `tool_choice`, `tool_results`,
  `functions`, `function_call`, `web_search_options`, and any plugin
  other than `{"id":"web","enabled":false}`.
- Citing any source submitted after **2025-01-01 00:00:00 GMT** is
  detected by the contamination-audit judge and disqualifies the run.
- Mentioning `arXiv:2502.17655`, the verbatim title of the target
  paper, or "Wang-Zahl 2025" is also a disqualification.
