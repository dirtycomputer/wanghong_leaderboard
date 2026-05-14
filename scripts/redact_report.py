"""Redact ``evaluation_report.json`` before publishing to ``submissions/``.

The full report a judge run produces contains:

* ``judges.B.suspect_passages`` — the contamination phrase bank pattern
  that was matched; publishing this hands participants a roadmap for
  evading or spoofing the audit.
* ``judges.C.missing_gold_nodes`` and ``judges.C.notes`` — names and
  quoted content from the hidden gold proof graph; the whole point of
  the gold graph is that participants do not see it.
* ``judges.*.raw_text`` — the LLM's verbatim response, which can
  contain large fragments of gold-graph content or proprietary
  reasoning.

This script keeps every field the public leaderboard renderer actually
uses (scores, applied caps, verdict, judge model record) and strips
the fields above. Idempotent — running it twice is a no-op.

Usage::

    python -m scripts.redact_report \\
        runs/example/output/evaluation_report.json \\
        --out submissions/baselines/example/eval-20260513T205411Z/evaluation_report.json
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import orjson

#: Per-judge fields that must NOT make it to a public ``submissions/`` tree.
_REDACT_PER_JUDGE: dict[str, tuple[str, ...]] = {
    "A": ("contamination_hits",),
    "B": ("suspect_passages", "raw_text"),
    "C": ("missing_gold_nodes", "notes", "raw_text"),
    "D": ("raw_text",),
    "E": ("raw_text",),
}


def redact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``report`` with sensitive fields removed."""
    redacted = copy.deepcopy(report)
    judges = redacted.get("judges") or {}
    if not isinstance(judges, dict):
        return redacted
    for letter, fields in _REDACT_PER_JUDGE.items():
        j = judges.get(letter)
        if not isinstance(j, dict):
            continue
        for field in fields:
            if field in j:
                j.pop(field, None)
    return redacted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Destination path. Parent directories are created.",
    )
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"error: {args.source} not found", file=sys.stderr)
        return 1

    try:
        report = orjson.loads(args.source.read_bytes())
    except orjson.JSONDecodeError as exc:
        print(f"error: {args.source} is not valid JSON ({exc})", file=sys.stderr)
        return 1
    if not isinstance(report, dict):
        print(f"error: {args.source} top-level must be a JSON object", file=sys.stderr)
        return 1

    out = redact_report(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(orjson.dumps(out, option=orjson.OPT_INDENT_2))
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
