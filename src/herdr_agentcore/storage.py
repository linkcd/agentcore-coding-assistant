"""Versioned local config and connection records; never store AWS credentials."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


class UserError(Exception):
    """An actionable error suitable for display without a traceback."""


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def plain_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise UserError(f"{label} must be a non-empty string of at most 4096 characters.")
    if any(ord(c) < 32 or 127 <= ord(c) < 160 for c in value):
        raise UserError(f"{label} must not contain terminal control characters.")
    return value


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


def private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    private_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(value, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise UserError(f"Cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise UserError(f"Unsupported or invalid format in {path}; expected version 1.")
    return value


@contextmanager
def exclusive_lock(path: Path):
    private_dir(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UserError(
                "This connection or config is already in use by another process."
            ) from exc
        yield
    finally:
        os.close(fd)
        # Do not unlink: another process may already hold/open this lock inode.


@dataclass(frozen=True)
class Paths:
    config: Path
    state: Path

    @classmethod
    def resolve(cls, config: str | None = None, state: str | None = None) -> Paths:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        return cls(
            Path(
                config or os.environ.get("HERDR_PLUGIN_CONFIG_DIR", config_home / "herdr-agentcore")
            )
            .expanduser()
            .resolve(),
            Path(state or os.environ.get("HERDR_PLUGIN_STATE_DIR", state_home / "herdr-agentcore"))
            .expanduser()
            .resolve(),
        )


@dataclass(frozen=True)
class Profile:
    runtime_arn: str
    region: str
    command: list[str]
    endpoint: str = "DEFAULT"
    aws_profile: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        if not isinstance(data, dict):
            raise UserError("A runtime profile must be a JSON object.")
        allowed = {"runtime_arn", "region", "command", "endpoint", "aws_profile"}
        if set(data) - allowed:
            raise UserError(f"Unknown profile fields: {', '.join(sorted(set(data) - allowed))}")
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
            raise UserError("Profile region must match the runtime ARN's region.")
        command = data.get("command", ["/app/run.sh"])
        if not isinstance(command, list) or not 1 <= len(command) <= 64:
            raise UserError("command must be an argv array with 1–64 elements.")
        for arg in command:
            plain_text(arg, "command argument")
        if sum(len(arg.encode()) + 1 for arg in command) > 8192:
            raise UserError("Launch command is too long (maximum 8 KiB).")
        if command[0].startswith("-"):
            raise UserError("The command executable must not start with '-'.")
        endpoint = plain_text(data.get("endpoint", "DEFAULT"), "endpoint")
        aws_profile = data.get("aws_profile")
        if aws_profile is not None:
            plain_text(aws_profile, "AWS profile")
        return cls(arn, region, command, endpoint, aws_profile)


class Store:
    def __init__(self, paths: Paths):
        self.paths = paths

    def _configuration(self) -> tuple[dict, dict[str, Profile]]:
        path = self.paths.config / "config.json"
        if not path.exists():
            return {"version": 1, "profiles": {}}, {}
        data = read_json(path)
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            raise UserError(f"Expected a profiles object in {path}.")
        if "default_profile" in data:
            profile_name(data["default_profile"])
        return data, {
            profile_name(name): Profile.from_dict(value) for name, value in profiles.items()
        }

    def profiles(self) -> dict[str, Profile]:
        return self._configuration()[1]

    @staticmethod
    def _select_profile(data: dict, profiles: dict[str, Profile], requested: str | None) -> str:
        if requested is None:
            if "default_profile" in data:
                requested = data["default_profile"]
            elif "default" in profiles:
                requested = "default"
            elif len(profiles) == 1:
                requested = next(iter(profiles))
            elif not profiles:
                raise UserError("No runtime profiles. Configure or provision a runtime first.")
            else:
                raise UserError(
                    "Multiple runtime profiles have no default. Run 'set-default PROFILE' "
                    "or supply --profile for this launch."
                )
        profile_name(requested)
        if requested not in profiles:
            raise UserError(
                f"Unknown runtime profile '{requested}'. Check profiles or set-default."
            )
        return requested

    def resolve_profile(self, requested: str | None = None) -> str:
        data, profiles = self._configuration()
        return self._select_profile(data, profiles, requested)

    def set_default(self, name: str) -> None:
        profile_name(name)
        with exclusive_lock(self.paths.config / "config.lock"):
            data, profiles = self._configuration()
            data["default_profile"] = self._select_profile(data, profiles, name)
            atomic_json(self.paths.config / "config.json", data)

    def save_profile(self, name: str, profile: Profile, replace: bool = False) -> None:
        profile_name(name)
        with exclusive_lock(self.paths.config / "config.lock"):
            data, profiles = self._configuration()
            if name in profiles and not replace:
                raise UserError(f"Profile '{name}' already exists. Use --replace to update it.")
            if "default_profile" not in data:
                if not profiles:
                    data["default_profile"] = name
                elif "default" in profiles or len(profiles) == 1:
                    data["default_profile"] = self._select_profile(data, profiles, None)
            profiles[name] = profile
            data["profiles"] = {key: asdict(value) for key, value in profiles.items()}
            atomic_json(self.paths.config / "config.json", data)

    def create(self, profile_key: str | None = None, name: str | None = None) -> dict:
        data, profiles = self._configuration()
        profile_key = self._select_profile(data, profiles, profile_key)
        identifier = str(uuid.uuid4())
        record = {
            "version": 1,
            "id": identifier,
            "name": plain_text(name or f"{profile_key}-{identifier[:8]}", "connection name"),
            "profile_name": profile_key,
            "profile": asdict(profiles[profile_key]),
            "runtime_session_id": str(uuid.uuid4()),
            "shell_id": str(uuid.uuid4()),
            "launch_state": "not_started",
            "status": "created",
            "created_at": timestamp(),
        }
        self.save(record)
        return record

    def save(self, record: dict) -> None:
        record["updated_at"] = timestamp()
        try:
            atomic_json(
                self.paths.state / "connections" / f"{connection_id(record['id'])}.json", record
            )
        except OSError as exc:
            raise UserError(
                "Cannot persist connection state; check disk space and permissions."
            ) from exc

    def load(self, identifier: str) -> dict:
        record = read_json(self.paths.state / "connections" / f"{connection_id(identifier)}.json")
        if record.get("id") != identifier:
            raise UserError("Connection file identity does not match its filename.")
        for key in ("runtime_session_id", "shell_id"):
            connection_id(record.get(key, ""))
        plain_text(record.get("name"), "connection name")
        Profile.from_dict(record.get("profile"))
        if record.get("launch_state") not in {"not_started", "attempted", "sent"}:
            raise UserError("Invalid connection launch state.")
        return record

    def connections(self) -> list[dict]:
        directory = self.paths.state / "connections"
        return sorted(
            (self.load(path.stem) for path in directory.glob("*.json")),
            key=lambda item: item["created_at"],
            reverse=True,
        )

    def lock(self, identifier: str):
        return exclusive_lock(self.paths.state / "locks" / f"{connection_id(identifier)}.lock")
