"""Preload OpenCode's plugin dependencies while building the image."""

import os
import subprocess

from run import launch_arguments, launch_environment

env = launch_environment(
    {
        **os.environ,
        "AWS_REGION": "us-west-2",
        "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
    },
    b"",
)
subprocess.run(
    launch_arguments(env, ["debug", "config"]), env=env, stdout=subprocess.DEVNULL, check=True
)
