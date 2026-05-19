from __future__ import annotations

import json

import httpx
import pytest

from harnesses.tools.restricted_search.exa import ExaRestrictedSearch
from harnesses.tools.restricted_search.openalex import OpenAlexRestrictedSearch


def test_exa_search_sends_cutoff_and_filters_results():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "old",
                        "url": "https://arxiv.org/abs/1909.10973",
                        "publishedDate": "2020-01-01T00:00:00Z",
                        "author": "A",
                        "highlights": ["ok"],
                    },
                    {
                        "title": "new",
                        "url": "https://example.com/new",
                        "publishedDate": "2025-02-01T00:00:00Z",
                    },
                    {"title": "missing date", "url": "https://example.com/missing"},
                ]
            },
        )

    client = ExaRestrictedSearch(
        "key",
        cutoff="2025-01-01T00:00:00Z",
        transport=httpx.MockTransport(handler),
    )
    results = client.search("kakeya")
    assert captured["json"]["type"] == "auto"
    assert captured["json"]["contents"] == {"highlights": True}
    assert captured["json"]["endPublishedDate"] == "2025-01-01T00:00:00Z"
    assert len(results) == 1
    assert results[0]["title"] == "old"
    assert results[0]["highlights"] == ["ok"]
    assert results[0]["arxiv_id"] == "1909.10973"


def test_exa_requires_api_key():
    with pytest.raises(ValueError):
        ExaRestrictedSearch("")


def test_openalex_search_sends_publication_date_and_filters_results():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "old",
                        "publication_date": "2020-01-01",
                        "primary_location": {
                            "landing_page_url": "https://arxiv.org/abs/2010.02251",
                        },
                        "authorships": [{"author": {"display_name": "Alice"}}],
                        "abstract_inverted_index": {"hello": [0], "world": [1]},
                    },
                    {
                        "title": "new",
                        "publication_date": "2025-02-01",
                    },
                    {"title": "missing date"},
                ]
            },
        )

    client = OpenAlexRestrictedSearch(
        cutoff="2025-01-01T00:00:00Z",
        transport=httpx.MockTransport(handler),
    )
    results = client.search("kakeya", max_results=3)
    assert "to_publication_date%3A2025-01-01" in captured["url"]
    assert len(results) == 1
    assert results[0]["source"] == "openalex"
    assert results[0]["arxiv_id"] == "2010.02251"
    assert results[0]["highlights"] == ["hello world"]
