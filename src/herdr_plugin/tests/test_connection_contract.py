"""Descriptor import and runtime-specific hints without runtime implementation imports."""

import json
from unittest.mock import Mock

import pytest
from agentcore_contract import ConnectionSpec, UserError, encode_descriptor
from conftest import ARN
from herdr_agentcore.cli import exec_attach, main, setup_menu
from herdr_agentcore.storage import Profile


def test_import_preserves_runtime_command_but_selects_host_credentials_locally(tmp_path, store):
    descriptor = tmp_path / "published.json"
    descriptor.write_text(
        json.dumps(
            encode_descriptor(
                ConnectionSpec.from_dict(
                    {
                        "runtime_arn": ARN,
                        "command": ["/opt/assistant", "--project", "a b"],
                        "endpoint": "RELEASE",
                        "agent_kind": "example-agent",
                    }
                )
            )
        )
    )
    assert (
        main(
            [
                "configure",
                "--connection-file",
                str(descriptor),
                "--profile",
                "imported",
                "--config-dir",
                str(store.paths.config),
                "--aws-profile",
                "host-role",
            ]
        )
        == 0
    )
    profile = store.profiles()["imported"]
    assert profile.command == ["/opt/assistant", "--project", "a b"]
    assert profile.endpoint == "RELEASE"
    assert profile.agent_kind == "example-agent"
    assert profile.aws_profile == "host-role"
    assert store.resolve_profile() == "default"


def test_invalid_descriptor_does_not_replace_existing_profile(tmp_path, store):
    descriptor = tmp_path / "bad.json"
    descriptor.write_text(json.dumps({"version": 2}))
    path = store.paths.config / "config.json"
    before = path.read_bytes()
    assert (
        main(
            [
                "configure",
                "--connection-file",
                str(descriptor),
                "--replace",
                "--config-dir",
                str(store.paths.config),
            ]
        )
        == 1
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", [None, "opencode", "example-agent"])
def test_attach_hint_comes_from_saved_profile_and_clears_inherited_hint(monkeypatch, store, kind):
    store.save_profile(
        "selected",
        Profile.from_dict({"runtime_arn": ARN, "command": ["/bin/sh"], "agent_kind": kind}),
    )
    record = store.create("selected")
    monkeypatch.setenv("HERDR_AGENT", "unrelated-agent")
    execute = Mock()
    monkeypatch.setattr("herdr_agentcore.cli.os.execve", execute)
    exec_attach(store, record["id"])
    _, argv, env = execute.call_args.args
    assert argv[2:4] == ["herdr_agentcore", "attach"]
    assert record["id"] in argv
    assert env.get("HERDR_AGENT") == kind


def test_profile_and_arn_registration_do_not_infer_agent_kind(store):
    assert Profile.from_dict({"runtime_arn": ARN, "command": ["opencode"]}).agent_kind is None
    assert (
        main(
            [
                "configure",
                "--runtime-arn",
                ARN,
                "--profile",
                "new",
                "--config-dir",
                str(store.paths.config),
                "--command",
                "opencode",
            ]
        )
        == 0
    )
    assert store.profiles()["new"].agent_kind is None


def test_new_reexec_attaches_the_same_record_with_the_selected_hint(monkeypatch, store):
    from herdr_agentcore import cli

    store.save_profile(
        "selected",
        Profile.from_dict(
            {"runtime_arn": ARN, "command": ["/opt/assistant"], "agent_kind": "example"}
        ),
    )
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_AGENT", "unrelated")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    execute = Mock()
    monkeypatch.setattr(cli.os, "execve", execute)
    assert (
        main(
            [
                "new",
                "--profile",
                "selected",
                "--reconnect-seconds",
                "17",
                "--config-dir",
                str(store.paths.config),
                "--state-dir",
                str(store.paths.state),
            ]
        )
        == 0
    )
    _, argv, env = execute.call_args.args
    identifier = store.connections()[0]["id"]
    assert argv[3:5] == ["attach", identifier]
    assert env["HERDR_AGENT"] == "example"
    monkeypatch.setenv("HERDR_AGENT", "example")
    connected = []

    async def connect(store, identifier, reconnect_seconds):
        assert reconnect_seconds == 17
        connected.append(identifier)
        return 0

    monkeypatch.setattr(cli, "connect", connect)
    assert main(argv[3:]) == 0
    assert connected == [identifier]
    assert len(store.connections()) == 1


def test_missing_command_does_not_replace_profile_or_infer_from_agent_kind(store):
    path = store.paths.config / "config.json"
    before = path.read_bytes()
    assert (
        main(
            [
                "configure",
                "--runtime-arn",
                ARN,
                "--agent-kind",
                "opencode",
                "--replace",
                "--config-dir",
                str(store.paths.config),
            ]
        )
        == 1
    )
    assert path.read_bytes() == before


def test_setup_requires_explicit_command_even_for_opencode(monkeypatch, store):
    responses = iter(["new", ARN, "", "", "opencode", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    with pytest.raises(UserError, match="explicit launch argv"):
        setup_menu(store)
    assert "new" not in store.profiles()


def test_connector_command_override_is_saved_in_the_session_snapshot(tmp_path, store):
    import shlex

    from herdr_agentcore.connector import launch_command

    descriptor = tmp_path / "source.json"
    descriptor.write_text(
        json.dumps(
            encode_descriptor(
                ConnectionSpec.from_dict(
                    {
                        "runtime_arn": ARN,
                        "command": ["/original/launcher"],
                        "agent_kind": "opencode",
                    }
                )
            )
        )
    )
    argv = ["/custom/launcher", "--project", "space and ; punctuation"]
    assert (
        main(
            [
                "configure",
                "--connection-file",
                str(descriptor),
                "--profile",
                "custom",
                "--config-dir",
                str(store.paths.config),
                "--command",
                *argv,
            ]
        )
        == 0
    )
    record = store.create_record("custom")
    assert record.profile.command == argv
    assert shlex.split(launch_command(record.profile))[4:] == argv


def test_import_standard_cdk_outputs(tmp_path, store):
    path = tmp_path / "cdk-outputs.json"
    spec = ConnectionSpec.from_dict(
        {"runtime_arn": ARN, "command": ["/declared/start"], "agent_kind": "example"}
    )
    path.write_text(
        json.dumps({"RuntimeStack": {"ConnectionDescriptor": json.dumps(encode_descriptor(spec))}})
    )
    assert (
        main(
            [
                "configure",
                "--cdk-outputs",
                str(path),
                "--stack",
                "RuntimeStack",
                "--profile",
                "cdk",
                "--config-dir",
                str(store.paths.config),
            ]
        )
        == 0
    )
    assert store.profiles()["cdk"].command == ["/declared/start"]
    assert store.profiles()["cdk"].agent_kind == "example"
