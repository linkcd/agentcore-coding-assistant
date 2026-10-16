"""Local terminal input and mode restoration."""

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
