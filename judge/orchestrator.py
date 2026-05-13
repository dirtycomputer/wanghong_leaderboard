"""Run all five judges, apply the rubric, write the evaluation report.

The orchestrator is intentionally explicit about which clients run
which judges. Two clients are constructed:

* a ``web_enabled=True`` client for Judges B and E (contamination
  audit and open-world novelty);
* a ``web_enabled=False`` client for Judges C and D (gold-graph
  alignment and adversarial gap finder).

Judge A is pure-program and does not need an LLM client.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any

import orjson

from judge import a_protocol, b_contamination, c_gold_graph, d_adversarial, e_novelty
from judge.client import JudgeClient
from judge.eval_version import EvalVersion, JudgeModelRecord, make_evaluation_id
from judge.rubric import RUBRIC_VERSION, Cap, apply_rubric, verdict_from


@dataclasses.dataclass
class OrchestratorClients:
    """Bundle of judge clients passed to :func:`evaluate`.

    Both clients can be the same object if the caller does not care
    about web/no-web separation (e.g. unit tests). Production paths
    should pass a web-enabled client for ``web_client`` and a
    no-web client for ``offline_client``.
    """

    web_client: JudgeClient
    offline_client: JudgeClient


def evaluate(
    submission_dir: Path,
    *,
    clients: OrchestratorClients,
    gold_graph_path: Path,
    corpus_manifest_path: Path | None = None,
    target_paper_parse_hash: str | None = None,
    rubric_version: str = RUBRIC_VERSION,
) -> dict[str, Any]:
    """Run the full judge stack and return the evaluation report dict."""
    submission_dir = Path(submission_dir)

    a = a_protocol.run(
        submission_dir, corpus_manifest_path=corpus_manifest_path
    )
    a_dq = any(cap.cap == 0.0 for cap in a.caps)

    if a_dq:
        b = b_contamination._inconclusive(clients.web_client.model)
        c = c_gold_graph._inconclusive(clients.offline_client.model)
        d = d_adversarial._inconclusive(clients.offline_client.model)
        e = e_novelty._inconclusive(clients.web_client.model)
    else:
        b = b_contamination.run(submission_dir, client=clients.web_client)
        c = c_gold_graph.run(
            submission_dir,
            client=clients.offline_client,
            gold_graph_path=gold_graph_path,
        )
        d = d_adversarial.run(submission_dir, client=clients.offline_client)
        e = e_novelty.run(submission_dir, client=clients.web_client)

    subscores: dict[str, float] = {
        "protocol": _avg(a.subscores.get("protocol", 0.0), b.protocol_subscore),
        "gold_graph": c.overall_subscore,
        "correctness": d.correctness_subscore,
        "gap_resistance": d.gap_resistance_subscore,
        "novelty": e.novelty_subscore,
        "clarity": a.subscores.get("clarity", 0.0),
    }
    all_caps: list[Cap] = []
    for caps in (a.caps, b.caps, c.caps, d.caps, e.caps):
        all_caps.extend(c2 for c2 in caps if c2.cap < 100.0)

    weighted, final, applied = apply_rubric(subscores, all_caps)
    eval_version = EvalVersion(
        evaluation_id=make_evaluation_id(),
        rubric_version=rubric_version,
        gold_graph_hash=_hash_file(gold_graph_path),
        target_paper_parse_hash=target_paper_parse_hash,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        judge_models=(
            JudgeModelRecord(role="A_protocol", model="(pure-program)"),
            JudgeModelRecord(
                role="B_contamination",
                model=clients.web_client.model,
                web_access=True,
            ),
            JudgeModelRecord(
                role="C_gold_graph", model=clients.offline_client.model
            ),
            JudgeModelRecord(
                role="D_adversarial", model=clients.offline_client.model
            ),
            JudgeModelRecord(
                role="E_novelty", model=clients.web_client.model, web_access=True
            ),
        ),
    )

    submission_meta = _load_submission_meta(submission_dir)
    submission_meta["path"] = str(submission_dir)

    return {
        "schema_version": "1.0",
        "evaluation_id": eval_version.evaluation_id,
        "rubric_version": rubric_version,
        "gold_graph_hash": eval_version.gold_graph_hash,
        "target_paper_parse_hash": target_paper_parse_hash,
        "submission": submission_meta,
        "judges": {
            "A": a.as_dict(),
            "B": b.as_dict(),
            "C": c.as_dict(),
            "D": d.as_dict(),
            "E": e.as_dict(),
        },
        "subscores": subscores,
        "weighted_score": weighted,
        "applied_caps": [c.as_dict() for c in applied],
        "final_score": final,
        "verdict": verdict_from(final, applied),
        "judge_models": [j.as_dict() for j in eval_version.judge_models],
    }


def _avg(*xs: float) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _hash_file(path: Path) -> str | None:
    import hashlib

    if not Path(path).exists():
        return None
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def _load_submission_meta(submission_dir: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "harness_name": None,
        "harness_version": None,
        "corpus_hash": None,
    }
    run_manifest = submission_dir / "run_manifest.json"
    if run_manifest.exists():
        try:
            obj = orjson.loads(run_manifest.read_bytes())
        except orjson.JSONDecodeError:
            return meta
        meta["harness_name"] = obj.get("harness_name")
        meta["harness_version"] = obj.get("harness_version")
        meta["corpus_hash"] = obj.get("corpus_hash")
    return meta
