"""MinerU v4 client for precise PDF parsing.

Used by:
* the corpus builder (``scripts/build_corpus.py``), which parses every
  pre-cutoff PDF into ``full.md`` + ``images/`` + ``content_list.json``
* the vault pipeline (``scripts/parse_target_paper.py``), which parses
  the target paper into ``judge/vault/`` only.

Participants never call this module — their containers are not given
``MINERU_KEY``.

The client is structured so that every HTTP boundary can be mocked in
tests: ``submit_batch``, ``poll_task`` and ``download_zip`` are the
three I/O units; ``parse_pdf_url`` is the high-level orchestrator.
"""

from __future__ import annotations

import dataclasses
import io
import logging
import os
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
import orjson

logger = logging.getLogger(__name__)

MINERU_BASE = "https://mineru.net/api/v4"
MINERU_MODEL_VERSION = "vlm"

#: Files inside ``full_zip_url`` that we keep (and only these). Anything
#: else MinerU bundles is discarded so the corpus stays auditable.
_KEEP_FILES = ("full.md", "content_list.json", "layout.json", "middle.json")
_KEEP_DIRS = ("images/",)

_DEFAULT_POLL_INTERVAL = 10.0
_DEFAULT_MAX_POLL_SECONDS = 1800.0


class MineruError(RuntimeError):
    """Raised when a MinerU call returns an error or never completes."""


@dataclasses.dataclass(frozen=True)
class ParseResult:
    """Filesystem layout produced by :func:`parse_pdf_url`."""

    paper_dir: Path
    full_md: Path
    content_list: Path | None
    images_dir: Path
    mineru_meta: Path
    markdown_sha256: str


class MineruClient:
    """Thin client for the MinerU v4 batch-URL parsing API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = MINERU_BASE,
        model_version: str = MINERU_MODEL_VERSION,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        max_poll_seconds: float = _DEFAULT_MAX_POLL_SECONDS,
    ) -> None:
        if not api_key:
            raise ValueError("MinerU api_key is required")
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._model_version = model_version
        self._poll_interval = poll_interval
        self._max_poll_seconds = max_poll_seconds
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @classmethod
    def from_env(cls, env_var: str = "MINERU_KEY", **kwargs: Any) -> MineruClient:
        key = os.environ.get(env_var, "").strip()
        if not key:
            raise RuntimeError(
                f"{env_var} is not set; cannot reach MinerU. "
                "Copy .env.example to .env and fill it in."
            )
        return cls(api_key=key, **kwargs)

    def submit_batch(
        self,
        pdf_urls: Iterable[str],
        *,
        is_ocr: bool = False,
    ) -> str:
        """Create a batch parsing task. Returns the MinerU task id."""
        payload = {
            "model_version": self._model_version,
            "files": [
                {"url": url, "is_ocr": is_ocr}
                for url in pdf_urls
            ],
        }
        if not payload["files"]:
            raise ValueError("submit_batch requires at least one PDF URL")
        with httpx.Client(timeout=httpx.Timeout(60.0)) as http:
            response = http.post(
                f"{self._base}/extract/task/batch",
                headers=self._headers,
                content=orjson.dumps(payload),
            )
        body = _decode_json(response)
        if response.status_code >= 400:
            raise MineruError(f"submit_batch failed: {response.status_code} {body!r}")
        task_id = _extract_task_id(body)
        if not task_id:
            raise MineruError(f"submit_batch returned no task_id: {body!r}")
        return task_id

    def poll_task(self, task_id: str) -> dict[str, Any]:
        """Poll the batch task until it is complete or times out.

        Returns the final raw response body (which contains the
        per-file ``full_zip_url`` entries). Raises :class:`MineruError`
        on timeout or terminal failure.
        """
        deadline = time.monotonic() + self._max_poll_seconds
        while time.monotonic() < deadline:
            with httpx.Client(timeout=httpx.Timeout(60.0)) as http:
                response = http.get(
                    f"{self._base}/extract-results/batch/{task_id}",
                    headers=self._headers,
                )
            body = _decode_json(response)
            if response.status_code >= 400:
                raise MineruError(f"poll_task failed: {response.status_code} {body!r}")

            state = _extract_state(body).lower()
            if state in {"done", "success", "completed", "finished"}:
                return body
            if state in {"failed", "error", "timeout"}:
                raise MineruError(f"task {task_id} terminal state {state!r}: {body!r}")

            logger.debug("task %s state=%s; sleeping %.1fs", task_id, state, self._poll_interval)
            time.sleep(self._poll_interval)

        raise MineruError(f"task {task_id} did not complete within {self._max_poll_seconds:.0f}s")

    def download_zip(self, zip_url: str) -> bytes:
        with httpx.Client(timeout=httpx.Timeout(300.0), follow_redirects=True) as http:
            response = http.get(zip_url)
        if response.status_code >= 400:
            raise MineruError(f"download_zip failed: {response.status_code}")
        return response.content


def extract_zip(
    zip_bytes: bytes,
    *,
    out_dir: Path,
    keep_files: tuple[str, ...] = _KEEP_FILES,
    keep_dirs: tuple[str, ...] = _KEEP_DIRS,
) -> dict[str, Path]:
    """Extract the curated subset of files from a MinerU result zip."""
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if name in keep_files or any(name.startswith(d) for d in keep_dirs):
                dest = out_dir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(info))
                extracted[name] = dest
    return extracted


def parse_pdf_url(
    client: MineruClient,
    pdf_url: str,
    *,
    paper_dir: Path,
) -> ParseResult:
    """End-to-end: submit, poll, download, extract, write metadata."""
    paper_dir.mkdir(parents=True, exist_ok=True)
    task_id = client.submit_batch([pdf_url])
    result = client.poll_task(task_id)
    zip_url = _extract_zip_url(result, pdf_url)
    if not zip_url:
        raise MineruError(f"no full_zip_url in task result: {result!r}")
    zip_bytes = client.download_zip(zip_url)
    files = extract_zip(zip_bytes, out_dir=paper_dir)

    full_md = files.get("full.md")
    if full_md is None:
        raise MineruError(f"MinerU result missing full.md: keys={sorted(files)}")
    content_list = files.get("content_list.json")
    images_dir = paper_dir / "images"

    markdown_bytes = full_md.read_bytes()
    import hashlib
    markdown_sha256 = hashlib.sha256(markdown_bytes).hexdigest()

    mineru_meta_path = paper_dir / "mineru_meta.json"
    mineru_meta_path.write_bytes(
        orjson.dumps(
            {
                "task_id": task_id,
                "pdf_url": pdf_url,
                "model_version": client._model_version,  # noqa: SLF001 - internal field by design
                "extracted_files": sorted(files.keys()),
            },
            option=orjson.OPT_INDENT_2,
        )
    )

    return ParseResult(
        paper_dir=paper_dir,
        full_md=full_md,
        content_list=content_list,
        images_dir=images_dir,
        mineru_meta=mineru_meta_path,
        markdown_sha256=markdown_sha256,
    )


def _decode_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw_text": response.text}


def _extract_task_id(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    data = body.get("data", body)
    if isinstance(data, dict):
        for key in ("task_id", "id", "batch_id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _extract_state(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    data = body.get("data", body)
    if isinstance(data, dict):
        for key in ("state", "status"):
            value = data.get(key)
            if isinstance(value, str):
                return value
    return ""


def _extract_zip_url(body: Any, pdf_url: str) -> str:
    if not isinstance(body, dict):
        return ""
    data = body.get("data", body)
    candidates: list[dict[str, Any]] = []
    if isinstance(data, dict):
        files = data.get("files") or data.get("results") or data.get("extract_result") or []
        if isinstance(files, list):
            candidates = [f for f in files if isinstance(f, dict)]
        if not candidates and "full_zip_url" in data:
            return str(data["full_zip_url"])
    for cand in candidates:
        if cand.get("url") == pdf_url and isinstance(cand.get("full_zip_url"), str):
            return cand["full_zip_url"]
    for cand in candidates:
        url = cand.get("full_zip_url")
        if isinstance(url, str) and url:
            return url
    return ""
