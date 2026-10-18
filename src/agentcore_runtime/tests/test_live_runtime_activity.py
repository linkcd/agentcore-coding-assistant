"""Offline checks for disposable activity-probe cleanup."""

import uuid
from unittest.mock import Mock

import pytest
from agentcore_contract import UserError
from live_runtime_activity import run

ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test_runtime-Abc123"


@pytest.mark.parametrize(
    "stream",
    [
        [{"runtimeClientError": {"message": "failed"}}],
        [{"chunk": {"contentStop": {"exitCode": 1}}}],
    ],
)
def test_failed_activity_probe_stops_only_its_generated_session(monkeypatch, stream):
    client = Mock()
    client.invoke_agent_runtime_command.return_value = {"stream": stream}
    session = Mock()
    session.client.return_value = client
    monkeypatch.setattr("boto3.Session", Mock(return_value=session))
    with pytest.raises(UserError):
        run(ARN, None, False)
    request = client.invoke_agent_runtime_command.call_args.kwargs
    identifier = request["runtimeSessionId"]
    assert uuid.UUID(identifier).version == 4
    assert "--existing-health-server" in request["body"]["command"]
    client.stop_runtime_session.assert_called_once_with(
        agentRuntimeArn=ARN,
        runtimeSessionId=identifier,
        qualifier="DEFAULT",
    )
