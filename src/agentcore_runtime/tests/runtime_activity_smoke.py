"""Run inside the built image: real OpenCode events -> real /ping, without AWS.

The container is network-isolated. OpenCode's native shell API supplies controlled
work instead of a model call. All processes and scratch state are disposable.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def request(path, body=None, *, port=4096, timeout=40):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def wait_for(operation, label, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if result := operation():
                return result
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {label}")


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def main(*, existing_health_server=False, model_turn=False):
    with tempfile.TemporaryFile(mode="w+t") as logs:
        health = (
            None
            if existing_health_server
            else subprocess.Popen(
                [sys.executable, "/app/healthcheck.py"],
                stdout=logs,
                stderr=logs,
                start_new_session=True,
            )
        )
        opencode = subprocess.Popen(
            [
                "/app/run.sh",
                "--print-logs",
                "--log-level",
                "DEBUG",
                "serve",
                "--hostname",
                "127.0.0.1",
                "--port",
                "4096",
            ],
            stdout=logs,
            stderr=logs,
            start_new_session=True,
        )
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            wait_for(lambda: request("/global/health", timeout=1), "OpenCode server")
            session = request("/session", {"title": "Activity smoke"})["id"]

            def ping():
                return request("/ping", port=8080)

            assert ping() == {"status": "Healthy"}  # Process exists, but is idle.
            work = pool.submit(
                request, f"/session/{session}/shell", {"agent": "build", "command": "sleep 3"}
            )
            wait_for(lambda: ping() == {"status": "HealthyBusy"}, "busy shell work", timeout=10)
            assert ping() == {"status": "HealthyBusy"}  # No advancing AWS timestamp.
            work.result(timeout=30)
            wait_for(lambda: ping() == {"status": "Healthy"}, "completed work", timeout=10)
            assert opencode.poll() is None

            if model_turn:
                work = pool.submit(
                    request,
                    f"/session/{session}/message",
                    {
                        "agent": "build",
                        "parts": [
                            {
                                "type": "text",
                                "text": (
                                    "This is a health-reporting test. Use the question tool "
                                    "to ask me 'Continue the activity test?' with the options "
                                    "Continue and Stop. "
                                    "Wait for my answer. After I answer, reply only ACTIVITY_OK. "
                                    "Do not use any other tools or change any files."
                                ),
                            }
                        ],
                    },
                )
                wait_for(
                    lambda: ping() == {"status": "HealthyBusy"}, "model generation", timeout=20
                )
                question = wait_for(
                    lambda: next(
                        (q for q in request("/question") if q["sessionID"] == session), None
                    ),
                    "model question",
                    timeout=30,
                )
                wait_for(lambda: ping() == {"status": "Healthy"}, "waiting for user", timeout=10)
                assert not work.done()
                assert len(question["questions"]) == 1
                labels = {option["label"] for option in question["questions"][0]["options"]}
                assert {"Continue", "Stop"} <= labels
                time.sleep(2)
                assert ping() == {"status": "Healthy"}
                request(f"/question/{question['id']}/reply", {"answers": [["Continue"]]})
                wait_for(
                    lambda: ping() == {"status": "HealthyBusy"}, "resumed generation", timeout=10
                )
                response = work.result(timeout=30)
                text = "".join(p.get("text", "") for p in response["parts"] if p["type"] == "text")
                assert "ACTIVITY_OK" in text
                wait_for(lambda: ping() == {"status": "Healthy"}, "model completion", timeout=10)
                print("PASS: Bedrock busy -> question waiting/idle -> reply/busy -> complete/idle")

            work = pool.submit(
                request, f"/session/{session}/shell", {"agent": "build", "command": "sleep 30"}
            )
            wait_for(lambda: ping() == {"status": "HealthyBusy"}, "second work", timeout=10)
            stop(opencode)
            wait_for(lambda: ping() == {"status": "Healthy"}, "crashed process", timeout=10)
            print("PASS: real OpenCode idle -> busy -> idle; process death clears busy state")
        except BaseException:
            logs.seek(0)
            print(logs.read(), file=sys.stderr)
            raise
        finally:
            stop(opencode)
            if health is not None:
                stop(health)
            pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-health-server", action="store_true")
    parser.add_argument("--model-turn", action="store_true", help="Makes a real model call")
    args = parser.parse_args()
    main(existing_health_server=args.existing_health_server, model_turn=args.model_turn)
