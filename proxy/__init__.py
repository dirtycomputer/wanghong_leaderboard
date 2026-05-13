"""OpenRouter guard proxy for the Wang Hong (Kakeya 3D) leaderboard.

This package is the security boundary between participant harnesses and
OpenRouter. It pins the model to ``google/gemma-4-31b-it``, refuses any
request that could fetch post-cutoff information (``:online`` suffix,
``plugins`` other than disabled web, ``tools``, ``tool_choice``,
``web_search_options``, server tools), and pins provider selection so a
single submission is reproducible.
"""

from proxy.policy import (
    GEMMA_MODEL_ID,
    PolicyViolation,
    enforce_request,
    safe_provider_envelope,
)

__all__ = [
    "GEMMA_MODEL_ID",
    "PolicyViolation",
    "enforce_request",
    "safe_provider_envelope",
]
