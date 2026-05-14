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

The end-to-end live runs (10-paper demo corpus, Gemma 4 31B IT
generation, post-P5.1) surfaced these calibration patterns. They are
**expected** — documenting them so maintainers don't keep
re-discovering them — and should be revisited whenever the rubric or
judge models are bumped. Two judge models have been exercised so far:
`meta-llama/llama-3.3-70b-instruct` (the first run, when frontier
providers were TOS-blocked) and `moonshotai/kimi-k2.6` (the current
production judge).

| Pattern | Where it shows up | Why it's expected | When to revisit |
| --- | --- | --- | --- |
| **Judge D fires `fatal_gap_found=True` on every Gemma baseline** | All four reference baselines hit `correctness ≤ 10`, `gap_resistance ≤ 5` under Kimi K2.6. | Gemma cannot actually prove the conjecture; "fatal gap" is the truthful verdict. The cap (≤70) doesn't bind because subscores are already far below it. | Once a baseline genuinely scores above ~60 on the unguarded axes, re-prompt Judge D to demand richer error categorisation so non-trivial improvements register. |
| **Reasoning judge models need a large `max_tokens`** | Kimi K2.6 spends ~14k tokens on the thinking block for the gold-graph / adversarial prompts. At the old `max_tokens=2048` every Judge C/D/E call returned 0 content (`finish_reason=length`) and silently fell back to `_inconclusive`. | OpenRouter's `reasoning` cap (`effort` / `max_tokens` / `exclude`) is not honoured by this Kimi provider — verified all three variants. The portable lever is `DEFAULT_JUDGE_MAX_TOKENS = 24000`. | If a future judge model's reasoning block grows past ~20k tokens, raise `DEFAULT_JUDGE_MAX_TOKENS`. `chat()` now raises a clear `finish_reason=length` error so this is obvious from logs. |
| **Survey-only cap (≤45) rarely binds** | `zero_shot` / `agentic_self_critique` emit 0 `new_lemmas`, so Judge A attaches the survey-only cap — but the weighted score is already ~30, well below 45, so it never binds. The submission is still `FLAGGED` (P5.1 verdict logic counts non-binding caps). | The participant proxy rejects `tools` / structured-output server features (P1 policy); baselines rely on prompt engineering alone and score low on their own merits. | If baselines start reaching the 45+ band, the survey-only cap will begin to bind and should be revisited. |
| **Judge B conjecture-statement carve-out is mandatory** | Without `_filter_conjecture_statements` (P5.1) every `target_theorem` literal triggered a CONTAMINATED DQ. | "Every Kakeya set in R^n has Hausdorff dimension n" has been public since 1971 but is also the first sentence of arXiv:2502.17655. | Whenever the gold paper is replaced or the judge model rotated, re-test the conjecture-statement test bench in `tests/test_judge_llm_layers.py`. |
| **arXiv ID schema must accept pre-2007 short form** | The Kakeya canon (Tao 1998 `9807163`, Katz 2000 `0010069`, Wolff 2002 `0102135`) is heavily pre-2007. | The new `YYMM.NNNNN` format only started in April 2007. | If a future regex rotation re-tightens the pattern, run the live baselines and check `protocol` / `clarity` for any retrieval baseline. |
| **Judge model strongly compresses the score band** | Same four baselines, same corpus: Llama 3.3 70B produced 35.8-52.2; Kimi K2.6 produced 29.2-34.2. The *ordering* is stable across both (planner_verifier #1, then zero_shot / agentic, rag_synthesis last). | Kimi K2.6 is a stricter adversarial reviewer — `gold_graph`, `correctness`, `gap_resistance` and `novelty` all score lower. Absolute scores are only comparable within one `evaluation_id`; the leaderboard versions them for exactly this reason. | When rotating the judge model, re-baseline all four and publish the new `evaluation_id` alongside the old. Do **not** compare scores across judge models. |
| **`target_theorem_match` is high even for non-solutions** | Kimi K2.6 gives 90-100 on Judge C's `target_theorem_match` for every baseline. | Every baseline correctly *states* the conjecture; that axis only measures whether the harness aimed at the right theorem, not whether it proved it. The `core_mechanism` / `lemma_chain` axes (0-25) carry the real signal. | If a harness games `target_theorem_match` without progress elsewhere, down-weight it in the rubric. |

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
