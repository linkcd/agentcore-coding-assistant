"""Opt-in cloud Codex tool probe. Use only a fresh disposable runtime session."""

import argparse
import shlex
import uuid

import boto3
from agentcore_contract import ConnectionSpec, UserError
from botocore.config import Config


def remote_script() -> str:
    return r'''
import json, re, subprocess, tempfile, tomllib
from pathlib import Path

config_path = Path.home()/'.codex/config.toml'
config = tomllib.loads(config_path.read_text())
assert config_path.stat().st_mode & 0o777 == 0o600
with tempfile.TemporaryDirectory(prefix="codex-tool-probe-", dir="/home/agent") as directory:
    root = Path(directory)
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (workspace / ".git/config").write_text("protected")
    (root / "outside").write_text("protected")
    checks = """
import json,os,socket,subprocess
from pathlib import Path
def denied(operation):
    try:
        operation()
        return False
    except OSError:
        return True
stamp = subprocess.check_output(['date','-u','+%Y-%m-%dT%H:%M:%SZ'],text=True).strip()
Path('inside').write_text('ok')
try:
    with socket.socket() as sock:
        sock.settimeout(2)
        network_blocked = sock.connect_ex(('127.0.0.1',8080)) != 0
except PermissionError:
    network_blocked = True
outside = Path.cwd().parent/'outside'
outside_hidden = not outside.exists()
denied(lambda: outside.write_text('sandbox-only'))
result = {
    'date': stamp,
    'workspace_write': Path('inside').read_text() == 'ok',
    'metadata_write_blocked': denied(lambda: Path('.git/config').write_text('unexpected')),
    'outside_host_file_hidden': outside_hidden,
    'containerd_hidden': not Path('/run/containerd').exists(),
    'daemon_hidden': denied(lambda: os.listdir('/tmp/codex-daemon-1000')),
    'network_isolated': network_blocked,
}
print(json.dumps(result))
assert all(value for key,value in result.items() if key != 'date')
"""
    result = subprocess.run(['codex','sandbox','-P',config['default_permissions'],
                             '-C',str(workspace),'--','/usr/local/bin/python3','-c',checks],
                            cwd=workspace,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=45)
    print('SANDBOX_CHECK ' + result.stdout.strip(), flush=True)
    # An unmounted parent can be writable sandbox-local tmpfs. Verify the host file.
    assert (root/'outside').read_text() == 'protected', 'Outside host file was modified'
    print('PASS: outside host file remained unchanged', flush=True)
    if result.returncode:
        print(result.stderr, flush=True)
        raise SystemExit('Native Codex sandbox checks failed')
    prompt = ("Use the shell tool to run exactly: date -u '+%Y-%m-%dT%H:%M:%SZ'. "
              "Do not estimate time. Do not run other commands or edit files. "
              "Return the command output.")
    model = subprocess.run(
        ['/app/run.sh','exec','--skip-git-repo-check','--json','-C',str(workspace),prompt],
        cwd=workspace,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120)
    commands = []
    for line in model.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get('item', {})
        if event.get('type') == 'item.completed' and item.get('type') == 'command_execution':
            commands.append(item)
    assert model.returncode == 0, 'Codex model turn failed'
    assert any(item.get('exit_code') == 0 and 'date' in item.get('command','') and
               re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', item.get('aggregated_output',''))
               for item in commands), 'No successful date tool execution was recorded'
    print('PASS: real Codex model executed date inside its configured sandbox', flush=True)
'''


def run(runtime_arn: str, aws_profile: str | None = None):
    spec = ConnectionSpec.from_dict({"runtime_arn": runtime_arn, "command": ["/app/run.sh"]})
    identifier = str(uuid.uuid4())
    client = boto3.Session(profile_name=aws_profile, region_name=spec.region).client(
        "bedrock-agentcore", config=Config(read_timeout=240)
    )
    try:
        response = client.invoke_agent_runtime_command(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=identifier,
            qualifier=spec.endpoint,
            body={
                "command": shlex.join(["/usr/local/bin/python3", "-c", remote_script()]),
                "timeout": 200,
            },
        )
        code = None
        for event in response["stream"]:
            chunk = event.get("chunk")
            if chunk is None:
                raise UserError("Sandbox probe returned a service error.")
            delta = chunk.get("contentDelta", {})
            for key in ("stdout", "stderr"):
                if delta.get(key):
                    print(delta[key], end="", flush=True)
            if "contentStop" in chunk:
                code = chunk["contentStop"].get("exitCode")
        if code != 0:
            raise UserError("The cloud sandbox probe did not complete successfully.")
    finally:
        client.stop_runtime_session(
            agentRuntimeArn=runtime_arn, runtimeSessionId=identifier, qualifier=spec.endpoint
        )
        print("Stopped own Codex sandbox probe session", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--aws-profile")
    args = parser.parse_args()
    try:
        run(args.runtime_arn, args.aws_profile)
    except Exception as exc:
        message = str(exc) if isinstance(exc, UserError) else type(exc).__name__
        print(f"FAIL: {message}", flush=True)
        raise SystemExit(1) from None
