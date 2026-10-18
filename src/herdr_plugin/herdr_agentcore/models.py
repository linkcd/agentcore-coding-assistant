"""Validated domain records and internal JSON storage boundaries."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from agentcore_contract import ConnectionSpec
from agentcore_contract import UserError as UserError
from agentcore_contract import plain_text as plain_text


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def profile_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
        raise UserError("Profile names must use 1–64 letters, numbers, underscores, or hyphens.")
    return value


def connection_id(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise UserError("Invalid connection ID; use an ID from 'sessions'.") from exc
    return value


@dataclass(frozen=True)
class Profile(ConnectionSpec):
    """A connection specification plus host-local AWS credential selection."""

    aws_profile: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        if not isinstance(data, dict):
            raise UserError("A runtime profile must be a JSON object.")
        connection = {key: value for key, value in data.items() if key != "aws_profile"}
        spec = ConnectionSpec.from_dict(connection)
        aws_profile = data.get("aws_profile")
        if aws_profile is not None:
            plain_text(aws_profile, "AWS profile")
        return cls(**asdict(spec), aws_profile=aws_profile)


class LaunchState(StrEnum):
    NOT_STARTED = "not_started"
    ATTEMPTED = "attempted"
    SENT = "sent"


class ConnectionStatus(StrEnum):
    CREATED = "created"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DETACHED = "detached"
    ERROR = "error"
    TAKEN_OVER = "taken_over"
    EXITED = "exited"
    EXPIRED = "expired"
    STOPPED = "stopped"

    @property
    def attachable(self) -> bool:
        return self not in {self.EXITED, self.EXPIRED, self.STOPPED}


def record_time(value: str, label: str) -> str:
    plain_text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError
    except ValueError as exc:
        raise UserError(f"{label} must be an ISO-8601 timestamp with a timezone.") from exc
    return value


@dataclass
class ConnectionRecord:
    """Typed workflow state; serialized fields retain the existing v1 contract.

    `status` remains the last-known v1 connection label, not an authoritative
    compute inventory. In particular, STOPPED records an accepted stop request.
    Existing recovery annotations are preserved in `extra` during round trips.
    """

    id: str
    name: str
    profile_name: str
    profile: Profile
    runtime_session_id: str
    shell_id: str
    launch_state: LaunchState
    status: ConnectionStatus
    created_at: str
    updated_at: str
    last_message: str | None = None
    exit_code: int | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> ConnectionRecord:
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] != 1
        ):
            raise UserError("Unsupported connection format; expected version 1.")
        try:
            record = cls(
                id=connection_id(data["id"]),
                name=plain_text(data["name"], "connection name"),
                profile_name=profile_name(data["profile_name"]),
                profile=Profile.from_dict(data["profile"]),
                runtime_session_id=connection_id(data["runtime_session_id"]),
                shell_id=connection_id(data["shell_id"]),
                launch_state=LaunchState(data["launch_state"]),
                status=ConnectionStatus(data["status"]),
                created_at=record_time(data["created_at"], "created_at"),
                updated_at=record_time(data["updated_at"], "updated_at"),
                last_message=data.get("last_message"),
                exit_code=data.get("exit_code"),
            )
        except KeyError as exc:
            raise UserError(f"Connection record is missing required field: {exc.args[0]}.") from exc
        except (ValueError, TypeError) as exc:
            raise UserError("Invalid connection launch state or status.") from exc
        if record.last_message is not None:
            plain_text(record.last_message, "last_message")
        if record.exit_code is not None and type(record.exit_code) is not int:
            raise UserError("Connection exit_code must be an integer.")
        known = set(cls.__dataclass_fields__) | {"version"}
        known.remove("extra")
        record.extra = {key: value for key, value in data.items() if key not in known}
        return record

    def to_dict(self) -> dict:
        data = {
            **self.extra,
            "version": 1,
            "id": self.id,
            "name": self.name,
            "profile_name": self.profile_name,
            "profile": asdict(self.profile),
            "runtime_session_id": self.runtime_session_id,
            "shell_id": self.shell_id,
            "launch_state": str(self.launch_state),
            "status": str(self.status),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.last_message is not None:
            data["last_message"] = self.last_message
        if self.exit_code is not None:
            data["exit_code"] = self.exit_code
        return data

    def transition(self, status: ConnectionStatus | str, message: str | None = None):
        self.status = ConnectionStatus(status)
        self.last_message = message
