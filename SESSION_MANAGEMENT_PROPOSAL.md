# Discussion proposal: cloud-hosted Herdr, disposable agents, durable work

**Status:** Discussion draft, not an approved implementation plan.

**Confirmed hosting goal:** Run the management and worker stack in AWS: EC2-hosted Herdr and coordination, with AgentCore-hosted OpenCode agents. Storage and recovery implementation details remain under discussion.

**Date:** 2026-10-17

**Scope:** EC2-based Herdr management, AgentCore-based OpenCode workers, their identity mapping, and durable state/recovery.

**Related:** [DESIGN.md](DESIGN.md), [REQUIREMENTS.md](REQUIREMENTS.md).

This document records the proposed direction and the identity mapping discussed during development. Identifiers in examples are placeholders; actual deployment configuration and connection records remain outside the repository.

## 1. Recommendation

Treat compute as disposable workers, while keeping the work identity, workspace, and recovery state durable.

The EC2/EBS analogy is useful: terminating a worker should not mean deleting its work. A healthy worker can remain warm for efficiency, but correctness should not depend on that particular process, PTY, pane, or microVM surviving.

The overall hosting target is a fully cloud-hosted execution stack. The laptop is a viewing/control endpoint; closing it should not remove the manager, its connectors, or its ability to coordinate work. EC2 access method and worker persistence are separate choices.

For persistence and recovery, the recommendation is:

1. Keep the current AgentCore microVM execution model.
2. Use S3 Files for durable workspaces, artifacts, non-secret configuration, skills, and conversation checkpoints.
3. Extend the existing plugin connection record into a durable execution binding; do not introduce a separate customer registry service.
4. Add explicit attach, resume, stop, and archive semantics.
5. Start with one active management controller and one active writer per independent workspace/conversation.

This is a proposal for persistence and recovery, not a recommendation to repeatedly kill healthy workers or restart OpenCode after every prompt.

### 1.1 Full-cloud placement and responsibility

```text
Operator's terminal or browser — access and viewing only
       |
       | Chosen EC2 access method, e.g. SSO + standard SSM shell
       v
AWS EC2 management host
  Herdr TUI when accessed through a standard SSM shell
  Herdr background server + plugin + connector processes
  Master agent / coordinator and workflow progress
  Retained EBS-backed management configuration and binding records
       |
       | IAM SigV4-signed WebSocket over TLS; EC2 instance role
       v
AgentCore Runtime
  OpenCode workers + tools
  AgentCore execution role -> Bedrock
  S3 Files -> durable workspaces/checkpoints (planned)
```

All continuously required execution and coordination should run in AWS. An agent or coordinator left on the laptop would still pause when the laptop sleeps, even if its workers are remote. Local development remains possible, but it is not the unattended hosting target.

Retained EC2 storage preserves management files, not running processes. It also does not persist AgentCore worker files automatically. These are two independent recovery boundaries: the manager's registry/workflow state and the workers' workspace/conversation state.

### 1.2 Authentication conclusion: no plugin protocol change required

**Hosting Herdr on EC2 does not require changing how this plugin authenticates to AgentCore.** The existing Boto3 credential provider chain and SDK SigV4 shell-signing path can use an EC2 instance profile natively. Choosing SSM, an AWS browser console, or SSH to access EC2 does not change that host-to-AgentCore path.

| Boundary | Identity and responsibility |
| --- | --- |
| Human -> EC2 access | IAM Identity Center/SSO or other short-term federated credentials authorize access through the chosen mechanism. |
| EC2 Herdr host -> AgentCore | EC2 instance role authorizes the connector's required AgentCore operations; the SDK obtains and refreshes temporary credentials through its provider chain. |
| AgentCore OpenCode -> Bedrock/tools | AgentCore execution role supplies the worker's AWS permissions independently of the EC2 host role. |
| Provisioning/build operations | A deployment identity needs the additional CloudFormation, IAM/PassRole, and ECR permissions. Those privileges need not be part of the everyday management role. |

On EC2, leave each connector profile's `aws_profile` as `null` unless an intentional role-based named profile is required. Attach the appropriate instance role, require IMDSv2, and ensure metadata and the necessary AWS endpoints are reachable. Keep static/exported AWS credentials, stale SSO profile selections, and metadata-disabling settings out of the Herdr service environment so they do not override instance-role discovery. Do not fetch temporary credentials once and export a frozen snapshot at daemon startup.

The plugin's `--profile` selects a runtime configuration; it is not an AWS credential identity. Likewise, the owned worker image's `AWS_PROFILE=default` enables OpenCode's Node credential chain inside AgentCore; it is not an instruction to set a named AWS profile on the EC2 management host.

No static SSH private key, long-lived IAM user access key, custom API key, or laptop credential-forwarding process is required for the plugin's AgentCore connection. This is an EC2/IAM/environment setup requirement, not an authentication-code migration.

Code references: [connector credential/signing path](src/herdr_agentcore/connector.py#L24), [profile fields](src/herdr_agentcore/storage.py#L115), [runtime launcher](src/herdr_agentcore/runtime_image/launch.py#L17), and [runtime execution-role provisioning](src/herdr_agentcore/provision.py#L53). These establish code compatibility; the EC2 instance-role/SSM hosting path still needs deployment validation.

### 1.3 EC2 access is a separate architectural concern

For a workflow without static SSH-key management, the preferred starting point is a native terminal using AWS CLI SSO plus a **standard SSM Session Manager shell**, then the EC2-side Herdr TUI. Browser Session Manager is a useful alternate access path. A standard SSM shell requires neither SSH keys nor an SSH daemon/inbound port 22.

Herdr's native `--remote` / saved-machine connection currently uses an SSH bridge. A standard SSM shell is not a drop-in replacement for that protocol: it runs the TUI on EC2 instead. SSH-over-SSM still requires SSH authentication; SSM supplies the tunnel. EC2 Instance Connect can supply temporary SSH-key authorization without a permanent operator-managed key, but remains an SSH-based option.

The plugin should remain independent of this access choice. Install Herdr, the plugin, dependencies, and runtime profiles on EC2. Run the Herdr server independently under a service manager such as systemd, with a stable Unix service account and retained state paths. Match interactive access to that same account/session configuration. A Linux service account is not an IAM user and does not require an SSH key.

A dropped viewer connection should leave the supervised manager and its connectors running. Reconnect to the existing Herdr session rather than creating a second manager. SSM/browser timeouts, human SSO expiry, the plugin's reconnect window, and AgentCore idle/max-lifetime limits are separate. Native SSM does not eliminate Session Manager policies, and keeping EC2 alive does not extend AgentCore's compute lifetime.

Before calling this hosting setup validated, test terminal rendering, shortcuts/paste/resize, SSM disconnect and timeout survival, same-session reattachment, instance-role credential refresh, and manager restart behavior. The current repository provisions AgentCore, not the EC2 management host or its service/SSM configuration. Worker persistence and automatic manager/worker recovery remain additional implementation work.

## 2. Current implementation versus proposed behavior

| Area | Current behavior | Proposed increment |
| --- | --- | --- |
| Execution identifiers | Connection UUID, runtime-session UUID, shell UUID, and runtime-profile snapshot are saved before launch. | Retain the connection UUID as durable work identity and record execution generations. |
| Herdr names | A live alias such as `cloud-1` belongs to the current Herdr pane occupant. | Persist a desired name and restore the live alias when attaching recovered execution. |
| Reattachment | Reconnect to the same live PTY using its saved identifiers. | Preserve this warm path and add explicit recovery when compute/process replacement is confirmed. |
| Files and OpenCode state | The owned deployment currently uses ephemeral storage. | Persistent workspace plus consistent OpenCode checkpoints. |
| Lifecycle | 15-minute idle timeout, 8-hour maximum microVM lifetime; activity-aware health is deployed. | Checkpoint work so idle/maximum-lifetime termination becomes recoverable. |
| Management | Connector records are host-local; EC2 hosting has not been provisioned/validated by this repository. | Run Herdr, connectors, and the master/coordinator on EC2 with retained management state and reconciliation after replacement. |
| Host authentication | The connector already uses Boto3 and SigV4-authenticated WebSockets. | Use EC2 instance-profile credentials through the same code path; no static-key authentication redesign. |

The health bridge is not storage or recovery. Reporting `HealthyBusy` protects reported active work from idle cleanup, but does not extend the maximum compute lifetime or preserve a conversation after termination.

## 3. Identity model: what maps to what?

### 3.1 The identifiers have different jobs

| Identifier | Meaning | Expected lifetime |
| --- | --- | --- |
| Plugin connection/binding UUID | Canonical identity for the saved execution binding and its workspace. Reuse the existing `id` field. | Durable across worker replacement. |
| Herdr agent name, e.g. `cloud-1` | Human-friendly live alias, unique in the relevant Herdr server. | May disappear when its pane occupant ends. |
| Herdr server/session + pane ID | Where an execution is currently attached. | Replaceable; pane IDs are scoped to a server. |
| Runtime ARN + endpoint/version context | Which AgentCore deployment/configuration executes the work. | Deployment lifetime; may change during an explicit migration. |
| AgentCore runtime session ID | Routing identity for related invocations within a runtime. | Normally reused for related work and supported stop/resume cycles. |
| AgentCore shell ID | A particular remote PTY. | Reused for warm attachment; replaced when that PTY is replaced. |
| OpenCode conversation ID | Which saved conversation OpenCode should load. | Durable when the corresponding application data is preserved. |
| Workflow/task ID, if present | The business task or coordination workflow assigned to a worker. | Independent of the process; not necessarily identical to the workspace binding. |

The AWS routing identity is not just a friendly name. The plugin must resolve the runtime ARN, endpoint, and runtime session ID together. Reattaching the original terminal also requires its shell ID.

### 3.2 Current mapping for a name such as `cloud-1`

```text
Herdr live name: cloud-1
  -> current Herdr server + pane
  -> pane metadata: connection=<short connection UUID>
  -> full plugin connection record
       id: <connection-uuid-A>
       name: owned-runtime-<short-id>
       profile.runtime_arn: <runtime-arn>
       profile.endpoint: <endpoint>
       runtime_session_id: <runtime-session-uuid-A>
       shell_id: <shell-uuid-A>
```

Records are stored at:

```text
$HERDR_PLUGIN_STATE_DIR/connections/<connection-uuid>.json
```

The short metadata token is for display/discovery, not an authoritative identifier. Any lookup based on a short prefix must reject ambiguity; the full UUID is the canonical key.

**Current gap:** assigning or renaming `cloud-1` through Herdr does not synchronize that alias into the saved plugin record. The plugin's record `name` and Herdr's live agent name are separate. The current CLI's `new --name` labels the plugin record; it does not automatically establish the same Herdr live alias. Name-based recovery after a pane disappears is therefore not a complete implemented contract.

### 3.3 Proposed durable mapping

```text
Durable binding: <connection-uuid-A>
  |-- desired Herdr name: cloud-1
  |-- persistent workspace: /mnt/s3files/herdr/<connection-uuid-A>/
  |-- OpenCode conversation: <saved-conversation-id>
  |-- latest complete checkpoint: <checkpoint-generation>
  `-- current execution generation
        |-- runtime ARN + endpoint/version
        |-- runtime session ID
        |-- shell ID
        `-- Herdr server/session + pane
```

Illustrative additions to the existing record—not a finalized storage schema:

```yaml
id: <existing-connection-uuid>
name: <human-readable-work-label>
desired_agent_name: cloud-1
profile: <saved-runtime-profile-snapshot>
runtime_session_id: <runtime-session-uuid>
shell_id: <current-shell-uuid>
execution_generation: <monotonic-counter>
persistent_root: /mnt/s3files/herdr/<connection-uuid>
remote_cwd: /mnt/s3files/herdr/<connection-uuid>/repo
opencode_session_id: <saved-conversation-id>
checkpoint_manifest: <latest-complete-manifest-path>
runtime_compatibility: <runtime-and-opencode-version-information>
herdr_attachment:
  server: <server-identity>
  session: <herdr-session-identity>
  workspace: <current-workspace-id>
  tab: <current-tab-id>
  pane: <current-pane-id>
```

The implementation should introduce these fields through a deliberate versioned migration. It should retain profile snapshots, atomic writes, attachment locks, and the existing at-most-once launch rules.

Publish the full binding ID through an appropriate Herdr metadata/API field while allowing shortened display text. Restore the desired alias only when the recovered agent is recognized. If that name is already occupied, surface the conflict rather than renaming or replacing an unrelated agent. Historical duplicate names also need explicit disambiguation; a name must not silently resolve to whichever record happens to be newest.

## 4. Reuse the session ID without keeping the compute alive forever

Keeping an AgentCore session ID stable is compatible with disposable compute. AWS documents that a stopped session can receive another invocation and obtain new compute under the same session ID.

Recommended policy:

- Reuse the recorded AWS session ID for ordinary stop/resume of the same binding on the same runtime.
- Allocate a new session UUID for a genuinely new independent worker, such as a new `cloud-6`.
- Allow a new AWS session ID or runtime ARN during an explicit replacement/migration, while retaining the durable binding ID and workspace path.
- Record execution generations so an old attachment or delayed result cannot be mistaken for the current run.
- Do not create another session ID merely because a network request timed out. The original request may already have succeeded.

The storage namespace must therefore be keyed by the durable binding UUID, not exclusively by the current AWS session ID or friendly agent name.

### Example: resume `cloud-1`

1. Resolve the requested name to a unique durable binding.
2. Load the saved runtime context, session/shell IDs, persistent paths, and conversation/checkpoint metadata.
3. If the original PTY and process survive, reattach without launching another OpenCode instance.
4. If replacement is confirmed necessary, establish exclusive ownership, validate storage/checkpoint compatibility, and provision or reuse the appropriate AWS session.
5. Open a replacement shell and restore the selected OpenCode state. Launch with the recorded conversation ID, for example through native `--session` support.
6. Bind the new pane and restore the desired Herdr alias, respecting uniqueness.

A connection failure alone is not evidence that compute ended. If the remote state cannot be established, keep the binding in an uncertain/recovery-required state rather than spawning competing writers.

### Example: create `cloud-6`

1. Allocate a new binding UUID and, by default, a separate persistent workspace namespace.
2. Allocate a new AWS runtime-session UUID and shell UUID. UUID strings satisfy the documented session-ID length requirement.
3. Persist the complete intent before connecting or sending launch commands.
4. Initialize the workspace once, launch OpenCode, and capture its conversation identity.
5. Attach it to the requested Herdr tab/pane and register the live alias `cloud-6`.

Deliberately reusing an existing project should be explicit; creating a new worker must not overwrite an existing workspace or accidentally share its conversation database.

## 5. Persistent storage: the EBS analogy and its limits

Proposed workspace layout:

```text
/mnt/s3files/herdr/<binding-uuid>/
  repo/                 # Repository, .git, and uncommitted changes
  config/               # Non-secret user/tool configuration
  skills/               # Worker-specific skills
  artifacts/            # Outputs and useful execution results
  checkpoints/          # Versioned application-state backups and manifests
  recovery.json         # Durable identity and recovery metadata
```

Keep installed executables in the versioned image. Keep PIDs, sockets, health leases, and disposable caches on local runtime storage. Resolve AWS access through the runtime execution role; do not checkpoint temporary credentials or signed URLs.

| Storage choice | Fit and tradeoff |
| --- | --- |
| S3 Files with microVMs | Preferred initial direction for customer-managed, durable workspaces shared across replacement sessions and runtime versions. Requires VPC connectivity; filesystem behavior must be validated. |
| Managed session storage Preview | Convenient per-session microVM persistence without provisioning a BYO filesystem, but current documentation says data resets after 14 days without invocation and after runtime version changes. Not recommended as the sole durable source of work for this design. |
| AgentCore Instances with capacity-provider EBS volumes | Closest to EC2/EBS semantics for a persistent worker disk. Volumes survive stops and reattach on resume with the same session ID. This is a different compute/deployment choice, requiring its own provisioning and connector validation. |

S3 Files is a network filesystem, not an EBS block device. AWS documents NFSv4.2, close-to-open consistency, and no hard-link support. Validate Git operations, dependency managers, rename/flush behavior, and workspace concurrency before depending on them. Treat the mounted filesystem as the workspace access path rather than concurrently editing its backing objects through S3 APIs.

The current runtime uses public networking. Integrating S3 Files requires the VPC, mount targets, network access, execution-role mount/write permissions, and appropriate access-point UID/GID. Namespace directories on a shared access point are an organization/concurrency mechanism, not separate IAM security boundaries.

## 6. OpenCode database and checkpoint strategy

Do not assume that persisting the repository also preserves the conversation. OpenCode's native conversation data and its conversation ID must be recoverable together.

The recommended starting strategy is:

- Keep the live SQLite database on local disk.
- Produce consistent, versioned backups to S3 Files using SQLite's backup mechanism or a validated native export.
- Record the conversation ID, checkpoint generation, runtime/OpenCode compatibility, workspace identity, and relevant task progress in a checkpoint manifest.
- Publish a checkpoint as usable only after its payload is written and verified; retain the previous valid checkpoint until then.
- Restore only a complete, compatible checkpoint to local application storage before launching OpenCode.

SQLite explicitly documents restrictions on WAL over network filesystems. Copying a live `.db` file alone can also omit committed data in its WAL. Putting the live database directly on S3 Files should require a separate compatibility decision and evidence; it is not assumed safe because ordinary text files work.

Checkpoint at completed turns, important completed tool steps, transitions into a user-input wait, and graceful stop. Add periodic checkpoints during long work so recovery does not depend solely on receiving a shutdown signal.

This provides a defined recovery point, not zero-loss memory restoration. We need to agree on an acceptable recovery-point objective: how much recent conversation/progress can be lost after an abrupt failure? We also need a recovery-time objective: how quickly should replacement work become usable?

An SQLite backup only makes the database snapshot consistent. It is not an atomic transaction across the repository and external systems. Checkpoint publication should use a safe work boundary where possible, record in-flight/uncertain actions, and reconcile the actual workspace and external results during recovery.

If live-database durability with native disk semantics is a stronger requirement than the microVM/S3 Files model, evaluate AgentCore Instances with EBS before committing to a network-filesystem database design.

### Waiting for user input needs explicit recovery semantics

The deployed health bridge intentionally reports an unanswered question as idle when no other tracked work is active. That permits compute to stop while the human is away.

The recovery design must preserve enough context to present or continue that question later. An old in-memory question/permission request is not guaranteed to become valid again just because the conversation database is restored. Define how native OpenCode treats interrupted tool requests, how a later answer is associated with the saved question, and when a fresh permission request is needed. Never infer approval from an old prompt or assume that an interrupted tool completed.

## 7. Lifecycle contract

| Operation | Intended contract |
| --- | --- |
| New | Create a new durable binding and independent workspace by default. |
| Attach | Reconnect to an existing live terminal/process. |
| Resume | Resolve a saved binding and choose warm attachment or explicit checkpoint-based process/compute recovery. |
| Detach | Close the terminal connection while leaving work subject to runtime lifecycle limits. |
| Stop | Quiesce/checkpoint when possible, terminate compute, and retain durable work. |
| Archive | Mark logical work finished and retain its results according to policy. |
| Delete work | Explicitly delete persistent data; distinct from stopping compute or closing a pane. |

Graceful stop should drain or cancel work deliberately, flush/checkpoint state, persist the recovery marker, request compute stop, and establish stop completion before replacement starts. The exact completion-detection mechanism must use supported AgentCore behavior; the current plugin has no stop-completion waiter. Provisioning/teardown conflicts need bounded retries without changing the intended identity.

Abrupt failures must recover from the last complete checkpoint. No pre-stop callback can be assumed to run after a crash or platform termination.

The 8-hour microVM ceiling remains. A logical task can span many compute generations, provided each generation can recover from durable state. `HealthyBusy` should reflect genuine tracked work, not be permanently asserted to keep a worker alive.

## 8. Swarm ownership and coordinator state

Use separate checkouts/branches and separate OpenCode state for independent workers. Shared reference data or tools can be shared deliberately; do not give every worker the same writable home and conversation database.

Begin with one active writer per binding. Before takeover, confirm that the previous writer is stopped or fenced from further writes. An elapsed controller lease alone is not proof that a remote worker has stopped. A simple local lock is useful for one manager, but is insufficient for multiple independent management hosts.

Persist the coordinator's assignments, dependencies, completions, and uncertain outcomes as well as worker files. Replacing a master process must not silently start duplicate workers or repeat a deployment, PR creation, or other external side effect. Use idempotency where the target operation supports it, and reconcile outcomes when delivery is uncertain.

Herdr remains the live terminal/agent orchestration layer. The plugin owns durable execution bindings and recovery. No Cognito account platform, Jindouyun dependency, or separate customer-registry service is required for this increment.

The confirmed target places Herdr's server, connectors, and coordination on an always-on EC2 management host with retained state. Running the **Herdr manager on EC2** is separate from choosing **AgentCore Instances** for worker compute. The former does not change the latter's microVM limits. The laptop is a viewing/control client.

When migrating management from a laptop, do not simply copy binding records and start two active controllers. Establish exclusive control, transfer the required non-secret profiles/bindings privately, switch host authentication to the EC2 role, and reconcile saved remote identities before attaching or replacing work. Do not migrate human SSO caches, static credential files, or live socket/PID state as part of that transfer.

## 9. Proposed implementation order

1. **EC2 management baseline:** provision a single always-on host, role-based AWS access, supervised Herdr, retained configuration/bindings, and the selected access method. Place the master/coordinator there and validate viewer-disconnect independence. This moves execution to the cloud without requiring changes to the plugin's authentication protocol.
2. **Identity and schema:** define the binding additions, name lookup/conflict rules, storage namespace, checkpoint manifest, and migration from current records.
3. **Storage:** integrate S3 Files and validate mount readiness, Git/tool compatibility, configuration/skill discovery, and data survival across compute termination and image updates.
4. **Checkpointing:** capture OpenCode conversation identity and implement consistent, versioned backups with measurable recovery-point behavior.
5. **Explicit resume:** implement exclusive ownership, warm attachment versus confirmed replacement, state restoration, new shell creation, and Herdr rebinding.
6. **Failure and swarm validation:** test crashes, idle expiry, maximum lifetime, unanswered questions, manager restarts, competing resume attempts, and uncertain tool results. Evaluate multi-manager failover only after the single-controller contract works.

EC2 hosting and durable worker recovery are separate milestones. Moving the manager first provides the desired cloud placement; it does not make the workers' current ephemeral state durable.

## 10. Acceptance scenarios

The core acceptance test is:

> Make uncommitted code changes, checkpoint a conversation, terminate the worker, recreate compute, and resume the same logical work with the expected files and conversation—without duplicate execution.

Additional scenarios:

- Connect to EC2 using short-term/federated access without static SSH or IAM user keys; verify connector calls use the intended instance role.
- Disconnect or time out the viewer during work; verify the EC2 Herdr server, connectors, and cloud-side coordination continue, then reconnect to the same session.
- Detach and attach a healthy worker without relaunching it.
- Start `cloud-6` without modifying `cloud-1`'s files, state, or identifiers.
- Rename or replace a Herdr pane while preserving the durable binding and runtime mapping.
- Stop during a user-input wait, restore the conversation, and correctly handle the later answer.
- Crash during a tool operation or checkpoint write; use the last complete recovery point and identify uncertain effects.
- Update the runtime image; verify storage survives and incompatible state requires explicit migration.
- Restart the management host; reconcile existing workers before attempting replacement.
- Attempt concurrent resumes; only one writer may become active.
- Delete/archive logical work only through the corresponding explicit operation.

## 11. Decisions for later discussion

1. What does a durable binding represent initially: one coding workspace/conversation, one named worker, or one task? Recommendation: workspace/conversation, with task IDs recorded separately as needed.
2. What recovery-point and recovery-time targets are acceptable, especially during long tool calls?
3. Is S3 Files plus local SQLite checkpoints sufficient, or is EBS-backed live state important enough to choose AgentCore Instances?
4. Where is the authoritative management registry retained, and how is it backed up/reconstructed independently of a laptop?
5. How should saved names be scoped, renamed, archived, and disambiguated across Herdr servers?
6. How are pending questions, permission requests, and interrupted tools recovered through native OpenCode behavior?
7. Which shared-workspace patterns are supported, and what writer-fencing mechanism is required before enabling multiple controllers?
8. What checkpoint retention, workspace deletion, and version-migration policies should apply?
9. Which EC2 access path offers the required terminal experience, and how should its OS identity, session policies, and audit controls be configured independently of AgentCore authentication?

## References

- [AgentCore session lifecycle and reuse](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)
- [AgentCore lifecycle settings and compute limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [AgentCore filesystem configurations, S3 Files semantics, and storage lifecycles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html)
- [AgentCore Instances and persistent EBS volumes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html)
- [SQLite WAL behavior and filesystem restrictions](https://sqlite.org/wal.html)
- [AWS SDK IMDS credential provider](https://docs.aws.amazon.com/sdkref/latest/guide/feature-imds-credentials.html)
- [Starting standard SSM sessions](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html)
- [AWS CLI IAM Identity Center configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)
- [SSM Run As configuration](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-preferences-run-as.html)
- [SSH-over-SSM requirements](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-enable-ssh-connections.html)

AWS capabilities and limits cited here reflect the documentation reviewed for this discussion. Validate availability and contracts again when implementing the selected storage/compute option.
