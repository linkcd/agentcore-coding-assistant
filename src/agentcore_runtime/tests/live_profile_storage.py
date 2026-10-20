"""Verify an empty profile root using fresh sessions; remove only the probe's file."""

import argparse
import hashlib
import shlex
import uuid
from pathlib import PurePosixPath

import boto3
from agentcore_contract import ConnectionSpec, UserError
from botocore.config import Config


def run(runtime_arn: str, mount_path: str) -> None:
    spec = ConnectionSpec.from_dict({"runtime_arn": runtime_arn, "command": ["/app/run.sh"]})
    client = boto3.Session(region_name=spec.region).client(
        "bedrock-agentcore", config=Config(read_timeout=240)
    )
    filename = ".profile-storage-probe-" + uuid.uuid4().hex
    content = uuid.uuid4().hex.encode() * 128
    digest = hashlib.sha256(content).hexdigest()

    def invoke(code: str) -> None:
        identifier = str(uuid.uuid4())
        try:
            response = client.invoke_agent_runtime_command(
                agentRuntimeArn=runtime_arn,
                runtimeSessionId=identifier,
                qualifier=spec.endpoint,
                body={
                    "command": shlex.join(["/usr/local/bin/python3", "-c", code]),
                    "timeout": 180,
                },
            )
            exit_code = None
            for event in response["stream"]:
                chunk = event.get("chunk")
                if chunk is None:
                    raise UserError("Storage probe returned a service error.")
                for key in ("stdout", "stderr"):
                    text = chunk.get("contentDelta", {}).get(key)
                    if text:
                        print(text, end="", flush=True)
                if "contentStop" in chunk:
                    exit_code = chunk["contentStop"].get("exitCode")
            if exit_code != 0:
                raise UserError("Storage probe did not complete successfully.")
        finally:
            client.stop_runtime_session(
                agentRuntimeArn=runtime_arn,
                runtimeSessionId=identifier,
                qualifier=spec.endpoint,
            )
            print("Stop requested for own storage-probe session", flush=True)

    preamble = f"""
import hashlib,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/app')
from runtime import inherit_settings
mount=Path({mount_path!r})
settings=inherit_settings(dict(os.environ),Path('/proc/1/environ').read_bytes(),
    ('AGENTCORE_REQUIRED_MOUNT','AGENTCORE_PROFILE_DIRECTORY','AGENTCORE_WORKDIR'))
root=Path(settings['AGENTCORE_PROFILE_DIRECTORY'])
assert root==mount, 'Expected the profile directory to be the access-point mount root'
probe=root/{filename!r}
assert mount.is_mount(), 'Expected configured filesystem mount'
assert os.getuid()==1000, 'Probe must use the image agent user'
"""
    cleanup_needed = True
    try:
        invoke(
            preamble
            + f"""
config=subprocess.run(['/app/run.sh','debug','config'],capture_output=True,text=True,timeout=120,check=True)
assert not list(root.iterdir()), 'Expected an empty profile directory'
assert not json.loads(config.stdout).get('mcp'), 'Expected no inherited MCP configuration'
with probe.open('xb') as stream:
    stream.write({content!r})
    stream.flush()
    os.fsync(stream.fileno())
print('PASS: empty mounted profile root, non-root write, and no inherited MCP servers',flush=True)
"""
        )
        invoke(
            preamble
            + f"""
assert hashlib.sha256(probe.read_bytes()).hexdigest()=={digest!r}, 'Cross-session content mismatch'
probe.unlink()
assert not list(root.iterdir()), 'Unexpected files remain in the profile root'
print('PASS: second session read the persisted file; root is empty after probe cleanup',flush=True)
"""
        )
        cleanup_needed = False
    finally:
        if cleanup_needed:
            invoke(
                preamble
                + "probe.unlink(missing_ok=True)\nprint('Removed only the storage-probe file')\n"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--mount-path", required=True)
    args = parser.parse_args()
    if not PurePosixPath(args.mount_path).is_absolute():
        parser.error("--mount-path must be an absolute mounted path")
    try:
        run(args.runtime_arn, args.mount_path)
    except Exception as exc:
        print(str(exc) if isinstance(exc, UserError) else type(exc).__name__)
        raise SystemExit(1) from None
