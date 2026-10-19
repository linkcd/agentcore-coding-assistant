"""Opt-in end-to-end plugin probe in an isolated Herdr server and cloud session.

Requires execution from an existing Herdr pane and a deployed assistant runtime.
Never runs as part of the default pytest suite. All created cloud sessions and
the disposable local server are stopped in cleanup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from agentcore_contract import decode_descriptor
from herdr_agentcore.connector import AgentCoreTransport
from herdr_agentcore.storage import Paths, Profile, Store, UserError

ROOT = Path(__file__).resolve().parents[3]


def until(operation, description: str, timeout: float = 90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = operation()
        if value:
            return value
        time.sleep(0.25)
    raise UserError(f"Timed out: {description}")


def check_prompt_screen(screen: str):
    # This OpenCode update dialog can still be classified as idle by Herdr.
    # Sending a prompt+Enter would answer the dialog, not submit a model turn.
    if "update available" in screen.lower() or "updating to v" in screen.lower():
        raise UserError("The assistant's updater is active; no prompt will be submitted.")


def input_widget_ready(kind: str, screen: str) -> bool:
    if kind == "opencode":
        return "Ask anything" in screen
    if kind == "codex":
        return "Codex" in screen and "›" in screen
    raise UserError("This E2E probe has no UI driver for the selected recognition kind.")


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


def check_runtime_role_environment(profile: Profile, record: dict, expect_shim: bool = True):
    """Inspect only our test session; return booleans, never credential values."""
    import boto3
    from botocore.config import Config

    kind = profile.agent_kind
    if kind not in {"opencode", "codex"}:
        raise UserError("This process probe supports the two supplied example adapters only.")
    script = (
        "PROCESS_NAME = "
        + repr(kind)
        + "\n"
        + """
import json
from pathlib import Path

snapshots = []
for process in Path('/proc').glob('[0-9]*'):
    try:
        if (process / 'comm').read_text().strip() != PROCESS_NAME:
            continue
        env = dict(item.split(b'=', 1) for item in
                   (process / 'environ').read_bytes().split(b'\\0') if b'=' in item)
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    snapshots.append({
        'has_static_credentials': any(key in env for key in (
            b'AWS_ACCESS_KEY_ID', b'AWS_SECRET_ACCESS_KEY',
            b'AWS_SESSION_TOKEN', b'AWS_SECURITY_TOKEN')),
        'default_profile': env.get(b'AWS_PROFILE') == b'default',
        'shim_used': bool(env.get(b'HERDR_REAL_OPENCODE')),
        'has_provider_token': any(key in env for key in (
            b'AWS_BEARER_TOKEN_BEDROCK', b'OPENAI_API_KEY')),
    })
print(json.dumps(snapshots))
"""
    )
    client = boto3.Session(profile_name=profile.aws_profile, region_name=profile.region).client(
        "bedrock-agentcore", config=Config(read_timeout=60)
    )
    response = client.invoke_agent_runtime_command(
        agentRuntimeArn=profile.runtime_arn,
        runtimeSessionId=record["runtime_session_id"],
        qualifier=profile.endpoint,
        body={"command": shlex.join(["python3", "-c", script]), "timeout": 30},
    )
    output = []
    exit_code = None
    for event in response["stream"]:
        if "chunk" not in event:
            raise UserError("Runtime credential environment inspection failed.")
        chunk = event["chunk"]
        output.append(chunk.get("contentDelta", {}).get("stdout", ""))
        if "contentStop" in chunk:
            exit_code = chunk["contentStop"].get("exitCode")
    if exit_code != 0:
        raise UserError("Runtime credential environment inspection did not complete.")
    snapshots = json.loads("".join(output))
    if not snapshots or not all(
        not entry["has_static_credentials"]
        and (kind != "opencode" or entry["default_profile"])
        and not entry.get("has_provider_token", False)
        and entry["shim_used"] == expect_shim
        for entry in snapshots
    ):
        raise UserError("The assistant did not start with the expected runtime-role environment.")
    print(f"PASS: runtime {kind} has no static AWS credentials or provider tokens", flush=True)


def run(
    runtime_arn: str,
    aws_profile: str | None,
    connection_file: Path | None = None,
    check_runtime_role: bool = False,
    agent_kind: str = "opencode",
    check_shell_time: bool = False,
):
    if os.environ.get("HERDR_ENV") != "1":
        raise UserError("Run this probe from a Herdr-managed pane.")
    profile = Profile.from_dict(
        {
            "runtime_arn": runtime_arn,
            "aws_profile": aws_profile,
            "command": ["/app/run.sh"],
            "agent_kind": agent_kind,
        }
    )
    if connection_file:
        spec = decode_descriptor(json.loads(connection_file.read_text()))
        if spec.runtime_arn != runtime_arn:
            raise UserError("The descriptor ARN does not match the requested test runtime.")
        profile = Profile.from_dict({**asdict(spec), "aws_profile": aws_profile})
    transport = AgentCoreTransport(profile)
    kind = profile.agent_kind
    if kind not in {"opencode", "codex"}:
        raise UserError("Select a recognition kind supported by this E2E probe.")
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
            store.save_profile(
                "not-selected",
                Profile.from_dict(
                    {
                        "runtime_arn": runtime_arn,
                        "aws_profile": aws_profile,
                        "command": ["/bin/false"],
                    }
                ),
            )
            workspace = herdr.result(
                "workspace", "create", "--cwd", temp, "--label", "AgentCore live smoke", "--focus"
            )
            print(
                f"Created isolated workspace: {workspace['workspace']['workspace_id']}", flush=True
            )
            pane = herdr.action_pane("new")
            record = until(lambda: next(iter(store.connections()), None), "connection record", 15)
            if record["profile_name"] != "live-smoke":
                raise UserError("New-agent action did not use the configured default profile.")
            print(
                "PASS: started the default profile without a picker or terminal input", flush=True
            )
            print(f"Fresh test runtime session: {record['runtime_session_id']}", flush=True)
            until(lambda: store.load(record["id"])["status"] == "connected", "AgentCore connection")
            agent = until(lambda: herdr.agent(pane), f"{kind} recognized by Herdr")
            print("Herdr agent recognition: " + json.dumps(agent), flush=True)
            if agent.get("agent") != kind:
                raise UserError("Herdr recognized a different assistant than the declared kind.")

            def ready():
                state = herdr.agent(pane) or {}
                screen = herdr.read(pane)
                check_prompt_screen(screen)
                if state.get("agent_status") == "blocked":
                    raise UserError(
                        "Assistant startup requires user input; no dialog was approved."
                    )
                return input_widget_ready(kind, screen)

            until(ready, f"{kind} input widget")
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
            screen = herdr.read(pane)
            check_prompt_screen(screen)
            print(f"{kind} screen:\n" + screen, flush=True)
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
            if check_runtime_role:
                check_runtime_role_environment(profile, record, expect_shim=False)
            print("Completed screen:\n" + herdr.read(pane), flush=True)
            herdr.call("pane", "send-text", pane, "\x1dd")
            until(lambda: store.load(record["id"])["status"] == "detached", "connector detach", 15)
            until(
                lambda: all(p["pane_id"] != pane for p in herdr.panes()),
                "detached pane closed before opening the next action",
                15,
            )
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
                lambda: re.search(r"RESUMED:\s*HERDR-CLOUD=457", herdr.read(pane)),
                "follow-up model reply",
                60,
            )
            print(
                "PASS: follow-up model turn after reattach retained conversation context",
                flush=True,
            )
            if check_shell_time:
                response = herdr.call(
                    "agent",
                    "prompt",
                    pane,
                    "Use the shell tool to execute exactly: date -u '+%Y-%m-%dT%H:%M:%SZ'. "
                    "Do not estimate the time, run other commands, or change files. "
                    "Reply only with SHELL_TIME= followed by the command output.",
                    "--wait",
                    "--timeout",
                    "90000",
                    check=False,
                    timeout=100,
                )
                if (
                    response.returncode
                    or (herdr.agent(pane) or {}).get("agent_status") == "blocked"
                ):
                    raise UserError("Shell-time prompt failed or needs approval; no input retried.")
                match = until(
                    lambda: re.search(
                        r"SHELL_TIME=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", herdr.read(pane)
                    ),
                    "interactive shell-time reply",
                    30,
                )
                print("PASS: Herdr interactive shell-time reply " + match[1], flush=True)
                print("Shell-time screen:\n" + herdr.read(pane), flush=True)
            herdr.call("pane", "send-text", pane, "\x1dd")
            until(lambda: store.load(record["id"])["status"] == "detached", "final detach", 15)
            until(
                lambda: all(p["pane_id"] != pane for p in herdr.panes()),
                "detached pane closed before stop action",
                15,
            )
            pane = herdr.action_pane("stop")
            until(lambda: "Session [" in herdr.read(pane), "stop-session picker", 15)
            herdr.select_first(pane)
            until(lambda: "to stop it:" in herdr.read(pane), "explicit stop confirmation", 15)
            herdr.call("pane", "send-text", pane, record["name"])
            herdr.call("pane", "send-keys", pane, "enter")
            until(lambda: store.load(record["id"])["status"] == "stopped", "runtime stop", 45)
            print("PASS: plugin stop action accepted for its own test runtime session", flush=True)
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
    parser.add_argument("--connection-file", type=Path)
    parser.add_argument(
        "--agent-kind",
        choices=["opencode", "codex"],
        default="opencode",
        help="UI test driver when a descriptor is not supplied",
    )
    parser.add_argument(
        "--check-runtime-role",
        action="store_true",
        help="Verify the owned runtime's role environment without adding a compatibility shim",
    )
    parser.add_argument(
        "--check-shell-time",
        action="store_true",
        help="Request a read-only date command after the attachment checks",
    )
    args = parser.parse_args()
    try:
        run(
            args.runtime_arn,
            args.aws_profile,
            args.connection_file,
            args.check_runtime_role,
            args.agent_kind,
            args.check_shell_time,
        )
    except Exception as exc:
        message = str(exc) if isinstance(exc, UserError) else type(exc).__name__
        print(f"FAIL: {message}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
