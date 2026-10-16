"""Launch installed OpenCode using the runtime role's SDK credential provider.

No credentials are fetched, serialized, or exported by this launcher. The image
contains no AWS credential/profile files. AWS_PROFILE selects the Node provider
chain in OpenCode 1.18.30; its metadata provider handles role credential refresh.
"""

import os
import sys
from pathlib import Path

# Remote shells may omit deployment environment variables. Copy only these
# non-secret settings from PID 1, never its complete environment.
RUNTIME_SETTINGS = ("AWS_REGION", "AWS_DEFAULT_REGION", "BEDROCK_MODEL_ID", "OPENCODE_WORKDIR")


def launch_environment(current: dict[str, str], container: bytes) -> dict[str, str]:
    env = dict(current)
    settings = dict(item.split(b"=", 1) for item in container.split(b"\0") if b"=" in item)
    for key in RUNTIME_SETTINGS:
        if not env.get(key) and key.encode() in settings:
            env[key] = settings[key.encode()].decode()
    region = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION")
    if not region or not env.get("BEDROCK_MODEL_ID"):
        raise ValueError("The runtime must configure AWS_REGION and BEDROCK_MODEL_ID.")
    env["AWS_REGION"] = region
    env.setdefault("AWS_DEFAULT_REGION", region)
    env["AWS_PROFILE"] = "default"
    # Upgrade checks read global config, not the runtime's OPENCODE_CONFIG.
    # Keep the image's pinned executable stable even on a fresh remote shell.
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env.setdefault("OPENCODE_CONFIG", "/app/opencode.json")
    return env


def main():
    try:
        container = Path("/proc/1/environ").read_bytes()
    except OSError:
        container = b""
    try:
        env = launch_environment(dict(os.environ), container)
        os.chdir(env.get("OPENCODE_WORKDIR") or env.get("HOME", "/home/agent"))
        # Forward native CLI arguments, including --session, without treating
        # them as a prompt or bypassing OpenCode's normal tool permissions.
        os.execvpe("opencode", ["opencode", *sys.argv[1:]], env)
    except (ValueError, OSError) as exc:
        print(f"OpenCode runtime: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
