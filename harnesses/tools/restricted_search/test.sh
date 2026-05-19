#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python3 - <<'PY'
from harnesses.tools.restricted_search.exa import ExaRestrictedSearch
from harnesses.tools.restricted_search.openalex import OpenAlexRestrictedSearch


def run(name, fn):
    try:
        results = fn()
    except Exception as exc:
        print(f"\n{name}: ERROR {exc}")
        return
    print(f"\n{name}: {len(results)} result(s)")
    for item in results[:3]:
        print(f"- {item['published_date']} | {item['source']} | {item['title'][:100]}")


query = "Kakeya conjecture polynomial partitioning"

run("openalex", lambda: OpenAlexRestrictedSearch().search(query, max_results=50))
run("exa", lambda: ExaRestrictedSearch.from_env().search("artificial intelligence", max_results=50))
PY
