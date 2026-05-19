"""OpenAlex search with mandatory publication-date cutoff."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

OPENALEX_BASE = "https://api.openalex.org/works"
DEFAULT_CUTOFF = "2025-01-01T00:00:00Z"


class OpenAlexSearchError(RuntimeError):
    """Raised when OpenAlex search cannot return results."""


class OpenAlexRestrictedSearch:
    def __init__(
        self,
        *,
        base_url: str = OPENALEX_BASE,
        cutoff: str = DEFAULT_CUTOFF,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._cutoff = _parse_datetime(cutoff)
        self._timeout = timeout_seconds
        self._transport = transport

    @property
    def cutoff_iso(self) -> str:
        return _format_datetime(self._cutoff)

    def search(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        max_results = max(1, min(int(max_results), 20))
        params = {
            "search": query,
            "filter": f"to_publication_date:{self._cutoff.date().isoformat()}",
            "per-page": str(max_results),
            "sort": "publication_date:desc",
        }
        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self._timeout)}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        with httpx.Client(**client_kwargs) as http:
            try:
                response = http.get(self._base_url, params=params)
            except httpx.HTTPError as exc:
                raise OpenAlexSearchError(f"OpenAlex request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenAlexSearchError("OpenAlex returned non-JSON") from exc
        if response.status_code >= 400:
            raise OpenAlexSearchError(f"OpenAlex error {response.status_code}: {payload!r}")
        return [
            normalised
            for item in payload.get("results", [])
            if isinstance(item, dict)
            for normalised in [_normalise_work(item, cutoff=self._cutoff)]
            if normalised is not None
        ]


def search_openalex(
    query: str,
    *,
    max_results: int = 10,
    cutoff: str = DEFAULT_CUTOFF,
) -> list[dict[str, Any]]:
    return OpenAlexRestrictedSearch(cutoff=cutoff).search(query, max_results=max_results)


def _normalise_work(item: dict[str, Any], *, cutoff: datetime) -> dict[str, Any] | None:
    published_raw = item.get("publication_date")
    if not isinstance(published_raw, str) or not published_raw:
        return None
    published = _parse_datetime(published_raw)
    if published >= cutoff:
        return None
    url = _work_url(item)
    authors = [
        author.get("author", {}).get("display_name", "")
        for author in item.get("authorships", [])
        if isinstance(author, dict)
    ]
    abstract = _abstract(item.get("abstract_inverted_index"))
    return {
        "title": str(item.get("title") or ""),
        "url": url,
        "published_date": _format_datetime(published),
        "author": ", ".join(author for author in authors if author),
        "highlights": [abstract] if abstract else [],
        "arxiv_id": _extract_arxiv_id(url),
        "source": "openalex",
    }


def _work_url(item: dict[str, Any]) -> str:
    location = item.get("primary_location") or {}
    if isinstance(location, dict):
        pdf_url = location.get("pdf_url")
        landing_url = location.get("landing_page_url")
        if isinstance(pdf_url, str) and pdf_url:
            return pdf_url
        if isinstance(landing_url, str) and landing_url:
            return landing_url
    return str(item.get("doi") or item.get("id") or "")


def _abstract(index: Any) -> str:
    if not isinstance(index, dict):
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                words.append((position, str(word)))
    return " ".join(word for _, word in sorted(words))[:2000]


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    if len(value) == 10:
        value = f"{value}T00:00:00+00:00"
    elif value.endswith("Z"):
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
