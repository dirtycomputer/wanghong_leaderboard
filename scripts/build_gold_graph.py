"""Extract a hidden gold proof graph from the target paper.

MVP path: feed ``judge/vault/target_paper/full.md`` (produced by
``scripts/parse_target_paper.py``) to a strong LLM with the
``proof_graph.schema.json`` shape pinned in the system prompt, then
schema-validate and save to ``judge/vault/gold_graph.json``.

Before P5 (alpha leaderboard) this artefact must be reviewed and
edited by harmonic analysis / GMT reviewers. The output records its
provenance (``source: "llm_extraction"``) so a later hand-review can
bump it to ``source: "expert_curated"``.

Usage::

    python -m scripts.build_gold_graph \
        --target-md judge/vault/target_paper/full.md \
        --out judge/vault/gold_graph.json
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import orjson

from cli.kakeya_lb.schemas import PROOF_GRAPH_SCHEMA_PATH, validate_against
from judge.client import JudgeClient, JudgeError

logger = logging.getLogger("build_gold_graph")

_SYSTEM_PROMPT = (
    "You are extracting a structured proof graph from a mathematical "
    "paper that proves the three-dimensional Kakeya set conjecture. "
    "Output JSON that validates against the leaderboard's "
    "proof_graph.schema.json: schema_version='1.0', target_theorem (string), "
    "definitions (list of {name, statement}), pre_cutoff_dependencies "
    "(list of {arxiv_id, claim, where_used}), new_lemmas (list of "
    "{name, statement, proof_status, depends_on, used_for}), known_gaps "
    "(list of {location, description, severity}), final_implication (string). "
    "Use proof_status='proved' for fully proved lemmas. Be faithful to the "
    "paper. Return STRICT JSON, no commentary."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-md",
        type=Path,
        default=Path("judge/vault/target_paper/full.md"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("judge/vault/gold_graph.json"),
    )
    parser.add_argument("--max-input-bytes", type=int, default=180_000)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.target_md.exists():
        logger.error(
            "%s does not exist; run scripts.parse_target_paper first",
            args.target_md,
        )
        return 1

    text = args.target_md.read_text(encoding="utf-8", errors="replace")
    if len(text) > args.max_input_bytes:
        logger.warning(
            "target markdown is %d bytes; truncating to %d",
            len(text), args.max_input_bytes,
        )
        text = text[: args.max_input_bytes]

    client = JudgeClient.from_env(model=None, web_enabled=False)
    logger.info("extracting with model %s", client.model)
    try:
        response = client.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            expect_json=True,
            temperature=0.0,
            max_tokens=8192,
        )
    except JudgeError as exc:
        logger.error("extraction failed: %s", exc)
        return 2

    graph = response.parsed_json
    if not isinstance(graph, dict):
        logger.error("extractor returned non-object JSON")
        return 2
    graph.setdefault("schema_version", "1.0")
    _normalize_in_place(graph)

    errors = validate_against(graph, PROOF_GRAPH_SCHEMA_PATH)
    if errors:
        logger.error("extracted graph fails schema:\n  - %s", "\n  - ".join(errors))
        # Still write to a sibling file so a reviewer can inspect.
        bad_path = args.out.with_suffix(".invalid.json")
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_bytes(orjson.dumps(graph, option=orjson.OPT_INDENT_2))
        logger.error("wrote raw extraction to %s", bad_path)
        return 3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(orjson.dumps(graph, option=orjson.OPT_INDENT_2))

    meta_path = args.out.with_name("gold_graph_meta.json")
    meta_path.write_bytes(
        orjson.dumps(
            {
                "source": "llm_extraction",
                "extractor_model": response.model,
                "extracted_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "input_path": str(args.target_md),
                "input_bytes": len(text),
                "expert_reviewed": False,
                "notes": "MVP; replace with expert_curated before public beta.",
            },
            option=orjson.OPT_INDENT_2,
        )
    )
    logger.info("wrote %s (%d new_lemmas)", args.out, len(graph.get("new_lemmas") or []))
    print(args.out)
    return 0


_ARXIV_PREFIX_RE = __import__("re").compile(r"^(?:arXiv:)?(.+)$")
_SEVERITY_ALIASES: dict[str, str] = {
    "low": "minor",
    "medium": "moderate",
    "major": "fatal",
    "high": "fatal",
    "critical": "fatal",
}


def _normalize_in_place(graph: dict) -> None:
    """Light post-processing for common LLM-output quirks.

    Strips ``arXiv:`` prefixes off citation IDs and maps severity
    aliases onto the schema's enum. Does not invent values.
    """
    for dep in graph.get("pre_cutoff_dependencies") or []:
        if isinstance(dep, dict):
            aid = dep.get("arxiv_id")
            if isinstance(aid, str):
                m = _ARXIV_PREFIX_RE.match(aid.strip())
                if m:
                    dep["arxiv_id"] = m.group(1)
    for gap in graph.get("known_gaps") or []:
        if isinstance(gap, dict):
            sev = gap.get("severity")
            if isinstance(sev, str):
                gap["severity"] = _SEVERITY_ALIASES.get(sev.lower(), sev.lower())
    for lemma in graph.get("new_lemmas") or []:
        if isinstance(lemma, dict):
            ps = lemma.get("proof_status")
            if isinstance(ps, str):
                lemma["proof_status"] = ps.lower()


if __name__ == "__main__":
    sys.exit(main())
