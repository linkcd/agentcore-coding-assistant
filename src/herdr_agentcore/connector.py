"""AgentCore shell transport, with at-most-once launch and explicit reattachment."""

from __future__ import annotations

import asyncio
import shlex
import time

import websockets
from bedrock_agentcore.runtime.shell import ShellChannel, ShellFramer
from botocore.exceptions import BotoCoreError, ClientError
from websockets.exceptions import ConnectionClosed, InvalidStatus

from .storage import Profile, Store, UserError

TERMINAL_STATUSES = {"exited", "expired", "stopped"}


class AgentCoreTransport:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.client = None

    def _sign(self, record: dict):
        # Credential resolution/signing may invoke an SSO/credential process.
        # Run it off the terminal's asyncio loop and re-sign each connection.
        if self.client is None:
            import boto3
            from bedrock_agentcore.runtime import AgentCoreRuntimeClient

            session = boto3.Session(
                profile_name=self.profile.aws_profile,
                region_name=self.profile.region,
            )
            self.client = AgentCoreRuntimeClient(region=self.profile.region, session=session)
        return self.client.connect_shell(
            runtime_arn=self.profile.runtime_arn,
            session_id=record["runtime_session_id"],
            shell_id=record["shell_id"],
            endpoint_name=self.profile.endpoint,
        )

    async def connect(self, record: dict):
        url, headers = await asyncio.to_thread(self._sign, record)
        return await websockets.connect(
            url,
            additional_headers=headers,
            open_timeout=30,
            close_timeout=3,
            ping_interval=20,
            ping_timeout=20,
            max_size=64 * 1024,
            max_queue=16,
        )

    def stop(self, record: dict):
        import boto3

        session = boto3.Session(
            profile_name=self.profile.aws_profile,
            region_name=self.profile.region,
        )
        session.client("bedrock-agentcore").stop_runtime_session(
            agentRuntimeArn=self.profile.runtime_arn,
            runtimeSessionId=record["runtime_session_id"],
            qualifier=self.profile.endpoint,
        )


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
        record: dict,
        transport,
        terminal,
        reconnect_seconds: float = 120,
        publish=None,
    ):
        self.store = store
        self.record = record
        self.transport = transport
        self.terminal = terminal
        self.reconnect_seconds = reconnect_seconds
        self.publish = publish
        self.framer = ShellFramer()

    async def status(self, value: str, message: str | None = None):
        self.record["status"] = value
        if message:
            self.record["last_message"] = message
        else:
            self.record.pop("last_message", None)
        self.store.save(self.record)
        if self.publish:
            await self.publish(self.record["id"], value)

    async def run(self) -> int:
        if self.record["status"] in TERMINAL_STATUSES:
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
            if self.record["status"] not in TERMINAL_STATUSES:
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
                ws = await self.transport.connect(self.record)
                reconnected = await asyncio.wait_for(self._confirmation(ws), timeout=30)
                if not reconnected and self.record["launch_state"] != "not_started":
                    await self.status("expired", "The original remote PTY no longer exists.")
                    raise UserError(
                        "The original remote PTY no longer exists. No command was replayed. "
                        "Create a new agent and recover its workspace/conversation explicitly."
                    )
                await ws.send(self.framer.encode_resize(*self.terminal.size()))
                if self.record["launch_state"] == "not_started":
                    # Persist BEFORE sending. A crash/send failure must never cause
                    # another launch command to be typed into a running agent.
                    self.record["launch_state"] = "attempted"
                    self.store.save(self.record)
                    profile = Profile.from_dict(self.record["profile"])
                    await ws.send(self.framer.encode_stdin(launch_command(profile)))
                    self.record["launch_state"] = "sent"
                    self.store.save(self.record)
                elif self.record["launch_state"] == "attempted":
                    self.terminal.notice(
                        "Launch delivery is uncertain; inspect the existing terminal."
                    )
                await self.status("connected")
                connected_at = time.monotonic()
                code = await self._pump(ws)
                self.record["exit_code"] = code
                await self.status("exited")
                return code
            except InvalidStatus as exc:
                if exc.response.status_code < 500 and exc.response.status_code != 429:
                    raise UserError(
                        f"AgentCore rejected the connection (HTTP {exc.response.status_code}). "
                        "Check the runtime, region, endpoint, and AWS shell permissions."
                    ) from exc
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
                if code == 4000:
                    await self.status("taken_over", "Another client attached to this shell.")
                    self.terminal.notice("Another client took over this shell; reconnect disabled.")
                    return 1
                if code == 1000:
                    await self.status("exited", "Shell connection closed without an exit status.")
                    return 1
            except (BotoCoreError, ClientError) as exc:
                raise UserError(
                    f"AWS authentication/configuration failed ({type(exc).__name__}). "
                    "Check your AWS profile and refresh its credentials if needed."
                ) from exc
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
                self.terminal.notice(
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
                if metadata.get("shellId") != self.record["shell_id"]:
                    raise UserError("AgentCore did not confirm the requested shell ID.")
                if not isinstance(metadata.get("reconnected"), bool):
                    raise UserError(
                        "Shell confirmation lacks reconnected state; refusing unsafe launch."
                    )
                return metadata["reconnected"]
            if frame.channel in {ShellChannel.STDOUT, ShellChannel.STDERR}:
                self.terminal.write(frame.payload)
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
                    self.terminal.write(frame.payload)
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
