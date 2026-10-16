# Coding agent context and handoff

## Read first

1. `README.md`: the goal of this repository.
2. `REQUIREMENTS.md`: scope and acceptance criteria.
3. `DESIGN.md`: architecture, diagrams, and implementation decisions.

The goal is a **community Herdr plugin for OpenCode executing inside AgentCore Runtime**. Connectors execute on the Herdr server host; OpenCode, its tools, and its workspace execute in AgentCore. For unattended operation, the target is **laptop Herdr client → SSH → always-on EC2 Herdr management server and connectors → AgentCore sessions**. Laptop-hosted management remains a development option.

**Scope clarification:** follow Herdr's design and focus on AgentCore-based orchestration. Jindouyun is only a reference for missing execution concepts. Do not turn this plugin into a Jindouyun client or add Cognito, end-user accounts, per-user Runtime ownership, or a separate control-plane/registry service. S3 Files persistence for coding files, configuration, skills, and OpenCode state is explicitly in scope and is the primary persistence target.

## Repository conventions

- Keep the README focused on the goal. Maintain requirements and design in the root files above. Do not recreate a `docs/` tree, publication guides, or a long usage manual unless requested.
- Put all implementation and test code under `src/`: `src/herdr_agentcore/` and `src/tests/`.
- Keep `herdr-plugin.toml`, `pyproject.toml`, `uv.lock`, and CI configuration in their standard root/`.github/` locations.
- Keep the plugin standalone. Use Herdr's public plugin, CLI, and socket interfaces rather than changing Herdr core.
- Local `herdr/`, `agentcore-samples/`, and `agentcore-sdk-python/` directories, if present, are ignored research checkouts. They are not shipped plugin code. Use them as references; do not build a dependency on their local paths or include them in a distribution.
- Check the actual working tree before changing files; the repository may not yet have a root Git repository initialized. Do not initialize, commit, push, or publish merely to complete a local change.

## Current implementation

Experimental version `0.1.0`, targeting Herdr 0.9.5+, Python 3.11+, macOS/Linux. Dependencies are locked with uv; the AgentCore SDK is pinned to 1.24.1.

| File | Responsibility |
| --- | --- |
| `herdr-plugin.toml` | Five actions and pane entrypoints: setup, new, attach, sessions, stop. |
| `src/herdr_agentcore/cli.py` | CLI, in-pane menus, workflow coordination, explicit stop confirmation. |
| `src/herdr_agentcore/herdr.py` | Public Herdr command calls and connection metadata. |
| `src/herdr_agentcore/storage.py` | Profile/record validation, atomic persistence, local locks. |
| `src/herdr_agentcore/connector.py` | AWS signing, shell framing, launch-once behavior, reconnect, termination. |
| `src/herdr_agentcore/terminal.py` | Raw POSIX terminal I/O, resize signals, detach keys, cleanup. |
| `src/tests/` | Offline behavior tests and optional Herdr manifest validation. |

The runtime must already be deployed. The default remote launcher is `/app/run.sh`, matching the AWS coding-agent sample. The plugin does not deploy infrastructure or install OpenCode on the management host. A cloud Herdr host must have the plugin, its dependencies, and runtime profiles installed there; the laptop's plugins/config are not automatically copied to it.

## Preserve these decisions

1. **Herdr-native identities with durable execution bindings.** Herdr owns workspace/tab/pane/live-agent identity. Use the existing connection UUID as an internal recovery binding, not a new platform resource. Preserve runtime-session/shell IDs for warm reattachment and record persistent paths/conversation IDs for recovery. One session per independent agent is the default, not a restriction against helper/agent shells sharing a runtime session.
2. **Never replay uncertain work.** Persist launch state before sending a command. Do not blindly relaunch on reconnect or resend a prompt after ambiguous delivery.
3. **Detach is not stop.** Closing the WebSocket detaches. Explicit stop terminates the session's compute and processes, not its logical identity or configured persistent data. Do not add shutdown frames to ordinary disconnect cleanup.
4. **Attach and resume are different.** Inspect the shell confirmation's `reconnected` flag. Keep attach strict and never blindly launch into an existing agent. The planned resume operation may deliberately create a replacement shell/process after confirming remote state and loading the saved conversation. A network failure alone is not proof the process ended.
5. **Separate compute, transport, and agent state.** Herdr uses `HERDR_AGENT=opencode` and screen detection. Metadata reports transport health; it must not invent agent lifecycle events. A runtime supervisor must report real work to AgentCore rather than treating socket keepalive as a busy signal.
6. **Keep user state outside installation.** Use Herdr's plugin config/state directories, atomic records, and per-connection locks. Never persist AWS credentials, signed URLs, or raw terminal transcripts.
7. **Treat CLI responses correctly.** Herdr success responses contain `id` and `result`; do not require an `ok: true` field.
8. **Compute lifetime is not persistent-file lifetime.** Stop/expiry can be followed by explicit recovery under the same runtime session ID and recorded S3 Files paths. The current code still treats stopped/expired records as non-attachable; explicit recovery remains to be implemented.
9. **S3 Files-backed coding state is required but not integrated yet.** Consume the runtime's configured mount, initially `/mnt/s3files`, with a stable persistent-home namespace per independent binding. Persist repositories, working changes, configuration, skills, and OpenCode state; support remote Working Directory selection. Replace the sample launcher's forced ephemeral home/cwd and configuration overwrite. Validate database locking/concurrency and skill discovery; keep sockets/PIDs ephemeral. Managed session storage Preview is only a possible later alternative with different retention semantics.
10. **One deployment, many sessions and shells.** A runtime profile supplies image/permissions/network/storage settings for multiple sessions. Additional shells may share a runtime session and deliberately share files. Ordinary build/test shells must not be labeled OpenCode agents. Implement separate shell/process stop and whole-session stop scopes before enabling shared-session panes.
11. **Laptop is a client for unattended operation.** Run Herdr's server, connectors, and any autonomous coordination on an always-on EC2 management host first. Use native Herdr SSH remote-machine support. Laptop sleep/reboot should only disconnect viewing/control, not trigger cloud shutdown. Logic left on the laptop cannot progress while it is offline.
12. **Two recovery boundaries.** Retain management-host configuration, registry, and workflow progress; reconcile connections after host/server replacement. Separately recover AgentCore compute and OpenCode conversation state. Instance-role credentials belong to the management host; model/tool credentials belong to the runtime execution role. An always-on host does not remove AgentCore lifetime limits.
13. **EC2 first; ECS/failover later.** EC2 fits Herdr's existing SSH model. ECS needs compatible remote access, external state, and task-replacement reconciliation; ECS Exec is not assumed to replace SSH. Start with one active manager and introduce controller leases before multi-host failover. This is infrastructure coordination, not end-user identity management.

When changing shell behavior, inspect the pinned SDK's implementation and tests. Some SDK docstrings differ from implementation: `ShellSession.close()` detaches, and the high-level iterator hides connection-confirmation frames. This connector uses the SDK's signing helper with direct WebSocket framing so it can inspect confirmation.

## Validation

Run from the repository root:

```bash
uv sync --frozen
uv run ruff check src
uv run ruff format --check src
uv run pytest
uv build
```

Optional validation using an installed Herdr binary:

```bash
HERDR_TEST_BINARY="$(command -v herdr)" uv run pytest
```

That test uses isolated config/state/socket paths and does not start a server or modify the normal user registry. Without the variable it is skipped. Other tests use fake transports, a real local WebSocket server, and a local PTY; they make no AWS calls.

The manifest's production build is `uv sync --frozen --no-dev`. After testing that command, use `uv sync --frozen` to restore test dependencies. Keep version numbers aligned in the manifest, package metadata, and `__init__.py`; regenerate the lockfile when dependency/project resolution changes.

## Validation status and next work

- Offline tests, lint/format checks, package builds, and isolated Herdr 0.9.5 manifest validation have passed on macOS/Python 3.13. Re-run relevant checks after changes.
- Live AgentCore/OpenCode integration, actual Herdr pane interaction, and cloud lifecycle behavior remain unverified.
- No EC2/ECS management deployment, laptop sleep/reboot validation, or automatic management-host recovery has been implemented or verified.
- The Linux/macOS Python 3.11/3.13 CI matrix is configured; remote CI execution and GitHub-managed install/update validation remain pending.
- Publication and marketplace listing have not occurred. A public repository with a valid manifest and the `herdr-plugin` topic is the community distribution route; official endorsement is separate.

Prioritize live terminal validation and the persistent coding-file requirements (P01–P07), then the EC2 management model (H01–H09). Extend binding records with persistent home/cwd, integrate S3 Files and runtime bootstrap/process supervision, and capture OpenCode conversation state. Implement the lifecycle increment (L01–L12): resume, Herdr rebinding, host reconciliation, additional shells, and scoped stop operations. Handle stop completion and retryable provisioning/stop conflicts; the current connector treats non-429 HTTP 4xx responses as terminal. Recovery must not duplicate a launch, tool request, or coordination step.

The current prototype has no S3 Files-backed home/cwd integration, persisted OpenCode conversation ID, additional-shell workflow, recovery supervisor, explicit resume/archive action, or management-host deployment/reconciliation. These are design targets, not verified capabilities. The copied sample's S3 Files mount for shared tools does not establish coding-state persistence. Keep direct AWS IAM authentication; do not add Jindouyun authentication/control-plane dependencies while implementing these gaps.

Before cloud tests, obtain the runtime/profile details and authorization to perform the intended operations. Do not deploy resources, stop existing sessions, alter the user's live Herdr setup, or publish a repository as an incidental test. Use disposable named Herdr sessions for interactive testing.

For handoff, state what changed, which checks actually ran, and what remains unverified. Update these instructions and the requirements/design when implementation decisions change, without adding separate handoff documents.
