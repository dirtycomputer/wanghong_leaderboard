"""arXiv harvester with strict ``submittedDate < 2025-01-01 GMT`` cutoff.

The harvester is deliberately small and side-effect-light so it can be
unit-tested with mocked HTTP. The two public entrypoints are:

* :func:`search_arxiv` — given an arXiv query expression, page through
  the Atom feed and yield :class:`ArxivResult` records that have passed
  the cutoff filter. Honours the arXiv API rate-limit recommendation
  (3 seconds between paginated requests).
* :func:`download_pdf` — fetch the PDF of a single result to disk,
  verifying the destination is fresh and writing alongside a SHA-256
  digest for the manifest builder.

The seed-keyword YAML is consumed by the orchestrator
(``scripts/build_corpus.py``); this module knows nothing about it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF = "https://arxiv.org/pdf/{arxiv_id}{version}.pdf"

#: Hard cutoff. The harvester refuses to keep results submitted on or
#: after this instant in GMT.
DEFAULT_CUTOFF = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)

#: arXiv asks polite clients to wait between paginated requests.
ARXIV_RATE_LIMIT_SECONDS = 3.0

_ATOM_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


@dataclasses.dataclass(frozen=True)
class ArxivResult:
    """A single paper returned by the arXiv API.

    ``arxiv_id`` is the canonical id without a version suffix
    (e.g. ``"1909.10973"``). ``version`` is the version suffix as it
    appears in the API (``"v3"``); ``submitted_at`` is the submission
    timestamp of *that specific version*.
    """

    arxiv_id: str
    version: str
    title: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    submitted_at: datetime
    updated_at: datetime
    abstract: str
    pdf_url: str

    @property
    def id_with_version(self) -> str:
        return f"{self.arxiv_id}{self.version}"


class CutoffViolation(RuntimeError):
    """Raised when an unexpected post-cutoff record is encountered."""


def search_arxiv(
    query: str,
    *,
    cutoff: datetime = DEFAULT_CUTOFF,
    max_results: int = 100,
    page_size: int = 100,
    client: httpx.Client | None = None,
    blocklist: frozenset[str] = frozenset(),
    sleep_seconds: float = ARXIV_RATE_LIMIT_SECONDS,
) -> Iterator[ArxivResult]:
    """Page through the arXiv API and yield records before ``cutoff``.

    The function never returns a paper submitted at or after ``cutoff``
    and never returns an id in ``blocklist`` (used to drop the target
    paper as a defence-in-depth measure even if it somehow matches a
    seed query). Pagination stops as soon as the server returns fewer
    than ``page_size`` entries.
    """
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    if max_results <= 0:
        return

    owned_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(60.0))

    try:
        emitted = 0
        start = 0
        while emitted < max_results:
            window = min(page_size, max_results - emitted)
            xml_text = _fetch_arxiv_page(
                http,
                query=query,
                start=start,
                window=window,
                backoff_base=sleep_seconds,
            )
            entries = _parse_atom_feed(xml_text)
            if not entries:
                return
            for entry in entries:
                if entry.submitted_at >= cutoff:
                    logger.debug(
                        "skipping %s submitted_at=%s >= cutoff=%s",
                        entry.arxiv_id, entry.submitted_at.isoformat(), cutoff.isoformat(),
                    )
                    continue
                if entry.arxiv_id in blocklist:
                    logger.info("dropping blocklisted id %s", entry.arxiv_id)
                    continue
                yield entry
                emitted += 1
                if emitted >= max_results:
                    return
            if len(entries) < window:
                return
            start += window
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    finally:
        if owned_client:
            http.close()


#: HTTP statuses arXiv uses for transient rate-limiting / overload.
#: ``export.arxiv.org`` is fronted by a CDN that returns 429 under load
#: and 503 during maintenance windows; both clear on their own.
_ARXIV_RETRYABLE_STATUS = frozenset({429, 503})


def _fetch_arxiv_page(
    http: httpx.Client,
    *,
    query: str,
    start: int,
    window: int,
    backoff_base: float,
    max_retries: int = 4,
) -> str:
    """GET one page of the arXiv Atom feed, retrying transient failures.

    arXiv rate-limits aggressively; a bare ``raise_for_status`` aborts
    the whole harvest on the first ``429``. This retries ``429`` /
    ``503`` and transport errors with exponential backoff
    (``backoff_base * 2**attempt``). Non-transient 4xx (e.g. a
    malformed query) still fails fast. ``backoff_base`` is wired to the
    caller's ``sleep_seconds`` so tests can set it to ``0`` for instant
    retries.
    """
    params = {
        "search_query": query,
        "start": start,
        "max_results": window,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = http.get(ARXIV_API, params=params)
        except httpx.TransportError as exc:
            last_exc = exc
        else:
            if response.status_code not in _ARXIV_RETRYABLE_STATUS:
                response.raise_for_status()
                return response.text
            last_exc = httpx.HTTPStatusError(
                f"arXiv transient {response.status_code}",
                request=response.request,
                response=response,
            )
            logger.warning(
                "arXiv %s on start=%d (attempt %d/%d)",
                response.status_code, start, attempt + 1, max_retries + 1,
            )
        if attempt < max_retries:
            # Backoff is wired to the caller's politeness delay: the
            # default 3s gives 3 / 6 / 12 / 24s; tests pass 0 for
            # instant retries.
            time.sleep(backoff_base * (2 ** attempt))
    assert last_exc is not None
    raise last_exc


def _parse_atom_feed(xml_text: str) -> list[ArxivResult]:
    root = ET.fromstring(xml_text)
    out: list[ArxivResult] = []
    for entry in root.findall("a:entry", _ATOM_NS):
        result = _parse_entry(entry)
        if result is not None:
            out.append(result)
    return out


def _parse_entry(entry: ET.Element) -> ArxivResult | None:
    id_text = _text(entry.find("a:id", _ATOM_NS))
    if not id_text:
        return None
    arxiv_id, version = _split_arxiv_id(id_text)

    title = _normalise_whitespace(_text(entry.find("a:title", _ATOM_NS)))
    abstract = _normalise_whitespace(_text(entry.find("a:summary", _ATOM_NS)))
    published = _parse_iso8601(_text(entry.find("a:published", _ATOM_NS)))
    updated = _parse_iso8601(_text(entry.find("a:updated", _ATOM_NS))) or published
    if published is None:
        return None

    authors = tuple(
        _text(a.find("a:name", _ATOM_NS)) or ""
        for a in entry.findall("a:author", _ATOM_NS)
    )
    authors = tuple(a for a in authors if a)

    categories = tuple(
        c.attrib.get("term", "") for c in entry.findall("a:category", _ATOM_NS)
    )
    categories = tuple(c for c in categories if c)

    pdf_url = ""
    for link in entry.findall("a:link", _ATOM_NS):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    if not pdf_url:
        pdf_url = ARXIV_PDF.format(arxiv_id=arxiv_id, version=version)

    return ArxivResult(
        arxiv_id=arxiv_id,
        version=version,
        title=title,
        authors=authors,
        categories=categories,
        submitted_at=published,
        updated_at=updated or published,
        abstract=abstract,
        pdf_url=pdf_url,
    )


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _normalise_whitespace(text: str) -> str:
    return " ".join(text.split())


def _split_arxiv_id(id_url: str) -> tuple[str, str]:
    """Split ``http://arxiv.org/abs/2410.12345v2`` into id + version."""
    tail = id_url.rsplit("/", 1)[-1]
    if "v" in tail:
        base, _, ver = tail.rpartition("v")
        if ver.isdigit():
            return base, f"v{ver}"
    return tail, ""


def _parse_iso8601(value: str) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def download_pdf(
    result: ArxivResult,
    *,
    out_dir: Path,
    cutoff: datetime = DEFAULT_CUTOFF,
    client: httpx.Client | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Download a single paper PDF to ``out_dir`` and return its metadata.

    A defence-in-depth check re-verifies the cutoff. Any record that
    slipped through ``search_arxiv`` will raise :class:`CutoffViolation`
    here before its PDF lands on disk.
    """
    if result.submitted_at >= cutoff:
        raise CutoffViolation(
            f"refusing to download {result.id_with_version}: "
            f"submitted_at {result.submitted_at.isoformat()} >= cutoff {cutoff.isoformat()}"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "source.pdf"
    if pdf_path.exists() and not overwrite:
        digest = _sha256_file(pdf_path)
    else:
        owned_client = client is None
        http = client or httpx.Client(timeout=httpx.Timeout(120.0), follow_redirects=True)
        try:
            response = http.get(result.pdf_url)
            response.raise_for_status()
            pdf_path.write_bytes(response.content)
        finally:
            if owned_client:
                http.close()
        digest = _sha256_file(pdf_path)

    return {
        "arxiv_id": result.arxiv_id,
        "version": result.version,
        "submitted_at": result.submitted_at.isoformat(),
        "pdf_path": str(pdf_path),
        "pdf_sha256": digest,
        "pdf_bytes": pdf_path.stat().st_size,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
