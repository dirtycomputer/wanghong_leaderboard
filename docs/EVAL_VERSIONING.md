# Evaluation Versioning

Scores are versioned by the pieces that can change evaluation behavior:

| Field | Meaning |
| --- | --- |
| `evaluation_id` | Unique id for one evaluation run. |
| `rubric_version` | Scoring rubric version. |
| `gold_graph_hash` | Hash of `judge/vault/<task-yaml-name>/gold_graph.json`. |
| `target_paper_parse_hash` | Optional hash of the private target markdown. |
| `judge_models` | Models used by Judges B-E. |

Harness runs no longer depend on a local corpus snapshot. Retrieval is handled by
the restricted search service and recorded in `run_manifest.json` under
`restricted_search`.

When rotating judge models or changing the rubric, publish a new
`evaluation_id`. Scores should only be compared within the same rubric and judge
configuration.
