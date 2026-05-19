from __future__ import annotations

from pathlib import Path

from scripts.target_paper import ensure_target_markdown, target_from_task, task_vault_dir


def test_target_from_task_uses_arxiv_id(tmp_path: Path):
    task = tmp_path / "kakeya3d_discovery.yaml"
    task.write_text('target_paper:\n  arxiv_id: "2502.17655"\n', encoding="utf-8")

    arxiv_id, pdf_url = target_from_task(task)

    assert arxiv_id == "2502.17655"
    assert pdf_url == "https://arxiv.org/pdf/2502.17655.pdf"
    assert task_vault_dir(task, tmp_path / "vault") == tmp_path / "vault" / "kakeya3d_discovery"


def test_ensure_target_markdown_uses_task_vault_dir(tmp_path: Path):
    task = tmp_path / "kakeya3d_discovery.yaml"
    task.write_text('target_paper:\n  arxiv_id: "2502.17655"\n', encoding="utf-8")
    full_md = tmp_path / "vault" / "kakeya3d_discovery" / "target_paper" / "full.md"
    full_md.parent.mkdir(parents=True)
    full_md.write_text("target paper", encoding="utf-8")

    path, digest = ensure_target_markdown(task, tmp_path / "vault")

    assert path == full_md
    assert len(digest) == 64
