"""Codex example startup uses native IAM authentication and preserves arguments."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from agentcore_runtime.agent_images.codex import assistant
from agentcore_runtime.agent_images.common import runtime


def test_native_sandbox_profile_keeps_workspace_writes_without_full_root_access():
    path = Path(__file__).resolve().parents[1] / "agent_images/codex/codex-config.toml"
    config = tomllib.loads(path.read_text())
    assert config["default_permissions"] == "agentcore-workspace"
    profile = config["permissions"]["agentcore-workspace"]
    filesystem = profile["filesystem"]
    assert filesystem[":minimal"] == "read"
    assert ":root" not in filesystem and "/" not in filesystem
    assert filesystem[":workspace_roots"]["."] == "write"
    for metadata in (".git", ".agents", ".codex", ".aws"):
        assert filesystem[":workspace_roots"][metadata] == "read"
    assert "network" not in profile
    assert "approval_policy" not in config


def test_codex_only_inherits_nonsecret_runtime_settings():
    env = assistant.launch_environment(
        {},
        b"AWS_REGION=us-west-2\0BEDROCK_INFERENCE_REGION=us-east-2\0BEDROCK_MODEL_ID=openai.gpt-5.5\0"
        b"BEDROCK_ENDPOINT_TYPE=mantle\0AWS_SECRET_ACCESS_KEY=synthetic\0",
    )
    assert env["BEDROCK_INFERENCE_REGION"] == "us-east-2"
    assert env["BEDROCK_ENDPOINT_TYPE"] == "mantle"
    assert "AWS_SECRET_ACCESS_KEY" not in env


@pytest.mark.parametrize(
    "endpoint_type,provider,model",
    [
        (None, "amazon-bedrock-runtime", "global.openai.gpt-5.6-sol"),
        ("runtime", "amazon-bedrock-runtime", "global.openai.gpt-5.6-sol"),
        ("mantle", "amazon-bedrock", "openai.gpt-5.6-sol"),
    ],
)
def test_codex_launch_preserves_user_config_and_native_arguments(
    monkeypatch, tmp_path, endpoint_type, provider, model
):
    config = tmp_path / "config.toml"
    config.write_text('approval_policy = "on-request"')
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BEDROCK_INFERENCE_REGION", "us-east-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", model)
    monkeypatch.delenv("BEDROCK_ENDPOINT_TYPE", raising=False)
    if endpoint_type is not None:
        monkeypatch.setenv("BEDROCK_ENDPOINT_TYPE", endpoint_type)
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"")
    monkeypatch.setattr(sys, "argv", ["launch.py", "--version"])
    execute = Mock()
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    monkeypatch.setattr(runtime.os, "chdir", Mock())
    runtime.launch(assistant)
    executable, argv, env = execute.call_args.args
    assert executable == "codex" and argv[-1] == "--version"
    assert f'model_provider="{provider}"' in argv
    assert f'model_providers.{provider}.aws.region="us-east-2"' in argv
    assert argv[argv.index("--model") + 1] == model
    assert ('web_search="disabled"' in argv) == (endpoint_type != "mantle")
    assert "--yolo" not in argv
    assert config.read_text() == 'approval_policy = "on-request"'


@pytest.mark.skipif(
    not os.environ.get("CODEX_RUNTIME_TEST_IMAGE"), reason="Opt-in Codex image test"
)
@pytest.mark.parametrize("endpoint_type", [None, "runtime", "mantle"])
def test_codex_image_starts_cli_without_credentials_or_network(endpoint_type):
    model = "openai.gpt-5.6-sol" if endpoint_type == "mantle" else "global.openai.gpt-5.6-sol"
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
            f"BEDROCK_MODEL_ID={model}",
            *(
                ["-e", f"BEDROCK_ENDPOINT_TYPE={endpoint_type}"]
                if endpoint_type is not None
                else []
            ),
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
