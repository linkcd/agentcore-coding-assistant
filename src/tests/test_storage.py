"""Profile validation, durable identities, and attachment locking."""

import json
import stat
from dataclasses import asdict

import pytest
from conftest import ARN

from herdr_agentcore.storage import Paths, Profile, Store, UserError, connection_id


def test_profile_is_snapshotted_and_each_environment_is_isolated(store):
    first = store.create("default")
    second = store.create("default")
    for key in ("id", "runtime_session_id", "shell_id"):
        assert first[key] != second[key]
    replacement = Profile.from_dict({"runtime_arn": ARN, "command": ["/other/launcher"]})
    store.save_profile("default", replacement, replace=True)
    assert store.load(first["id"])["profile"]["command"] == ["/app/run.sh"]
    assert store.create("default")["profile"]["command"] == ["/other/launcher"]


def test_atomic_records_private_and_complete(store, record):
    path = store.paths.state / "connections" / f"{record['id']}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["shell_id"] == record["shell_id"]
    record["status"] = "connected"
    store.save(record)
    assert store.load(record["id"])["status"] == "connected"
    assert not list(path.parent.glob(".*.json.*"))


def test_attachment_lock_prevents_competing_connectors(store, record):
    with store.lock(record["id"]):
        with pytest.raises(UserError, match="already in use"), store.lock(record["id"]):
            pytest.fail("Competing connector acquired the lock")
    with store.lock(record["id"]):
        assert store.load(record["id"])


@pytest.mark.parametrize("identifier", ["../../config", "", None, "bad-id"])
def test_invalid_ids_cannot_escape_storage(identifier):
    with pytest.raises(UserError):
        connection_id(identifier)


@pytest.mark.parametrize(
    "changes",
    [
        {"region": "us-east-1"},
        {"runtime_arn": None},
        {"runtime_arn": "https://example.com"},
        {"command": []},
        {"command": "opencode"},
        {"command": ["opencode", "\x1b[31m"]},
        {"command": ["-invalid"]},
        {"access_key": "do-not-store"},
    ],
)
def test_profile_validation(changes):
    with pytest.raises(UserError):
        Profile.from_dict({"runtime_arn": ARN, **changes})


def test_existing_profile_requires_explicit_replacement(store):
    with pytest.raises(UserError, match="--replace"):
        store.save_profile("default", store.profiles()["default"])


def test_version_and_corruption_are_not_silently_overwritten(store):
    path = store.paths.config / "config.json"
    path.write_text('{"version": 99, "profiles": {}}')
    with pytest.raises(UserError, match="version 1"):
        store.save_profile("other", Profile.from_dict({"runtime_arn": ARN}))
    assert json.loads(path.read_text())["version"] == 99


def test_plugin_paths_take_precedence_over_standalone_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(tmp_path / "plugin-config"))
    monkeypatch.setenv("HERDR_PLUGIN_STATE_DIR", str(tmp_path / "plugin-state"))
    paths = Paths.resolve()
    assert paths.config == tmp_path / "plugin-config"
    assert paths.state == tmp_path / "plugin-state"
    explicit = Paths.resolve(str(tmp_path / "explicit"))
    assert explicit.config == tmp_path / "explicit"


def test_roundtrip_has_only_nonsecret_profile_fields(store):
    assert set(asdict(store.profiles()["default"])) == {
        "runtime_arn",
        "region",
        "command",
        "endpoint",
        "aws_profile",
    }
    assert isinstance(Store(store.paths).profiles()["default"], Profile)
