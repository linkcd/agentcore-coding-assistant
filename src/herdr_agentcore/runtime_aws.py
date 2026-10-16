"""Opt-in runtime-role credentials for the sample's PATH-based OpenCode launcher."""

import shlex


def runtime_role_launcher(command: list[str]) -> list[str]:
    """Wrap a launcher that invokes ``opencode`` through PATH.

    The sample generates its provider/MCP configuration before exec'ing OpenCode,
    but also exports a one-time IMDS credential snapshot. A temporary shim removes
    that snapshot AFTER initialization. AWS_PROFILE enables OpenCode's standard
    Node credential chain, which can refresh credentials with an expiration.

    Use only where the runtime's default AWS profile resolves its execution role.
    A configured Bedrock API key or absolute OpenCode invocation needs a separate
    runtime-specific setup. This does not change management-host authentication.
    """
    shim = (
        "#!/bin/sh",
        "unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN",
        "export AWS_PROFILE=default",
        'exec "$HERDR_REAL_OPENCODE" "$@"',
    )
    script = "; ".join(
        [
            "set -eu",
            'real="${HERDR_REAL_OPENCODE:-$(command -v opencode)}"',
            'test -x "$real"',
            'dir="$(mktemp -d /tmp/herdr-runtime-role.XXXXXXXX)"',
            "printf '%s\\n' " + " ".join(shlex.quote(line) for line in shim) + ' > "$dir/opencode"',
            'chmod 700 "$dir/opencode"',
            'export HERDR_REAL_OPENCODE="$real"',
            'export PATH="$dir:$PATH"',
            "exec " + shlex.join(command),
        ]
    )
    return ["/bin/sh", "-c", script]
