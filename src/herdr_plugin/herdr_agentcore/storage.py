"""Versioned local config and connection records; never store AWS credentials."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .models import (
    ConnectionRecord,
    ConnectionStatus,
    LaunchState,
    Profile,
    UserError,
    connection_id,
    plain_text,
    profile_name,
    timestamp,
)


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
        # Persist the directory entry too: atomic replacement alone is not a
        # crash-durability boundary for persist-before-launch decisions.
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise UserError(f"Cannot read JSON from {path}: {exc}") from exc
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
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
            elif not profiles:
                raise UserError("No runtime profiles. Configure a connection first.")
            else:
                raise UserError(
                    "No default runtime profile is configured. Run 'set-default PROFILE' "
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
            profiles[name] = profile
            data["profiles"] = {key: asdict(value) for key, value in profiles.items()}
            atomic_json(self.paths.config / "config.json", data)

    def create_record(
        self, profile_key: str | None = None, name: str | None = None
    ) -> ConnectionRecord:
        data, profiles = self._configuration()
        profile_key = self._select_profile(data, profiles, profile_key)
        identifier = str(uuid.uuid4())
        now = timestamp()
        record = ConnectionRecord(
            id=identifier,
            name=plain_text(name or f"{profile_key}-{identifier[:8]}", "connection name"),
            profile_name=profile_key,
            profile=profiles[profile_key],
            runtime_session_id=str(uuid.uuid4()),
            shell_id=str(uuid.uuid4()),
            launch_state=LaunchState.NOT_STARTED,
            status=ConnectionStatus.CREATED,
            created_at=now,
            updated_at=now,
        )
        self.save_record(record)
        return record

    def save_record(self, record: ConnectionRecord) -> None:
        record.updated_at = timestamp()
        data = record.to_dict()
        ConnectionRecord.from_dict(data)
        try:
            atomic_json(self.paths.state / "connections" / f"{connection_id(record.id)}.json", data)
        except OSError as exc:
            raise UserError(
                "Cannot persist connection state; check disk space and permissions."
            ) from exc

    def load_record(self, identifier: str) -> ConnectionRecord:
        data = read_json(self.paths.state / "connections" / f"{connection_id(identifier)}.json")
        record = ConnectionRecord.from_dict(data)
        if record.id != identifier:
            raise UserError("Connection file identity does not match its filename.")
        return record

    def connection_records(self) -> list[ConnectionRecord]:
        directory = self.paths.state / "connections"
        records = []
        for path in directory.glob("*.json"):
            try:
                records.append(self.load_record(path.stem))
            except UserError as exc:
                warnings.warn(
                    f"Skipping invalid connection record {path.name!r}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
        return sorted(
            records, key=lambda item: datetime.fromisoformat(item.created_at), reverse=True
        )

    # Keep the v1 mapping API for callers/scripts while workflows use typed records.
    def create(self, profile_key: str | None = None, name: str | None = None) -> dict:
        return self.create_record(profile_key, name).to_dict()

    def save(self, record: dict) -> None:
        typed = ConnectionRecord.from_dict(record)
        self.save_record(typed)
        record["updated_at"] = typed.updated_at

    def load(self, identifier: str) -> dict:
        return self.load_record(identifier).to_dict()

    def connections(self) -> list[dict]:
        return [record.to_dict() for record in self.connection_records()]

    def lock(self, identifier: str):
        return exclusive_lock(self.paths.state / "locks" / f"{connection_id(identifier)}.lock")
