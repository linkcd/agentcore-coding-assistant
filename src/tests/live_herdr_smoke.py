"""Opt-in end-to-end plugin probe in an isolated Herdr server and cloud session.

Requires execution from an existing Herdr pane and a deployed OpenCode runtime.
Never runs as part of the default pytest suite. All created cloud sessions and
the disposable local server are stopped in cleanup.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from herdr_agentcore.connector import AgentCoreTransport
from herdr_agentcore.storage import Paths, Profile, Store, UserError

ROOT = Path(__file__).resolve().parents[2]


def until(operation, description: str, timeout: float = 90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = operation()
        if value:
            return value
        time.sleep(0.25)
    raise UserError(f"Timed out: {description}")


class IsolatedHerdr:
    def __init__(self, directory: Path):
        self.binary = shutil.which("herdr")
        if not self.binary:
            raise UserError("herdr is not installed.")
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("HERDR_")}
        self.env.update(
            {
                "XDG_CONFIG_HOME": str(directory / "c"),
                "XDG_STATE_HOME": str(directory / "s"),
                "HERDR_CONFIG_PATH": str(directory / "config.toml"),
                "HERDR_SOCKET_PATH": str(directory / "a.sock"),
                "HERDR_CLIENT_SOCKET_PATH": str(directory / "b.sock"),
                "HERDR_SESSION": "agentcore-smoke-" + uuid.uuid4().hex[:8],
                "SHELL": "/bin/sh",
            }
        )
        (directory / "config.toml").write_text(
            '[terminal]\ndefault_shell = "/bin/sh"\nshell_mode = "non_login"\n'
            "[update]\nversion_check = false\nmanifest_check = false\n"
            "[session]\nresume_agents_on_restore = false\n"
        )
        self.server = None
        self.directory = directory

    def call(self, *args, check=True, timeout=20) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [self.binary, *args],
            env=self.env,
            cwd=self.directory,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode:
            raise UserError(f"Herdr {' '.join(args[:3])}: {result.stderr.strip() or result.stdout}")
        return result

    def result(self, *args, **kwargs):
        reply = json.loads(self.call(*args, **kwargs).stdout)
        if "error" in reply:
            raise UserError(str(reply["error"]))
        return reply["result"]

    def start(self):
        self.call("plugin", "link", str(ROOT))
        self.server = subprocess.Popen(
            [self.binary, "server"],
            env=self.env,
            cwd=self.directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        until(
            lambda: self.call("workspace", "list", check=False).returncode == 0,
            "isolated Herdr server startup",
            15,
        )
        print(f"Isolated Herdr session: {self.env['HERDR_SESSION']}", flush=True)

    def close(self):
        if self.server is not None:
            self.call("server", "stop", check=False)
            self.server.wait(timeout=20)
            print("Stopped isolated Herdr server", flush=True)

    def read(self, pane):
        response = self.call("pane", "read", pane, "--source", "recent-unwrapped", check=False)
        return response.stdout if response.returncode == 0 else ""

    def panes(self):
        return self.result("pane", "list")["panes"]

    def action_pane(self, action: str):
        before = {pane["pane_id"] for pane in self.panes()}
        self.result("plugin", "action", "invoke", f"agentcore.{action}")
        return until(
            lambda: next((p["pane_id"] for p in self.panes() if p["pane_id"] not in before), None),
            f"plugin {action} action opened a pane",
            15,
        )

    def select_first(self, pane):
        self.call("pane", "send-text", pane, "1")
        self.call("pane", "send-keys", pane, "enter")

    def agent(self, pane):
        response = self.call("agent", "get", pane, check=False)
        if response.returncode:
            return None
        return json.loads(response.stdout).get("result", {}).get("agent")


def run(runtime_arn: str, aws_profile: str | None):
    if os.environ.get("HERDR_ENV") != "1":
        raise UserError("Run this probe from a Herdr-managed pane.")
    profile = Profile.from_dict({"runtime_arn": runtime_arn, "aws_profile": aws_profile})
    transport = AgentCoreTransport(profile)
    with tempfile.TemporaryDirectory(prefix="h-") as temp:
        herdr = IsolatedHerdr(Path(temp))
        store = None
        pane = None
        try:
            herdr.start()
            config = Path(herdr.call("plugin", "config-dir", "agentcore").stdout.strip())
            state = Path(herdr.env["XDG_STATE_HOME"]) / "herdr" / "plugins" / "agentcore"
            store = Store(Paths(config, state))
            store.save_profile("live-smoke", profile)
            workspace = herdr.result(
                "workspace", "create", "--cwd", temp, "--label", "AgentCore live smoke", "--focus"
            )
            print(
                f"Created isolated workspace: {workspace['workspace']['workspace_id']}", flush=True
            )
            pane = herdr.action_pane("new")
            until(lambda: "Runtime profile" in herdr.read(pane), "runtime picker", 15)
            herdr.select_first(pane)
            record = until(lambda: next(iter(store.connections()), None), "connection record", 15)
            print(f"Fresh test runtime session: {record['runtime_session_id']}", flush=True)
            until(lambda: store.load(record["id"])["status"] == "connected", "AgentCore connection")
            agent = until(lambda: herdr.agent(pane), "OpenCode recognized by Herdr")
            print("Herdr agent recognition: " + json.dumps(agent), flush=True)
            # This OpenCode version draws its name as block art, not literal text.
            # Recognition may precede both the input widget and its idle state.
            until(lambda: "Ask anything" in herdr.read(pane), "OpenCode input widget")
            herdr.result(
                "agent",
                "wait",
                pane,
                "--until",
                "idle",
                "--until",
                "done",
                "--timeout",
                "30000",
                timeout=35,
            )
            print("OpenCode screen:\n" + herdr.read(pane), flush=True)
            prompt = (
                "This is a connectivity smoke test. Do not use tools or change files. "
                "Reply with HERDR and CLOUD joined by a hyphen, then an equals sign, "
                "then the sum of 173 and 284. Output only that one string."
            )
            response = herdr.call(
                "agent",
                "prompt",
                pane,
                prompt,
                "--wait",
                "--timeout",
                "90000",
                check=False,
                timeout=100,
            )
            print(f"agent prompt --wait exit code: {response.returncode}", flush=True)
            if response.returncode:
                print(response.stderr or response.stdout, flush=True)
                raise UserError("Herdr prompt/wait failed; input will not be resubmitted.")
            until(lambda: "HERDR-CLOUD=457" in herdr.read(pane), "model reply", 60)
            print("PASS: model turn produced HERDR-CLOUD=457", flush=True)
            print("Completed screen:\n" + herdr.read(pane), flush=True)
            herdr.call("pane", "send-text", pane, "\x1dd")
            until(lambda: store.load(record["id"])["status"] == "detached", "connector detach", 15)
            print("PASS: detach without runtime stop", flush=True)
            pane = herdr.action_pane("attach")
            until(lambda: "Session [" in herdr.read(pane), "saved-session picker", 15)
            herdr.select_first(pane)
            until(lambda: store.load(record["id"])["status"] == "connected", "reattachment")
            until(lambda: "HERDR-CLOUD=457" in herdr.read(pane), "conversation after reattach", 30)
            if len(store.connections()) != 1:
                raise UserError("Reattachment unexpectedly created another connection record.")
            print(
                "PASS: reattached same saved session and preserved conversation output", flush=True
            )
            herdr.result(
                "agent",
                "wait",
                pane,
                "--until",
                "idle",
                "--until",
                "done",
                "--timeout",
                "30000",
                timeout=35,
            )
            followup = (
                "Do not use tools. Prefix your previous answer with RESUMED: "
                "and output only the resulting string."
            )
            response = herdr.call(
                "agent",
                "prompt",
                pane,
                followup,
                "--wait",
                "--timeout",
                "90000",
                check=False,
                timeout=100,
            )
            if response.returncode:
                print(response.stderr or response.stdout, flush=True)
                raise UserError(
                    "Herdr follow-up prompt/wait failed; input will not be resubmitted."
                )
            until(
                lambda: "RESUMED:HERDR-CLOUD=457" in herdr.read(pane), "follow-up model reply", 60
            )
            print(
                "PASS: follow-up model turn after reattach retained conversation context",
                flush=True,
            )
            herdr.call("pane", "send-text", pane, "\x1dd")
            until(lambda: store.load(record["id"])["status"] == "detached", "final detach", 15)
            pane = herdr.action_pane("stop")
            until(lambda: "Session [" in herdr.read(pane), "stop-session picker", 15)
            herdr.select_first(pane)
            until(lambda: "to stop it:" in herdr.read(pane), "explicit stop confirmation", 15)
            herdr.call("pane", "send-text", pane, record["name"])
            herdr.call("pane", "send-keys", pane, "enter")
            until(lambda: store.load(record["id"])["status"] == "stopped", "runtime stop", 45)
            print("PASS: plugin stop action terminated its own test runtime session", flush=True)
        except BaseException:
            if pane:
                print("Last isolated pane output:\n" + herdr.read(pane), flush=True)
                print("Last agent state: " + json.dumps(herdr.agent(pane)), flush=True)
            raise
        finally:
            try:
                herdr.close()
            finally:
                if store is not None:
                    for record in store.connections():
                        if record["status"] != "stopped":
                            transport.stop(record)
                            print(
                                f"Stopped own test session: {record['runtime_session_id']}",
                                flush=True,
                            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--aws-profile")
    args = parser.parse_args()
    try:
        run(args.runtime_arn, args.aws_profile)
    except Exception as exc:
        message = str(exc) if isinstance(exc, UserError) else type(exc).__name__
        print(f"FAIL: {message}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
