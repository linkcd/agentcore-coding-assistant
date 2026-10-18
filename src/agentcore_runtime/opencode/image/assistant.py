"""Launch installed OpenCode using the runtime role's SDK credential provider.

No credentials are fetched, serialized, or exported by this launcher. The image
contains no AWS credential/profile files. AWS_PROFILE selects the Node provider
chain in OpenCode 1.18.30; its metadata provider handles role credential refresh.
"""

if __package__:
    from ...common.runtime import inherit_settings
else:
    from runtime import inherit_settings

# Remote shells may omit deployment environment variables. Copy only these
# non-secret settings from PID 1, never its complete environment.
RUNTIME_SETTINGS = ("AWS_REGION", "AWS_DEFAULT_REGION", "BEDROCK_MODEL_ID", "OPENCODE_WORKDIR")
WORKDIR_SETTING = "OPENCODE_WORKDIR"


def launch_environment(current: dict[str, str], container: bytes) -> dict[str, str]:
    env = inherit_settings(current, container, RUNTIME_SETTINGS)
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


def launch_arguments(env: dict[str, str], arguments: list[str]) -> list[str]:
    return ["opencode", *arguments]
