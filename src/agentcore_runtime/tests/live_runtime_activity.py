"""Opt-in activity probe on a fresh AgentCore session, always stopped in cleanup.

Requires command-invocation and stop permissions. --model-turn additionally
uses the runtime's configured model to test a real question/wait/reply cycle.
Never target an existing work session or alter the deployed HTTP health process.
"""

import argparse
import shlex
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from runtime_connection import UserError, runtime_target


def run(runtime_arn: str, aws_profile: str | None, model_turn: bool):
    profile = runtime_target(runtime_arn)
    record = {"runtime_session_id": str(uuid.uuid4())}
    script = Path(__file__).with_name("runtime_activity_smoke.py").read_text()
    command = ["/usr/local/bin/python3", "-c", script, "--existing-health-server"]
    if model_turn:
        command.append("--model-turn")
    client = boto3.Session(profile_name=aws_profile, region_name=profile.region).client(
        "bedrock-agentcore", config=Config(read_timeout=210)
    )
    print(f"Fresh activity-test session: {record['runtime_session_id']}", flush=True)
    try:
        response = client.invoke_agent_runtime_command(
            agentRuntimeArn=profile.runtime_arn,
            runtimeSessionId=record["runtime_session_id"],
            qualifier=profile.endpoint,
            body={"command": shlex.join(command), "timeout": 180},
        )
        exit_code = None
        for event in response["stream"]:
            if "chunk" not in event:
                raise UserError("Runtime activity command returned a service error.")
            chunk = event["chunk"]
            delta = chunk.get("contentDelta", {})
            for key in ("stdout", "stderr"):
                if delta.get(key):
                    print(delta[key], end="", flush=True)
            if "contentStop" in chunk:
                exit_code = chunk["contentStop"].get("exitCode")
        if exit_code != 0:
            raise UserError("Runtime activity command did not complete successfully.")
    finally:
        client.stop_runtime_session(
            agentRuntimeArn=profile.runtime_arn,
            runtimeSessionId=record["runtime_session_id"],
            qualifier=profile.endpoint,
        )
        print("Stopped own activity-test runtime session", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--aws-profile")
    parser.add_argument("--model-turn", action="store_true")
    args = parser.parse_args()
    run(args.runtime_arn, args.aws_profile, args.model_turn)


if __name__ == "__main__":
    main()
