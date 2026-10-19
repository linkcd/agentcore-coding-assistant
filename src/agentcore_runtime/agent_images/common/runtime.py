"""Shared startup operations. Assistant adapters supply environment and argv."""

import os
import sys
from pathlib import Path


def inherit_settings(
    current: dict[str, str], container: bytes, names: tuple[str, ...]
) -> dict[str, str]:
    """Copy only declared non-secret PID 1 settings when the shell omits them."""
    env = dict(current)
    settings = dict(item.split(b"=", 1) for item in container.split(b"\0") if b"=" in item)
    for name in names:
        if not env.get(name) and name.encode() in settings:
            env[name] = settings[name.encode()].decode()
    return env


def launch(adapter):
    try:
        container = Path("/proc/1/environ").read_bytes()
    except OSError:
        container = b""
    try:
        current = inherit_settings(
            dict(os.environ), container, ("AGENTCORE_REQUIRED_MOUNT", "AGENTCORE_WORKDIR")
        )
        env = adapter.launch_environment(current, container)
        required_mount = env.get("AGENTCORE_REQUIRED_MOUNT")
        if required_mount and not Path(required_mount).is_mount():
            raise ValueError("The configured runtime filesystem is not mounted.")
        argv = adapter.launch_arguments(env, sys.argv[1:])
        os.chdir(env.get("AGENTCORE_WORKDIR") or env.get("HOME", "/home/agent"))
        os.execvpe(argv[0], argv, env)
    except (ValueError, OSError) as exc:
        print(f"Runtime startup: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
