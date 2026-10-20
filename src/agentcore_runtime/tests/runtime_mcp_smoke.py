"""Verify generic locked MCP startup with a disposable, network-free test package."""

import argparse
import base64
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

SERVER = """import json,sys,agentcore_mcp_probe
for line in sys.stdin:
    request=json.loads(line)
    if "id" not in request: continue
    method=request["method"]
    if method=="initialize":
        result={"protocolVersion":request["params"]["protocolVersion"],
                "capabilities":{"tools":{}},"serverInfo":{"name":"probe","version":"1.0"}}
    elif method=="tools/list":
        result={"tools":[{"name":"echo","description":"Return the supplied text",
                "inputSchema":{"type":"object","properties":{"text":{"type":"string"}},
                "required":["text"]}}]}
    elif method=="tools/call":
        text=agentcore_mcp_probe.echo(request["params"]["arguments"]["text"])
        result={"content":[{"type":"text","text":text}]}
    else: result={}
    print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}),flush=True)
"""


def make_test_wheel(project):
    wheel = "agentcore_mcp_probe-1.0.0-py3-none-any.whl"
    info = "agentcore_mcp_probe-1.0.0.dist-info"
    files = {
        "agentcore_mcp_probe.py": b"def echo(text): return text\n",
        f"{info}/METADATA": b"Metadata-Version: 2.1\nName: agentcore-mcp-probe\nVersion: 1.0.0\n",
        f"{info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    records = []
    for name, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        records.append(f"{name},sha256={digest},{len(content)}\n")
    files[f"{info}/RECORD"] = ("".join(records) + f"{info}/RECORD,,\n").encode()
    with zipfile.ZipFile(project / wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return wheel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--model-turn", action="store_true")
    parser.add_argument("--native", choices=("opencode", "codex"), default="opencode")
    args = parser.parse_args()
    sys.path.insert(0, "/usr/local/lib/herdr-agentcore")
    from runtime import inherit_settings, prepare_tool_directories, tool_environment

    settings = inherit_settings(
        dict(os.environ),
        Path("/proc/1/environ").read_bytes(),
        ("AGENTCORE_REQUIRED_MOUNT", "AGENTCORE_PROFILE_DIRECTORY", "AGENTCORE_WORKDIR"),
    )
    env = tool_environment(settings)
    prepare_tool_directories(env)
    project = args.project
    if not args.reuse:
        project.mkdir(parents=True, exist_ok=False)
        wheel = make_test_wheel(project)
        (project / "pyproject.toml").write_text(
            '[project]\nname="mcp-probe"\nversion="0.1.0"\nrequires-python=">=3.13,<3.14"\n'
            'dependencies=["agentcore-mcp-probe==1.0.0"]\n[tool.uv]\npackage=false\n'
            f'[tool.uv.sources]\nagentcore-mcp-probe={{path="{wheel}"}}\n'
        )
        (project / "server.py").write_text(SERVER)
        subprocess.run(
            ["uv", "lock", "--project", str(project), "--python", "python3.13"],
            env=env,
            check=True,
            stdout=sys.stderr,
            timeout=120,
        )
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in project.iterdir()}
    command = [
        "/usr/local/bin/agentcore-mcp",
        "--project",
        str(project),
        "--setup-timeout",
        "90",
        "--",
    ]
    command += ["python", "-u", str(project / "server.py")]
    with tempfile.TemporaryFile(mode="w+t") as logs:
        native = command
        if args.native == "codex":
            native = [
                "codex",
                "sandbox",
                "-P",
                "agentcore-workspace",
                "-C",
                str(project),
                "--",
                *command,
            ]
        process = subprocess.Popen(
            native, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=logs, text=True
        )
        messages = queue.Queue()

        def read_messages():
            for line in process.stdout:
                messages.put(json.loads(line))

        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        sequence = 0

        def call(method, params=None):
            nonlocal sequence
            sequence += 1
            request = {"jsonrpc": "2.0", "id": sequence, "method": method, "params": params or {}}
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            while True:
                response = messages.get(timeout=120)
                if response.get("id") == sequence:
                    assert "error" not in response, response
                    assert not response["result"].get("isError"), response
                    return response["result"]

        try:
            call(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "image-probe", "version": "1.0"},
                },
            )
            process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            process.stdin.flush()
            tools = {tool["name"] for tool in call("tools/list")["tools"]}
            assert tools == {"echo"}
            assert "MCP_OK" in json.dumps(
                call("tools/call", {"name": "echo", "arguments": {"text": "MCP_OK"}})
            )
            print("PASS: initialize, tools/list, and actual MCP calls", flush=True)
        except BaseException:
            logs.seek(0)
            print(logs.read(), file=sys.stderr)
            raise
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            reader.join(timeout=10)
    if args.native == "opencode":
        with tempfile.TemporaryDirectory(prefix="mcp-config-") as temporary:
            config = json.loads(Path("/app/opencode.json").read_text())
            name = "probe"
            config["mcp"] = {name: {"type": "local", "command": command, "timeout": 120000}}
            config["permission"] = {name + "_*": "allow"}
            path = Path(temporary) / "opencode.json"
            path.write_text(json.dumps(config))
            native_env = {
                **env,
                "OPENCODE_CONFIG": str(path),
                "OPENCODE_DISABLE_MODELS_FETCH": "1",
                "AGENTCORE_WORKDIR": env.get("AGENTCORE_PROFILE_DIRECTORY") or temporary,
            }
            result = subprocess.run(
                ["/app/run.sh", "mcp", "list"],
                env=native_env,
                capture_output=True,
                text=True,
                timeout=150,
            )
            assert result.returncode == 0, result.stderr
            assert "connected" in result.stdout.lower(), result.stdout + result.stderr
            print("PASS: fresh OpenCode connected to the registered MCP", flush=True)
            if args.model_turn:
                prompt = (
                    "Call the probe_echo MCP tool once with text MCP_NATIVE_OK. "
                    "Return its result. Do not use other tools or edit files."
                )
                result = subprocess.run(
                    ["/app/run.sh", "run", "--format", "json", prompt],
                    env=native_env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
                events = [
                    json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")
                ]
                used = {
                    event.get("part", {}).get("tool")
                    for event in events
                    if event.get("type") == "tool_use"
                    and event.get("part", {}).get("state", {}).get("status") == "completed"
                }
                assert result.returncode == 0 and "probe_echo" in used, (
                    result.returncode,
                    used,
                    [event.get("type") for event in events],
                    [
                        event.get("error", {}).get("name")
                        for event in events
                        if event.get("type") == "error"
                    ],
                    [
                        event.get("part", {}).get("text", "")[:400]
                        for event in events
                        if event.get("type") == "text"
                    ],
                    result.stderr,
                )
                print("PASS: native OpenCode called the disposable MCP tool", flush=True)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in project.iterdir()}
    assert before == after, "MCP startup changed persistent tool definitions"
    print("PASS: persistent definitions unchanged; local environments are disposable", flush=True)


if __name__ == "__main__":
    main()
