#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from harnesses.tools.restricted_search.openalex import OpenAlexRestrictedSearch  # noqa: E402


def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: openalex_search.py QUERY [MAX_RESULTS]", file=sys.stderr)
        return 2
    load_env()
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    client = OpenAlexRestrictedSearch(
        cutoff=os.environ.get("RESTRICTED_SEARCH_CUTOFF", "2025-01-01T00:00:00Z")
    )
    payload = {
        "query": sys.argv[1],
        "provider": "openalex",
        "cutoff": client.cutoff_iso,
        "results": client.search(sys.argv[1], max_results=max_results),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
