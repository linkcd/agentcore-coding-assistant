"""AgentCore HTTP contract, adapted from awslabs/agentcore-samples (Apache-2.0).

Modified: threaded HTTP handling and activity-aware busy reporting, without
fabricated last-activity timestamps. Maximum compute lifetime still applies.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__:
    from .activity import ACTIVITY_DIRECTORY, health_status
else:
    from activity import ACTIVITY_DIRECTORY, health_status


class Handler(BaseHTTPRequestHandler):
    activity_directory = Path(os.environ.get("HERDR_ACTIVITY_DIR", ACTIVITY_DIRECTORY))

    def respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def do_GET(self):
        if self.path == "/ping":
            self.respond(200, {"status": health_status(self.activity_directory)})
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/invocations":
            self.respond(200, {"message": "Connect with the Herdr AgentCore shell plugin."})
        else:
            self.respond(404, {"error": "Not found"})

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
