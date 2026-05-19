"""Five-layer judge stack for the Wang Hong leaderboard.

Judges run on the *evaluation* side and intentionally have access to
post-cutoff information that the participant side does not:

* the target paper ``arXiv:2502.17655`` in ``judge/vault/``,
* a hidden LLM-extracted proof graph in ``judge/vault/<task>/gold_graph.json``,
* the latest available LLMs via ``OPENROUTER_JUDGE_KEY``,
* live web search for the contamination + novelty judges.

Layers
------
* :mod:`judge.a_protocol` — pure-program checks: schemas, citation
  containment, phrase-bank contamination, missing files.
* :mod:`judge.b_contamination` — latest LLM + web search; looks for
  post-cutoff phrase / lemma / citation matches.
* :mod:`judge.c_gold_graph` — latest LLM with the hidden gold graph in
  context; per-axis structural alignment.
* :mod:`judge.d_adversarial` — hostile referee; demands precise
  quantifiers and finds the first fatal gap.
* :mod:`judge.e_novelty` — latest LLM + web; classifies the submission
  as known / leak / pre-cutoff combination / novel route / wrong.

The :mod:`judge.orchestrator` runs all five and applies the rubric
caps before emitting ``evaluation_report.json``.
"""

from judge.client import (
    DEFAULT_JUDGE_MAX_TOKENS,
    JudgeClient,
    JudgeError,
    JudgeResponse,
)
from judge.eval_version import EvalVersion
from judge.rubric import RUBRIC_VERSION, RubricCaps, apply_rubric

__all__ = [
    "DEFAULT_JUDGE_MAX_TOKENS",
    "EvalVersion",
    "JudgeClient",
    "JudgeError",
    "JudgeResponse",
    "RUBRIC_VERSION",
    "RubricCaps",
    "apply_rubric",
]
