"""Cancellable POSIX terminal I/O with bounded input and live resize forwarding."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import termios
import tty

from .storage import UserError


class DetachKeys:
    """Ctrl+] d detaches; Ctrl+] Ctrl+] sends a literal Ctrl+]."""

    def __init__(self):
        self.pending = False

    def feed(self, data: bytes) -> tuple[bytes, bool]:
        output = bytearray()
        for byte in data:
            if self.pending:
                self.pending = False
                if byte == ord("d"):
                    return bytes(output), True
                output.append(0x1D)
                if byte != 0x1D:
                    output.append(byte)
            elif byte == 0x1D:
                self.pending = True
            else:
                output.append(byte)
        return bytes(output), False


class Terminal:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.output_fd = sys.stdout.fileno()
        self.inputs: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self.resized = asyncio.Event()
        self.detached = asyncio.Event()
        self.keys = DetachKeys()
        self.enabled = False
        self.reader_active = False

    def __enter__(self):
        if not os.isatty(self.fd) or not os.isatty(self.output_fd):
            raise UserError("Interactive connection requires a terminal (a Herdr pane works).")
        self.loop = asyncio.get_running_loop()
        self.settings = termios.tcgetattr(self.fd)
        self.output_blocking = os.get_blocking(self.output_fd)
        self.signals = {
            sig: signal.getsignal(sig)
            for sig in (
                signal.SIGWINCH,
                signal.SIGTERM,
                signal.SIGHUP,
            )
        }
        try:
            tty.setraw(self.fd)
            os.set_blocking(self.output_fd, False)
            self._add_reader()
            self.loop.add_signal_handler(signal.SIGWINCH, self.resized.set)
            for sig in (signal.SIGTERM, signal.SIGHUP):
                self.loop.add_signal_handler(sig, self.detached.set)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        self.loop.remove_reader(self.fd)
        self.loop.remove_writer(self.output_fd)
        for sig, previous in self.signals.items():
            self.loop.remove_signal_handler(sig)
            signal.signal(sig, previous)
        # Never wait for a stalled output consumer while restoring the terminal.
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.settings)
        except (OSError, termios.error):
            pass  # A closed PTY may no longer accept mode changes.
        cleanup = (
            b"\x1b[?2026l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1004l\x1b[?1006l"
            b"\x1b[?2004l\x1b[?1049l\x1b[?25h\x1b[0m\r\n"
        )
        try:
            os.write(self.output_fd, cleanup)
        except OSError:
            pass  # Best-effort display cleanup; never block or hide the original error.
        finally:
            try:
                os.set_blocking(self.output_fd, self.output_blocking)
            except OSError:
                pass  # A closed descriptor cannot be restored.

    def _add_reader(self):
        if not self.reader_active:
            self.loop.add_reader(self.fd, self._readable)
            self.reader_active = True

    def _readable(self):
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            self.detached.set()
            return
        if not data:
            self.detached.set()
            return
        data, detach = self.keys.feed(data)
        if detach:
            self.detached.set()
            return
        if data and self.enabled:
            self.inputs.put_nowait(data)
            if self.inputs.full():
                self.loop.remove_reader(self.fd)
                self.reader_active = False
        # Keystrokes during an outage are deliberately not replayed later.

    def enable_input(self, enabled: bool):
        self.enabled = enabled
        if not enabled:
            while not self.inputs.empty():
                self.inputs.get_nowait()
            self._add_reader()

    async def read(self) -> bytes:
        data = await self.inputs.get()
        self._add_reader()
        return data

    def size(self) -> tuple[int, int]:
        size = os.get_terminal_size(self.output_fd)
        return max(size.columns, 1), max(size.lines, 1)

    async def write(self, data: bytes):
        remaining = memoryview(data)
        while remaining:
            try:
                written = os.write(self.output_fd, remaining)
            except BlockingIOError:
                ready = self.loop.create_future()

                def writable(ready=ready):
                    if not ready.done():
                        ready.set_result(None)

                self.loop.add_writer(self.output_fd, writable)
                try:
                    await ready
                finally:
                    self.loop.remove_writer(self.output_fd)
                continue
            if written <= 0:
                raise OSError("Terminal output closed.")
            remaining = remaining[written:]

    async def notice(self, message: str):
        await self.write(f"\r\n[AgentCore] {message}\r\n".encode())
