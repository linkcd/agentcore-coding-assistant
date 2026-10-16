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

from . import __version__, herdr
from .runtime_aws import runtime_role_launcher
from .storage import Paths, Profile, Store, UserError


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="OpenCode terminals on AgentCore Runtime")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="operation", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config-dir", help="Override the plugin configuration directory")
    common.add_argument("--state-dir", help="Override the plugin state directory")
    provision = commands.add_parser("provision", parents=[common])
    provision.add_argument("--name", required=True, help="Name for the new runtime deployment")
    provision.add_argument("--region", required=True)
    provision.add_argument(
        "--model-id", required=True, help="Bedrock model/system inference-profile ID"
    )
    provision.add_argument("--opencode-version", default="1.18.30")
    provision.add_argument("--aws-profile", help="Management-host AWS credentials")
    provision.add_argument("--profile", default="default", help="Connector profile to save")
    provision.add_argument("--replace", action="store_true", help="Replace the connector profile")
    provision.add_argument(
        "--update", action="store_true", help="Update this deployment's existing stacks"
    )
    provision.add_argument(
        "--plan", action="store_true", help="Print templates without AWS or Docker calls"
    )
    configure = commands.add_parser("configure", parents=[common])
    configure.add_argument("--profile", default="default")
    runtime = configure.add_mutually_exclusive_group(required=True)
    runtime.add_argument("--runtime-arn")
    runtime.add_argument(
        "--runtime-config", type=Path, help="Import the sample's runtime_config.json"
    )
    configure.add_argument("--aws-profile")
    configure.add_argument("--endpoint", default="DEFAULT")
    configure.add_argument("--replace", action="store_true")
    configure.add_argument(
        "--runtime-role-credentials",
        action="store_true",
        help="Use refreshable runtime IAM credentials with a PATH-based OpenCode launcher",
    )
    configure.add_argument("--command", nargs=argparse.REMAINDER, default=["/app/run.sh"])
    commands.add_parser("profiles", parents=[common])
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
            cmd.add_argument("--profile", default="default")
            cmd.add_argument("--name")
        else:
            cmd.add_argument("connection_id")
    for operation in ("action", "menu"):
        cmd = commands.add_parser(operation, parents=[common])
        cmd.add_argument("entrypoint", choices=["setup", "new", "attach", "sessions", "stop"])
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
    use_runtime_role = (
        input("Use refreshable runtime-role credentials? [y/N]: ").strip().lower() == "y"
    )
    profile = Profile.from_dict(
        {
            "runtime_arn": arn,
            "aws_profile": aws_profile,
            "endpoint": endpoint,
            "command": (
                runtime_role_launcher(["/app/run.sh"]) if use_runtime_role else ["/app/run.sh"]
            ),
        }
    )
    replace = name in store.profiles()
    if replace and input(f"Replace profile {name!r}? [y/N]: ").lower() != "y":
        return
    store.save_profile(name, profile, replace)
    print(f"Saved to {store.paths.config / 'config.json'}")
    print("Remote launcher: /app/run.sh. Runtime-role refresh: " + str(use_runtime_role))
    input("Press Enter to close setup.")


def exec_attach(store: Store, identifier: str):
    env = dict(os.environ, HERDR_AGENT="opencode")
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
    ]
    # exec is important on macOS: Herdr reads the process's launch environment.
    os.execve(sys.executable, argv, env)


def menu(store: Store, entrypoint: str):
    if not sys.stdin.isatty():
        raise UserError("Open menus with the Herdr plugin action or pane command.")
    if entrypoint == "setup":
        return setup_menu(store)
    if entrypoint == "new":
        name = choose(list(store.profiles()), str, "Runtime profile")
        if name is not None:
            record = store.create(name)
            exec_attach(store, record["id"])
        return
    records = store.connections()
    if entrypoint == "sessions":
        print_sessions(records)
        input("Press Enter to close. Use the reattach action to reopen a terminal.")
        return
    excluded = {"stopped"} if entrypoint == "stop" else {"exited", "expired", "stopped"}
    available = [r for r in records if r["status"] not in excluded]
    record = choose(
        available,
        lambda r: f"{r['name']} — {r['status']} ({r['id'][:8]})",
        "Session",
    )
    if record is not None:
        if entrypoint == "stop":
            print("This terminates the entire runtime session and its processes. Detach first.")
            if input(f"Type {record['name']!r} to stop it: ") == record["name"]:
                stop_connection(store, record["id"])
                input("Stop requested. Press Enter to close.")
        else:
            exec_attach(store, record["id"])


def stop_connection(store: Store, identifier: str):
    from botocore.exceptions import BotoCoreError, ClientError

    from .connector import AgentCoreTransport

    with store.lock(identifier):
        record = store.load(identifier)
        if record["status"] == "stopped":
            return
        try:
            AgentCoreTransport(Profile.from_dict(record["profile"])).stop(record)
        except (BotoCoreError, ClientError) as exc:
            raise UserError(
                f"Stop failed ({type(exc).__name__}); no local status was changed."
            ) from exc
        record["status"] = "stopped"
        store.save(record)
        print(f"Stop requested for {record['name']}.")


def print_sessions(records: list[dict]):
    if not records:
        print("No saved sessions.")
    for record in records:
        print(f"{record['id']}  {record['status']:12}  {record['name']}")
        print(f"  Last recorded: {record['updated_at']}")
        if record.get("last_message"):
            print(f"  {record['last_message']}")
    if records:
        print("Statuses are last-known local records, not a live AWS inventory.")


async def connect(store: Store, identifier: str, reconnect_seconds: int) -> int:
    from .connector import AgentCoreTransport, Connector
    from .terminal import Terminal

    if not 0 <= reconnect_seconds <= 900:
        raise UserError("--reconnect-seconds must be between 0 and 900.")
    with store.lock(identifier):
        record = store.load(identifier)
        profile = Profile.from_dict(record["profile"])
        print(f"Connecting {record['name']} ({identifier})")
        print("Ctrl+] then d detaches. Ctrl+] twice sends a literal Ctrl+].")
        print("Reattach uses this shell; creating a new agent uses a new runtime session.")

        async def publish(connection, status):
            await asyncio.to_thread(herdr.report_connection, connection, status)

        with Terminal() as terminal:
            runner = Connector(
                store,
                record,
                AgentCoreTransport(profile),
                terminal,
                reconnect_seconds=reconnect_seconds,
                publish=publish,
            )
            return await runner.run()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = Store(Paths.resolve(args.config_dir, args.state_dir))
    try:
        if args.operation == "provision":
            from .provision import provision

            provision(args, store)
        elif args.operation == "configure":
            arn = args.runtime_arn
            if args.runtime_config:
                imported = json.loads(args.runtime_config.read_text())
                if not isinstance(imported, dict):
                    raise UserError("runtime_config.json must contain an object.")
                arn = imported.get("runtime_arn")
            profile = Profile.from_dict(
                {
                    "runtime_arn": arn,
                    "command": args.command,
                    "aws_profile": args.aws_profile,
                    "endpoint": args.endpoint,
                }
            )
            if args.runtime_role_credentials:
                profile = Profile.from_dict(
                    {**asdict(profile), "command": runtime_role_launcher(profile.command)}
                )
            store.save_profile(args.profile, profile, args.replace)
            print(f"Saved profile {args.profile} to {store.paths.config / 'config.json'}")
        elif args.operation == "profiles":
            print(json.dumps({k: asdict(v) for k, v in store.profiles().items()}, indent=2))
        elif args.operation == "sessions":
            records = store.connections()
            if args.json:
                print(json.dumps(records, indent=2))
            else:
                print_sessions(records)
        elif args.operation == "action":
            print(json.dumps(herdr.open_action(args.entrypoint)))
        elif args.operation == "stop":
            if not args.yes:
                raise UserError("Stopping terminates the runtime session; pass --yes to confirm.")
            stop_connection(store, args.connection_id)
        elif args.operation == "menu":
            menu(store, args.entrypoint)
        elif args.operation in {"new", "attach"}:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise UserError("Interactive connection requires a terminal.")
            if os.environ.get("HERDR_ENV") == "1" and os.environ.get("HERDR_AGENT") != "opencode":
                env = dict(os.environ, HERDR_AGENT="opencode")
                os.execve(
                    sys.executable,
                    [
                        sys.executable,
                        "-m",
                        "herdr_agentcore",
                        *(sys.argv[1:] if argv is None else argv),
                    ],
                    env,
                )
            identifier = (
                store.create(args.profile, args.name)["id"]
                if args.operation == "new"
                else args.connection_id
            )
            return asyncio.run(connect(store, identifier, args.reconnect_seconds))
        return 0
    except (UserError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"AgentCore: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        return 130
