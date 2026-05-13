"""End-to-end CLI: run the 5-layer judge stack on a submission directory.

Usage::

    python -m scripts.judge_submission \
        --submission runs/example/output \
        --corpus-manifest corpus/manifest.jsonl \
        --gold-graph judge/vault/gold_graph.json \
        --report-out runs/example/evaluation_report.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import orjson

from cli.kakeya_lb.schemas import validate_against
from judge.client import JudgeClient
from judge.orchestrator import OrchestratorClients, evaluate

logger = logging.getLogger("judge_submission")

EVAL_REPORT_SCHEMA = (
    Path(__file__).resolve().parents[1] / "schemas" / "evaluation_report.schema.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        default=Path("corpus/manifest.jsonl"),
    )
    parser.add_argument(
        "--gold-graph",
        type=Path,
        default=Path("judge/vault/gold_graph.json"),
    )
    parser.add_argument(
        "--target-parse-hash",
        type=str,
        default=None,
        help="Optional SHA-256 of judge/vault/target_paper/full.md.",
    )
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument(
        "--web-model",
        type=str,
        default=None,
        help="Override JUDGE_MODEL for B / E.",
    )
    parser.add_argument(
        "--offline-model",
        type=str,
        default=None,
        help="Override JUDGE_MODEL for C / D.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.submission.exists():
        logger.error("submission %s not found", args.submission)
        return 1
    if not args.gold_graph.exists():
        logger.error(
            "gold graph %s not found; run scripts.build_gold_graph first",
            args.gold_graph,
        )
        return 1

    web_client = JudgeClient.from_env(model=args.web_model, web_enabled=True)
    offline_client = JudgeClient.from_env(model=args.offline_model, web_enabled=False)
    clients = OrchestratorClients(web_client=web_client, offline_client=offline_client)

    report = evaluate(
        args.submission,
        clients=clients,
        gold_graph_path=args.gold_graph,
        corpus_manifest_path=(
            args.corpus_manifest if args.corpus_manifest.exists() else None
        ),
        target_paper_parse_hash=args.target_parse_hash,
    )

    schema_errors = validate_against(report, EVAL_REPORT_SCHEMA)
    if schema_errors:
        logger.warning(
            "evaluation_report does not satisfy its schema (%d issues); writing anyway",
            len(schema_errors),
        )
        for err in schema_errors:
            logger.warning("  - %s", err)

    out_path = args.report_out or (args.submission / "evaluation_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(orjson.dumps(report, option=orjson.OPT_INDENT_2))

    logger.info(
        "verdict=%s final=%.1f weighted=%.1f caps=%d",
        report["verdict"], report["final_score"], report["weighted_score"],
        len(report["applied_caps"]),
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
