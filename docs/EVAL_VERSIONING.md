# Evaluation versioning

The Wang Hong leaderboard evaluates submissions against three moving
artefacts: the **corpus** (P2), the **rubric** (P4), and the
**judge model line-up** (P4). All three can change over time; the
versioning protocol below guarantees that historical scores remain
reproducible and that fresh scores cannot silently overwrite them.

## The four hashes / IDs every score carries

Every `evaluation_report.json` records:

| Field | Source | Bumped when … |
| --- | --- | --- |
| `corpus_hash` | `corpus/corpus_hash.txt` (P2) | a paper is added/removed, MinerU parse changes |
| `gold_graph_hash` | `judge/vault/gold_graph.json` | gold graph is re-extracted or expert-edited |
| `target_paper_parse_hash` | `judge/vault/target_paper/full.md` | target paper PDF is re-parsed |
| `rubric_version` | `judge/rubric.py::RUBRIC_VERSION` | scoring weights or cap thresholds change |
| `judge_models[].model` | `judge/orchestrator.py` (per-judge) | a frontier judge model is swapped in |
| `evaluation_id` | `judge/eval_version.py::make_evaluation_id` | every individual evaluation run |

An evaluation report from `eval-2026-05-13T08:55Z` cannot be compared
1-to-1 with one from `eval-2026-08-01T10:00Z` unless every field above
matches. The public leaderboard renders a `score@evaluation_id` column
so reviewers can pick which axis to compare on.

## Lifecycle

1. **Score:** `python -m scripts.judge_submission` writes
   `evaluation_report.json` with the four hashes + the rubric / model
   record at the moment of evaluation.
2. **Publish:** the leaderboard ingests the report and adds a row keyed
   by `(harness, corpus_hash, rubric_version, evaluation_id)`. Older
   rows are not modified.
3. **Bump:** when any of the four hashes / versions changes, run the
   relevant baselines and any pinned submissions again. Public ranking
   tables show the latest version as the primary view; older versions
   remain reachable.

## Why these axes are separate

* **Corpus drift** is genuine new knowledge — adding a paper can
  legitimately enable a strategy that was previously infeasible.
* **Rubric drift** changes the scoring function — same submission,
  different score is *not* a problem with the harness.
* **Judge-model drift** is the most subtle. Frontier model upgrades
  can both raise the ceiling (better at finding gaps) and lower it
  (more lenient on plausibility). A versioned record makes these
  shifts auditable rather than invisible.

## Rotating a judge model

Rotation procedure for the contamination / gold-graph / adversarial /
novelty judges:

1. Pick the new model slug. Confirm OpenRouter accepts it on the
   judge key (and not on the participant key).
2. Run all four baselines and all currently-pinned third-party
   submissions through `scripts.judge_submission` with the new model.
3. Compare per-axis subscores against the previous run. Investigate
   any axis that moves >10 points.
4. Bump the relevant `judge_models[].model` slug *and* note the
   shift in the public leaderboard's change log.

If the rotation also changes how caps fire (e.g. a stricter
adversarial judge starts reporting `fatal` more aggressively), bump
`RUBRIC_VERSION` as well.

## Known calibration drifts

The first end-to-end live runs (10-paper demo corpus, Llama 3.3 70B
judges, Gemma 4 31B IT generation, post-P5.1) surfaced these
calibration patterns. They are **expected** — documenting them so
maintainers don't keep re-discovering them — and should be revisited
whenever the rubric or judge models are bumped.

| Pattern | Where it shows up | Why it's expected | When to revisit |
| --- | --- | --- | --- |
| **Judge D fires `fatal_gap_found=True` on every Gemma baseline** | All four reference baselines hit `correctness ≤ 20`, `gap_resistance ≤ 40`. | Gemma cannot actually prove the conjecture; "fatal gap" is the truthful verdict. The cap (≤70) doesn't bind because subscores are already low. | Once a baseline genuinely scores above ~60 on the unguarded axes, re-prompt Judge D to demand richer error categorisation so non-trivial improvements register. |
| **Survey-only cap (≤45) is the ceiling for any baseline that fails JSON extraction** | `agentic_self_critique` produced 0 `new_lemmas` because Gemma's final-summary call returned malformed JSON. | The participant proxy intentionally rejects `tools` / `function_call` / structured-output server features (P1 policy). Baselines must rely on prompt engineering alone. | If/when reliable structured output becomes available without breaking the time-capsule policy, lift this for baselines (not for participants). |
| **Judge B conjecture-statement carve-out is mandatory** | Without `_filter_conjecture_statements` (P5.1) every `target_theorem` literal triggered a CONTAMINATED DQ. | "Every Kakeya set in R^n has Hausdorff dimension n" has been public since 1971 but is also the first sentence of arXiv:2502.17655. | Whenever the gold paper is replaced or the judge model rotated, re-test the conjecture-statement test bench in `tests/test_judge_llm_layers.py`. |
| **arXiv ID schema must accept pre-2007 short form** | The Kakeya canon (Tao 1998 `9807163`, Katz 2000 `0010069`, Wolff 2002 `0102135`) is heavily pre-2007. | The new `YYMM.NNNNN` format only started in April 2007. | If a future regex rotation re-tightens the pattern, run the live baselines and check `protocol` / `clarity` for any retrieval baseline. |
| **Score range for unprepared baselines clusters at 35-52** | Post-P5.1 reference scores: `planner_verifier` 52.2, `zero_shot` 45.0 (cap), `agentic` 45.0 (cap), `rag_synthesis` 35.8. | None of the baselines try to actually solve the problem. Variance comes from how well each handles the schema + survives the survey-only cap. | If baselines start reaching the 60+ band, the survey-only cap probably needs raising (right now it dominates the band). |
| **Llama 3.3 70B as judge is acceptable but conservative** | Provider TOS blocks Anthropic / OpenAI / Google models on the experiment account; judges fall back to Llama. | Llama 70B is competent at structural alignment but more lenient on adversarial gap-finding than a frontier model. | Once a frontier judge model is reachable on the judge OpenRouter key, run all four baselines through it and record the new `evaluation_id` alongside the Llama scores in `docs/EVAL_VERSIONING.md`. |

When updating the rubric, judges, or gold graph, the maintainer
checklist is:

1. Re-run the four reference baselines with `scripts.run_baseline`.
2. Re-score them with `scripts.judge_submission`.
3. If any score moves >10 points on a single axis without an obvious
   cause, add a row to this table before publishing the new
   `rubric_version` / `evaluation_id`.

## Building a new gold graph

The MVP gold graph (`source: "llm_extraction"`) is replaced before the
public beta with an `expert_curated` version. The replacement procedure:

1. Re-run `python -m scripts.parse_target_paper` (only if MinerU is
   re-run; otherwise the existing parse remains the source of truth).
2. Hand the parse to two reviewers in harmonic analysis / GMT.
3. They edit `judge/vault/gold_graph.json` in place, set
   `judge/vault/gold_graph_meta.json::expert_reviewed = true`, and
   sign off.
4. The SHA-256 of `gold_graph.json` changes → `gold_graph_hash` in
   future reports also changes → leaderboard creates a new column.
