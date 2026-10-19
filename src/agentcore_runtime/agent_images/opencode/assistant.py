"""Launch installed OpenCode using the runtime role's SDK credential provider.

No credentials are fetched, serialized, or exported by this launcher. The image
contains no AWS credential/profile files. AWS_PROFILE selects the Node provider
chain in OpenCode 1.18.30; its metadata provider handles role credential refresh.
"""

import json

if __package__:
    from ..common.runtime import inherit_settings
else:
    from runtime import inherit_settings

# Remote shells may omit deployment environment variables. Copy only these
# non-secret settings from PID 1, never its complete environment.
RUNTIME_SETTINGS = (
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "BEDROCK_MODEL_ID",
    "BEDROCK_INFERENCE_REGION",
    "BEDROCK_ENDPOINT_TYPE",
    "OPENCODE_CONFIG_CONTENT",
)
PROVIDERS = {
    "runtime": "@ai-sdk/amazon-bedrock",
    "mantle": "@ai-sdk/amazon-bedrock/mantle",
}


def endpoint_configuration(env: dict[str, str]) -> str:
    """Select the startup model's native SDK while retaining other JSON settings."""
    try:
        config = json.loads(env.get("OPENCODE_CONFIG_CONTENT") or "{}")
    except ValueError:
        raise ValueError("OPENCODE_CONFIG_CONTENT must contain a JSON object.") from None
    section = config
    for key in ("provider", "amazon-bedrock", "models", env["BEDROCK_MODEL_ID"], "provider"):
        if not isinstance(section, dict):
            raise ValueError("OPENCODE_CONFIG_CONTENT provider/model sections must be objects.")
        section = section.setdefault(key, {})
    if not isinstance(section, dict):
        raise ValueError("OPENCODE_CONFIG_CONTENT model provider must be a JSON object.")
    section["npm"] = PROVIDERS[env["BEDROCK_ENDPOINT_TYPE"]]
    return json.dumps(config)


def launch_environment(current: dict[str, str], container: bytes) -> dict[str, str]:
    env = inherit_settings(current, container, RUNTIME_SETTINGS)
    region = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION")
    if not region or not env.get("BEDROCK_MODEL_ID"):
        raise ValueError("The runtime must configure AWS_REGION and BEDROCK_MODEL_ID.")
    endpoint_type = env.get("BEDROCK_ENDPOINT_TYPE")
    if endpoint_type is not None and endpoint_type not in PROVIDERS:
        raise ValueError('BEDROCK_ENDPOINT_TYPE must be "runtime" or "mantle".')
    env["AWS_REGION"] = region
    env.setdefault("AWS_DEFAULT_REGION", region)
    env["BEDROCK_INFERENCE_REGION"] = env.get("BEDROCK_INFERENCE_REGION") or region
    env["AWS_PROFILE"] = "default"
    # Upgrade checks read global config, not the runtime's OPENCODE_CONFIG.
    # Keep the image's pinned executable stable even on a fresh remote shell.
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env.setdefault("OPENCODE_CONFIG", "/app/opencode.json")
    # Native model metadata selects the route unless a profile explicitly overrides it.
    if endpoint_type is not None:
        env["OPENCODE_CONFIG_CONTENT"] = endpoint_configuration(env)
    return env


def launch_arguments(env: dict[str, str], arguments: list[str]) -> list[str]:
    return ["opencode", *arguments]
