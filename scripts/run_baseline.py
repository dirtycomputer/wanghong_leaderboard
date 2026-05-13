"""Run a maintained reference baseline by name.

The baselines are the four reference scores the leaderboard publishes
against every corpus / rubric / judge-model version. They use the same
participant API surface as third-party submissions (MODEL_API_BASE +
MODEL_API_KEY) so the official runner can also score them.

Usage::

    python -m scripts.run_baseline \
        --baseline rag_synthesis \
        --task /path/to/task.yaml \
        --corpus /path/to/corpus \
        --output runs/baseline-rag/output \
        --model-api-base "$MODEL_API_BASE" \
        --model-api-key "$MODEL_API_KEY"

Available baselines: ``zero_shot``, ``rag_synthesis``,
``planner_verifier``, ``agentic_self_critique``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from baselines import REGISTRY
from baselines.common.context import BaselineContext

logger = logging.getLogger("run_baseline")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        required=True,
        choices=sorted(REGISTRY.keys()),
        help="Which reference baseline to run.",
    )
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--model-api-base",
        type=str,
        default=os.environ.get("MODEL_API_BASE", ""),
    )
    parser.add_argument(
        "--model-api-key",
        type=str,
        default=os.environ.get("MODEL_API_KEY", ""),
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=os.environ.get("MODEL_NAME", "google/gemma-4-31b-it"),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.model_api_base or not args.model_api_key:
        logger.error(
            "MODEL_API_BASE and MODEL_API_KEY are required (either via env or --flags)"
        )
        return 2

    ctx = BaselineContext(
        task_path=args.task,
        corpus_root=args.corpus,
        output_dir=args.output,
        model_api_base=args.model_api_base.rstrip("/"),
        model_api_key=args.model_api_key,
        model_name=args.model_name,
    )

    runner = REGISTRY[args.baseline]
    logger.info("running baseline %s", args.baseline)
    summary = runner(ctx)
    logger.info("done %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
