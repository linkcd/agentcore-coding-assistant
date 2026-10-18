"""Offline regressions for live-test parsing and Herdr session isolation."""

import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from herdr_agentcore.storage import UserError
from live_agentcore_smoke import field
from live_herdr_smoke import (
    IsolatedHerdr,
    check_prompt_screen,
    check_runtime_role_environment,
    input_widget_ready,
)


def test_probe_uses_latest_result_after_shell_replay():
    replay_and_reply = "PROBE_SIZE=25 88\r\nold output\r\nPROBE_SIZE=35 100\r\n"
    assert field(replay_and_reply, "PROBE_SIZE") == "35 100"
    with pytest.raises(UserError, match="Missing probe result"):
        field(replay_and_reply, "PROBE_NONCE")


def test_live_server_does_not_inherit_callers_herdr_context(monkeypatch, tmp_path):
    monkeypatch.setattr("live_herdr_smoke.shutil.which", lambda name: "/test/herdr")
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/user/live.sock")
    monkeypatch.setenv("HERDR_CLIENT_SOCKET_PATH", "/user/client.sock")
    monkeypatch.setenv("HERDR_SESSION", "user-session")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p99")
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", "/user/plugin-config")
    isolated = IsolatedHerdr(tmp_path)
    assert isolated.env["HERDR_SOCKET_PATH"] == str(tmp_path / "a.sock")
    assert isolated.env["HERDR_CLIENT_SOCKET_PATH"] == str(tmp_path / "b.sock")
    assert isolated.env["HERDR_SESSION"].startswith("agentcore-smoke-")
    assert "HERDR_PANE_ID" not in isolated.env
    assert "HERDR_PLUGIN_CONFIG_DIR" not in isolated.env
    assert isolated.env["XDG_CONFIG_HOME"] == str(tmp_path / "c")
    assert isolated.server is None


@pytest.mark.parametrize("kind,shim", [("opencode", False), ("opencode", True), ("codex", False)])
def test_runtime_environment_probe_distinguishes_owned_and_legacy_launchers(
    monkeypatch, store, record, kind, shim
):
    client = Mock()
    session = Mock()
    session.client.return_value = client
    monkeypatch.setattr("boto3.Session", Mock(return_value=session))

    def respond(static=False, used_shim=shim):
        snapshot = {
            "has_static_credentials": static,
            "default_profile": kind == "opencode",
            "shim_used": used_shim,
        }
        client.invoke_agent_runtime_command.return_value = {
            "stream": [
                {"chunk": {"contentDelta": {"stdout": json.dumps([snapshot])}}},
                {"chunk": {"contentStop": {"exitCode": 0}}},
            ]
        }

    profile = replace(store.profiles()["default"], agent_kind=kind)
    respond()
    check_runtime_role_environment(profile, record, expect_shim=shim)
    respond(static=True)
    with pytest.raises(UserError, match="expected runtime-role environment"):
        check_runtime_role_environment(profile, record, expect_shim=shim)
    respond(used_shim=not shim)
    with pytest.raises(UserError, match="expected runtime-role environment"):
        check_runtime_role_environment(profile, record, expect_shim=shim)


@pytest.mark.parametrize(
    "message", ["Update Available", "Updating to v1.19.3", "Update available · 0.164"]
)
def test_probe_does_not_send_prompt_into_update_dialog(message):
    with pytest.raises(UserError, match="no prompt"):
        check_prompt_screen(f"{message}\nAsk anything…")
    check_prompt_screen("Ask anything…\nBuild · Claude Sonnet 4.5 Amazon Bedrock")


def test_probe_uses_separate_ready_screen_patterns():
    assert input_widget_ready("opencode", "Ask anything…")
    assert not input_widget_ready("codex", "Ask anything…")
    assert input_widget_ready("codex", "OpenAI Codex\n› ")
    assert not input_widget_ready("codex", "Connected to AgentCore")
    with pytest.raises(UserError):
        input_widget_ready("not-a-test-driver", "ready")
