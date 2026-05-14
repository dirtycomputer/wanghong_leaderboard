"""Tests for the MinerU v4 client."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import orjson
import pytest

from corpus import mineru_parse
from corpus.mineru_parse import (
    MineruClient,
    MineruError,
    extract_zip,
    parse_pdf_url,
)


def _zip_with(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extract_zip_keeps_only_curated_files(tmp_path: Path):
    payload = _zip_with(
        {
            "full.md": b"# title",
            "content_list.json": b"[]",
            "layout.json": b"{}",
            "images/fig1.png": b"PNG",
            "images/fig2.png": b"PNG",
            "random_log.txt": b"should be dropped",
            "raw/source.pdf": b"binary",
        }
    )
    files = extract_zip(payload, out_dir=tmp_path)
    assert set(files.keys()) == {
        "full.md",
        "content_list.json",
        "layout.json",
        "images/fig1.png",
        "images/fig2.png",
    }
    assert (tmp_path / "full.md").read_bytes() == b"# title"
    assert not (tmp_path / "random_log.txt").exists()
    assert not (tmp_path / "raw" / "source.pdf").exists()


class FakeMineruClient:
    """Stand-in for :class:`MineruClient` used by :func:`parse_pdf_url`."""

    def __init__(
        self,
        *,
        task_id: str = "task-1",
        zip_bytes: bytes = b"",
        poll_result: dict | None = None,
        model_version: str = "vlm",
    ) -> None:
        self.submitted: list[list[str]] = []
        self.polled: list[str] = []
        self.downloaded: list[str] = []
        self._task_id = task_id
        self._zip_bytes = zip_bytes
        # Real MinerU v4 ``extract-results/batch`` response shape:
        # the per-file state + zip url live under data.extract_result[].
        self._poll_result = poll_result or {
            "code": 0,
            "data": {
                "batch_id": task_id,
                "extract_result": [
                    {
                        "file_name": "2024.00001",
                        "state": "done",
                        "err_msg": "",
                        "full_zip_url": "https://example.com/result.zip",
                    }
                ],
            },
        }
        self._model_version = model_version

    def submit_batch(self, urls, *, is_ocr=False):
        self.submitted.append(list(urls))
        return self._task_id

    def poll_task(self, task_id):
        self.polled.append(task_id)
        return self._poll_result

    def download_zip(self, url):
        self.downloaded.append(url)
        return self._zip_bytes


def test_parse_pdf_url_writes_meta_and_hashes(tmp_path: Path):
    zip_bytes = _zip_with({"full.md": b"# Hello", "images/a.png": b"x"})
    client = FakeMineruClient(zip_bytes=zip_bytes)
    result = parse_pdf_url(
        client,  # type: ignore[arg-type]
        "https://arxiv.org/pdf/2024.00001.pdf",
        paper_dir=tmp_path / "paper",
    )
    assert client.submitted == [["https://arxiv.org/pdf/2024.00001.pdf"]]
    assert client.polled == ["task-1"]
    assert client.downloaded == ["https://example.com/result.zip"]
    assert result.full_md.read_bytes() == b"# Hello"
    meta = orjson.loads(result.mineru_meta.read_bytes())
    assert meta["model_version"] == "vlm"
    assert "full.md" in meta["extracted_files"]


def test_parse_pdf_url_raises_when_no_zip(tmp_path: Path):
    client = FakeMineruClient(
        poll_result={"code": 0, "data": {"batch_id": "x", "extract_result": []}}
    )
    with pytest.raises(MineruError):
        parse_pdf_url(
            client,  # type: ignore[arg-type]
            "https://arxiv.org/pdf/2024.00001.pdf",
            paper_dir=tmp_path / "paper",
        )


def test_parse_pdf_url_raises_when_missing_full_md(tmp_path: Path):
    client = FakeMineruClient(zip_bytes=_zip_with({"content_list.json": b"[]"}))
    with pytest.raises(MineruError):
        parse_pdf_url(
            client,  # type: ignore[arg-type]
            "https://arxiv.org/pdf/2024.00001.pdf",
            paper_dir=tmp_path / "paper",
        )


# A verbatim MinerU v4 ``extract-results/batch`` success payload, as
# captured from the live API during the P8 probe.
_REAL_DONE = {
    "code": 0,
    "msg": "ok",
    "trace_id": "06782c684c3b9123678fbce11eb31a4f",
    "data": {
        "batch_id": "b19e37f8-9e22-4c31-805d-38d30d6664cf",
        "extract_result": [
            {
                "file_name": "9807163v1",
                "state": "done",
                "err_msg": "",
                "full_zip_url": "https://cdn-mineru.example/result.zip",
            }
        ],
    },
}


def test_extract_task_id_prefers_batch_id():
    assert mineru_parse._extract_task_id(_REAL_DONE) == (
        "b19e37f8-9e22-4c31-805d-38d30d6664cf"
    )
    assert mineru_parse._extract_task_id({"data": {"task_id": "abc"}}) == "abc"
    assert mineru_parse._extract_task_id({}) == ""


def test_extract_state_reads_per_file_results():
    # Regression: the real API puts state at data.extract_result[].state,
    # NOT data.state. The original guessed parser returned "" here and
    # poll_task spun until timeout on every paper.
    assert mineru_parse._extract_state(_REAL_DONE) == "done"


def test_extract_state_running_when_any_file_incomplete():
    body = {
        "data": {
            "extract_result": [
                {"file_name": "a", "state": "done"},
                {"file_name": "b", "state": "running"},
            ]
        }
    }
    assert mineru_parse._extract_state(body) == "running"


def test_extract_state_failed_when_any_file_failed():
    body = {
        "data": {
            "extract_result": [
                {"file_name": "a", "state": "done"},
                {"file_name": "b", "state": "failed", "err_msg": "bad pdf"},
            ]
        }
    }
    assert mineru_parse._extract_state(body) == "failed"
    assert "bad pdf" in mineru_parse._extract_error(body)


def test_extract_state_falls_back_to_data_state():
    # Non-batch-shaped responses (or a provider tweak) may still put a
    # bare state field on data.
    assert mineru_parse._extract_state({"data": {"state": "Done"}}) == "Done"
    assert mineru_parse._extract_state({"status": "failed"}) == "failed"
    assert mineru_parse._extract_state({}) == ""


def test_extract_zip_url_from_real_shape():
    assert mineru_parse._extract_zip_url(
        _REAL_DONE, "https://arxiv.org/pdf/math/9807163v1"
    ) == "https://cdn-mineru.example/result.zip"


def test_extract_zip_url_matches_correct_file_in_multi_file_batch():
    body = {
        "data": {
            "extract_result": [
                {"file_name": "1111.11111", "state": "done", "full_zip_url": "https://a.zip"},
                {"file_name": "2222.22222", "state": "done", "full_zip_url": "https://b.zip"},
            ]
        }
    }
    assert mineru_parse._extract_zip_url(
        body, "https://arxiv.org/pdf/2222.22222.pdf"
    ) == "https://b.zip"


def test_mineru_client_requires_api_key():
    with pytest.raises(ValueError):
        MineruClient(api_key="")
