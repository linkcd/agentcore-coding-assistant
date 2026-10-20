"""Both images expose usable non-root tools, including inside Codex's sandbox."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("image_variable", ["HERDR_RUNTIME_TEST_IMAGE", "CODEX_RUNTIME_TEST_IMAGE"])
def test_image_tools_and_native_extensions(image_variable):
    image = os.environ.get(image_variable)
    if not image:
        pytest.skip(f"Set {image_variable} for the toolchain test")
    script = Path(__file__).with_name("runtime_tools_smoke.py").read_text()
    # Reproduce a remote shell with a reduced PATH, then apply the actual launcher helper.
    wrapper = """
import os,sys,subprocess,tempfile
sys.path.insert(0,'/app')
from runtime import tool_environment,prepare_tool_directories
env=tool_environment({**os.environ,'PATH':'/usr/bin:/bin'})
prepare_tool_directories(env)
command=['/usr/local/bin/python3','-c',sys.argv[1]]
with tempfile.TemporaryDirectory(dir='/home/agent') as work:
    if sys.argv[2]=='codex':
        command=['codex','sandbox','-P','agentcore-workspace','-C',work,'--',*command]
    raise SystemExit(subprocess.run(command,env=env,cwd=work).returncode)
"""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            # Docker's default seccomp blocks the user namespaces used by Codex.
            # This test still runs Codex's own sandbox as UID 1000, without host mounts.
            *(
                ["--security-opt", "seccomp=unconfined"]
                if image_variable == "CODEX_RUNTIME_TEST_IMAGE"
                else []
            ),
            image,
            "/usr/local/bin/python3",
            "-c",
            wrapper,
            script,
            "codex" if image_variable == "CODEX_RUNTIME_TEST_IMAGE" else "opencode",
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"native_builds": "passed"' in result.stdout


@pytest.mark.parametrize("image_variable", ["HERDR_RUNTIME_TEST_IMAGE", "CODEX_RUNTIME_TEST_IMAGE"])
def test_mcp_starts_with_empty_caches_in_both_images(image_variable):
    image = os.environ.get(image_variable)
    if not image:
        pytest.skip(f"Set {image_variable} for MCP bootstrap verification")
    script = Path(__file__).with_name("runtime_mcp_smoke.py").read_text()
    native = "codex" if image_variable == "CODEX_RUNTIME_TEST_IMAGE" else "opencode"
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            *(["--security-opt", "seccomp=unconfined"] if native == "codex" else []),
            "-e",
            "AWS_REGION=us-west-2",
            "-e",
            "BEDROCK_MODEL_ID=example.model",
            "-e",
            "UV_OFFLINE=1",
            image,
            "/usr/local/bin/python3",
            "-c",
            script,
            "--project",
            "/home/agent/mcp-probe",
            "--native",
            native,
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "actual MCP calls" in result.stdout
