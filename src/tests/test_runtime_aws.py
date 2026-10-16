"""Runtime-role launch behavior without real AWS credentials or network access."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ARN

from herdr_agentcore.cli import main
from herdr_agentcore.runtime_aws import runtime_role_launcher
from herdr_agentcore.storage import Profile


def test_launcher_clears_snapshot_after_original_initialization(tmp_path):
    binary = tmp_path / "opencode"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "print(json.dumps({\n"
        "'static_keys': [k for k in ('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY',"
        "'AWS_SESSION_TOKEN','AWS_SECURITY_TOKEN') if k in os.environ],\n"
        "'profile': os.environ.get('AWS_PROFILE'),\n"
        "'initialized': os.environ.get('INITIALIZED'),\n"
        "'argv': sys.argv[1:],\n"
        "'shim': os.environ['PATH'].split(':')[0]}))\n"
    )
    binary.chmod(0o700)
    launcher = tmp_path / "launcher with spaces"
    launcher.write_text(
        "#!/bin/sh\n"
        "export AWS_ACCESS_KEY_ID=expired AWS_SECRET_ACCESS_KEY=expired\n"
        "export AWS_SESSION_TOKEN=expired AWS_SECURITY_TOKEN=expired\n"
        "export INITIALIZED=yes\n"
        'exec opencode "$@"\n'
    )
    launcher.chmod(0o700)
    arguments = ["one argument", "'; false; '", "$(false)"]
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    env.pop("HERDR_REAL_OPENCODE", None)
    result = subprocess.run(
        runtime_role_launcher([str(launcher), *arguments]),
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    data = json.loads(result.stdout)
    try:
        assert data["static_keys"] == []
        assert data["profile"] == "default"
        assert data["initialized"] == "yes"
        assert data["argv"] == arguments
    finally:
        shim = Path(data["shim"])
        assert shim.name.startswith("herdr-runtime-role.")
        shutil.rmtree(shim)


def test_runtime_role_command_is_valid_profile_data():
    command = runtime_role_launcher(["/app/run.sh"])
    assert all("\n" not in value for value in command)
    assert shlex.split(shlex.join(command)) == command
    assert Profile.from_dict({"runtime_arn": ARN, "command": command}).command == command


def test_configuration_flag_does_not_change_management_aws_profile(tmp_path):
    result = main(
        [
            "configure",
            "--runtime-arn",
            ARN,
            "--aws-profile",
            "management-profile",
            "--runtime-role-credentials",
            "--config-dir",
            str(tmp_path),
        ]
    )
    assert result == 0
    profile = json.loads((tmp_path / "config.json").read_text())["profiles"]["default"]
    assert profile["aws_profile"] == "management-profile"
    assert profile["command"] == runtime_role_launcher(["/app/run.sh"])


@pytest.mark.parametrize("command", [[], ["-invalid"], [""], ["line\nbreak"]])
def test_configuration_validates_command_before_wrapping(tmp_path, command):
    result = main(
        [
            "configure",
            "--runtime-arn",
            ARN,
            "--runtime-role-credentials",
            "--config-dir",
            str(tmp_path),
            "--command",
            *command,
        ]
    )
    assert result == 1
    assert not (tmp_path / "config.json").exists()
