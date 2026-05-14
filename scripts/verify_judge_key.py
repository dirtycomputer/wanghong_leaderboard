"""Pre-flight check for the OpenRouter judge key.

The first live baseline scoring run discovered the experiment account
could only reach Llama models — Anthropic / OpenAI / Google providers
returned ``403 provider TOS``. Before paying for a real evaluation
round the operator should confirm the new key can actually reach the
intended judge model.

This script:

1. Reads the key from ``--env`` (default ``OPENROUTER_JUDGE_KEY``).
2. Hits ``/api/v1/key`` to confirm scope, expiry, and usage so far.
3. Hits ``/api/v1/chat/completions`` with a 1-token completion against
   each candidate model and reports OK / 4xx / 5xx.
4. Exits non-zero if no candidate model is reachable.

Run::

    python -m scripts.verify_judge_key \\
        --models anthropic/claude-sonnet-4.6 openai/gpt-5 google/gemini-3-pro

The default candidate list mirrors the frontier-judge fallbacks
documented in ``docs/EVAL_VERSIONING.md``.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

DEFAULT_CANDIDATES: tuple[str, ...] = (
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.7",
    "openai/gpt-5",
    "openai/gpt-4o",
    "google/gemini-3-pro-preview",
    "google/gemini-2.5-pro",
    "meta-llama/llama-3.3-70b-instruct",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default="OPENROUTER_JUDGE_KEY")
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_CANDIDATES),
        help="Model slugs to test. Defaults to the documented judge candidates.",
    )
    parser.add_argument("--base-url", default=OPENROUTER_BASE)
    args = parser.parse_args(argv)

    key = os.environ.get(args.env, "").strip()
    if not key:
        print(f"error: {args.env} is not set", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    base = args.base_url.rstrip("/")

    # 1. Scope check
    try:
        with httpx.Client(timeout=30.0) as http:
            scope = http.get(f"{base}/key", headers=headers)
    except httpx.HTTPError as exc:
        print(f"error: could not reach {base}/key: {exc}", file=sys.stderr)
        return 2
    if scope.status_code >= 400:
        print(f"error: /key returned {scope.status_code}: {scope.text[:200]}", file=sys.stderr)
        return 2
    data = scope.json().get("data") or {}
    print("key scope:")
    print(f"  label              {data.get('label')}")
    print(f"  is_free_tier       {data.get('is_free_tier')}")
    print(f"  usage (total)      {data.get('usage')}")
    print(f"  rate_limit         {data.get('rate_limit')}")
    print()

    # 2. Model reachability
    print(f"{'model':45s}  {'status':>8s}  notes")
    print("-" * 80)
    reachable: list[str] = []
    for model in args.models:
        ok, note = _probe_model(base, headers, model)
        status = "OK" if ok else "FAIL"
        print(f"{model:45s}  {status:>8s}  {note}")
        if ok:
            reachable.append(model)
    print()

    if not reachable:
        print(
            "no candidate model was reachable; the judge stack cannot run "
            "with this key as-is",
            file=sys.stderr,
        )
        return 1
    print(f"reachable models: {len(reachable)} / {len(args.models)}")
    print(f"recommended JUDGE_MODEL: {reachable[0]}")
    return 0


def _probe_model(
    base: str, headers: dict[str, str], model: str
) -> tuple[bool, str]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        with httpx.Client(timeout=60.0) as http:
            r = http.post(f"{base}/chat/completions", headers=headers, json=body)
    except httpx.HTTPError as exc:
        return False, f"transport error: {exc}"
    if r.status_code == 200:
        return True, "1-token probe ok"
    try:
        err = r.json().get("error") or {}
        message = str(err.get("message") or "")[:80]
    except ValueError:
        message = r.text[:80]
    return False, f"{r.status_code} {message}"


if __name__ == "__main__":
    sys.exit(main())
