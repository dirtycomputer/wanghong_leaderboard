# Published submissions

Every directory under this tree corresponds to one harness; every
nested directory is one `evaluation_id`. The leaderboard workflow
(`.github/workflows/leaderboard.yml`) recursively reads every
`evaluation_report.json` here and renders the public site.

## Layout

```
submissions/
  baselines/
    zero_shot/
      eval-20260513T205339Z/
        evaluation_report.json
    rag_synthesis/
      eval-20260513T205411Z/
        evaluation_report.json
    planner_verifier/
      eval-20260513T205434Z/
        evaluation_report.json
    agentic_self_critique/
      eval-20260513T205458Z/
        evaluation_report.json

  community/
    <harness-name>/
      <eval-id>/
        evaluation_report.json
```

## Publishing a new score

1. Score the submission locally / on a private runner:

   ```bash
   python -m scripts.judge_submission \
       --submission runs/example/output \
       --gold-graph judge/vault/gold_graph.json
   ```

2. **Redact** the resulting `evaluation_report.json` before committing.
   The unredacted form contains LLM `raw_text` fields plus
   `judges.C.missing_gold_nodes` / `judges.C.notes` and
   `judges.B.suspect_passages`, all of which can leak the hidden gold
   proof graph or the contamination phrase bank:

   ```bash
   python -m scripts.redact_report \
       runs/example/output/evaluation_report.json \
       --out submissions/baselines/example/eval-20260513T205411Z/evaluation_report.json
   ```

3. Commit and push. The Pages workflow picks up the new report on its
   next run.

```bash
git add submissions/
git commit -m "Score example baseline @eval-20260513T205411Z (45.0, FLAGGED)"
git push
```

## What NOT to commit

- Unredacted `evaluation_report.json` (run `scripts/redact_report.py` first).
- Any file under `judge/vault/` — the gold graph and target paper parse
  are the leaderboard's hidden assets.
- `proof_graph.json` / `final_proof.md` / `cited_sources.json` from the
  submission output. Only the redacted `evaluation_report.json` is
  needed for the public leaderboard.
