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
