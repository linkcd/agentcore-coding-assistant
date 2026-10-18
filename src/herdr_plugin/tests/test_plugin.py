"""Public Herdr plugin contracts and CLI workflows."""

import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import ARN
from herdr_agentcore import __version__, herdr
from herdr_agentcore.cli import main, parser, stop_connection
from herdr_agentcore.storage import UserError

ROOT = Path(__file__).resolve().parents[3]


def test_manifest_entrypoints_and_package_versions_match():
    manifest = tomllib.loads((ROOT / "herdr-plugin.toml").read_text())
    package = tomllib.loads((ROOT / "src/herdr_plugin/pyproject.toml").read_text())
    assert manifest["id"] == herdr.PLUGIN_ID
    assert manifest["version"] == package["project"]["version"] == __version__
    assert manifest["platforms"] == ["linux", "macos"]
    actions = {a["id"] for a in manifest["actions"]}
    assert actions == {p["id"] for p in manifest["panes"]}
    assert actions == {"new", "attach", "setup", "sessions", "stop"}
    for entry in [*manifest["actions"], *manifest["panes"]]:
        assert entry["command"][:3] == ["./.venv/bin/python", "-m", "herdr_agentcore"]
        parser().parse_args(entry["command"][3:])
    assert manifest["build"][0]["command"] == ["uv", "sync", "--frozen", "--no-dev"]


def test_action_uses_explicit_context_and_public_plugin_pane_api(monkeypatch):
    monkeypatch.delenv(herdr.PROFILE_ENV, raising=False)
    monkeypatch.setenv("HERDR_PLUGIN_CONTEXT_JSON", json.dumps({"focused_pane_id": "w9:p8"}))
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_BIN_PATH", "/test/herdr")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, '{"id":"cli:plugin","result":{}}', "")

    monkeypatch.setattr(subprocess, "run", run)
    herdr.open_action("new")
    assert calls == [
        [
            "/test/herdr",
            "plugin",
            "pane",
            "open",
            "--plugin",
            "agentcore",
            "--entrypoint",
            "new",
            "--placement",
            "split",
            "--target-pane",
            "w9:p8",
            "--direction",
            "right",
        ]
    ]


def test_action_without_context_never_targets_an_unrelated_focused_pane(monkeypatch):
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)
    monkeypatch.setenv("HERDR_PLUGIN_CONTEXT_JSON", "{}")
    with pytest.raises(UserError, match="workspace"):
        herdr.open_action("attach")


def test_quiet_herdr_commands_use_exit_status_not_json(monkeypatch):
    monkeypatch.setenv("HERDR_ENV", "1")

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert herdr.command("pane", "report-metadata", expect_json=False) == {}
    with pytest.raises(UserError, match="invalid JSON"):
        herdr.command("plugin", "pane", "open")


def test_quiet_herdr_command_errors_are_not_accepted(monkeypatch):
    monkeypatch.setenv("HERDR_ENV", "1")

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "pane_not_found")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(UserError, match="pane_not_found"):
        herdr.command("pane", "report-metadata", expect_json=False)


def test_import_sample_configuration_does_not_copy_secrets(tmp_path):
    imported = tmp_path / "runtime.json"
    imported.write_text(json.dumps({"runtime_arn": ARN, "other": "must-not-be-imported"}))
    config = tmp_path / "config"
    assert (
        main(
            [
                "configure",
                "--runtime-config",
                str(imported),
                "--config-dir",
                str(config),
                "--command",
                "/custom/launcher",
            ]
        )
        == 0
    )
    saved = (config / "config.json").read_text()
    assert "must-not-be-imported" not in saved
    assert ARN in saved
    assert json.loads(saved)["profiles"]["default"]["agent_kind"] is None


def test_stop_requires_confirmation_and_never_calls_aws_without_it(monkeypatch, record):
    def fail(*args):
        pytest.fail("Unconfirmed stop called AWS")

    monkeypatch.setattr("herdr_agentcore.cli.stop_connection", fail)
    assert main(["stop", record["id"]]) == 1


def test_stop_uses_recorded_identity_and_preserves_state_on_failure(monkeypatch, store, record):
    from herdr_agentcore.agentcore import AgentCoreError

    calls = []

    def fail(self, value):
        calls.append(value)
        raise AgentCoreError("NoCredentialsError")

    monkeypatch.setattr("herdr_agentcore.connector.AgentCoreTransport.stop", fail)
    with pytest.raises(UserError, match="no local status"):
        stop_connection(store, record["id"])
    assert calls[0]["runtime_session_id"] == record["runtime_session_id"]
    assert store.load(record["id"])["status"] == "created"
