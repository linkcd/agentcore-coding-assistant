"""Start Codex with its native Bedrock provider and runtime-role credentials."""

import json

if __package__:
    from ...common.runtime import inherit_settings
else:
    from runtime import inherit_settings

SETTINGS = ("AWS_REGION", "BEDROCK_INFERENCE_REGION", "BEDROCK_MODEL_ID", "CODEX_WORKDIR")
WORKDIR_SETTING = "CODEX_WORKDIR"


def launch_environment(current: dict[str, str], container: bytes) -> dict[str, str]:
    env = inherit_settings(current, container, SETTINGS)
    if not env.get("BEDROCK_INFERENCE_REGION") or not env.get("BEDROCK_MODEL_ID"):
        raise ValueError("The runtime must define BEDROCK_INFERENCE_REGION and BEDROCK_MODEL_ID.")
    return env


def launch_arguments(env: dict[str, str], arguments: list[str]) -> list[str]:
    return [
        "codex",
        "--config",
        'model_provider="amazon-bedrock"',
        "--config",
        "model_providers.amazon-bedrock.aws.region=" + json.dumps(env["BEDROCK_INFERENCE_REGION"]),
        "--model",
        env["BEDROCK_MODEL_ID"],
        *arguments,
    ]
