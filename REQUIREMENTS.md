# Requirements

## Objective

Provide a community-installable Herdr plugin for coding agents that execute in AgentCore Runtime, including a repository-owned OpenCode container, runtime provisioning, and terminal connection/orchestration.

## Scope authority

Follow Herdr's workspace/tab/pane/live-agent model. The plugin supplies AgentCore execution bindings, terminal transport, persistence, and lifecycle operations through Herdr's existing extension interfaces.

Jindouyun is a reference for execution concepts only. The plugin does not depend on its proposed CLI or control plane and does not include Cognito, per-user accounts, tenant ownership, or a separate cloud resource registry service. Direct AWS IAM authentication and deployment-level permissions remain required.

## Initial scope

- Herdr 0.9.5 or later on macOS and Linux.
- Python 3.11 or later, with dependencies managed by uv.
- Either provision the included OpenCode runtime or configure an existing AgentCore runtime with WebSocket Shell access. Provisioning uses a local Docker engine with Buildx/ARM64 support and management-host AWS authorization.
- Connectors run on the Herdr server host: laptop-hosted for development, or cloud-hosted for unattended management. OpenCode executes in independent AgentCore environments.

## Deployment target

**Laptop Herdr client → SSH → EC2 Herdr management server and connectors → AgentCore coding-agent sessions.**

Use a single always-on EC2 management host for the first cloud deployment, taking advantage of Herdr's existing SSH remote-machine support. Install and configure the plugin on that host, where actions execute. Coordination workflows must also execute there to progress while the laptop is offline.

ECS is an alternative deployment target requiring a compatible remote-access transport, external state storage, and task-replacement recovery. Neither the EC2 deployment nor an ECS-specific integration has been implemented or tested by this repository yet.

## Target lifecycle model

**Herdr owns live agent identity and pane organization. A durable plugin execution binding records the remote runtime session, shell, persistent files, and active OpenCode conversation needed to reconnect or recover that work.**

A deployed runtime provides the image, IAM role, networking, storage, and lifecycle configuration for many isolated sessions. AgentCore allocates the underlying compute; the plugin manages execution bindings and attachments. Creating an agent does not require deploying another runtime.

The current default allocates one runtime session and one shell per independent agent. This is a default isolation policy, not a requirement that AgentCore sessions contain exactly one agent. Additional agent or helper-shell panes within an existing runtime session are a planned capability, with separately scoped shell and session operations.

| User intent | Required behavior |
| --- | --- |
| New independent execution binding | Create fresh compute with a new runtime session ID and a separate persistent-home namespace by default. Explicitly selecting existing/shared project files must preserve those files. |
| Existing session with a live PTY | Reattach to the same shell and OpenCode process without launching again. |
| Existing environment, but the original agent process has exited | Open a new shell and explicitly resume the persisted OpenCode conversation. |
| Existing session whose compute has stopped | Provision fresh compute under the same runtime session ID, remount S3 Files, reuse the recorded persistent paths, and explicitly resume the saved conversation. |
| Existing session with missing/incompatible persisted state | Report that recovery is required; do not silently present a fresh agent as the original one. |

Only the new-agent and live-PTY reattachment paths are implemented in the current prototype. Restarting the OpenCode process and recovery after compute termination are requirements for the next lifecycle increment.

## Functional requirements

| ID | Requirement |
| --- | --- |
| F01 | Package the integration as a standalone Herdr plugin using the public manifest and CLI APIs. Support standard community installation and updates. |
| F02 | Configure named runtime profiles containing the runtime ARN, region, endpoint qualifier, optional AWS profile, and remote launch argv. |
| F03 | Start a new remote agent in a Herdr pane. The connector executes on the management host; OpenCode and its tools execute in AgentCore. |
| F04 | Allocate a distinct runtime-session ID and shell ID for each new independent agent. |
| F05 | Forward terminal bytes in both directions, preserving interactive TUI controls, Unicode, paste, and interrupts. |
| F06 | Forward initial terminal dimensions and subsequent resize events, including after reconnection. |
| F07 | Integrate with Herdr's OpenCode recognition and screen-derived lifecycle detection. Expose connection health separately. |
| F08 | Persist both remote identifiers so users can reattach to the same PTY while it exists. |
| F09 | Retry transient connection failures within a bounded window, re-signing connections. Never replay uncertain launch commands or user input. |
| F10 | Distinguish terminal detachment from explicitly stopping the session's compute and processes. |
| F11 | List saved connections with clearly labeled last-known status. Prevent competing local connectors from attaching to the same saved connection. |
| F12 | Preserve user configuration and connection records across plugin updates. |
| F13 | Offer opt-in expiration-aware runtime-role authentication for the sample's PATH-based OpenCode launcher. Preserve runtime initialization, management-host authentication, and existing connection snapshots. |
| F14 | Ship the OpenCode image build context and provisioning implementation in the same distribution as the connector, with upstream attribution and no dependency on research checkouts. |
| F15 | Provision ECR, an execution role, and an IAM-authenticated AgentCore runtime; publish a pinned ARM64 image and save a connector profile only after deployment completes. |
| F16 | Use the runtime execution role and an expiration-aware SDK credential provider for Bedrock. Do not fetch, export, or persist credential snapshots in the owned launcher. Keep deployment authentication separate. |
| F17 | Provide an offline deployment plan, explicit updates to owned stacks, bounded deployment waits, and CloudFormation failure/cleanup guidance. Retain existing profile and session state on failed provisioning. |

## Lifecycle requirements — next increment

| ID | Requirement |
| --- | --- |
| L01 | Use the existing local connection UUID as a durable plugin execution-binding identity. Keep Herdr's native live-agent identity and naming semantics. |
| L02 | Maintain host-local binding records mapping that identity to runtime ARN, endpoint/version context, runtime-session ID, shell ID, active OpenCode conversation ID, persistent-home/working-directory paths, and current Herdr attachment. |
| L03 | Keep `attach` a strict live-PTY operation. Add explicit `resume` behavior that selects warm reattachment, process restart, or compute recovery from confirmed remote state. A network failure alone is not evidence that a process has ended. |
| L04 | Use a configured S3 Files mount for persistent coding files and OpenCode state. Allocate separate namespaces for independent execution by default, with deliberate sharing for helper shells or selected existing projects. |
| L05 | Provide an idempotent runtime bootstrap/supervisor that initializes new sessions once, checkpoints recoverable state, and resumes the saved conversation after process/compute replacement. Do not claim restoration of in-memory execution or in-flight tools. |
| L06 | Treat stop as compute termination, not deletion of binding records or persistent files. Retain recovery metadata and wait for stop completion before resume. File deletion must be a separate explicit operation. |
| L07 | Track compute state, connection state, and OpenCode lifecycle state independently. Report real background work through AgentCore's health mechanism; do not infer busy state from an open socket. |
| L08 | Rebind recovered execution to a Herdr pane and reapply its desired live-agent name subject to Herdr's uniqueness and occupant-lifetime rules. Scope pane bindings to the Herdr server/session. |
| L09 | Handle retryable provisioning/stop conflicts with bounded backoff and prevent competing recovery attempts. Any future multi-manager deployment needs controller coordination beyond the current local process lock, not a per-user identity service. |
| L10 | Detect missing state, retention expiry, and runtime-version incompatibility before resuming. Define backup/migration behavior rather than silently resetting saved execution state. |
| L11 | Support explicitly opening additional shells in an existing runtime session, including ordinary build/test terminals. Only panes running a supported agent should receive an agent-detection hint. |
| L12 | Separate detach, stop-shell/process, and stop-runtime-session operations. Session stop must identify its scope across all attached shells; closing a helper pane must not terminate sibling work. |

## Persistent coding-file requirements — next increment

| ID | Requirement |
| --- | --- |
| P01 | Use an S3 Files access point mounted by the configured AgentCore runtime. Select the mount/root through runtime configuration; do not introduce Cognito identities or per-user storage provisioning. |
| P02 | Persist repositories, Git metadata, uncommitted changes, tool configuration, skills, OpenCode conversation data, recovery metadata, and selected artifacts beyond connection and compute lifetimes. |
| P03 | Associate each independent execution binding with a stable persistent-home/root path. Reattach and replacement compute must reuse the recorded path; a new runtime session ID alone must not reset persistent files. |
| P04 | Support a configured remote Working Directory within the mounted persistent root, including existing repositories. Preserve the distinction from Herdr's management-host working directory. |
| P05 | Direct `HOME` or the supported OpenCode/tool data directories to persistent storage. Preserve existing configuration instead of overwriting it on every launch; ensure skills remain discoverable. |
| P06 | Validate S3 Files filesystem behavior for OpenCode's database and development tools, including locking/concurrent access. Keep sockets, PIDs, and other ephemeral process state outside the persistent home where required. |
| P07 | Validate mount readiness and recovery metadata before starting work. Detach, session stop, and plugin uninstall must not delete persistent files. Explicitly shared directories need defined concurrency behavior. |

S3 Files is the primary persistence target. Managed per-session storage Preview may be evaluated later, but its isolation and retention behavior must not silently replace the persistent-file contract. See [DESIGN.md](DESIGN.md#persistent-coding-files-through-s3-files).

## Cloud management requirements — target deployment

| ID | Requirement |
| --- | --- |
| H01 | Run the Herdr background server and AgentCore connectors on an always-on management host; recommend EC2 for the initial deployment. |
| H02 | Use Herdr's native SSH remote-machine connection from the laptop. Laptop disconnect, sleep, or reboot must not intentionally terminate the management server, connectors, or runtime sessions. |
| H03 | Install the plugin, dependencies, and runtime profiles on the management host. Use an EC2 instance role for connector AWS access rather than depending on laptop-supplied credentials. |
| H04 | Persist Herdr configuration/session state and plugin profiles/execution bindings on retained storage outside ephemeral installations. Define retention, backup, and reattachment behavior for host replacement. |
| H05 | Supervise the Herdr server with a service manager. Restarting the server must reconcile surviving cloud sessions before creating replacement attachments; never assume restarting a service restores old processes. |
| H06 | Place any autonomous coordination workflow on the cloud management host or another cloud service. Persist its progress and make recovery idempotent; work that depends on laptop-side logic pauses when the laptop is offline. |
| H07 | Keep management-host recovery separate from AgentCore compute/conversation recovery. AgentCore idle/max-lifetime policies still apply while the management host is running. |
| H08 | Begin with one active management host. Before adding failover or multiple controllers, implement controller leases to prevent competing connectors and duplicate orchestration. |
| H09 | For an ECS deployment, supply a compatible remote-access endpoint, persistent external state, and task-replacement reconciliation. Do not assume ECS Exec provides Herdr's SSH transport or that service replacement preserves sockets/processes. |

## Design constraints

| ID | Constraint |
| --- | --- |
| C01 | Keep implementation and test code under `src/`. Keep project/build configuration at the repository root or in `.github/`. |
| C02 | Keep the README focused on the repository goal. Maintain requirements and design in these root-level files rather than separate guides. |
| C03 | Use Herdr's plugin config/state directories for user data; do not write runtime state into a managed installation. |
| C04 | Resolve AWS credentials through the normal credential chain. Do not persist credentials, signed URLs, or terminal transcripts. |
| C05 | Write connection state atomically and record a launch attempt before sending it. Reject unsupported state/config versions. |
| C06 | Restore local terminal settings on exit and cancel input/output tasks cleanly. |
| C07 | Use public Herdr interfaces without a core fork or private protocol dependency. |
| C08 | Keep automated tests offline. Cloud operations require an explicitly selected runtime and authorized test activity. |
| C09 | Keep orchestration Herdr-native and connect directly to AgentCore using AWS IAM. Exclude Cognito, end-user account management, and dependencies on Jindouyun's proposed platform services. |

## Prototype boundaries

These remain absent from the current implementation. The process/compute recovery items are now explicit next-increment requirements above, not implemented features.

- Provisioning VPC/S3 Files/gateway infrastructure (the included deployment currently uses public networking and ephemeral coding state).
- Automated EC2/ECS management-host deployment, recovery, and failover.
- Windows terminal support.
- Restarting OpenCode from a persisted conversation or recovering after compute termination.
- Automatic reattachment after a Herdr management-server restart, whether laptop- or cloud-hosted.
- Authoritative remote OpenCode lifecycle events.
- Making Herdr's local Git, worktree, or file actions operate remotely.
- First-party endorsement or automatic publication of the plugin.

Outside the plugin's product scope: Cognito/end-user authentication, per-user Runtime authorization catalogs, a DynamoDB-backed customer registry, and Jindouyun control-plane integration.

## Acceptance criteria

| Area | Required outcome | Current evidence |
| --- | --- | --- |
| Plugin contract | Herdr accepts the manifest and its declared commands match implemented entrypoints. | Offline tests, isolated Herdr 0.9.5 registry validation, and live new/attach/stop actions. |
| Owned runtime provisioning | Build and deploy the included image with role-based Bedrock access, then connect using its saved profile. | AWS deployment and image update passed. Herdr model turn, process environment without static credentials or the compatibility shim, detach/reattach, context-aware follow-up, and test-session stop all passed. Full post-expiry credential rotation remains pending. |
| Runtime lifecycle | Document per-session limits; report actual active work as `HealthyBusy`; distinguish detachment, stop, and recoverable state. | Deployed idle timeout is 900 seconds and maximum lifetime 28,800 seconds, with no persistent filesystem. Cloud tests verified busy/idle transitions during real OpenCode shell work, Bedrock generation, and process death. Full-duration idle/max-lifetime tests remain pending. |
| Waiting for input | A permission/question wait is idle when no other tracked work is active; a reply resumes busy reporting until the turn finishes. | A real Bedrock question/wait/reply/completion cycle passed against the deployed health endpoint. Event regression tests additionally cover permission waits, multiple requests, other active sessions, and the 16-minute-work/15-minute-idle timeline. Actual AWS termination timing remains unverified. |
| Terminal transport | Input/output bytes and resize messages survive a round trip. Local terminal modes restore on failure. | Live AgentCore shell input/output and resize before/after reconnect; local WebSocket/PTY tests. Full pane-layout/resize matrix pending. |
| Session identity | Reconnect uses the original runtime-session/shell pair without another launch. | Live same-PID/environment reattach and an OpenCode follow-up turn retaining conversation context; offline tests. |
| Failure handling | Uncertain input is not replayed; takeover stops retries; a missing original PTY does not trigger another agent launch. | Offline tests. |
| Storage and updates | Records remain outside the installation; locks prevent concurrent attachment; profile changes do not retarget saved sessions. | Offline storage tests; live update test pending. |
| Real cloud workflow | Multiple remote OpenCode TUIs work in Herdr, including prompting, dialogs, status detection, resize, detach, reconnect, and stop. | Single-agent prompt/wait/read, detach/reattach, follow-up turn, and stop passed. Five distinct sessions completed concurrent news retrieval/translation, result collection, follow-up prompts, and requested cleanup. Small tiled viewports exposed an OpenCode/Bun crash; dialogs, interrupted-network behavior, and durable workflow recovery remain pending. |
| Small-viewport failure | A failed remote TUI must not be mistaken for a healthy idle agent or receive uncontrolled terminal input. | Known gap: OpenCode 1.18.30/Bun 1.3.14 crashes at 35×20 before mouse input, while the connector can remain connected. Zoomed view is the current workaround; process-aware failure handling is pending. |
| Platform compatibility | Supported Python versions pass on macOS and Linux. | Local Python 3.13/macOS verified; CI matrix configured, remote CI pending. |
| Clean execution | A new independent binding gets fresh compute and its own persistent-home namespace by default; explicitly selected existing files are preserved. | Pending S3 Files home/bootstrap integration and live validation. |
| Runtime credentials | Temporary execution-role credentials remain refreshable without copying credentials into plugin state or requiring laptop-side renewal. | Opt-in wrapper implemented. Fresh Bedrock turns, absence of static credentials in OpenCode, and same-session reattachment passed live validation. Full credential-lifetime rollover remains unverified. |
| Process recovery | Resume after OpenCode exits preserves execution binding, files, and conversation while using a new process/PTY. | Manually verified after credential expiry while compute survived, using the saved OpenCode session and a replacement shell. No automated resume action. |
| Compute recovery | Stop and resume with the same runtime session ID restores saved files and the primary conversation; stop completion is respected. | Not implemented. |
| Herdr rebinding | A replacement pane reconnects the same saved execution binding while respecting Herdr's live-agent naming rules. | Recovery/rebinding behavior not implemented. |
| Recovery failure | Missing storage or incompatible runtime versions require explicit recovery/reset; concurrent recovery does not duplicate agent launches. | Not implemented. |
| Laptop independence | With management on EC2, sleep/reboot the laptop during a task; the cloud server/connectors remain running and the same agent is visible after client reconnect. | Deployment and live validation pending. |
| Cloud coordination | A cloud-side coordinating workflow advances between agents while the laptop is offline. | Workflow selection/implementation and live validation pending. |
| Management-host recovery | Restart/replace the management host; retained state identifies existing cloud agents and reattachment does not duplicate launches or workflow actions. | Automatic reconciliation and live validation pending. |
| Remote plugin execution | Plugin actions execute on the selected cloud Herdr server and use its configuration and instance role, without copying laptop credentials. | Live remote-machine validation pending. |
| Persistent coding files | Repository state, uncommitted changes, configuration, skills, and OpenCode history survive compute stop/replacement using the same recorded S3 Files paths. | Not implemented or validated. |
| Remote Working Directory | A pane starts in the selected persistent repository without the launcher forcing it back to an ephemeral home. | Not implemented. |
| Multiple shells | Additional agent/helper-shell panes use distinct shell IDs inside the selected runtime session; shell operations do not stop sibling work. | Not implemented. |

## Follow-up priorities

1. Extend the verified single-agent and five-agent live workflows to dialogs, forced network outages, durable coordination recovery, and the full pane resize/layout matrix; preserve the tested version baseline.
2. Extend version-1 records into Herdr-native execution bindings with persistent-home and remote Working Directory paths; preserve existing records through migration.
3. Integrate the configured S3 Files mount, persistent OpenCode/configuration/skills paths, and runtime-side bootstrap/process supervision. Validate file persistence before implementing recovery claims.
4. Establish a single EC2 management host with supervised Herdr, host-installed plugin, instance-role credentials, and persistent management state. Validate laptop sleep/reboot and remote plugin actions.
5. Add explicit resume, management-host reconciliation, and additional shell panes with clearly scoped stop operations. Validate process restart, compute stop/resume, host replacement, runtime-version changes, and concurrent recovery.
6. Validate GitHub-managed installation and updates before community publication. Add authoritative lifecycle events and cloud workflow recovery as needed; consider ECS and multi-host failover after the single-host contract is validated.
