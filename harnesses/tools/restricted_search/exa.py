"""Small Exa client with mandatory publication-date filtering."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

EXA_BASE = "https://api.exa.ai"
DEFAULT_CUTOFF = "2025-01-01T00:00:00Z"


class RestrictedSearchError(RuntimeError):
    """Raised when the restricted search backend cannot return results."""


class ExaRestrictedSearch:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = EXA_BASE,
        cutoff: str = DEFAULT_CUTOFF,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Exa api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._cutoff = _parse_datetime(cutoff)
        self._timeout = timeout_seconds
        self._transport = transport

    @classmethod
    def from_env(cls) -> ExaRestrictedSearch:
        key = os.environ.get("EXA_API_KEY", "").strip()
        cutoff = os.environ.get("RESTRICTED_SEARCH_CUTOFF", DEFAULT_CUTOFF)
        return cls(api_key=key, cutoff=cutoff)

    @property
    def cutoff_iso(self) -> str:
        return _format_datetime(self._cutoff)

    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        max_results = max(1, min(int(max_results), 20))
        body: dict[str, Any] = {
            "query": query,
            "type": "auto",
            "numResults": max_results,
            "endPublishedDate": self.cutoff_iso,
            "contents": {"highlights": True},
        }
        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self._timeout)}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        with httpx.Client(**client_kwargs) as http:
            try:
                response = http.post(
                    f"{self._base_url}/search",
                    headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise RestrictedSearchError(f"Exa request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise RestrictedSearchError("Exa returned non-JSON") from exc
        if response.status_code >= 400:
            raise RestrictedSearchError(f"Exa error {response.status_code}: {payload!r}")

        raw_results = payload.get("results") or []
        return [
            normalised
            for item in raw_results
            if isinstance(item, dict)
            for normalised in [_normalise_result(item, cutoff=self._cutoff)]
            if normalised is not None
        ]


def search_exa(
    query: str,
    *,
    max_results: int = 10,
    cutoff: str = DEFAULT_CUTOFF,
) -> list[dict[str, Any]]:
    key = os.environ.get("EXA_API_KEY", "").strip()
    return ExaRestrictedSearch(api_key=key, cutoff=cutoff).search(query, max_results=max_results)


def _normalise_result(item: dict[str, Any], *, cutoff: datetime) -> dict[str, Any] | None:
    published_raw = item.get("publishedDate")
    if not isinstance(published_raw, str) or not published_raw:
        return None
    published = _parse_datetime(published_raw)
    if published >= cutoff:
        return None
    url = str(item.get("url") or "")
    highlights = _string_list(item.get("highlights"))
    return {
        "title": str(item.get("title") or ""),
        "url": url,
        "published_date": _format_datetime(published),
        "author": str(item.get("author") or ""),
        "highlights": highlights,
        "arxiv_id": _extract_arxiv_id(url),
        "source": "exa",
    }


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # noqa: UP017 - keep local Py3.10 usable
    return parsed.astimezone(timezone.utc)  # noqa: UP017 - keep local Py3.10 usable


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime(  # noqa: UP017 - keep local Py3.10 usable
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _extract_arxiv_id(url: str) -> str | None:
    import re

    match = re.search(
        r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}|[0-9]{7})(v[0-9]+)?",
        url,
    )
    if not match:
        return None
    return (match.group(1) + (match.group(2) or "")).removesuffix(".pdf")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]
