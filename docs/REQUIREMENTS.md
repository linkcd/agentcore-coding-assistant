# Requirements

## Objective

Provide a community Herdr plugin for coding agents in AgentCore Runtime.
Separate assistant runtime definitions, terminal connection, and a small shared contract.
`opencode` and `codex` are example named runtime settings. Their names are references, not a connector enum.
See the [design glossary](DESIGN.md#glossary) for technical abbreviations.

## Scope authority

Follow Herdr's workspace, tab, pane, and live-agent model.
Use public extension interfaces for AgentCore bindings, transport, persistence, and lifecycle operations.
Use direct AWS IAM authentication and deployment-level permissions.

Jindouyun is a reference for execution concepts only.
Exclude its proposed CLI/control plane, Cognito, end-user accounts, tenant ownership, and a separate customer registry service.

## Initial scope

- Support Herdr 0.9.5+ on macOS and Linux.
- Support Python 3.11+ with uv-managed dependencies.
- Provision the owned runtime or configure an existing AgentCore runtime with WebSocket Shell access.
- Require a local Docker engine with Buildx/ARM64 support for provisioning.
- Run connectors on the Herdr server host. Run OpenCode and its tools in AgentCore.
- Permit laptop-hosted management for development. Use cloud-hosted management for unattended operation.

## Deployment target

**Terminal/browser access → EC2 Herdr server, connectors, and coordinator → AgentCore coding agents.**

Start with one always-on EC2 management host.
Install the plugin and its configuration there. Run coordination there so it can continue without the laptop.
Use a standard SSM shell with the EC2-side Herdr TUI, or use native Herdr SSH remote-machine access.
This access choice does not change connector authentication.

ECS is a later alternative. It needs compatible remote access, external state, and task-replacement recovery.
This repository has not deployed or validated either management-host option.

## Target lifecycle model

Herdr owns live-agent identity and pane organization.
A durable plugin execution binding records the runtime, shell, persistent paths, and OpenCode conversation.
AgentCore allocates compute from a deployment's image, permissions, network, storage, and lifecycle settings.
One deployment can serve many sessions. A new agent does not need a new deployment.

The current default is one runtime session and one shell per independent agent.
Additional agent or helper shells in an existing session are planned.
Those shells will need separate shell and whole-session operations.

| User intent | Required behavior |
| --- | --- |
| New independent binding | Allocate a new session ID and separate persistent namespace by default. Preserve explicitly selected existing/shared files. |
| Original PTY survives | Reattach to the same shell and process. Do not launch again. |
| Compute survives but the process ended | Open a new shell and explicitly resume the saved conversation. |
| Compute stopped | Reuse the session ID on fresh compute. Remount storage and restore the recorded conversation. |
| Saved state is missing or incompatible | Report recovery-required state. Do not present a new conversation as the original one. |

Only new-agent creation and live-PTY attachment are implemented.
Process replacement and recovery after compute termination remain next-increment requirements.

## Functional requirements

| ID | Requirement |
| --- | --- |
| F01 | Use a standalone Herdr plugin with public manifest and CLI APIs. Support community installation and updates. |
| F02 | Configure named profiles with ARN, region, endpoint, optional host AWS profile, explicit launch argv, and optional agent kind. Never infer a command or assistant. |
| F03 | Start a remote agent in a Herdr pane. Run the connector on the management host and OpenCode/tools in AgentCore. |
| F04 | Allocate distinct runtime-session and shell IDs for each new independent agent. |
| F05 | Forward terminal bytes in both directions. Preserve TUI controls, Unicode, paste, and interrupts. |
| F06 | Forward initial dimensions and later resize events, including after reconnect. |
| F07 | Use Herdr's OpenCode recognition and screen-derived lifecycle detection. Report connection health separately. |
| F08 | Save both remote IDs for attachment to the original PTY while it exists. |
| F09 | Retry classified transient connection failures within a bounded window. Re-sign connections. Never replay uncertain launch commands or input. |
| F10 | Distinguish terminal detachment from explicit compute and process stop. |
| F11 | Label saved status as last-known state. Prevent competing local attachments. Report damaged records without hiding healthy records. |
| F12 | Preserve configuration, records, and existing profile snapshots across updates. |
| F13 | Export a compatible launch command for the sample's PATH-based credential wrapper from the runtime component. Preserve initialization and host authentication. |
| F14 | Separate the runtime CDK project, Herdr connector package, and shared contract. Include attribution and avoid research-checkout dependencies. |
| F15 | Use official AWS CDK constructs for image assets, an execution role, and an IAM-authenticated runtime. Export connection data through stack outputs. |
| F16 | Use the execution role and a refreshable SDK provider for Bedrock. Do not fetch, export, or persist credential snapshots. |
| F17 | Use standard CDK synth/diff/deploy/destroy and CloudFormation state. Declare model permissions needed by surviving sessions. Do not overwrite connector profiles on deployment failure. |
| F18 | Start new agents without a profile picker. Honor CLI/controller override before the saved default. Reject invalid or ambiguous selection before remote work. |

## Lifecycle requirements — next increment

These requirements define the full recovery contract.
Parts of L07 already exist in activity reporting, but independent recovery state and supervision remain planned.

| ID | Requirement |
| --- | --- |
| L01 | Reuse the local connection UUID as the durable binding. Keep Herdr's live-agent identity and naming semantics. |
| L02 | Record runtime ARN, endpoint/version, session ID, shell ID, conversation ID, persistent paths, and current Herdr attachment. |
| L03 | Keep `attach` strict. Add explicit `resume` based on confirmed remote state. A network failure does not prove process death. |
| L04 | Use a configured S3 Files mount. Give independent work separate namespaces by default. Permit deliberate sharing with helper shells or existing projects. |
| L05 | Add idempotent bootstrap and recovery supervision. Checkpoint recoverable state. Do not claim restoration of memory or in-flight tools. |
| L06 | Stop compute without deleting bindings or persistent files. Confirm stop completion before resume. Make file deletion a separate explicit operation. |
| L07 | Track compute, connection, and OpenCode work state separately. Report actual background work through AgentCore health, not socket presence. |
| L08 | Bind recovered work to a pane. Restore the desired name under Herdr's uniqueness and occupant-lifetime rules. Scope pane IDs to the server/session. |
| L09 | Bound provisioning/stop conflict retries. Prevent competing recovery attempts. Multiple managers require coordination beyond a local process lock. |
| L10 | Detect missing state, retention expiry, and incompatible runtime versions before resume. Define backup and migration behavior. |
| L11 | Open additional shells in an existing runtime session. Give agent-detection hints only to panes that run supported agents. |
| L12 | Separate detach, stop-shell/process, and stop-runtime-session. Report whole-session impact. Closing a helper pane must not stop sibling work. |

## Persistent coding-file requirements — next increment

| ID | Requirement |
| --- | --- |
| P01 | Use an S3 Files access point mounted by the runtime. Select mount/root through deployment configuration, without per-user storage provisioning. |
| P02 | Persist repositories, Git metadata, uncommitted changes, configuration, skills, conversation data, recovery metadata, and selected artifacts. |
| P03 | Give each binding a stable persistent root. Reuse it after replacement. A new session ID must not silently reset files. |
| P04 | Support a remote Working Directory within the persistent root, including existing repositories. Keep it distinct from the host pane's directory. |
| P05 | Persist `HOME` or supported tool data directories. Preserve configuration and skill discovery on later launches. |
| P06 | Validate filesystem behavior for tools and OpenCode state, including locking and concurrent access. Keep sockets and PIDs ephemeral. |
| P07 | Check mount readiness and recovery metadata before work. Detach, stop, and uninstall must not delete persistent files. Define deliberate sharing behavior. |

S3 Files is the primary target.
Managed session storage Preview has different retention and isolation rules. Evaluate it separately before any substitution.
See [storage design](DESIGN.md#persistent-coding-files-through-s3-files).

## Cloud management requirements — target deployment

| ID | Requirement |
| --- | --- |
| H01 | Run Herdr's server and connectors on an always-on host. Use EC2 for the first deployment. |
| H02 | Separate EC2 access from connector authentication. Viewer disconnect, sleep, or reboot must not request manager or worker termination. |
| H03 | Install the plugin, dependencies, and profiles on EC2. Use its instance role through the existing SDK/SigV4 path without laptop credential forwarding. |
| H04 | Retain Herdr state, profiles, bindings, and workflow progress outside installations. Define backup and recovery after host replacement. |
| H05 | Supervise Herdr with a service manager. Reconcile remote work after restart before creating replacement attachments. |
| H06 | Run autonomous coordination in AWS. Persist progress and make recovery idempotent. Laptop-side logic cannot progress while the laptop is offline. |
| H07 | Separate management-host recovery from worker recovery. AgentCore idle/max-lifetime limits still apply. |
| H08 | Start with one active manager. Add controller leases before failover or multiple controllers. |
| H09 | For ECS, provide compatible remote access, persistent state, and task-replacement reconciliation. Do not assume ECS Exec implements Herdr's SSH transport. |
| H10 | Avoid operator-managed static SSH keys and long-lived IAM user keys. Separate human access, connector authorization, and worker-role authorization. |

## Design constraints

| ID | Constraint |
| --- | --- |
| C01 | Keep exactly three source components: `agentcore_runtime`, `herdr_plugin`, and `runtime_contract`. Each owns its implementation, tests, and README. Infrastructure uses CDK/npm configuration. |
| C02 | Keep the README goal-focused. Put design, requirements, proposals, and reviews in `docs/`. Keep agent entrypoints at the root. Follow the writing rules in `agent.md`. |
| C03 | Store user data in Herdr's plugin config/state directories, not the installation. |
| C04 | Use the normal AWS credential chain. Never store credentials, signed URLs, or terminal transcripts. |
| C05 | Validate versioned records at storage boundaries. Sync atomic writes and launch intent before sending a command. Reject unsupported versions. |
| C06 | Keep terminal output nonblocking under backpressure. Cancel I/O tasks and restore modes on exit. |
| C07 | Use public Herdr interfaces without a core fork or private protocol. |
| C08 | Keep default tests offline. Cloud tests need an explicitly selected runtime and authorized operations. |
| C09 | Keep orchestration Herdr-native and authorization IAM-based. Exclude Cognito, end-user accounts, and Jindouyun platform dependencies. |

Both applications depend only on the shared contract, not each other.
The Python and TypeScript contract code uses standard libraries and has no operational side effects.
Runtime descriptors exclude credentials and host AWS profile selection.
Every profile requires explicit launch argv. A missing assistant hint selects an ordinary terminal.
Profiles are unreleased; internal version fields do not require backward-compatibility branches.
Named runtime profiles declare commands and accept explicit overrides. `opencode` and `codex` are example settings references, not predefined connector values.
Keep runtime modules directly under their component directory without a duplicate package folder.
Keep root workspace configuration, the Herdr manifest, and CI in their standard locations.

## Prototype boundaries

The current implementation does not provide:

- VPC/S3 Files or gateway infrastructure.
- Automated EC2/ECS management deployment, recovery, or failover.
- Windows terminal support.
- Automatic conversation resume or compute recovery.
- Automatic attachment after a Herdr server restart.
- Authoritative OpenCode lifecycle events in Herdr.
- Remote execution of Herdr's local Git/worktree/file actions.
- First-party endorsement or automatic publication.

Cognito, per-user runtime authorization catalogs, DynamoDB customer registries, and Jindouyun control-plane integration remain outside product scope.

## Acceptance criteria

| Area | Required outcome | Current evidence |
| --- | --- | --- |
| Plugin contract | Herdr accepts the manifest and declared entrypoints. | Offline and isolated Herdr 0.9.5 tests pass. Earlier cloud new/attach/stop actions passed. |
| New-agent selection | Use explicit override or saved default without a picker. | Offline precedence, required-default, and snapshot tests pass. Earlier two-profile cloud test passed. |
| Owned runtime | Deploy the image, call Bedrock through its role, and connect. | Earlier creation/update, model, process-environment, attachment, and cleanup tests passed. |
| Safe updates | Review CDK differences, retain required model access declaratively, and register resolved outputs after success. | CDK assertion tests cover resources, scoped policy, and outputs. Earlier custom-provisioner tests are historical evidence only. |
| Runtime lifecycle | Report actual work and document per-session limits. | Deployed values are 900 seconds idle and 28,800 seconds maximum, without persistent storage. Full expiry tests remain pending. |
| Waiting for input | Report idle only when no other tracked work runs. Resume busy reporting after a reply. | A fresh cloud question/reply cycle passed on this revision. Local tests cover concurrent tools, nested tasks, permission requests, errors, and unknown children. |
| Terminal transport | Preserve bytes and resize. Keep detach responsive under output pressure. Restore modes. | Earlier cloud I/O/resize passed. Current PTY tests cover backpressure, partial writes, and closed-descriptor cleanup. |
| Session identity | Reuse original IDs without a second launch. | Earlier same-PID attachment and context-aware follow-up passed. Current offline tests preserve identity on retry. |
| Failure handling | Do not replay uncertain input. Stop retrying after takeover. Refuse a replacement PTY after launch. | Offline tests pass, including classified retryable conflicts. |
| Storage and updates | Retain snapshots and extra record fields. Isolate damaged records. Prevent competing attachment. | Offline validation, locking, timezone ordering, and file/directory sync tests pass. Managed install/update remains pending. |
| Real cloud workflow | Support prompts, result collection, attachment, and explicit cleanup. | Five agents completed concurrent retrieval/translation and follow-ups. Dialog and forced-outage coverage remains incomplete. |
| Small viewport | Do not misidentify a failed TUI as healthy or send uncontrolled input. | Gap: 35×20 crashes on the tested OpenCode/Bun version. Zooming is a workaround; the complete safe boundary is unknown. |
| Platform compatibility | Pass on supported macOS/Linux and Python versions. | macOS/Python 3.13 tested locally. Remote CI matrix execution remains pending. |
| Clean execution | Give new independent work fresh compute and a separate namespace. Preserve selected existing files. | Remote IDs are independent. Persistent-home integration is pending. |
| Runtime credentials | Refresh temporary role credentials without stored snapshots. | Fresh model calls and credential-presence checks passed. Full credential rollover remains unverified. |
| Process recovery | Restore the same binding and conversation in a replacement process/PTY. | Manually verified while compute survived. No automated resume action. |
| Compute recovery | Restore files and conversation after confirmed compute stop. | Not implemented. |
| Herdr rebinding | Attach recovered work and respect live-name uniqueness. | Not implemented. |
| Recovery failure | Reject missing/incompatible state and prevent duplicate recovery. | Not implemented. |
| Laptop independence | Continue cloud work during laptop sleep/reboot and reconnect to the same agent. | EC2 deployment and validation pending. |
| Cloud coordination | Advance a cloud workflow while the laptop is offline. | Workflow implementation and validation pending. |
| Host recovery | Reconcile retained identities without duplicate workers or actions. | Not implemented. |
| Remote plugin execution | Use the selected cloud server's plugin, configuration, and instance role. | Remote-machine/SSM deployment validation pending. |
| Persistent coding files | Preserve files, configuration, skills, and history across worker replacement. | Not implemented. |
| Remote Working Directory | Start in the selected persistent repository. | Persistent-directory integration pending. |
| Multiple shells | Use separate shell IDs with explicit operation scope. Preserve sibling work. | Not implemented. |

The CDK/profile implementation passed local Python, CDK assertion, image, package-boundary, license, link, and requirement-ID checks.
The `opencode` example was deployed with CDK, imported into the updated connector, and passed fresh cloud activity/model/attachment tests.
The old custom deployment was removed. Later shared-image E2E tests passed for both examples on disposable cloud runtimes.
Both model/attachment flows passed; Codex sandbox/tool execution and work-health reporting remain unqualified.
The following counts describe earlier implementations before the custom provisioner was replaced.

Earlier local validation: 170 offline Python tests passed, with three Docker tests skipped in that run.
All nine image tests then passed against the full image built and pushed by the provisioner, including those three Docker tests.
The provisioner build succeeded after earlier direct builds timed out during public-base metadata resolution.
The updated runtime and default endpoint reached READY.
Fresh cloud probes passed activity, question/reply, role-based inference, default selection, attachment, and conversation continuity.
Both disposable sessions and the isolated Herdr server were stopped. Concurrent/nested-tool dialog cases remain locally tested only.

## Follow-up priorities

1. Extend dialog, forced-outage, layout, and durable-workflow coverage from the tested baseline.
2. Migrate binding records to include persistent paths, conversation IDs, and execution generations.
3. Integrate S3 Files and checkpointing. Validate files, configuration, skills, and database recovery.
4. Deploy one supervised EC2 manager with retained state and an instance role. Test viewer disconnect and laptop sleep.
5. Add explicit resume, host reconciliation, additional shells, and scoped stop operations.
6. Validate managed installation, updates, and the platform matrix before publication.
7. Consider ECS and multi-manager failover after the single-manager contract passes.
