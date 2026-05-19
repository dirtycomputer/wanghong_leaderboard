"""FastAPI service exposing date-restricted search to harness containers."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from harnesses.tools.restricted_search.exa import ExaRestrictedSearch, RestrictedSearchError
from harnesses.tools.restricted_search.openalex import OpenAlexRestrictedSearch, OpenAlexSearchError

app = FastAPI(title="wanghong restricted search", version="0.0.1")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=10, ge=1, le=20)


def _search_token() -> str:
    return os.environ.get("RESTRICTED_SEARCH_TOKEN", "").strip()


def _authorize(authorization: str | None, x_search_token: str | None) -> None:
    expected = _search_token()
    if not expected:
        return
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    if bearer != expected and x_search_token != expected:
        raise HTTPException(status_code=401, detail="invalid restricted search token")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "providers": ["openalex", "exa"],
        "cutoff": os.environ.get("RESTRICTED_SEARCH_CUTOFF", "2025-01-01T00:00:00Z"),
    }


@app.post("/v1/openalex/search")
@app.post("/openalex/search")
def openalex_search(
    request: SearchRequest,
    authorization: str | None = Header(default=None),
    x_search_token: str | None = Header(default=None, alias="X-Search-Token"),
) -> dict[str, Any]:
    _authorize(authorization, x_search_token)
    client = OpenAlexRestrictedSearch(
        cutoff=os.environ.get("RESTRICTED_SEARCH_CUTOFF", "2025-01-01T00:00:00Z")
    )
    try:
        results = client.search(request.query, max_results=request.max_results)
    except OpenAlexSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "query": request.query,
        "provider": "openalex",
        "cutoff": client.cutoff_iso,
        "results": results,
    }


@app.post("/v1/exa/search")
@app.post("/exa/search")
def exa_search(
    request: SearchRequest,
    authorization: str | None = Header(default=None),
    x_search_token: str | None = Header(default=None, alias="X-Search-Token"),
) -> dict[str, Any]:
    _authorize(authorization, x_search_token)
    try:
        client = ExaRestrictedSearch.from_env()
        results = client.search(request.query, max_results=request.max_results)
    except (RestrictedSearchError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "query": request.query,
        "provider": "exa",
        "cutoff": client.cutoff_iso,
        "results": results,
    }
