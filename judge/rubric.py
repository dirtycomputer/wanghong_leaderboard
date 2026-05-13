"""Rubric: weighted scoring + hard caps for the judge stack.

The weighted score is a convex combination of per-axis sub-scores
each in ``[0, 100]``. Caps from individual judges (DQ on protocol
violation, cap-70 on fatal gap, cap-45 on survey-only, etc.) are
applied *after* weighting via :func:`apply_rubric`.

The rubric is versioned: bumping :data:`RUBRIC_VERSION` is how we
distinguish historical scores when the weights or caps change.
"""

from __future__ import annotations

import dataclasses
from typing import Any

RUBRIC_VERSION = "kakeya3d-rubric-v0.1"

#: Convex weights (sum == 1.0). Axes:
#: - ``protocol``: Judge A + Judge B agreement on safety / reproducibility
#: - ``gold_graph``: Judge C alignment with the hidden gold graph
#: - ``correctness``: Judge D's assessment of mathematical soundness
#: - ``gap_resistance``: Judge D's gap-finding outcome (inverted severity)
#: - ``novelty``: Judge E's open-world classification
#: - ``clarity``: Judge A's audit metadata (file presence + manifest)
WEIGHTS: dict[str, float] = {
    "protocol": 0.20,
    "gold_graph": 0.25,
    "correctness": 0.25,
    "gap_resistance": 0.15,
    "novelty": 0.10,
    "clarity": 0.05,
}


@dataclasses.dataclass(frozen=True)
class Cap:
    """A score ceiling produced by a judge."""

    reason: str
    cap: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "cap": float(self.cap), "source": self.source}


@dataclasses.dataclass(frozen=True)
class RubricCaps:
    DQ_VALUE: float = 0.0
    SURVEY_ONLY: float = 45.0  # no new_lemmas at all
    KEY_LEMMA_UNPROVED: float = 65.0  # only sketched/conjectural lemmas
    FATAL_GAP: float = 70.0  # Judge D finds a fatal gap
    MEDIUM_CONTAMINATION_RISK: float = 80.0  # Judge B says "moderate"


CAPS = RubricCaps()


def weighted_score(subscores: dict[str, float]) -> float:
    """Compute the convex-combination score for the supplied axes.

    Missing axes default to 0. Each subscore is clamped to ``[0, 100]``.
    """
    total = 0.0
    for axis, weight in WEIGHTS.items():
        value = float(subscores.get(axis, 0.0))
        value = max(0.0, min(100.0, value))
        total += weight * value
    return total


def apply_rubric(
    subscores: dict[str, float],
    caps: list[Cap],
) -> tuple[float, float, list[Cap]]:
    """Return ``(weighted_score, final_score, applied_caps)``."""
    weighted = weighted_score(subscores)
    if not caps:
        return weighted, weighted, []
    min_cap = min(c.cap for c in caps)
    final = min(weighted, min_cap)
    # Only retain caps that actually bind (i.e. <= weighted score).
    binding = sorted(
        (c for c in caps if c.cap <= weighted), key=lambda c: c.cap
    )
    return weighted, final, binding


def verdict_from(final_score: float, caps: list[Cap]) -> str:
    """Map (final score, applied caps) to a public-leaderboard verdict."""
    cap_reasons = {c.reason for c in caps}
    if any("disqualified" in r.lower() for r in cap_reasons):
        return "DISQUALIFIED"
    if any("contamin" in r.lower() for r in cap_reasons):
        return "CONTAMINATED"
    if any("schema" in r.lower() or "missing" in r.lower() for r in cap_reasons):
        return "FAILED"
    if final_score == CAPS.DQ_VALUE:
        return "DISQUALIFIED"
    if caps:
        return "FLAGGED"
    return "RANKED"
