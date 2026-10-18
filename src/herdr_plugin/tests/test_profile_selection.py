"""Explicit profile defaults and controller overrides."""

import json
import sys
from dataclasses import asdict
from unittest.mock import Mock

import pytest
from conftest import ARN, PROFILE_DATA
from herdr_agentcore import cli, herdr
from herdr_agentcore.storage import Paths, Profile, Store, UserError, atomic_json


def test_first_profile_is_default_and_later_saves_do_not_change_it(tmp_path):
    store = Store(Paths(tmp_path / "config", tmp_path / "state"))
    profile = Profile.from_dict(PROFILE_DATA)
    store.save_profile("owned", profile)
    store.save_profile("other", profile)
    assert store.resolve_profile() == "owned"
    assert store.create()["profile_name"] == "owned"
    store.set_default("other")
    store.save_profile("owned", profile, replace=True)
    assert store.resolve_profile() == "other"


def test_default_changes_only_new_records(store, record):
    original = store.load(record["id"])
    store.save_profile("other", Profile.from_dict({"runtime_arn": ARN, "command": ["/other"]}))
    store.set_default("other")
    assert store.create()["profile"]["command"] == ["/other"]
    assert store.load(record["id"]) == original
    assert store.create("default")["profile"]["command"] == ["/app/run.sh"]


@pytest.mark.parametrize("names", [["only"], ["other", "default"], ["one", "two"]])
def test_config_without_default_requires_explicit_selection(tmp_path, names):
    store = Store(Paths(tmp_path / "config", tmp_path / "state"))
    atomic_json(
        store.paths.config / "config.json",
        {"version": 1, "profiles": {name: PROFILE_DATA for name in names}},
    )
    with pytest.raises(UserError, match="set-default"):
        store.create()
    assert store.connections() == []
    assert store.create(names[0])["profile_name"] == names[0]
    store.set_default(names[0])
    assert store.resolve_profile() == names[0]


def test_missing_saved_default_is_not_silently_replaced(store):
    path = store.paths.config / "config.json"
    data = json.loads(path.read_text())
    data["default_profile"] = "missing"
    atomic_json(path, data)
    with pytest.raises(UserError, match="Unknown runtime profile"):
        store.create()
    assert store.create("default")["profile_name"] == "default"
    store.set_default("default")
    assert store.resolve_profile() == "default"


@pytest.mark.parametrize("invalid", [None, 123, "bad profile"])
def test_malformed_default_is_not_overwritten(store, invalid):
    path = store.paths.config / "config.json"
    data = json.loads(path.read_text())
    data["default_profile"] = invalid
    atomic_json(path, data)
    before = path.read_bytes()
    with pytest.raises(UserError):
        store.save_profile("other", Profile.from_dict(PROFILE_DATA))
    assert path.read_bytes() == before


def test_set_default_cli_preserves_profiles_and_rejects_unknown_name(store):
    store.save_profile("other", Profile.from_dict(PROFILE_DATA))
    before = {name: asdict(profile) for name, profile in store.profiles().items()}
    args = ["--config-dir", str(store.paths.config), "--state-dir", str(store.paths.state)]
    assert cli.main(["set-default", "other", *args]) == 0
    assert store.resolve_profile() == "other"
    assert {name: asdict(profile) for name, profile in store.profiles().items()} == before
    assert cli.main(["set-default", "missing", *args]) == 1
    assert store.resolve_profile() == "other"


@pytest.mark.parametrize(
    "explicit,environment,expected",
    [
        (None, None, "default"),
        (None, "other", "other"),
        ("default", "other", "default"),
        ("other", None, "other"),
    ],
)
def test_new_entrypoint_never_prompts_and_honors_controller_precedence(
    monkeypatch, store, explicit, environment, expected
):
    store.save_profile("other", Profile.from_dict(PROFILE_DATA))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    if environment is None:
        monkeypatch.delenv(herdr.PROFILE_ENV, raising=False)
    else:
        monkeypatch.setenv(herdr.PROFILE_ENV, environment)
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("Unexpected picker")))
    attach = Mock()
    monkeypatch.setattr(cli, "exec_attach", attach)
    cli.menu(store, "new", explicit)
    records = store.connections()
    assert len(records) == 1
    assert records[0]["profile_name"] == expected
    attach.assert_called_once_with(store, records[0]["id"])


def test_bad_controller_override_does_not_fall_back_to_default(monkeypatch, store):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv(herdr.PROFILE_ENV, "missing")
    with pytest.raises(UserError, match="Unknown runtime profile"):
        cli.menu(store, "new")
    assert store.connections() == []


def test_direct_new_cli_uses_saved_default(monkeypatch, store):
    store.save_profile("other", Profile.from_dict(PROFILE_DATA))
    store.set_default("other")
    monkeypatch.delenv(herdr.PROFILE_ENV, raising=False)
    monkeypatch.setenv("HERDR_AGENT", "opencode")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    connected = []

    async def connect(store, identifier, reconnect_seconds):
        connected.append(store.load(identifier)["profile_name"])
        return 0

    monkeypatch.setattr(cli, "connect", connect)
    assert (
        cli.main(
            ["new", "--config-dir", str(store.paths.config), "--state-dir", str(store.paths.state)]
        )
        == 0
    )
    assert connected == ["other"]


@pytest.mark.parametrize("explicit,expected", [(None, "other"), ("chosen", "chosen")])
def test_action_forwards_profile_to_server_owned_pane(monkeypatch, explicit, expected):
    monkeypatch.setenv("HERDR_PLUGIN_CONTEXT_JSON", '{"focused_pane_id":"w9:p8"}')
    monkeypatch.setenv(herdr.PROFILE_ENV, "other")
    command = Mock(return_value={"result": {}})
    monkeypatch.setattr(herdr, "command", command)
    herdr.open_action("new", explicit)
    argv = command.call_args.args
    assert argv[argv.index("--target-pane") + 1] == "w9:p8"
    assert argv[argv.index("--env") + 1] == f"{herdr.PROFILE_ENV}={expected}"


def test_profile_override_is_not_accepted_for_attach(monkeypatch):
    command = Mock()
    monkeypatch.setattr(herdr, "command", command)
    with pytest.raises(UserError, match="only supported"):
        herdr.open_action("attach", "other")
    command.assert_not_called()
