"""Shared startup helpers used by each image's run.py entrypoint."""

import hashlib
import os
import sys
from pathlib import Path

TOOL_DIRECTORIES = (
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR",
    "TMPDIR",
    "UV_CACHE_DIR",
    "UV_TOOL_DIR",
    "UV_TOOL_BIN_DIR",
    "UV_PYTHON_INSTALL_DIR",
    "PIP_CACHE_DIR",
    "npm_config_cache",
    "npm_config_prefix",
    "PNPM_CONFIG_STORE_DIR",
    "PNPM_HOME",
    "CARGO_HOME",
    "GOPATH",
    "GOBIN",
    "GOCACHE",
    "GOMODCACHE",
)


def tool_environment(current: dict[str, str]) -> dict[str, str]:
    """Expose image tools and keep disposable installs off the coding filesystem."""
    env = dict(current)
    home = Path(env.get("HOME") or "/home/agent")
    root = Path(env.get("AGENTCORE_TOOL_ROOT") or "/tmp/agentcore")
    if not home.is_absolute() or not root.is_absolute():
        raise ValueError("HOME and AGENTCORE_TOOL_ROOT must be absolute paths.")
    env["HOME"], env["AGENTCORE_TOOL_ROOT"] = str(home), str(root)
    defaults = {
        "XDG_CACHE_HOME": root / "cache",
        "XDG_RUNTIME_DIR": root / "run",
        "TMPDIR": root / "tmp",
        "UV_CACHE_DIR": root / "cache/uv",
        "UV_TOOL_DIR": root / "tools/uv",
        "UV_TOOL_BIN_DIR": home / ".local/bin",
        "UV_PYTHON_INSTALL_DIR": root / "tools/python",
        "UV_LINK_MODE": "copy",
        "PIP_CACHE_DIR": root / "cache/pip",
        "npm_config_cache": root / "cache/npm",
        "npm_config_prefix": home / ".local",
        "PNPM_CONFIG_STORE_DIR": root / "cache/pnpm",
        "PNPM_HOME": home / ".local/share/pnpm",
        "CARGO_HOME": root / "tools/cargo",
        "GOROOT": "/usr/local/go",
        "GOPATH": root / "tools/go",
        "GOBIN": home / ".local/bin",
        "GOCACHE": root / "cache/go-build",
        "GOMODCACHE": root / "cache/go-mod",
    }
    workdir = Path(env.get("AGENTCORE_WORKDIR") or home).resolve()
    key = hashlib.sha256(str(workdir).encode()).hexdigest()[:24]
    defaults["UV_PROJECT_ENVIRONMENT"] = root / "environments/projects" / key
    defaults["CARGO_TARGET_DIR"] = root / "build" / key / "rust"
    for name, value in defaults.items():
        if not env.get(name):
            env[name] = str(value)
    paths = [
        "/usr/local/bin",
        str(home / ".local/bin"),
        env["UV_TOOL_BIN_DIR"],
        str(Path(env["npm_config_prefix"]) / "bin"),
        env["PNPM_HOME"],
        str(Path(env["CARGO_HOME"]) / "bin"),
        env["GOBIN"],
        "/usr/local/sbin",
        "/usr/bin",
        "/usr/sbin",
        "/bin",
        "/sbin",
    ]
    # Keep custom paths (including an activated venv) ahead of repaired standard paths.
    custom = [
        entry for entry in env.get("PATH", "").split(os.pathsep) if entry and entry not in paths
    ]
    env["PATH"] = os.pathsep.join(dict.fromkeys([*custom, *paths]))
    return env


def prepare_tool_directories(env: dict[str, str]) -> None:
    """Create writable tool directories without creating a project virtual environment."""
    for name in TOOL_DIRECTORIES:
        Path(env[name]).mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("UV_PROJECT_ENVIRONMENT", "CARGO_TARGET_DIR"):
        Path(env[name]).parent.mkdir(mode=0o700, parents=True, exist_ok=True)


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


def prepare_profile_directory(env: dict[str, str]) -> None:
    """Use the dedicated access-point root without creating another profile directory."""
    selected = env.get("AGENTCORE_PROFILE_DIRECTORY")
    if not selected:
        return
    mount_value = env.get("AGENTCORE_REQUIRED_MOUNT")
    if not mount_value or not Path(mount_value).is_mount():
        raise ValueError("The profile requires its configured filesystem mount.")
    mount = Path(mount_value).resolve()
    profile = Path(selected)
    if not profile.is_absolute() or profile != mount or profile.resolve() != mount:
        raise ValueError("The profile directory must be the dedicated access-point mount root.")
    working = Path(env.get("AGENTCORE_WORKDIR") or selected)
    if not working.is_absolute() or not working.resolve().is_relative_to(mount):
        raise ValueError("The working directory must be inside this profile's directory.")
    if not env.get("AGENTCORE_WORKDIR"):
        env["AGENTCORE_WORKDIR"] = selected


def launch(prepare_environment, build_arguments):
    try:
        container = Path("/proc/1/environ").read_bytes()
    except OSError:
        container = b""
    try:
        current = inherit_settings(
            dict(os.environ),
            container,
            ("AGENTCORE_REQUIRED_MOUNT", "AGENTCORE_WORKDIR", "AGENTCORE_PROFILE_DIRECTORY"),
        )
        env = prepare_environment(current, container)
        required_mount = env.get("AGENTCORE_REQUIRED_MOUNT")
        if required_mount and not Path(required_mount).is_mount():
            raise ValueError("The configured runtime filesystem is not mounted.")
        prepare_profile_directory(env)
        env = tool_environment(env)
        prepare_tool_directories(env)
        argv = build_arguments(env, sys.argv[1:])
        os.chdir(env.get("AGENTCORE_WORKDIR") or env.get("HOME", "/home/agent"))
        os.execvpe(argv[0], argv, env)
    except (ValueError, OSError) as exc:
        print(f"Runtime startup: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
