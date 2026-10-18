"""Codex example startup uses native IAM authentication and preserves arguments."""

import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from agentcore_runtime.codex.image import assistant
from agentcore_runtime.common import runtime


def test_codex_only_inherits_nonsecret_runtime_settings():
    env = assistant.launch_environment(
        {},
        b"AWS_REGION=us-west-2\0BEDROCK_INFERENCE_REGION=us-east-2\0BEDROCK_MODEL_ID=openai.gpt-5.5\0AWS_SECRET_ACCESS_KEY=synthetic\0",
    )
    assert env["BEDROCK_INFERENCE_REGION"] == "us-east-2"
    assert "AWS_SECRET_ACCESS_KEY" not in env


def test_codex_launch_preserves_user_config_and_native_arguments(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('approval_policy = "on-request"')
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BEDROCK_INFERENCE_REGION", "us-east-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "openai.gpt-5.5")
    monkeypatch.setattr(sys, "argv", ["launch.py", "--version"])
    execute = Mock()
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    monkeypatch.setattr(runtime.os, "chdir", Mock())
    runtime.launch(assistant)
    executable, argv, env = execute.call_args.args
    assert executable == "codex" and argv[-1] == "--version"
    assert 'model_provider="amazon-bedrock"' in argv
    assert "--yolo" not in argv
    assert config.read_text() == 'approval_policy = "on-request"'


@pytest.mark.skipif(
    not os.environ.get("CODEX_RUNTIME_TEST_IMAGE"), reason="Opt-in Codex image test"
)
def test_codex_image_starts_cli_without_credentials_or_network():
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            "BEDROCK_INFERENCE_REGION=us-east-2",
            "-e",
            "BEDROCK_MODEL_ID=openai.gpt-5.5",
            os.environ["CODEX_RUNTIME_TEST_IMAGE"],
            "/app/run.sh",
            "--version",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "codex-cli 0.163.0" in result.stdout
