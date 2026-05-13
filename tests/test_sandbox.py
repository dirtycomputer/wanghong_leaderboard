"""Tests for the sandbox runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from runner.sandbox import (
    INTERNAL_NETWORK,
    REQUIRED_OUTPUTS,
    SandboxConfig,
    SandboxError,
    build_docker_command,
    is_immutable_image_reference,
    run_in_sandbox,
    validate_harness_manifest_safety,
    validate_outputs,
)


def _config(tmp_path: Path, **overrides) -> SandboxConfig:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    task = tmp_path / "task.yaml"
    task.write_text("prompt: hello\n", encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    defaults = dict(
        image_ref="ghcr.io/foo/bar@sha256:" + ("a" * 64),
        run_id="run-123",
        corpus_root=corpus,
        task_path=task,
        output_dir=output,
        proxy_api_base="http://leaderboard-proxy/v1",
        proxy_token="ephemeral-xyz",
        cpu=4,
        memory_gb=8,
        max_wall_time_seconds=3600,
    )
    defaults.update(overrides)
    return SandboxConfig(**defaults)


def test_immutable_image_reference_accepts_sha256_digest():
    assert is_immutable_image_reference("ghcr.io/x/y@sha256:" + "0" * 64)


@pytest.mark.parametrize(
    "ref",
    [
        "ghcr.io/x/y:latest",
        "ghcr.io/x/y:main",
        "ghcr.io/x/y:v1",
        "",
        "ghcr.io/x/y",
        "ghcr.io/x/y@sha256:tooShort",
    ],
)
def test_immutable_image_reference_rejects_floating_or_invalid(ref):
    assert not is_immutable_image_reference(ref)


def test_build_docker_command_pins_invariants(tmp_path: Path):
    config = _config(tmp_path)
    cmd = build_docker_command(config)
    assert cmd[:2] == ["docker", "run"]
    assert "--rm" in cmd
    network_idx = cmd.index("--network")
    assert cmd[network_idx + 1] == INTERNAL_NETWORK
    assert "--cap-drop" in cmd and "ALL" in cmd
    assert "--security-opt" in cmd and "no-new-privileges" in cmd
    assert "--read-only" in cmd
    # corpus is read-only
    assert any(v.endswith(":/corpus:ro") for v in cmd)
    # output is writeable
    assert any(v.endswith(":/output:rw") for v in cmd)
    # MODEL_NAME pinned, MODEL_API_BASE forwarded
    assert "MODEL_NAME=google/gemma-4-31b-it" in cmd
    assert any(e.startswith("MODEL_API_BASE=") for e in cmd)
    assert config.image_ref in cmd


def test_build_docker_command_refuses_floating_tag(tmp_path: Path):
    with pytest.raises(SandboxError):
        build_docker_command(_config(tmp_path, image_ref="ghcr.io/x/y:latest"))


def test_validate_outputs_lists_missing(tmp_path: Path):
    missing = validate_outputs(tmp_path)
    assert sorted(missing) == sorted(REQUIRED_OUTPUTS)


def test_validate_outputs_passes_when_all_present(tmp_path: Path):
    for name in REQUIRED_OUTPUTS:
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert validate_outputs(tmp_path) == []


def test_validate_harness_manifest_safety_rejects_unsafe_claims():
    manifest = {"claims": {"uses_external_apis": True}}
    with pytest.raises(SandboxError):
        validate_harness_manifest_safety(manifest)
    manifest = {"claims": {"requires_network": True}}
    with pytest.raises(SandboxError):
        validate_harness_manifest_safety(manifest)


def test_run_in_sandbox_invokes_subprocess(tmp_path: Path):
    captured: dict = {}

    class FakeCompletedProcess:
        def __init__(self):
            self.returncode = 0
            self.stdout = "hi"
            self.stderr = ""

    class FakeRunner:
        def run(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return FakeCompletedProcess()

    config = _config(tmp_path)
    result = run_in_sandbox(config, runner=FakeRunner())
    assert result.exit_code == 0
    assert captured["cmd"][:2] == ["docker", "run"]
    assert captured["kwargs"]["timeout"] == config.max_wall_time_seconds
    assert captured["kwargs"]["check"] is False
