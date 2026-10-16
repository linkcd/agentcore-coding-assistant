"""Aggregate live, fresh OpenCode work leases for AgentCore /ping.

No activity is inferred from an open shell or the mere existence of a process.
Lease heartbeats validate telemetry freshness, not AWS last-activity timestamps.
"""

import json
import math
import time
from pathlib import Path

ACTIVITY_DIRECTORY = Path("/tmp/herdr-agentcore-activity")
LEASE_SECONDS = 45
MAX_RECORD_BYTES = 4096


def live_process(pid: int, start: str, proc_root: Path) -> bool:
    fields = (proc_root / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
    return fields[0] not in {"T", "t", "Z", "X", "x"} and fields[19] == start


def health_status(
    directory: Path = ACTIVITY_DIRECTORY,
    *,
    now: float | None = None,
    proc_root: Path = Path("/proc"),
) -> str:
    now = time.time() if now is None else now
    for path in directory.glob("*.json"):
        try:
            if path.is_symlink():
                continue
            with path.open() as file:
                content = file.read(MAX_RECORD_BYTES + 1)
            if len(content) > MAX_RECORD_BYTES:
                continue
            record = json.loads(content)
            if not isinstance(record, dict) or record.get("version") != 1:
                continue
            if record.get("busy") is not True:
                continue
            pid, start, updated = record["pid"], record["process_start"], record["updated_at"]
            if (
                type(pid) is not int
                or pid <= 0
                or not isinstance(start, str)
                or not start.isdigit()
            ):
                continue
            if type(updated) not in (int, float) or not math.isfinite(updated):
                continue
            if not 0 <= now - updated <= LEASE_SECONDS:
                continue
            if live_process(pid, start, proc_root):
                return "HealthyBusy"
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            # Concurrent replacement/removal, malformed records, and exited
            # processes are not evidence of active work. Never renew stale files.
            continue
    return "Healthy"
