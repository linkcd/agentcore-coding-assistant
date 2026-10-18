"""Local terminal input and mode restoration."""

import asyncio
import os
import pty
import termios

import pytest
from herdr_agentcore.terminal import DetachKeys, Terminal


def test_detach_prefix_across_reads_and_literal_escape():
    keys = DetachKeys()
    assert keys.feed(b"hello\x1d") == (b"hello", False)
    assert keys.feed(b"d") == (b"", True)
    assert keys.feed(b"\x1d\x1d") == (b"\x1d", False)
    assert keys.feed(b"\x1dx") == (b"\x1dx", False)
    assert keys.feed(b"\x03\x1b[A") == (b"\x03\x1b[A", False)


async def test_real_pty_restores_modes_on_error_and_discards_offline_input(monkeypatch):
    master, slave = pty.openpty()

    class Stream:
        def fileno(self):
            return slave

    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdin", Stream())
    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdout", Stream())
    original = termios.tcgetattr(slave)
    try:
        terminal = Terminal()
        with pytest.raises(RuntimeError, match="intentional"), terminal:
            assert not termios.tcgetattr(slave)[3] & termios.ICANON
            os.write(master, b"discard during outage")
            terminal._readable()
            assert terminal.inputs.empty()
            terminal.enable_input(True)
            os.write(master, b"prompt\r")
            terminal._readable()
            assert await terminal.read() == b"prompt\r"
            raise RuntimeError("intentional")
        restored = termios.tcgetattr(slave)
        # macOS may set the kernel-owned PENDIN bit on return to canonical mode.
        restored[3] &= ~getattr(termios, "PENDIN", 0)
        original[3] &= ~getattr(termios, "PENDIN", 0)
        assert restored == original
    finally:
        os.close(master)
        os.close(slave)


async def test_full_output_buffer_does_not_block_timers_or_detach(monkeypatch):
    master, slave = pty.openpty()

    class Stream:
        def fileno(self):
            return slave

    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdin", Stream())
    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdout", Stream())
    writer = None
    original = termios.tcgetattr(slave)
    try:
        with Terminal() as terminal:
            writer = asyncio.create_task(terminal.write(b"x" * (2 * 1024 * 1024)))
            tick = asyncio.Event()
            asyncio.get_running_loop().call_later(0.02, tick.set)
            await asyncio.wait_for(tick.wait(), 1)
            assert not writer.done()
            os.write(master, b"\x1dd")
            await asyncio.wait_for(terminal.detached.wait(), 1)
            writer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await writer
        assert os.get_blocking(slave)
        assert bool(termios.tcgetattr(slave)[3] & termios.ICANON) == bool(
            original[3] & termios.ICANON
        )
    finally:
        if writer is not None:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        os.close(master)
        os.close(slave)


async def test_partial_nonblocking_writes_preserve_all_bytes(monkeypatch):
    master, slave = pty.openpty()

    class Stream:
        def fileno(self):
            return slave

    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdin", Stream())
    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdout", Stream())
    os.set_blocking(master, False)
    data = bytes(range(256)) * 4096
    received = bytearray()

    async def read():
        while len(received) < len(data):
            try:
                received.extend(os.read(master, 65536))
            except BlockingIOError:
                await asyncio.sleep(0.001)

    try:
        with Terminal() as terminal:
            await asyncio.wait_for(asyncio.gather(terminal.write(data), read()), 3)
            assert received == data
    finally:
        os.close(master)
        os.close(slave)


async def test_closed_pty_cleanup_does_not_hide_original_error(monkeypatch):
    master, slave = pty.openpty()

    class Stream:
        def fileno(self):
            return slave

    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdin", Stream())
    monkeypatch.setattr("herdr_agentcore.terminal.sys.stdout", Stream())
    try:
        with pytest.raises(RuntimeError, match="original failure"), Terminal():
            os.close(slave)
            raise RuntimeError("original failure")
    finally:
        os.close(master)
