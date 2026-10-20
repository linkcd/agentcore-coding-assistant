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

from agentcore_runtime.agent_images.common import runtime
from agentcore_runtime.agent_images.common.healthcheck import Handler
from agentcore_runtime.agent_images.opencode import run as launcher

IMAGE_CONTEXT = Path(__file__).resolve().parents[1] / "agent_images/opencode"
COMMON = Path(__file__).resolve().parents[1] / "agent_images/common"

MODEL = "anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_shell_receives_deployment_settings_but_not_pid1_credentials():
    container = (
        f"AWS_REGION=us-west-2\0BEDROCK_MODEL_ID={MODEL}\0"
        "BEDROCK_ENDPOINT_TYPE=runtime\0"
        "AWS_ACCESS_KEY_ID=synthetic\0AWS_SESSION_TOKEN=synthetic\0"
    ).encode()
    env = launcher.launch_environment({"HOME": "/home/agent"}, container)
    assert env["AWS_REGION"] == "us-west-2"
    assert env["BEDROCK_MODEL_ID"] == MODEL
    assert env["BEDROCK_ENDPOINT_TYPE"] == "runtime"
    assert env["AWS_PROFILE"] == "default"
    assert env["OPENCODE_CONFIG"] == "/app/opencode.json"
    assert env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    assert not {"AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN"} & env.keys()


def test_explicit_runtime_settings_take_precedence():
    env = launcher.launch_environment(
        {
            "AWS_REGION": "us-east-1",
            "BEDROCK_MODEL_ID": MODEL,
            "OPENCODE_CONFIG": "/custom/config.json",
            "BEDROCK_INFERENCE_REGION": "us-west-2",
            "BEDROCK_ENDPOINT_TYPE": "runtime",
        },
        b"AWS_REGION=us-west-2\0BEDROCK_MODEL_ID=other\0",
    )
    assert env["AWS_REGION"] == "us-east-1"
    assert env["OPENCODE_CONFIG"] == "/custom/config.json"
    assert env["BEDROCK_INFERENCE_REGION"] == "us-west-2"


def test_automatic_model_routing_preserves_native_configuration():
    original = (
        '{"provider":{"amazon-bedrock":{"models":{"custom":{"provider":{"npm":"custom-sdk"}}}}}}'
    )
    env = launcher.launch_environment(
        {"AWS_REGION": "eu-west-1", "BEDROCK_MODEL_ID": MODEL},
        ("OPENCODE_CONFIG_CONTENT=" + original + "\0").encode(),
    )
    assert env["OPENCODE_CONFIG_CONTENT"] == original
    assert "BEDROCK_ENDPOINT_TYPE" not in env


@pytest.mark.parametrize(
    "endpoint_type,npm",
    [
        ("runtime", "@ai-sdk/amazon-bedrock"),
        ("mantle", "@ai-sdk/amazon-bedrock/mantle"),
    ],
)
def test_endpoint_selection_retains_other_native_configuration(endpoint_type, npm):
    original = {
        "permission": {"edit": "ask"},
        "provider": {
            "amazon-bedrock": {
                "options": {"region": "us-east-2"},
                "models": {MODEL: {"name": "Custom model", "provider": {"npm": "old-provider"}}},
            }
        },
    }
    settings = ("OPENCODE_CONFIG_CONTENT=" + json.dumps(original) + "\0").encode()
    env = launcher.launch_environment(
        {
            "AWS_REGION": "eu-west-1",
            "BEDROCK_MODEL_ID": MODEL,
            "BEDROCK_ENDPOINT_TYPE": endpoint_type,
        },
        settings,
    )
    expected = json.loads(json.dumps(original))
    expected["provider"]["amazon-bedrock"]["models"][MODEL]["provider"]["npm"] = npm
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"]) == expected
    current = {**env, "OPENCODE_CONFIG_CONTENT": '{"model":"user-choice"}'}
    resolved = json.loads(launcher.launch_environment(current, settings)["OPENCODE_CONFIG_CONTENT"])
    assert resolved["model"] == "user-choice"
    assert "permission" not in resolved
    assert resolved["provider"]["amazon-bedrock"]["models"][MODEL]["provider"]["npm"] == npm
    assert current["OPENCODE_CONFIG_CONTENT"] == '{"model":"user-choice"}'


@pytest.mark.parametrize(
    "config",
    ["not-json", "[]", '{"provider":null}', '{"provider":{"amazon-bedrock":{"models":[]}}}'],
)
def test_invalid_native_configuration_fails_before_launch(config):
    with pytest.raises(ValueError, match="OPENCODE_CONFIG_CONTENT"):
        launcher.launch_environment(
            {
                "AWS_REGION": "eu-west-1",
                "BEDROCK_MODEL_ID": MODEL,
                "BEDROCK_ENDPOINT_TYPE": "runtime",
                "OPENCODE_CONFIG_CONTENT": config,
            },
            b"",
        )


def test_missing_runtime_settings_fail_before_launch():
    with pytest.raises(ValueError, match="AWS_REGION and BEDROCK_MODEL_ID"):
        launcher.launch_environment({}, b"")


def test_launch_forwards_session_argv_and_preserves_user_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTCORE_TOOL_ROOT", str(tmp_path / "runtime"))
    config = tmp_path / "opencode.json"
    original = '{"mcp": {}, "permission": {"edit": "ask"}}'
    config.write_text(original)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENCODE_CONFIG", str(config))
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODEL)
    monkeypatch.setenv("BEDROCK_ENDPOINT_TYPE", "runtime")
    monkeypatch.delenv("AGENTCORE_WORKDIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py", "--session", "saved-conversation"])
    chdir, execute = Mock(), Mock()
    monkeypatch.setattr(runtime.os, "chdir", chdir)
    monkeypatch.setattr(runtime.os, "execvpe", execute)
    launcher.main()
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
            assert "AgentCore Shell" in json.load(response)["message"]
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
        (COMMON / file).is_file()
        for file in (
            "Dockerfile",
            "run.sh",
            "runtime.py",
            "healthcheck.py",
            "activity.py",
        )
    )
    assert all(
        (IMAGE_CONTEXT / file).is_file()
        for file in (
            "run.py",
            "activity.mjs",
            "activity-plugin.mjs",
            "build.py",
        )
    )


@pytest.mark.skipif(not os.environ.get("HERDR_RUNTIME_TEST_IMAGE"), reason="Opt-in Docker test")
@pytest.mark.parametrize("inference_region", ["us-west-2", "us-east-2"])
@pytest.mark.parametrize(
    "endpoint_type,npm,model",
    [
        ("runtime", "@ai-sdk/amazon-bedrock", MODEL),
        ("mantle", "@ai-sdk/amazon-bedrock/mantle", "openai.gpt-5.5"),
    ],
)
def test_built_image_resolves_opencode_configuration_without_credentials(
    inference_region, endpoint_type, npm, model
):
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
            f"BEDROCK_INFERENCE_REGION={inference_region}",
            "-e",
            f"BEDROCK_MODEL_ID={model}",
            "-e",
            f"BEDROCK_ENDPOINT_TYPE={endpoint_type}",
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
    assert config["model"] == "amazon-bedrock/" + model
    assert config["provider"]["amazon-bedrock"]["options"]["region"] == inference_region
    assert config["provider"]["amazon-bedrock"]["models"][model]["provider"]["npm"] == npm
    assert "file:///app/activity-plugin.mjs" in config["plugin"]


@pytest.mark.skipif(not os.environ.get("HERDR_RUNTIME_TEST_IMAGE"), reason="Opt-in Docker test")
def test_real_opencode_drives_runtime_health():
    script = Path(__file__).with_name("runtime_activity_smoke.py").resolve()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--mount",
            f"type=bind,source={script},target=/tmp/activity-smoke.py,readonly",
            "-e",
            "AWS_REGION=us-west-2",
            "-e",
            f"BEDROCK_MODEL_ID={MODEL}",
            "-e",
            "OPENCODE_DISABLE_MODELS_FETCH=1",
            "-e",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS=1",
            os.environ["HERDR_RUNTIME_TEST_IMAGE"],
            "/usr/local/bin/python3",
            "/tmp/activity-smoke.py",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not os.environ.get("HERDR_RUNTIME_TEST_IMAGE"), reason="Opt-in Docker test")
@pytest.mark.parametrize(
    "name", ["opencode-agentcore-profile-2", "opencode-s3filesystem-agentcore-profile-3", "mantle"]
)
def test_project_model_is_registered_in_pinned_opencode(name):
    if name == "mantle":
        profile = {
            "region": "us-east-2",
            "inference": {"bedrock-endpoint-type": "mantle", "modelId": "openai.gpt-5.5"},
        }
    else:
        profile_path = Path(__file__).resolve().parents[1] / "provision_profiles" / f"{name}.json"
        profile = json.loads(profile_path.read_text())
    env = {
        "AWS_REGION": profile["region"],
        "BEDROCK_INFERENCE_REGION": profile["inference"].get("region", profile["region"]),
        "BEDROCK_MODEL_ID": profile["inference"]["modelId"],
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    if "bedrock-endpoint-type" in profile["inference"]:
        env["BEDROCK_ENDPOINT_TYPE"] = profile["inference"]["bedrock-endpoint-type"]
    command = ["docker", "run", "--rm", "--network", "none"]
    for key, value in env.items():
        command.extend(["-e", f"{key}={value}"])
    command.extend(
        [
            os.environ["HERDR_RUNTIME_TEST_IMAGE"],
            "/app/run.sh",
            "models",
            "amazon-bedrock",
            "--verbose",
        ]
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    header = "amazon-bedrock/" + profile["inference"]["modelId"] + "\n"
    assert header in result.stdout
    model, _ = json.JSONDecoder().raw_decode(result.stdout.split(header, 1)[1].lstrip())
    if name == "mantle":
        assert model["api"]["npm"] == "@ai-sdk/amazon-bedrock/mantle"
    else:
        assert model["api"]["npm"] == "@ai-sdk/amazon-bedrock"
        assert model["limit"] == {"context": 1000000, "output": 8192}
        # The same native catalog must retain both routes without a startup override.
        for model_id, sdk in (
            ("global.openai.gpt-6-astra", "@ai-sdk/amazon-bedrock"),
            ("openai.gpt-oss-20b", "@ai-sdk/amazon-bedrock/mantle"),
        ):
            header = "amazon-bedrock/" + model_id + "\n"
            entry, _ = json.JSONDecoder().raw_decode(result.stdout.split(header, 1)[1].lstrip())
            assert entry["api"]["npm"] == sdk
