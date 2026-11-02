"""Preload OpenCode's plugin dependencies while building the image."""

import os
import subprocess

from run import launch_arguments, launch_environment
from runtime import prepare_tool_directories, tool_environment

env = tool_environment(
    launch_environment(
        {
            **os.environ,
            "AWS_REGION": "us-west-2",
            "BEDROCK_MODEL_ID": "global.moonshotai.kimi-k3",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
        },
        b"",
    )
)
prepare_tool_directories(env)
subprocess.run(
    launch_arguments(env, ["debug", "config"]), env=env, stdout=subprocess.DEVNULL, check=True
)
