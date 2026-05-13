"""Run the Gemma 4 31B IT contamination canary.

This is the gate that must pass before the rest of the leaderboard is
worth building. It asks the pinned generation model a handful of
questions whose honest pre-2025-01-01 answer is "I don't know" or
"this is still open", then scores the response against a phrase bank
that recognises post-cutoff leakage of arXiv:2502.17655.

Usage::

    python -m scripts.canary_gemma \
        --prompts scripts/canary_prompts.yaml \
        --out reports/canary

Set ``OPENROUTER_KEY`` in your environment (or .env) first. The script
does not need any other credentials — MinerU and the judge key are not
involved in the canary.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
import yaml

from proxy.client import OpenRouterClient

SEVERITY_WEIGHTS: dict[str, int] = {"fatal": 100, "severe": 50, "moderate": 25, "weak": 10}
PROMPT_LEAK_THRESHOLD = 25
MODEL_CONTAMINATED_THRESHOLD = 70


@dataclass
class PromptSpec:
    id: str
    system: str
    user: str
    rationale: str


@dataclass
class PatternSpec:
    pattern: str
    severity: str
    description: str
    regex: re.Pattern[str] = field(init=False)

    def __post_init__(self) -> None:
        self.regex = re.compile(self.pattern)


@dataclass
class PromptResult:
    id: str
    response_text: str
    matches: list[dict[str, Any]]
    weighted_score: int
    leaked: bool
    input_tokens: int | None
    output_tokens: int | None


def load_config(path: Path) -> tuple[list[PromptSpec], list[PatternSpec]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    prompts = [
        PromptSpec(
            id=p["id"],
            system=p["role_system"],
            user=p["role_user"],
            rationale=p.get("rationale", ""),
        )
        for p in data.get("prompts", [])
    ]
    patterns = [
        PatternSpec(
            pattern=p["pattern"],
            severity=p["severity"],
            description=p.get("description", ""),
        )
        for p in data.get("contamination_patterns", [])
    ]
    if not prompts:
        raise ValueError(f"no prompts found in {path}")
    if not patterns:
        raise ValueError(f"no contamination patterns found in {path}")
    return prompts, patterns


def score_text(text: str, patterns: list[PatternSpec]) -> tuple[list[dict[str, Any]], int]:
    matches: list[dict[str, Any]] = []
    total = 0
    for pat in patterns:
        for m in pat.regex.finditer(text or ""):
            weight = SEVERITY_WEIGHTS.get(pat.severity, 0)
            total += weight
            matches.append(
                {
                    "pattern": pat.pattern,
                    "severity": pat.severity,
                    "description": pat.description,
                    "span": [m.start(), m.end()],
                    "snippet": text[max(0, m.start() - 30) : m.end() + 30],
                    "weight": weight,
                }
            )
    return matches, total


def run_prompt(
    client: OpenRouterClient,
    prompt: PromptSpec,
    patterns: list[PatternSpec],
    *,
    temperature: float,
    max_tokens: int,
) -> PromptResult:
    completion = client.chat(
        messages=[
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    matches, score = score_text(completion.text, patterns)
    return PromptResult(
        id=prompt.id,
        response_text=completion.text,
        matches=matches,
        weighted_score=score,
        leaked=score >= PROMPT_LEAK_THRESHOLD,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Gemma 4 31B IT contamination canary report")
    lines.append("")
    lines.append(f"- Generated at: {report['generated_at']}")
    lines.append(f"- Model: `{report['model']}`")
    lines.append(f"- Provider pin: `{report['provider_pin'] or '(unpinned)'}`")
    lines.append(f"- Total contamination score: **{report['total_score']}**")
    lines.append(f"- Verdict: **{report['verdict']}**")
    lines.append("")
    lines.append("## Per-prompt results")
    lines.append("")
    for r in report["prompts"]:
        lines.append(f"### {r['id']} — score {r['weighted_score']} (leaked: {r['leaked']})")
        if r["matches"]:
            for m in r["matches"]:
                lines.append(
                    f"  - `{m['severity']}` /{m['pattern']}/ — {m['description']}"
                )
                lines.append(f"    > …{m['snippet']}…")
        else:
            lines.append("  - no contamination patterns matched")
        lines.append("")
        lines.append("<details><summary>Raw response</summary>\n")
        lines.append("```\n" + (r["response_text"] or "") + "\n```")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines)


def verdict_from(total: int) -> str:
    if total >= MODEL_CONTAMINATED_THRESHOLD:
        return "CONTAMINATED — leaderboard premise at risk"
    if total >= PROMPT_LEAK_THRESHOLD:
        return "SUSPICIOUS — manual review required"
    return "CLEAN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompts",
        type=Path,
        default=Path(__file__).resolve().parent / "canary_prompts.yaml",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("CANARY_REPORT_DIR", "reports/canary")),
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument(
        "--env-var",
        default="OPENROUTER_KEY",
        help="Environment variable holding the participant-side OpenRouter key.",
    )
    args = parser.parse_args(argv)

    prompts, patterns = load_config(args.prompts)
    client = OpenRouterClient.from_env(args.env_var)

    results: list[PromptResult] = []
    total = 0
    for p in prompts:
        result = run_prompt(
            client,
            p,
            patterns,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        results.append(result)
        total += result.weighted_score
        print(
            f"[{result.id}] score={result.weighted_score} leaked={result.leaked} "
            f"tokens={result.input_tokens}/{result.output_tokens}",
            file=sys.stderr,
        )

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": "google/gemma-4-31b-it",
        "provider_pin": os.environ.get("GEMMA_PROVIDER_SLUG", "").strip() or None,
        "total_score": total,
        "verdict": verdict_from(total),
        "prompts": [
            {
                "id": r.id,
                "response_text": r.response_text,
                "matches": r.matches,
                "weighted_score": r.weighted_score,
                "leaked": r.leaked,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
            }
            for r in results
        ],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    json_path = args.out / f"gemma_canary_{stamp}.json"
    md_path = args.out / f"gemma_canary_{stamp}.md"
    json_path.write_bytes(orjson.dumps(report, option=orjson.OPT_INDENT_2))
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"\nReport: {json_path}\nReport: {md_path}\nVerdict: {report['verdict']}")
    if report["verdict"].startswith("CONTAMINATED"):
        return 2
    if report["verdict"].startswith("SUSPICIOUS"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
