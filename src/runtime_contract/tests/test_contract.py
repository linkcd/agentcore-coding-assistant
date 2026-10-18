"""Explicit connection commands, validation boundaries, and publication data."""

import copy
import json

import pytest
from agentcore_contract import (
    ConnectionSpec,
    UserError,
    decode_cdk_outputs,
    decode_descriptor,
    encode_descriptor,
)

ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test_runtime-Abc123"


def test_roundtrip_uses_only_connection_data_and_copies_argv():
    command = ["/app/run.sh", "--session", "saved"]
    spec = ConnectionSpec.from_dict(
        {
            "runtime_arn": ARN,
            "command": command,
            "agent_kind": "opencode",
            "runtime_profile": "reviewer",
        }
    )
    command.append("changed")
    descriptor = encode_descriptor(spec)
    assert descriptor["transport"] == "agentcore-shell-v1"
    assert descriptor["version"] == 1
    assert decode_descriptor(descriptor) == spec
    assert spec.command == ["/app/run.sh", "--session", "saved"]
    assert "aws_profile" not in descriptor["connection"]
    assert descriptor["connection"]["runtime_profile"] == "reviewer"


def test_generic_connection_has_no_agent_hint_and_derives_region():
    spec = ConnectionSpec.from_dict({"runtime_arn": ARN, "command": ["/bin/sh"]})
    assert spec.region == "us-west-2"
    assert spec.agent_kind is None


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"transport": "http"},
        {"credentials": "synthetic"},
        {"connection": {"runtime_arn": ARN, "aws_profile": "deployment-role"}},
        {"connection": {"runtime_arn": ARN, "command": ["/bin/sh"], "agent_kind": "bad\nkind"}},
        {"connection": {"runtime_arn": ARN, "command": ["/bin/sh"], "agent_kind": True}},
        {"connection": {"runtime_arn": ARN, "command": []}},
        {"connection": {"runtime_arn": ARN, "region": "eu-west-1"}},
    ],
)
def test_invalid_contract_is_rejected_without_modifying_input(change):
    descriptor = {
        **encode_descriptor(ConnectionSpec.from_dict({"runtime_arn": ARN, "command": ["/bin/sh"]})),
        **change,
    }
    before = copy.deepcopy(descriptor)
    with pytest.raises(UserError):
        decode_descriptor(descriptor)
    assert descriptor == before


def test_missing_command_is_rejected_in_both_spec_and_descriptor():
    with pytest.raises(UserError, match="command is required"):
        ConnectionSpec.from_dict({"runtime_arn": ARN})
    with pytest.raises(UserError, match="command is required"):
        decode_descriptor(
            {
                "version": 1,
                "transport": "agentcore-shell-v1",
                "connection": {"runtime_arn": ARN, "agent_kind": "opencode"},
            }
        )


def test_cdk_outputs_select_the_declared_stack_and_resolve_its_descriptor():
    spec = ConnectionSpec.from_dict({"runtime_arn": ARN, "command": ["/custom/start"]})
    outputs = {"Selected": {"ConnectionDescriptor": json.dumps(encode_descriptor(spec))}}
    assert decode_cdk_outputs(outputs) == spec
    outputs["Other"] = {"RuntimeArn": "unrelated"}
    with pytest.raises(UserError, match="multiple stacks"):
        decode_cdk_outputs(outputs)
    assert decode_cdk_outputs(outputs, "Selected") == spec


@pytest.mark.parametrize(
    "outputs,stack",
    [
        ({}, None),
        ({"Stack": {}}, "Missing"),
        ({"Stack": {}}, None),
        ({"Stack": {"ConnectionDescriptor": "{invalid"}}, None),
        ({"Stack": {"ConnectionDescriptor": {}}}, None),
    ],
)
def test_invalid_cdk_outputs_fail_without_guessing(outputs, stack):
    with pytest.raises(UserError):
        decode_cdk_outputs(outputs, stack)
