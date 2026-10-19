"""Start Codex with its native Bedrock provider and runtime-role credentials."""

import json

if __package__:
    from ..common.runtime import inherit_settings, launch
else:
    from runtime import inherit_settings, launch

SETTINGS = ("AWS_REGION", "BEDROCK_INFERENCE_REGION", "BEDROCK_MODEL_ID", "BEDROCK_ENDPOINT_TYPE")
PROVIDERS = {
    "runtime": "amazon-bedrock-runtime",
    "mantle": "amazon-bedrock",
}


def launch_environment(current: dict[str, str], container: bytes) -> dict[str, str]:
    env = inherit_settings(current, container, SETTINGS)
    if not env.get("BEDROCK_INFERENCE_REGION") or not env.get("BEDROCK_MODEL_ID"):
        raise ValueError("The runtime must define BEDROCK_INFERENCE_REGION and BEDROCK_MODEL_ID.")
    env.setdefault("BEDROCK_ENDPOINT_TYPE", "runtime")
    if env.get("BEDROCK_ENDPOINT_TYPE") not in PROVIDERS:
        raise ValueError('BEDROCK_ENDPOINT_TYPE must be "runtime" or "mantle".')
    return env


def launch_arguments(env: dict[str, str], arguments: list[str]) -> list[str]:
    provider = PROVIDERS[env["BEDROCK_ENDPOINT_TYPE"]]
    return [
        "codex",
        "--config",
        "model_provider=" + json.dumps(provider),
        "--config",
        f"model_providers.{provider}.aws.region=" + json.dumps(env["BEDROCK_INFERENCE_REGION"]),
        # Runtime has no hosted web-search tool. Keep Mantle's native setting.
        *(
            ["--config", 'web_search="disabled"']
            if env["BEDROCK_ENDPOINT_TYPE"] == "runtime"
            else []
        ),
        "--model",
        env["BEDROCK_MODEL_ID"],
        *arguments,
    ]


def main():
    launch(launch_environment, launch_arguments)


if __name__ == "__main__":
    main()
