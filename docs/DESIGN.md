# Design

## Central decision and implementation status

**Herdr owns workspaces, tabs, panes, and live-agent identity. The plugin binds them to AgentCore execution.**
The target adds persistent coding files and recovery under the existing connection UUID.
It does not introduce a separate end-user platform.

The prototype creates agents, reattaches original PTYs, detaches, and requests compute stop.
Sections marked **target** describe planned behavior.
The current connector refuses to relaunch work when a previously used PTY is missing.

The repository separates runtime definitions, the Herdr connector, and their connection contract.
The runtime component owns example images and official CDK definitions selected through named settings profiles.
The connector accepts deployed ARNs or exported descriptors, including external runtimes.
Opening a pane uses an existing deployment; it does not build infrastructure for each agent.

### Scope of the Jindouyun comparison

Jindouyun is a reference for persistent files, remote Working Directories, multiple shells, skills, and recovery.
It is not a required backend.
Exclude Cognito, per-user account ownership, customer runtime catalogs, DynamoDB registries, and the proposed `agentcore-code` CLI.

| Layer | Responsibility |
| --- | --- |
| Herdr | Layout, live names, terminal presentation, and public prompt/read/wait/key APIs. |
| Plugin | Runtime selection, execution bindings, shell transport, and lifecycle actions. Persistent paths and recovery remain targets. |
| AgentCore | Isolated compute, worker/tool execution, and configured storage. |
| Runtime image | Startup and model access for the selected settings. Work tracking depends on that example's implementation. |
| AWS IAM and host access | Authorize connector and worker operations. Keep human host access separate. |

One runtime session and one shell per independent agent is the default isolation policy.
Additional helper or agent shells in a session remain planned.

The hosting target is one always-on EC2 manager with Herdr, connectors, and coordination.
OpenCode workers run in AgentCore. The laptop provides access and viewing.
The repository has not deployed or validated this EC2 hosting path.

## Architecture

The diagrams use OpenCode as an example. Named runtime settings can select other assistants without changing the connector.

A Herdr server-owned pane runs its connector on the server's host.
The connector uses an authenticated WebSocket to an AgentCore remote PTY.
“Host-local” refers to the management host, which can be a development laptop or a cloud host.

### Laptop-hosted development mode

```mermaid
flowchart LR
    subgraph Local[Developer machine]
        UI[Herdr TUI] --> Server[Herdr server]
        Server --> Pane[Plugin terminal pane]
        Pane <--> Connector[Python connector]
        Connector <--> Store[(Profiles and connection records)]
        Connector -->|Transport metadata| Server
        Credentials[AWS credential chain] --> Connector
    end
    subgraph AWS[AgentCore Runtime]
        Shell[WebSocket Shell API] <--> PTY[Remote PTY]
        PTY <--> OpenCode[OpenCode]
        OpenCode --> Tools[Tools and model inference]
        OpenCode --> Workspace[Coding workspace]
    end
    Connector <-->|SigV4 / terminal bytes / resize| Shell
```

One deployed runtime can serve many sessions.
Each new independent agent gets a separate runtime-session ID and shell ID.

### Cloud-hosted management — recommended target

```mermaid
flowchart LR
    Client[Laptop Herdr client]
    subgraph EC2[Always-on EC2 management host]
        Server[Herdr server]
        Coordinator[Coordinator]
        A[Pane A / connector]
        B[Pane B / connector]
        State[(Retained management state)]
        Role[Instance role]
        Coordinator --> Server
        Server --> A
        Server --> B
        Server --- State
        A --- State
        B --- State
        Role --> A
        Role --> B
    end
    subgraph Runtime[AgentCore]
        WorkerA[Session A / OpenCode A]
        WorkerB[Session B / OpenCode B]
        WorkerA --- FilesA[(Planned persistent workspace A)]
        WorkerB --- FilesB[(Planned persistent workspace B)]
    end
    Client <-->|Native Herdr SSH access| Server
    A <-->|Signed WebSocket| WorkerA
    B <-->|Signed WebSocket| WorkerB
```

This diagram shows native Herdr SSH access.
Alternatively, a standard SSM shell can run the Herdr TUI on EC2, attached to the supervised server.
Standard SSM needs no SSH keys or inbound SSH port.
SSH-over-SSM still needs SSH authentication.
See the [hosting proposal](SESSION_MANAGEMENT_PROPOSAL.md#11-full-cloud-placement-and-responsibility).

The viewer connection and AgentCore sockets have independent owners.
A viewer disconnect must leave the EC2 manager and connectors running.
Coordination can continue only if it also runs in AWS.

Install Herdr, the plugin, dependencies, and profiles on EC2.
Native remote access does not copy them from a laptop.
For the SSH option, this command registers an existing SSH host alias:

```bash
herdr machine add cloudbox
```

This is a setup example, not a deployed resource.
Route laptop-side commands with the appropriate `herdr --machine <saved-profile>`.
Agent and pane IDs belong to the selected server.

### EC2 versus ECS

| Concern | EC2: first target | ECS: later alternative |
| --- | --- | --- |
| Access | Standard SSM to an EC2-side TUI, or native Herdr SSH access. | Supply compatible remote access. ECS Exec is not Herdr's SSH protocol. |
| Management | Supervise Herdr with a service manager such as systemd. | Service replacement starts a new task but loses old processes and sockets. |
| State | Retain EBS-backed files with backup and reattachment rules. | Use external persistent storage with validated locking behavior. |
| AWS identity | Instance role through the SDK chain. | Task role through the SDK chain. |
| Recovery | Reconcile after host/server restart. | Reconcile after task replacement. |

Begin with one active manager.
Add controller leases and idempotent workflow recovery before failover or multiple managers.
A local process lock does not coordinate separate hosts.

### Management-host state and credentials

Retain Herdr configuration/layout state, plugin profiles, execution bindings, and coordinator progress.
Keep installations replaceable. Keep IPC sockets and PID files on local runtime storage.
Define how a replacement host locates retained files; an existing volume alone is not a recovery procedure.

The connector uses the EC2 instance role. OpenCode uses the AgentCore execution role.
Human SSO/SSM access is a third boundary.
The existing Boto3 provider and SigV4 WebSocket path need no protocol rewrite for EC2.
Use `aws_profile: null`, reachable IMDSv2, and a service environment without conflicting static credentials.
Do not forward laptop credentials or export a one-time credential snapshot.

Run the server under the intended service account and session configuration.
A service restart restores availability, not lost connectors or workflow progress.
Automatic reconciliation remains planned.

### Failure boundaries and expected behavior

| Event | Expected behavior |
| --- | --- |
| Viewer closes or laptop sleeps | Keep healthy cloud management and workers running. Do not send stop because viewing ended. |
| Development laptop sleeps | Local connectors and coordination pause. Remote work remains subject to runtime limits. |
| Management host/task restarts | Load retained records and inspect remote work before attachment or replacement. Reconciliation is planned. |
| Shell disappears | Use strict attach or explicit process recovery based on confirmed state. |
| Compute stops | Restore persistent files and conversation on fresh compute. This recovery is planned. |
| Coordinator fails | Restore its own progress and reconcile uncertain outcomes. Server supervision cannot do this alone. |

Management recovery and worker recovery are separate mechanisms. Test both independently and together.
Remote resources can continue to incur costs without a viewer.

### Runtime fleet and session allocation

The fleet consists of sessions created from a runtime configuration.
Use separate profiles for different images, permissions, networks, or storage settings.
Do not deploy a runtime for each pane.

```mermaid
flowchart TB
    Runtime[Deployed runtime configuration] --> A[Session A]
    Runtime --> B[Session B]
    Runtime --> C[Session C]
    A --> ComputeA[Current compute A]
    B --> ComputeB[Current compute B]
    C --> ComputeC[Current compute C]
    A --- StorageA[(Planned S3 Files namespace A)]
    B --- StorageB[(Planned S3 Files namespace B)]
    C --- StorageC[(Planned S3 Files namespace C)]
```

The planned namespaces separate independent work on a configured filesystem.
They do not require per-user access points or a separate registry service.
They are directory organization, not independent IAM security boundaries.
Permit deliberate use of an existing Working Directory without overwriting its files.

## Component responsibilities

```text
src/
  agentcore_runtime/   AWS CDK project and named runtime settings
  herdr_plugin/        herdr-agentcore package
  runtime_contract/   agentcore-contract package
```

Each component has its own README, implementation, and tests. The infrastructure project uses npm/CDK; the connector and Python contract use uv.
Both applications depend on the contract. Neither imports the other application's implementation.
The contract uses only the standard library and has no AWS, Docker, Herdr, or filesystem side effects.

| Component | Responsibility |
| --- | --- |
| `herdr-plugin.toml` | Declare build, action, and pane commands. |
| Connector `cli.py` | Parse commands, import descriptors, display menus, and request stop confirmation. |
| `models.py` | Validate profiles, typed records, launch states, and status labels. |
| `storage.py` | Read/write version-1 JSON, sync atomic replacements, isolate damaged records, and enforce locks. |
| `sessions.py` | Coordinate create, attach, selection, and stop use cases. |
| `agentcore.py` | Resolve credentials, sign handshakes, call stop, and classify AWS/WebSocket errors. |
| `connector.py` | Interpret shell frames, launch once, reconnect, and handle termination. |
| `terminal.py` | Manage raw mode, nonblocking output, bounded input, detach, and resize. |
| `herdr.py` | Call public Herdr APIs and report transport metadata. |
| Runtime `app.ts` and `profile.ts` | Select and read a named settings file. |
| Runtime `runtime-stack.ts` | Define official CDK runtime, IAM, Docker assets, and outputs. |
| Runtime `profiles/` | Supply example settings such as `opencode` and `codex`; names are not enums. |
| Runtime `common/` | Share the Dockerfile, startup, environment inheritance, HTTP health, work-lease reader, and license. |
| Runtime `opencode/image/` | Supply the OpenCode adapter, configuration, dependency warmup, and work-event plugin. |
| Runtime `codex/image/` | Supply the Codex adapter with its native AWS provider. |
| Contract `connection.py` | Validate and encode connection data without operational side effects. |
| `src/*/tests/` | Hold each component's offline tests and applicable live probes. |

Connector modules are under `src/herdr_plugin/herdr_agentcore/`.
Runtime modules are directly under `src/agentcore_runtime/`, with definitions in `opencode/` and future assistant folders.
Contract modules are under `src/runtime_contract/agentcore_contract/`.
Profile formats are not publicly released. Internal version fields do not imply a backward-compatibility promise.
Infrastructure has no custom provisioning executable or Python distribution. Use the official CDK CLI.
Storage offers typed records and mapping helpers.

### Connection contract

The runtime publisher exports descriptor version 1 with transport `agentcore-shell-v1`.
It contains ARN, region, endpoint, required argv, an optional `runtime_profile` settings reference, and an optional `agent_kind` recognition hint.
The connector validates and imports that data, then adds local AWS credential selection.
Credentials and host AWS credential-profile names do not belong in the descriptor.
Runtime profile names do belong in the descriptor as references to the settings used to deploy it.
For example, a profile named `reviewer` can supply an OpenCode image and hint. No connector branch is needed for that name.
See the [contract README](../src/runtime_contract/README.md) for the complete shape.

Direct ARN registration can set the same fields explicitly.
All profiles with no hint use an ordinary terminal. The connector never infers OpenCode or a launch command.
Herdr must support an agent kind before its recognition hint can enable agent APIs.
An API-only runtime does not become a terminal assistant merely because its ARN is valid.
The contract does not yet define persistent checkpoints or resume operations.
The supplied `opencode` settings declare `/app/run.sh`. CDK context can override the declared command.
The override changes descriptor argv, not the image's container `CMD`. The selected executable must exist in the runtime.
See the [existing-runtime guide](CONNECT_EXISTING_RUNTIME.md) for registration and verification.

## Repository-owned runtime and provisioning

Standard `cdk deploy` deploys the named runtime settings independently of the connector.
The supplied OpenCode and Codex images adapt `awslabs/agentcore-samples`.
Repository, package, and image retain its Apache-2.0 license and NOTICE.
No research checkout, GitHub gateway, or shared sample deployment file is required.

### Deployment sequence

1. Select `profiles/NAME.json` with CDK context `runtimeProfile=NAME`.
2. Confirm the AWS identity, target region, and CDK bootstrap environment.
3. Run `cdk synth` to validate the application and generate its template/asset manifest.
4. Run `cdk diff` and review IAM, image, runtime, and output changes.
5. Run `cdk deploy`. CDK builds and publishes the ARM64 Docker asset through the bootstrap repository.
6. CloudFormation creates or updates the execution role, policies, and native `AWS::BedrockAgentCore::Runtime` resource.
7. CDK writes resolved outputs to the private `--outputs-file` path after success.
8. Import the selected stack's `ConnectionDescriptor` with the connector.

The supplied settings name the stacks `HerdrOpenCodeRuntime` and `HerdrCodexRuntime`.
These are example profile properties, not connector constants.
Role trust restricts access to the account and matching runtime name. CDK's repository grant supplies image-pull access.
Model permissions follow the profile's inference service. The OpenCode example uses Bedrock Runtime; the Codex example uses Mantle.
The same generic stack consumes both settings files.

The official libraries are `aws-cdk-lib`, `constructs`, and the `aws-cdk` CLI.
The project uses TypeScript, Node.js 22+, npm, and Docker with ARM64 support.
The existing CDK bootstrap provides deployment roles and asset storage. It is shared infrastructure, not part of the runtime's teardown.

Runtime model authorization is separate from deployment authorization. Verify model availability and account access.
The example stack uses IAM authentication, public networking, HTTP health, 900-second idle timeout, and a 28,800-second maximum lifetime.
Deployment does not create an assistant session. The new-agent action does that.

### Runtime bootstrap and authentication

The image defaults to OpenCode 1.18.30 and checks its installed version during build.
Its HTTP service runs as an unprivileged user.
Both supplied profiles use `common/Dockerfile` with explicit npm package/version, executable, and adapter directory arguments.
CDK stages shared files and the selected adapter only; another adapter's changes do not invalidate this image asset.
The shared `/app/run.sh` executes `launch.py`, which uses `/app/assistant.py` for environment and argument preparation.
The OpenCode adapter forwards native argv, including `--session`, and selects `OPENCODE_WORKDIR` or existing `HOME`.
It preserves user configuration and does not grant automatic tool approval.

The OpenCode adapter sets `OPENCODE_DISABLE_AUTOUPDATE=1` for launch and build-time dependency warmup.
OpenCode's updater reads global configuration; the extra config's `autoupdate: false` alone did not suppress its dialog.

`OPENCODE_CONFIG=/app/opencode.json` supplies the Bedrock provider, region, and model.
`AWS_PROFILE=default` selects OpenCode's refreshable Node provider chain inside AgentCore.
Without injected keys or credential files, the chain resolves the execution role.
The launcher does not fetch IMDS credentials, export keys, or save tokens.
It copies only allowlisted non-secret deployment settings from PID 1 when the shell lacks them.

The image includes a local OpenCode activity plugin and health reader.
The build resolves plugin SDK dependencies so the default home can load the hook without package downloads.
The deployed image still has ephemeral coding state and no S3 Files mount.

The Codex example pins version 0.163.0 and selects the native `amazon-bedrock` provider.
It forwards native argv, keeps approvals enabled, and does not overwrite user configuration or generate a one-time bearer token.
Both images use the shared health reader. The Codex adapter has no work-event source, so it currently supplies readiness only.
See the [runtime comparison and status evidence](../src/agentcore_runtime/README.md#opencode-and-codex-comparison) for Herdr's separate native support and remaining validation gaps.

### Updates, failures, and cleanup

Use `cdk diff` and `cdk deploy` with the same stack, profile, account, and region.
New sessions use the new image. Existing processes do not restart or reload their environment.

When surviving sessions need earlier Bedrock models, declare those IDs through `retainedModelIds` context.
CDK does not read and merge arbitrary prior IAM policies. Its declared configuration is authoritative.
Review removals before updating. CloudFormation rollback does not create a transaction across every asset and local profile.
A failed deployment can leave published assets or a failed stack. Inspect standard CDK/CloudFormation events before retrying.
The connector profile changes only through explicit registration of successful outputs.

For teardown, stop the selected runtime's sessions, then use `cdk destroy` for its stack.
Keep shared CDK bootstrap resources. Their asset retention and garbage collection are separate operations.
Remove a local connection profile separately if it is no longer required.
Earlier two-stack custom-provisioner results are historical evidence, not the current deployment procedure.

## Herdr integration

The plugin declares five actions and matching pane entrypoints:

- `agentcore.setup`: configure a runtime profile.
- `agentcore.new`: start an agent with the selected/default profile.
- `agentcore.attach`: reattach a saved connection.
- `agentcore.sessions`: show last-known records.
- `agentcore.stop`: confirm whole-session stop for detached work.

Actions use `herdr plugin pane open` with the invocation context's target.
They execute on the selected Herdr server host.
The connector re-executes with the saved `agent_kind` as `HERDR_AGENT` so Herdr can recognize the host-side wrapper.
An ordinary terminal profile clears inherited hints. Existing OpenCode-only profiles retain their old behavior.

Herdr lifecycle remains screen-derived.
The connector publishes separate `cloud` and `connection` metadata tokens.
Transport connectivity and cached screen output do not establish current agent health.
The standard OpenCode-to-Herdr socket integration cannot directly reach a host socket from an AgentCore microVM.
A remote lifecycle relay remains planned.

### Herdr-native orchestration

After agent recognition, use `agent list`, `agent prompt`, `agent read`, `agent wait`, and `agent send-keys`.
`agent start --kind opencode` selects a local canonical executable; it is not an AgentCore deployment API.
A host-side script or master agent can coordinate multiple worker panes through public APIs.
Cloud workers do not automatically gain access to the manager's Herdr socket.

### Default and controller-selected runtime profiles

New-agent selection uses this order:

1. Explicit `--profile`.
2. Controller-supplied `HERDR_AGENTCORE_PROFILE`.
3. Saved `default_profile`.

`action new --profile NAME` forwards the override through Herdr's public `--env` option.
`new` and `menu new` use the same precedence.
Attach and stop use the saved target and reject an explicit profile override.

`set-default NAME` validates the profile and writes configuration under its lock.
The first profile becomes default; later saves preserve the choice.
Selection and snapshot come from one configuration read.
Changing defaults does not change saved connection targets.

Configuration formats are unreleased. There is no historical-name or single-profile fallback.
Without `default_profile`, require an override or `set-default`. Do not guess, open a picker, or fall back from invalid input.
The `profiles` command retains its output shape.

Offline precedence and snapshot tests pass.
An earlier two-profile cloud probe selected the default without input and passed model/attach/follow-up/stop checks.
That probe waits for a detached pane to close before invoking the next action.

### Additional shells and operation scope — target

```text
Herdr workspace/tab
  Implementation pane → session A / shell 1 → OpenCode conversation 1
  Test pane           → session A / shell 2 → ordinary build/test shell
  Review pane         → session B / shell 3 → OpenCode conversation 2
```

Each pane binds to one shell. Session sharing is deliberate.
Only actual agent panes receive the OpenCode hint.
Add separate detach, shell/process stop, and session stop before shared-session panes.
Whole-session stop affects all shells and must identify that scope.

## Agent identity and storage

| Identity | Meaning |
| --- | --- |
| Connection/binding UUID | Canonical saved execution identity. Reuse it for future recovery. |
| Runtime ARN + endpoint + session ID | Remote execution context. A session ID alone is not portable across deployments. |
| Shell ID | One PTY lifetime. Reuse for warm attachment; replace only during explicit recovery. |
| OpenCode conversation ID | Saved conversation to resume. Not yet captured automatically. |
| Herdr server/session + pane ID | Current attachment. Pane IDs can change and are server-scoped. |
| Herdr agent name | Live alias with uniqueness rules. It is not the durable key. |

Configuration is `HERDR_PLUGIN_CONFIG_DIR/config.json`.
Records and locks are under `HERDR_PLUGIN_STATE_DIR`.
These locations belong to the management host, not necessarily the viewing laptop.
Standalone CLI use also supports XDG defaults and directory overrides.

Version-1 records contain a profile snapshot, remote IDs, launch state, status, and timestamps.
`ConnectionRecord` validates required fields, enums, UUIDs, and timezone-aware timestamps at the storage boundary.
Unknown recovery annotations survive round trips.
Lists warn about damaged records and continue with healthy records; explicit loading still fails.
Records sort by creation instant, including timezone offsets.

Writes sync the temporary file, replace the destination atomically, then sync the parent directory.
Attachment and stop use a local per-connection lock.
The lock file remains in place so another process cannot acquire a different inode for the same connection.

### Target execution-binding records

Migrate the record to include persistent paths, conversation ID, checkpoint/version metadata, desired name, and current attachment.
Keep the host-local store initially. Do not add a customer registry service.

```mermaid
flowchart TB
    Binding[Durable connection UUID] --> Session[Runtime / endpoint / session]
    Binding --> Conversation[Saved conversation]
    Binding --> Files[(Persistent files and checkpoint)]
    Binding --> Attachment[Current attachment]
    Attachment --> Shell[Shell ID]
    Attachment --> Pane[Herdr server / session / pane]
```

Restore a desired name only after the recovered agent is recognized.
Report occupied or ambiguous names instead of replacing unrelated agents.
Short metadata prefixes are for display/discovery; resolve a unique full UUID before operations.
Unknown remote IDs need an explicit adoption flow. Do not guess the shell or conversation.

## Persistent coding files through S3 Files

**Target:** consume an S3 Files access point mounted by the runtime.
Mount/root are deployment settings, not per-user identity resources.
Example configuration shape:

```json
{
  "filesystemConfigurations": [
    {
      "s3FilesAccessPoint": {
        "accessPointArn": "<configured-s3-files-access-point-arn>",
        "mountPath": "/mnt/s3files"
      }
    }
  ]
}
```

Proposed layout:

```text
/mnt/s3files/
  mcp/                              Shared tools, if configured
  herdr/<binding-uuid>/
    repo/                           Files, .git, and uncommitted changes
    config/                         Non-secret tool configuration
    skills/                         Configured worker skills
    artifacts/                      Selected results
    checkpoints/                    Consistent application backups
    recovery.json                   Identity and recovery metadata
```

Configure persistent `HOME` or supported data directories without hiding installed executables.
Record the remote Working Directory separately from the management-host pane directory.
Reuse saved paths after attachment or replacement.
Give independent writers separate worktrees and conversation state by default.
Validate skill discovery; placing files in a directory alone does not configure it.

### Bootstrap and filesystem behavior

- Check the mount before launch. Do not silently fall back to ephemeral storage.
- Initialize defaults once. Preserve existing files and configuration on later launches.
- Replace the external sample's forced home/directory and config rewrite when integrating persistence.
- Validate Git, package managers, rename/flush, locking, crash recovery, and concurrent access.
- Keep live SQLite state on local disk initially. Publish consistent backups to S3 Files.
- Do not copy only a live `.db` file or assume SQLite WAL works on a network filesystem.
- Keep PIDs, sockets, health leases, and disposable caches local and ephemeral.
- Validate conversation/checkpoint compatibility before process replacement.
- Coordinate bootstrap and recovery so they cannot create duplicate writers.

S3 Files needs VPC connectivity, mount targets, execution-role permissions, and correct access-point UID/GID.
Directory namespaces are not IAM isolation boundaries.
Define backups, retention, and migrations. Detach, stop, and uninstall must not delete persistent work.

Managed session storage Preview is a later option with different semantics.
The reviewed documentation describes reset after 14 days without invocation and after runtime-version changes.
AgentCore Instances with capacity-provider EBS are another compute choice; they are not the current microVM deployment.
See the [checkpoint proposal](SESSION_MANAGEMENT_PROPOSAL.md#6-opencode-database-and-checkpoint-strategy).

Persistent-home/cwd integration, automatic conversation capture, and this storage layout remain unimplemented.

## Resume semantics — target

| Situation | Required action | Preserved identity |
| --- | --- | --- |
| Original PTY/process survives | Reattach without launch. | Binding, session, shell, conversation. |
| Compute survives; original PTY unavailable | Inspect the process/supervisor. Attach surviving work or confirm exit before explicit resume. | Binding, session, paths, conversation; shell may change. |
| Compute stopped | Reuse session ID, remount storage, validate state, and resume in a new shell. | Binding, session, files, conversation. |
| Storage missing/incompatible | Report recovery required. Require explicit repair or migration. | Binding and failure evidence. |

Recovery is explicit, not an automatic reconnect retry.
It restores files and saved conversation state, not memory, running tools, or an instruction pointer.
A socket failure does not prove that a writer stopped.
A supervisor or named `tmux` session may decouple work from one PTY while compute survives; neither is installed by this plugin.

```mermaid
flowchart TD
    Resume[Resume saved execution] --> Registry[Resolve binding and saved state]
    Registry --> Live{Original PTY alive?}
    Live -->|Yes| Attach[Reattach without launch]
    Live -->|No or unknown| Inspect[Inspect process and recovery state]
    Inspect --> Known{Replacement confirmed?}
    Known -->|No| Uncertain[Report uncertain; do not relaunch]
    Known -->|Yes| Data{Checkpoint valid?}
    Data -->|No| Recovery[Recovery required]
    Data -->|Yes| Bootstrap[Exclusive bootstrap and conversation resume]
    Bootstrap --> Bind[Bind shell and Herdr pane]
    Attach --> Bind
```

### User-facing lifecycle operations

| Operation | Contract | Status |
| --- | --- | --- |
| New | Allocate independent binding/session; initialize or explicitly select files. | IDs and launch implemented; persistence pending. |
| Attach | Reattach original live PTY. | Implemented. |
| Detach | Disconnect transport without stop. | Implemented. |
| Stop runtime session | Stop all session compute/processes; keep records and persistent files. | API request implemented. No completion waiter or resume. |
| Stop shell/process | Stop selected execution without affecting siblings. | Planned. |
| Resume | Choose warm attachment or confirmed checkpoint recovery. | Planned. |
| Archive | Mark work finished and retain/export results. | Planned. Data deletion is separate. |

The WebSocket adapter retries classified transient errors, including explicit `RetryableConflictException`.
Unknown HTTP 409 responses remain terminal. Retry never changes session identity or replays work.
Bounded provisioning/stop conflict handling and stop-completion detection remain recovery work.

### Independent state dimensions

| Dimension | Examples | Authority |
| --- | --- | --- |
| Compute | running, stopped, recovering, unknown | AgentCore and future supervision. Local records are observations. |
| Connection | attached, detached, reconnecting | Connector. |
| Agent work | working, idle, waiting, unknown | Herdr screen detection; separate OpenCode-derived AgentCore health. |

The version-1 `stopped` label means the API accepted a stop request, not confirmed completion.
Idle is not stopped compute. Detach is not task completion.
The health bridge does not relay lifecycle events to Herdr or supervise recovery.

## Current launch and reattach sequence

```mermaid
sequenceDiagram
    actor User
    participant Herdr
    participant Service as SessionService
    participant Connector
    participant Store
    participant Shell as AgentCore Shell
    User->>Herdr: New or attach
    Herdr->>Service: Open plugin pane
    Service->>Store: Create/load record and lock
    Service->>Connector: Attach recorded target
    Connector->>Shell: Signed WebSocket with saved IDs
    Shell-->>Connector: Shell ID and reconnected flag
    alt Launch not attempted
        Connector->>Store: Sync attempted state
        Connector->>Shell: Send launch once
        Connector->>Store: Save sent state
    else Original PTY confirmed
        Note over Connector,Shell: No repeated launch
    else Original PTY missing
        Connector->>Store: Mark expired
        Connector-->>User: Explicit recovery required
    end
    loop Connected
        Herdr->>Connector: Input or resize
        Connector->>Shell: STDIN or RESIZE
        Shell-->>Connector: Output
        Connector-->>Herdr: Await nonblocking terminal write
    end
```

The OpenCode definition supplies `["/app/run.sh"]` unless its caller overrides it.
The generic contract and connector require explicit argv and provide no default.
The connector quotes each argument and sends `exec env TERM=xterm-256color COLORTERM=truecolor ...`.
Persisting `attempted` is mandatory before sending the launch.
If delivery is uncertain, show the existing terminal rather than send another command.

### Historical sample credential adaptation

An earlier prototype used a shim for external sample images that exported static credentials.
The current example launchers use native role providers directly. The old custom runtime CLI has been removed.
External image owners can supply a reviewed wrapper through explicit argv when required.
The connector does not implement or choose runtime authentication.

That wrapper resolved the real executable, created a private temporary shim, and prepended it to `PATH`.
It then runs the original launcher.
When the launcher invokes OpenCode, the shim removes four static credential variables and sets `AWS_PROFILE=default`.
It executes the original binary with unchanged arguments.

The removed variables are `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, and `AWS_SECURITY_TOKEN`.
Removal must occur after initialization because the sample launcher exports a fresh snapshot during startup.
The shim preserves generated region/model/MCP configuration.
Host `aws_profile` remains independent from runtime `AWS_PROFILE`.

Validate original argv before wrapping and validate the wrapped result.
Absolute OpenCode paths bypass the shim. Explicit provider credentials, files, or API keys can select a different identity.
Enable it only where the default chain resolves the intended role.
The temporary shim is ephemeral; automatic process repair and full-lifetime rollover tests remain separate work.

## Current connector transport and lifecycle behavior

```mermaid
stateDiagram-v2
    [*] --> Created
    Created --> Connecting
    Connecting --> Connected: Shell confirmed
    Connected --> Reconnecting: Transient loss
    Reconnecting --> Connected: Original PTY confirmed
    Connected --> Detached: Detach
    Reconnecting --> Detached: Detach
    Detached --> Connecting: Explicit attach
    Connecting --> Expired: Original PTY missing
    Connected --> Expired: Platform shutdown
    Reconnecting --> Error: Retry window elapsed
    Connected --> Exited: Shell exit
    Connected --> TakenOver: Remote takeover
    Detached --> Stopped: Stop request accepted
```

- Resolve/refresh credentials outside the event loop, then sign each handshake.
- Use the SDK signing helper with direct framing so confirmation remains visible.
- Forward output bytes without decoding. Bound WebSocket buffers and input chunks.
- Await nonblocking partial writes. A full PTY buffer must leave timers, resize, and detach responsive.
- Remove write callbacks on cancellation. Restore modes with `TCSANOW`, without waiting for output drainage.
- Forward dimensions initially, after resize, and after reconnect.
- Pause and discard input during outages. End the connector after ambiguous input delivery.
- Classify errors from safe codes/status, not raw bodies or signed URLs.
- Retry HTTP 429, server failures, and known transient codes within the configured reconnect window.
- Reject competing local attachments with the lock. Do not reconnect after remote takeover.
- Ctrl+] then `d` detaches. Ctrl+] twice sends a literal prefix.
- Stop requires confirmation and the lock. It targets all compute in that runtime session.

### Deployed session lifecycle

The runtime control API confirmed `idleRuntimeSessionTimeout: 900`, `maxLifetime: 28800`, and no filesystem configurations.
These values come from `runtime_template()` in `deployment.py`.

| Limit or operation | Meaning |
| --- | --- |
| Idle | Platform-determined inactivity can stop compute after 15 minutes. Invocation activity and `HealthyBusy` affect accounting. |
| Maximum | Compute ends after 8 hours. Activity, reattachment, and credential refresh do not reset the clock. |
| Threshold timing | The reviewed AWS documentation allows up to 15 seconds for termination after a threshold. |
| Scope | Each session has its own compute/timers. Termination does not delete the deployment, role, image, or local record. |
| Detach | Close transport without requesting termination. |
| Stop | Request whole-session termination. No completion waiter exists. |
| Data | Current coding files and conversation state are ephemeral. Saved IDs cannot reconstruct them. |

Full-duration platform expiry tests remain pending.
The exact effect of interactive Shell traffic on idle accounting has not been validated here.

### Activity-aware health — deployed and validated

The earlier deployed bridge used session events and per-session question/permission waits.
It passed cloud tests for work, a question/reply cycle, completion, and process death.
The current concurrency revision is deployed. Fresh cloud activity and model/attachment probes passed on the updated image.
Concurrent and nested-tool wait cases have offline event-test coverage; live permission-dialog coverage remains pending.

The current `activity-plugin.mjs` uses public OpenCode 1.18.30 `event`, `dispose`, `tool.execute.before`, and `tool.execute.after` hooks.
The tracker also reads tool-part events so errors can clear work even without an after hook.
It keeps session status, active tool-call IDs, and wait-request IDs in memory.

Rules:

- Session `busy` and `retry` indicate work until completion or an input wait.
- A scoped wait blocks its associated tool, not every tool in the session.
- Other active tools and sessions keep health busy.
- Task metadata can link a parent call to a child session. A known child wait propagates through that task.
- A parent with other active tools remains busy. A background child can remain busy after its parent becomes idle.
- Unknown child activity or a malformed cycle remains conservatively busy.
- Unscoped waits suppress an unambiguous sole tool or a question tool. Ambiguous parallel work remains conservative.
- A model error does not prove concurrent tools stopped. Tool completion/error events and session idle clear their state.

Each plugin instance writes a private atomic lease under `/tmp/herdr-agentcore-activity` only while busy.
The lease contains version, PID, Linux start tick, timestamp, and busy flag.
It contains no session graph, prompt, tool argument, credential, or conversation text.
Busy heartbeats run every 10 seconds. Idle and disposal remove the lease and timer.

The shared `common/activity.py` accepts leases no older than 45 seconds with a matching live PID/start tick.
It rejects stopped, zombie, exited, reused-PID, malformed, oversized, symlink, and future-dated records.
No valid lease means `Healthy`; valid work means `HealthyBusy`.
Internal lease timestamps never become a continuously advancing AWS `time_of_last_update`.

Sixteen minutes of work followed by an unanswered question can start the idle window at minute 16.
With no other tracked work, the 15-minute threshold is around minute 31.
The 8-hour maximum remains unchanged.

The bridge does not track arbitrary detached OS jobs.
`--pure` or replacement configuration can disable external hooks.
It is neither persistent storage nor a recovery supervisor.
Publish an image update and start fresh processes to deploy a changed hook.

## Implementation increments

1. Extend dialog, forced-network-outage, and pane-layout coverage.
2. Migrate bindings to persistent paths, conversation IDs, and checkpoint/version metadata.
3. Integrate S3 Files, safe checkpoints, and runtime-side recovery supervision.
4. Deploy one supervised EC2 manager with retained state, instance-role access, and validated SSM/SSH access.
5. Add explicit resume, Herdr rebinding, host reconciliation, and bounded stop/provisioning conflict handling.
6. Add helper/agent shells with separate shell and whole-session stop scope.
7. Test replacement, expiry, competing recovery, and uncertain tool outcomes before failover or ECS hosting.

These increments require no Cognito or Jindouyun platform dependency.

## Packaging and validation

The shared-image refactor passed local checks and later cloud E2E tests on separate disposable deployments for both examples.
Both passed real model calls through Herdr, credential inspection, detach/attachment, follow-up context, and explicit stop requests.
OpenCode also passed deployed activity-health checks. Codex work-event reporting, sandbox/tool execution, and long-duration behavior remain gaps.
Both temporary stacks and runtimes were confirmed deleted. One native CloudFormation deletion timeout required a retry after the runtime was confirmed absent.
Detailed findings and warnings are recorded in the runtime root README. The historical sections below describe prior implementations.
The refactor passed 180 Python tests with both rebuilt images, six CDK tests, and TypeScript checks.
The full assistant comparison and Herdr detection evidence are maintained only in the runtime root README.
After disposable qualification and commit, the shared images were deployed to persistent OpenCode and Codex stacks.
Both runtimes and their DEFAULT endpoints reached READY. Herdr imported both CDK output descriptors and retained OpenCode as its default.
New sessions on both persistent deployments passed the model/role/attachment/follow-up/stop probe. OpenCode's activity-health probe also passed.
The persistent deployments remain available after cleanup of the probes' own sessions and servers.

Herdr installs from a public GitHub repository with a root manifest.
The build command is `uv sync --frozen --no-dev`; it installs only the connector and its dependencies, including the contract.
Runtime infrastructure is a separate npm/CDK project, not a Python package or console entrypoint.
Community discovery uses the `herdr-plugin` topic. Publication and official endorsement are separate.

Code and tests live inside the three `src/` components. Each has a README and package metadata.
Each wheel includes only its component. Only the runtime wheel includes images and provisioning code.
Each source distribution includes its component code, tests, README, and applicable licenses.
Root architecture documents and the Herdr manifest remain repository-level files.
See the [plugin review](PLUGIN_GUIDELINES_REVIEW.md).

```bash
uv sync --frozen
uv run --frozen ruff check src
uv run --frozen ruff format --check src
HERDR_TEST_BINARY="$(command -v herdr)" uv run --frozen pytest -q --tb=short
uv run --frozen python src/herdr_plugin/tests/repository_privacy.py
uv build --all-packages
```

Default tests use fake transports, a local WebSocket server, and local PTYs. They make no AWS calls.
The optional Herdr binary test uses an isolated disabled registry.
Node tests cover activity events; Python tests cover process-bound leases and HTTP health.

The CDK/profile implementation passed 174 Python tests with both image-test flags enabled, including descriptor/import, explicit-command, recognition-hint, and dependency-boundary checks.
Five CDK tests check native resources, profile selection, command output, and scoped permissions. Both example profiles synthesize successfully.
ARM64 runtime tests cover OpenCode health transitions and Codex CLI startup. Later cloud tests verified both model paths; Codex has no busy-health claim.
The connector and Python contract build two wheels and source distributions. Infrastructure has separate CDK assertions and synthesis checks.
Isolated wheel installations passed descriptor export/import. Neither application required the other application package.
Documentation checks passed for 11 Markdown files, 57 local links, and 56 requirement IDs. Privacy and formatting checks passed.

The old runtime and its two custom-provisioned stacks were deleted after inspection. The six saved sessions were already expired.
Old ECR images remain under the original retention policy.
The selected `opencode` settings were deployed with official CDK, and the runtime and DEFAULT endpoint reached READY.
The production connector was reinstalled/relinked and imported the stack's `ConnectionDescriptor` output.
Fresh cloud tests passed shell/model activity, question wait/reply, process-death cleanup, role-only inference, default selection, attachment, and conversation continuity.
Both disposable test-session stop requests succeeded. The isolated test server was stopped.
The final CDK diff against the new deployment reported no differences.
The results below describe earlier revisions.

The earlier refactor passed **170 offline Python tests**. Three Docker tests were skipped in that run.
All nine image tests then passed against the full ARM64 image built and pushed by the provisioner.
Those tests include configuration, Buildx discovery, and real OpenCode shell activity with networking disabled.
Earlier direct Dockerfile builds timed out while resolving public-base metadata, including a longer retry.
An intermediate local overlay image passed tests. The later full provisioner build succeeded with its temporary Docker configuration.
The deployed artifact came from that full build, not the intermediate overlay.

Current tests cover typed record errors, extra-field preservation, atomic sync order, safe error classification, launch identity, and terminal backpressure.
Deployment tests now cover unreadable templates, image failure before IAM changes, policy/runtime failure, retained statements, and descriptor publication last.
The earlier implementation was deployed after its checks. The updated runtime and default endpoint reached READY.
Fresh probes verified shell work, model generation, question wait/reply/completion, and process-death cleanup through the deployed health service.
A separate isolated Herdr probe passed default selection, role-only Bedrock inference, detach/reattach, and a context-aware follow-up.
Both disposable runtime sessions and the isolated Herdr server were stopped.
The saved default profile is now `opencode-agentcore-runtime`. Actual deployment identifiers remain outside the repository.
The dated sections below retain evidence from earlier revisions.

### Live validation — 2026-10-16

The baseline used Herdr 0.9.5, OpenCode 1.18.30, and Bedrock Claude Sonnet 4.5.
Probes used fresh runtime IDs and isolated Herdr servers/configuration/state/sockets.
They stopped all their own sessions and servers. They left the caller's server running.
Actual deployment and session identifiers remain outside the repository.

Verified:

- Authenticated Shell input/output and sizes 88×25 and 100×35.
- Same-PID and same-environment attachment to the original PTY.
- Plugin new, recognition, prompt/wait, context-aware follow-up, and confirmed stop.
- Presence of the external sample's `/mnt/s3files` directory, but not coding-state persistence.

Quiet Herdr commands can return empty stdout on success. The adapter now uses their exit status.
AgentCore also replays buffered output on attachment. Probes select the newest result before a unique completion marker.

After authorizing a live test, use one of these commands:

```bash
uv run python src/herdr_plugin/tests/live_agentcore_smoke.py --runtime-arn "$RUNTIME_ARN"
uv run python src/herdr_plugin/tests/live_herdr_smoke.py --runtime-arn "$RUNTIME_ARN"
uv run python src/herdr_plugin/tests/live_herdr_smoke.py --runtime-arn "$RUNTIME_ARN" --connection-file "$CONNECTION_FILE"
uv run python src/herdr_plugin/tests/live_herdr_smoke.py --runtime-arn "$RUNTIME_ARN" --check-runtime-role
uv run python src/agentcore_runtime/tests/live_runtime_activity.py --runtime-arn "$RUNTIME_ARN" --model-turn
```

Use optional `--aws-profile` for host identity selection.
The Herdr probe needs a Herdr-managed pane and makes small model calls.
Role inspection needs command-invocation permission and returns only presence/profile/shim booleans, never credential values.
The activity probe uses the existing health process and answers only its controlled Continue/Stop question.
All scripts stop their own generated sessions. They are excluded from default pytest discovery.

### Owned-runtime and activity cloud validation

Earlier tests passed ECR/IAM/runtime creation, profile registration, and a digest-pinned image update.
Both generated CloudFormation templates passed `cfn-lint` at that baseline.
An initial updater dialog intercepted a test prompt; that disposable session was stopped.
Explicit updater suppression fixed startup. Probes now refuse known update screens before prompting.

Fresh owned-image tests passed role-based Bedrock inference without static credentials or the legacy shim.
They also passed same-session attachment, a context-aware follow-up, and cleanup.
Full credential rollover remains unverified.

Earlier activity cloud tests observed shell work, model generation, a pending question, reply, completion, and process death through the actual `/ping` service.
The question wait was idle; the reply resumed busy reporting.
A separate Herdr model/role/attachment probe passed on that image.
Live permission-dialog behavior and full-duration idle/max-lifetime expiry remain unverified.

### Concurrent startup and small-viewport failure — 2026-10-16

Five independent sessions were recognized in one Herdr tab.
A narrow tiled layout exposed an OpenCode 1.18.30/Bun 1.3.14 Linux ARM64 native crash.
A local-PTY-controlled cloud probe reproduced it before mouse input.

| Dimensions | Before mouse input | After valid SGR wheel input |
| --- | --- | --- |
| 35×20 | Bun segmentation fault during startup. | Not attempted after failure. |
| 80×20 | Input widget ready. | No crash or literal wheel echo. |
| 35×40 | Input widget ready. | No crash or literal wheel echo. |

The exact source defect and complete safe-size boundary remain unknown.
Literal mouse sequences appeared after failed TUIs; the test does not establish malformed mouse input as the initial cause.
A live wrapper and idle badge can outlast a failed remote UI.
Check visible output and avoid uncontrolled input or scrolling into a failed application.

The five agents were recovered with zoomed presentation as `cloud-1` through `cloud-5` in tab label `2`.
They completed work and were stopped on request. Failed-startup and diagnostic sessions were also stopped.
Zooming is a workaround, not a renderer fix.
`live_layout_probe.py --runtime-arn ... --cols ... --rows ...` reproduces dimensions using its own disposable session.
No upstream viewport issue was filed or fix deployed by this project.

### Suspended process with literal key echo — separate observed case

A later inspection found OpenCode in `T (stopped)` state, consistent with suspension such as Ctrl+Z.
This was not proof of another crash.
After identity checks, `SIGCONT` restored the same process, UI, and conversation.
Typed characters remained in the input draft.

The `exec` launcher leaves no parent shell for `fg`.
Distinguish suspension, agent idle, process exit, and stopped compute before recovery.

### Parallel workload validation — 2026-10-16

Five agents fetched separate public news feeds and translated ten headlines each into Chinese.
Herdr submitted concurrent prompts and collected all results.
Follow-up prompts corrected a translation and refreshed entries.
On request, all five connectors detached and their runtime sessions stopped.

This verifies basic concurrent work and follow-up, not durable coordination recovery.
Forced outages, the full layout/resize matrix, EC2 hosting, and persistent coding-state recovery remain pending.

### Runtime credential expiry and conversation recovery — 2026-10-16

A long-lived session returned `The security token included in the request is expired` after laptop sleep.
Host STS and the terminal still worked.
Redacted inspection showed a static OpenCode credential snapshot while IMDS had current credentials.
Reattachment could not change that process environment.

Removing static variables and setting `AWS_PROFILE=default` produced refreshable credentials and a successful headless model call.
Manual recovery then preserved the conversation:

1. Identify the saved conversation and home.
2. Back up the database.
3. Detach the connector.
4. Confirm the old process identity and exit before replacement.
5. Allocate a new shell in the surviving runtime session.
6. Launch OpenCode with its original `--session` and role-provider setup.
7. Update the private binding and reattach in Herdr.

A new model turn succeeded. Earlier errors remained in chat history.
This is process recovery on surviving compute, not implemented automatic resume, stopped-compute recovery, or persistent storage.
The later opt-in shim passed an independent fresh-session model/environment/attachment/follow-up test.
Full credential-lifetime rollover remains untested.

## Glossary

| Term | Meaning |
| --- | --- |
| API / CLI / SDK | Application programming interface / command-line interface / software development kit. |
| ARN / UUID | Amazon Resource Name / universally unique identifier. |
| Binding | Saved plugin record that connects work identity to remote execution. |
| PTY / TUI | Pseudo-terminal / terminal user interface. |
| IAM / SigV4 | AWS Identity and Access Management / AWS Signature Version 4 request signing. |
| EC2 / ECS | Amazon Elastic Compute Cloud / Amazon Elastic Container Service. |
| ECR / EBS / EFS | Amazon Elastic Container Registry / Elastic Block Store / Elastic File System. |
| SSM / SSO | AWS Systems Manager / single sign-on. |
| IMDSv2 / STS | Instance Metadata Service version 2 / AWS Security Token Service. |
| VPC | Amazon Virtual Private Cloud. |
| WSS / TLS | WebSocket over TLS / Transport Layer Security. |
| PID / UID / GID | Process ID / user ID / group ID. |
| IPC / WAL | Interprocess communication / write-ahead log. |
| MCP | Model Context Protocol. |
| XDG | Desktop-environment conventions used here for configuration and state paths. |

## Upstream references

- [Herdr plugin contract](https://herdr.dev/docs/0.9.5/plugins/) and [wrapper detection](https://herdr.dev/docs/0.9.5/agents/).
- [Herdr remote-machine support](https://herdr.dev/docs/connecting-machines/).
- [AWS coding-agent runtime sample](https://github.com/awslabs/agentcore-samples/tree/main/01-features/02-host-your-agent/01-runtime/04-coding-agents/03-code-agents-competition-e2e).
- [AgentCore SDK shell implementation](https://github.com/aws/bedrock-agentcore-sdk-python/tree/main/src/bedrock_agentcore/runtime/shell).
- [AgentCore lifecycle](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html).
- [Busy-state reporting](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html).
- [Sessions and stop/resume](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html).
- [S3 Files and filesystem options](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html).
- [Stop conflicts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-stop-session.html).
- [OpenCode 1.18.30 public plugin hooks](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/plugin/src/index.ts).
- [OpenCode 1.18.30 task metadata](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/tool/task.ts).
- [SQLite WAL restrictions](https://sqlite.org/wal.html).
