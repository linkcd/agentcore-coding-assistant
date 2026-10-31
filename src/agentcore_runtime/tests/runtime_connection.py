"""Local addressing utility for disposable probes; no connector dependency."""

import re
from dataclasses import dataclass


class UserError(Exception):
    """Probe error safe to show without raw service responses."""


@dataclass(frozen=True)
class RuntimeTarget:
    runtime_arn: str
    region: str
    endpoint: str = "DEFAULT"


def runtime_target(arn: str) -> RuntimeTarget:
    match = re.fullmatch(
        r"arn:(aws|aws-cn|aws-us-gov):bedrock-agentcore:([a-z0-9-]+):"
        r"[0-9]{12}:runtime/[a-zA-Z0-9_-]+",
        arn,
    )
    if not match:
        raise UserError("Supply an AgentCore runtime ARN, not an endpoint ARN or URL.")
    return RuntimeTarget(arn, match[2])
