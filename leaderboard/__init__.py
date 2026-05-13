"""Static-site generator for the public Wang Hong leaderboard.

Reads ``evaluation_report.json`` files emitted by the judge stack
(:mod:`scripts.judge_submission`) and renders a small static site:

* ``index.html`` — current score table sorted by ``final_score``,
  one row per harness (latest ``evaluation_id``); a separate section
  enumerates every contamination / DQ event ever observed.
* ``submissions/<slug>.html`` — per-submission detail page showing
  per-axis subscores, applied caps, the judge model line-up that
  produced the score, and links to the historical evaluations of the
  same harness.
* ``static/style.css`` — vendored stylesheet.

The site is intentionally JS-free so it can be hosted on GitHub
Pages, S3, or any static file server.
"""

from leaderboard.aggregate import (
    EvaluationRecord,
    HarnessHistory,
    aggregate,
    contamination_events,
    load_reports,
)
from leaderboard.render import render_site

__all__ = [
    "EvaluationRecord",
    "HarnessHistory",
    "aggregate",
    "contamination_events",
    "load_reports",
    "render_site",
]
