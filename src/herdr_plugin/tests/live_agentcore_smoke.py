"""Opt-in live shell probe. Creates and stops only its own new runtime session.

Run explicitly, never through the default offline pytest suite:
    uv run python src/herdr_plugin/tests/live_agentcore_smoke.py --runtime-arn <runtime-arn>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shlex
import tempfile
import uuid
from pathlib import Path

from bedrock_agentcore.runtime.shell import ShellChannel
from herdr_agentcore.connector import AgentCoreTransport, Connector
from herdr_agentcore.storage import Paths, Profile, Store, UserError
from websockets.exceptions import InvalidStatus


class ProbeTerminal:
    """Keep probe output in memory; never persist a terminal transcript."""

    def __init__(self):
        self.output = bytearray()

    async def write(self, data: bytes):
        self.output.extend(data)


async def read_until(ws, framer, marker: str) -> str:
    output = bytearray()
    pattern = re.compile(rf"(?:^|\n){re.escape(marker)}\r?(?:\n|$)")
    async with asyncio.timeout(45):
        while True:
            raw = await ws.recv()
            if not isinstance(raw, bytes) or not raw:
                continue
            frame = framer.decode(raw)
            if frame.channel in {ShellChannel.STDOUT, ShellChannel.STDERR}:
                output.extend(frame.payload)
                if len(output) > 1024 * 1024:
                    raise UserError("Probe output exceeded its memory limit.")
                text = output.decode(errors="replace")
                if pattern.search(text):
                    return text
            elif frame.channel == ShellChannel.STATUS:
                raise UserError("Remote shell exited before completing the probe.")
            elif frame.channel == ShellChannel.CLOSE:
                raise UserError("Remote shell was terminated during the probe.")


def field(output: str, key: str) -> str:
    matches = re.findall(rf"(?:^|\n){re.escape(key)}=([^\r\n]+)", output)
    if not matches:
        raise UserError(f"Missing probe result: {key}")
    # Reattach replays buffered history, including earlier probe results. Use
    # the final value preceding this invocation's unique completion marker.
    return matches[-1]


async def run(runtime_arn: str, aws_profile: str | None):
    profile = Profile.from_dict(
        {"runtime_arn": runtime_arn, "command": ["/bin/sh"], "aws_profile": aws_profile}
    )
    with tempfile.TemporaryDirectory(prefix="agentcore-smoke-") as directory:
        store = Store(Paths(Path(directory) / "config", Path(directory) / "state"))
        store.save_profile("live-test", profile)
        record = store.create("live-test", "herdr-live-probe")
        transport = AgentCoreTransport(profile)
        connector = Connector(store, record, transport, ProbeTerminal())
        ws = None
        nonce = uuid.uuid4().hex
        print(f"Fresh test runtime session: {record['runtime_session_id']}", flush=True)
        try:
            ws = await transport.connect(record)
            print("WebSocket authenticated", flush=True)
            reconnected = await asyncio.wait_for(connector._confirmation(ws), 45)
            print(f"Shell confirmation: reconnected={reconnected}", flush=True)
            if reconnected:
                raise UserError("A fresh test shell unexpectedly reported reconnected=true.")
            await ws.send(connector.framer.encode_resize(88, 25))
            command = (
                "stty -echo; "
                f"export HERDR_SMOKE_NONCE={shlex.quote(nonce)}; "
                "printf '\\nPROBE_PID=%s\\n' \"$$\"; "
                "printf 'PROBE_SIZE=%s\\n' \"$(stty size)\"; "
                "printf 'PROBE_LAUNCHER=%s\\n' \"$(test -x /app/run.sh && printf yes)\"; "
                "printf 'PROBE_MOUNT=%s\\n' \"$(test -d /mnt/s3files && printf yes)\"; "
                "printf 'PROBE_OPENCODE=%s\\n' \"$(command -v opencode || true)\"; "
                "printf 'PROBE_VERSION=%s\\n' \"$(opencode --version 2>/dev/null)\"; "
                f"printf '\\nPROBE_DONE_{nonce}\\n'\n"
            )
            await ws.send(connector.framer.encode_stdin(command))
            output = await read_until(ws, connector.framer, f"PROBE_DONE_{nonce}")
            pid = field(output, "PROBE_PID")
            result = {
                key: field(output, key)
                for key in (
                    "PROBE_SIZE",
                    "PROBE_LAUNCHER",
                    "PROBE_MOUNT",
                    "PROBE_OPENCODE",
                    "PROBE_VERSION",
                )
            }
            if result["PROBE_SIZE"] != "25 88":
                raise UserError(f"Resize mismatch: {result['PROBE_SIZE']}")
            print(json.dumps(result), flush=True)
            await ws.close()
            ws = None
            print("Detached; reconnecting to the same runtime session and shell", flush=True)
            ws = await transport.connect(record)
            reconnected = await asyncio.wait_for(connector._confirmation(ws), 45)
            if not reconnected:
                raise UserError("The original shell did not survive detachment.")
            await ws.send(connector.framer.encode_resize(100, 35))
            await ws.send(
                connector.framer.encode_stdin(
                    "printf '\\nPROBE_PID=%s\\n' \"$$\"; "
                    "printf 'PROBE_NONCE=%s\\n' \"$HERDR_SMOKE_NONCE\"; "
                    "printf 'PROBE_SIZE=%s\\n' \"$(stty size)\"; "
                    f"printf '\\nPROBE_RESUMED_{nonce}\\n'\n"
                )
            )
            output = await read_until(ws, connector.framer, f"PROBE_RESUMED_{nonce}")
            if field(output, "PROBE_PID") != pid or field(output, "PROBE_NONCE") != nonce:
                raise UserError("Reattachment lost the shell process or environment.")
            if field(output, "PROBE_SIZE") != "35 100":
                raise UserError(f"Resize after reconnect: observed {field(output, 'PROBE_SIZE')!r}")
            print(
                "PASS: input/output, initial resize, same-PID reattach, environment, second resize",
                flush=True,
            )
        finally:
            try:
                if ws is not None:
                    await ws.close()
            finally:
                await asyncio.to_thread(transport.stop, record)
                print(f"Stopped own test session: {record['runtime_session_id']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--aws-profile")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.runtime_arn, args.aws_profile))
    except InvalidStatus as exc:
        # Do not print the signed request URL or headers.
        print(f"FAIL: AgentCore WebSocket HTTP {exc.response.status_code}", flush=True)
        raise SystemExit(1) from None
    except Exception as exc:
        message = str(exc) if isinstance(exc, UserError) else type(exc).__name__
        print(f"FAIL: {message}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
