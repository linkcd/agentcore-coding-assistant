#!/bin/sh
# Adapted from awslabs/agentcore-samples (Apache-2.0); see NOTICE.
# Modified: no IMDS requests, static credential exports, or config overwrites.
set -eu
exec python3.11 /app/launch.py "$@"
