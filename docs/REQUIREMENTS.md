# Requirements

## Objective

Provide a community Herdr plugin for coding agents in AgentCore Runtime.
Separate assistant runtime definitions, terminal connection, and a small shared contract.
The three sample provision profiles select Codex/GPT-5.6 Sol PUBLIC, OpenCode/Kimi PUBLIC, and OpenCode/Kimi with VPC/S3 Files. Their names are references, not a connector enum.
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
- Run connectors on the Herdr server host. Run the selected assistant and its tools in AgentCore.
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
| F03 | Start a remote agent in a Herdr pane. Run the connector on the management host and the selected assistant/tools in AgentCore. |
| F04 | Allocate distinct runtime-session and shell IDs for each new independent agent. |
| F05 | Forward terminal bytes in both directions. Preserve TUI controls, Unicode, paste, and interrupts. |
| F06 | Forward initial dimensions and later resize events, including after reconnect. |
| F07 | Use Herdr's native recognition and screen-derived lifecycle detection for the explicit agent kind. Report connection health separately. |
| F08 | Save both remote IDs for attachment to the original PTY while it exists. |
| F09 | Retry classified transient connection failures within a bounded window. Re-sign connections. Never replay uncertain launch commands or input. |
| F10 | Distinguish terminal detachment from explicit compute and process stop. |
| F11 | Label saved status as last-known state. Prevent competing local attachments. Report damaged records without hiding healthy records. |
| F12 | Preserve configuration, records, and existing profile snapshots across updates. |
| F13 | Export explicit launch argv from the runtime component. Keep image-specific initialization and credential-provider setup in the runtime adapter; preserve host authentication. |
| F14 | Separate the runtime CDK project, Herdr connector package, and shared contract. Include attribution and avoid research-checkout dependencies. |
| F15 | Use official AWS CDK constructs for image assets, an execution role, and an IAM-authenticated runtime. Export connection data through stack outputs. |
| F16 | Use the execution role and a refreshable SDK provider for Bedrock. Do not fetch, export, or persist credential snapshots. |
| F17 | Use standard CDK synth/diff/deploy/destroy and CloudFormation state. Permit sample sessions to switch available Bedrock models without a per-model IAM update. Do not overwrite connector profiles on deployment failure. |
| F18 | Start new agents without a profile picker. Honor CLI/controller override before the saved default. Reject invalid or ambiguous selection before remote work. |
| F19 | Provide a version-pinned common coding toolchain with usable executable/library paths for non-root agent subprocesses. Keep default dependency caches and build state on local runtime storage. |
| F20 | Support generic Python MCP servers through explicit project manifests, lockfiles, and server commands. Rebuild local environments on replacement compute, preserve persistent definitions, and keep setup output off MCP stdout. Do not register a specific server as a production default. |

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

P01 and mount-root startup have an implemented baseline. Cross-session 4 KiB/8 MiB file tests passed.
The remaining requirements cover complete coding-state persistence, not only a writable shared mount.

| ID | Requirement |
| --- | --- |
| P01 | Create one dedicated access point per S3-backed profile at /agent-filesystem/profiles/<profile-name>. Mount and start directly at the profile mount path. Reject access-point sharing between profiles. Manage storage through TypeScript CDK using external networking and a bucket-root filesystem. |
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
Every connection profile requires explicit launch argv. A missing connection assistant hint selects an ordinary terminal.
Profiles are unreleased; internal version fields do not require backward-compatibility branches.
Named provision profiles reference explicit image launch defaults and can override them. Several project profiles can reuse the same OpenCode image.
Require only `inference.modelId` for normal startup selection. OpenCode uses native model metadata; the Codex image defaults to its Runtime provider.
Permit optional `inference.bedrock-endpoint-type` with exactly `"runtime"` or `"mantle"` as an advanced startup override.
Authorize both Runtime and Mantle inference in each sample execution role, independently of startup routing. Keep grants limited to inference and discovery.
Reject invalid explicit values, old field names, and duplicate derived endpoint environment settings. Omit the endpoint environment key when the profile has no override.
Resolve deployment choices from the selected provision profile and component `.env` at the CDK entrypoint.
Pass resolved properties into the stack. Reject per-field context overrides and ignore ambient shell variables for profile bindings.
Use the authenticated CDK Toolkit for account identity. Keep credentials outside deployment files.
The filesystem worker uses access-point-only permissions. The infrastructure service role uses the bucket configuration from `.env`.
CDK creates profile access points and passes their generated ARNs to runtimes. Users do not supply access-point ARNs.
Do not create or delete the external VPC, subnets, security groups, or bucket. The filesystem uses the bucket root; access points select profile folders.
New profile roots start empty; copying existing data is a separate explicit operation.
Keep runtime modules directly under their component directory without a duplicate package folder.
Keep root workspace configuration, the Herdr manifest, and CI in their standard locations.
Keep project `LICENSE` and `NOTICE` sources only at the repository root. Package and image builds must include their contents without maintaining source copies in each component.
The supplied `/app/run.sh` executes the selected image's `/app/run.py`; shared startup code is an imported helper library.

## Prototype boundaries

The current implementation does not provide:

- Gateway or network infrastructure. TypeScript CDK manages storage and dedicated profile access points using external network bindings.
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
| Plugin contract | Herdr accepts the manifest and declared entrypoints. | Offline and isolated Herdr 0.9.5 tests pass. All three current profiles opened two interactive sessions each. The latest Codex probe passed new/attach/stop. |
| New-agent selection | Use explicit override or saved default without a picker. | Offline precedence, required-default, and snapshot tests pass. The latest six-session check used explicit profiles; the isolated Codex probe verified default selection. |
| Owned runtime | Deploy the image, call Bedrock through its role, and connect. | All three current profiles passed CDK deploy with no changes and reached READY. Sol and both Kimi profiles passed real model/tool calls. |
| Safe updates | Review CDK differences, keep sample model invocation independent of the selected model, and register resolved outputs after success. | CDK tests cover invocation-only permissions, scoped storage/trust, and outputs. Earlier custom-provisioner tests are historical evidence only. |
| Runtime lifecycle | Report actual work and document per-session limits. | All profiles use 900 seconds idle and 28,800 seconds maximum. The filesystem profile mounts S3 Files. OpenCode has activity health; Codex has readiness only. Full expiry tests remain pending. |
| Waiting for input | Report idle only when no other tracked work runs. Resume busy reporting after a reply. | Both rebuilt OpenCode deployments passed fresh cloud question/wait/reply and process-death health probes. Local tests cover concurrent tools, nested tasks, permission requests, errors, and unknown children. |
| Terminal transport | Preserve bytes and resize. Keep detach responsive under output pressure. Restore modes. | Earlier cloud I/O/resize passed. Current PTY tests cover backpressure, partial writes, and closed-descriptor cleanup. |
| Session identity | Reuse original IDs without a second launch. | All three rebuilt profiles passed attachment and context-aware follow-up. Earlier same-PID checks and current offline identity-preservation tests also passed. |
| Failure handling | Do not replay uncertain input. Stop retrying after takeover. Refuse a replacement PTY after launch. | Offline tests pass, including classified retryable conflicts. |
| Storage and updates | Retain snapshots and extra record fields. Isolate damaged records. Prevent competing attachment. | Offline validation, locking, timezone ordering, and file/directory sync tests pass. Managed install/update remains pending. |
| Real cloud workflow | Support prompts, result collection, attachment, and explicit cleanup. | Six current-profile sessions completed date and folder-access requests in three tabs and were left open for the user. Separate disposable probes cleaned up their files/sessions. Dialog and forced-outage coverage remains incomplete. |
| Small viewport | Do not misidentify a failed TUI as healthy or send uncontrolled input. | Gap: 35×20 crashes on the tested OpenCode/Bun version. Zooming is a workaround; the complete safe boundary is unknown. |
| Platform compatibility | Pass on supported macOS/Linux and Python versions. | macOS/Python 3.13 tested locally. Remote CI matrix execution remains pending. |
| Clean execution | Give new independent work fresh compute and a separate namespace. Preserve selected existing files. | Remote IDs are independent. The filesystem sessions share one mount root; automatic per-binding namespaces and persistent home remain pending. |
| Runtime credentials | Refresh temporary role credentials without stored snapshots. | Fresh model calls and credential-presence checks passed. Full credential rollover remains unverified. |
| Model switching | Select another compatible model without a model-ID IAM update. | Model-only profiles permit both endpoints. Both OpenCode profiles passed fresh Runtime/Mantle calls and same-conversation Kimi-to-Astra recall. Mixed-history continuation on Mantle GPT-OSS returned HTTP 400. Codex encrypted-history conversion and regional model availability remain limits. |
| Process recovery | Restore the same binding and conversation in a replacement process/PTY. | Manually verified while compute survived. No automated resume action. |
| Compute recovery | Restore files and conversation after confirmed compute stop. | Not implemented. |
| Herdr rebinding | Attach recovered work and respect live-name uniqueness. | Not implemented. |
| Recovery failure | Reject missing/incompatible state and prevent duplicate recovery. | Not implemented. |
| Laptop independence | Continue cloud work during laptop sleep/reboot and reconnect to the same agent. | EC2 deployment and validation pending. |
| Cloud coordination | Advance a cloud workflow while the laptop is offline. | Workflow implementation and validation pending. |
| Host recovery | Reconcile retained identities without duplicate workers or actions. | Not implemented. |
| Remote plugin execution | Use the selected cloud server's plugin, configuration, and instance role. | Remote-machine/SSM deployment validation pending. |
| Persistent coding files | Preserve files, configuration, skills, and history across worker replacement. | S3 Files mount/startup and 4 KiB/8 MiB file persistence across separate sessions passed after the AWS directory-marker repair. Configuration/skills migration and conversation checkpoints remain pending. |
| Remote Working Directory | Start in the selected persistent repository. | Profile-selected working directory and mount-root startup are implemented. Both filesystem sessions started in `/mnt/workspace`. Per-binding repository selection and recovery remain pending. |
| Multiple shells | Use separate shell IDs with explicit operation scope. Preserve sibling work. | Not implemented. |

### Latest verification — 2026-10-20

The latest user-confirmed fresh deployment removed and recreated all runtime/storage stacks while retaining external network resources and S3 data.
All new Runtime/DEFAULT endpoints are version 1 and READY. Both ARM64 builds, 236 Python tests, 29 CDK tests, and cross-session S3 persistence passed.
Six independent user sessions in three tabs completed real time and directory checks and were left open. Final deployment diffs were clean.

The final reviewed version was deployed after the superseded runtime/storage stacks were removed. All five deployed stacks are `CREATE_COMPLETE`; all three Runtime/DEFAULT versions are 1 and READY.
The separately authorized network egress stack restores internet access while the storage stack remains network-independent.
Both ARM64 builds, 235 Python tests, 30 CDK tests, and all three Herdr E2E flows passed. Native model, shell, tool/build/install, MCP, OpenCode activity, and Codex sandbox checks passed.
S3 verification covered profile-directory startup, cross-session files, MCP environment reconstruction, and distinct configuration discovery for two directories sharing one access point.
That shared-directory test does not claim access isolation. All disposable sessions received stop requests and only test files were removed. Final stack diffs were clean.

Earlier same-day results:

TypeScript CDK adoption preserved all 23 original sample infrastructure resources. The infrastructure and S3 runtime stacks reached `UPDATE_COMPLETE`.
The S3 runtime/DEFAULT version 5 uses a generated profile-specific access point and an empty root. Other runtimes remain at version 4.
Two disposable sessions verified empty-root startup, no inherited MCP servers, a non-root 4 KiB write, and a matching cross-session read. Cleanup restored an empty root.
All 26 CDK tests passed, including two-profile access-point/root/IAM separation. A live second-profile isolation check remains unqualified.
The default Python run passed 212 tests with 18 opt-in skips. Final CDK diffs and the privacy audit were clean.

The final coding-tool images reached Runtime/DEFAULT version 4 and READY on all three existing profiles.
The diffs changed only container images. Both ARM64 builds, 230 Python tests, and 22 CDK tests passed.
Fresh sessions passed tool discovery, native builds, non-root CLI installation, and generic MCP initialization/discovery/tool calls.
Both OpenCode profiles completed model-driven calls to the disposable MCP server. Codex passed its native sandbox and model-driven shell check.
A second S3-backed runtime rebuilt the MCP environment from unchanged persistent definitions. Cleanup removed only the probe files.
This verifies F19/F20 for the tested tools and fixture. It does not implement per-binding allocation or conversation recovery.

### Launcher verification — 2026-10-19

Both ARM64 builds, TypeScript, 21 CDK tests, and all 217 Python tests passed for the launcher and root-legal-file revision.
The image-only update reached Runtime/DEFAULT version 2 and READY on all three profiles, preserving ARNs and the absence of an endpoint override.
All three interactive E2E flows, both OpenCode activity probes, and the Codex sandbox probe passed. Six replacement sessions returned date and folder-access results.
Separate-session storage checks verified matching 4 KiB and 8 MiB files, then removed the probe's files and requested stop for its three sessions.
The six user-requested interactive sessions were left open. Codex work-health and broader tool/approval cases remain unqualified.
The updated Codex deployment reached Runtime/DEFAULT version 2 with GPT-5.6 Sol on native Bedrock Runtime in Ireland.
Fresh sessions passed model inference, sandbox isolation, runtime-role checks, attachment, a context-preserving follow-up, and a real `date` tool call.
Both Ireland retention settings were verified as `default`; the rebuild did not change account retention controls.
All disposable probe sessions received stop requests. Isolated Herdr servers stopped, and all three final CDK diffs showed no changes.
Deployed launcher and legal-file contents matched the source hashes. The first PUBLIC Kimi question wait exceeded 30 seconds; a fresh retry passed.
See the [runtime validation record](../src/agentcore_runtime/README.md#current-validation) for exact test scope.

### Historical validation

The old custom deployment was removed. Earlier shared-image deployments passed model/attachment tests for both assistant kinds and activity tests for OpenCode.
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
3. Extend the verified S3 Files mount with per-binding paths and checkpointing. Validate coding tools, configuration, skill discovery, and database recovery.
4. Deploy one supervised EC2 manager with retained state and an instance role. Test viewer disconnect and laptop sleep.
5. Add explicit resume, host reconciliation, additional shells, and scoped stop operations.
6. Validate managed installation, updates, and the platform matrix before publication.
7. Consider ECS and multi-manager failover after the single-manager contract passes.
