# Production runbook

Operator guide for taking the leaderboard from "v0.1 in main" to
"public site with real scores."

There are **three** independent things to set up. They can land in any
order; the leaderboard renders whatever it has.

1. [GitHub Pages auto-deploy](#1-github-pages-auto-deploy) — automated.
2. [Frontier judge OpenRouter key](#2-frontier-judge-openrouter-key) —
   manual application + one-shot verification.
3. [Full corpus build](#3-full-corpus-build) — manual quota + a long
   one-shot job.

---

## 1. GitHub Pages auto-deploy

Workflow: `.github/workflows/leaderboard.yml`.

### One-time setup

1. In the repo settings → **Pages**, set the source to "GitHub Actions".
2. Push any change touching `submissions/**`, `leaderboard/**`,
   `scripts/build_leaderboard.py`, or the workflow itself.
3. The workflow builds the site from `submissions/` and deploys it.
4. The site URL appears in the deploy job's summary
   (e.g. `https://<org>.github.io/wanghong_leaderboard/`).

`workflow_dispatch` is enabled so an operator can rebuild manually
without a commit (Actions tab → Leaderboard → Run workflow).

### Publishing a new score

For every submission scored locally with
`scripts.judge_submission`, copy the **redacted** report into the
public tree:

```bash
python -m scripts.redact_report \
    runs/example/output/evaluation_report.json \
    --out submissions/baselines/example/eval-20260513T205411Z/evaluation_report.json
git add submissions/
git commit -m "Add example baseline @eval-20260513T205411Z (45.0, FLAGGED)"
git push
```

The redactor strips `raw_text`, `suspect_passages`, and
`missing_gold_nodes` / `notes` from Judge C — anything that could
leak the gold proof graph or the contamination phrase bank.
Do NOT commit unredacted `evaluation_report.json`.

### What the workflow does **not** do

- Does not score submissions. Scoring is a paid, judge-dependent step;
  the operator runs `scripts.judge_submission` locally / on a private
  runner and commits the redacted result.
- Does not pull from a private repo. Everything published is in this
  repo's `submissions/` tree.

---

## 2. Frontier judge OpenRouter key

The first live baseline run discovered the experiment account could
only reach Llama models — Anthropic / OpenAI / Google providers
returned `403 provider TOS`. Production judging should use a frontier
model so the rubric's adversarial gap-finder is meaningfully strict.

### Apply

1. Create a **separate** OpenRouter account from the participant key
   (so a participant-side compromise cannot escalate). This is the
   `OPENROUTER_JUDGE_KEY` slot in `.env`.
2. Enable billing on that account.
3. If you're outside a region the frontier provider serves, configure
   a payment method that the provider's TOS accepts (LLC, VAT id,
   etc.). The `403 provider TOS` error is usually a billing / region
   issue, not the key itself.

### Verify

Run the pre-flight check before paying for a full scoring round:

```bash
export OPENROUTER_JUDGE_KEY=sk-or-...
python -m scripts.verify_judge_key
```

Output looks like:

```
key scope:
  label              sk-or-v1-xxx...yyy
  is_free_tier       False
  usage (total)      0.0

model                                          status  notes
--------------------------------------------------------------------------------
anthropic/claude-sonnet-4.6                       OK   1-token probe ok
anthropic/claude-opus-4.7                       FAIL   403 provider declined
openai/gpt-5                                      OK   1-token probe ok
openai/gpt-4o                                     OK   1-token probe ok
google/gemini-3-pro-preview                       OK   1-token probe ok
google/gemini-2.5-pro                             OK   1-token probe ok
meta-llama/llama-3.3-70b-instruct                 OK   1-token probe ok

reachable models: 6 / 7
recommended JUDGE_MODEL: anthropic/claude-sonnet-4.6
```

### Rotate

When the judge model is bumped, add a row to
[`docs/EVAL_VERSIONING.md` § Known calibration drifts](EVAL_VERSIONING.md#known-calibration-drifts)
and re-score the four reference baselines so the new
`evaluation_id` shows up on the public leaderboard alongside the old.

---

## 3. Full corpus build

The demo runs used 10 papers and substituted `pypdf` for MinerU. A
production corpus is hundreds of pre-2025-01-01 papers parsed by the
real MinerU v4 VLM endpoint.

### Acquire keys

- **`MINERU_KEY`** — sign up at mineru.net, enable v4 API access,
  fund the account. MinerU bills per page; budget conservatively
  ($0.05-0.10 per page is typical for the VLM model).
- **`OPENROUTER_KEY`** — Gemma-4-31b-it only. This is the participant
  proxy key; keep it segregated from the judge key.

### Plan the budget

```
papers ≈ 200   # heuristic for a wide Kakeya / restriction / decoupling corpus
pages_per_paper ≈ 40   # arXiv math papers vary; expect 20-150
total_pages ≈ 8000
mineru_cost ≈ total_pages × 0.07 ≈ $560
```

The pypdf substitute is free and acceptable for **local iteration**.
The real MinerU parse is needed for **published** corpus snapshots
because the calibration baseline numbers in
[`docs/EVAL_VERSIONING.md`](EVAL_VERSIONING.md) were taken against
the MinerU output format.

### A note on arXiv rate-limiting

`export.arxiv.org` rate-limits aggressively and the limiter is
**IP-scoped and sticky** — repeated harvests in a short window earn a
`429` block that lasts well beyond a single request. The harvester
(`_fetch_arxiv_page`) retries `429` / `503` with exponential backoff
(3 / 6 / 12 / 24 s), which absorbs *transient* throttling **mid-harvest**
but is deliberately not tuned to wait out a full IP block — a corpus
build should fail loudly, not hang silently for an hour.

If you've been smoke-testing and then hit a wall of `429`s, that's the
sticky block: **wait 30–60 minutes** before the full build, and don't
run overlapping harvests.

### Build

```bash
# 1. Smoke-build 5 papers first to confirm MinerU plumbing.
#    (If this returns a wall of arXiv 429s, see the rate-limit note
#    above — wait and retry.)
python -m scripts.build_corpus --max-papers 5

# 2. Inspect corpus/manifest.jsonl and corpus_hash.txt. The hash
#    should be stable across re-runs given the same seed file.
cat corpus/corpus_hash.txt

# 3. Once you're satisfied, drop --max-papers and run the full build.
#    Expect several hours and the MinerU bill above.
python -m scripts.build_corpus

# 4. Parse the target paper into the private judge vault.
#    This must NOT enter corpus/.
python -m scripts.parse_target_paper

# 5. Extract the MVP gold proof graph and write it to judge/vault/.
#    P5.1 already showed this is shallow; expert review before the
#    public beta.
python -m scripts.build_gold_graph
```

### Confirm safety boundary

```bash
# The target paper must NOT appear anywhere under corpus/.
grep -r '2502.17655' corpus/ && echo "LEAK!" || echo "OK"

# The vault must NOT be committed.
git status --ignored judge/vault/

# Re-run the canary against the participant proxy. The hard floor of
# the project still applies — if Gemma starts knowing the target
# paper, the leaderboard premise is broken.
python -m scripts.canary_gemma
```

### Re-baseline

After a corpus rebuild, re-run the four reference baselines so the
public leaderboard reflects the new `corpus_hash`:

```bash
for B in zero_shot rag_synthesis planner_verifier agentic_self_critique; do
  python -m scripts.run_baseline --baseline "$B" \
      --task tasks/kakeya3d_discovery.yaml \
      --corpus corpus \
      --output runs/baseline-$B \
      --model-api-base http://127.0.0.1:8080/v1 \
      --model-api-key ephemeral

  python -m scripts.judge_submission \
      --submission runs/baseline-$B \
      --corpus-manifest corpus/manifest.jsonl \
      --gold-graph judge/vault/gold_graph.json \
      --report-out runs/baseline-$B/evaluation_report.json

  python -m scripts.redact_report \
      runs/baseline-$B/evaluation_report.json \
      --out submissions/baselines/$B/$(date -u +eval-%Y%m%dT%H%M%SZ)/evaluation_report.json
done

git add submissions/
git commit -m "Re-baseline against corpus $(cat corpus/corpus_hash.txt | head -c 12)"
git push
```

The Pages workflow will pick up the new reports and redeploy.

---

## Pre-launch checklist

- [ ] `python -m scripts.canary_gemma` reports `verdict: CLEAN` against the production OpenRouter key.
- [ ] `python -m scripts.verify_judge_key` shows at least one frontier model reachable.
- [ ] `corpus/corpus_hash.txt` matches what is recorded in the published `evaluation_report.json` files.
- [ ] `git status --ignored judge/vault/` confirms the vault is local only.
- [ ] `grep -r 2502.17655 corpus/` returns nothing.
- [ ] Four reference baselines are scored against the production corpus and committed under `submissions/baselines/`.
- [ ] At least one harmonic-analysis / GMT reviewer has signed off on `judge/vault/gold_graph.json` (`gold_graph_meta.json::expert_reviewed = true`).
- [ ] Pages site renders and the anti-cheat section is empty (or every entry is investigated).
