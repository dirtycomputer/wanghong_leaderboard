"""End-to-end CLI: run the 5-layer judge stack on a submission directory.

    Usage::

    python -m scripts.judge_submission \
        --submission runs/example/output \
        --task tasks/kakeya3d_discovery.yaml \
        --report-out runs/example/evaluation_report.json

By default the private judge files live under
``judge/vault/<task-yaml-name>/``.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

import orjson

from judge.client import JudgeClient
from judge.orchestrator import OrchestratorClients, evaluate
from runner.schema_utils import validate_against
from scripts import build_gold_graph
from scripts.target_paper import ensure_target_markdown, task_vault_dir

logger = logging.getLogger("judge_submission")

EVAL_REPORT_SCHEMA = (
    Path(__file__).resolve().parents[1] / "schemas" / "evaluation_report.schema.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--task", type=Path, default=Path("tasks/kakeya3d_discovery.yaml"))
    parser.add_argument("--vault-root", type=Path, default=Path("judge/vault"))
    parser.add_argument(
        "--gold-graph",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--target-parse-hash",
        type=str,
        default=None,
        help="Optional SHA-256 of judge/vault/<task>/target_paper/full.md.",
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
    if not args.task.exists():
        logger.error("task %s not found", args.task)
        return 1

    task_dir = task_vault_dir(args.task, args.vault_root)
    gold_graph = args.gold_graph or (task_dir / "gold_graph.json")
    target_parse_hash = args.target_parse_hash
    if not gold_graph.exists():
        target_md, target_hash = ensure_target_markdown(args.task, args.vault_root)
        target_parse_hash = target_parse_hash or target_hash
        rc = build_gold_graph.main(["--target-md", str(target_md), "--out", str(gold_graph)])
        if rc != 0:
            return rc
    elif target_parse_hash is None:
        target_md = task_dir / "target_paper" / "full.md"
        if target_md.exists():
            target_parse_hash = _sha256(target_md)

    web_client = JudgeClient.from_env(model=args.web_model, web_enabled=True)
    offline_client = JudgeClient.from_env(model=args.offline_model, web_enabled=False)
    clients = OrchestratorClients(web_client=web_client, offline_client=offline_client)

    report = evaluate(
        args.submission,
        clients=clients,
        gold_graph_path=gold_graph,
        target_paper_parse_hash=target_parse_hash,
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
