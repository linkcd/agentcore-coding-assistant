"""Busy reporting, waiting-for-input semantics, and stale-process protection."""

import json
import shutil
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agentcore_runtime.common import healthcheck
from agentcore_runtime.common.activity import LEASE_SECONDS, health_status


@pytest.fixture
def activity(tmp_path):
    directory, proc = tmp_path / "activity", tmp_path / "proc"
    directory.mkdir()

    def write(*, pid=42, start="123", state="S", updated=100, **changes):
        process = proc / str(pid)
        process.mkdir(parents=True, exist_ok=True)
        # The command name may contain spaces and parentheses.
        fields = [state, *(["0"] * 18), start]
        (process / "stat").write_text(f"{pid} (opencode (worker)) " + " ".join(fields))
        record = {
            "version": 1,
            "pid": pid,
            "process_start": start,
            "busy": True,
            "updated_at": updated,
            **changes,
        }
        path = directory / f"{pid}.json"
        path.write_text(json.dumps(record))
        return path

    return directory, proc, write


def test_only_live_fresh_work_reports_busy(activity):
    directory, proc, write = activity
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"
    path = write()
    assert health_status(directory, now=100, proc_root=proc) == "HealthyBusy"
    assert health_status(directory, now=100 + LEASE_SECONDS + 1, proc_root=proc) == "Healthy"
    path.unlink()
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"


@pytest.mark.parametrize("state", ["T", "t", "Z", "X", "x"])
def test_suspended_or_dead_processes_are_not_busy(activity, state):
    directory, proc, write = activity
    write(state=state)
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"


def test_pid_reuse_and_process_exit_invalidate_even_a_fresh_lease(activity):
    directory, proc, write = activity
    write(process_start="old-process")
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"
    write(process_start="122")
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"
    write()
    (proc / "42" / "stat").unlink()
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"


@pytest.mark.parametrize(
    "changes",
    [
        {"updated_at": 101},
        {"updated_at": float("nan")},
        {"updated_at": "100"},
        {"updated_at": True},
        {"pid": -1},
        {"pid": "42"},
        {"pid": True},
        {"busy": False},
        {"busy": "true"},
        {"version": 2},
    ],
)
def test_invalid_lease_cannot_hold_runtime_busy(activity, changes):
    directory, proc, write = activity
    path = write()
    record = json.loads(path.read_text())
    path.write_text(json.dumps({**record, **changes}))
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"


def test_broken_or_oversized_files_do_not_hide_other_active_agents(activity):
    directory, proc, write = activity
    (directory / "broken.json").write_text("{")
    (directory / "huge.json").write_text(" " * 5000)
    write(pid=43, busy=False)
    assert health_status(directory, now=100, proc_root=proc) == "Healthy"
    write(pid=42)
    assert health_status(directory, now=100, proc_root=proc) == "HealthyBusy"


def test_ping_transitions_without_fabricated_last_activity_timestamps(activity, monkeypatch):
    directory, proc, write = activity
    monkeypatch.setattr(healthcheck.Handler, "activity_directory", directory)
    monkeypatch.setattr(
        healthcheck, "health_status", lambda path: health_status(path, now=100, proc_root=proc)
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), healthcheck.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def ping():
        url = f"http://127.0.0.1:{server.server_port}/ping"
        with urllib.request.urlopen(url, timeout=5) as reply:
            return json.load(reply)

    try:
        assert ping() == {"status": "Healthy"}
        path = write()
        assert ping() == {"status": "HealthyBusy"}
        assert ping() == {"status": "HealthyBusy"}
        path.unlink()
        assert ping() == {"status": "Healthy"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required for plugin unit tests")
def test_activity_plugin_node_suite():
    subprocess.run(
        ["node", "--test", str(Path(__file__).with_name("test_activity_plugin.mjs"))],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
