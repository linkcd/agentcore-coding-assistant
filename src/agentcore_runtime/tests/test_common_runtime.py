"""Shared startup handles both adapters without assistant-specific branches."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from agentcore_runtime.codex.image import assistant as codex
from agentcore_runtime.common import runtime
from agentcore_runtime.opencode.image import assistant as opencode


def test_only_allowed_settings_cross_the_pid1_boundary():
    current = {"REGION": "explicit"}
    container = b"REGION=container\0MODEL=example\0AWS_SECRET_ACCESS_KEY=synthetic\0BROKEN"
    env = runtime.inherit_settings(current, container, ("REGION", "MODEL"))
    assert env == {"REGION": "explicit", "MODEL": "example"}
    assert current == {"REGION": "explicit"}


@pytest.mark.parametrize("adapter", [opencode, codex])
def test_shared_launch_preserves_arguments_cwd_and_configuration(monkeypatch, tmp_path, adapter):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(adapter.WORKDIR_SETTING, str(project))
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "example.model")
    monkeypatch.setenv("BEDROCK_INFERENCE_REGION", "us-east-2")
    arguments = ["--session", "a b;literal"]
    monkeypatch.setattr(sys, "argv", ["launch.py", *arguments])
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=PermissionError))
    execute, chdir = Mock(), Mock()
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    monkeypatch.setattr(runtime.os, "chdir", chdir)
    runtime.launch(adapter)
    executable, argv, env = execute.call_args.args
    assert argv[0] == executable
    assert argv[-2:] == arguments
    assert "--yolo" not in argv
    chdir.assert_called_once_with(str(project))


def test_invalid_environment_never_executes_a_program(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"")
    execute = Mock()
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    with pytest.raises(SystemExit):
        runtime.launch(opencode)
    execute.assert_not_called()


@pytest.mark.parametrize("image_variable", ["HERDR_RUNTIME_TEST_IMAGE", "CODEX_RUNTIME_TEST_IMAGE"])
def test_both_images_run_the_shared_health_contract_without_an_assistant(image_variable):
    image = os.environ.get(image_variable)
    if not image:
        pytest.skip(f"Set {image_variable} for the container health check")
    script = """
import json, subprocess, time, urllib.request
server = subprocess.Popen(['python3.11', '/app/healthcheck.py'])
try:
    deadline = time.monotonic() + 10
    while True:
        try:
            response = urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=1)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    with response:
        assert json.load(response) == {'status': 'Healthy'}
    url = 'http://127.0.0.1:8080/invocations'
    with urllib.request.urlopen(url, data=b'{}', timeout=1) as reply:
        assert 'AgentCore Shell' in json.load(reply)['message']
finally:
    server.terminate()
    server.wait(timeout=5)
"""
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image, "python3.11", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
