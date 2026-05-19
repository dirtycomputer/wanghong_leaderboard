"""Prepare the private target paper used by the judge."""

from __future__ import annotations

import hashlib
import io
import os
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
import yaml

MINERU_BASE = "https://mineru.net/api/v4"


def target_from_task(task_path: Path) -> tuple[str, str]:
    task = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
    arxiv_id = str((task.get("target_paper") or {}).get("arxiv_id") or "").strip()
    if not arxiv_id:
        raise RuntimeError(f"{task_path} is missing target_paper.arxiv_id")
    return arxiv_id, f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def task_vault_dir(task_path: Path, vault_root: Path) -> Path:
    return vault_root / task_path.stem


def ensure_target_markdown(task_path: Path, vault_root: Path) -> tuple[Path, str]:
    arxiv_id, pdf_url = target_from_task(task_path)
    out_dir = task_vault_dir(task_path, vault_root) / "target_paper"
    full_md = out_dir / "full.md"
    if not full_md.exists():
        _parse_with_mineru(pdf_url, out_dir)
    return full_md, _sha256(full_md)


def _parse_with_mineru(pdf_url: str, out_dir: Path) -> None:
    key = os.environ.get("MINERU_KEY", "").strip()
    if not key:
        raise RuntimeError("MINERU_KEY is required to parse the target paper")

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True) as http:
        submit = http.post(
            f"{MINERU_BASE}/extract/task/batch",
            headers=headers,
            json={"model_version": "vlm", "files": [{"url": pdf_url, "is_ocr": False}]},
        )
        submit.raise_for_status()
        task_id = _task_id(submit.json())

        zip_url = ""
        for _ in range(180):
            result = http.get(f"{MINERU_BASE}/extract-results/batch/{task_id}", headers=headers)
            result.raise_for_status()
            item = _first_result(result.json())
            state = str(item.get("state") or "").lower()
            if state in {"done", "success", "completed", "finished"}:
                zip_url = str(item.get("full_zip_url") or "")
                break
            if state in {"failed", "error", "timeout"}:
                raise RuntimeError(f"MinerU failed: {item!r}")
            time.sleep(10)

        if not zip_url:
            raise RuntimeError("MinerU did not return full_zip_url")
        archive = http.get(zip_url)
        archive.raise_for_status()

    _extract(archive.content, out_dir)
    if not (out_dir / "full.md").exists():
        raise RuntimeError("MinerU result missing full.md")


def _task_id(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    task_id = data.get("batch_id")
    if not task_id:
        raise RuntimeError(f"MinerU submit returned no batch_id: {payload!r}")
    return str(task_id)


def _first_result(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    results = data.get("extract_result") or []
    if not results:
        return {}
    first = results[0]
    return first if isinstance(first, dict) else {}


def _extract(zip_bytes: bytes, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    keep_files = {"full.md", "content_list.json", "layout.json", "middle.json"}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name not in keep_files and not name.startswith("images/"):
                continue
            dest = out_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
