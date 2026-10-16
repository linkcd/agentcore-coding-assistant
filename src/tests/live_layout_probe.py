"""Opt-in OpenCode terminal-size/mouse probe through a real local PTY.

Creates its own fresh AgentCore session and stops it in cleanup. It never opens
or alters a pane in the user's Herdr server.
"""

import argparse
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

from herdr_agentcore.connector import AgentCoreTransport
from herdr_agentcore.storage import Paths, Profile, Store


def collect(fd, output, seconds, stop_at_ready=False):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        remaining = max(0, deadline - time.monotonic())
        readable, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not readable:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return
        if not chunk:
            return
        output.extend(chunk)
        if len(output) > 4 * 1024 * 1024:
            raise RuntimeError("Probe output limit exceeded")
        if b"Bun has crashed" in output:
            return
        if stop_at_ready and (b"Ask anything" in output or b"ctrl+p commands" in output):
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--cols", type=int, default=35)
    parser.add_argument("--rows", type=int, default=20)
    args = parser.parse_args()
    profile = Profile.from_dict({"runtime_arn": args.runtime_arn})
    transport = AgentCoreTransport(profile)
    with tempfile.TemporaryDirectory(prefix="opencode-layout-") as directory:
        root = Path(directory)
        store = Store(Paths(root / "config", root / "state"))
        store.save_profile("probe", profile)
        record = store.create("probe", "size-and-mouse-probe")
        master, slave = pty.openpty()
        termios.tcsetwinsize(slave, (args.rows, args.cols))
        env = {key: value for key, value in os.environ.items() if not key.startswith("HERDR_")}
        child = None
        output = bytearray()
        print(
            f"Probe {args.cols}x{args.rows}, fresh session {record['runtime_session_id']}",
            flush=True,
        )
        try:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "herdr_agentcore",
                    "attach",
                    record["id"],
                    "--config-dir",
                    str(store.paths.config),
                    "--state-dir",
                    str(store.paths.state),
                ],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                start_new_session=True,
            )
            os.close(slave)
            slave = None
            collect(master, output, 60, stop_at_ready=True)
            ready = b"Ask anything" in output or b"ctrl+p commands" in output
            collect(master, output, 3)
            before_mouse = b"Bun has crashed" in output
            print(json.dumps({"ready": ready, "crash_before_mouse": before_mouse}), flush=True)
            if ready and not before_mouse:
                # Valid SGR wheel reports within the supplied terminal dimensions.
                os.write(master, (b"\x1b[<64;10;10M" + b"\x1b[<65;10;10M") * 5)
                collect(master, output, 5)
            print(
                json.dumps(
                    {
                        "crash_after_probe": b"Bun has crashed" in output,
                        "literal_mouse_echo": b"^[[<" in output,
                    }
                ),
                flush=True,
            )
            if b"Bun has crashed" in output or not ready:
                text = output.decode(errors="replace")
                text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
                print(text[-4000:], flush=True)
        finally:
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGTERM)
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            os.close(master)
            if slave is not None:
                os.close(slave)
            transport.stop(record)
            print("Stopped probe session " + record["runtime_session_id"], flush=True)


if __name__ == "__main__":
    main()
