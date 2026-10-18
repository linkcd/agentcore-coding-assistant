"""CLI and simple in-pane menus for the community plugin."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from agentcore_contract import decode_cdk_outputs, decode_descriptor

from . import __version__, herdr
from .models import ConnectionRecord
from .sessions import SessionService
from .storage import Paths, Profile, Store, UserError


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Connect Herdr terminals to AgentCore Runtime")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="operation", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config-dir", help="Override the plugin configuration directory")
    common.add_argument("--state-dir", help="Override the plugin state directory")
    configure = commands.add_parser("configure", parents=[common])
    configure.add_argument("--profile", default="default")
    runtime = configure.add_mutually_exclusive_group(required=True)
    runtime.add_argument("--runtime-arn")
    runtime.add_argument("--cdk-outputs", type=Path, help="Import the CDK --outputs-file document")
    configure.add_argument(
        "--stack", help="Stack name in CDK outputs; required if more than one is present"
    )
    runtime.add_argument(
        "--connection-file", type=Path, help="Import a versioned connection descriptor"
    )
    runtime.add_argument(
        "--runtime-config", type=Path, help="Import the sample's runtime_config.json"
    )
    configure.add_argument("--aws-profile")
    configure.add_argument(
        "--runtime-profile",
        help="Named runtime settings reference; metadata, not a built-in assistant type",
    )
    configure.add_argument("--endpoint")
    configure.add_argument("--replace", action="store_true")
    configure.add_argument(
        "--agent-kind", help="Herdr agent identifier; 'terminal' clears the hint"
    )
    configure.add_argument(
        "--command",
        nargs=argparse.REMAINDER,
        help="Required with an ARN; overrides a descriptor command. Put this option last.",
    )
    commands.add_parser("profiles", parents=[common])
    default = commands.add_parser("set-default", parents=[common])
    default.add_argument("profile", help="Saved runtime profile used for new agents")
    sessions = commands.add_parser("sessions", parents=[common])
    sessions.add_argument("--json", action="store_true")
    stop = commands.add_parser("stop", parents=[common])
    stop.add_argument("connection_id")
    stop.add_argument(
        "--yes", action="store_true", help="Confirm termination of the runtime session"
    )
    for operation in ("new", "attach"):
        cmd = commands.add_parser(operation, parents=[common])
        cmd.add_argument("--reconnect-seconds", type=int, default=120)
        if operation == "new":
            cmd.add_argument("--profile", help="Override the configured default runtime profile")
            cmd.add_argument("--name")
        else:
            cmd.add_argument("connection_id")
    for operation in ("action", "menu"):
        cmd = commands.add_parser(operation, parents=[common])
        cmd.add_argument("entrypoint", choices=["setup", "new", "attach", "sessions", "stop"])
        cmd.add_argument("--profile", help="Runtime profile override for the new-agent entrypoint")
    return root


def choose(items: list, label, prompt: str):
    if not items:
        raise UserError("Nothing to select. Configure a runtime or create a session first.")
    for index, item in enumerate(items, 1):
        print(f"  {index}. {label(item)}")
    while True:
        answer = input(f"{prompt} [1-{len(items)}, q to cancel]: ").strip()
        if answer.lower() == "q":
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(items):
            return items[int(answer) - 1]
        print("Enter a listed number or q.")


def setup_menu(store: Store):
    print("Configure an existing AgentCore runtime. AWS credentials use your normal AWS chain.")
    name = input("Profile name [default]: ").strip() or "default"
    arn = input("Runtime ARN: ").strip()
    aws_profile = input("AWS profile (blank for default credential chain): ").strip() or None
    endpoint = input("Runtime endpoint [DEFAULT]: ").strip() or "DEFAULT"
    kind = input("Herdr agent kind (blank for an ordinary terminal): ").strip() or None
    command = input("Launch argv as JSON (required): ").strip()
    if not command:
        raise UserError("Supply explicit launch argv. The connector has no default command.")
    profile = Profile.from_dict(
        {
            "runtime_arn": arn,
            "aws_profile": aws_profile,
            "endpoint": endpoint,
            "command": json.loads(command),
            "agent_kind": kind,
        }
    )
    replace = name in store.profiles()
    if replace and input(f"Replace profile {name!r}? [y/N]: ").lower() != "y":
        return
    store.save_profile(name, profile, replace)
    print(f"Saved to {store.paths.config / 'config.json'}")
    print("Remote launch argv: " + json.dumps(profile.command))
    input("Press Enter to close setup.")


def exec_attach(store: Store, identifier: str, reconnect_seconds: int = 120):
    env = dict(os.environ)
    kind = store.load_record(identifier).profile.agent_kind
    env.pop("HERDR_AGENT", None)
    if kind is not None:
        env["HERDR_AGENT"] = kind
    argv = [
        sys.executable,
        "-m",
        "herdr_agentcore",
        "attach",
        identifier,
        "--config-dir",
        str(store.paths.config),
        "--state-dir",
        str(store.paths.state),
        "--reconnect-seconds",
        str(reconnect_seconds),
    ]
    # exec is important on macOS: Herdr reads the process's launch environment.
    os.execve(sys.executable, argv, env)


def menu(store: Store, entrypoint: str, profile: str | None = None):
    if not sys.stdin.isatty():
        raise UserError("Open menus with the Herdr plugin action or pane command.")
    if profile is not None and entrypoint != "new":
        raise UserError("--profile is only supported for the new-agent entrypoint.")
    if entrypoint == "setup":
        return setup_menu(store)
    if entrypoint == "new":
        requested = profile if profile is not None else os.environ.get(herdr.PROFILE_ENV)
        record = SessionService(store).create(requested)
        print(f"Using runtime profile: {record.profile_name}", flush=True)
        exec_attach(store, record.id)
        return
    if entrypoint == "sessions":
        print_sessions(store.connection_records())
        input("Press Enter to close. Use the reattach action to reopen a terminal.")
        return
    available = SessionService(store).available(for_stop=entrypoint == "stop")
    record = choose(
        available,
        lambda r: f"{r.name} — {r.status} ({r.id[:8]})",
        "Session",
    )
    if record is not None:
        if entrypoint == "stop":
            print("This terminates the entire runtime session and its processes. Detach first.")
            if input(f"Type {record.name!r} to stop it: ") == record.name:
                stop_connection(store, record.id)
                input("Stop requested. Press Enter to close.")
        else:
            exec_attach(store, record.id)


def stop_connection(store: Store, identifier: str):
    record = SessionService(store).stop(identifier)
    if record is not None:
        print(f"Stop requested for {record.name}.")


def print_sessions(records: list[ConnectionRecord]):
    if not records:
        print("No saved sessions.")
    for record in records:
        print(f"{record.id}  {record.status:12}  {record.name}")
        print(f"  Last recorded: {record.updated_at}")
        if record.last_message:
            print(f"  {record.last_message}")
    if records:
        print("Statuses are last-known local records, not a live AWS inventory.")


async def connect(store: Store, identifier: str, reconnect_seconds: int) -> int:
    def on_start(record):
        print(f"Connecting {record.name} ({identifier})")
        print("Ctrl+] then d detaches. Ctrl+] twice sends a literal Ctrl+].")
        print("Reattach uses this shell; creating a new agent uses a new runtime session.")

    async def publish(connection, status):
        await asyncio.to_thread(herdr.report_connection, connection, status)

    return await SessionService(store).attach(
        identifier, reconnect_seconds=reconnect_seconds, publish=publish, on_start=on_start
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = Store(Paths.resolve(args.config_dir, args.state_dir))
    try:
        if args.operation == "configure":
            if args.stack and not args.cdk_outputs:
                raise UserError("--stack requires --cdk-outputs.")
            data = {"runtime_arn": args.runtime_arn, "agent_kind": None}
            if args.cdk_outputs:
                data = asdict(
                    decode_cdk_outputs(json.loads(args.cdk_outputs.read_text()), args.stack)
                )
            if args.connection_file:
                data = asdict(decode_descriptor(json.loads(args.connection_file.read_text())))
            if args.runtime_config:
                imported = json.loads(args.runtime_config.read_text())
                if not isinstance(imported, dict):
                    raise UserError("runtime_config.json must contain an object.")
                data = {"runtime_arn": imported.get("runtime_arn"), "agent_kind": None}
            for key in ("command", "endpoint", "agent_kind", "runtime_profile"):
                value = getattr(args, key)
                if value is not None:
                    data[key] = None if key == "agent_kind" and value == "terminal" else value
            profile = Profile.from_dict({**data, "aws_profile": args.aws_profile})
            store.save_profile(args.profile, profile, args.replace)
            print(f"Saved profile {args.profile} to {store.paths.config / 'config.json'}")
        elif args.operation == "profiles":
            print(json.dumps({k: asdict(v) for k, v in store.profiles().items()}, indent=2))
        elif args.operation == "set-default":
            store.set_default(args.profile)
            print(f"Default runtime profile: {args.profile}")
        elif args.operation == "sessions":
            records = store.connection_records()
            if args.json:
                print(json.dumps([record.to_dict() for record in records], indent=2))
            else:
                print_sessions(records)
        elif args.operation == "action":
            print(json.dumps(herdr.open_action(args.entrypoint, args.profile)))
        elif args.operation == "stop":
            if not args.yes:
                raise UserError("Stopping terminates the runtime session; pass --yes to confirm.")
            stop_connection(store, args.connection_id)
        elif args.operation == "menu":
            menu(store, args.entrypoint, args.profile)
        elif args.operation in {"new", "attach"}:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise UserError("Interactive connection requires a terminal.")
            if args.operation == "new":
                SessionService.validate_reconnect(args.reconnect_seconds)
                requested = (
                    args.profile if args.profile is not None else os.environ.get(herdr.PROFILE_ENV)
                )
                identifier = SessionService(store).create(requested, args.name).id
            else:
                identifier = args.connection_id
            kind = store.load_record(identifier).profile.agent_kind
            if os.environ.get("HERDR_ENV") == "1" and os.environ.get("HERDR_AGENT") != kind:
                exec_attach(store, identifier, args.reconnect_seconds)
                return 0
            return asyncio.run(connect(store, identifier, args.reconnect_seconds))
        return 0
    except (UserError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"AgentCore: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        return 130
