"""Use only public Herdr plugin and pane APIs."""

from __future__ import annotations

import json
import os
import subprocess

from .storage import UserError, profile_name

PLUGIN_ID = "agentcore"
PROFILE_ENV = "HERDR_AGENTCORE_PROFILE"


def command(*args: str, timeout: float = 10, expect_json: bool = True) -> dict:
    if os.environ.get("HERDR_ENV") != "1":
        raise UserError("Run this action inside Herdr.")
    binary = os.environ.get("HERDR_BIN_PATH", "herdr")
    result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise UserError(result.stderr.strip() or result.stdout.strip() or "Herdr command failed.")
    if not expect_json:
        return {}
    try:
        reply = json.loads(result.stdout)
    except ValueError as exc:
        raise UserError("Herdr returned an invalid JSON response.") from exc
    if not isinstance(reply, dict) or "result" not in reply or "error" in reply:
        error = reply.get("error") if isinstance(reply, dict) else None
        raise UserError(str(error or "Herdr returned an invalid success response."))
    return reply


def open_action(entrypoint: str, profile: str | None = None) -> dict:
    if entrypoint not in {"new", "attach", "setup", "sessions", "stop"}:
        raise UserError("Unknown plugin action.")
    if profile is not None and entrypoint != "new":
        raise UserError("--profile is only supported for new-agent actions.")
    try:
        context = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    except ValueError as exc:
        raise UserError("Invalid Herdr invocation context.") from exc
    target = context.get("focused_pane_id") or os.environ.get("HERDR_PANE_ID")
    args = ["plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", entrypoint]
    if target:
        args += ["--placement", "split", "--target-pane", target, "--direction", "right"]
    elif context.get("workspace_id"):
        args += ["--placement", "tab", "--workspace", context["workspace_id"]]
    else:
        raise UserError("Open a Herdr workspace before invoking AgentCore actions.")
    if entrypoint == "new":
        selected = profile if profile is not None else os.environ.get(PROFILE_ENV)
        if selected is not None:
            # The server launches the pane, so explicitly forward the caller's
            # override instead of relying on the daemon's launch environment.
            args += ["--env", f"{PROFILE_ENV}={profile_name(selected)}"]
    return command(*args)


def report_connection(identifier: str, status: str) -> None:
    """Display transport state without taking over OpenCode lifecycle detection."""
    pane = os.environ.get("HERDR_PANE_ID")
    if not pane or os.environ.get("HERDR_ENV") != "1":
        return
    try:
        command(
            "pane",
            "report-metadata",
            pane,
            "--source",
            "agentcore:connector",
            "--token",
            f"cloud={status}",
            "--token",
            f"connection={identifier[:8]}",
            timeout=2,
            expect_json=False,
        )
    except (OSError, UserError, subprocess.TimeoutExpired):
        pass
