"""Validate the version-1 AgentCore shell connection contract. No side effects."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass


class UserError(Exception):
    """An actionable error that is safe to display without a traceback."""


def plain_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise UserError(f"{label} must be a non-empty string of at most 4096 characters.")
    if any(ord(c) < 32 or 127 <= ord(c) < 160 for c in value):
        raise UserError(f"{label} must not contain terminal control characters.")
    return value


def validate_command(command) -> list[str]:
    if not isinstance(command, list) or not 1 <= len(command) <= 64:
        raise UserError("command is required and must be an argv array with 1–64 elements.")
    for arg in command:
        plain_text(arg, "command argument")
    if sum(len(arg.encode()) + 1 for arg in command) > 8192:
        raise UserError("Launch command is too long (maximum 8 KiB).")
    if command[0].startswith("-"):
        raise UserError("The command executable must not start with '-'.")
    return list(command)


@dataclass(frozen=True)
class ConnectionSpec:
    runtime_arn: str
    region: str
    command: list[str]
    endpoint: str = "DEFAULT"
    agent_kind: str | None = None
    runtime_profile: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ConnectionSpec:
        if not isinstance(data, dict):
            raise UserError("A runtime connection must be a JSON object.")
        allowed = {"runtime_arn", "region", "command", "endpoint", "agent_kind", "runtime_profile"}
        if set(data) - allowed:
            raise UserError("Unknown runtime connection fields.")
        arn = data.get("runtime_arn", "")
        if not isinstance(arn, str):
            raise UserError("runtime_arn must be a string.")
        match = re.fullmatch(
            r"arn:(aws|aws-cn|aws-us-gov):bedrock-agentcore:([a-z0-9-]+):"
            r"([0-9]{12}):runtime/([a-zA-Z0-9_-]+)",
            arn,
        )
        if not match:
            raise UserError("Expected an AgentCore runtime ARN, not an endpoint ARN or URL.")
        region = data.get("region") or match[2]
        if region != match[2]:
            raise UserError("Connection region must match the runtime ARN's region.")
        command = validate_command(data.get("command"))
        endpoint = plain_text(data.get("endpoint", "DEFAULT"), "endpoint")
        kind = data.get("agent_kind")
        if kind is not None and (
            not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", kind)
        ):
            raise UserError("agent_kind must be null or a lowercase agent identifier.")
        reference = data.get("runtime_profile")
        if reference is not None and (
            not isinstance(reference, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", reference)
        ):
            raise UserError("runtime_profile must be null or a named profile reference.")
        return cls(arn, region, list(command), endpoint, kind, reference)


def encode_descriptor(connection: ConnectionSpec) -> dict:
    validated = ConnectionSpec.from_dict(asdict(connection))
    return {"version": 1, "transport": "agentcore-shell-v1", "connection": asdict(validated)}


def decode_descriptor(data: dict) -> ConnectionSpec:
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise UserError("Unsupported connection descriptor; expected version 1.")
    if set(data) != {"version", "transport", "connection"}:
        raise UserError("A descriptor must contain only version, transport, and connection.")
    if data["transport"] != "agentcore-shell-v1":
        raise UserError("Unsupported connection transport; expected agentcore-shell-v1.")
    return ConnectionSpec.from_dict(data["connection"])


def decode_cdk_outputs(data: dict, stack: str | None = None) -> ConnectionSpec:
    """Read the resolved descriptor in a standard CDK --outputs-file document."""
    if not isinstance(data, dict) or not data:
        raise UserError("CDK outputs must contain at least one stack.")
    if stack is None:
        if len(data) != 1:
            raise UserError("CDK outputs contain multiple stacks. Supply --stack explicitly.")
        stack = next(iter(data))
    outputs = data.get(stack)
    if not isinstance(outputs, dict):
        raise UserError("The selected stack is not present in the CDK outputs.")
    descriptor = outputs.get("ConnectionDescriptor")
    if not isinstance(descriptor, str):
        raise UserError("The stack has no ConnectionDescriptor output.")
    try:
        return decode_descriptor(json.loads(descriptor))
    except json.JSONDecodeError as exc:
        raise UserError("ConnectionDescriptor must contain valid JSON.") from exc
