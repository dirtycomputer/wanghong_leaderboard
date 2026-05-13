"""Tests for the arXiv harvester."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from corpus.harvest_arxiv import (
    DEFAULT_CUTOFF,
    ArxivResult,
    CutoffViolation,
    _parse_atom_feed,
    _split_arxiv_id,
    download_pdf,
    search_arxiv,
)


def _atom_feed(entries: list[dict]) -> str:
    items = []
    for e in entries:
        items.append(
            "<entry>"
            f"<id>http://arxiv.org/abs/{e['id']}{e.get('version', '')}</id>"
            f"<title>{e['title']}</title>"
            f"<summary>{e.get('summary', '')}</summary>"
            f"<published>{e['published']}</published>"
            f"<updated>{e.get('updated', e['published'])}</updated>"
            f"<author><name>{e.get('author', 'A. Researcher')}</name></author>"
            f"<category term='{e.get('category', 'math.CA')}'/>"
            f"<link title='pdf' type='application/pdf' href='https://arxiv.org/pdf/{e['id']}.pdf'/>"
            "</entry>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        + "".join(items) + "</feed>"
    )


def test_parses_minimal_entry():
    feed = _atom_feed(
        [
            {
                "id": "2401.00001",
                "version": "v1",
                "title": "On  the   Kakeya conjecture in R^3",
                "summary": "Some\nsummary",
                "published": "2024-01-15T08:00:00Z",
                "author": "Alice Author",
                "category": "math.CA",
            }
        ]
    )
    parsed = _parse_atom_feed(feed)
    assert len(parsed) == 1
    entry = parsed[0]
    assert entry.arxiv_id == "2401.00001"
    assert entry.version == "v1"
    assert entry.title == "On the Kakeya conjecture in R^3"
    assert entry.authors == ("Alice Author",)
    assert entry.categories == ("math.CA",)
    assert entry.submitted_at == datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)


def test_split_arxiv_id_versioned_and_unversioned():
    assert _split_arxiv_id("http://arxiv.org/abs/2410.12345v3") == ("2410.12345", "v3")
    assert _split_arxiv_id("http://arxiv.org/abs/2410.12345") == ("2410.12345", "")


def test_search_arxiv_filters_post_cutoff_entries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                text=_atom_feed(
                    [
                        {
                            "id": "2024.00001",
                            "version": "v1",
                            "title": "Pre-cutoff",
                            "published": "2024-06-01T00:00:00Z",
                        },
                        {
                            "id": "2025.00099",
                            "version": "v1",
                            "title": "Post-cutoff",
                            "published": "2025-02-24T10:00:00Z",
                        },
                    ]
                ),
            )
        return httpx.Response(200, text=_atom_feed([]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        results = list(
            search_arxiv(
                "all:Kakeya",
                cutoff=DEFAULT_CUTOFF,
                max_results=10,
                page_size=2,
                client=http,
                sleep_seconds=0.0,
            )
        )

    assert [r.arxiv_id for r in results] == ["2024.00001"]


def test_search_arxiv_honours_blocklist():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                text=_atom_feed(
                    [
                        {
                            "id": "2024.99999",
                            "version": "v1",
                            "title": "Innocent",
                            "published": "2024-09-01T00:00:00Z",
                        },
                        {
                            "id": "2502.17655",
                            "version": "v1",
                            "title": "Target",
                            "published": "2024-12-25T00:00:00Z",  # pretend pre-cutoff
                        },
                    ]
                ),
            )
        return httpx.Response(200, text=_atom_feed([]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        results = list(
            search_arxiv(
                "all:Kakeya",
                cutoff=DEFAULT_CUTOFF,
                max_results=10,
                page_size=2,
                client=http,
                blocklist=frozenset({"2502.17655"}),
                sleep_seconds=0.0,
            )
        )
    assert [r.arxiv_id for r in results] == ["2024.99999"]


def test_search_arxiv_paginates_until_short_page():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # full page of 2
            return httpx.Response(
                200,
                text=_atom_feed(
                    [
                        {
                            "id": "2024.0001",
                            "version": "v1",
                            "title": "A",
                            "published": "2024-06-01T00:00:00Z",
                        },
                        {
                            "id": "2024.0002",
                            "version": "v1",
                            "title": "B",
                            "published": "2024-06-02T00:00:00Z",
                        },
                    ]
                ),
            )
        if calls["n"] == 2:
            # short page -> stop after this one
            return httpx.Response(
                200,
                text=_atom_feed(
                    [
                        {
                            "id": "2024.0003",
                            "version": "v1",
                            "title": "C",
                            "published": "2024-06-03T00:00:00Z",
                        },
                    ]
                ),
            )
        return httpx.Response(200, text=_atom_feed([]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        results = list(
            search_arxiv(
                "all:Kakeya",
                cutoff=DEFAULT_CUTOFF,
                max_results=10,
                page_size=2,
                client=http,
                sleep_seconds=0.0,
            )
        )

    assert [r.arxiv_id for r in results] == ["2024.0001", "2024.0002", "2024.0003"]
    assert calls["n"] == 2


def _make_result(submitted: datetime) -> ArxivResult:
    return ArxivResult(
        arxiv_id="2024.12345",
        version="v1",
        title="Test",
        authors=("A. Author",),
        categories=("math.CA",),
        submitted_at=submitted,
        updated_at=submitted,
        abstract="",
        pdf_url="https://arxiv.org/pdf/2024.12345.pdf",
    )


def test_download_pdf_refuses_post_cutoff(tmp_path: Path):
    result = _make_result(datetime(2025, 6, 1, tzinfo=UTC))
    with pytest.raises(CutoffViolation):
        download_pdf(result, out_dir=tmp_path)


def test_download_pdf_writes_sha256(tmp_path: Path):
    payload = b"%PDF-1.4 fake pdf content"
    expected = hashlib.sha256(payload).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/pdf/2024.12345.pdf"
        return httpx.Response(200, content=payload)

    result = _make_result(datetime(2024, 12, 30, tzinfo=UTC))
    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as http:
        meta = download_pdf(result, out_dir=tmp_path / "paper", client=http)

    assert meta["pdf_sha256"] == expected
    assert meta["pdf_bytes"] == len(payload)
    assert Path(meta["pdf_path"]).read_bytes() == payload


def test_download_pdf_skips_when_already_present(tmp_path: Path):
    payload = b"%PDF-existing"
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "source.pdf").write_bytes(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("download should be skipped when file already exists")

    result = _make_result(datetime(2024, 12, 30, tzinfo=UTC))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        meta = download_pdf(result, out_dir=paper_dir, client=http, overwrite=False)

    assert meta["pdf_sha256"] == hashlib.sha256(payload).hexdigest()
