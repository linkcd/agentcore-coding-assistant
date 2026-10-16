"""Optional validation by the installed Herdr parser in an isolated registry."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def test_real_herdr_accepts_manifest_in_isolated_registry(tmp_path):
    binary = os.environ.get("HERDR_TEST_BINARY")
    if not binary:
        pytest.skip("Set HERDR_TEST_BINARY to validate using an installed Herdr binary.")
    # Never inherit the caller's session/socket or mutate the normal user registry.
    env = {key: value for key, value in os.environ.items() if not key.startswith("HERDR_")}
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    root = Path(__file__).resolve().parents[2]

    def run(*args):
        result = subprocess.run(
            [binary, "plugin", *args], env=env, text=True, capture_output=True, timeout=15
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    # macOS Unix sockets have a short path limit; pytest's descriptive temp paths
    # exceed it. Use separate short-lived socket paths, also isolated from the user.
    with tempfile.TemporaryDirectory(prefix="h-") as sockets:
        env["HERDR_SOCKET_PATH"] = str(Path(sockets) / "a.sock")
        env["HERDR_CLIENT_SOCKET_PATH"] = str(Path(sockets) / "c.sock")
        run("link", str(root), "--disabled")
        listing = json.loads(run("list", "--plugin", "agentcore", "--json"))
        assert "agentcore" in json.dumps(listing)
        directory = run("config-dir", "agentcore").strip()
        assert Path(directory).is_relative_to(tmp_path)
        # No server is started. All registry files belong to the pytest fixture;
        # unlink is a server API in Herdr 0.9.5, so fixture cleanup removes them.
