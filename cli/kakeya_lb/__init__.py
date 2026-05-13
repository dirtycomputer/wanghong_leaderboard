"""``kakeya-lb`` — local helper CLI for Wang Hong leaderboard participants."""

from cli.kakeya_lb.schemas import (
    HARNESS_MANIFEST_SCHEMA_PATH,
    PROOF_GRAPH_SCHEMA_PATH,
    RUN_MANIFEST_SCHEMA_PATH,
    load_schema,
    validate_against,
)

__all__ = [
    "HARNESS_MANIFEST_SCHEMA_PATH",
    "PROOF_GRAPH_SCHEMA_PATH",
    "RUN_MANIFEST_SCHEMA_PATH",
    "load_schema",
    "validate_against",
]
