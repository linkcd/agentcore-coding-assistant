"""Shared startup handles both adapters without assistant-specific branches."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from agentcore_runtime.agent_images.codex import run as codex
from agentcore_runtime.agent_images.common import runtime
from agentcore_runtime.agent_images.opencode import run as opencode


@pytest.mark.parametrize("path", ["", "/usr/bin:/bin", "/custom/bin:/usr/bin:/custom/bin"])
def test_tool_paths_work_without_a_login_shell(path, tmp_path):
    current = {"HOME": str(tmp_path / "home"), "PATH": path}
    env = runtime.tool_environment(current)
    paths = env["PATH"].split(os.pathsep)
    assert paths.index("/usr/local/bin") < paths.index("/usr/bin")
    assert str(tmp_path / "home/.local/bin") in paths
    assert str(Path(env["CARGO_HOME"]) / "bin") in paths
    assert env["PNPM_HOME"] in paths and env["GOBIN"] in paths
    assert len(paths) == len(set(paths))
    if "/custom/bin" in path:
        assert paths[0] == "/custom/bin"
    assert current["PATH"] == path


def test_caches_and_project_environments_are_local_and_explicit_overrides_survive(tmp_path):
    project = tmp_path / "persistent/repo"
    current = {
        "HOME": str(tmp_path / "home"),
        "AGENTCORE_WORKDIR": str(project),
        "AGENTCORE_TOOL_ROOT": str(tmp_path / "local"),
    }
    env = runtime.tool_environment(current)
    runtime.prepare_tool_directories(env)
    assert not project.exists()
    for name in (
        "UV_CACHE_DIR",
        "UV_TOOL_DIR",
        "UV_PYTHON_INSTALL_DIR",
        "TMPDIR",
        "UV_PROJECT_ENVIRONMENT",
        "CARGO_TARGET_DIR",
        "GOCACHE",
        "GOMODCACHE",
        "npm_config_cache",
        "PNPM_CONFIG_STORE_DIR",
    ):
        assert Path(env[name]).is_relative_to(tmp_path / "local")
    assert not Path(env["UV_PROJECT_ENVIRONMENT"]).exists()
    assert env["UV_LINK_MODE"] == "copy"
    other = runtime.tool_environment({**current, "AGENTCORE_WORKDIR": str(project / "other")})
    assert other["UV_PROJECT_ENVIRONMENT"] != env["UV_PROJECT_ENVIRONMENT"]
    overrides = {
        "UV_CACHE_DIR": str(tmp_path / "chosen"),
        "npm_config_prefix": str(tmp_path / "npm"),
    }
    selected = runtime.tool_environment({**current, **overrides})
    assert all(selected[key] == value for key, value in overrides.items())
    assert str(tmp_path / "npm/bin") in selected["PATH"].split(os.pathsep)


def test_only_allowed_settings_cross_the_pid1_boundary():
    current = {"REGION": "explicit"}
    container = b"REGION=container\0MODEL=example\0AWS_SECRET_ACCESS_KEY=synthetic\0BROKEN"
    env = runtime.inherit_settings(current, container, ("REGION", "MODEL"))
    assert env == {"REGION": "explicit", "MODEL": "example"}
    assert current == {"REGION": "explicit"}


def test_dedicated_mount_is_the_profile_directory_and_preserves_config(monkeypatch, tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    monkeypatch.setattr(Path, "is_mount", lambda path: path == mount)
    config = mount / "opencode.json"
    config.write_text("existing configuration")
    env = {"AGENTCORE_REQUIRED_MOUNT": str(mount), "AGENTCORE_PROFILE_DIRECTORY": str(mount)}
    runtime.prepare_profile_directory(env)
    assert env["AGENTCORE_WORKDIR"] == str(mount)
    assert config.read_text() == "existing configuration"
    assert not (mount / "profiles").exists()


@pytest.mark.parametrize(
    "failure", ["unmounted", "outside", "outside-workdir", "nested", "symlink"]
)
def test_profile_bootstrap_rejects_wrong_mount_or_directory(monkeypatch, tmp_path, failure):
    mount = tmp_path / "mount"
    mount.mkdir()
    env = {
        "AGENTCORE_REQUIRED_MOUNT": str(mount),
        "AGENTCORE_PROFILE_DIRECTORY": str(mount),
        "AGENTCORE_WORKDIR": str(mount),
    }
    monkeypatch.setattr(Path, "is_mount", lambda path: path == mount and failure != "unmounted")
    if failure == "outside":
        env["AGENTCORE_PROFILE_DIRECTORY"] = str(tmp_path / "outside/profile1")
    elif failure == "outside-workdir":
        env["AGENTCORE_WORKDIR"] = str(tmp_path / "other")
    elif failure == "nested":
        env["AGENTCORE_PROFILE_DIRECTORY"] = str(mount / "profiles/profile1")
    elif failure == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(mount, target_is_directory=True)
        env["AGENTCORE_PROFILE_DIRECTORY"] = str(alias)
    with pytest.raises(ValueError):
        runtime.prepare_profile_directory(env)
    assert not list(mount.iterdir())


@pytest.mark.parametrize("adapter", [opencode, codex])
def test_shared_launch_preserves_arguments_cwd_and_configuration(monkeypatch, tmp_path, adapter):
    monkeypatch.setenv("AGENTCORE_TOOL_ROOT", str(tmp_path / "runtime"))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGENTCORE_WORKDIR", str(project))
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "example.model")
    monkeypatch.setenv("BEDROCK_INFERENCE_REGION", "us-east-2")
    monkeypatch.setenv("BEDROCK_ENDPOINT_TYPE", "runtime")
    arguments = ["--session", "a b;literal"]
    monkeypatch.setattr(sys, "argv", ["run.py", *arguments])
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=PermissionError))
    execute, chdir = Mock(), Mock()
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    monkeypatch.setattr(runtime.os, "chdir", chdir)
    adapter.main()
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
        opencode.main()
    execute.assert_not_called()


@pytest.mark.parametrize("adapter", [opencode, codex])
@pytest.mark.parametrize(
    "endpoint_type", ["", "Bedrock Runtime", "Bedrock Mantle", "Runtime", "runtime "]
)
def test_invalid_endpoint_override_never_launches(monkeypatch, adapter, endpoint_type):
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("BEDROCK_INFERENCE_REGION", "eu-west-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "example.model")
    monkeypatch.delenv("BEDROCK_ENDPOINT_TYPE", raising=False)
    if endpoint_type is not None:
        monkeypatch.setenv("BEDROCK_ENDPOINT_TYPE", endpoint_type)
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"")
    execute = Mock()
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    with pytest.raises(SystemExit):
        adapter.main()
    execute.assert_not_called()


@pytest.mark.parametrize("adapter", [opencode, codex])
def test_model_only_settings_use_image_defaults_without_changing_the_input(adapter):
    settings = {
        "AWS_REGION": "eu-west-1",
        "BEDROCK_INFERENCE_REGION": "eu-west-1",
        "BEDROCK_MODEL_ID": "global.openai.gpt-5.6-sol",
    }
    env = adapter.launch_environment(settings, b"")
    assert "BEDROCK_ENDPOINT_TYPE" not in settings
    if adapter is codex:
        assert 'model_provider="amazon-bedrock-runtime"' in adapter.launch_arguments(env, [])
    else:
        assert "BEDROCK_ENDPOINT_TYPE" not in env
        assert "OPENCODE_CONFIG_CONTENT" not in env


@pytest.mark.parametrize("adapter", [opencode, codex])
def test_shell_endpoint_choice_takes_precedence_over_pid1(adapter):
    env = adapter.launch_environment(
        {
            "AWS_REGION": "eu-west-1",
            "BEDROCK_INFERENCE_REGION": "eu-west-1",
            "BEDROCK_MODEL_ID": "example.model",
            "BEDROCK_ENDPOINT_TYPE": "runtime",
        },
        b"BEDROCK_ENDPOINT_TYPE=mantle\0",
    )
    assert env["BEDROCK_ENDPOINT_TYPE"] == "runtime"


@pytest.mark.parametrize("mounted", [True, False])
def test_configured_mount_must_be_ready_before_launch(monkeypatch, mounted, tmp_path):
    monkeypatch.setenv("AGENTCORE_TOOL_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "example.model")
    monkeypatch.setenv("BEDROCK_ENDPOINT_TYPE", "runtime")
    monkeypatch.delenv("AGENTCORE_REQUIRED_MOUNT", raising=False)
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"AGENTCORE_REQUIRED_MOUNT=/mnt/workspace\0")
    monkeypatch.setattr(Path, "is_mount", lambda path: mounted and str(path) == "/mnt/workspace")
    monkeypatch.setattr(runtime.os, "chdir", Mock())
    execute = Mock()
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    if mounted:
        opencode.main()
        assert execute.call_args.args[2]["AGENTCORE_REQUIRED_MOUNT"] == "/mnt/workspace"
    else:
        with pytest.raises(SystemExit):
            opencode.main()
        execute.assert_not_called()


@pytest.mark.parametrize("image_variable", ["HERDR_RUNTIME_TEST_IMAGE", "CODEX_RUNTIME_TEST_IMAGE"])
def test_both_images_run_the_shared_health_contract_without_an_assistant(image_variable):
    image = os.environ.get(image_variable)
    if not image:
        pytest.skip(f"Set {image_variable} for the container health check")
    root = Path(__file__).resolve().parents[3]
    legal_hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("LICENSE", "NOTICE")
    }
    script = (
        f"legal_hashes = {legal_hashes!r}\n"
        + """
import hashlib, json, subprocess, time, urllib.request
from pathlib import Path
for name, expected in legal_hashes.items():
    assert hashlib.sha256((Path('/app') / name).read_bytes()).hexdigest() == expected
server = subprocess.Popen(['/usr/local/bin/python3', '/app/healthcheck.py'])
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
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            image,
            "/usr/local/bin/python3",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
