"""Shell transport and session lifecycle behavior without AWS calls."""

import asyncio
import json
import shlex

import pytest
import websockets
from conftest import ARN
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from herdr_agentcore.connector import Connector, launch_command
from herdr_agentcore.storage import Profile, UserError


def confirmation(record, reconnected=False):
    return (
        b"\x03"
        + json.dumps(
            {
                "kind": "Status",
                "status": "Success",
                "metadata": {"shellId": record["shell_id"], "reconnected": reconnected},
            }
        ).encode()
    )


def termination(code=0):
    return (
        b"\x03"
        + json.dumps(
            {
                "metadata": {},
                "status": "Success" if code == 0 else "Failure",
                "details": {"causes": [{"reason": "ExitCode", "message": str(code)}]},
            }
        ).encode()
    )


class FakeTerminal:
    def __init__(self):
        self.detached = asyncio.Event()
        self.resized = asyncio.Event()
        self.inputs = asyncio.Queue()
        self.output = bytearray()
        self.enabled = False
        self.dimensions = (100, 30)
        self.notices = []

    def enable_input(self, value):
        self.enabled = value

    def size(self):
        return self.dimensions

    def write(self, value):
        self.output.extend(value)

    def notice(self, value):
        self.notices.append(value)

    async def read(self):
        return await self.inputs.get()


class FakeSocket:
    def __init__(self, *frames):
        self.incoming = asyncio.Queue()
        for frame in frames:
            self.incoming.put_nowait(frame)
        self.sent = []
        self.closed = False

    async def recv(self):
        value = await self.incoming.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, *sockets):
        self.sockets = list(sockets)
        self.calls = []

    async def connect(self, record):
        self.calls.append((record["runtime_session_id"], record["shell_id"]))
        value = self.sockets.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


async def until(predicate):
    async with asyncio.timeout(3):
        # Bounded observation of public state; avoid test-only production hooks.
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.001)


async def test_launch_once_render_bytes_and_preserve_exit_code(store, record):
    socket = FakeSocket(confirmation(record), b"\x01\x1b[32mhello\xe4\xb8\xad", termination(7))
    terminal = FakeTerminal()
    code = await Connector(store, record, FakeTransport(socket), terminal).run()
    assert code == 7
    assert terminal.output == b"\x1b[32mhello\xe4\xb8\xad"
    launch = [frame for frame in socket.sent if frame[0] == 0]
    assert len(launch) == 1 and b"exec env" in launch[0] and b"/app/run.sh" in launch[0]
    assert json.loads(socket.sent[0][1:]) == {"width": 100, "height": 30}
    assert store.load(record["id"])["exit_code"] == 7
    assert socket.closed


async def test_detach_keeps_handles_and_never_sends_shutdown_frame(store, record):
    socket = FakeSocket(confirmation(record))
    terminal = FakeTerminal()
    runner = asyncio.create_task(Connector(store, record, FakeTransport(socket), terminal).run())
    await until(lambda: terminal.enabled)
    terminal.detached.set()
    assert await runner == 0
    saved = store.load(record["id"])
    assert saved["status"] == "detached"
    assert saved["shell_id"] == record["shell_id"]
    assert not any(frame[0] == 255 for frame in socket.sent)
    assert socket.closed


@pytest.mark.parametrize("launch_state", ["sent", "attempted"])
async def test_reattach_never_relaunches_even_after_uncertain_send(store, record, launch_state):
    record["launch_state"] = launch_state
    socket = FakeSocket(confirmation(record, True), b"\x01still-running", termination())
    await Connector(store, record, FakeTransport(socket), FakeTerminal()).run()
    assert not any(frame[0] == 0 for frame in socket.sent)


async def test_expired_remote_pty_is_not_recreated_by_connector(store, record):
    record["launch_state"] = "sent"
    socket = FakeSocket(confirmation(record, False))
    with pytest.raises(UserError, match="No command was replayed"):
        await Connector(store, record, FakeTransport(socket), FakeTerminal()).run()
    assert store.load(record["id"])["status"] == "expired"
    assert socket.sent == []


async def test_network_reconnect_reuses_both_ids_and_does_not_relaunch(store, record):
    first = FakeSocket(confirmation(record), OSError("network down"))
    second = FakeSocket(confirmation(record, True), b"\x01replayed", termination())
    transport = FakeTransport(first, second)
    terminal = FakeTerminal()
    assert await Connector(store, record, transport, terminal, reconnect_seconds=5).run() == 0
    assert transport.calls == [(record["runtime_session_id"], record["shell_id"])] * 2
    assert not any(frame[0] == 0 for frame in second.sent)
    assert first.closed and second.closed


async def test_uncertain_initial_send_is_persisted_before_delivery(store, record):
    class InterruptedSocket(FakeSocket):
        async def send(self, data):
            if data[0] == 0:
                assert store.load(record["id"])["launch_state"] == "attempted"
                raise OSError("send failed")
            await super().send(data)

    first = InterruptedSocket(confirmation(record))
    second = FakeSocket(confirmation(record, True), termination())
    await Connector(store, record, FakeTransport(first, second), FakeTerminal()).run()
    assert not any(frame[0] == 0 for frame in second.sent)


async def test_kicked_client_never_reconnects(store, record):
    kicked = ConnectionClosedError(Close(4000, "taken over"), None)
    socket = FakeSocket(confirmation(record), kicked)
    transport = FakeTransport(socket)
    assert await Connector(store, record, transport, FakeTerminal()).run() == 1
    assert len(transport.calls) == 1
    assert store.load(record["id"])["status"] == "taken_over"


async def test_shutdown_frame_ends_session_without_retry(store, record):
    socket = FakeSocket(confirmation(record), b"\xff")
    with pytest.raises(UserError, match="terminated"):
        await Connector(store, record, FakeTransport(socket), FakeTerminal()).run()
    assert store.load(record["id"])["status"] == "expired"


async def test_detach_cancels_blocked_connect(store, record):
    class BlockedTransport:
        async def connect(self, record):
            await asyncio.Future()

    terminal = FakeTerminal()
    task = asyncio.create_task(Connector(store, record, BlockedTransport(), terminal).run())
    await until(lambda: record["status"] == "connecting")
    terminal.detached.set()
    assert await asyncio.wait_for(task, 1) == 0


async def test_invalid_confirmation_cannot_start_agent(store, record):
    socket = FakeSocket(b'\x03{"metadata": {"shellId": "wrong"}, "status": "Success"}')
    with pytest.raises(UserError, match="confirm"):
        await Connector(store, record, FakeTransport(socket), FakeTerminal()).run()
    assert not socket.sent


async def test_uncertain_prompt_delivery_is_not_retried(store, record):
    class FailingInput(FakeSocket):
        async def send(self, data):
            if data == b"\x00my prompt\r":
                raise OSError("connection dropped during input")
            await super().send(data)

    socket = FailingInput(confirmation(record))
    terminal = FakeTerminal()
    transport = FakeTransport(socket)
    runner = asyncio.create_task(Connector(store, record, transport, terminal).run())
    await until(lambda: terminal.enabled)
    await terminal.inputs.put(b"my prompt\r")
    with pytest.raises(UserError, match="delivery became uncertain"):
        await runner
    assert len(transport.calls) == 1
    assert not terminal.enabled and socket.closed


async def test_zero_retry_window_does_not_retry_failed_connect(store, record):
    transport = FakeTransport(OSError("offline"))
    with pytest.raises(UserError, match="Reconnect window elapsed"):
        await Connector(store, record, transport, FakeTerminal(), reconnect_seconds=0).run()
    assert len(transport.calls) == 1


async def test_normal_close_without_status_does_not_retry(store, record):
    from websockets.exceptions import ConnectionClosedOK

    socket = FakeSocket(confirmation(record), ConnectionClosedOK(Close(1000, ""), None))
    transport = FakeTransport(socket)
    assert await Connector(store, record, transport, FakeTerminal()).run() == 1
    assert store.load(record["id"])["status"] == "exited"
    assert len(transport.calls) == 1


def test_shell_arguments_cannot_inject_additional_commands():
    profile = Profile.from_dict(
        {
            "runtime_arn": ARN,
            "command": [
                "/app/custom launcher",
                "'; touch /tmp/oops; '",
                "$(something)",
            ],
        }
    )
    argv = shlex.split(launch_command(profile))
    assert argv[4:] == profile.command


async def test_real_local_websocket_byte_and_resize_roundtrip(store, record):
    """A real local WS server verifies protocol I/O without AWS or credentials."""
    received = []
    terminal = FakeTerminal()

    async def server(ws):
        await ws.send(confirmation(record))
        received.append(await ws.recv())  # dimensions
        received.append(await ws.recv())  # launch
        await ws.send(b"\x01\x1b[?2004hremote ready")
        received.append(await ws.recv())  # test input
        await ws.send(b"\x01input received")
        received.append(await ws.recv())  # resize
        await ws.send(termination())

    async with websockets.serve(server, "127.0.0.1", 0) as serving:
        port = serving.sockets[0].getsockname()[1]

        class LocalTransport:
            async def connect(self, record):
                return await websockets.connect(f"ws://127.0.0.1:{port}")

        runner = asyncio.create_task(Connector(store, record, LocalTransport(), terminal).run())
        await until(lambda: b"remote ready" in terminal.output)
        await terminal.inputs.put(b"\x1b[200~hello\nworld\x1b[201~\r")
        await until(lambda: b"input received" in terminal.output)
        terminal.dimensions = (60, 20)
        terminal.resized.set()
        assert await asyncio.wait_for(runner, 3) == 0
    assert received[2] == b"\x00\x1b[200~hello\nworld\x1b[201~\r"
    assert received[3] == b'\x04{"width": 60, "height": 20}'
