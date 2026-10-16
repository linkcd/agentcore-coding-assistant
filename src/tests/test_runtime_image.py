"""Runtime bootstrap and HTTP contract without AWS/model requests."""

import json
import os
import subprocess
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from herdr_agentcore.provision import IMAGE_CONTEXT, docker, docker_environment
from herdr_agentcore.runtime_image import launch
from herdr_agentcore.runtime_image.healthcheck import Handler

MODEL = "anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_shell_receives_deployment_settings_but_not_pid1_credentials():
    container = (
        f"AWS_REGION=us-west-2\0BEDROCK_MODEL_ID={MODEL}\0"
        "AWS_ACCESS_KEY_ID=synthetic\0AWS_SESSION_TOKEN=synthetic\0"
    ).encode()
    env = launch.launch_environment({"HOME": "/home/agent"}, container)
    assert env["AWS_REGION"] == "us-west-2"
    assert env["BEDROCK_MODEL_ID"] == MODEL
    assert env["AWS_PROFILE"] == "default"
    assert env["OPENCODE_CONFIG"] == "/app/opencode.json"
    assert env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    assert not {"AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN"} & env.keys()


def test_explicit_runtime_settings_take_precedence():
    env = launch.launch_environment(
        {
            "AWS_REGION": "us-east-1",
            "BEDROCK_MODEL_ID": MODEL,
            "OPENCODE_CONFIG": "/custom/config.json",
            "OPENCODE_WORKDIR": "/work/repository",
        },
        b"AWS_REGION=us-west-2\0BEDROCK_MODEL_ID=other\0",
    )
    assert env["AWS_REGION"] == "us-east-1"
    assert env["OPENCODE_CONFIG"] == "/custom/config.json"
    assert env["OPENCODE_WORKDIR"] == "/work/repository"


def test_missing_runtime_settings_fail_before_launch():
    with pytest.raises(ValueError, match="AWS_REGION and BEDROCK_MODEL_ID"):
        launch.launch_environment({}, b"")


def test_launch_forwards_session_argv_and_preserves_user_configuration(monkeypatch, tmp_path):
    config = tmp_path / "opencode.json"
    original = '{"mcp": {}, "permission": {"edit": "ask"}}'
    config.write_text(original)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENCODE_CONFIG", str(config))
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODEL)
    monkeypatch.delenv("OPENCODE_WORKDIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["launch.py", "--session", "saved-conversation"])
    chdir, execute = Mock(), Mock()
    monkeypatch.setattr(launch.os, "chdir", chdir)
    monkeypatch.setattr(launch.os, "execvpe", execute)
    launch.main()
    chdir.assert_called_once_with(str(tmp_path))
    executable, argv, env = execute.call_args.args
    assert executable == "opencode"
    assert argv == ["opencode", "--session", "saved-conversation"]
    assert env["AWS_PROFILE"] == "default"
    assert config.read_text() == original
    assert env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"


def test_http_health_contract():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/ping", timeout=5) as response:
            assert json.load(response) == {"status": "Healthy"}
        with urllib.request.urlopen(base + "/invocations", data=b"{}", timeout=5) as response:
            assert "Herdr" in json.load(response)["message"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_packaged_runtime_configuration_matches_pinned_opencode():
    config = json.loads((IMAGE_CONTEXT / "opencode.json").read_text())
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["enabled_providers"] == ["amazon-bedrock"]
    assert config["small_model"] == config["model"]
    assert "apiKey" not in json.dumps(config)
    assert all(
        (IMAGE_CONTEXT / file).is_file()
        for file in (
            "Dockerfile",
            ".dockerignore",
            "run.sh",
            "launch.py",
            "healthcheck.py",
            "NOTICE",
            "LICENSE",
        )
    )


@pytest.mark.skipif(not os.environ.get("HERDR_RUNTIME_TEST_IMAGE"), reason="Opt-in Docker test")
def test_built_image_resolves_opencode_configuration_without_credentials():
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            "AWS_REGION=us-west-2",
            "-e",
            f"BEDROCK_MODEL_ID={MODEL}",
            "-e",
            "OPENCODE_DISABLE_MODELS_FETCH=1",
            "-e",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS=1",
            os.environ["HERDR_RUNTIME_TEST_IMAGE"],
            "/app/run.sh",
            "debug",
            "config",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    config = json.loads(result.stdout)
    assert config["model"] == "amazon-bedrock/" + MODEL
    assert config["provider"]["amazon-bedrock"]["options"]["region"] == "us-west-2"


@pytest.mark.skipif(not os.environ.get("HERDR_RUNTIME_TEST_IMAGE"), reason="Opt-in Docker test")
def test_real_buildx_is_discoverable_with_temporary_docker_config():
    plugins = json.loads(docker("info", "--format", "{{json .ClientInfo.Plugins}}", capture=True))
    directories = sorted({str(Path(plugin["Path"]).parent) for plugin in plugins})
    host = docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}", capture=True)
    with docker_environment(host, directories) as env:
        assert "buildx" in docker("buildx", "version", env=env, capture=True)
