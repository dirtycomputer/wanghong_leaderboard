from __future__ import annotations

import os
from typing import Any

import httpx


def restricted_search(query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
    base = os.environ["SEARCH_API_BASE"].rstrip("/")
    token = os.environ.get("SEARCH_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=httpx.Timeout(60.0)) as http:
        response = http.post(
            f"{base}/search",
            headers=headers,
            json={"query": query, "max_results": max_results},
        )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") or []
    return [r for r in results if isinstance(r, dict)]
