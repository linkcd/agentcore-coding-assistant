"""Check deployed tools and generic MCP recovery using only disposable sessions."""

import argparse
import hashlib
import shlex
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from runtime_connection import UserError, runtime_target


def run(runtime_arn, native, persistent_root=None):
    spec = runtime_target(runtime_arn)
    tests = Path(__file__).parent
    common = tests.parent / "agent_images/common"
    source_hashes = {
        target: hashlib.sha256((common / source).read_bytes()).hexdigest()
        for target, source in {
            "/app/run.sh": "run.sh",
            "/app/runtime.py": "runtime.py",
            "/usr/local/lib/herdr-agentcore/runtime.py": "runtime.py",
            "/usr/local/lib/herdr-agentcore/mcp_run.py": "mcp_run.py",
            "/usr/local/bin/uvx": "uvx.sh",
        }.items()
    }
    tools = (tests / "runtime_tools_smoke.py").read_text()
    mcp = (tests / "runtime_mcp_smoke.py").read_text()
    client = boto3.Session(region_name=spec.region).client(
        "bedrock-agentcore", config=Config(read_timeout=360)
    )

    def invoke(code):
        identifier = str(uuid.uuid4())
        try:
            response = client.invoke_agent_runtime_command(
                agentRuntimeArn=runtime_arn,
                runtimeSessionId=identifier,
                qualifier=spec.endpoint,
                body={
                    "command": shlex.join(["/usr/local/bin/python3", "-c", code]),
                    "timeout": 300,
                },
            )
            exit_code = None
            for event in response["stream"]:
                chunk = event.get("chunk")
                if chunk is None:
                    raise UserError("Tool probe returned a service error.")
                for key in ("stdout", "stderr"):
                    content = chunk.get("contentDelta", {}).get(key)
                    if content:
                        print(content, end="", flush=True)
                if "contentStop" in chunk:
                    exit_code = chunk["contentStop"].get("exitCode")
            if exit_code != 0:
                raise UserError("Deployed tool probe did not complete successfully.")
        finally:
            client.stop_runtime_session(
                agentRuntimeArn=runtime_arn, runtimeSessionId=identifier, qualifier=spec.endpoint
            )
            print("Stop requested for own tool-probe session", flush=True)

    project = str(Path(persistent_root or "/home/agent") / (".tool-probe-" + uuid.uuid4().hex))
    arguments = ["mcp-probe", "--project", project, "--native", native]
    if native == "opencode":
        arguments.append("--model-turn")
    code = f"""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
sys.tracebacklimit=0
sys.path.insert(0,'/app')
from runtime import tool_environment,prepare_tool_directories
for target,expected in {source_hashes!r}.items():
    assert hashlib.sha256(Path(target).read_bytes()).hexdigest()==expected, target
print('PASS: deployed launcher and tool-helper source hashes',flush=True)
env=tool_environment({{**os.environ,'PATH':'/usr/bin:/bin'}})
prepare_tool_directories(env)
with tempfile.TemporaryDirectory(dir='/home/agent') as work:
    command=['/usr/local/bin/python3','-c',{tools!r}]
    if {native!r}=='codex':
        command=['codex','sandbox','-P','agentcore-workspace','-C',work,'--',*command]
    subprocess.run(command,env=env,cwd=work,check=True)
sys.argv={arguments!r}
exec({mcp!r})
"""
    try:
        invoke(code)
        if persistent_root:
            arguments = ["mcp-probe", "--project", project, "--native", native, "--reuse"]
            invoke(f"import sys\nsys.tracebacklimit=0\nsys.argv={arguments!r}\nexec({mcp!r})")
            print(
                "PASS: second runtime rebuilt the MCP from the same persistent definitions",
                flush=True,
            )
    finally:
        if persistent_root:
            # Only these uniquely named probe files are ours. Never recurse through the mount.
            cleanup = f"""
from pathlib import Path
project=Path({project!r})
if project.exists():
    for name in ['pyproject.toml','uv.lock','server.py',
                 'agentcore_mcp_probe-1.0.0-py3-none-any.whl']:
        (project/name).unlink(missing_ok=True)
    project.rmdir()
print('PASS: removed only the persistent tool-probe files')
"""
            invoke(cleanup)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--native", choices=("opencode", "codex"), required=True)
    parser.add_argument("--persistent-root", type=Path)
    args = parser.parse_args()
    if args.persistent_root and not args.persistent_root.is_absolute():
        parser.error("--persistent-root must be an absolute mounted path")
    try:
        run(args.runtime_arn, args.native, args.persistent_root)
    except Exception as exc:
        print(str(exc) if isinstance(exc, UserError) else type(exc).__name__)
        raise SystemExit(1) from None
