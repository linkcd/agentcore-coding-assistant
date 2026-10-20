#!/usr/local/bin/python3
"""Run a locked Python MCP project with a replaceable local environment."""

import argparse
import fcntl
import hashlib
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__:
    from .runtime import prepare_tool_directories, tool_environment
else:
    from runtime import prepare_tool_directories, tool_environment


def environment_key(project: Path, python: Path) -> str:
    digest = hashlib.sha256(str(project).encode() + b"\0" + str(python.resolve()).encode())
    for name in ("pyproject.toml", "uv.lock"):
        digest.update(b"\0" + name.encode() + b"\0" + (project / name).read_bytes())
    return digest.hexdigest()


def bootstrap(
    project: Path, python: str, timeout: float, current: dict[str, str]
) -> dict[str, str]:
    project = project.resolve(strict=True)
    env = tool_environment(current)
    interpreter = shutil.which(python, path=env["PATH"])
    uv = shutil.which("uv", path=env["PATH"])
    if not interpreter or not uv:
        raise ValueError("The requested Python interpreter and uv must be installed.")
    key = environment_key(project, Path(interpreter))
    root = Path(env["AGENTCORE_TOOL_ROOT"])
    environment = root / "environments/mcp" / key
    if environment.resolve().is_relative_to(project):
        raise ValueError("The MCP environment must be outside its persistent tool project.")
    # Each lockfile generation owns a different environment. A new definition cannot
    # mutate the dependencies of an already-running server using an older generation.
    env["UV_PROJECT_ENVIRONMENT"] = str(environment)
    env["UV_PYTHON_DOWNLOADS"] = "never"
    env.pop("VIRTUAL_ENV", None)
    prepare_tool_directories(env)
    locks = root / "locks"
    locks.mkdir(mode=0o700, parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with (locks / f"{key}.lock").open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for MCP environment setup.") from None
                time.sleep(0.1)
        ready = environment / ".agentcore-ready"
        if not ready.is_file():
            subprocess.run(
                [
                    uv,
                    "sync",
                    "--locked",
                    "--no-dev",
                    "--no-install-project",
                    "--no-editable",
                    "--project",
                    str(project),
                    "--python",
                    interpreter,
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=sys.stderr,
                stderr=sys.stderr,
                check=True,
                timeout=max(0.01, deadline - time.monotonic()),
            )
            if environment_key(project, Path(interpreter)) != key:
                raise ValueError(
                    "The MCP definition changed during setup. Retry with a stable lockfile."
                )
            ready.touch()
    env["VIRTUAL_ENV"] = str(environment)
    env["PATH"] = str(environment / "bin") + os.pathsep + env["PATH"]
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--python", default="python3.13")
    parser.add_argument("--setup-timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if (
        not args.project.is_absolute()
        or not command
        or not math.isfinite(args.setup_timeout)
        or args.setup_timeout <= 0
    ):
        parser.error("Use an absolute --project, a positive timeout, and -- COMMAND [ARGS].")
    try:
        env = bootstrap(args.project, args.python, args.setup_timeout, dict(os.environ))
        os.execvpe(command[0], command, env)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"MCP startup: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
