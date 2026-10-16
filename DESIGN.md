# Design

## Central decision and implementation status

**Herdr owns workspaces, tabs, panes, and live agent identity. The plugin binds those primitives to AgentCore execution and persistent coding files.** A durable plugin binding supports recovery without introducing a separate end-user platform or replacing Herdr's agent model.

The current prototype creates agents, reattaches surviving PTYs, detaches, and explicitly stops compute. The lifecycle target extends this with persisted conversation identity, process restart, and recovery onto fresh compute. Sections labeled **target** describe planned work; they do not change the current connector's conservative behavior when the original PTY is missing.

### Scope of the Jindouyun comparison

Jindouyun is a reference for missing execution concepts: persistent coding files, remote Working Directories, multiple shells, skills, and process/conversation recovery. It is not a required backend. This plugin does not adopt Cognito, per-user account ownership, a customer-facing Runtime catalog, DynamoDB registries, or the proposed `agentcore-code` CLI.

| Layer | Responsibility |
| --- | --- |
| Herdr | Layout, live agent identities/names, terminal presentation, prompt/read/wait/key APIs, and orchestration by scripts or agents using those APIs. |
| Plugin | AgentCore runtime selection, remote execution bindings, shell transport, persistent paths, lifecycle actions, and recovery metadata. |
| AgentCore runtime | Isolated compute, coding-agent/tool execution, mounted files, and runtime-side process supervision/health. |
| AWS IAM and host access | Direct AgentCore authorization through the management host's credentials/role, plus Herdr's existing local/SSH access model. |

The default remains one runtime session and one shell per independently isolated agent. Additional helper or agent shells within an existing runtime session are a planned extension; one-agent-per-session is not a universal identity rule.

**Deployment decision:** for management that continues while the laptop sleeps or reboots, run the Herdr background server, connectors, and coordinating workflows on an always-on cloud host. Start with one EC2 host and Herdr's native SSH remote-machine support. Keep the laptop as a client and OpenCode execution in AgentCore. This cloud deployment has not yet been validated.

## Architecture

Each server-owned Herdr pane hosts a connector on the same machine as the Herdr server. The connector uses AgentCore's authenticated WebSocket Shell API to access a remote PTY running OpenCode. Here, "host-local" means local to the management server, which can be a laptop or a cloud host.

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

One deployed runtime ARN can serve multiple runtime sessions. The plugin creates a separate runtime session for each new independent coding environment.

### Cloud-hosted management — recommended target

```mermaid
flowchart LR
    subgraph Laptop[Developer laptop]
        Client[Herdr client]
    end
    subgraph EC2[Always-on EC2 management host]
        Server[Herdr background server]
        Coordinator[Coordination workflows]
        PaneA[Pane A and connector]
        PaneB[Pane B and connector]
        State[(Persistent management state)]
        Role[EC2 instance role]
        Coordinator --> Server
        Server --> PaneA
        Server --> PaneB
        Server --- State
        PaneA --- State
        PaneB --- State
        Role --> PaneA
        Role --> PaneB
    end
    subgraph Runtime[AgentCore Runtime]
        AgentA[Session A and OpenCode A]
        AgentB[Session B and OpenCode B]
        AgentA --- FilesA[(Session workspace A)]
        AgentB --- FilesB[(Session workspace B)]
    end
    Client <-->|Native Herdr connection over SSH| Server
    PaneA <-->|Authenticated WebSocket Shell| AgentA
    PaneB <-->|Authenticated WebSocket Shell| AgentB
```

The SSH connection and AgentCore WebSockets have independent owners. Closing the laptop connection leaves the EC2 server and connectors running. Laptop-side controls and live viewing pause until reconnect; cloud-side workflows can continue if they actually run on the management host or another cloud service.

Install Herdr, the plugin, Python/uv dependencies, and runtime profiles on the EC2 host. Herdr's remote-machine connection does not copy local plugins or configuration there. With an existing SSH host alias, the laptop can register the server using the standard command:

```bash
herdr machine add cloudbox
```

This is a setup example, not a command already executed or a deployed resource. The profile selects a remote Herdr session. Agent/pane IDs belong to that remote server; automation should use the corresponding `herdr --machine <saved-profile>` routing when invoked from the laptop.

### EC2 versus ECS

| Concern | EC2 — first deployment | ECS — alternative |
| --- | --- | --- |
| Remote client access | Existing SSH access fits Herdr's saved-machine transport. | Provide an SSH endpoint or another compatible bridge; ECS Exec is not assumed to implement the transport. |
| Long-running management | Supervise the Herdr server with a service manager such as systemd. | An ECS service maintains task availability, but task replacement terminates the old server/connectors. |
| Durable state | Retained EBS-backed storage with explicit retention, backup, and reattachment policies. | External persistent storage, for example EFS, with validated filesystem/locking behavior. |
| AWS authentication | Instance-role credentials resolved through the normal AWS credential chain. | Task-role credentials resolved through the normal AWS credential chain. |
| Replacement recovery | Reconcile registry state after a host/server restart. | Reconcile after every task replacement or deployment that replaces the task. |
| Initial effort | Lower; uses Herdr's existing host model. | Higher; remote access, task identity, and state recovery need additional design and validation. |

Start with one active management host. An additional host is not automatically safe failover: controller leases and idempotent workflow recovery are needed before two hosts can control the same remote execution. The existing process lock is only a local attachment guard, not a distributed coordination mechanism. This concerns process coordination, not end-user account management.

### Management-host state and credentials

Persist Herdr configuration and saved session/layout state, the plugin's config directory, and its execution-binding records on the management host. Installation trees remain replaceable. Keep live IPC sockets and process-specific files on the host's local runtime filesystem. Persisted state must be reachable after the planned host replacement; a volume's mere existence is not a recovery policy.

The connector uses the management host's instance role for AgentCore access. OpenCode uses its AgentCore execution role for model/tools access. Laptop SSH authentication is a third, separate boundary. Do not require an active laptop credential-forwarding process to keep the cloud connectors authorized.

Configure the service manager to start Herdr with the intended service user, environment, and persistent session. Starting the daemon restores service availability; automatic recovery of plugin connections and coordination progress requires an additional reconciliation workflow, which is not implemented yet.

### Failure boundaries and expected behavior

| Event | Expected behavior |
| --- | --- |
| Herdr client closes or laptop sleeps/reboots | SSH/viewing ends; cloud server, connectors, and cloud-side coordination continue while their hosts are healthy. Do not issue runtime stop merely because a viewer disappears. |
| Laptop-hosted development mode loses connectivity | Its connectors cannot make progress while asleep; remote work may continue subject to shell/runtime lifetimes. This mode does not provide unattended management. |
| EC2 management host or ECS task restarts | Connectors and sockets are lost. Load retained registry state, inspect remote sessions, and reattach/recover without replaying uncertain work. Automatic reconciliation is planned. |
| AgentCore shell disappears | Apply strict attach versus explicit process recovery semantics, independent of the management host's health. |
| AgentCore compute expires or stops | Recover workspace/conversation state onto fresh compute according to the resume contract. An always-on Herdr host does not remove AgentCore lifetime limits. |
| A coordinating workflow crashes | Recover its own durable progress. Herdr process supervision alone does not restore workflow execution state. |

There are two recovery mechanisms to implement: **management-host recovery** restores registry, connections, and coordination; **AgentCore recovery** restores coding workspace/conversation state. Validate them separately and together. Remote activity can continue to consume cloud resources while no laptop is attached.

### Runtime fleet and session allocation

The fleet is the collection of session sandboxes created from a deployed runtime configuration. Normally deploy one runtime per environment configuration, not one runtime per pane. Different images, permissions, or network configurations can use separate runtime profiles.

```mermaid
flowchart TB
    Runtime[Deployed OpenCode runtime configuration]
    Runtime --> A[Runtime session A]
    Runtime --> B[Runtime session B]
    Runtime --> C[Runtime session C]
    A --> ComputeA[Current compute A]
    B --> ComputeB[Current compute B]
    C --> ComputeC[Current compute C]
    A --- StorageA[(S3 Files namespace A)]
    B --- StorageB[(S3 Files namespace B)]
    C --- StorageC[(S3 Files namespace C)]
```

The storage branches represent separate persistent-home namespaces for independent executions on the configured S3 Files filesystem. They do not require a separate storage service or per-user access-point provisioning. AgentCore manages compute allocation. The plugin keeps Herdr-to-AgentCore bindings, creates session IDs, and manages connections and lifecycle operations. Infrastructure provisioning remains separately configured.

New UUID session IDs create independent compute environments. Persistent files have a separate lifecycle. The plugin should allocate a fresh home namespace for new independent work by default, but permit deliberate use of an existing Working Directory or shared files. Directory namespaces prevent accidental overlap; they are not additional IAM security boundaries.

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| `herdr-plugin.toml` | Declare build steps, actions, and terminal pane entrypoints. |
| `src/herdr_agentcore/cli.py` | Parse commands; present setup/session menus; coordinate new, attach, and stop workflows. |
| `src/herdr_agentcore/herdr.py` | Invoke public Herdr APIs and report transport metadata. |
| `src/herdr_agentcore/storage.py` | Validate profiles and records; persist state atomically; enforce local attachment locks. |
| `src/herdr_agentcore/connector.py` | Sign connections, interpret shell frames, launch once, reconnect, and handle termination. |
| `src/herdr_agentcore/terminal.py` | Manage POSIX raw mode, bounded input, detach keys, and resize notifications. |
| `src/tests/` | Offline behavior tests and optional isolated Herdr manifest validation. |

## Herdr integration

The plugin defines five actions and corresponding pane entrypoints:

- `agentcore.setup`: configure a runtime profile.
- `agentcore.new`: choose a profile and start a cloud agent.
- `agentcore.attach`: reattach a saved connection.
- `agentcore.sessions`: show last-known connection records.
- `agentcore.stop`: explicitly stop compute for a detached runtime session.

Actions open panes using `herdr plugin pane open` with an explicit target from the invocation context. Actions and connectors execute on the selected Herdr server host. The connector is re-executed with `HERDR_AGENT=opencode` so that server can identify its host-local wrapper and use its OpenCode screen manifest.

Agent lifecycle remains screen-derived. The connector separately reports `cloud` and `connection` metadata tokens. A connected transport does not imply an idle agent, and cached screen content during an outage is not live lifecycle evidence.

An event-based lifecycle bridge is a follow-up: the standard OpenCode integration talks to a host-local Herdr socket, which is not directly reachable from an AgentCore microVM even when Herdr itself runs on EC2.

### Herdr-native orchestration

Use plugin/pane actions to provision or attach remote execution, then use Herdr's existing `agent list`, `agent prompt`, `agent read`, `agent wait`, and `agent send-keys` surfaces once the agent is recognized. `agent start --kind opencode` selects the canonical executable; it is not an AgentCore provisioning API.

A coordinating script or agent on the management host can drive multiple cloud-agent panes through these APIs. The plugin supplies execution and lifecycle support rather than a new workflow/control-plane service. Cloud workers do not automatically gain access to the management host's Herdr socket; a narrowly scoped bridge would be separate future work if workers need to issue Herdr commands directly.

### Additional shells and operation scope — target

Each pane binds to one remote shell. An AgentCore runtime session may have several agent/helper shells; each agent shell can have its own OpenCode conversation. Workspace/tab grouping remains Herdr presentation and does not create new backend Project or User resources.

```text
Herdr workspace/tab
  Pane: implementation → runtime session A / shell 1 → OpenCode conversation 1
  Pane: tests          → runtime session A / shell 2 → ordinary build/test shell
  Pane: reviewer       → runtime session B / shell 3 → OpenCode conversation 2
```

Only actual agent panes receive `HERDR_AGENT=opencode`. An ordinary helper shell must remain a normal Herdr terminal. Detach disconnects a pane; stopping a shell/process affects that execution; stopping a runtime session affects all its shells. Before adding shared-session shells, implement explicit stop scopes and sibling-impact reporting. The current stop action targets the runtime session.

## Agent identity and storage

| Identity | Lifetime and meaning |
| --- | --- |
| Plugin execution-binding ID | Stable internal handle for remote execution and recovery. Reuse the current connection UUID; this is not a new end-user or platform agent resource. |
| AgentCore runtime-session ID | Identifies the session/environment context within its runtime; retain it across supported stop/resume cycles. |
| AgentCore shell ID | Identifies a PTY lifetime. Reuse it for warm reattachment; replace it for an explicit process/compute recovery. |
| OpenCode conversation ID | Identifies the primary conversation to resume from persisted state; not yet captured by this plugin. |
| Herdr server/session and pane ID | Current attachment on the management host. Pane IDs are scoped to one server and can change on replacement/movement. |
| Herdr agent name | A convenient live alias, not a durable identity. Restore the desired display name subject to local uniqueness. |

Profiles are stored in `HERDR_PLUGIN_CONFIG_DIR/config.json`. Connection records and locks are stored under `HERDR_PLUGIN_STATE_DIR`. In cloud-hosted mode, these paths belong to the EC2/ECS management host, not the viewing laptop. Standalone CLI use has separate XDG defaults and explicit directory overrides.

A current connection record snapshots its profile, both remote IDs, launch state, last-known transport status, and timestamps. Editing a profile therefore affects new connections only. Config and record formats use `version: 1`; record writes use an atomic replacement and a local per-connection lock.

### Target execution-binding records

Extend that record through a versioned migration to include the active OpenCode conversation ID, S3 Files persistent-home and remote Working Directory paths, bootstrap metadata, runtime-version compatibility information, desired Herdr name, and current attachment. Runtime ARN, endpoint, and session ID must be resolved together; a session ID alone is not a portable identity across deployments. Host-local records remain the initial store; no cloud customer-registry service is required.

```mermaid
flowchart TB
    Agent[Plugin binding for Herdr agent backend-coder]
    Agent --> Session[Runtime ARN / endpoint / runtime session ID]
    Agent --> Conversation[Primary OpenCode conversation ID]
    Agent --> Workspace[(Persistent workspace and recovery metadata)]
    Agent --> Attachment[Current attachment]
    Attachment --> Shell[Current shell ID]
    Attachment --> Pane[Herdr server / session / pane ID]
```

For example, execution displayed as `backend-coder` can move from shell X and pane `w1:p2` to shell Y and pane `w1:p7` while retaining its binding ID, persistent paths, runtime session ID, and conversation. Herdr may clear a live alias when the connector exits; the plugin must explicitly rebind and reapply its desired name after recognition, respecting live-name uniqueness. Saved execution may exist without an attached pane.

When attaching an existing session, resolve its configured runtime context and stored shell/conversation mapping. Unknown IDs need an explicit adoption/discovery flow; do not guess the PTY or claim to have resumed a conversation. IAM controls AWS access. Locks and any future controller leases prevent competing connectors/recovery; they do not implement end-user identity or authorization.

## Persistent coding files through S3 Files

**Primary target:** an S3 Files access point mounted by the AgentCore runtime. Reuse the sample's `/mnt/s3files` mount when appropriate; the access point and mount path are deployment configuration, not Cognito-derived resources. Example configuration shape:

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

```text
/mnt/s3files/
  mcp/                                   Existing shared tools, if configured
  herdr/<execution-binding-id>/home/
    src/my-repo/                         Files, .git, and uncommitted work
    .config/opencode/                    Persistent agent configuration
    .local/share/opencode/               Conversation/application state
    .herdr-agentcore/skills/             Configured persistent skills
    .herdr-agentcore/recovery/           Paths and conversation mappings
    artifacts/                          Selected build/task results
```

The layout is proposed. Configure `HOME` or supported tool/OpenCode data directories to point at the persistent home, while keeping installed executables reachable independently of `HOME`. Configure and test skill discovery for the selected OpenCode version; placing files in a directory alone does not establish discovery.

Persist the selected home and Working Directory in the binding record. Launch in that remote directory, which may be an existing repository; it is independent of the local Herdr pane's cwd. Reconnect and replacement compute reuse the same paths. Additional shells may intentionally share files, with separate directories/worktrees or other explicit coordination for concurrent editing.

### Bootstrap and filesystem behavior

- Verify the configured mount and persistent path before launching. A failed mount must not silently redirect work to ephemeral storage.
- Initialize a new home's defaults once. Preserve existing configuration, files, and conversation state on later launches.
- Replace the sample launcher's hardcoded `/home/agent`, forced `cd "$HOME"`, and unconditional OpenCode config rewrite with explicit persistent-home/cwd handling.
- Validate OpenCode database behavior on S3 Files, including locking, crash recovery, and concurrent access. Do not assume network-mounted storage has identical semantics to a local disk; this is a release gate for conversation persistence.
- Keep sockets, PIDs, runtime leases, and other process-specific state on an appropriate ephemeral filesystem. Filesystem persistence does not restore processes, locks, or memory.
- Record and verify OpenCode conversation/recovery metadata before process replacement. Coordinate concurrent bootstrap attempts so they cannot launch duplicate agents.

S3 Files requires the runtime's VPC/mount connectivity, permissions, and POSIX access-point identity to be configured correctly. Provisioning remains a deployment concern; the plugin consumes the configured mount. Its persistent files survive compute replacement according to the customer-managed filesystem and backing-storage lifecycle. Detach, session stop, and plugin uninstall do not mean file deletion. Backups, retention, and format migrations must be deliberate.

Managed per-session storage Preview is a possible later alternative, not the primary contract. Its documented per-session isolation, 14-day inactivity expiry, and reset on runtime-version updates differ from S3 Files persistence and must be evaluated explicitly before use.

The microVM's default idle timeout is 15 minutes and its maximum compute lifetime is 8 hours. Those limits govern each compute incarnation; persistent files have their own lifecycle. The current prototype does not yet configure persistent home/cwd, capture conversation IDs, or validate this filesystem layout.

## Resume semantics — target

| Situation | Required action | Identity preserved |
| --- | --- | --- |
| Original PTY and OpenCode process survive | Reattach using the existing runtime-session/shell pair; send no launch command. | Execution binding, runtime session, shell, conversation. |
| Compute survives but the original PTY is unavailable | Inspect runtime-side process supervision; attach a replacement shell to surviving work where possible, otherwise explicitly resume the saved conversation after confirming process exit. | Binding, runtime session, persistent paths/conversation; shell changes. |
| Compute has stopped | Reuse the runtime session ID, remount S3 Files on fresh compute, validate saved paths/metadata, and resume OpenCode in a new shell. | Binding, runtime session, persistent files/conversation; compute and shell change. |
| Storage is missing or incompatible | Enter recovery-required state and require explicit migration/reset. | Preserve binding and failure information; do not claim successful resume. |

Process/compute recovery is an explicit operation, not a reconnect retry. It restores saved files and conversation state, not an arbitrary instruction pointer, running subprocess, or in-flight tool call. A dropped socket is insufficient evidence that the agent process died.

A runtime-side supervisor or named `tmux` session can keep work independent of one AgentCore shell attachment while compute survives. Evaluate that execution pattern as part of recovery; it is not currently installed by the plugin and cannot preserve processes across compute termination.

```mermaid
flowchart TD
    Resume[Resume saved execution] --> Registry[Resolve Herdr binding, persistent paths, and runtime context]
    Registry --> Live{Original PTY confirmed alive?}
    Live -->|Yes| Attach[Reattach without launching]
    Live -->|No or unavailable| Inspect[Inspect supervisor and recovery state]
    Inspect --> Known{Process ended or fresh compute confirmed?}
    Known -->|No| Uncertain[Report unavailable or uncertain; do not relaunch]
    Known -->|Yes| Data{Persisted identity and conversation valid?}
    Data -->|No| Recovery[Recovery required]
    Data -->|Yes| Bootstrap[Idempotent bootstrap and native conversation resume]
    Bootstrap --> Bind[Bind replacement shell and Herdr pane]
    Attach --> Bind
```

### User-facing lifecycle operations

| Operation | Contract | Current implementation |
| --- | --- | --- |
| New | Create an execution binding/session and initialize its persistent home or deliberately select existing project files. | New remote IDs and launch implemented; persistent-home/cwd integration pending. |
| Attach | Reattach only to the original live PTY. | Implemented. |
| Detach | Disconnect local terminal; leave remote compute subject to platform lifecycle policies. | Implemented. |
| Stop runtime session | Terminate its compute and all shells, retaining binding records and persistent files. | Stop API implemented; the prototype currently prevents reattaching stopped records. |
| Stop shell/process | Stop only the selected execution; preserve sibling shells and persistent files. | Planned alongside additional-shell support. |
| Resume | Reattach if alive, otherwise explicitly recover process/compute from persisted state. | Planned. |
| Archive | Mark logical work finished and retain/export results according to policy. Data deletion is a separate decision. | Planned; not an AgentCore stop operation. |

The new resume path must make stopped/expired execution recoverable through its saved binding while retaining strict attach behavior. Retry `RetryableConflictException`/retryable HTTP 409 responses during provisioning and stop with bounded backoff; do not treat every conflict as a successful operation or relaunch an ambiguous request. The current WebSocket connector treats non-429 HTTP 4xx responses as terminal, so retryable lifecycle conflict handling is an implementation gap.

### Independent state dimensions

| Dimension | Example states | Authority |
| --- | --- | --- |
| Compute | running, stopped, recovering, unknown | AgentCore operations and runtime supervisor; local records are last-known observations. |
| Connection | attached, detached, reconnecting | Local connector. |
| Agent work | working, idle, blocked, unknown | Current screen detection; future remote OpenCode event bridge. |

Do not conflate `idle` with stopped compute, or detachment with task completion. The runtime supervisor should report actual active/background work through AgentCore health responses (`HealthyBusy` when appropriate). WebSocket keepalive is a transport mechanism, not a substitute for workload tracking or a way to bypass maximum compute lifetime. The sample's always-`Healthy` handler does not implement this supervisor.

## Current launch and reattach sequence

```mermaid
sequenceDiagram
    actor User
    participant Herdr
    participant Connector
    participant Store
    participant Shell as AgentCore Shell
    User->>Herdr: New agent or attach
    Herdr->>Connector: Open plugin pane
    Connector->>Store: Create/load record and acquire lock
    Connector->>Shell: Signed WebSocket connection with both IDs
    Shell-->>Connector: Confirm shell ID and reconnected flag
    alt Launch not yet attempted
        Connector->>Store: Persist launch_state = attempted
        Connector->>Shell: Send remote launch argv once
        Connector->>Store: Persist launch_state = sent
    else Existing PTY confirmed
        Note over Connector,Shell: Reattach without replaying the launch
    else Original PTY missing
        Connector->>Store: Mark expired
        Connector-->>User: Stop; explicit recovery required
    end
    loop While connected
        Herdr->>Connector: Input or resize
        Connector->>Shell: STDIN or RESIZE frame
        Shell-->>Connector: Terminal output
        Connector-->>Herdr: Output bytes and connection metadata
    end
```

The default remote argv is `["/app/run.sh"]`, matching the AWS sample. Arguments are shell-quoted individually and launched with `exec env TERM=xterm-256color COLORTERM=truecolor ...`. Remote provisioning, permissions, model selection, and workspace initialization belong to the runtime launcher.

## Current connector transport and lifecycle behavior

```mermaid
stateDiagram-v2
    [*] --> Created
    Created --> Connecting
    Connecting --> Connected: Shell confirmed
    Connected --> Reconnecting: Transient network loss
    Reconnecting --> Connected: Same PTY confirmed
    Connected --> Detached: User detaches
    Reconnecting --> Detached: User detaches
    Detached --> Connecting: Explicit attach
    Connecting --> Expired: Original PTY missing
    Connected --> Expired: Platform shutdown
    Reconnecting --> Error: Retry window elapsed
    Connected --> Exited: Shell exit
    Connected --> TakenOver: Another client attaches
    Detached --> Stopped: Explicit stop request
```

- Use the SDK to generate a freshly signed shell connection; process WebSocket frames directly so connection confirmation and `reconnected` are visible.
- Forward output bytes without decoding/re-encoding the terminal stream. Input chunks remain below the shell frame-size limit.
- Forward initial dimensions, `SIGWINCH` updates, and dimensions after reconnect.
- Persist `attempted` before sending the launch. If delivery is uncertain, show the existing terminal rather than repeating the command.
- Discard input during an outage. If an input send fails ambiguously, end the connector rather than resubmit it.
- A second local connector is rejected by the lock. Remote takeover closes the displaced connection without a reconnect loop.
- Ctrl+] followed by `d` detaches; Ctrl+] twice sends a literal prefix. Detach closes the WebSocket without the shell-shutdown frame.
- Stop calls `StopRuntimeSession` after explicit confirmation and successful local lock acquisition. It affects the whole remote runtime session.

AgentCore microVM lifetime and idle limits still apply. Reattaching after expiry can reach a fresh environment; that must not be mistaken for the original agent. The sample's shared storage mount does not automatically persist OpenCode conversation state.

## Implementation increments

1. Validate the existing terminal bridge against a deployed runtime.
2. Extend host-local execution bindings with S3 Files persistent-home/cwd and conversation metadata, keeping existing records readable through migration.
3. Integrate the configured S3 Files mount and runtime-side persistent-home bootstrap/process supervision; validate repositories, configuration, skills, and OpenCode database persistence.
4. Establish the single-EC2 management deployment: supervised Herdr, host-installed plugin, instance role, persistent management state, and laptop SSH attachment. Test laptop sleep/reboot while agents are running.
5. Add explicit resume, Herdr rebinding, management-host reconciliation, and retryable lifecycle conflicts. Add helper/agent shell panes in existing sessions with separate shell-stop versus session-stop semantics.
6. Test persistent files, selected Working Directories, multiple shells, process restart, compute stop/resume, management-host replacement, and competing recovery attempts.

Management-host and runtime provisioning remain separately configured. Autonomous coordination uses Herdr's APIs and runs on the management host for unattended operation. Authoritative lifecycle-event forwarding can build on the execution bindings; ECS deployment and multi-host failover follow validation of the single-host contract. None of these increments depends on Cognito or Jindouyun platform services.

## Packaging and validation

Herdr installs from a public GitHub repository containing the root manifest. The build runs `uv sync --frozen --no-dev`; runtime entrypoints use the installation's virtual environment. Community marketplace discovery uses the `herdr-plugin` topic. Discovery and first-party endorsement are separate.

All implementation and test code lives under `src/`. The wheel includes only `src/herdr_agentcore`; the source distribution also includes tests, the manifest, and the root project files.

Validation commands:

```bash
uv sync --frozen
uv run ruff check src
uv run ruff format --check src
uv run pytest
uv build
```

The optional `HERDR_TEST_BINARY` environment variable enables manifest validation with an installed Herdr binary in an isolated registry. Tests otherwise use fake transports, a local WebSocket server, and a local PTY. Live AWS behavior is assessed separately against the acceptance criteria in [REQUIREMENTS.md](REQUIREMENTS.md).

## Upstream references

- [Herdr plugin contract](https://herdr.dev/docs/plugins/) and [wrapper detection](https://herdr.dev/docs/agents/).
- [Herdr SSH remote-machine support](https://herdr.dev/docs/connecting-machines/).
- [AWS coding-agent runtime sample](https://github.com/awslabs/agentcore-samples/tree/main/01-features/02-host-your-agent/01-runtime/04-coding-agents/03-code-agents-competition-e2e).
- [AgentCore Python SDK shell implementation](https://github.com/aws/bedrock-agentcore-sdk-python/tree/main/src/bedrock_agentcore/runtime/shell).
- [AgentCore runtime lifecycle](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html).
- [AgentCore isolated sessions and stop/resume behavior](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html).
- [AgentCore S3 Files mounts and filesystem alternatives](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html).
- [StopRuntimeSession and retryable conflicts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-stop-session.html).
