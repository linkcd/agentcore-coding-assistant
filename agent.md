# Coding agent context and handoff

## Read first

1. `README.md`: the goal of this repository.
2. `REQUIREMENTS.md`: scope and acceptance criteria.
3. `DESIGN.md`: architecture, diagrams, and implementation decisions.

The goal is a **community Herdr plugin for OpenCode executing inside AgentCore Runtime**, including the runtime image/provisioning source and the connector in this repository. Connectors execute on the Herdr server host; OpenCode, its tools, and its workspace execute in AgentCore. For unattended operation, the target is **laptop Herdr client → SSH → always-on EC2 Herdr management server and connectors → AgentCore sessions**. Laptop-hosted management remains a development option.

**Scope clarification:** follow Herdr's design and focus on AgentCore-based orchestration. Jindouyun is only a reference for missing execution concepts. Do not turn this plugin into a Jindouyun client or add Cognito, end-user accounts, per-user Runtime ownership, or a separate control-plane/registry service. S3 Files persistence for coding files, configuration, skills, and OpenCode state is explicitly in scope and is the primary persistence target.

## Repository conventions

- Keep the README focused on the goal. Maintain requirements and design in the root files above. Do not recreate a `docs/` tree, publication guides, or a long usage manual unless requested.
- Put all implementation and test code under `src/`: `src/herdr_agentcore/` and `src/tests/`.
- Keep `herdr-plugin.toml`, `pyproject.toml`, `uv.lock`, and CI configuration in their standard root/`.github/` locations.
- Keep the plugin standalone. Use Herdr's public plugin, CLI, and socket interfaces rather than changing Herdr core.
- Local `herdr/`, `agentcore-samples/`, and `agentcore-sdk-python/` directories, if present, are ignored research checkouts. They are not shipped plugin code. Use them as references; do not build a dependency on their local paths or include them in a distribution.
- Inspect Git status, diffs, and relevant history before changing files. Commit, push, or publish only when requested.
- Never commit actual AWS credentials, personal account/resource IDs or ARNs, populated runtime configuration, connection records, or test transcripts. Runtime configuration belongs outside the checkout. Use placeholders or standard fictional account IDs in examples/tests. Before a commit, run the repository privacy guard across working files, index, and history; fix findings without exposing their values.

## Current implementation

Experimental version `0.1.0`, targeting Herdr 0.9.5+, Python 3.11+, macOS/Linux. Dependencies are locked with uv; the AgentCore SDK is pinned to 1.24.1.

| File | Responsibility |
| --- | --- |
| `herdr-plugin.toml` | Five actions and pane entrypoints: setup, new, attach, sessions, stop. |
| `src/herdr_agentcore/cli.py` | CLI, in-pane menus, workflow coordination, explicit stop confirmation. |
| `src/herdr_agentcore/provision.py` | CloudFormation infrastructure/runtime templates, local ARM64 image build/ECR push, owned-stack updates, and connector-profile registration. |
| `src/herdr_agentcore/runtime_image/` | Packaged Docker build context with pinned OpenCode, role-based launcher, HTTP health contract, configuration, and attribution. |
| `src/herdr_agentcore/herdr.py` | Public Herdr command calls and connection metadata. |
| `src/herdr_agentcore/storage.py` | Profile/record validation, atomic persistence, local locks. |
| `src/herdr_agentcore/connector.py` | AWS signing, shell framing, launch-once behavior, reconnect, termination. |
| `src/herdr_agentcore/runtime_aws.py` | Opt-in post-initialization shim for expiration-aware runtime-role credentials. |
| `src/herdr_agentcore/terminal.py` | Raw POSIX terminal I/O, resize signals, detach keys, cleanup. |
| `src/tests/` | Offline behavior tests and optional Herdr manifest validation. |

Use `provision` to build/deploy the included runtime or configure an existing deployment. Provisioning needs local Docker/Buildx plus AWS deployment permissions, creates two owned CloudFormation stacks, and saves a connector profile only after completion. It does not run implicitly when opening a pane. The default remote launcher is `/app/run.sh`; the owned image installs OpenCode inside AgentCore. A cloud Herdr host must have the plugin, dependencies, and runtime profiles installed there; the laptop's plugins/config are not automatically copied to it.

Setup or `configure --runtime-role-credentials` can wrap a PATH-based OpenCode launcher to remove static credentials after initialization and set runtime `AWS_PROFILE=default`. Enable only where that default chain resolves the intended execution role. The management-host `aws_profile` stays independent; saved connection snapshots are unchanged. An absolute OpenCode invocation bypasses the shim. Original argv and wrapped argv must both pass profile validation.

The owned image already sets `AWS_PROFILE=default` and relies on the SDK's execution-role provider/refresh. It never fetches or exports credentials and needs no compatibility shim. Set `OPENCODE_DISABLE_AUTOUPDATE=1` in both the image and launcher to preserve the pinned executable; the updater ignores the additional runtime config's `autoupdate` setting when reading global config. Preserve user configuration, allowlist non-secret PID 1 settings, and forward native OpenCode argv. The current provisioner uses public networking with ephemeral home/state; VPC/S3 Files provisioning and persistent-home integration remain planned. Preserve the adapted sample's NOTICE/LICENSE files in packages and image builds.

The deployed lifecycle settings were read back from AgentCore: **900 seconds idle, 28,800 seconds maximum lifetime**, and no filesystem configurations. Timers apply to each session's compute, not the deployment. The health endpoint currently always reports `Healthy`; it does not report actual OpenCode work as `HealthyBusy`. Do not claim that a connected shell prevents idle expiry, that role-credential refresh extends compute lifetime, or that local connection records preserve ephemeral remote files. Activity-aware reporting, persistence, and recovery remain required for unattended operation.

## Preserve these decisions

1. **Herdr-native identities with durable execution bindings.** Herdr owns workspace/tab/pane/live-agent identity. Use the existing connection UUID as an internal recovery binding, not a new platform resource. Preserve runtime-session/shell IDs for warm reattachment and record persistent paths/conversation IDs for recovery. One session per independent agent is the default, not a restriction against helper/agent shells sharing a runtime session.
2. **Never replay uncertain work.** Persist launch state before sending a command. Do not blindly relaunch on reconnect or resend a prompt after ambiguous delivery.
3. **Detach is not stop.** Closing the WebSocket detaches. Explicit stop terminates the session's compute and processes, not its logical identity or configured persistent data. Do not add shutdown frames to ordinary disconnect cleanup.
4. **Attach and resume are different.** Inspect the shell confirmation's `reconnected` flag. Keep attach strict and never blindly launch into an existing agent. The planned resume operation may deliberately create a replacement shell/process after confirming remote state and loading the saved conversation. A network failure alone is not proof the process ended.
5. **Separate compute, transport, and agent state.** Herdr uses `HERDR_AGENT=opencode` and screen detection. Metadata reports transport health; it must not invent agent lifecycle events. A runtime supervisor must report real work to AgentCore rather than treating socket keepalive as a busy signal.
6. **Keep user state outside installation.** Use Herdr's plugin config/state directories, atomic records, and per-connection locks. Never persist AWS credentials, signed URLs, or raw terminal transcripts.
7. **Treat CLI responses correctly.** Structured Herdr success responses contain `id` and `result`; do not require an `ok: true` field. Quiet commands such as `pane report-metadata`, `pane send-text`, and `pane send-keys` use exit status and may produce empty stdout.
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
uv run python src/tests/repository_privacy.py
uv build
```

Optional validation using an installed Herdr binary:

```bash
HERDR_TEST_BINARY="$(command -v herdr)" uv run pytest
```

That test uses isolated config/state/socket paths and does not start a server or modify the normal user registry. Without the variable it is skipped. Default pytest tests use fake transports, a real local WebSocket server, and a local PTY; they make no AWS calls.

Opt-in live scripts are `src/tests/live_agentcore_smoke.py` and `src/tests/live_herdr_smoke.py`. Both require `--runtime-arn` and optionally `--aws-profile`; they create and stop their own fresh runtime sessions. The Herdr script also creates an isolated local server and performs small model calls. These scripts are not part of default pytest discovery. Obtain authorization for live runs; never substitute an existing work session for their generated test IDs.

The Herdr smoke test accepts `--runtime-role-credentials` to exercise the wrapper and inspect only its own OpenCode process through `InvokeAgentRuntimeCommand`. It returns credential-presence booleans, never values. That optional validation also requires command-invocation permission.

For the owned image, use `--check-runtime-role` instead: launch `/app/run.sh` directly and verify role settings, absence of static credentials, and absence of the legacy shim. The probe refuses to submit into known OpenCode update screens even if Herdr reports idle.

Build the owned image locally with `docker buildx build --platform linux/arm64 --load -t herdr-agentcore-local:1.18.30 src/herdr_agentcore/runtime_image`. Set `HERDR_RUNTIME_TEST_IMAGE=herdr-agentcore-local:1.18.30` for pytest's opt-in Docker configuration and Buildx-discovery checks. Those tests use no AWS/model requests. `provision --plan` is offline; omitting `--plan` creates cloud resources and pushes the image.

The manifest's production build is `uv sync --frozen --no-dev`. After testing that command, use `uv sync --frozen` to restore test dependencies. Keep version numbers aligned in the manifest, package metadata, and `__init__.py`; regenerate the lockfile when dependency/project resolution changes.

## Validation status and next work

- Offline tests, lint/format checks, package builds, and isolated Herdr 0.9.5 manifest validation have passed on macOS/Python 3.13. Re-run relevant checks after changes.
- The repository-owned image was deployed successfully, including ECR/IAM/runtime creation, profile registration, and a subsequent image update. The first test exposed a startup updater dialog; its disposable session was stopped, and explicit updater suppression fixed the launch. A fresh test then passed role-based Bedrock inference, process inspection without static credentials or the legacy shim, same-session detach/reattach, context-aware follow-up, and test-session cleanup. The isolated test server was stopped. Both CloudFormation templates passed `cfn-lint`; local image/bootstrap/provisioning tests also passed. Full credential rotation remains pending. Discover the externally saved profile for current identifiers; never embed them here.
- Live validation on 2026-10-16 passed against an externally configured runtime, with Herdr 0.9.5 and OpenCode 1.18.30: shell input/output and resize, same-PID/environment reattachment, plugin new/attach/stop, a Bedrock model turn through `agent prompt --wait`, and a follow-up turn retaining context after reattachment. All disposable test runtime sessions and isolated Herdr servers were stopped; the original Herdr server remained running. Keep actual deployment identifiers out of repository records.
- Live tests found that Herdr's quiet commands return empty stdout and AgentCore replays buffered output on attachment. Respect quiet-command exit status and avoid mistaking replayed output for new probe results. See DESIGN.md for the validation details.
- Five independent sessions were started and recognized in one tab. Small tiled panes exposed an OpenCode 1.18.30/Bun 1.3.14 native crash: 35×20 failed before any mouse input; 80×20 and 35×40 passed startup plus SGR wheel controls. The exact source-level bug and safe-size boundary remain unknown. Five recovered agents subsequently completed parallel news-retrieval/translation tasks and follow-up corrections, then were stopped on request. Discover current sessions before operating; later user-opened sessions are not disposable probes.
- A live wrapper plus `cloud=connected` and an idle badge can outlast a remote TUI crash. Literal mouse/focus escape sequences may then echo. Verify visible application output, and avoid history reads that inject scrolling into a failed application. The opt-in `src/tests/live_layout_probe.py` reproduces viewport behavior in fresh disposable sessions.
- Literal key echo can also indicate suspension, not a crash. Cloud-5 was observed with remote OpenCode in `T (stopped)` state; identity-checked `SIGCONT` restored the same process/chat. The `exec` launcher leaves no parent shell for `fg`. Distinguish Unix process suspension, agent idle, and stopped AgentCore compute before choosing a recovery action.
- A later Bedrock token-expiry incident came from `/app/run.sh` exporting temporary IMDS credentials once. Host STS access and the shell still worked while OpenCode retained an expired snapshot. An expiration-aware Node provider and model call were verified after removing the snapshot and setting runtime `AWS_PROFILE=default`.
- The affected conversation was manually resumed in the same surviving runtime using a database backup, identity-checked process replacement, a new shell, and the saved OpenCode `--session` value. A follow-up model turn succeeded. The user subsequently requested stopping that old session and opening a fresh session on the owned image; both operations completed and the new agent was ready. Discover current state before operating. The earlier recovery is evidence for process recovery, not an implemented resume action or durable compute recovery.
- The opt-in wrapper passed a separate fresh-session Herdr test: original launcher initialization, model turn, OpenCode environment without static credential variables, detach/reattach, context-aware follow-up, and test cleanup. The externally configured user profile was updated for future launches. Full credential-lifetime rollover remains untested; profile changes do not repair previously launched processes.
- Basic concurrent prompting and result collection are verified. Durable workflow recovery, approval dialogs, forced network outages, small-viewport protection, the full pane resize/layout matrix, long-idle/max-lifetime behavior, and persistent coding-state recovery remain unverified or unresolved.
- No EC2/ECS management deployment, laptop sleep/reboot validation, or automatic management-host recovery has been implemented or verified.
- The Linux/macOS Python 3.11/3.13 CI matrix is configured; remote CI execution and GitHub-managed install/update validation remain pending.
- Publication and marketplace listing have not occurred. A public repository with a valid manifest and the `herdr-plugin` topic is the community distribution route; official endorsement is separate.

Build on the verified single-agent live path: prioritize persistent coding-file requirements (P01–P07) and the remaining multi-agent/lifecycle acceptance cases, then the EC2 management model (H01–H09). Extend binding records with persistent home/cwd, integrate S3 Files and runtime bootstrap/process supervision, and capture OpenCode conversation state. Implement the lifecycle increment (L01–L12): resume, Herdr rebinding, host reconciliation, additional shells, and scoped stop operations. Handle stop completion and retryable provisioning/stop conflicts; the current connector treats non-429 HTTP 4xx responses as terminal. Recovery must not duplicate a launch, tool request, or coordination step.

The current prototype has no S3 Files-backed home/cwd integration, persisted OpenCode conversation ID, additional-shell workflow, recovery supervisor, explicit resume/archive action, or management-host deployment/reconciliation. These are design targets, not verified capabilities. The copied sample's S3 Files mount for shared tools does not establish coding-state persistence. Keep direct AWS IAM authentication; do not add Jindouyun authentication/control-plane dependencies while implementing these gaps.

Before cloud tests, obtain the runtime/profile details and authorization to perform the intended operations. Do not deploy resources, stop existing sessions, alter the user's live Herdr setup, or publish a repository as an incidental test. Use disposable named Herdr sessions for interactive testing.

For handoff, state what changed, which checks actually ran, and what remains unverified. Update these instructions and the requirements/design when implementation decisions change, without adding separate handoff documents.
