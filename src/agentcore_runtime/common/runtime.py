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
        env = adapter.launch_environment(dict(os.environ), container)
        argv = adapter.launch_arguments(env, sys.argv[1:])
        os.chdir(env.get(adapter.WORKDIR_SETTING) or env.get("HOME", "/home/agent"))
        os.execvpe(argv[0], argv, env)
    except (ValueError, OSError) as exc:
        print(f"Runtime startup: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
