"""AWS/WebSocket adapter: credential providers and sanitized error classification."""

from __future__ import annotations

import asyncio
import json
import re

import websockets
from botocore.exceptions import BotoCoreError, ClientError
from websockets.exceptions import InvalidStatus

from .models import Profile, UserError

RETRYABLE_CODES = {
    "RetryableConflictException",
    "ThrottlingException",
    "TooManyRequestsException",
    "RequestTimeout",
    "RequestTimeoutException",
    "ServiceUnavailableException",
    "InternalServerException",
    "EndpointConnectionError",
    "ConnectionClosedError",
    "ConnectTimeoutError",
    "ReadTimeoutError",
}


class AgentCoreError(UserError):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(f"AgentCore request failed ({code}).")


def safe_code(value, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    code = value.split(":", 1)[0].rsplit("#", 1)[-1]
    return code if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,100}", code) else fallback


def aws_error(exc: BotoCoreError | ClientError) -> AgentCoreError:
    if isinstance(exc, ClientError):
        code = safe_code(exc.response.get("Error", {}).get("Code"), "UnknownAWSFailure")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
    else:
        code, status = type(exc).__name__, 0
    return AgentCoreError(code, retryable=code in RETRYABLE_CODES or status == 429 or status >= 500)


def websocket_error(exc: InvalidStatus) -> AgentCoreError:
    response = exc.response
    fallback = f"HTTP{response.status_code}"
    code = safe_code(response.headers.get("x-amzn-errortype"), fallback)
    if code == fallback and response.body:
        try:
            payload = json.loads(response.body)
            if isinstance(payload, dict):
                code = safe_code(payload.get("__type") or payload.get("code"), fallback)
        except (ValueError, UnicodeError):
            pass
    # Only explicitly retryable conflicts may be retried. Other 409s may require
    # user intervention; never infer that a new session/launch should be created.
    retryable = (
        response.status_code == 429 or response.status_code >= 500 or code in RETRYABLE_CODES
    )
    return AgentCoreError(code, retryable=retryable)


class AgentCoreTransport:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.client = None

    def _sign(self, record: dict):
        if self.client is None:
            import boto3
            from bedrock_agentcore.runtime import AgentCoreRuntimeClient

            session = boto3.Session(
                profile_name=self.profile.aws_profile, region_name=self.profile.region
            )
            self.client = AgentCoreRuntimeClient(region=self.profile.region, session=session)
        return self.client.connect_shell(
            runtime_arn=self.profile.runtime_arn,
            session_id=record["runtime_session_id"],
            shell_id=record["shell_id"],
            endpoint_name=self.profile.endpoint,
        )

    async def connect(self, record: dict):
        try:
            # Resolve/refresh credentials off the terminal event loop, then sign
            # each new handshake. Do not retain or log signed URLs/headers.
            url, headers = await asyncio.to_thread(self._sign, record)
            return await websockets.connect(
                url,
                additional_headers=headers,
                open_timeout=30,
                close_timeout=3,
                ping_interval=20,
                ping_timeout=20,
                max_size=64 * 1024,
                max_queue=16,
            )
        except InvalidStatus as exc:
            raise websocket_error(exc) from exc
        except (BotoCoreError, ClientError) as exc:
            raise aws_error(exc) from exc
        except RuntimeError as exc:
            # The pinned AgentCore SDK uses RuntimeError for this one condition.
            if str(exc) == "No AWS credentials found":
                raise AgentCoreError("NoCredentialsError") from exc
            raise

    def stop(self, record: dict):
        import boto3

        try:
            session = boto3.Session(
                profile_name=self.profile.aws_profile, region_name=self.profile.region
            )
            session.client("bedrock-agentcore").stop_runtime_session(
                agentRuntimeArn=self.profile.runtime_arn,
                runtimeSessionId=record["runtime_session_id"],
                qualifier=self.profile.endpoint,
            )
        except (BotoCoreError, ClientError) as exc:
            raise aws_error(exc) from exc
