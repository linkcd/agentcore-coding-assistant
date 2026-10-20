"""Locked MCP environments are local, replaceable, and clean on stdout."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agentcore_runtime.agent_images.common import mcp_run

UV = shutil.which("uv")
pytestmark = pytest.mark.skipif(not UV, reason="uv is required for locked bootstrap tests")


@pytest.fixture
def tool_project(tmp_path):
    project = tmp_path / "persistent/server"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname="bootstrap-test"\nversion="0.1.0"\nrequires-python=">=3.11"\n'
        "dependencies=[]\n[tool.uv]\npackage=false\n"
    )
    env = {**os.environ, "UV_CACHE_DIR": str(tmp_path / "lock-cache")}
    subprocess.run(
        [UV, "lock", "--offline", "--project", str(project), "--python", sys.executable],
        env=env,
        capture_output=True,
        check=True,
    )
    return project


def settings(tmp_path):
    return {
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ["PATH"],
        "AGENTCORE_TOOL_ROOT": str(tmp_path / "local"),
    }


def test_bootstrap_recreates_local_environment_without_changing_persistent_files(
    tool_project, tmp_path
):
    original = {path.name: path.read_bytes() for path in tool_project.iterdir()}
    first = mcp_run.bootstrap(tool_project, sys.executable, 30, settings(tmp_path))
    environment = Path(first["VIRTUAL_ENV"])
    assert environment.is_relative_to(tmp_path / "local")
    assert (environment / "bin/python").exists()
    assert first["UV_PYTHON_DOWNLOADS"] == "never"
    shutil.rmtree(tmp_path / "local")
    second = mcp_run.bootstrap(tool_project, sys.executable, 30, settings(tmp_path))
    assert second["VIRTUAL_ENV"] == first["VIRTUAL_ENV"]
    assert (environment / "bin/python").exists()
    assert {path.name: path.read_bytes() for path in tool_project.iterdir()} == original


def test_changed_definition_gets_a_separate_generation_and_stale_lock_fails(tool_project, tmp_path):
    first = mcp_run.bootstrap(tool_project, sys.executable, 30, settings(tmp_path))
    manifest = tool_project / "pyproject.toml"
    manifest.write_text(manifest.read_text().replace('version="0.1.0"', 'version="0.2.0"'))
    lock = (tool_project / "uv.lock").read_bytes()
    with pytest.raises(subprocess.CalledProcessError):
        mcp_run.bootstrap(tool_project, sys.executable, 30, settings(tmp_path))
    assert (tool_project / "uv.lock").read_bytes() == lock
    assert Path(first["VIRTUAL_ENV"], "bin/python").exists()


def test_missing_lock_or_interpreter_fails_before_install(tool_project, tmp_path):
    with pytest.raises(ValueError, match="must be installed"):
        mcp_run.bootstrap(tool_project, "nonexistent-python-for-test", 30, settings(tmp_path))
    (tool_project / "uv.lock").unlink()
    with pytest.raises(FileNotFoundError):
        mcp_run.bootstrap(tool_project, sys.executable, 30, settings(tmp_path))
    assert not (tmp_path / "local").exists()


def test_bootstrap_keeps_stdio_clean_and_preserves_command_arguments(tool_project, tmp_path):
    script = "import json,sys; print(json.dumps([sys.argv[1],sys.stdin.readline().strip()]))"
    result = subprocess.run(
        [
            sys.executable,
            mcp_run.__file__,
            "--project",
            str(tool_project),
            "--python",
            sys.executable,
            "--",
            "python",
            "-c",
            script,
            "a b;literal",
        ],
        env=settings(tmp_path),
        input="request\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["a b;literal", "request"]


def test_setup_failure_never_starts_the_server(tool_project, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            mcp_run.__file__,
            "--project",
            str(tool_project),
            "--python",
            "nonexistent-python-for-test",
            "--",
            "python",
            "-c",
            "print('started')",
        ],
        env=settings(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "MCP startup:" in result.stderr
