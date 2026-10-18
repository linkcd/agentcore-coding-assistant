"""Record validation, crash-durable writes, and damaged-record isolation."""

import json
import os
import stat
import uuid
from unittest.mock import patch

import pytest
from herdr_agentcore.models import ConnectionRecord, ConnectionStatus, UserError
from herdr_agentcore.storage import atomic_json


@pytest.mark.parametrize("field", ["status", "created_at", "updated_at", "profile_name"])
def test_missing_record_fields_fail_at_storage_boundary(store, record, field):
    record.pop(field)
    with patch("herdr_agentcore.storage.read_json", return_value=record):
        with pytest.raises(UserError, match="missing required field"):
            store.load_record(record["id"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "invented"),
        ("launch_state", "started"),
        ("created_at", "yesterday"),
        ("updated_at", "2026-01-01T00:00:00"),
        ("exit_code", True),
        ("version", True),
    ],
)
def test_invalid_record_values_are_rejected(record, field, value):
    with pytest.raises(UserError):
        ConnectionRecord.from_dict({**record, field: value})


def test_v1_roundtrip_preserves_recovery_annotations(store, record):
    record["opencode_session_id"] = "saved-conversation"
    record["previous_shell_id"] = str(uuid.uuid4())
    typed = ConnectionRecord.from_dict(record)
    assert typed.to_dict() == record
    typed.transition(ConnectionStatus.DETACHED)
    store.save_record(typed)
    assert store.load(record["id"])["opencode_session_id"] == "saved-conversation"


def test_one_broken_record_does_not_hide_healthy_records(store, record):
    bad = store.paths.state / "connections" / f"{uuid.uuid4()}.json"
    bad.write_text("{incomplete")
    with pytest.warns(RuntimeWarning, match="Skipping invalid connection record"):
        records = store.connections()
    assert [item["id"] for item in records] == [record["id"]]
    assert bad.exists()  # Report damage; never silently delete a user's record.


def test_atomic_write_syncs_directory_after_replacement(tmp_path, monkeypatch):
    calls = []
    fsync, replace = os.fsync, os.replace

    def sync(fd):
        calls.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        fsync(fd)

    def rename(source, destination):
        calls.append("replace")
        replace(source, destination)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", rename)
    path = tmp_path / "record.json"
    atomic_json(path, {"version": 1})
    assert calls == ["file", "replace", "directory"]
    assert json.loads(path.read_text()) == {"version": 1}


def test_records_sort_by_instant_and_mapping_save_uses_persisted_timestamp(store, record):
    other = store.create()
    record["created_at"] = "2026-01-01T01:00:00+02:00"
    other["created_at"] = "2026-01-01T00:00:00+00:00"
    store.save(record)
    store.save(other)
    assert store.load(record["id"]) == record
    assert [item.id for item in store.connection_records()] == [other["id"], record["id"]]
