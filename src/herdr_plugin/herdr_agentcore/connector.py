"""AgentCore shell transport, with at-most-once launch and explicit reattachment."""

from __future__ import annotations

import asyncio
import shlex
import time

from bedrock_agentcore.runtime.shell import ShellChannel, ShellFramer
from websockets.exceptions import ConnectionClosed

from .agentcore import AgentCoreError
from .agentcore import AgentCoreTransport as AgentCoreTransport
from .models import ConnectionRecord, LaunchState, Profile, UserError
from .storage import Store


def launch_command(profile: Profile) -> str:
    # argv, not an interpolated user prompt. The remote shell is replaced so its
    # termination STATUS reflects agent exit rather than an idle parent shell.
    return "exec env TERM=xterm-256color COLORTERM=truecolor " + shlex.join(profile.command) + "\n"


def status_payload(frame) -> dict:
    try:
        value = frame.json()
    except (ValueError, UnicodeError) as exc:
        raise UserError("Invalid AgentCore shell STATUS frame.") from exc
    if not isinstance(value, dict) or not isinstance(value.get("metadata", {}), dict):
        raise UserError("Invalid AgentCore shell STATUS structure.")
    return value


def exit_code(status: dict) -> int:
    if status.get("status") == "Success":
        return 0
    for cause in status.get("details", {}).get("causes", []):
        if cause.get("reason") == "ExitCode":
            try:
                return int(cause["message"])
            except (ValueError, KeyError, TypeError):
                break
    return 1


class Connector:
    def __init__(
        self,
        store: Store,
        record: ConnectionRecord | dict,
        transport,
        terminal,
        reconnect_seconds: float = 120,
        publish=None,
    ):
        self.store = store
        self.record = (
            record if isinstance(record, ConnectionRecord) else ConnectionRecord.from_dict(record)
        )
        self.transport = transport
        self.terminal = terminal
        self.reconnect_seconds = reconnect_seconds
        self.publish = publish
        self.framer = ShellFramer()

    async def status(self, value: str, message: str | None = None):
        self.record.transition(value, message)
        self.store.save_record(self.record)
        if self.publish:
            await self.publish(self.record.id, value)

    async def run(self) -> int:
        if not self.record.status.attachable:
            raise UserError("This remote session has ended. Create a new cloud agent.")
        worker = asyncio.create_task(self._serve())
        detach = asyncio.create_task(self.terminal.detached.wait())
        try:
            done, _ = await asyncio.wait([worker, detach], return_when=asyncio.FIRST_COMPLETED)
            if worker in done:
                return await worker
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            await self.status("detached")
            return 0
        except UserError as exc:
            if self.record.status.attachable:
                await self.status("error", str(exc))
            raise
        finally:
            worker.cancel()
            detach.cancel()
            await asyncio.gather(worker, detach, return_exceptions=True)

    async def _serve(self) -> int:
        outage_start = None
        delay = 1.0
        while True:
            ws = None
            connected_at = None
            await self.status("connecting" if outage_start is None else "reconnecting")
            try:
                ws = await self.transport.connect(self.record.to_dict())
                reconnected = await asyncio.wait_for(self._confirmation(ws), timeout=30)
                if not reconnected and self.record.launch_state != LaunchState.NOT_STARTED:
                    await self.status("expired", "The original remote PTY no longer exists.")
                    raise UserError(
                        "The original remote PTY no longer exists. No command was replayed. "
                        "Create a new agent and recover its workspace/conversation explicitly."
                    )
                await ws.send(self.framer.encode_resize(*self.terminal.size()))
                if self.record.launch_state == LaunchState.NOT_STARTED:
                    # Persist BEFORE sending. A crash/send failure must never cause
                    # another launch command to be typed into a running agent.
                    self.record.launch_state = LaunchState.ATTEMPTED
                    self.store.save_record(self.record)
                    await ws.send(self.framer.encode_stdin(launch_command(self.record.profile)))
                    self.record.launch_state = LaunchState.SENT
                    self.store.save_record(self.record)
                elif self.record.launch_state == LaunchState.ATTEMPTED:
                    await self.terminal.notice(
                        "Launch delivery is uncertain; inspect the existing terminal."
                    )
                await self.status("connected")
                connected_at = time.monotonic()
                code = await self._pump(ws)
                self.record.exit_code = code
                await self.status("exited")
                return code
            except AgentCoreError as exc:
                if not exc.retryable:
                    raise
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
                if code == 4000:
                    await self.status("taken_over", "Another client attached to this shell.")
                    await self.terminal.notice(
                        "Another client took over this shell; reconnect disabled."
                    )
                    return 1
                if code == 1000:
                    await self.status("exited", "Shell connection closed without an exit status.")
                    return 1
            except (OSError, TimeoutError):
                pass  # Transient network failure; do not replay any user input.
            finally:
                self.terminal.enable_input(False)
                if ws is not None:
                    # WebSocket close detaches. Do not send channel 0xff, which
                    # requests remote shell shutdown.
                    try:
                        await ws.close()
                    except (OSError, ConnectionClosed):
                        pass
            now = time.monotonic()
            if connected_at is not None and now - connected_at >= 30:
                outage_start = None
                delay = 1.0
            if outage_start is None:
                outage_start = now
                await self.terminal.notice(
                    "Disconnected. Reconnecting; input is paused. Ctrl+] d detaches."
                )
            remaining = self.reconnect_seconds - (now - outage_start)
            if remaining <= 0:
                raise UserError("Reconnect window elapsed. Use the reattach action to try again.")
            await self.status("reconnecting")
            await asyncio.sleep(min(delay, remaining))
            delay = min(delay * 2, 15)

    async def _confirmation(self, ws) -> bool:
        while True:
            raw = await ws.recv()
            if not isinstance(raw, bytes) or not raw:
                continue
            frame = self.framer.decode(raw)
            if frame.channel == ShellChannel.STATUS:
                status = status_payload(frame)
                metadata = status.get("metadata", {})
                if metadata.get("shellId") != self.record.shell_id:
                    raise UserError("AgentCore did not confirm the requested shell ID.")
                if not isinstance(metadata.get("reconnected"), bool):
                    raise UserError(
                        "Shell confirmation lacks reconnected state; refusing unsafe launch."
                    )
                return metadata["reconnected"]
            if frame.channel in {ShellChannel.STDOUT, ShellChannel.STDERR}:
                await self.terminal.write(frame.payload)
            elif frame.channel == ShellChannel.CLOSE:
                raise UserError("AgentCore closed the shell before connection confirmation.")

    async def _pump(self, ws) -> int:
        async def output():
            while True:
                raw = await ws.recv()
                if not isinstance(raw, bytes) or not raw:
                    continue
                frame = self.framer.decode(raw)
                if frame.channel in {ShellChannel.STDOUT, ShellChannel.STDERR}:
                    await self.terminal.write(frame.payload)
                elif frame.channel == ShellChannel.STATUS:
                    status = status_payload(frame)
                    if not status.get("metadata", {}).get("shellId"):
                        return exit_code(status)
                elif frame.channel == ShellChannel.CLOSE:
                    await self.status("expired", "AgentCore terminated the remote shell.")
                    raise UserError("AgentCore terminated the remote shell (shutdown or expiry).")
                # HEARTBEAT and future channels aren't terminal output.

        async def input_bytes():
            while True:
                data = await self.terminal.read()
                try:
                    await ws.send(self.framer.encode_stdin(data))
                except (ConnectionClosed, OSError) as exc:
                    raise UserError(
                        "Input delivery became uncertain. Reattach and inspect before resubmitting."
                    ) from exc

        async def resize():
            while True:
                await self.terminal.resized.wait()
                self.terminal.resized.clear()
                await ws.send(self.framer.encode_resize(*self.terminal.size()))

        self.terminal.enable_input(True)
        reader = asyncio.create_task(output())
        tasks = [reader, asyncio.create_task(input_bytes()), asyncio.create_task(resize())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # Prefer explicit shell termination if it coincides with another I/O failure.
            if reader in done:
                return await reader
            for task in tasks:
                if task in done:
                    await task
            raise UserError("Terminal input loop stopped unexpectedly.")
        finally:
            self.terminal.enable_input(False)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
