"""Tests for the ``kakeya-lb`` CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

import orjson
import pytest
import yaml

from cli.kakeya_lb.main import main


def _starter_copy(dest: Path) -> Path:
    shutil.copytree(Path("starter"), dest)
    return dest


def test_validate_starter_succeeds(tmp_path: Path, capsys):
    target = _starter_copy(tmp_path / "h")
    rc = main(["validate", str(target)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK" in captured.out


def test_validate_refuses_external_apis(tmp_path: Path, capsys):
    target = _starter_copy(tmp_path / "h")
    yaml_path = target / "harness.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    raw["claims"]["uses_external_apis"] = True
    yaml_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    rc = main(["validate", str(target)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "uses_external_apis" in err


def test_validate_reports_schema_errors(tmp_path: Path, capsys):
    target = _starter_copy(tmp_path / "h")
    yaml_path = target / "harness.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    raw["resources"]["max_wall_time_hours"] = 99  # > 48
    yaml_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    rc = main(["validate", str(target)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "max_wall_time_hours" in err


def test_init_copies_starter(tmp_path: Path, capsys):
    dest = tmp_path / "fresh"
    rc = main(["init", str(dest)])
    assert rc == 0
    assert (dest / "Dockerfile").exists()
    assert (dest / "harness.yaml").exists()
    assert (dest / "src" / "main.py").exists()


def test_init_refuses_non_empty_dir_without_force(tmp_path: Path, capsys):
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "junk.txt").write_text("...", encoding="utf-8")
    rc = main(["init", str(dest)])
    assert rc == 1
    assert "already exists" in capsys.readouterr().err


def _write_valid_outputs(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "final_proof.md").write_text("# proof", encoding="utf-8")
    (dst / "self_critique.md").write_text("ok", encoding="utf-8")
    (dst / "cited_sources.json").write_bytes(orjson.dumps([]))
    (dst / "trace.jsonl").write_text("", encoding="utf-8")
    (dst / "proof_graph.json").write_bytes(
        orjson.dumps(
            {
                "schema_version": "1.0",
                "target_theorem": "Every Kakeya set in R^3 has Hausdorff dimension 3.",
                "definitions": [],
                "pre_cutoff_dependencies": [],
                "new_lemmas": [],
                "known_gaps": [],
                "final_implication": "Not derived.",
            }
        )
    )


def test_schema_check_passes_when_outputs_valid(tmp_path: Path, capsys):
    out = tmp_path / "output"
    _write_valid_outputs(out)
    rc = main(["schema-check", str(out)])
    assert rc == 0


def test_schema_check_fails_on_missing_file(tmp_path: Path, capsys):
    out = tmp_path / "output"
    _write_valid_outputs(out)
    (out / "final_proof.md").unlink()
    rc = main(["schema-check", str(out)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "final_proof.md" in err


def test_schema_check_fails_on_bad_proof_graph(tmp_path: Path, capsys):
    out = tmp_path / "output"
    _write_valid_outputs(out)
    (out / "proof_graph.json").write_bytes(orjson.dumps({"schema_version": "1.0"}))
    rc = main(["schema-check", str(out)])
    assert rc == 1
    assert "schema violation" in capsys.readouterr().err


def test_cli_requires_subcommand(capsys):
    with pytest.raises(SystemExit):
        main([])
