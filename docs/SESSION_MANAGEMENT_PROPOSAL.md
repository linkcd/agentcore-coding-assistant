# Discussion proposal: cloud management and durable work

**Status:** Discussion draft. This is not an approved implementation plan.

**Confirmed goal:** Run Herdr management and coordination on EC2. Run assistants selected by named runtime settings in AgentCore.

**Discussion date:** 2026-10-17.

**Scope:** Hosting, execution identity, persistent state, and recovery.

**Related:** [Design](DESIGN.md), [requirements](REQUIREMENTS.md), and [glossary](DESIGN.md#glossary).

Examples use placeholders. Actual profiles and execution records remain outside the repository.
Storage and recovery details still need decisions and validation.

## 1. Recommendation

Treat worker compute as replaceable. Keep work identity, files, and recovery state durable.
A healthy worker can stay warm for efficiency.
Correctness must not depend on one process, PTY, pane, or microVM surviving.

Run ongoing management and coordination in AWS.
The laptop provides access and viewing. Closing it must not remove the manager or coordinator.
Host access and worker persistence are separate choices.

For persistence and recovery:

1. Keep the current AgentCore microVM model initially.
2. Use S3 Files for workspaces, artifacts, non-secret configuration, skills, and checkpoints.
3. Extend the existing connection record into a durable execution binding.
4. Define explicit attach, resume, stop, and archive operations.
5. Start with one active controller and one active writer per independent workspace/conversation.

There is no need to restart healthy workers after every prompt or add a customer registry service.

### 1.1 Full-cloud placement and responsibility

```text
Operator terminal/browser: access and viewing
        |
        | Selected access method, for example SSO + standard SSM
        v
EC2 management host
  Herdr TUI when accessed through SSM
  Herdr server, plugin, and connector processes
  Master/coordinator and saved workflow progress
  Retained EBS-backed management configuration and bindings
        |
        | SigV4-signed WebSocket over TLS; instance role
        v
AgentCore Runtime
  OpenCode workers and tools
  Execution role -> Bedrock
  S3 Files -> persistent workspaces/checkpoints (planned)
```

A coordinator left on the laptop still pauses when the laptop sleeps.
Local development is permitted, but it is not the unattended target.

Retained EC2 storage preserves management files, not processes or remote worker files.
Manager registry/workflow recovery and worker file/conversation recovery are separate boundaries.

### 1.2 Authentication conclusion: no plugin protocol change required

The existing Boto3 credential chain and SDK SigV4 path support EC2 instance profiles.
SSM, browser, or SSH access to EC2 does not change that connector path.

| Boundary | Identity and responsibility |
| --- | --- |
| Human → EC2 | IAM Identity Center/SSO or other short-term federated access authorizes the chosen host-access mechanism. |
| EC2 → AgentCore | The instance role authorizes connector operations. The SDK resolves and refreshes credentials. |
| OpenCode → Bedrock/tools | The AgentCore execution role supplies worker permissions independently. |
| Build/deployment | A deployment identity needs extra CloudFormation, IAM/PassRole, and ECR permissions. These need not belong to the everyday manager. |

On EC2, set connector `aws_profile` to `null` unless a deliberate role-based named profile is required.
Attach the instance role, require IMDSv2, and permit access to metadata and required AWS endpoints.
Remove conflicting static credentials, stale SSO selections, and metadata-disabling settings from the service environment.
Do not export a one-time credential snapshot at daemon startup.

Plugin `--profile` selects a runtime configuration, not an AWS identity.
The owned image's `AWS_PROFILE=default` selects the Node provider inside AgentCore.
It does not instruct the EC2 manager to use a named host profile.

The connector does not require static SSH keys, IAM user keys, custom API keys, or laptop credential forwarding.
This is IAM/environment setup, not an authentication-code migration.

Relevant code:

- [AWS adapter](../src/herdr_plugin/herdr_agentcore/agentcore.py): credential resolution and signing.
- [Profile model](../src/herdr_plugin/herdr_agentcore/models.py): host credential selection and runtime target.
- [Shared worker launcher](../src/agentcore_runtime/common/runtime.py): environment inheritance, working directory, and process startup.
- [OpenCode adapter](../src/agentcore_runtime/opencode/image/assistant.py): execution-role provider selection.
- [CDK stack](../src/agentcore_runtime/runtime-stack.ts): execution-role permissions and runtime resources.
- [Connection contract](../src/runtime_contract/README.md): versioned data between runtime publishers and connectors.

Code compatibility is established. EC2 instance-role/SSM deployment validation remains pending.

### 1.3 EC2 access is a separate architectural concern

For access without permanent SSH-key management, start with AWS CLI SSO and a standard SSM shell.
Run the Herdr TUI on EC2 through that shell.
Browser Session Manager is another access option.
Standard SSM needs neither an SSH daemon nor inbound port 22.

Herdr's native `--remote` and saved-machine connection use an SSH bridge.
A standard SSM shell runs the TUI on EC2; it does not implement that bridge.
SSH-over-SSM provides a tunnel but still requires SSH authentication.
EC2 Instance Connect can authorize temporary SSH keys, but remains an SSH option.

Install Herdr, the plugin, dependencies, and profiles on EC2.
Supervise the server under a stable Unix service account with retained state paths.
Use the same account/session configuration for interactive access.
A Unix service account is not an IAM user and does not inherently need an SSH key.

A viewer disconnect must leave the server and connectors running.
Reconnect to that server rather than start a second manager.
Keep SSM timeout, SSO expiry, connector reconnect, and AgentCore lifecycle limits distinct.
An always-on EC2 host does not extend worker compute lifetime.

Validate rendering, shortcuts, paste, resize, viewer timeout/disconnect, instance-role refresh, and manager restart.
The current provisioner deploys AgentCore, not EC2, its service manager, or SSM configuration.

## 2. Current implementation versus proposed behavior

| Area | Current behavior | Proposed change |
| --- | --- | --- |
| IDs | Saved connection, runtime-session, and shell UUIDs with a profile snapshot. | Retain binding identity and record execution generations. |
| Names | Herdr live aliases belong to the current pane occupant. | Persist desired names and restore them on recovery. |
| Attach | Reuse the original live PTY. | Keep this path and add confirmed replacement recovery. |
| Worker state | Ephemeral files and OpenCode data. | Persistent workspace and consistent checkpoints. |
| Lifecycle | 15-minute idle timeout and 8-hour microVM maximum. Earlier activity health is deployed. | Make termination recoverable through checkpoints. |
| Management | Host-local records. No deployed EC2 manager. | EC2 coordinator, retained state, and host reconciliation. |
| Authentication | Boto3 and SigV4 WebSockets. | Use the same code with an EC2 instance role. |

An earlier deployed refactor added validated records, classified errors, nonblocking output, staged updates, and concurrent health tracking.
Its cloud activity and Herdr model/attachment probes passed.
The source split separates runtime infrastructure, the connector, and their contract.
Both shared-image examples passed short cloud model/attachment probes on disposable CDK deployments. OpenCode also passed activity-health checks.
Codex work-health, sandbox/tool execution, and long-duration behavior remain unqualified.
Runtime infrastructure now uses official AWS CDK. Named settings such as `opencode` and `codex` select configuration, not hardcoded assistant types.
The saved `runtime_profile` reference is separate from the local Herdr connection profile and its recognition hint.
Storage and automatic recovery remain unimplemented.
`HealthyBusy` reports active work; it cannot preserve files or extend the maximum lifetime.

## 3. Identity model: what maps to what?

### 3.1 The identifiers have different jobs

| Identifier | Purpose and lifetime |
| --- | --- |
| Connection/binding UUID | Canonical saved work identity. Reuse current `id` across replacement. |
| Herdr agent name, such as `cloud-1` | Human-readable live alias. It can disappear when the occupant ends. |
| Herdr server/session + pane ID | Current attachment. Replaceable and server-scoped. |
| Runtime ARN + endpoint/version | Deployment context. Change only through explicit migration. |
| Runtime session ID | Routing identity for related invocations and supported stop/resume cycles. |
| Shell ID | Particular PTY. Reuse for attachment; replace with a replacement PTY. |
| OpenCode conversation ID | Saved conversation. Durable only with its application data. |
| Workflow/task ID | Coordination work assigned to a worker. It need not equal the binding ID. |

Resolve runtime ARN, endpoint, and runtime session ID together.
Original-terminal attachment also requires the shell ID.

### 3.2 Current mapping for a name such as `cloud-1`

```text
Herdr live name: cloud-1
  -> Herdr server + pane
  -> metadata: connection=<short UUID>
  -> full connection record
       id: <connection-uuid-A>
       name: opencode-agentcore-runtime-<short-id>
       profile.runtime_arn: <runtime-arn>
       profile.endpoint: <endpoint>
       runtime_session_id: <runtime-session-uuid-A>
       shell_id: <shell-uuid-A>
```

Records are at `$HERDR_PLUGIN_STATE_DIR/connections/<connection-uuid>.json`.
The short token is for display/discovery. Reject ambiguous prefixes and use the full UUID for operations.

Renaming a Herdr agent does not synchronize the alias into the plugin record.
`new --name` labels the record, not the Herdr live agent.
Name-based recovery after a pane disappears is therefore incomplete.

### 3.3 Proposed durable mapping

```text
Binding: <connection-uuid-A>
  |-- desired Herdr name
  |-- persistent workspace
  |-- saved OpenCode conversation
  |-- latest complete checkpoint
  `-- current execution generation
        |-- runtime ARN + endpoint/version
        |-- runtime session ID
        |-- shell ID
        `-- Herdr server/session + pane
```

Illustrative additions, not a final schema:

```yaml
id: <existing-connection-uuid>
name: <work-label>
desired_agent_name: cloud-1
profile: <saved-profile-snapshot>
runtime_session_id: <runtime-session-uuid>
shell_id: <current-shell-uuid>
execution_generation: <monotonic-counter>
persistent_root: /mnt/s3files/herdr/<binding-uuid>
remote_cwd: /mnt/s3files/herdr/<binding-uuid>/repo
runtime_profile: <named-settings-reference>
conversation_id: <assistant-native-conversation-id>
checkpoint_manifest: <latest-complete-manifest-path>
runtime_compatibility: <runtime-and-opencode-versions>
herdr_attachment:
  server: <server-identity>
  session: <herdr-session-identity>
  workspace: <workspace-id>
  tab: <tab-id>
  pane: <pane-id>
```

Introduce fields through a deliberate versioned migration.
Retain snapshots, atomic writes, locks, and launch-at-most-once behavior.
Expose the full binding ID through an appropriate Herdr field while permitting short display text.
Restore the desired alias after agent recognition.
Report occupied or historical duplicate names instead of selecting the newest record silently.

## 4. Reuse the session ID without keeping the compute alive forever

AWS documents that another invocation can obtain fresh compute for a stopped session ID.
Stable session identity is therefore compatible with replaceable compute.

- Reuse the recorded session ID for normal stop/resume on the same runtime.
- Allocate a new session UUID for new independent work.
- Permit a new runtime/session during explicit migration while retaining the binding and workspace.
- Record execution generations so delayed results cannot masquerade as the current run.
- Do not allocate a replacement because a request timed out. The original request might have succeeded.

Key storage by binding UUID, not only by the current AWS session ID or friendly name.

### Example: resume `cloud-1`

1. Resolve the name to one binding.
2. Load runtime context, IDs, paths, and checkpoint metadata.
3. If the original PTY/process survives, reattach without launch.
4. If replacement is necessary, establish exclusive ownership.
5. Validate storage and checkpoint compatibility.
6. Obtain the appropriate compute/session.
7. Restore application state to local runtime storage.
8. Open a replacement shell and launch with the saved conversation ID.
9. Bind the pane and restore the alias under Herdr's uniqueness rules.

If remote state is uncertain, report recovery required rather than create a competing writer.

### Example: create `cloud-6`

1. Allocate a binding UUID and separate persistent namespace by default.
2. Allocate runtime-session and shell UUIDs.
3. Persist complete intent before connecting or launching.
4. Initialize the workspace once.
5. Launch OpenCode and capture its conversation identity.
6. Attach the pane and register the live alias.

UUID strings satisfy the documented session-ID length requirement.
Explicit project reuse must not overwrite files or accidentally share a conversation database.

## 5. Persistent storage: the EBS analogy and its limits

Proposed layout:

```text
/mnt/s3files/herdr/<binding-uuid>/
  repo/                 Repository, Git metadata, and working changes
  config/               Non-secret tool configuration
  skills/               Worker-specific skills
  artifacts/            Selected results
  checkpoints/          Versioned application backups and manifests
  recovery.json         Identity and recovery metadata
```

Keep executables in the image.
Keep PIDs, sockets, leases, and disposable caches local to compute.
Use the execution role. Do not checkpoint credentials or signed URLs.

| Storage choice | Fit and limits |
| --- | --- |
| S3 Files with microVMs | Preferred initial target for durable work across replacement and runtime versions. Requires VPC access and filesystem validation. |
| Managed session storage Preview | Per-session persistence without a customer filesystem. Reviewed documentation describes resets after 14 inactive days and runtime-version changes. |
| AgentCore Instances with EBS | Persistent worker volumes can survive stop and reattach under the same session ID. This is a different deployment/compute model. |

S3 Files is a network filesystem, not an EBS block device.
AWS documents NFSv4.2, close-to-open consistency, and no hard-link support.
Validate Git, dependency managers, rename/flush, and concurrency before relying on them.
Use the mounted filesystem for work; avoid simultaneous direct edits to backing S3 objects.

The current runtime uses public networking.
S3 Files needs VPC connectivity, mount targets, mount/write permissions, and the appropriate UID/GID.
Shared-access-point directories organize work; they are not independent IAM security boundaries.

## 6. OpenCode database and checkpoint strategy

Repository persistence alone does not preserve a conversation.
Recover the native conversation data and its ID together.

Recommended initial strategy:

1. Keep live SQLite data on local disk.
2. Create consistent, versioned backups with SQLite backup support or a validated native export.
3. Record conversation ID, checkpoint generation, compatibility, workspace identity, and task progress in a manifest.
4. Write and verify the payload before publishing its manifest as complete.
5. Retain the previous valid checkpoint until publication succeeds.
6. Restore only a complete, compatible checkpoint before starting OpenCode.

SQLite WAL has network-filesystem restrictions.
Copying a live `.db` file alone can omit committed WAL data.
Directly hosting the live database on S3 Files needs a separate compatibility decision and evidence.

Checkpoint completed turns, important completed tools, user-input waits, and graceful stops.
Add periodic checkpoints during long work. Do not depend only on a shutdown signal.

Define a recovery-point objective: how much recent progress may be lost?
Define a recovery-time objective: how quickly must replacement become usable?
A consistent database backup is not an atomic transaction across files and external systems.
Record uncertain/in-flight actions and reconcile actual results during recovery.
If live-database disk semantics are essential, evaluate AgentCore Instances/EBS separately.

### Waiting for user input needs explicit recovery semantics

An unanswered question is idle when no other tracked work is active.
This allows compute to end while the human is away.

Preserve enough context to present or continue the question later.
A restored database does not guarantee that an old in-memory request ID is valid.
Define native OpenCode behavior for interrupted tools, later answers, and fresh permission requests.
Never infer approval from an old prompt or assume an interrupted tool completed.

## 7. Lifecycle contract

| Operation | Intended contract |
| --- | --- |
| New | Create a binding and independent workspace by default. |
| Attach | Reconnect to an original live terminal/process. |
| Resume | Select warm attachment or confirmed checkpoint-based replacement. |
| Detach | Close transport; leave work subject to lifecycle limits. |
| Stop | Quiesce/checkpoint when possible, stop compute, and retain work. |
| Archive | Mark work finished and retain results according to policy. |
| Delete work | Explicitly delete persistent data, separately from stopping compute. |

Graceful stop should drain/cancel work, checkpoint, save recovery metadata, request stop, and confirm completion before replacement.
Use supported AgentCore behavior for completion detection. The current plugin has no completion waiter.
The local `stopped` label records an accepted request only.
Provisioning/stop conflicts need bounded retries without changing intended identity.

Abrupt failure uses the last complete checkpoint. No pre-stop callback is guaranteed.
Logical work can span many compute generations, but each microVM still has its maximum lifetime.
Report `HealthyBusy` only for genuine tracked work.

## 8. Swarm ownership and coordinator state

Use separate checkouts/branches and OpenCode state for independent workers.
Share reference data deliberately. Do not give all workers one writable home/database.

Start with one active writer per binding.
Before takeover, confirm the old writer stopped or is prevented from further writes.
An expired controller lease does not prove the remote writer stopped.
Local locks are insufficient across multiple managers.

Persist assignments, dependencies, completions, and uncertain outcomes.
A replacement coordinator must not duplicate workers, deployments, pull requests, or other external effects.
Use idempotency where supported and reconcile uncertain delivery elsewhere.

Herdr remains the live terminal/orchestration layer.
The connector owns execution bindings and host-side recovery decisions.
Runtime definitions own worker startup, persistent state, and assistant-specific recovery adapters.
Their small connection contract does not yet define checkpoint or resume operations.
Neither component needs a separate customer account or registry platform.
Hosting the manager on EC2 is distinct from choosing AgentCore Instances for workers.

For laptop-to-EC2 migration:

1. Establish exclusive control.
2. Transfer required non-secret profiles/bindings privately.
3. Select the EC2 instance role for connector access.
4. Reconcile remote identities before attachment or replacement.

Do not transfer SSO caches, static credential files, sockets, or PID state as manager recovery data.
Do not start two active controllers by copying records alone.

## 9. Proposed implementation order

1. **EC2 baseline:** deploy one supervised manager, instance role, retained state, and selected access method. Place coordination there and test viewer independence.
2. **Identity/schema:** define binding additions, name conflicts, namespaces, manifests, and record migration.
3. **Storage:** integrate S3 Files and test mounts, tools, skill discovery, and survival across compute/image replacement.
4. **Checkpoints:** capture conversation identity and publish consistent versioned backups with measurable recovery points.
5. **Resume:** implement exclusive ownership, confirmed replacement, restore, new shell creation, and Herdr rebinding.
6. **Failures:** test crashes, expiry, unanswered questions, manager restarts, competing recovery, and uncertain tools.

Evaluate failover only after the single-controller contract works.
Moving management to EC2 does not make worker state durable.

## 10. Acceptance scenarios

Core scenario:

> Make uncommitted changes and checkpoint a conversation. Terminate the worker, recreate compute, and resume the expected files and conversation without duplicate execution.

Additional scenarios:

- Use short-term host access without static SSH/IAM user keys. Verify connector calls use the instance role.
- Disconnect or time out the viewer. Verify management and coordination continue, then reconnect to the same session.
- Attach a healthy detached worker without another launch.
- Create `cloud-6` without changing `cloud-1` files, state, or identifiers.
- Rename/replace a pane without losing the binding.
- Stop during a question wait, restore state, and handle a later answer correctly.
- Crash during a tool or checkpoint. Use the last complete checkpoint and identify uncertain effects.
- Update the image. Preserve files and require explicit migration for incompatible state.
- Restart the manager. Reconcile before replacement.
- Attempt simultaneous resumes. Permit only one writer.
- Archive/delete only through the explicit corresponding operation.

## 11. Decisions for later discussion

1. What does a binding represent: workspace/conversation, worker, or task? Initial recommendation: workspace/conversation, with separate task IDs.
2. What recovery-point and recovery-time objectives apply during long tools?
3. Are S3 Files and local SQLite checkpoints sufficient, or is Instances/EBS needed?
4. Where is management state retained, backed up, and reconstructed?
5. How are names scoped, renamed, archived, and disambiguated across servers?
6. How does native OpenCode recover questions, permissions, and interrupted tools?
7. Which sharing patterns are supported, and how are old writers prevented from writing after takeover?
8. What retention, deletion, and version-migration rules apply?
9. Which EC2 access method meets terminal needs, with what OS identity, session policy, and audit controls?

## References

- [AgentCore session reuse](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html).
- [Lifecycle settings and compute limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html).
- [S3 Files and storage lifecycles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html).
- [AgentCore Instances and EBS](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html).
- [SQLite WAL restrictions](https://sqlite.org/wal.html).
- [SDK IMDS provider](https://docs.aws.amazon.com/sdkref/latest/guide/feature-imds-credentials.html).
- [Standard SSM sessions](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html).
- [AWS CLI SSO configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html).
- [SSM Run As](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-preferences-run-as.html).
- [SSH-over-SSM requirements](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-enable-ssh-connections.html).

These statements reflect documentation reviewed for this proposal.
Recheck availability and contracts when implementing the selected compute/storage option.
