"""AWS adapter failures must be sanitized and classified before reaching workflows."""

from unittest.mock import AsyncMock, Mock

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from conftest import PROFILE_DATA
from herdr_agentcore.agentcore import AgentCoreError, AgentCoreTransport, aws_error, websocket_error
from herdr_agentcore.models import Profile
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (409, "RetryableConflictException", True),
        (409, "ConflictException", False),
        (401, "UnauthorizedException", False),
        (403, "AccessDeniedException", False),
        (429, "ThrottlingException", True),
        (503, "ServiceUnavailableException", True),
    ],
)
def test_handshake_error_policy(status, code, retryable):
    error = websocket_error(
        InvalidStatus(
            Response(
                status,
                "failed",
                Headers({"x-amzn-ErrorType": code}),
                body=b'{"message":"must-not-be-logged"}',
            )
        )
    )
    assert error.retryable is retryable
    assert error.code == code
    assert "must-not-be-logged" not in str(error)


def test_retryable_conflict_from_body_and_untrusted_message_redaction():
    error = websocket_error(
        InvalidStatus(
            Response(
                409,
                "failed",
                Headers(),
                body=b'{"__type":"namespace#RetryableConflictException","message":"secret"}',
            )
        )
    )
    assert error.retryable
    assert "secret" not in str(error)
    error = websocket_error(
        InvalidStatus(
            Response(
                403, "failed", Headers(), body=b'{"code":"sensitive/value","message":"secret"}'
            )
        )
    )
    assert error.code == "HTTP403"


def test_sdk_error_classification_does_not_expose_service_messages():
    exc = ClientError(
        {"Error": {"Code": "RetryableConflictException", "Message": "secret"}}, "Stop"
    )
    assert aws_error(exc).retryable
    assert "secret" not in str(aws_error(exc))
    assert not aws_error(NoCredentialsError()).retryable


async def test_transport_normalizes_pinned_sdk_missing_credentials(monkeypatch, record):
    transport = AgentCoreTransport(Profile.from_dict(PROFILE_DATA))
    monkeypatch.setattr(
        transport, "_sign", Mock(side_effect=RuntimeError("No AWS credentials found"))
    )
    with pytest.raises(AgentCoreError, match="NoCredentialsError"):
        await transport.connect(record)


async def test_transport_normalizes_handshake_conflict(monkeypatch, record):
    transport = AgentCoreTransport(Profile.from_dict(PROFILE_DATA))
    monkeypatch.setattr(transport, "_sign", Mock(return_value=("wss://example.test", {})))
    failure = InvalidStatus(
        Response(409, "conflict", Headers({"x-amzn-ErrorType": "RetryableConflictException"}))
    )
    monkeypatch.setattr(
        "herdr_agentcore.agentcore.websockets.connect", AsyncMock(side_effect=failure)
    )
    with pytest.raises(AgentCoreError) as caught:
        await transport.connect(record)
    assert caught.value.retryable
